"""Retrieves trades, transfers, balances and price information from the Gemini Crypto Exchange.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'api_key'`, `'api_secret'` keys.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the output will be written.  If the directory does not
  exist, it will be created.

Output format:
==============

CSV files.

output_directory
-- trades.1632852595934.csv
-- transfers.1632752595924.csv
-- balances.2021-06-01.csv
-- balances.2021-07-01.csv
...

The timestamp in the trades/transfers files indicates the timestamp of the last trade/transfer contained in the file and is used to download only later ones.

Example:
========

    def CONFIG_gemini():
        return dict(
            module='finance_dl.gemini',
            credentials={
                'key': 'XXXXXX',
                'secret': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'gemini'),
        )
"""

import io
import urllib.parse
import re
import dateutil.parser
import datetime
import logging
import os, time, shutil, glob, re

import requests
import json
import base64
import hmac
import hashlib
import datetime, time
import csv

logger = logging.getLogger('gemini_downloader')

BALANCES_URL = "https://api.gemini.com/v1/balances"
TRADES_URL = "https://api.gemini.com/v1/mytrades"
TRANSFERS_URL = "https://api.gemini.com/v1/transfers"
TICKERS_URL = "https://api.gemini.com/v2/ticker"


def get_request_headers(api_key, b64, signature):
    return   {
        'Content-Type': "text/plain",
        'Content-Length': "0",
        'X-GEMINI-APIKEY': api_key,
        'X-GEMINI-PAYLOAD': b64,
        'X-GEMINI-SIGNATURE': signature,
        'Cache-Control': "no-cache"
        }


class RateLimitedRetryingRequester:
    """
    For public API entry points, we limit requests to 120 requests per minute, and recommend that you do not exceed 1 request per second.
    When requests are received at a rate exceeding X requests per minute, we offer a "burst" rate of five additional requests that are queued but their processing is delayed until the request rate falls below the defined rate.

When you exceed the rate limit for a group of endpoints, you will receive a 429 Too Many Requests HTTP status response until your request rate drops back under the required limit.
    """
    MIN_PERIOD = 0.5
    last_req_ts = 0
    RETRY_CODES = [429]
    NUM_RETRIES = 3

    def make_request(self, url, headers = None, get = True):
        now = time.time()
        wait = self.MIN_PERIOD - (now - self.last_req_ts)
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(url) if get else requests.post(url, headers=headers)
            self.last_req_ts = time.time()
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as exc:
            if exc.response.status_code not in self.RETRY_CODES:
                raise exc

        wait = self.MIN_PERIOD
        for i in range(self.NUM_RETRIES):
            if r.status_code == 429:
                # rate, parse error message for waiting interval
                match = re.search(".*\s(?P<duration>[0-9]+)\smilliseconds.*", r.json()["message"])
                wait = float(match.group("duration")) / 1e3 * 1.1 # safety margin
                logger.info(f"Server requested delay of: {wait*1e3:.1f} ms.")
            else:
                wait = 2 * wait
            time.sleep(wait)
            try:
                r = requests.get(url) if get else requests.post(url, headers=headers)
                self.last_req_ts = time.time()
                r.raise_for_status()
                return r.json()
            except requests.HTTPError as exc:
                if exc.response.status_code not in self.RETRY_CODES:
                    raise exc


def get_trades(requester, api_key, api_secret, data_dir):
    trades = []
    tprev = None
    old_files = sorted(glob.glob(os.path.join(data_dir, 'trades.*.csv')))
    if len(old_files):
        ts = int(old_files[-1].split(".")[1])
    else:
        ts = int(time.time() - 3600*24*365*20) * 1000 # start 20 years ago
    t = datetime.datetime.now()
    payload_nonce =  int(time.mktime(t.timetuple())*1000)

    while ts != tprev:
        tprev = ts
        payload =  {"request": "/v1/mytrades",
                    "nonce": str(payload_nonce),
                    "limit_trades": 500,
                    "timestamp" : ts}
        encoded_payload = json.dumps(payload).encode()
        b64 = base64.b64encode(encoded_payload)
        signature = hmac.new(api_secret, b64, hashlib.sha384).hexdigest()
        request_headers = get_request_headers(api_key, b64, signature)
        my_trades = requester.make_request(TRADES_URL, headers = request_headers, get = False)
        if 'result' in my_trades:
            raise Exception(my_trades)
        logger.info(f"Got {len(my_trades)} trade(s).")
        trades.extend(my_trades)
        if len(my_trades) == 0:
            break
        if not isinstance(my_trades, list):
            raise Exception(response.json())
        ts = my_trades[0]['timestampms']
        payload_nonce += 1000
    # Dedup
    if len(trades) == 0:
        # no new trades
        return
    trades = sorted(trades, key = lambda x: x['timestampms'])
    unique_trades = {tr['tid'] : tr for tr in trades}
    unique_trades = list(tr for _, tr in unique_trades.items())

    # Now turn into a CSV
    data_file = open(os.path.join(data_dir, f"trades.{ts+1}.csv"), 'w')
    csv_writer = csv.writer(data_file)
    header = None
    for tr in unique_trades:
        if not header:
            header = tr.keys()
            csv_writer.writerow(header)
        csv_writer.writerow(tr.values())
    data_file.close()


