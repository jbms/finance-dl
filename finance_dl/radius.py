"""Retrieves transaction and balance information from RadiusBank.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the RadiusBank website.

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

- `earliest_history_date`: Optional.  If specified, must be a `datetime.date`
  specifying the earliest UTC date for which to retrieve data.

- `max_history_days`: Optional.  If `earliest_history_date` is not specified,
  this must be a positive `int` specifying the number of days of history to
  retrieve, starting from the previous UTC day.  Defaults to `365*4`.  If
  `earliest_history_date` is specified, `max_history_days` has no effect.

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

from IPython import embed

logger = logging.getLogger('radius_scrape')

netloc_re = r'^([^\.@]+\.)*radiusbank.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


standard_date_format = '%m/%d/%Y'

class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials, output_directory,
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
        if 'account_name' in kwargs.keys():
            logger.info('Account name given: {}'.format(kwargs['account_name']))
            self.account_name = kwargs['account_name']

        print(kwargs)

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        if self.logged_in:
            return
        logger.info('Initiating log in')
        url = "https://banking.radiusbank.com/login"
        self.driver.get(url)

        # Click on that stupid button first
        try:
            continue_btn = self.wait_and_return(self.find_continue_button)
            with self.wait_for_page_load():
                continue_btn.click()
        except:
            pass

        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        # In case of autofill
        for i in range(50):
            username.send_keys(Keys.BACK_SPACE)

        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        with self.wait_for_page_load(timeout = 30):
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True

    def find_continue_btn(self):
        for frame in self.for_each_frame():
            try:
                return self.driver.find_element_by_xpath('//button[@class="btn bg--aqua"]')
            except:
                pass
        raise NoSuchElementException()

    def find_download_button(self):
        for frame in self.for_each_frame():
            try:
                return self.driver.find_element_by_xpath('//i[@class="dropdown icon"]')
            except:
                pass
        raise NoSuchElementException()
        

    def find_download_button(self):
        for frame in self.for_each_frame():
            try:
                return self.driver.find_element_by_xpath('//i[@class="dropdown icon"]')
            except:
                pass
        raise NoSuchElementException()
        



    def download_ofx(self):

        downloaded_files = glob.glob(os.path.join(self.output_directory, '*.qfx'))
        dates = []
        for f in downloaded_files:
            match = re.search('20\d\d-\d\d', f)
            try:
                thisDate = datetime.date.strptime(match.group(0), '%Y-%m')
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

        logging.info('Fetching previous months activity.')
        # when downloading from timezone different from bank, there's some uncertainty
        # in the name of file downloaded
        today = datetime.date.today().strftime('%m_%d_%y')
        tomorrow = (datetime.date.today() + datetime.timedelta(1)).strftime('%m_%d_%y')

        url = "https://banking.radiusbank.com/accounts/%s?period=previous_month&format=qfx" % self.credentials['account_uid']
        self.driver.get(url)
        
        src1 = os.path.join(self.download_dir, 'Rewards Checking-{}.qfx'.format(today))
        src2 = os.path.join(self.download_dir, 'Rewards Checking-{}.qfx'.format(tomorrow))
        retries = 10
        while retries > 0:
            if os.path.exists(src1) or os.path.exists(src2):
                src = src1 if os.path.exists(src1) else src2
                break
            else:
                time.sleep(1)
                retries -= 1
 
        if os.path.exists(src):
            days_this_month = datetime.date.today().day
            last_month = datetime.date.today() - datetime.timedelta(days_this_month)
            last_month = last_month.strftime('%Y-%m')
            newfname = 'RadiusBank - {}.qfx'.format(last_month)
            dst = os.path.join(self.output_directory, newfname)
            logging.info('Moving file from {} to {}'.format(src, dst))
            shutil.move(src, dst)
        else:
            logging.info(f"Cannot find previous months file {src}.")

        # Default saved filename is Rewards Checking-11_11_19.qfx
        logging.info('Fetching this months activity.')
        url = "https://banking.radiusbank.com/accounts/%s?period=current_month&format=qfx" % self.credentials['account_uid']
        self.driver.get(url)

        retries = 10
        while retries > 0:
            if os.path.exists(src1) or os.path.exists(src2):
                src = src1 if os.path.exists(src1) else src2
                break
            else:
                time.sleep(1)
                retries -= 1


        if os.path.exists(src):
            this_month = datetime.date.today()
            this_month = this_month.strftime('%Y-%m')
            newfname = 'RadiusBank - {}.qfx'.format(this_month)
            dst = os.path.join(self.output_directory, newfname)
            logging.info('Moving file from {} to {}'.format(src, dst))
            shutil.move(src, dst)
        else:
            logging.info(f"Cannot find this months file {src}.")

        logging.info('Success')

    def run(self):
        self.login()
        self.download_ofx()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
