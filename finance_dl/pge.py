"""Retrieves Pacific Gas and Electric (PG&E) PDF bills.

These PDF bills can be parsed by extracting the text using `pdftotext`.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Stockplanconnect website.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'username'` and `'password'`
  keys.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the bills will be saved.  If the directory does not
  exist, it will be created.

- `stop_early`: Optional.  Must be a `bool` that specifies whether to stop after
  the most recent already-present bill is downloaded.  Defaults to `True`.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.

Output format:
==============

Each statement is saved to the `output_directory` with a name like:

    2017-11-28.bill.pdf

The date corresponds to the "Statement Date" of the bill.

Example:
========

    def CONFIG_pge():
        return dict(
            module='finance_dl.pge',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'pge'),
        )


Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import re
import datetime
import logging
import os
import urllib.parse

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys

from . import scrape_lib

logger = logging.getLogger('pge_scrape')

netloc_re = r'^([^\.@]+\.)*pge.com$'


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


class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials, output_directory, stop_early=True, **kwargs):
        super().__init__(**kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        self.stop_early = stop_early
        self.logged_in = False

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        if self.logged_in:
            return
        logger.info('Initiating log in')
        self.driver.get('https://m.pge.com/')

        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        password.send_keys(Keys.ENTER)
        self.wait_and_return(lambda: self.find_visible_elements(By.ID, 'arrowBillPaymentHistory'))
        logger.info('Logged in')
        self.logged_in = True

    def get_output_path(self, output_dir, date):
        journal_date_format = '%Y-%m-%d'
        return os.path.join(
            output_dir, '%s.bill.pdf' % (date.strftime(journal_date_format)))

    def process_download(self, download_result, output_dir):
        logger.info('Got download: %s' % download_result[0])
        m = re.fullmatch(r'.*custbill([0-9]{2})([0-9]{2})([0-9]{4})\.pdf',
                         download_result[0])
        if not m:
            logger.error('Failed to determine date from downloaded file: %s' %
                         download_result[0])
            return True
        else:
            date = datetime.date(
                year=int(m.group(3)), month=int(m.group(1)), day=int(
                    m.group(2)))
            new_path = self.get_output_path(output_dir, date)
            if os.path.exists(new_path):
                logger.info('Skipping duplicate download: %s', date)
                return False
            tmp_path = new_path.replace('.pdf', '.tmp.pdf')
            with open(tmp_path, 'wb') as f:
                download_data = download_result[1]
                f.write(download_data)
            os.rename(tmp_path, new_path)
            logger.info("Wrote %s", new_path)
            return True

    def do_download_from_link(self, link, output_dir):
        scrape_lib.retry(lambda: self.click(link), retry_delay=2)
        logger.info('Waiting for download')
        download_result, = self.wait_and_return(self.get_downloaded_file)
        return self.process_download(download_result, output_dir)

    def get_bills(self, output_dir):
        logger.info('Sending escape')
        actions = ActionChains(self.driver)
        actions.send_keys(Keys.ESCAPE)
        actions.perform()
        logger.info('Looking for download link')
        (bills_link, ), = self.wait_and_return(lambda: self.find_visible_elements(By.ID, 'arrowBillPaymentHistory'))
        scrape_lib.retry(lambda: self.click(bills_link), retry_delay=2)
        (more_link, ), = self.wait_and_return(lambda: self.find_visible_elements(By.ID, 'href-view-24month-history'))
        scrape_lib.retry(lambda: self.click(more_link), retry_delay=2)
        links, = self.wait_and_return(lambda: self.find_visible_elements(By.CSS_SELECTOR, ".utag-bill-history-view-bill-pdf"))

        for link in links:
            if not self.do_download_from_link(link, output_dir) and self.stop_early:
                break

    def run(self):
        self.login()
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.get_bills(self.output_directory)


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