def get_balances_and_prices(requester, api_key, api_secret, data_dir):
    payload_nonce =  int(time.time()*1000)

    payload =  {"request": "/v1/balances", "nonce": str(payload_nonce)}
    encoded_payload = json.dumps(payload).encode()
    b64 = base64.b64encode(encoded_payload)
    signature = hmac.new(api_secret, b64, hashlib.sha384).hexdigest()

    request_headers = get_request_headers(api_key, b64, signature)
    balances = requester.make_request(BALANCES_URL, request_headers, get = False)
    if 'result' in balances:
        raise Exception(balances)
    logger.info(f"Got balances. Found {len(balances)} currencies.")

    # Prices
    tickers = [b['currency'] + "USD" for b in balances if b['currency'] != 'USD' and b['currency'] != 'GUSD']
    prices = {}
    prices['GUSD'] = 1
    for t in tickers:
        obj = requester.make_request(TICKERS_URL+"/"+t.lower(), None, get = True)
        price = (float(obj['ask']) + float(obj['bid']))/2
        currency = obj['symbol'][:-3] # BTCUSD -> BTC
        prices[currency] = price
    logger.info("Got prices")

    # Merge and Date
    for bal in balances:
        bal['price'] = prices[bal['currency']]\
             if bal['currency'] in prices else None
        bal['timestamp'] = int(time.time())

    # Now turn into a CSV
    date = datetime.date.today().strftime("%Y-%m-%d")
    data_file = open(os.path.join(data_dir, f"balances.{date}.csv"), 'w')
    csv_writer = csv.writer(data_file)
    header = None
    for tr in balances:
        if not header:
            header = tr.keys()
            csv_writer.writerow(header)
        csv_writer.writerow(tr.values())
    data_file.close()

def get_transfers(requester, api_key, api_secret, data_dir):
    transfers = []
    tprev = None
    # Find timestamp of last transfer downloaded by inspecting old files.
    old_files = sorted(glob.glob(os.path.join(data_dir, "transfers.*.csv")))
    if len(old_files) > 0:
        ts = int(old_files[-1].split(".")[1])
    else:
        ts = int(time.time() - 3600*24*365*20) * 1000

    t = datetime.datetime.now()
    payload_nonce =  int(time.mktime(t.timetuple())*1000)
    while ts != tprev:
        tprev = ts
        payload =  {"request": "/v1/transfers", "nonce": payload_nonce, "timestamp": ts}
        encoded_payload = json.dumps(payload).encode()
        b64 = base64.b64encode(encoded_payload)
        signature = hmac.new(api_secret, b64, hashlib.sha384).hexdigest()
        request_headers = get_request_headers(api_key, b64, signature)
        obj = requester.make_request(TRANSFERS_URL, request_headers, get = False)
        if len(obj) == 0:
            break
        if not isinstance(obj, list):
            raise Exception(response.json())
        my_transfers = obj
        transfers.extend(my_transfers)
        logger.info(f"Got {len(my_transfers)} transfers.")
        if len(my_transfers) == 0:
            break
        ts = my_transfers[0]['timestampms']
        payload_nonce += 1

    # Dedup
    transfers = sorted(transfers, key = lambda x: x['timestampms'])
    unique_transfers = {tr['eid'] : tr for tr in transfers}
    unique_transfers = list(tr for _, tr in unique_transfers.items())

    #find set of all columns
    if len(transfers) == 0:
        # no new transfers
        return
    columns = list(transfers[0].keys())
    for tr in unique_transfers:
        for col in tr:
            if col not in columns:
                columns.append(col)
    standardized_rows = [
        [tr[c] if c in tr else None for c in columns]\
            for tr in unique_transfers]

    # Now turn into a CSV
    # ts corresponds to timestamp of last received record
    data_file = open(os.path.join(data_dir, f"transfers.{ts+1}.csv"), 'w')
    csv_writer = csv.writer(data_file)
    for row in standardized_rows:
        if columns:
            csv_writer.writerow(columns)
            columns = None
        csv_writer.writerow(row)
    data_file.close()


def run(credentials = None, output_directory = None, **kwargs):
    api_key = credentials['api_key']
    api_secret = credentials['api_secret']
    api_secret = api_secret.encode()
    requester = RateLimitedRetryingRequester()
    get_trades(requester, api_key, api_secret, output_directory)
    get_balances_and_prices(requester, api_key, api_secret, output_directory)
    get_transfers(requester, api_key, api_secret, output_directory)

def interactive(credentials = None, output_directory = None, **kwargs):
    raise Exception("Not implemented")
