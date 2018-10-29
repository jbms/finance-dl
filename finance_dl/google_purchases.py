"""Retrieves purchase history from https://myaccount.google.com/purchases.

This contains purchases that have been heuristically extracted from Gmail
messages, and possibly other sources.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Google purchases website.

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
`<id>.json` is a JSON file in the following format:

    {
      "id": "12345678901234567890",
      "payment_processor": "Amazon.com",
      "merchant": null,
      "items": [
        "Item description..."
      ],
      "timestamp": 1506573516000,
      "units": 190.0,
      "currency": "USD"
    }

For some purchases, `items` may be empty, and/or `merchant` may be specified as
a string.

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

from typing import List, Any
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

logger = logging.getLogger('google_purchases')

netloc_re = r'^([^\.@]+\.)*google.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


purchase_data_schema = {
    '#schema':
    'http://json-schema.org/draft-07/schema#',
    'description':
    'JSON schema for the raw data extracted.',
    'type':
    'array',
    'items': [
        {},  # [0]: unknown
        {},  # [1]: unknown
        {},  # [2]: unknown
        {
            'type':
            'array',  # [3]
            'items': [
                {
                    'type': 'array',  # [0]: time periods
                    'items': {
                        '$ref': '#/definitions/timePeriod'
                    },
                },
            ],
        },
    ],
    'definitions': {
        'timePeriod': {
            'type':
            'array',
            'items': [
                {},  # [0]: unknown
                {
                    'type': 'array',  # [1]: purchases in time period
                    'items': {
                        '$ref': '#/definitions/purchase'
                    },
                },
            ],
        },
        'purchase': {
            'type': 'array',
            'items': [
                { # [0]: id
                    'type': 'string',
                    'pattern': '^[0-9]+$',
                },
                { # [1]: misc information
                    'type': 'array',
                    'items': [
                        { 'type': 'string' }, # [0]: payment processor
                        { 'oneOf': [ # [1]: optional merchant information
                            { 'type': 'array',
                              'items': [
                                { 'type': 'string' } # [0]: merchant
                              ],
                            },
                            { 'type': 'null' },
                        ],
                        },
                        {}, # [2]: unknown
                        {}, # [3]: unknown
                        {}, # [4]: unknown
                        {}, # [5]: unknown
                        { # [6]: amount
                            'oneOf': [
                                {
                                    'type': 'array',
                                    'items': [
                                        {  # [0]: units
                                            'oneOf': [
                                            { 'type': 'number' },
                                            { 'type': 'null' },
                                            ],
                                        },
                                        { 'type': 'string', 'pattern': '^[A-Z]{3}$' }, # [1]: currency
                                ],
                                },
                                { 'type': 'null' },
                            ]
                        },
                        { # [7]: unknown
                        },
                    ],
                    'additionalItems': { # Item description
                        'type': 'string',
                    },
                },
                { # [2]: unknown
                },
                { # [3]: unknown
                },
                { # [4]: timestamp (milliseconds)
                    'type': 'number'
                },
            ],
        },
    },
}


def parse_single_raw_purchase(value: Any) -> dict:
    amount = value[1][6]
    if amount is None:
        units = None
        currency = None
    else:
        units = amount[0]
        currency = amount[1]
    return dict(
        id=value[0],
        payment_processor=value[1][0],
        merchant=value[1][1][0] if value[1][1] is not None else None,
        items=value[1][8:],
        timestamp=value[4],
        units=units,
        currency=currency,
    )


def parse_raw_purchase_data(value: Any) -> List[Any]:
    time_periods = value[3][0]
    raw_purchases = []  # type: List[Any]
    for time_period in time_periods:
        raw_purchases.extend(time_period[1])
    return [parse_single_raw_purchase(purchase) for purchase in raw_purchases]



class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials: dict, output_directory: str, **kwargs):
        super().__init__(**kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        self.logged_in = False

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        if self.logged_in:
            return

        google_login.login(self, 'https://myaccount.google.com/purchases')
        self.logged_in = True

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

    def save_purchase_data(self):
        def wait_for_data():
            if self.driver.title != 'Purchases':
                raise NoSuchElementException
            try:
                return self.extract_raw_data()
            except ValueError:
                raise NoSuchElementException
        raw_data, = self.wait_and_return(wait_for_data)
        jsonschema.validate(raw_data, purchase_data_schema)
        purchases = parse_raw_purchase_data(raw_data)
        logger.info('Parsed %d purchases', len(purchases))
        need_to_fetch = []
        for purchase in purchases:
            purchase_id = purchase['id']
            json_path = os.path.join(self.output_directory, purchase_id + '.json')
            if not os.path.exists(json_path):
                with atomic_write(json_path, mode='w') as f:
                    json.dump(purchase, f, indent='  ')
            html_path = os.path.join(self.output_directory,
                                     purchase_id + '.html')
            if os.path.exists(html_path):
                continue
            need_to_fetch.append((purchase_id, html_path))
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
        self.login()
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.save_purchase_data()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
