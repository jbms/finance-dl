"""Retrieves receipt images and extracted data from waveapps.com.

This uses the waveapps API (https://docs.waveapps.io/) to retrieve the data
directly.


Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with a `'token'` key specifying a
  Full Access token.  To generate a token, first sign in to https://waveapps.com
  and then visit the "Manage Applications" page:
  https://developer.waveapps.com/hc/en-us/articles/360019762711

  Choose "Create an application", then after creating an application choose
  "Create token".

  Alternatively, if you have a valid OAuth2 client id, instead of the `'token'`
  field you may specify `'client_id'`, `'username'`, and `'password'` fields.
  Signing in with a Google account is not supported.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the output will be written.  If the directory does not
  exist, it will be created.

Output format:
==============

For each receipt, the JSON data as returned by the API is saved within the
specified `output_directory` as `<receipt-id>.json`.  The JSON data contains at
least the following fields:

 - `id`: The unique receipt identifier, matching the `<receipt-id>` portion of
   the filename.

- `date`: The date.

- `merchant`: Merchant name

- `note`: Optional note.

- `total`: Total amount.

- `currency_code`: The currency code.

The corresponding receipt images are saved in full resolution as:
`<receipt-id>.jpeg`, and if there are additional images, as
`<receipt-id>.01.jpeg`, `<receipt-id>.02.jpeg`, etc.

Example:
========

    def CONFIG_waveapps():
        return dict(
            module='finance_dl.waveapps',
            credentials={
                'token': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'waveapps'),
        )

"""

from typing import List, Any
import contextlib
import logging
import json
import os

import requests
from atomicwrites import atomic_write

logger = logging.getLogger('waveapps')


class WaveScraper(object):
    def __init__(self, credentials: dict, output_directory: str,
                 headless=None):
        del headless
        self.credentials = credentials
        self.output_directory = output_directory

    def get_oauth2_token(self):
        if 'token' in self.credentials:
            logger.info('Using specified token')
            self._oauth_token = {
                'token_type': 'Bearer',
                'access_token': self.credentials['token']
            }
        else:
            logger.info('Obtaining oauth2 token')
            oauth_url = 'https://api.waveapps.com/oauth2/token/'
            response = requests.post(
                oauth_url, files={
                    k: (None, v, None, {})
                    for k, v in [
                        ('client_id', self.credentials['client_id']),
                        ('username', self.credentials['username']),
                        ('grant_type', 'password'),
                        ('password', self.credentials['password']),
                    ]
                })
            response.raise_for_status()
            self._oauth_token = response.json()
        self._authenticated_headers = {
            'authorization':
            self._oauth_token['token_type'] + ' ' +
            self._oauth_token['access_token'],
        }

    def get_businesses(self):
        logger.info('Getting list of businesses')
        response = requests.get(
            'https://api.waveapps.com/businesses/?include_personal=true',
            headers=dict(self._authenticated_headers,
                         accept='application/json'),
        )
        response.raise_for_status()
        result = response.json()
        logger.info('Got %d businesses', len(result))
        self._businesses = result

    def get_receipts(self, business_id: str):
        logger.info('Getting receipts for business %s', business_id)
        receipts = []  # type: List[Any]
        response = requests.get(
            'https://api.waveapps.com/businesses/' + business_id +
            '/receipts/?active_only=false',
            headers=dict(self._authenticated_headers,
                         accept='application/json'),
        )
        response.raise_for_status()
        result = response.json()
        cur_list = result['results']
        logger.info('Received %d receipts', len(cur_list))
        receipts.extend(cur_list)
        return receipts

    def get_all_receipts(self):
        receipts = []  # type: List[Any]
        for business in self._businesses:
            business_id = business['id']
            receipts.extend(self.get_receipts(business_id))
        return receipts

    def save_receipts(self, receipts: List[Any]):
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        for receipt in receipts:
            output_prefix = os.path.join(self.output_directory,
                                         str(receipt['id']))
            json_path = output_prefix + '.json'
            for image_i, image in enumerate(receipt['images']):
                image_url = image['file']
                if image_i == 0:
                    image_path = '%s.jpg' % (output_prefix, )
                else:
                    image_path = '%s.%02d.jpg' % (output_prefix, image_i)
                if not os.path.exists(image_path):
                    logger.info('Downloading receipt image %s', image_url)
                    r = requests.get(image_url)
                    r.raise_for_status()
                    data = r.content
                    with atomic_write(image_path, mode='wb') as f:
                        f.write(data)
            with atomic_write(json_path, mode='w', overwrite=True) as f:
                json.dump(receipt, f, sort_keys=True, indent='  ')

    def run(self):
        self.get_oauth2_token()
        self.get_businesses()
        receipts = self.get_all_receipts()
        self.save_receipts(receipts)


def run(**kwargs):
    scraper = WaveScraper(**kwargs)
    scraper.run()


@contextlib.contextmanager
def interactive(**kwargs):
    scraper = WaveScraper(**kwargs)
    kwargs['scraper'] = scraper
    yield kwargs
