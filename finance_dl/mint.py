"""Downloads Mint.com transactions and balance data.

This uses the `mintapi` Python package in conjunction with the `selenium` Python
package and `chromedriver` to scrape the Mint.com website.

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
  each time.  It is highly recommended to specify a `profile_dir` to avoid
  having to manually enter a multi-factor authentication code each time.

- `merge_files`: Optional.  If specified, must be a list of `str` values that
  specify the paths to additional CSV files containing transactions in the same
  format as the `mint.csv` output file.  These files are merged with the
  contents of `mint.csv` into a new file `mint-merged.csv` in the specified
  `output_directory`.

- `skip_refresh`: Optional.  Defaults to `False`.  A value of `True` indicates
  not to wait until all account data has been refreshed.

Output format:
==============

The transactions are saved to a file named `mint.csv` under the specified output
directory.  Balance information is saved to files named
`balances.%Y-%m-%dT%H%M%S%z.csv` under the specified output directory.

Duplicate transactions are excluded from the merged file, in the following way:
since the Mint CSV format lacks any sort of unique transaction identifier,
multiple legitimate transactions may produce identical lines in the CSV file.
Therefore, for each unique CSV line, considering only the 'Date', 'Original
Description', 'Amount', 'Transaction Type', and 'Account Name' fields, the
merged file contains N copies of this line, where N is the maximum number of
times this line occurs in any of the input CSV files.

Example:
========

    def CONFIG_mint():
        return dict(
            module='finance_dl.mint',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'mint'),
            # profile_dir is optional, but highly recommended to avoid having to
            # enter multi-factor authentication code each time.
            profile_dir=os.path.join(profile_dir, 'mint'),
        )

Interactive shell:
==================

From the interactive shell, type:

    run(output_directory=output_directory, profile_dir=profile_dir,
        credentials=credentials)

to run the scraper.

"""

import os
from typing import Sequence, Optional, Dict
import dateutil.parser
import io
import csv
import re
import contextlib
import collections
import urllib.parse
import datetime
import time
import json
import logging
import traceback
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import selenium.common.exceptions

from . import csv_merge
from . import scrape_lib

if False:
    from mintapi import Mint  # for typing only

logger = logging.getLogger('mint')

netloc_re = r'^([^\.@]+\.)*(mint|intuit).com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


class MintTokenScraper(scrape_lib.Scraper):
    def __init__(self, credentials, login_timeout=30, **kwargs):
        super().__init__(use_seleniumrequests=True, **kwargs)
        self.credentials = credentials
        self.login_timeout = login_timeout

    def login(self):
        logger.info('Logging into mint')
        self.driver.get(
            "https://accounts.intuit.com/index.html?offering_id=Intuit.ifs.mint&namespace_id=50000026&redirect_url=https://mint.intuit.com/overview.event"
        )
        logger.info('Waiting to enter username and password')
        (username, password), = self.wait_and_return(
            self.find_username_and_password_in_any_frame)
        logger.info('Entering username and password')
        username.send_keys(self.credentials['username'])
        password.send_keys(self.credentials['password'])
        password.send_keys(Keys.ENTER)
        start_time = time.time()
        while not self.driver.current_url.startswith(
                'https://mint.intuit.com/overview.event'):
            logger.info('Waiting for MFA')
            time.sleep(1)
            cur_time = time.time()
            if self.login_timeout is not None and cur_time > start_time + self.login_timeout:
                raise TimeoutError('Login failed to complete within timeout')

        while True:
            token_element, = self.wait_and_locate((By.NAME, 'javascript-user'))
            value_json = token_element.get_attribute('value')
            logger.info('scraped user data: %r', value_json)
            try:
                value = json.loads(value_json)
                if isinstance(value, dict) and 'token' in value:
                    break
            except ValueError:
                pass
            logger.info('Waiting for token')
            time.sleep(1)
            cur_time = time.time()
            if self.login_timeout is not None and cur_time > start_time + self.login_timeout:
                raise TimeoutError('Login failed to complete within timeout')


@contextlib.contextmanager
def connect(credentials, scraper_args=None):
    import mintapi
    mint = mintapi.Mint()
    scraper_args = dict(scraper_args or {})

    def try_login(scraper):
        scraper = MintTokenScraper(credentials=credentials, **scraper_args)
        scraper.login()
        mint.driver = scraper.driver
        mint.token = mint.get_token()

    with scrape_lib.temp_scraper(MintTokenScraper, credentials=credentials,
                                 **scraper_args) as scraper:
        okay = False
        try:
            try_login(scraper)
            okay = True
        except (TimeoutError, selenium.common.exceptions.TimeoutException):
            if not scraper_args.get('headless') and not scraper_args.get(
                    'login_timeout'):
                raise
            traceback.print_exc()
        if okay:
            yield mint
            return
    scraper_args['headless'] = True
    scraper_args['login_timeout'] = None
    logger.info('Retrying login interactively')
    with scrape_lib.temp_scraper(MintTokenScraper, credentials=credentials,
                                 **scraper_args) as scraper:
        try_login(scraper)
        yield mint


