"""Retrieves Google data using https://takeout.google.com

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Google Takeout website.

This is not itself a finance_dl data source, but is used by the
`finance_dl.google_purchases` module.
"""

from typing import List, Any, Iterable, FrozenSet
import urllib.parse
import re
import io
import logging
import time
import zipfile
from selenium.webdriver.common.by import By
from . import scrape_lib
from . import google_login

logger = logging.getLogger('google_takeout')

netloc_re = r'^([^\.@]+\.)*google.com$'


def check_url(url):
    result = urllib.parse.urlparse(url)
    if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
        raise RuntimeError('Reached invalid URL: %r' % url)


class Scraper(scrape_lib.Scraper):
    def __init__(self, credentials: dict, **kwargs):
        super().__init__(**kwargs)
        self.credentials = credentials

    def check_after_wait(self):
        check_url(self.driver.current_url)

    def _get_categories(self):
        categories, = self.wait_and_return(lambda: self.driver.find_elements(
            By.XPATH, '//input[@type="checkbox"]'))
        return categories

    def _create_archive(self, categories: FrozenSet[str]):
        logger.info('Selecting categories')
        checkboxes = self._get_categories()
        found_ids = set()
        for checkbox in checkboxes:
            value = checkbox.get_attribute('value')
            found_ids.add(value)
            wanted = value in categories
            checked = checkbox.get_attribute('checked') == 'true'
            if wanted != checked:
                checkbox.click()
        remaining = categories - found_ids
        if remaining:
            raise RuntimeError(
                'Categories not found: %s' % ', '.join(sorted(remaining)))
        logger.info('Creating archive')
        checkboxes[0].submit()

    def _get_download_links(self):
        download_links = self.driver.find_elements(By.XPATH,
                                                   '//a[.="Download"]')
        return [x.get_attribute('href') for x in download_links]

    def get_takeout_zipfile(self, categories: Iterable[str]) -> zipfile.ZipFile:
        """Returns a zipfile containing the specified takeout categories."""
        google_login.login(self,
                           'https://takeout.google.com/settings/takeout/light')
        # Wait for at least one checkbox
        self._get_categories()
        # Wait 2 seconds to be sure all have loaded and then get new checkboxes
        time.sleep(2)
        # Get existing download links
        download_links = self._get_download_links()
        self._create_archive(categories=frozenset(categories))

        for attempt_i in range(3):
            logger.info('Waiting for new download links (attempt %d)',
                        attempt_i + 1)
            # Wait 10 seconds for the archive to be created
            time.sleep(10)
            with self.wait_for_page_load():
                self.driver.refresh()
            new_download_links = set(
                self._get_download_links()) - set(download_links)
            if len(new_download_links) == 0: continue
            if len(new_download_links) > 1:
                raise RuntimeError('More than one new archive found')
            break
        new_download_link = list(new_download_links)[0]
        logger.info('Downloading archive')
        google_login.login(self, new_download_link)
        (_, data), = self.wait_and_return(self.get_downloaded_file)
        return zipfile.ZipFile(io.BytesIO(data))
