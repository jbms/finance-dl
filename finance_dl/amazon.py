"""Retrieves order invoices from Amazon.com.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Venmo website.

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

Each regular or digital order invoice is written in HTML format to the specified
`output_directory` using the naming scheme `<order-id>.html`,
e.g. `166-7926740-5141621.html` for a regular order invoice and
`D56-5204779-4181560.html` for a digital order invoice.

Example:
========

    def CONFIG_amazon():
        return dict(
            module='finance_dl.amazon',
            credentials={
                'username': 'XXXXXX',
                'password': 'XXXXXX',
            },
            output_directory=os.path.join(data_dir, 'amazon'),
            # profile_dir is optional.
            profile_dir=os.path.join(profile_dir, 'amazon'),
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""

import urllib.parse
import re
import logging
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from atomicwrites import atomic_write
from . import scrape_lib

logger = logging.getLogger('amazon_scrape')

netloc_re = r'^([^\.@]+\.)*amazon.com$'


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
        self.driver.get('https://www.amazon.com')

        logger.info('Looking for sign-in link')
        sign_in_links, = self.wait_and_return(
            lambda: self.find_visible_elements_by_descendant_partial_text('Sign in', 'a')
        )

        self.click(sign_in_links[0])
        logger.info('Looking for username link')
        (username, ), = self.wait_and_return(
            lambda: self.find_visible_elements(By.XPATH, '//input[@type="email"]')
        )
        username.send_keys(self.credentials['username'])
        username.send_keys(Keys.ENTER)

        logger.info('Looking for password link')
        (password, ), = self.wait_and_return(
            lambda: self.find_visible_elements(By.XPATH, '//input[@type="password"]')
        )
        password.send_keys(self.credentials['password'])
        password.send_keys(Keys.ENTER)
        logger.info('Logged in')
        self.logged_in = True

    def get_invoice_path(self, order_id):
        return os.path.join(self.output_directory, order_id + '.html')

    def get_orders(self, regular=True, digital=True):
        invoice_hrefs = []
        order_ids_seen = set()

        def get_invoice_urls():
            initial_iteration = True
            while True:

                def invoice_finder():
                    return self.find_elements_by_descendant_text_match(
                        '. = "Invoice"', 'a', only_displayed=True)

                if initial_iteration:
                    invoices = invoice_finder()
                else:
                    invoices, = self.wait_and_return(invoice_finder)
                initial_iteration = False

                for invoice_link in invoices:
                    href = invoice_link.get_attribute('href')
                    m = re.match('.*&orderID=((?:D)?[0-9\\-]+)(?:&.*)?$', href)
                    if m is None:
                        raise RuntimeError(
                            'Failed to parse order ID from href %r' % (href, ))
                    order_id = m[1]
                    invoice_path = self.get_invoice_path(order_id)
                    if order_id in order_ids_seen:
                        logger.info('Skipping already-seen order id: %r',
                                    order_id)
                        continue
                    if os.path.exists(invoice_path):
                        logger.info('Skipping already-downloaded invoice: %r',
                                    order_id)
                        continue
                    invoice_hrefs.append((href, order_id))
                    order_ids_seen.add(order_id)

                # Find next link
                next_links = self.find_elements_by_descendant_text_match(
                    '. = "Next"', 'a', only_displayed=True)
                if len(next_links) == 0:
                    logger.info('Found no more pages')
                    break
                if len(next_links) != 1:
                    raise RuntimeError('More than one next link found')
                with self.wait_for_page_load():
                    self.click(next_links[0])

        def retrieve_all_order_groups():
            order_select_index = 0

            while True:
                (order_filter,), = self.wait_and_return(
                    lambda: self.find_visible_elements(By.XPATH, '//select[@name="orderFilter"]')
                )
                order_select = Select(order_filter)
                num_options = len(order_select.options)
                if order_select_index >= num_options:
                    break
                option_text = order_select.options[
                    order_select_index].text.strip()
                if option_text != 'Archived Orders':
                    logger.info('Retrieving order group: %r', option_text)
                    with self.wait_for_page_load():
                        order_select.select_by_index(order_select_index)
                    get_invoice_urls()

                order_select_index += 1
                if order_select_index >= num_options:
                    break

        if regular:
            (orders_link,), = self.wait_and_return(
                lambda: self.find_elements_by_descendant_text_match('. = "Orders"', 'a', only_displayed=True)
            )
            scrape_lib.retry(lambda: self.click(orders_link), retry_delay=2)
            retrieve_all_order_groups()

        if digital:
            (digital_orders_link,), = self.wait_and_return(
                lambda: self.find_elements_by_descendant_text_match('contains(., "Digital Orders")', 'a', only_displayed=True)
            )
            scrape_lib.retry(lambda: self.click(digital_orders_link),
                             retry_delay=2)
            retrieve_all_order_groups()

        self.retrieve_invoices(invoice_hrefs)

    def retrieve_invoices(self, invoice_hrefs):
        for href, order_id in invoice_hrefs:
            invoice_path = self.get_invoice_path(order_id)

            logger.info('Downloading invoice for order %r', order_id)
            with self.wait_for_page_load():
                self.driver.get(href)

            # For digital orders, Amazon dynamically generates some of the information.
            # Wait until it is all generated.
            def get_source():
                source = self.driver.page_source
                if 'Grand Total:' in source:
                    return source
                return None

            page_source, = self.wait_and_return(get_source)
            if order_id not in page_source:
                raise ValueError('Failed to retrieve information for order %r'
                                 % (order_id, ))
            with atomic_write(invoice_path, mode='w') as f:
                # Write with Unicode Byte Order Mark to ensure content will be properly interpreted as UTF-8
                f.write('\ufeff' + page_source)
            logger.info('  Wrote %s', invoice_path)

    def run(self):
        self.login()
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.get_orders()


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
