"""Retrieves transaction and balance information from RadiusBank.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the RadiusBank website. It downloads all transactions in the current year, overwritting the file containing those, if it exists. 
If it's been less than 10 days since New Year's, it will download the previous year's transactions as well, in case some pending transactions got posted.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'username'`, `'password'` and 'account_id`
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

QFX file.

Example:
========

    def CONFIG_radius():
        return dict(
            module='finance_dl.radius',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
                'account_uid' : 'XXXXXX-XXXX-XXXX-XXXXXXXXXXXX',
            },
            output_directory=os.path.join(data_dir, 'radius'),

            # profile_dir is optional but highly recommended to avoid having to
            # enter multi-factor authentication code each time.
            profile_dir=os.path.join(profile_dir, 'chrome')
        )


Look up the account_uid by logging into web portal, navigating to the transactions page
and searching the web page source code for the pattern:
 download-url="/accounts/XXXXXX-XXXX-XXXX-XXXXXXXXXXXX"


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

logger = logging.getLogger('radius_scrape')
netloc_re = r'^([^\.@]+\.)*radiusbank.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


standard_date_format = '%m/%d/%Y'

class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials, output_directory, **kwargs):
        super().__init__(**kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.logged_in = False
        if 'account_name' in kwargs.keys():
            logger.info('Account name given: {}'.format(kwargs['account_name']))
            self.account_name = kwargs['account_name']


    def login(self):
        if self.logged_in:
            return
        logger.info('Initiating log in')
        url = "https://banking.radiusbank.com/login"
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

    def download_ofx(self):

        today = datetime.date.today()
        logging.info("Fetching all transactions from this year, {}.".format(today.year))
        url = "https://banking.radiusbank.com/accounts/%s?period=current_year&format=qfx" % self.credentials['account_uid']
        self.driver.get(url)

        dst = os.path.join(self.output_directory, 'RadiusBank - {}.qfx'.format(today.year))
        retries = 10
        while retries > 0:
            downloaded_files = sorted(glob.glob(os.path.join(self.download_dir, '*.qfx')))
            if len(downloaded_files) > 0 and os.path.exists(downloaded_files[-1]):
                shutil.move(downloaded_files[-1], dst)
                logging.info('Moved downloaded file to correct directory.')
                break
            else:
                time.sleep(1)
                retries -= 1
                if retries == 0:
                    logging.info('Unable to find downloaded file.')

        # If New Year's was recent, some pending transactions from last year may have gotten posted
        delta = today - datetime.date(today.year, 1, 1)
        if delta.days < 10:
            last_year = today.year-1
            logging.info("Fetching all transactions from last year, {}.".format(last_year))
            url = "https://banking.radiusbank.com/accounts/%s?period=previous_year&format=qfx" % self.credentials['account_uid']
            self.driver.get(url)

            dst = os.path.join(self.output_directory, 'RadiusBank - {}.qfx'.format(last_year))
            retries = 10
            while retries > 0:
                downloaded_files = sorted(glob.glob(os.path.join(self.download_dir, '*.qfx')))
                if len(downloaded_files) > 0 and os.path.exists(downloaded_files[-1]):
                    shutil.move(downloaded_files[-1], dst)
                    logging.info('Moved downloaded file to correct directory.')
                    break
                else:
                    time.sleep(1)
                    retries -= 1
                    if retries == 0:
                        logging.info('Unable to find downloaded file.')
        logging.info('Success')

    def run(self):
        self.login()
        self.download_ofx()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
