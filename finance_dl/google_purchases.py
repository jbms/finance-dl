"""Retrieves purchase and reservation history from Google.

This contains purchases that have been heuristically extracted from Gmail
messages, and possibly other sources.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Google Takeout and Google purchases/reservations websites.

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
  each time.

Output format:
==============

For each purchase, two files are written to the specified `output_directory`:
`<id>.html` contains the raw HTML content of the order details page, and
`order_<id>.json` is a JSON file in the Google Takeout Purchases/Reservations
format.

Example:
========

    def CONFIG_google_purchases():
        return dict(
            module='finance_dl.google_purchases',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'google_purchases'),
            # profile_dir is optional.
            profile_dir=os.path.join(profile_dir, 'google_purchases'),
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

from typing import List, Any, Tuple
import urllib.parse
import re
import json
import logging
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
import jsonschema
from atomicwrites import atomic_write
from . import scrape_lib
from . import google_login
from . import google_takeout

logger = logging.getLogger('google_purchases')

netloc_re = r'^([^\.@]+\.)*google.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)

class Scraper(google_takeout.Scraper):
    def __init__(self, output_directory: str, **kwargs):
        super().__init__(**kwargs)
        self.output_directory = output_directory

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def extract_raw_data(self):
        source = self.driver.page_source
        prefix = 'data:function(){return '
        start_index = source.index(prefix) + len(prefix)
        source_suffix = source[start_index:]
        try:
            value = json.loads(source_suffix)
            raise ValueError('Expected error parsing JSON')
        except json.JSONDecodeError as e:
            encoded_json = source_suffix[:e.pos]
            value = json.loads(encoded_json)
        return value

    def _fetch_html_pages(self, need_to_fetch: List[Tuple[str, str]]):
        logger.info('Fetching details for %d purchases', len(need_to_fetch))
        for i, (purchase_id, html_path) in enumerate(need_to_fetch):
            url = 'https://myaccount.google.com/purchases/detail?order_id=' + purchase_id
            logger.info('Fetching details %d/%d: %s', i, len(need_to_fetch), url)
            with self.wait_for_page_load():
                self.driver.get(url)
            content = self.driver.page_source
            with atomic_write(html_path, mode='w') as f:
                # Write with Unicode Byte Order Mark to ensure content will be properly interpreted as UTF-8
                f.write('\ufeff' + content)
            logger.info('Write details %d/%d: %s', i, len(need_to_fetch), html_path)

    def run(self):
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)

        self.download_data()

    def download_data(self):
        takeout_zip = self.get_takeout_zipfile(['my_orders'])
        need_to_fetch = []
        for name in takeout_zip.namelist():
            m = re.match(r'.*/order_([0-9]+)\.json$', name)
            if m is None:
                logger.info('Ignoring file in takeout archive: %s', name)
                continue
            order_id = m.group(1)
            json_path = os.path.join(self.output_directory,
                                     'order_' + order_id + '.json')
            if not os.path.exists(json_path):
                with atomic_write(json_path, mode='wb') as f:
                    f.write(takeout_zip.read(name))
            html_path = os.path.join(self.output_directory, order_id + '.html')
            if os.path.exists(html_path):
                continue
            need_to_fetch.append((order_id, html_path))
        self._fetch_html_pages(need_to_fetch)


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
