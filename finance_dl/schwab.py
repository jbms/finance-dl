"""Retrieves CSV account transactions/positions from Charles Schwab brokerage.

Uses Selenium and chromedriver to scrape the Schwab website.

Configuration
=============

The following keys may be specified in the configuration dict:

- `credentials`: Required. Must be a dict with `username` and `password` keys.

- `output_directory`: Required. Must be a `str` that specifies the path on the local
filesystem where the output will be written. If the directory does not exist, it will be
created.

- `min_start_date`: Required.  A `datetime.date` object specifying the earliest date at
which to attempt to retrieve data.  If no existing files are present for this account in
the output directory, data is retrieved starting from this date.

- `lot_details`: Optional. A boolean specifying whether or not to download full cost-basis
lot details for all positions. Defaults to `False`.

- `profile_dir`: Optional. If specified, must be a `str` that specifies the path to a
persistent Chrome browser profile to use. This should be a path used solely for this
single configuration; it should not refer to your normal browser profile. If not
specified, a fresh temporary profile will be used each time.

"""
import datetime
import enum
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Set, Tuple
from urllib.parse import urlencode

from finance_dl import scrape_lib
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

def sanitize(x):
    x = x.replace(' ', '_')
    x = re.sub('[^a-zA-Z0-9-_.]', '', x)
    return x

@dataclass(frozen=True)
class Account:
    label: str
    number: str


class PageType(enum.Enum):
    NONE = 0
    HISTORY = 1
    POSITIONS = 2


