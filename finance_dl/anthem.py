"""Retrieves Anthem BlueCross Explanation of Benefits (EOB) statements.

Due to automation countermeasures implemented by Anthem, this module is only
semi-automatic: the user must manually login and navigate to the claims page.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Anthem website.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `login_url`: Required.  Must be a `str` that specifies the initial URL at
  which to start.  The user is responsible for manually logging in and
  navigating to the claims page.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the output will be written.  If the directory does not
  exist, it will be created.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.

- `headless`: Must be set to `False`, since this scraper requires manual input.

Example:
========

    def CONFIG_anthem():
        return dict(
            module='finance_dl.anthem',
            login_url='https://anthem.com',
            output_directory=os.path.join(data_dir, 'anthem'),

            # profile_dir is optional but recommended.
            profile_dir=os.path.join(profile_dir, 'anthem'),

            # headless must be `False` since manual intervention is required
            headless=False,
        )

Output format:
==============

For each claim, two files are written to the specified `output_directory`:
`<id>.json` contains a JSON representation of the claim as returned by the
Anthem server, and `<id>.pdf` contains the PDF "Explanation of Benefits"
statement for the claim.

The JSON file contains output of the form:

    {
      "patient": {
        "displayName": "John Smith",
        "uniqueId": "123456789",
        "allowsAccess": true
      },
      "provider": "SOME MEDICAL PROVIDER",
      "totalCharges": 385,
      "serviceDate": "01/02/2017 00:00:00",
      "memberResponsibility": 111.05,
      "status": "Approved",
      "appliedToDeductible": 111.05,
      "claimNumber": "2017123AB1234"
    }



Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

from typing import List, Any
import urllib.parse
import re
import collections
import json
import logging
import datetime
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
import bs4
import jsonschema
from atomicwrites import atomic_write

from . import scrape_lib
from . import google_login

logger = logging.getLogger('anthem')

netloc_re = r'^([^\.@]+\.)*anthem.com$'


class Scraper(scrape_lib.Scraper):
    def __init__(self, login_url: str, output_directory: str, **kwargs):
        super().__init__(use_seleniumrequests=True, **kwargs)
        self.login_url = login_url
        self.output_directory = output_directory

    def login(self):
        self.driver.get(self.login_url)

    def maybe_get_claims_json(self):
        try:
            soup = bs4.BeautifulSoup(self.driver.page_source, 'html.parser')
            return json.loads(
                soup.find(id='claimsJson').text,
                object_pairs_hook=collections.OrderedDict)
        except:
            raise NoSuchElementException

    def wait_for_claims_json(self):
        logger.info('Please login and navigate to the claims page')
        result = self.wait_and_return(self.maybe_get_claims_json,
                                      timeout=500)[0]
        logger.info('Claims data found')
        return result

    def save_documents(self):
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        claims_json = self.wait_for_claims_json()
        downloads_needed = []
        for claim in claims_json['claims']:
            url = claim['eobLinkUrl']
            pdf_path = os.path.join(self.output_directory,
                                    claim['claimNumber'] + '.pdf')
            json_path = os.path.join(self.output_directory,
                                     claim['claimNumber'] + '.json')
            if not os.path.exists(json_path):
                with atomic_write(json_path, mode='w') as f:
                    f.write(json.dumps(claim, indent='  ').strip() + '\n')
            if not os.path.exists(pdf_path):
                if not claim['eobLinkUrl'].startswith('https:/'): continue
                downloads_needed.append((claim['eobLinkUrl'], pdf_path))
        for i, (url, pdf_path) in enumerate(downloads_needed):
            logger.info('Downloading EOB %d/%d', i + 1, len(downloads_needed))
            self.driver.get(url)
            download_result, = self.wait_and_return(self.get_downloaded_file)
            with atomic_write(pdf_path, mode='wb') as f:
                f.write(download_result[1])

    def run(self):
        self.login()
        self.save_documents()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
