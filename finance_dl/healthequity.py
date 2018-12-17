"""Retrieves transaction and balance information from HealthEquity.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Venmo website.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'username'` and `'password'`
  keys.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the output will be written.  If the directory does not
  exist, it will be created.  For compatibility with `beancount-import`, the
  last component of the `output_directory` should be your HealthEquity account
  number.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.  It is highly recommended to specify a `profile_dir` to avoid
  having to manually enter a multi-factor authentication code each time.

Output format:
==============

Cash transactions relating to contributions, distributions, and other are saved
to `cash-transactions-contribution.csv`, `cash-transactions-distribution.csv`,
and `cash-transactions-other.csv`, respectively, with the following fields:

    "Date","Transaction","Amount","Cash Balance"

Investment transactions are saved to `investment-transactions.csv` with the
following fields:

    "Date","Fund","Category","Description","Price","Amount","Shares","Total Shares","Total Value"

Investment holdings are saved to files named like
`YYYY-MM-ddTHHMMSSZZZZ.balances.csv`, where the date and time are the date and
time at which the scraper was run.

Example:
========

    def CONFIG_healthequity():
        return dict(
            module='finance_dl.healthequity',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            # Use your HealthEquity account number as the last directory component.
            output_directory=os.path.join(data_dir, 'healthequity', '1234567'),

            # profile_dir is optional but highly recommended to avoid having to
            # enter multi-factor authentication code each time.
            profile_dir=os.path.join(profile_dir, 'healthequity'),
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import urllib.parse
import re
import datetime
import time
import logging
import os
import bs4
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from . import scrape_lib
from . import csv_merge

logger = logging.getLogger('healthequity_scrape')

netloc_re = r'^([^\.@]+\.)*healthequity.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


def find_first_matching_date(lines, date_format):
    for line in lines:
        try:
            return datetime.datetime.strptime(line, date_format).date()
        except:
            pass
    return None


FUND_ACTIVITY_HEADERS = [
    'Fund', 'Name', 'Shares (#)', 'Closing Price', 'Closing Value'
]


def write_balances(data, path):
    rows = []
    for entry in data:
        keys = [x[0] for x in entry]
        if keys == FUND_ACTIVITY_HEADERS:
            row_values = dict(entry)
            row_values['Fund'] = row_values['Fund'].strip().split()[0]
            rows.append(row_values)
    csv_merge.write_csv(FUND_ACTIVITY_HEADERS, rows, path)


def write_fund_activity(raw_transactions_data, path):
    input_date_format = '%m/%d/%Y'
    output_date_format = '%Y-%m-%d'
    soup = bs4.BeautifulSoup(raw_transactions_data.decode('utf-8'), 'lxml')
    headers = [
        'Date', 'Fund', 'Category', 'Description', 'Price', 'Amount', 'Shares',
        'Total Shares', 'Total Value'
    ]
    rows = []
    for row in soup.find_all('tr'):
        cells = [str(x.text).strip() for x in row.find_all('td')]
        while cells and not cells[-1].strip():
            del cells[-1]
        if len(cells) == 1:
            continue
        assert len(cells) == len(headers)
        if cells == headers:
            continue
        row_values = dict(zip(headers, cells))
        row_values['Date'] = datetime.datetime.strptime(
            row_values['Date'], input_date_format).strftime(output_date_format)
        rows.append(row_values)
    csv_merge.merge_into_file(filename=path, field_names=headers, data=rows,
                              sort_by=lambda x: x['Date'])


def write_transactions(raw_transactions_data, path):
    input_date_format = '%m/%d/%Y'
    output_date_format = '%Y-%m-%d'
    soup = bs4.BeautifulSoup(raw_transactions_data.decode('utf-8'), 'lxml')
    headers = ['Date', 'Transaction', 'Amount', 'HSA Cash Balance']
    output_headers = ['Date', 'Transaction', 'Amount', 'Cash Balance']
    rows = []
    for row in soup.find_all('tr'):
        cells = [str(x.text).strip() for x in row.find_all('td')]
        while cells and not cells[-1].strip():
            del cells[-1]
        if len(cells) <= 1:
            continue
        if cells[0] == 'TOTAL':
            continue
        assert len(cells) == len(headers)
        if cells == headers:
            continue
        row_values = dict(zip(headers, cells))
        # Sanitize whitespace in description
        row_values['Transaction'] = ' '.join(row_values['Transaction'].split())
        row_values['Cash Balance'] = row_values.pop('HSA Cash Balance')

        # Sanitize date_str
        date_str = row_values['Date']
        date_str = re.sub('\\(Available .*\\)', '', date_str)

        row_values['Date'] = datetime.datetime.strptime(
            date_str, input_date_format).strftime(output_date_format)
        rows.append(row_values)
    rows.reverse()
    csv_merge.merge_into_file(filename=path, field_names=output_headers,
                              data=rows, sort_by=lambda x: x['Date'])


class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials, output_directory, **kwargs):
        super().__init__(**kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        self.logged_in = False

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        if self.logged_in:
            return
        logger.info('Initiating log in')
        self.driver.get('https://my.healthequity.com/')

        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        with self.wait_for_page_load():
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True

    def download_transaction_history(self):
        (transactions_link, ), = self.wait_and_return(
            lambda: self.find_visible_elements_by_descendant_partial_text('Transaction History', 'td'))
        scrape_lib.retry(transactions_link.click, retry_delay=2)
        (date_select, ), = self.wait_and_return(
            lambda: self.find_visible_elements_by_descendant_partial_text('All dates', 'select'))
        date_select = Select(date_select)
        with self.wait_for_page_load():
            date_select.select_by_visible_text('All dates')

        results = {}
        for transaction_type in ['Contribution', 'Distribution', 'Other']:
            logger.info('Retrieving transaction history of type %s',
                        transaction_type)
            (type_select, ), = self.wait_and_return(
                lambda: self.find_visible_elements_by_descendant_partial_text('All Transaction Types', 'select'))
            type_select = Select(type_select)
            with self.wait_for_page_load():
                type_select.select_by_visible_text(transaction_type)

            (download_link,), = self.wait_and_return(
                lambda: self.find_visible_elements(By.XPATH, '//input[contains(@value,"Download")]'))
            scrape_lib.retry(download_link.click, retry_delay=2)
            # (excel_link,), = self.wait_and_return(
            #     lambda: self.find_visible_elements(By.XPATH, '//input[contains(@name,"Excel")]'))
            # scrape_lib.retry(excel_link.click, retry_delay=2)
            logger.info('Waiting for downloaded transaction history')
            download_result, = self.wait_and_return(self.get_downloaded_file)
            results[transaction_type] = download_result[1]
            self.driver.back()  # undo selection of transaction type
            self.driver.refresh()

        self.driver.back()  # undo selection of "All dates"
        self.driver.back()  # undo selection of "Transaction history"
        self.driver.refresh()

        return results

    def get_investment_balance(self):
        headers = FUND_ACTIVITY_HEADERS
        (table, ), = self.wait_and_return(
            lambda: scrape_lib.find_table_by_headers(self, headers))
        data = scrape_lib.extract_table_data(table, headers)
        return data

    def go_to_investment_history(self):
        logger.info('Going to investment history')
        self.driver.get(
            'https://www.healthequity.com/Member/Investment/Desktop.aspx')

    def download_fund_activity(self):
        logger.info('Looking for fund activity link')
        (fund_activity_link,), = self.wait_and_return(
            lambda: self.find_visible_elements(By.XPATH, '//a[contains(@href, "FundActivity")]'))
        scrape_lib.retry(fund_activity_link.click, retry_delay=2)
        logger.info('Selecting date ranage for fund activity')
        (start_date,), = self.wait_and_return(
            lambda: self.find_visible_elements(By.XPATH, '//input[@type="text" and contains(@id, "dateSelectStart")]'))
        start_date.clear()
        start_date.send_keys('01011900')
        logger.info('Downloading fund activity')
        (download_link, ), = self.wait_and_return(
            lambda: self.driver.find_elements_by_link_text('Download'))
        scrape_lib.retry(download_link.click, retry_delay=2)
        logger.info('Waiting for fund activity download')
        download_result, = self.wait_and_return(self.get_downloaded_file)
        return download_result[1]

    def download_data(self):
        raw_transactions = self.download_transaction_history()
        self.go_to_investment_history()
        raw_balances = self.get_investment_balance()
        raw_fund_activity = self.download_fund_activity()
        return raw_transactions, raw_balances, raw_fund_activity

    def run(self):
        self.login()
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        raw_transactions, raw_balances, raw_fund_activity = self.download_data(
        )
        write_balances(
            raw_balances,
            os.path.join(
                self.output_directory,
                '%s.balances.csv' % time.strftime('%Y-%m-%dT%H%M%S%z')))
        for k, v in raw_transactions.items():
            write_transactions(
                v,
                os.path.join(self.output_directory,
                             'cash-transactions-%s.csv' % (k.lower())))
        write_fund_activity(
            raw_fund_activity,
            os.path.join(self.output_directory, 'investment-transactions.csv'))


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
