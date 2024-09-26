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

- `dir_per_year`: Optional. If true (default is false), adds one subdirectory
  to the output for each year's worth of transactions. Useful for filesystems
  that struggle with very large directories. Probably not that useful for
  actually finding anything, given the uselessness of Amazon's order ID
  scheme.

- `amazon_domain`: Optional.  Specifies the Amazon domain from which to download
  orders.  Must be one of `'.com'`, `'.co.cuk'` or `'.de'`.  Defaults to
  `'.com'`.

- `regular`: Optional.  Must be a `bool`.  If `True` (the default), download regular orders.
   For domains other than `amazon_domain=".com"`, `True` downloads regular AND digital orders.

- `digital`: Optional.  Must be a `bool` or `None`.  If `True`, download digital
  orders. Effective only for `amazon_domain=".com"`. Defaults to `True` for
  `amazon_domain=".com"`. For other domains, digital invoices are downloaded
  tgehter with regular invoices since there is no separate menu on the amazon website.

- `profile_dir`: Optional.  If specified, must be a `str` that specifies the
  path to a persistent Chrome browser profile to use.  This should be a path
  used solely for this single configuration; it should not refer to your normal
  browser profile.  If not specified, a fresh temporary profile will be used
  each time.

- `order_groups`: Optional.  If specified, must be a list of strings specifying the Amazon
  order page "order groups" that will be scanned for orders to download. Order groups
  include years (e.g. '2020'), as well as 'last 30 days' and 'past 3 months'.

- `download_preorder_invoices`: Optional. If specified and True, invoices for
  preorders (i.e. orders that have not actually been charged yet) will be
  skipped. Such preorder invoices are not typically useful for accounting
  since they claim a card was charged even though it actually has not been
  yet; they get replaced with invoices containing the correct information when
  the order is actually fulfilled.

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
import datetime
import dateutil.parser
import bs4
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from atomicwrites import atomic_write
from . import scrape_lib
from typing import List, Optional

logger = logging.getLogger('amazon_scrape')


@dataclasses.dataclass
class Domain():
    top_level: str

    sign_in: str
    sign_out: str

    # Find invoices.
    your_orders: str
    invoice: str
    invoice_link: List[str]
    order_summary: str
    order_summary_hidden: bool
    next: str

    # Confirm invoice page
    grand_total: str
    grand_total_digital: str
    order_cancelled: str
    pre_order: str

    digital_order: str
    regular_order_placed: str

    # .COM: digital orders have own order list
    # other domains: digital orders are in the regular order list
    digital_orders_menu: bool
    digital_orders_menu_text: Optional[str] = None
    
    fresh_fallback: Optional[str] = None


class DOT_COM(Domain):
    def __init__(self) -> None:
        super().__init__(
            top_level='com',
            sign_in='Sign In',
            sign_out='Sign Out',

            your_orders='Your Orders',
            invoice='Invoice',
            invoice_link=["View order", "View invoice"],
            # View invoice -> regular/digital order, View order -> Amazon Fresh
            fresh_fallback="View order",
            order_summary='Order Summary',
            order_summary_hidden=False,
            next='Next',

            grand_total='Grand Total:',
            grand_total_digital='Grand Total:',
            order_cancelled='Order Canceled',
            pre_order='Pre-order',

            digital_order='Digital Order: (.*)',
            regular_order_placed=r'(?:Subscribe and Save )?Order Placed:\s+([^\s]+ \d+, \d{4})',

            digital_orders_menu=True,
            digital_orders_menu_text='Digital Orders',
            )

    @staticmethod
    def parse_date(date_str) -> datetime.date:
        return dateutil.parser.parse(date_str).date()