def match_csv_to_json(csv_entry: dict, json_entry: dict):
    json_date = dateutil.parser.parse(json_entry['date'])
    json_csv_entry = {
        'Date':
        '%d/%02d/%d' % (json_date.month, json_date.day, json_date.year),
        'Original Description':
        json_entry['omerchant'],
        'Amount':
        json_entry['amount'].translate({
            ord('$'): None,
            ord(','): None
        }),
        'Transaction Type':
        'debit' if json_entry['isDebit'] else 'credit',
        'Account Name':
        json_entry['account'],
    }
    csv_entry = csv_entry.copy()
    csv_entry.pop('Category', None)
    csv_entry.pop('Description', None)
    csv_entry.pop('Labels', None)
    csv_entry.pop('Notes', None)
    if csv_entry != json_csv_entry:
        raise RuntimeError('CSV entry %r does not match JSON entry %r' %
                           (csv_entry, json_csv_entry))


def get_annotated_transactions(mint: 'Mint', num_attempts: int = 3):
    for attempt_num in range(num_attempts):
        try:
            logger.info('Getting CSV transactions')
            csv_data = mint.get_transactions_csv(
                include_investment=True).decode()
            if len(csv_data) == 0:
                raise RuntimeError('Received empty Mint data')

            logger.info('Getting JSON transactions')
            json_data = mint.get_transactions_json(include_investment=True)

            reader = csv.DictReader(io.StringIO(csv_data, newline=''))
            csv_rows = list(reader)

            if len(csv_rows) != len(json_data):
                raise RuntimeError('CSV data does not match JSON data')

            for csv_entry, json_entry in zip(csv_rows, json_data):
                match_csv_to_json(csv_entry, json_entry)
            break
        except:
            if attempt_num + 1 == num_attempts:
                raise
    return (reader.fieldnames, list(zip(csv_rows, json_data)))


def refresh_mint_data(mint: 'Mint'):
    logger.info('Initiating account refresh')
    mint.initiate_account_refresh()
    # Wait for downloading to be complete
    logger.info('Waiting for accounts to update')
    polling_interval_seconds = 5
    start_time = time.time()
    while True:
        time.sleep(polling_interval_seconds)
        accounts = mint.get_accounts()
        cur_time = time.time()
        pending = []
        ok = []
        other = []
        for account in accounts:
            status = account['fiLoginStatus']
            if status in ['DOWNLOADING_IN_PROGRESS', 'REFRESH_REQUESTED']:
                pending.append(account)
            elif status == 'OK':
                ok.append(account)
            else:
                other.append(account)
        if len(pending) == 0:
            break
        logger.info('[%d seconds] Still downloading: %s',
                    cur_time - start_time, ' '.join(
                        '%r' % account['name'] for account in pending))
    cur_time = time.time()
    logger.info('[%d seconds] Finished updating' % (cur_time - start_time))
    for account in other:
        logger.info('Account %r in state %r', account['name'],
                    account['fiLoginStatus'])


mint_date_format = '%m/%d/%Y'


def get_mint_date(row: dict):
    date = datetime.datetime.strptime(row['Date'], mint_date_format).date()
    return date


def download_mint_data(mint: 'Mint'):
    fieldnames, entries = get_annotated_transactions(mint)
    non_pending_txns = [
        csv_row for csv_row, json_row in entries
        if not json_row['isPending'] and not json_row['isDuplicate']
    ]

    balances = []
    account_max_transaction_date = dict()  # type: Dict[str, datetime.date]
    for csv_row in non_pending_txns:
        date = get_mint_date(csv_row)
        account = csv_row['Account Name']
        prev_date = account_max_transaction_date.get(account)
        if prev_date is None or prev_date < date:
            account_max_transaction_date[account] = date

    account_data = mint.get_accounts()
    for account in account_data:
        account_name = account['name']
        max_date = account_max_transaction_date.get(account_name)
        max_date_str = (max_date.strftime(mint_date_format)
                        if max_date is not None else '')
        balance = account.get('currentBalance', '')
        if account['accountType'] == 'credit':
            # Mint negates credit card balances.
            balance = -balance
        balances.append({
            'Name': account_name,
            'Currency': account.get('currency', ''),
            'Balance': str(balance),
            'Last Updated': str(account.get('lastUpdated', '')),
            'State': account.get('fiLoginStatus', ''),
            'Last Transaction': max_date_str,
        })

    new_csv = io.StringIO(newline='')
    new_csv_data = csv.DictWriter(new_csv, fieldnames=fieldnames,
                                  lineterminator='\n', quoting=csv.QUOTE_ALL)
    new_csv_data.writeheader()
    new_csv_data.writerows(non_pending_txns)

    csv_data = new_csv.getvalue()
    return csv_data, balances


