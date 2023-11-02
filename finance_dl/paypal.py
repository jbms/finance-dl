"""Retrieves Paypal activity from https://paypal.com.

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

For each Paypal transaction, two files are written to the specified
`output_directory`: `<id>.json` contains a JSON representation of the
transaction as returned by the Paypal server, and `<id>.html` contains an HTML
representation.

For invoices, instead the files `<id>.pdf` and `<id>.invoice.json` are written
to the specified `output_directory`.

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

from typing import List, Any
import urllib.parse
import re
import json
import logging
import datetime
import os
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from requests.exceptions import HTTPError
import jsonschema
from atomicwrites import atomic_write
from . import scrape_lib
from . import google_login

logger = logging.getLogger('paypal')

netloc_re = r'^([^\.@]+\.)*paypal.com$'

transaction_list_schema = {
    '#schema': 'http://json-schema.org/draft-07/schema#',
    'description': 'JSON schema for the transaction list response.',
    'type': 'object',
    'required': ['data'],
    'properties': {
        'data': {
            'type': 'object',
            'required': ['data'],
            'properties': {
                'data': {
                    'type': 'object',
                    'required': ['activity'],
                    'properties': {
                        'activity': {
                            'type': 'object',
                            'required': ['transactions'],
                            'properties': {
                                'transactions': {
                                    'type': 'array',
                                    'items': {
                                        'type': 'object',
                                        'required': ['id'],
                                        'properties': {
                                            'id': {
                                                'type': 'string',
                                                'pattern': r'^[A-Za-z0-9\-]+$',
                                            },
                                        },
                                    }
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}

transaction_details_schema = {
    '#schema': 'http://json-schema.org/draft-07/schema#',
    'description': 'JSON schema for the transaction details response.',
    'type': 'object',
    'required': ['data'],
    'properties': {
        'data': {
            'type': 'object',
            'required': ['amount'],
            'properties': {
                'amount': {
                    'type': 'object',
                },
            },
        },
    },
}


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials: dict, output_directory: str, **kwargs):
        super().__init__(use_seleniumrequests=True, **kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        self.logged_in = False

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def login(self):
        if self.logged_in:
            return

        self.driver.get('https://www.paypal.com/us/signin')
        time.sleep(0.2)
        logger.info('Finding username field')
        username, = self.wait_and_locate((By.XPATH, '//input[@type="email"]'),
                                         only_displayed=True)
        logger.info('Entering username')
        username.clear()
        username.send_keys(self.credentials['username'])
        username.send_keys(Keys.ENTER)
        time.sleep(0.2)
        logger.info('Finding password field')
        password, = self.wait_and_locate(
            (By.XPATH, '//input[@type="password"]'), only_displayed=True)
        logger.info('Entering password')
        password.send_keys(self.credentials['password'])
        with self.wait_for_page_load():
            password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True
        self.csrf_token = None

    def make_json_request(self, url):
        return self.driver.request(
            'GET', url, headers={
                'x-csrf-token': self.get_csrf_token(),
                'accept': 'application/json, text/javascript, */*; q=0.01',
                'x-requested-with': 'XMLHttpRequest',
                'accept-encoding': 'gzip, deflate',
            })

    def get_csrf_token(self):
        if self.csrf_token is not None: return self.csrf_token
        logging.info('Getting CSRF token')
        self.driver.get('https://www.paypal.com/myaccount/transactions/')
        # Get CSRF token
        body_element, = self.wait_and_locate((By.ID, "__APP_DATA__"))
        attribute_object = json.loads(body_element.get_attribute("innerHTML"))
        self.csrf_token = attribute_object["_csrf"]
        return self.csrf_token

    def get_transaction_list(self):
        end_date = datetime.datetime.now().date() + datetime.timedelta(days=2)
        start_date = end_date - datetime.timedelta(days=365 * 10)
        date_format = '%Y-%m-%d'
        logging.info('Getting transaction list')
        url = (
            'https://www.paypal.com/myaccount/transactions/filter?'
            'transactionType=ALL&nextPageToken=&freeTextSearch=&isClearFreeTextSearch=false&'
            'isClearFilterSelection=false&isClientSideFiltering=false&selectedCurrency=ALL&'
            'startDate=%s&endDate=%s' % (start_date.strftime(date_format),
                                         end_date.strftime(date_format)))
        resp = self.make_json_request(url)
        resp.raise_for_status()
        j = resp.json()
        jsonschema.validate(j, transaction_list_schema)
        return j['data']['data']['activity']['transactions']

    def save_transactions(self):
        transaction_list = self.get_transaction_list()
        logging.info('Got %d transactions', len(transaction_list))
        for transaction in transaction_list:
            transaction_id = transaction['id']
            output_prefix = os.path.join(self.output_directory, transaction_id)
            if transaction_id.startswith('INV'):
                pdf_path = output_prefix + '.pdf'
                if not os.path.exists(pdf_path):
                    invoice_url = (
                        'https://www.paypal.com/invoice/payerView/detailsInternal/'
                        + transaction_id + '?printPdfMode=true')
                    logging.info('Retrieving PDF %s', invoice_url)
                    r = self.driver.request('GET', invoice_url)
                    r.raise_for_status()
                    data = r.content
                    with atomic_write(pdf_path, mode='wb', overwrite=True) as f:
                        f.write(data)
                invoice_json_path = output_prefix + '.invoice.json'
                if not os.path.exists(invoice_json_path):
                    with atomic_write(
                            invoice_json_path,
                            mode='w',
                            encoding='utf-8',
                            newline='\n',
                            overwrite=True) as f:
                        f.write(json.dumps(transaction, indent='  '))
                continue
            details_url = (
                'https://www.paypal.com/myaccount/transactions/details/' +
                transaction_id)
            inline_details_url = (
                'https://www.paypal.com/myaccount/transactions/details/inline/'
                + transaction_id)
            html_path = output_prefix + '.html'
            json_path = output_prefix + '.json'
            if not os.path.exists(json_path):
                logging.info('Retrieving JSON %s', inline_details_url)
                json_resp = self.make_json_request(inline_details_url)
                json_resp.raise_for_status()
                j = json_resp.json()
                jsonschema.validate(j, transaction_details_schema)
                with atomic_write(json_path, mode='wb', overwrite=True) as f:
                    f.write(
                        json.dumps(j['data'], indent='  ', sort_keys=True).encode())
            if not os.path.exists(html_path):
                logging.info('Retrieving HTML %s', details_url)
                html_resp = self.driver.request('GET', details_url)
                try:
                    html_resp.raise_for_status()
                except HTTPError as e:
                    # in rare cases no HTML detail page exists but JSON could be extracted
                    # if JSON is present gracefully skip HTML download if it fails
                    if os.path.exists(json_path):
                        # HTML download failed but JSON present -> only log warning
                        logging.warning('Retrieving HTML %s failed due to %s but JSON is already present. Continuing...', details_url, e)
                    else:
                        logging.error('Retrieving HTML %s failed due to %s and no JSON is present. Aborting...', details_url, e)
                        raise e
                with atomic_write(
                        html_path, mode='w', encoding='utf-8',
                        newline='\n', overwrite=True) as f:
                    # Write with Unicode Byte Order Mark to ensure content will be properly interpreted as UTF-8
                    f.write('\ufeff' + html_resp.text)

    def run(self):
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.login()
        self.save_transactions()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
