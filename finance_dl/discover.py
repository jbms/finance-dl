"""Retrieves transaction and balance information from Discover.
Logs into the web interface, downloads an OFX file.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Discover website.

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

Output format:
==============

OFX file.

Example:
========

    def CONFIG_discover():
        return dict(
            module='finance_dl.discover',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'discover'),
            profile_dir=profile_dir,
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
import shutil
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from . import scrape_lib


logger = logging.getLogger('discover_scrape')

netloc_re = r'^([^\.@]+\.)*discover.com$'
XPATH_OF_LAST_FOUR_DIGITS = '//a[text() = "Card Details (ending "]/*'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials: dict, output_directory: str, **kwargs):
        super().__init__(use_seleniumrequests=True, **kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        os.makedirs(self.output_directory, exist_ok=True)

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def find_account_last4(self):
        return self.driver.find_element(By.XPATH, XPATH_OF_LAST_FOUR_DIGITS).text

    def login(self):
        try:
            account = self.driver.find_element(By.XPATH, XPATH_OF_LAST_FOUR_DIGITS)
            logger.info("Already logged in")
        except NoSuchElementException:
            logger.info('Initiating log in')
            url = "https://portal.discover.com/customersvcs/universalLogin/ac_main"
            self.driver.get(url)

            (username, password), = self.wait_and_return(
                self.find_username_and_password_in_any_frame)
            logger.info('Entering username and password')
            username.clear()
            password.clear()
            username.send_keys(self.credentials['username'])
            password.send_keys(self.credentials['password'])
            with self.wait_for_page_load(timeout=30):
                password.send_keys(Keys.ENTER)
            self.check_after_wait()
            logger.info('Logged in')
            account = self.wait_and_return(self.find_account_last4, timeout=7)[0]
        if len(account) != 4:
            raise Exception("{}: Either identified tag is not the account number, or they've changed its format.".format(account))
        self.account_name = account

    def download_ofx(self):
        # Downloads all transactions in current calendar year
        this_year = datetime.date.today().year
        start_date = datetime.datetime.strptime(str(this_year), '%Y')
        end_date = datetime.datetime.strptime(str(this_year + 1), '%Y')
        logging.info('Fetching history for all of {}'.format(this_year))
        fname = "Discover-{}.ofx".format(this_year)
        # Example URL:
        # https://card.discover.com/cardmembersvcs/ofxdl/ofxWebDownload?stmtKey=W&startDate=20191014&endDate=20191014&fileType=QFX&bid=9625&fileName=Discover-RecentActivity-20191014.qfx
        qfx_url = "https://card.discover.com/cardmembersvcs/ofxdl/ofxWebDownload?stmtKey=W&startDate={}&endDate={}&fileType=QFX&bid=9625&fileName={}"
        qfx_url = qfx_url.format(start_date.strftime('%Y%m%d'), end_date.strftime('%Y%m%d'), fname) 
        logging.info("Downloading from URL: {}".format(qfx_url))
        response = self.driver.request('GET', qfx_url)
        response.raise_for_status()
        account_folder = os.path.join(self.output_directory, self.account_name)
        os.makedirs(account_folder, exist_ok=True)
        with open(os.path.join(account_folder, fname), 'wb') as fout:
            fout.write(response.content)
        logging.info('Success')

    def run(self):
        self.login()
        self.download_ofx()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
