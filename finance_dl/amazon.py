"""Retrieves order invoices from Amazon.

This uses the `selenium` Python package in conjunction with `chromedriver` to
scrape the Amazon website.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `credentials`: Required.  Must be a `dict` with `'username'` and `'password'`
  keys.

- `output_directory`: Required.  Must be a `str` that specifies the path on the
  local filesystem where the output will be written.  If the directory does not
  exist, it will be created.

- `amazon_domain`: Optional.  Specifies the Amazon domain from which to download
  orders.  Must be one of `'.com'`, `'.co.cuk'` or `'.de'`.  Defaults to
  `'.com'`.

- `regular`: Optional.  Must be a `bool`.  If `True` (the default), download regular orders.

- `digital`: Optional.  Must be a `bool` or `None`.  If `True`, download digital
  orders.  Defaults to `None`, which is equivalent to `True` for
  `amazon_domain=".com"`, and `False` for `amazon_domain=".co.uk"`.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.

- `order_groups`: Optional.  If specified, must be a list of strings specifying the Amazon
  order page "order groups" that will be scanned for orders to download. Order groups
  include years (e.g. '2020'), as well as 'last 30 days' and 'past 3 months'.

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
            # order_groups is optional.
            order_groups=['past 3 months'],
        )

Interactive shell:
==================

From the interactive shell, type: `self.run()` to start the scraper.

"""
import dataclasses
import urllib.parse
import re
import logging
import os
import pathlib
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from atomicwrites import atomic_write
from . import scrape_lib
from typing import List, Optional

logger = logging.getLogger('amazon_scrape')


@dataclasses.dataclass
class Domain:
  top_level: str

  sign_in: str
  sign_out: str

  # Find invoices.
  your_orders: str
  invoice: str
  order_summary: str
  next: str

  # Confirm invoice page
  grand_total: str
  grand_total_digital: str

  digital_orders: bool
  digital_orders_text: Optional[str] = None


DOT_COM = Domain(
  top_level='com',
  sign_in='Sign In',
  sign_out='Sign Out',

  your_orders='Your Orders',
  invoice='Invoice',
  order_summary='Order Summary',
  next='Next',

  grand_total='Grand Total:',
  grand_total_digital='Grand Total:',

  digital_orders=True,
  digital_orders_text='Digital Orders',
)

DOT_CO_UK = Domain(
  top_level='co.uk',
  sign_in='Sign in',
  sign_out='Sign out',

  your_orders='Your Orders',
  invoice='Invoice',
  order_summary='Order Summary',
  next='Next',

  grand_total='Grand Total:',
  grand_total_digital='Grand Total:',

  digital_orders=False,
)

DOT_DE = Domain(
  top_level='de',
  sign_in='Hallo, Anmelden',
  sign_out='Abmelden',

  your_orders='Meine Bestellungen',
  invoice='Rechnung',
  order_summary='Bestellübersicht',
  next='Weiter',

  grand_total='Gesamtsumme:',
  grand_total_digital='Endsumme:',
  digital_orders=False,
)

DOMAINS = {"." + x.top_level: x for x in [DOT_COM, DOT_CO_UK, DOT_DE]}