def merge_mint_data(mint_data_list: Sequence[str]):
    fieldnames = None
    merged_counter = collections.Counter()  # type: Dict[tuple, int]
    merged_rows = []
    keep_fields = [
        'Date', 'Original Description', 'Amount', 'Transaction Type',
        'Account Name'
    ]

    def convert_row(row) -> tuple:
        return tuple(row[field] for field in keep_fields)

    for csv_data in mint_data_list:
        cur_counter = collections.Counter()  # type: Dict[tuple, int]
        reader = csv.DictReader(io.StringIO(csv_data, newline=''))
        if fieldnames is None:
            fieldnames = reader.fieldnames
        else:
            assert fieldnames == reader.fieldnames, (fieldnames,
                                                     reader.fieldnames)
        rows = list(reader)
        for row in rows:
            converted_row = convert_row(row)
            cur_counter[converted_row] += 1
            if cur_counter[converted_row] > merged_counter[converted_row]:
                merged_rows.append(row)
                merged_counter[converted_row] += 1

    merged_rows.sort(key=get_mint_date, reverse=True)

    assert fieldnames is not None

    new_csv = io.StringIO(newline='')
    new_csv_data = csv.DictWriter(new_csv, fieldnames=fieldnames,
                                  lineterminator='\n', quoting=csv.QUOTE_ALL)
    new_csv_data.writeheader()
    new_csv_data.writerows(merged_rows)

    csv_data = new_csv.getvalue()
    return csv_data


def merge_mint_files(input_paths: Sequence[str], output_path: str):
    mint_data_list = []
    for filename in input_paths:
        with open(filename, 'r') as f:
            mint_data_list.append(f.read())
    csv_data = merge_mint_data(mint_data_list)
    with open(output_path, 'w') as f:
        f.write(csv_data)


def verify_mint_update_consistency(csv_data: str, existing_filename: str,
                                   allow_missing: bool = False):
    unchanged = False

    if os.path.exists(existing_filename):
        missing = False
        with open(existing_filename, 'r') as f:
            old_data = f.read()

        def get_rows(data):
            reader = csv.DictReader(io.StringIO(csv_data, newline=''))
            csv_rows = list(reader)
            keep_fields = [
                'Date', 'Original Description', 'Amount', 'Transaction Type',
                'Account Name'
            ]

            def convert_row(row):
                return tuple(row[field] for field in keep_fields)

            return list(map(convert_row, csv_rows))

        if old_data == csv_data:
            unchanged = True
        else:
            old_rows = get_rows(old_data)
            old_counter = collections.Counter(old_rows)
            new_rows = get_rows(csv_data)
            new_counter = collections.Counter(new_rows)

            for k in old_rows:
                if old_counter[k] > new_counter[k]:
                    logger.warning('New file missing entry: %s', k)
                    missing = True
            if missing and not allow_missing:
                raise RuntimeError('New file is missing some existing entries')
    if not unchanged:
        with open(existing_filename, 'w') as f:
            f.write(csv_data)


def fetch_mint_data(credentials: dict, existing_filename: str,
                    new_filename: str, balances_output_prefix: str,
                    skip_refresh: bool = False, skip_download: bool = False,
                    allow_missing: bool = False, **kwargs):
    if new_filename == existing_filename:
        raise ValueError('new_filename must not equal existing_filename')
    if skip_download:
        with open(new_filename, 'r') as f:
            csv_data = f.read()
    else:
        with connect(credentials, kwargs) as mint:
            if not skip_refresh:
                refresh_mint_data(mint)
            csv_data, balances = download_mint_data(mint)
        with open(new_filename, 'w') as f:
            f.write(csv_data)

        balances_path = balances_output_prefix + time.strftime(
            '%Y-%m-%dT%H%M%S%z') + '.csv'
        csv_merge.write_csv([
            'Name', 'Currency', 'Balance', 'Last Updated', 'State',
            'Last Transaction'
        ], balances, balances_path)
        logger.info('Writing balances to: %s', balances_path)

    verify_mint_update_consistency(csv_data=csv_data,
                                   existing_filename=existing_filename,
                                   allow_missing=allow_missing)


def run(output_directory: str, merge_files: Sequence[str] = (), **kwargs):
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    existing_filename = os.path.join(output_directory, 'mint.csv')
    new_filename = os.path.join(output_directory, 'mint.csv.new')
    balances_output_prefix = os.path.join(output_directory, 'balances.')
    fetch_mint_data(existing_filename=existing_filename,
                    new_filename=new_filename,
                    balances_output_prefix=balances_output_prefix, **kwargs)
    if merge_files:
        merged_filename = os.path.join(output_directory, 'mint-merged.csv')
        merge_mint_files([existing_filename] + list(merge_files),
                         merged_filename)
        logger.info('Saved merged transactions to: %s', merged_filename)


@contextlib.contextmanager
def interactive(**kwargs):
    with connect(kwargs['credentials'],
                 dict(profile_dir=kwargs.get('profile_dir'))) as mint:
        kwargs['mint'] = mint
        yield kwargs