class DOT_CO_UK(Domain):
    def __init__(self) -> None:
        super().__init__(
            top_level='co.uk',
            sign_in='Sign in',
            sign_out='Sign out',

            your_orders='Your Orders',
            invoice='Invoice',
            invoice_link=["View order", "View invoice"],
            # View invoice -> regular/digital order, View order -> Amazon Fresh
            fresh_fallback="View order",
            order_summary='Order Summary',
            order_summary_hidden=False,
            next='Next',

            grand_total='Grand Total:',
            grand_total_digital='Grand Total:',
            order_cancelled='Order Canceled',
            pre_order='Pre-order',

            digital_order='Digital Order: (.*)',
            regular_order_placed=r'(?:Subscribe and Save )?Order Placed:\s+([^\s]+ \d+, \d{4})',

            digital_orders_menu=False,
            )

    @staticmethod
    def parse_date(date_str) -> datetime.date:
        return dateutil.parser.parse(date_str).date()

class DOT_DE(Domain):
    def __init__(self) -> None:
        super().__init__(
            top_level='de',
            sign_in='Anmelden',
            sign_out='Abmelden',

            your_orders='Meine Bestellungen',
            invoice='Rechnung',
            invoice_link=["Bestelldetails anzeigen"],
            fresh_fallback=None,
            order_summary='Bestellübersicht',
            order_summary_hidden=True,
            next='Weiter',

            grand_total='Gesamtsumme:',
            grand_total_digital='Endsumme:',
            order_cancelled='Order Canceled',
            pre_order='Pre-order',

            digital_order='Digitale Bestellung: (.*)',
            regular_order_placed=r'(?:Getätigte Spar-Abo-Bestellung|Bestellung aufgegeben am):\s+(\d+\. [^\s]+ \d{4})',

            digital_orders_menu=False,
            )

    class _parserinfo(dateutil.parser.parserinfo):
        MONTHS=[
            ('Jan', 'Januar'), ('Feb', 'Februar'), ('Mär', 'März'),
            ('Apr', 'April'), ('Mai', 'Mai'), ('Jun', 'Juni'),
            ('Jul', 'Juli'), ('Aug', 'August'), ('Sep', 'September'),
            ('Okt', 'Oktober'), ('Nov', 'November'), ('Dez', 'Dezember')
            ]
    
    @staticmethod
    def parse_date(date_str) -> datetime.date:
        return dateutil.parser.parse(date_str, parserinfo=DOT_DE._parserinfo(dayfirst=True)).date()

DOMAINS = {
    ".com": DOT_COM,
    ".co.uk": DOT_CO_UK, 
    ".de": DOT_DE
    }


