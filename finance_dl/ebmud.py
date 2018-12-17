"""Retrieves East Bay Municipal Utility District (EBMUD) PDF water bills.

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

    def CONFIG_ebmud():
        return dict(
            module='finance_dl.ebmud',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'ebmud'),
        )


Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import re
import logging
import os

import urllib.parse
import dateutil.parser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys

from . import scrape_lib

logger = logging.getLogger('ebmud_scrape')

netloc_re = r'^([^\.@]+\.)*ebmud.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


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
        self.driver.get(
            'https://www.ebmud.com/customers/account/manage-your-account')

        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        with self.wait_for_page_load():
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True

    def get_statements(self):
        logger.info('Looking for statement link')
        statements_link, = self.wait_and_locate((By.LINK_TEXT,
                                                 'View Statements'))
        statements_link.click()

        (statements_table, ), = self.wait_and_return(
            lambda: self.find_visible_elements_by_descendant_partial_text('Statement Date', 'table')
        )
        rows = statements_table.find_elements_by_xpath('tbody/tr/td')
        for row in rows:
            row_text_parts = row.text.split()
            assert len(row_text_parts) == 4
            statement_date = dateutil.parser.parse(row_text_parts[0]).date()
            output_date_format = '%Y-%m-%d'
            statement_path = os.path.join(
                self.output_directory, '%s.bill.pdf' %
                (statement_date.strftime(output_date_format), ))
            if os.path.exists(statement_path):
                logger.info('Skipping existing statement: %s', statement_path)
                continue
            logger.info('Downloading %s', statement_path)
            self.click(row)
            download_result, = self.wait_and_return(self.get_downloaded_file)
            tmp_path = statement_path + '.tmp'
            with open(tmp_path, 'wb') as f:
                f.write(download_result[1])
            os.rename(tmp_path, statement_path)
            logger.info('Wrote %s', statement_path)

    def run(self):
        self.login()
        self.get_statements()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
