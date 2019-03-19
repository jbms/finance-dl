"""Retrieves Google employee payroll statements from Ultipro in PDF format.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Ultipro website.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'username'` and `'password'`
  keys.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the PDF pay statements will be written.  If the
  directory does not exist, it will be created.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.

- `headless`: Optional.  If specified, must be a `bool`.  Defaults to `True`.
  Indicates whether to use a headless browser.  Scraping appears to be more
  reliable when this is set to `True`.

Output format:
==============

Each pay statement is downloaded in PDF format and saved to the
`output_directory` with a filename of `%Y-%m-%d.statement-<id>.pdf`, where
`<id>` is the document number in the "Pay History" list.  In some cases, due to
a bug of some sort, the document number in the "Pay History" list may differ
from the document number included in the actual document.  Such discrepancies
are handled by the `beancount_import.source.ultipro_google` module.

Example:
========

    def CONFIG_google_payroll():
        return dict(
            module='finance_dl.ultipro_google',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'documents', 'Income',
                                          'Google'),

            # profile_dir is optional but recommended.
            profile_dir=os.path.join(profile_dir, 'google_payroll'),

            # Recommended for greater reliability.
            headless=False,
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import datetime
import logging
import os
import re
import urllib.parse
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from atomicwrites import atomic_write
from . import scrape_lib, google_login

logger = logging.getLogger('ultipro')

output_date_format = '%Y-%m-%d'


class Scraper(scrape_lib.Scraper):
    def __init__(self,
                 credentials,
                 output_directory,
                 login_url='https://googlemypay.ultipro.com',
                 netloc_re=r'^([^\.@]+\.)*(ultipro.com|google.com)$',
                 **kwargs):
        super().__init__(**kwargs)
        self.credentials = credentials
        self.login_url = login_url
        self.netloc_re = netloc_re
        self.output_directory = output_directory

    def check_url(self, url):
        result = urllib.parse.urlparse(url)
        if result.scheme != 'https' or not re.fullmatch(self.netloc_re,
                                                        result.netloc):
            raise RuntimeError('Reached invalid URL: %r' % url)

    def check_after_wait(self):
        self.check_url(self.driver.current_url)

    def login(self):
        google_login.login(self, self.login_url)

    def get_next_statement(self,
                           existing_statements=set(),
                           downloaded_statements=set()):
        pay_history, = self.wait_and_return(
            lambda: self.find_element_in_any_frame(
                By.PARTIAL_LINK_TEXT, "Pay History", only_displayed=True))
        pay_history.click()

        def get_statement_table():
            try:
                for table in self.find_elements_in_any_frame(
                        By.TAG_NAME, 'table', only_displayed=True):
                    headings = [
                        x.text.strip()
                        for x in table.find_elements_by_xpath('thead/tr/th')
                    ]
                    if 'Pay Date' in headings and 'Document Number' in headings:
                        return table
            except:
                import traceback
                traceback.print_exc()

        table, = self.wait_and_return(get_statement_table)
        date_format = '%m/%d/%Y'
        for row in table.find_elements_by_xpath('tbody/tr'):
            row_text = [
                x.text.strip() for x in row.find_elements_by_tag_name('td')
            ]
            row_text = [x for x in row_text if x]
            pay_date = row_text[0]
            document_number = row_text[1]
            assert re.fullmatch('[0-9A-Z]+', document_number), document_number
            pay_date = datetime.datetime.strptime(pay_date, date_format).date()
            document_str = 'Document %r : %r' % (pay_date, document_number)
            if (pay_date, document_number) in existing_statements:
                logger.info('  Found in existing')
                continue
            if (pay_date, document_number) not in downloaded_statements:
                logger.info('%s:  Downloading', document_str)
                link = row.find_element_by_tag_name('a')
                link.click()
                download_link, = self.wait_and_return(
                    lambda: self.find_element_in_any_frame(
                        By.XPATH,
                        '//input[@type="image" and contains(@title, "download")]'
                    ))
                download_link.click()
                logger.info('%s: Waiting to get download', document_str)
                download_result, = self.wait_and_return(
                    self.get_downloaded_file)
                name, data = download_result
                if len(data) < 5000:
                    raise RuntimeError(
                        'Downloaded file size is invalid: %d' % len(data))
                output_name = '%s.statement-%s.pdf' % (
                    pay_date.strftime('%Y-%m-%d'), document_number)
                output_path = os.path.join(self.output_directory, output_name)
                with atomic_write(output_path, mode='wb') as f:
                    f.write(data)
                downloaded_statements.add((pay_date, document_number))
                return True
            else:
                logger.info('%s: Just downloaded', document_str)
        return False

    def get_existing_statements(self):
        existing_statements = set()
        if os.path.exists(self.output_directory):
            for name in os.listdir(self.output_directory):
                m = re.fullmatch(
                    r'([0-9]{4})-([0-9]{2})-([0-9]{2})\.statement-([0-9A-Z]+)\.pdf',
                    name)
                if m is not None:
                    date = datetime.date(
                        year=int(m.group(1)),
                        month=int(m.group(2)),
                        day=int(m.group(3)))
                    statement_number = m.group(4)
                    existing_statements.add((date, statement_number))
                    logger.info('Found existing statement %r %r', date,
                                statement_number)
                else:
                    logger.warning(
                        'Ignoring extraneous file in existing statement directory: %r',
                        os.path.join(self.output_directory, name))
        return existing_statements

    def download_statements(self):
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        existing_statements = self.get_existing_statements()
        downloaded_statements = set()
        while self.get_next_statement(
                existing_statements=existing_statements,
                downloaded_statements=downloaded_statements,
        ):
            pass

    def run(self):
        self.login()
        self.download_statements()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
