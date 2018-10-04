"""Retrieves transaction and balance information from Venmo.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Venmo website.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'username'` and `'password'`
  keys.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the output will be written.  If the directory does not
  exist, it will be created.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.  It is highly recommended to specify a `profile_dir` to avoid
  having to manually enter a multi-factor authentication code each time.

- `earliest_history_date`: Optional.  If specified, must be a `datetime.date`
  specifying the earliest UTC date for which to retrieve data.

- `max_history_days`: Optional.  If `earliest_history_date` is not specified,
  this must be a positive `int` specifying the number of days of history to
  retrieve, starting from the previous UTC day.  Defaults to `365*4`.  If
  `earliest_history_date` is specified, `max_history_days` has no effect.

Output format:
==============

The retrieved transaction and balance information is merged into the
`transactions.csv` and `balances.csv` files within the specified
`output_directory`.  Note that any existing transaction and balance information
in those files is not overwritten; instead, new information is merged in without
introducing duplicates.

The `transactions.csv` file is in the same CSV download format provided directly
from the Venmo website, and has the format:

" ID","Datetime","Type","Status","Note","From","To","Amount (total)","Amount (fee)","Funding Source","Destination"

The `balances.csv` file is created from scraping the HTML and has the format:

"Start Date","End Date","Start Balance","End Balance"

Example:
========

    def CONFIG_venmo():
        return dict(
            module='finance_dl.venmo',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'venmo'),

            # profile_dir is optional but highly recommended to avoid having to
            # enter multi-factor authentication code each time.
            profile_dir=os.path.join(profile_dir, 'venmo'),
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import io
import csv
import urllib.parse
import re
import dateutil.parser
import datetime
import logging
import os
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys

from . import scrape_lib
from . import csv_merge

logger = logging.getLogger('venmo_scrape')

netloc_re = r'^([^\.@]+\.)*venmo.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


balance_field_names = [
    'Start Date', 'End Date', 'Start Balance', 'End Balance'
]

standard_date_format = '%Y-%m-%d'


def parse_csv_date(x):
    return dateutil.parser.parse(
        x, ignoretz=True).replace(tzinfo=datetime.timezone.utc)


class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials, output_directory,
                 earliest_history_date=None, max_history_days=365 * 4,
                 **kwargs):
        """
        @param earliest_history_date: Earliest UTC date for which to retrieve
            transactions and balance information.

        @param max_history_days: Number of days of history to retrieve, starting
            from the previous UTC day, if `earliest_history_date` is not
            specified.
        """
        super().__init__(**kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.transactions_path = os.path.join(output_directory,
                                              'transactions.csv')
        self.balances_path = os.path.join(output_directory, 'balances.csv')
        self.latest_history_date = (
            datetime.datetime.now() - datetime.timedelta(days=1)).astimezone(
                datetime.timezone.utc).date()
        if earliest_history_date is None:
            self.earliest_history_date = self.latest_history_date - datetime.timedelta(
                days=max_history_days)
        else:
            self.earliest_history_date = dateutil.parser.parse(
                earliest_history_date).date()
        self.logged_in = False

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        if self.logged_in:
            return
        logger.info('Initiating log in')
        self.driver.get('https://venmo.com/account/sign-in')

        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        with self.wait_for_page_load():
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True

    def goto_statement(self, start_date, end_date):
        url_date_format = '%m-%d-%Y'
        with self.wait_for_page_load():
            self.driver.get(
                'https://venmo.com/account/statement?end=%s&start=%s' %
                (end_date.strftime(url_date_format),
                 start_date.strftime(url_date_format)))

    def download_csv(self):
        logger.info('Looking for CSV link')
        download_button, = self.wait_and_locate(
            (By.XPATH, '//button[text() = "Download CSV"]'))
        self.click(download_button)
        logger.info('Waiting for CSV download')
        download_result, = self.wait_and_return(self.get_downloaded_file)
        logger.info('Got CSV download')
        return download_result[1]

    def get_balance(self, balance_type):
        try:
            balance_node = self.driver.find_element(
                By.XPATH, '//*[@class="%s"]/child::*[@class="balance-amt"]' %
                balance_type)
            return balance_node.text
        except NoSuchElementException:
            return None

    def get_balances(self):
        def maybe_get_balance():
            start_balance = self.get_balance('start-balance')
            end_balance = self.get_balance('end-balance')
            if start_balance is not None and end_balance is not None:
                return (start_balance, end_balance)
            try:
                error_node = self.driver.find_element(
                    By.XPATH, '//*[@class="account-statement-error"]')
                error_text = error_node.text
                logging.info('Saw error text: %s', error_text)
                if error_text.startswith('Loading'):
                    return None
                return ('unknown', 'unknown')
            except NoSuchElementException:
                return None

        result, = self.wait_and_return(maybe_get_balance)
        return result

    def write_csv(self, csv_result):
        csv_reader = csv.DictReader(
            io.StringIO(csv_result.decode(), newline=''))
        field_names = csv_reader.fieldnames
        rows = list(csv_reader)

        def get_sort_key(row):
            return parse_csv_date(row['Datetime']).timestamp()

        transactions_file = os.path.join(self.output_directory,
                                         'transactions.csv')
        csv_merge.merge_into_file(filename=transactions_file,
                                  field_names=field_names, data=rows,
                                  sort_by=get_sort_key)

    def get_existing_balances(self):
        if not os.path.exists(self.balances_path):
            return []
        with open(self.balances_path, 'r', newline='') as f:
            csv_reader = csv.DictReader(f)
            assert csv_reader.fieldnames == balance_field_names
            return list(csv_reader)

    def get_start_date(self):
        existing_balances = self.get_existing_balances()
        if not existing_balances:
            return self.earliest_history_date
        return max(
            datetime.datetime.strptime(row['End Date'], standard_date_format)
            .date() for row in existing_balances) + datetime.timedelta(days=1)

    def fetch_statement(self, start_date, end_date):
        logging.info('Fetching statement: [%s, %s]',
                     start_date.strftime(standard_date_format),
                     end_date.strftime(standard_date_format))
        self.goto_statement(start_date, end_date)
        start_balance, end_balance = self.get_balances()
        # Write transactions before balance information, to make sure if an error occurs we will retry next time
        if (start_balance, end_balance) != ('unknown', 'unknown'):
            csv_data = self.download_csv()
            self.write_csv(csv_data)
        else:
            logging.info(
                'Skipping fetching transactions CSV because current period has no transactions'
            )
        csv_merge.merge_into_file(
            filename=self.balances_path,
            field_names=balance_field_names,
            data=[{
                'Start Date': start_date.strftime(standard_date_format),
                'End Date': end_date.strftime(standard_date_format),
                'Start Balance': start_balance,
                'End Balance': end_balance,
            }],
            sort_by=lambda row: (row['Start Date'], row['End Date']),
        )

    def fetch_history(self):

        start_date = self.get_start_date()
        logging.info('Fetching history starting from %s',
                     start_date.strftime('%Y-%m-%d'))

        while start_date <= self.latest_history_date:
            end_date = min(self.latest_history_date,
                           start_date + datetime.timedelta(days=89))
            self.fetch_statement(start_date, end_date)
            start_date = end_date + datetime.timedelta(days=1)

    def run(self):
        self.login()
        self.fetch_history()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
