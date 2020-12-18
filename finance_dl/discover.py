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
  When using Firefox you may encounter the issue that it asks for confirmation
  when downloading the file. You will need to launch Firefox from the profile
  folder, and turn on autosaving for OFX files in settings.

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
            # firefox seems to work better on Discover's website
            profile_dir=os.path.join(profile_dir, 'firefox'),
            firefox=True,
            # such a user agent string is necessary
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4044.122 Safari/537.36 Edg/81.0.416.62"
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
    def __init__(self, credentials, output_directory,
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
        os.makedirs(self.output_directory, exist_ok=True)

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def find_account_last4(self):
        return self.driver.find_element_by_xpath(XPATH_OF_LAST_FOUR_DIGITS).text


    def login(self):
        try:
            account = self.driver.find_element_by_xpath(XPATH_OF_LAST_FOUR_DIGITS)
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

        stdt = start_date.strftime('%Y%m%d')
        enddt = end_date.strftime('%Y%m%d')
        fname = "Discover-{}.ofx".format(this_year)
        # Example URL:
        # https://card.discover.com/cardmembersvcs/ofxdl/ofxWebDownload?stmtKey=W&startDate=20191014&endDate=20191014&fileType=QFX&bid=9625&fileName=Discover-RecentActivity-20191014.qfx
        qfx_url = "https://card.discover.com/cardmembersvcs/ofxdl/ofxWebDownload?stmtKey=W&startDate={}&endDate={}&fileType=QFX&bid=9625&fileName={}"
        qfx_url = qfx_url.format(stdt, enddt, fname)
        logging.info("Downloading from URL: {}".format(qfx_url))
        # this is necessary because otherwise it locks on the get() for a while
        self.driver.set_page_load_timeout(5)
        try:
            self.driver.get(qfx_url)
        except TimeoutException:
            pass
        (fname_, contents), = self.wait_and_return(self.get_downloaded_file)
        logger.info("Found downloaded file: {}".format(fname))
        account_folder = os.path.join(self.output_directory, self.account_name)
        os.makedirs(account_folder, exist_ok=True)
        dst = os.path.join(account_folder, fname)
        with open(dst, 'wb') as fout:
            fout.write(contents)
        logging.info('Success')

    def run(self):
        self.login()
        self.download_ofx()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