class Scraper(scrape_lib.Scraper):
    def __init__(self,
                 credentials,
                 output_directory,
                 dir_per_year=False,
                 amazon_domain: str = ".com",
                 regular: bool = True,
                 digital: Optional[bool] = None,
                 order_groups: Optional[List[str]] = None,
                 download_preorder_invoices: bool = False,
                 **kwargs):
        super().__init__(**kwargs)
        if amazon_domain not in DOMAINS:
          raise ValueError(f"Domain '{amazon_domain} not supported. Supported "
                           f"domains: {list(DOMAINS)}")
        self.domain = DOMAINS[amazon_domain]()
        self.credentials = credentials
        self.output_directory = output_directory
        self.dir_per_year = dir_per_year
        self.logged_in = False
        self.regular = regular
        self.digital_orders_menu = digital if digital is not None else self.domain.digital_orders_menu
        self.order_groups = order_groups
        self.download_preorder_invoices = download_preorder_invoices

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

        self.finish_login()

    def finish_login(self):
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

        with self.wait_for_page_load():
            password.send_keys(Keys.ENTER)

        logger.info('Logged in')
        self.logged_in = True

    def get_invoice_path(self, year, order_id):
        if self.dir_per_year:
            return os.path.join(self.output_directory, str(year), order_id + '.html')
        return os.path.join(self.output_directory, order_id + '.html')

    def get_order_id(self, href) -> str:
        m = re.match('.*[&?]orderID=((?:D)?[0-9\\-]+)(?:&.*)?$', href)
        if m is None:
            raise RuntimeError(
                'Failed to parse order ID from href %r' % (href, ))
        return m[1]

    def get_orders(self, regular=True, digital_orders_menu=True):
        invoice_hrefs = []
        order_ids_seen = set()
        order_ids_downloaded = frozenset([
            name[:len(name)-5]
            for _, _, files in os.walk(self.output_directory)
            for name in files
            if name.endswith('.html')
        ])

        def get_invoice_urls():
            initial_iteration = True
            while True:
                # break when there is no "next page"

                # Problem: different site structures depending on country
                
                # .com / .uk
                # Order Summary buttons are directly visible and can be
                # identified with href containing "orderID="
                # but order summary may have different names, e.g. for Amazon Fresh orders
                
                # .de
                # only link with href containing "orderID=" is "Bestelldetails anzeigen" (=Order Details)
                # which is not helpful
                # order summary is hidden behind submenu which requires a click to be visible

                def invoice_finder():
                    if not self.domain.order_summary_hidden:
                        # order summary link is visible on page
                        return self.driver.find_elements(
                            By.XPATH, '//a[contains(@href, "orderID=")]')
                    else:
                        # order summary link is hidden in submenu for each order
                        elements = self.driver.find_elements(By.XPATH, 
                            '//a[@class="a-popover-trigger a-declarative"]')
                        return [a for a in elements if a.text == self.domain.invoice]
                
                if initial_iteration:
                    invoices = invoice_finder()
                else:
                    invoices, = self.wait_and_return(invoice_finder)
                initial_iteration = False

                last_order_id = None

                def invoice_link_finder(invoice_link):
                    if invoice_link.text not in self.domain.invoice_link:
                        # skip invoice if label is not known
                        # different labels are possible e.g. for regular orders vs. Amazon fresh
                        if invoice_link.text != "":
                            # log non-empty link texts -> may be new type
                            logger.debug(
                                'Skipping invoice due to unknown invoice_link.text: %s',
                                invoice_link.text)
                        return (False, False)
                    href = invoice_link.get_attribute('href')
                    order_id = self.get_order_id(href)
                    if self.domain.fresh_fallback is not None and invoice_link.text == self.domain.fresh_fallback:
                        # Amazon Fresh order, construct link to invoice
                        logger.info("   Found likely Amazon Fresh order. Falling back to direct invoice URL.")
                        tokens = href.split("/")
                        tokens = tokens[:4]
                        tokens[-1] = f"gp/css/summary/print.html?orderID={order_id}"
                        href = "/".join(tokens)
                    return (order_id, href)

                def invoice_link_finder_hidden():
                        # submenu containing order summary takes some time to load after click
                        # search for order summary link and compare order_id
                        # repeat until order_id is different to last order_id
                        summary_links = self.driver.find_elements(By.LINK_TEXT, 
                            self.domain.order_summary)
                        if summary_links:
                            href = summary_links[0].get_attribute('href')
                            order_id = self.get_order_id(href)
                            if order_id != last_order_id:
                                return (order_id, href)
                        return False

                for invoice_link in invoices:
                    if not self.domain.order_summary_hidden:
                        (order_id, href) = invoice_link_finder(invoice_link)
                    else:
                        invoice_link.click()
                        (order_id, href), = self.wait_and_return(invoice_link_finder_hidden)
                    if order_id:
                        if order_id in order_ids_seen:
                            logger.info('Skipping already-seen order id: %r', order_id)
                            continue
                        if order_id in order_ids_downloaded:
                            logger.info('Skipping already-downloaded invoice: %r', order_id)
                            continue
                        logger.info('Found order \'{}\''.format(order_id))
                        invoice_hrefs.append((href, order_id))
                        order_ids_seen.add(order_id)
                        last_order_id = order_id

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
                order_filter, = self.wait_and_locate((By.CSS_SELECTOR, '#time-filter, #orderFilter'))
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

        if digital_orders_menu:
            # orders in separate Digital Orders list (relevant for .COM)
            # other domains list digital orders within the regular order list
            (digital_orders_link,), = self.wait_and_return(
                lambda: self.find_elements_by_descendant_text_match(
                    f'contains(., "{self.domain.digital_orders_menu_text}")', 'a', only_displayed=True)
            )
            scrape_lib.retry(lambda: self.click(digital_orders_link),
                             retry_delay=2)
            retrieve_all_order_groups()

        self.retrieve_invoices(invoice_hrefs)

    def retrieve_invoices(self, invoice_hrefs):
        for href, order_id in invoice_hrefs:
            logger.info('Downloading invoice for order %r', order_id)
            with self.wait_for_page_load():
                self.driver.get(href)

            # For digital orders, Amazon dynamically generates some of the information.
            # Wait until it is all generated.
            def get_source():
                source = self.driver.page_source
                if (
                    self.domain.grand_total in source or
                    self.domain.grand_total_digital in source or
                    self.domain.order_cancelled in source
                ):
                    return source
                elif 'problem loading this order' in source:
                    raise ValueError(f'Failed to retrieve information for order {order_id}')
                elif self.find_visible_elements(By.XPATH, '//input[@type="password"]'):
                    self.finish_login() # fallthrough

                return None

            page_source, = self.wait_and_return(get_source)
            if self.domain.pre_order in page_source and not self.download_preorder_invoices:
                    # Pre-orders don't have enough information to download yet. Skip them.
                    logger.info(f'Skipping pre-order invoice {order_id}')
                    return
            if order_id not in page_source:
                raise ValueError(f'Failed to retrieve information for order {order_id}')

            # extract order date
            def get_date(source, order_id):
                # code blocks taken from beancount-import/amazon-invoice.py
                soup=bs4.BeautifulSoup(source, 'lxml')

                def is_order_placed_node(node):
                    # order placed information in page header (top left)
                    m = re.fullmatch(self.domain.regular_order_placed, node.text.strip())
                    return m is not None
                
                def is_digital_order_row(node):
                    # information in heading of order table
                    if node.name != 'tr':
                        return False
                    m = re.match(self.domain.digital_order, node.text.strip())
                    if m is None:
                        return False
                    try:
                        self.domain.parse_date(m.group(1))
                        return True
                    except:
                        return False

                if order_id.startswith('D'):
                    # digital order
                    node = soup.find(is_digital_order_row)
                    regex = self.domain.digital_order
                else:
                    # regular order
                    node = soup.find(is_order_placed_node)
                    regex = self.domain.regular_order_placed
                
                m = re.fullmatch(regex, node.text.strip())
                if m is None:
                    return None
                order_date = self.domain.parse_date(m.group(1))
                return order_date

            order_date = get_date(page_source, order_id)
            if order_date is None: 
                if self.dir_per_year:
                    raise ValueError(f'Failed to get date for order {order_id}')
                else:
                    # date is not necessary, so just log
                    logger.info(f'Failed to get date for order {order_id}')
            else:
                order_date = order_date.year
            invoice_path = self.get_invoice_path(order_date, order_id)
            if not os.path.exists(os.path.dirname(invoice_path)):
                os.makedirs(os.path.dirname(invoice_path))
            with atomic_write(
                    invoice_path, mode='w', encoding='utf-8',
                    newline='\n', overwrite=True) as f:
                # Write with Unicode Byte Order Mark to ensure content will be properly interpreted as UTF-8
                f.write('\ufeff' + page_source)
            logger.info('  Wrote %s', invoice_path)

    def run(self):
        self.login()
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        self.get_orders(
            regular=self.regular,
            digital_orders_menu=self.digital_orders_menu
            )


def run(**kwargs):
    scrape_lib.run_with_scraper(Scraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(Scraper, **kwargs)