class SchwabScraper(scrape_lib.Scraper):
    HISTORY_URL = "https://client.schwab.com/Apps/accounts/transactionhistory/"
    POSITIONS_URL = "https://client.schwab.com/Areas/Accounts/Positions"
    TXN_API_URL = "https://client.schwab.com/api/History/Brokerage/ExportTransaction"
    BANK_TXN_API_URL = "https://client.schwab.com/api/History/Banking/ExportBankTransaction"
    POS_API_URL = "https://client.schwab.com/api/PositionV2/PositionsDataV2/Export"
    LOT_API_URL = "https://client.schwab.com/api/Cost/CostData/Export?"
    TRANSACTIONS_FILENAME_RE = re.compile(
        r"(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2}).csv"
    )
    POSITIONS_FILENAME_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2}).csv")
    ONE_DAY = datetime.timedelta(days=1)

    def __init__(
        self,
        credentials: Mapping[str, str],
        output_directory: str,
        min_start_date: datetime.date,
        **kwargs,
    ) -> None:
        self.lot_details = kwargs.pop("lot_details", False)
        super().__init__(use_seleniumrequests=True, **kwargs)
        self.credentials = credentials
        self.output_directory = output_directory
        self.min_start_date = min_start_date
        self.already_got_accounts: Set[Account] = set()
        self.current_page = PageType.NONE

    def run(self) -> None:
        self.load_history_page()

    def load_history_page(self) -> None:
        logger.info("Loading history page.")
        self.driver.get(self.HISTORY_URL)

        self.login_if_needed()
        self.current_page = PageType.HISTORY

        seen: Set[Account] = set()

        while True:
            account = self.select_next_unseen_account(seen)
            if account is None:
                break
            seen.add(account)
            account_dir, positions_dir = self.get_account_dirs(account)
            is_checking = self.download(account, account_dir, positions_dir)
            if self.lot_details and not is_checking:
                self.driver.get(self.POSITIONS_URL)
                self.current_page = PageType.POSITIONS
                self.download_lot_details(positions_dir)
                self.driver.get(self.HISTORY_URL)
                self.current_page = PageType.HISTORY

    def download(self, account: Account, account_dir: str, positions_dir: str) -> bool:
        assert self.current_page == PageType.HISTORY

        logger.info(f"Checking account {account}")

        from_date = self.get_last_fetched_date(account_dir)
        if from_date is None:
            from_date = self.min_start_date
        else:
            from_date += self.ONE_DAY
        # Only download up to yesterday, so we can avoid overlap and not risk missing
        # any transactions.
        to_date = datetime.date.today() - self.ONE_DAY
        is_checking = len(self.find_visible_elements(By.XPATH, '//a[text() = "Realized Gain / Loss"]')) == 0
        if to_date <= from_date:
            logger.info("No dates to download.")
            return is_checking
        if is_checking:
            logger.info("Downloading banking transactions.")
            from_str = from_date.strftime("%m/%d/%Y")
            to_str = to_date.strftime("%m/%d/%Y")
            account_str = account.number.replace("-", "")
            url = self.BANK_TXN_API_URL +\
                f"?AccountId={account_str}" +\
                f"&FromDate={from_str}&ToDate={to_str}&SelectedFilters=AllTransactions&SortBy=Date" +\
                f"&SortOrder=D&RecordsPerPage=400&GetDirection=F&dateRange=All"
            dest_name = f"{from_date.strftime('%Y-%m-%d')}_{to_date.strftime('%Y-%m-%d')}.csv"
            dest_path = os.path.join(account_dir, dest_name)
            self.save_url(url, dest_path)
        else:
            logger.info("Downloading brokerage transactions.")

            num_transaction_types = self.get_num_transaction_types()
            transaction_filter = "|".join(map(str, range(num_transaction_types)))

            from_str = from_date.strftime("%m/%d/%Y")
            to_str = to_date.strftime("%m/%d/%Y")
            url = self.TXN_API_URL +\
                f"?sortSeq=1&sortVal=0&tranFilter={transaction_filter}" +\
                f"&timeFrame=0&filterSymbol=&fromDate={from_str}&toDate={to_str}" +\
                "&exportError=&invalidFromDate=&invalidToDate=&symbolExportValue=" +\
                "&includeOptions=N&displayTotal=true"
            dest_name = f"{from_date.strftime('%Y-%m-%d')}_{to_date.strftime('%Y-%m-%d')}.csv"
            dest_path = os.path.join(account_dir, dest_name)
            self.save_url(url, dest_path)

            logger.info("Downloading positions.")

            url = self.POS_API_URL +\
                "?CalculateDayChangeIntraday=true" +\
                "&firstColumn=symbolandDescriptionStacked&format=csv"
            dest_name = datetime.date.today().strftime("%Y-%m-%d") + ".csv"
            dest_path = os.path.join(positions_dir, dest_name)
            self.save_url(url, dest_path)
        return is_checking

    def download_lot_details(self, pos_dir: str) -> None:
        assert self.current_page == PageType.POSITIONS

        data_attr_to_param = {
            "itemissueid": "itemIssueId",
            "accountindex": "accountindex",
            "quantity": "quantity",
            "viewonly": "isviewonly",
            "price": "price",
            "totalquantity": "positionquantity",
            "marketvalue": "marketvalue",
            "printtitle": "title",
            "iscostincomplete": "iscostincomplete",
            "isprofitlossnotavailable": "istotalprofitlossavailable",
            "profitlossdollar": "profitlossdollar",
            "profitlosspercent": "profitlosspercent",
            "quantitymismatch": "isQuantityMismatch",
        }
        fixed = {
            "ispricenotavailable": "false",
            "costbasismissing": "false",
            "format": "csv",
        }
        lots_dir = os.path.join(pos_dir, "lots", datetime.date.today().strftime("%Y-%m-%d"))
        if os.path.exists(lots_dir):
            logger.info("Lot details for this date already downloaded.")
            return
        else:
            os.makedirs(lots_dir)

        logger.info("Getting lot details.")

        lot_rows = self.get_elements_wait("table.securityTable tr")

        for row in lot_rows:
            symbol = row.get_attribute("data-pulsr-symbol")
            if not symbol:
                continue
            logger.info(f"  ...{symbol}")
            try:
                link = row.find_element(By.CSS_SELECTOR, "td.costBasisColumn a")
            except NoSuchElementException:
                # possibly options on this symbol
                logger.warning(f"Nothing to do on {symbol}")
                continue
            params = fixed.copy()
            for attr, param in data_attr_to_param.items():
                params[param] = link.get_attribute(f"data-{attr}")
            qs = urlencode(params)
            # Necessary because options have spaces, and SPAC warrants have a slash
            symbol = sanitize(symbol)
            dest_name = f"{symbol}.csv"
            dest_path = os.path.join(lots_dir, dest_name)
            self.save_url(f"{self.LOT_API_URL}{qs}", dest_path)

    def save_url(self, url, dest_path):
        response = self.driver.request('GET', url)
        response.raise_for_status()
        with open(dest_path, 'wb') as fout:
            fout.write(response.content)
        logger.info(f"Downloaded {dest_path}")

    def get_num_transaction_types(self) -> int:
        filter_link, = self.get_elements_wait("a.transaction-search-link")
        filter_link.click()

        checkbox_div, = self.get_elements_wait("div.transaction-filter-checkbox")

        checkboxes = checkbox_div.find_elements(By.CSS_SELECTOR, "span")

        modal_close, = self.get_elements_wait("button#modalClose")
        modal_close.click()

        return len(checkboxes)

    def select_next_unseen_account(self, seen: Set[Account]) -> Optional[Account]:
        for link in self.get_account_links():
            account = self.get_account_from_container(link)

            if account is None:
                continue

            if account in seen:
                continue

            link.click()

            def ready(driver):
                sel = self.get_elements_wait("button.account-selector-button")
                if sel:
                    acct = self.get_account_from_container(sel[0])
                    if acct is not None:
                        return acct.number == account.number
                return False

            WebDriverWait(self.driver, 30).until(
                EC.invisibility_of_element_located(
                    (By.CSS_SELECTOR, "sdps-account-selector__header")))
            # Make sure Schwab registers the selection of the new account.
            time.sleep(1)

            return account
        return None

    def get_account_links(self) -> List[Any]:
        selector_button, = self.get_elements_wait("button.account-selector-button")
        selector_button.click()

        return self.get_elements_wait(
            "li.sdps-account-selector__list-item a"
        )

    def get_account_from_container(self, container: Any) -> Optional[Account]:
        spans = container.find_elements(By.CSS_SELECTOR, "span")
        if len(spans) < 2:
            return None
        label_span, number_span = spans[:2]
        number = number_span.text
        if not number:
            return None
        return Account(label=label_span.text, number=number)

    def login_if_needed(self) -> None:
        login_frames = []
        logout_buttons = []

        def predicate(driver):
            login_frames.extend(
                driver.find_elements(By.CSS_SELECTOR, "iframe#lmsSecondaryLogin")
            )
            logout_buttons.extend(
                driver.find_elements(By.CSS_SELECTOR, "button.logout")
            )
            return login_frames or logout_buttons

        WebDriverWait(self.driver, 30).until(
            predicate, message="Did not find either app or login page."
        )

        if logout_buttons:
            logger.info("Already logged in.")
            return

        (login_frame,) = login_frames

        logger.info("Logging in.")

        self.driver.switch_to.frame(login_frame)
        
        username =  self.find_username_and_password()[0]
        username.send_keys(self.credentials["username"])

        logger.info("Looking for password field.")
        
        password = self.find_username_and_password()[1]
        password.send_keys(self.credentials["password"])

        password.send_keys(Keys.ENTER)

        logger.info("Waiting for app to load.")

        self.driver.switch_to.default_content()
        # Just confirm we are logged in.
        self.get_elements_wait("button.logout")

        logger.info("Logged in.")
        return

    def get_account_dirs(self, account: Account) -> Tuple[str, str]:
        acct_dir = os.path.join(self.output_directory, account.number)
        pos_dir = os.path.join(acct_dir, "positions")
        if not os.path.exists(pos_dir):
            os.makedirs(pos_dir)
        return acct_dir, pos_dir

    def get_last_fetched_date(self, account_dir: str) -> Optional[datetime.date]:
        last_date = None
        for entry in os.scandir(account_dir):
            if entry.is_file():
                match = self.TRANSACTIONS_FILENAME_RE.match(entry.name)
                if match:
                    end_str = match.groupdict()["end"]
                    end_date = datetime.datetime.strptime(end_str, "%Y-%m-%d").date()
                    if last_date is None or end_date > last_date:
                        last_date = end_date
        return last_date

    def get_elements_wait(self, selector: str):
        (elements,) = self.wait_and_return(
            lambda: self.get_elements(selector)
        )
        return elements

    def get_elements(self, selector: str):
        return self.find_visible_elements(By.CSS_SELECTOR, selector)


def run(**kwargs):
    scrape_lib.run_with_scraper(SchwabScraper, **kwargs)


def interactive(**kwargs):
    return scrape_lib.interact_with_scraper(SchwabScraper, **kwargs)
