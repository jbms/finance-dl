"""Retrieves PDF documents from https://www.stockplanconnect.com.

These PDF documents can be parsed by extracting the text using `pdftotext`.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Stockplanconnect website.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'username'` and `'password'`
  keys.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the documents will be saved.  If the directory does not
  exist, it will be created.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.

- `headless`: Must be set to `False` currently, as this scraper does not work
  properly when run with a headless browser.

Output format:
==============

Each document is saved to the `output_directory` with a name like:

    2017-02-09.Restricted_Units.Trade_Confirmations.Confirmation.pdf
    2017-08-30.Restricted_Units.Trade_Confirmations.Release_Confirmation.pdf
    2017-12-31.Other.Tax_Documents.Form_1099.pdf

If there are multiple documents of the same type on the same date, a number is
appended, e.g.:

    2018-05-31.Restricted_Units.Trade_Confirmations.Release_Confirmation.pdf
    2018-06-28.Restricted_Units.Trade_Confirmations.Release_Confirmation.2.pdf
    2018-06-28.Restricted_Units.Trade_Confirmations.Release_Confirmation.3.pdf

Example:
========

    def CONFIG_stockplanconnect():
        return dict(
            module='finance_dl.stockplanconnect',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'stockplanconnect'),
            headless=False,
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import urllib.parse
import re
import collections
import time
import logging
import os

import dateutil.parser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys

from finance_dl import scrape_lib

logger = logging.getLogger('scraper')

netloc_re = r'^([^\.@]+\.)*stockplanconnect.com|([^\.@]+\.)*morganstanley.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials, output_directory, **kwargs):
        super().__init__(**kwargs)
        self.credentials = credentials
        self.output_directory = output_directory

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        logger.info('Initiating log in')
        self.driver.get('https://www.stockplanconnect.com')
        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        time.sleep(2.0)
        username.click()
        time.sleep(2.0)
        logger.info('Entering username')
        username.send_keys(self.credentials['username'])
        username.click()
        time.sleep(2.0)
        logger.info('Entering password')
        password.click()
        time.sleep(1.0)
        password.send_keys(self.credentials['password'])
        time.sleep(1.0)
        with self.wait_for_page_load():
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')

    def get_output_path(self, parts, index):
        journal_date_format = '%Y-%m-%d'
        date = dateutil.parser.parse(parts[0])

        def sanitize(x):
            x = x.replace(' ', '_')
            x = re.sub('[^a-zA-Z0-9-_.]', '', x)
            return x

        suffix = ''
        if index != 1:
            suffix = '.%d' % index

        return os.path.join(
            self.output_directory,
            '%s.%s.%s.%s%s.pdf' % (date.strftime(journal_date_format),
                                   sanitize(parts[1]), sanitize(parts[2]),
                                   sanitize(parts[3]), suffix))

    def get_documents(self):
        logger.info('Looking for documents link')
        documents, = self.wait_and_locate((By.PARTIAL_LINK_TEXT, 'Documents'))
        scrape_lib.retry(lambda: self.click(documents), num_tries=3,
                         retry_delay=5)
        self.download_documents()

    def download_documents(self):
        logger.info('Looking for PDF links')
        links, = self.wait_and_return(
            lambda: self.driver.find_elements(By.LINK_TEXT, 'PDF'))
        links = list(links)[::-1]
        previously_seen_parts = collections.Counter()
        for link in links:
            cur_el = link
            output_path = None
            while True:
                try:
                    parent = cur_el.find_element_by_xpath('..')
                except:
                    break
                if parent == cur_el:
                    break
                full_text = parent.text
                parts = full_text.split('\n')
                if len(parts) == 5:
                    try:
                        key = tuple(parts)
                        index = previously_seen_parts[key] + 1
                        previously_seen_parts[key] += 1
                        output_path = self.get_output_path(parts, index)
                        break
                    except:
                        logger.info('Failed to determine output filename %r',
                                    parts)
                        break
                else:
                    cur_el = parent
            if output_path is None:
                logger.info('skipping link due to no date')
                continue
            if os.path.exists(output_path):
                logger.info('skipping existing file: %r', output_path)
                continue

            self.click(link)
            logger.info('Waiting for download')
            download_result, = self.wait_and_return(self.get_downloaded_file)

            if not os.path.exists(self.output_directory):
                os.makedirs(self.output_directory)

            tmp_path = output_path + '.tmp'
            with open(tmp_path, 'wb') as f:
                download_data = download_result[1]
                f.write(download_data)
            os.rename(tmp_path, output_path)
            logger.info("Wrote %s", output_path)

    def run(self):
        self.login()
        self.get_documents()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
