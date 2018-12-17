"""Retrieves Comcast PDF bills.

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

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.

Output format:
==============

Each statement is saved to the `output_directory` with a name like:

    2017-11-28.bill.pdf

The date corresponds to the "Bill Date" of the bill.

Example:
========

    def CONFIG_comcast():
        return dict(
            module='finance_dl.comcast',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'comcast'),
        )


Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import re
import datetime
import time
import logging
import os
import urllib.parse

import dateutil.parser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys

from . import scrape_lib

logger = logging.getLogger('comcast_scrape')

netloc_re = r'^([^\.@]+\.)*(comcast.com|xfinity.com|comcast.net)$'


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
        self.driver.get('https://customer.xfinity.com/Secure/MyAccount/')

        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        with self.wait_for_page_load():
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True

    def get_output_path(self, output_dir, date):
        journal_date_format = '%Y-%m-%d'
        return os.path.join(
            output_dir, '%s.bill.pdf' % (date.strftime(journal_date_format)))

    def process_download(self, download_result, output_dir, date):
        logger.info('Got download: %s' % download_result[0])
        new_path = self.get_output_path(output_dir, date)
        if os.path.exists(new_path):
            logger.info('Skipping duplicate download: %s', new_path)
            return
        tmp_path = new_path + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(download_result[1])
        os.rename(tmp_path, new_path)
        logger.info("Wrote %s" % new_path)

    def get_bills(self, output_dir):
        logger.info('Looking for bills link')

        def get_bills_link():
            (bills_link, ), = self.wait_and_return(
                lambda: self.find_visible_elements_by_descendant_partial_text('View Bill History', 'span'))
            return bills_link

        bills_link = get_bills_link()

        try:
            continue_link, = self.find_visible_elements_by_descendant_partial_text(
                'Check it out', 'button')
            continue_link.click()
            time.sleep(3.0)  # wait for overlay to go away
            bills_link = get_bills_link()
        except:
            pass

        self.driver.find_element_by_tag_name('body').send_keys(Keys.ESCAPE)
        bills_link.click()

        def get_links():
            links, = self.wait_and_return(
                lambda: self.driver.find_elements(By.XPATH, '//a[starts-with(text(), "View PDF")]'))
            return links

        links = get_links()
        time.sleep(5.0)
        links = get_links()

        for link in links:
            if not link.is_displayed():
                continue
            cur_el = link
            bill_date = None
            while True:
                parent = cur_el.find_element_by_xpath('..')
                if parent == cur_el:
                    break
                try:
                    bill_date = dateutil.parser.parse(parent.text, fuzzy=True)
                    break
                except:
                    cur_el = parent
                    continue
            if bill_date is None:
                print('skipping link due to no bill date')
                continue
            bill_date = bill_date + datetime.timedelta(days=1)
            new_path = self.get_output_path(output_dir, bill_date)
            if os.path.exists(new_path):
                logger.info(
                    "Skipping already-downloaded bill for %s" % bill_date)
            else:
                logger.info('Attempting download of bill for %s' % bill_date)
                link.click()
                logger.info('Waiting for download')
                download_result, = self.wait_and_return(
                    self.get_downloaded_file)
                self.process_download(download_result, output_dir, bill_date)

    def run(self):
        self.login()
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.get_bills(self.output_directory)


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