class Scraper(scrape_lib.Scraper):
    def __init__(self,
                 credentials,
                 output_directory,
                 amazon_domain: str = ".com",
                 regular: bool = True,
                 digital: Optional[bool] = None,
                 order_groups: Optional[List[str]] = None,
                 **kwargs):
        super().__init__(**kwargs)
        if amazon_domain not in DOMAINS:
          raise ValueError(f"Domain '{amazon_domain} not supported. Supported "
                           f"domains: {list(DOMAINS)}")
        self.domain = DOMAINS[amazon_domain]
        self.credentials = credentials
        self.output_directory = output_directory
        self.logged_in = False
        self.regular = regular
        self.digital = digital if digital is not None else self.domain.digital_orders
        self.order_groups = order_groups

    def check_url(self, url):
        netloc_re = r'^([^\.@]+\.)*amazon.' + self.domain.top_level + '$'
        result = urllib.parse.urlparse(url)
        if result.scheme != 'https' or not re.fullmatch(netloc_re, result.netloc):
            raise RuntimeError('Reached invalid URL: %r' % url)

    def check_after_wait(self):
        self.check_url(self.driver.current_url)

    def login(self):
        logger.info('Initiating log in')
        self.driver.get('https://www.amazon.' + self.domain.top_level)
        if self.logged_in:
            return

        sign_out_links = self.find_elements_by_descendant_partial_text(self.domain.sign_out, 'a')
        if len(sign_out_links) > 0:
            logger.info('You must be already logged in!')
            self.logged_in = True
            return

        logger.info('Looking for sign-in link')
        sign_in_links, = self.wait_and_return(
            lambda: self.find_visible_elements_by_descendant_partial_text(self.domain.sign_in, 'a')
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

        logger.info('Looking for "remember me" checkbox')
        (rememberMe, ) = self.wait_and_return(
            lambda: self.find_visible_elements(By.XPATH, '//input[@name="rememberMe"]')[0]
        )
        rememberMe.click()

        password.send_keys(Keys.ENTER)

        logger.info('Logged in')
        self.logged_in = True

    def get_invoice_path(self, order_id):
        return os.path.join(self.output_directory, order_id + '.html')

    def get_order_id(self, href) -> str:
        m = re.match('.*[&?]orderID=((?:D)?[0-9\\-]+)(?:&.*)?$', href)
        if m is None:
            raise RuntimeError(
                'Failed to parse order ID from href %r' % (href, ))
        return m[1]

    def get_orders(self, regular=True, digital=True):
        invoice_hrefs = []

        def get_invoice_urls():
            initial_iteration = True
            while True:

                def invoice_finder():
                    return [a for a in self.driver.find_elements_by_xpath('//a[@class="a-popover-trigger a-declarative"]') if a.text == self.domain.invoice]

                if initial_iteration:
                    invoices = invoice_finder()
                else:
                    invoices, = self.wait_and_return(invoice_finder)
                initial_iteration = False

                last_order_id = None
                for invoice_link in invoices:
                    while True:
                        invoice_link.click()
                        summary_links = self.driver.find_elements_by_link_text(self.domain.order_summary)
                        if summary_links:
                            href = summary_links[0].get_attribute('href')
                            order_id = self.get_order_id(href)
                            if order_id != last_order_id:
                              break
                        time.sleep(0.5)

                    last_order_id = order_id
                    logging.info('Found link for order %s: %s', order_id, href)
                    invoice_hrefs.append((href, order_id))

                # Find next link
                next_links = self.find_elements_by_descendant_text_match(
                    f'. = "{self.domain.next}"', 'a', only_displayed=True)
                if len(next_links) == 0:
                    logger.info('Found no more pages')
                    break
                if len(next_links) != 1:
                    raise RuntimeError('More than one next link found')
                with self.wait_for_page_load():
                    logging.info("Next page.")
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
                option = order_select.options[
                    order_select_index]
                option_text = option.text.strip()
                order_select_index += 1
                if option_text == 'Archived Orders':
                    continue
                if self.order_groups is not None and option_text not in self.order_groups:
                    logger.info('Skipping order group: %r', option_text)
                    continue
                logger.info('Retrieving order group: %r', option_text)
                if not option.is_selected():
                    with self.wait_for_page_load():
                        order_select.select_by_index(order_select_index - 1)
                get_invoice_urls()

        if regular:
            # on co.uk, orders link is hidden behind the menu, hence not directly clickable
            (orders_link,), = self.wait_and_return(
                lambda: self.find_elements_by_descendant_text_match(f'. = "{self.domain.your_orders}"', 'a', only_displayed=False)
            )
            link = orders_link.get_attribute('href')
            scrape_lib.retry(lambda: self.driver.get(link), retry_delay=2)

            retrieve_all_order_groups()

        if digital:
            (digital_orders_link,), = self.wait_and_return(
                lambda: self.find_elements_by_descendant_text_match(f'contains(., "{self.domain.digital_orders_text}")', 'a', only_displayed=True)
            )
            scrape_lib.retry(lambda: self.click(digital_orders_link),
                             retry_delay=2)
            retrieve_all_order_groups()

        self.retrieve_invoices(invoice_hrefs)

    def retrieve_invoices(self, invoice_hrefs):
        for href, order_id in invoice_hrefs:
            invoice_path = self.get_invoice_path(order_id)
            if pathlib.Path(invoice_path).exists():
              logging.info('Skipping already downloaded invoice for order %r', order_id)
              continue

            logger.info('Downloading invoice for order %r (link: %s)', order_id, href)
            with self.wait_for_page_load():
                self.driver.get(href)

            # For digital orders, Amazon dynamically generates some of the information.
            # Wait until it is all generated.
            def get_source():
                source = self.driver.page_source
                if self.domain.grand_total in source or self.domain.grand_total_digital in source:
                    return source
                return None

            page_source, = self.wait_and_return(get_source)
            if order_id not in page_source:
                raise ValueError('Failed to retrieve information for order %r'
                                 % (order_id, ))
            with atomic_write(
                    invoice_path, mode='w', encoding='utf-8',
                    newline='\n') as f:
                # Write with Unicode Byte Order Mark to ensure content will be properly interpreted as UTF-8
                f.write('\ufeff' + page_source)
            logger.info('  Wrote %s', invoice_path)

    def run(self):
        self.login()
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.get_orders(regular=self.regular, digital=self.digital)


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
