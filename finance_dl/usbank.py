"""Retrieves transaction and balance information from USBank Credit Card.
Specifically works with the REI CC from US Bank. May not work with others if web interface differs.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the USBank website.

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

OFX file.

Example:
========

    def CONFIG_usbank():
        return dict(
            module='finance_dl.usbank',
            account_name='REI - 1234',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'usbank'),

            # profile_dir is optional but highly recommended to avoid having to
            # enter multi-factor authentication code each time.
            profile_dir=os.path.join(profile_dir, 'chrome')
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import io
import urllib.parse
import re
import dateutil.parser
import datetime
import logging
import os, time, shutil, glob, re
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys

from . import scrape_lib

logger = logging.getLogger('usbank_scrape')

netloc_re = r'^([^\.@]+\.)*usbank.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


standard_date_format = '%m/%d/%Y'

class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials, output_directory, account_name,
                 earliest_history_date=None, max_history_days=30,
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
        self.account_name = account_name

        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
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
        print(kwargs)

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        if self.logged_in:
            return
        logger.info('Initiating log in')
        url = "https://onlinebanking.usbank.com/Auth/Login"
        self.driver.get(url)

        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        # In case of autofill
        for i in range(50):
            username.send_keys(Keys.BACK_SPACE)
            password.send_keys(Keys.BACK_SPACE)
        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        with self.wait_for_page_load(timeout = 30):
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True

    def find_account_link_in_any_frame(self):
        for frame in self.for_each_frame():
            try:
                return self.driver.find_element(By.PARTIAL_LINK_TEXT, self.account_name)
            except:
                pass
        raise NoSuchElementException()


    def find_download_page_in_any_frame(self):
        for frame in self.for_each_frame():
            try:
                return self.driver.find_element(By.PARTIAL_LINK_TEXT, "Download Transactions")
            except:
                pass
        raise NoSuchElementException()

        
    def find_date_fields(self):
        for frame in self.for_each_frame():
            try:
                fromDate = self.driver.find_element(By.ID, "FromDateInput")
                toDate = self.driver.find_element(By.ID, "ToDateInput")
                return (fromDate, toDate)
            except:
                pass
        raise NoSuchElementException()


    def find_download_link(self):
        for frame in self.for_each_frame():
            try:
                return self.driver.find_elements(By.ID, "DTLLink")[0]
            except:
                pass
        raise NoSuchElementException()



    def download_ofx(self):
        # Look thru downloaded files to find earliest date we want transactions for
        downloaded_files = glob.glob(os.path.join(self.output_directory, '*.ofx'))
        dates = []
        for f in downloaded_files:
            match = re.search('20\d\d-\d\d-\d\d', f)
            try:
                thisDate = datetime.date.strptime(match.group(0), '%Y-%m-%d')
                dates.append(thisDate)
            except:
                pass
        dates = sorted(dates)

        # Default starting date
        start_date = datetime.date.today() - datetime.timedelta(days=10)
        if len(dates) > 0:
            lastDate = dates[-1]
            logging.info("Latest download date found: {}".format(lastDate.strftime('%Y-%m-%d')))
            # If it's been more than 10 days since last download, use the older date
            # otherwise, download last 10 days
            # this is because pending transactions take ~10 days to get posted
            if datetime.date.today() - lastDate > datetime.timedelta(days=10):
                start_date = lastDate
        else:
            # if no older downloads
            start_date = self.earliest_history_date
                
        logging.info('Fetching history starting from %s', start_date.strftime('%Y-%m-%d'))
        stdt = start_date.strftime('%m/%d/%Y')
        enddt = datetime.date.today().strftime('%m/%d/%Y')

        account_link, = self.wait_and_return(self.find_account_link_in_any_frame)
        logger.info("Opening account page")
        with self.wait_for_page_load():
            account_link.click()


        download_page, = self.wait_and_return(self.find_download_page_in_any_frame)
        logger.info("Opening transaction download frame")
        download_page.click()
        time.sleep(1)    

        (fromDate, toDate), = self.wait_and_return(self.find_date_fields)
        
        logger.info("Setting the date range.")
        date_len = len("01/01/2019") + 5
        for i in range(date_len):
            fromDate.send_keys(Keys.BACK_SPACE)
        for i in range(date_len):
            toDate.send_keys(Keys.BACK_SPACE)
        fromDate.send_keys(stdt)
        toDate.send_keys(enddt)

        download_link, = self.wait_and_return(
            self.find_download_link)
        logger.info("Downloading transactions.")

        try:
            with self.wait_for_page_load(timeout = 8):
                download_link.click()
        except Exception as e:
            print(e)

        # The default filename produced by the USBank portal
        src = os.path.join(self.download_dir, 'export.qfx')
        newfname = 'USBank - {}.ofx'.format(datetime.date.today().strftime('%Y-%m-%d'))
        dst = os.path.join(self.output_directory, newfname)
        logging.info('Moving file from {} to {}'.format(src, dst))
        shutil.move(src, dst)
        logging.info('Success')

    def run(self):
        self.login()
        self.download_ofx()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
