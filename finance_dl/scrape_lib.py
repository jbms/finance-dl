import contextlib
import os
import sys
import time
import tempfile
import shutil
import seleniumrequests

from selenium import webdriver
from selenium.webdriver.firefox.firefox_binary import FirefoxBinary
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions
import signal

from selenium.webdriver.remote.webdriver import WebDriver

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


def all_conditions(*conditions):
    return lambda driver: all(condition(driver) for condition in conditions)


def atomic_write_contents(contents, path):
    if isinstance(contents, str):
        contents = contents.encode('utf-8')
    try:
        os.makedirs(os.path.dirname(path))
    except OSError:
        pass
    temp_path = path + '.tmp'
    with open(temp_path, 'wb') as f:
        f.write(contents)
    os.rename(temp_path, path)


def extract_table_data(table, header_names, single_header=False):
    rows = table.find_elements_by_xpath('thead/tr | tbody/tr | tr')
    headers = []
    seen_data = False
    data = []
    for row in rows:
        cell_elements = row.find_elements_by_xpath('th | td')
        cell_values = [x.text.strip() for x in cell_elements]
        is_header_values = [x in header_names for x in cell_values if x]
        if len(is_header_values) == 0:
            is_header = True
        else:
            if any(is_header_values) != all(is_header_values):
                raise RuntimeError('Header mismatch: %r' % (list(
                    zip(is_header_values,
                        [x for x in cell_values if x]),
                )))
            is_header = any(is_header_values)
        if is_header and (not seen_data or not single_header):
            if seen_data:
                headers.clear()
            cur_header = dict()
            headers.append(cur_header)
            cur_col = 0
            for text, el in zip(cell_values, cell_elements):
                colspan = el.get_attribute('colspan')
                if colspan is None:
                    colspan = 1
                else:
                    colspan = int(colspan)
                for span in range(colspan):
                    if text:
                        cur_header[cur_col] = text
                    cur_col += 1
        else:
            seen_data = True
            cur_col = 0
            cur_data = []
            for text, el in zip(cell_values, cell_elements):
                colspan = el.get_attribute('colspan')
                if colspan is None:
                    colspan = 1
                else:
                    colspan = int(colspan)
                header_parts = []
                for span in range(colspan):
                    for header in headers:
                        part = header.get(cur_col)
                        if part is not None:
                            header_parts.append(part)
                    cur_col += 1
                if text:
                    cur_data.append((':'.join(header_parts), text))
            if cur_data:
                data.append(cur_data)
    return data


def find_table_by_headers(scraper, headers):
    tables = None
    for header in headers:
        new_tables = scraper.find_visible_elements_by_descendant_partial_text(
            header, 'table')
        if tables is None:
            tables = set(new_tables)
        else:
            tables &= set(new_tables)
    return tables


# https://stackoverflow.com/questions/8344776/can-selenium-interact-with-an-existing-browser-session
def attach_to_session(executor_url, session_id):
    original_execute = WebDriver.execute

    def new_command_execute(self, command, params=None):
        if command == "newSession":
            # Mock the response
            return {'success': 0, 'value': None, 'sessionId': session_id}
        else:
            return original_execute(self, command, params)

    # Patch the function before creating the driver object
    WebDriver.execute = new_command_execute
    driver = webdriver.Remote(command_executor=executor_url,
                              desired_capabilities={})
    driver.session_id = session_id
    # Replace the patched function with original function
    WebDriver.execute = original_execute
    return driver


def is_displayed(element):
    """Returns `True` if `element` is displayed.

    Ignores StaleElementReferenceException.
    """

    try:
        return element.is_displayed()
    except StaleElementReferenceException:
        return False


class Scraper(object):
    def __init__(self, download_dir=None, connect=None, headless=True,
                 use_seleniumrequests=False, session_id=None,
                 profile_dir=None):

        self.download_dir = download_dir

        if connect is not None and session_id is not None:
            print('Connecting to existing browser: %s %s' % (connect,
                                                             session_id))
            self.driver = attach_to_session(connect, session_id)
            return

        original_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        chrome_options = webdriver.ChromeOptions()
        service_args = []
        chrome_options.add_experimental_option('excludeSwitches', [
            # 'enable-automation',
            # 'load-extension',
            # 'load-component-extension',
            'ignore-certificate-errors',
            # 'test-type',
        ])
        if profile_dir is not None:
            chrome_options.add_argument('user-data-dir=%s' % profile_dir)
            if not os.path.exists(profile_dir):
                os.makedirs(profile_dir)
        prefs = {}
        prefs['plugins.plugins_disabled'] = [
            'Chrome PDF Viewer', 'Chromium PDF Viewer'
        ]
        prefs['plugins.always_open_pdf_externally'] = True
        if download_dir is not None:
            prefs['download.default_directory'] = download_dir
        chrome_options.add_experimental_option('prefs', prefs)
        if headless:
            chrome_options.add_argument('headless')
        if use_seleniumrequests:
            driver_class = seleniumrequests.Chrome
        else:
            driver_class = webdriver.Chrome
        self.driver = driver_class(
            executable_path=os.path.join(
                os.path.dirname(__file__), 'chromedriver_wrapper.py'),
            chrome_options=chrome_options,
            service_args=service_args,
        )
        print(' --connect=%s --session-id=%s' %
              (self.driver.command_executor._url, self.driver.session_id))
        signal.signal(signal.SIGINT, original_sigint_handler)

    def check_after_wait(self):
        """Function called after each wait."""
        pass

    def get_downloaded_file(self):
        names = os.listdir(self.download_dir)
        partial_names = []
        other_names = []
        for name in names:
            if name.endswith('.part') or name.endswith('.crdownload'):
                partial_names.append(name)
            else:
                other_names.append(name)
        if len(other_names) == 0:
            return None
        if len(other_names) > 1:
            raise RuntimeError(
                'More than one downloaded file: %r' % other_names)
        # if len(partial_names) > 0:
        #     raise RuntimeError('Partial download files remain: %r' % partial_names)
        path = os.path.join(self.download_dir, other_names[0])
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) == 0:
            return None
        os.remove(path)
        return other_names[0], data

    # See http://www.obeythetestinggoat.com/how-to-get-selenium-to-wait-for-page-load-after-a-click.html
    @contextlib.contextmanager
    def wait_for_page_load(self, timeout=30):
        old_page = self.driver.find_element_by_tag_name('html')
        yield
        WebDriverWait(self.driver, timeout).until(
            expected_conditions.staleness_of(old_page),
            message='waiting for page to load')
        self.check_after_wait()

    @contextlib.contextmanager
    def wait_for_new_url(self, timeout=30):
        old_url = self.driver.current_url
        yield

        def is_new_url():
            if self.driver.current_url != old_url:
                return True
            raise NoSuchElementException

        self.wait_and_return(is_new_url)

    def wait_and_return(self, *conditions, timeout=30,
                        message='Waiting to match conditions'):
        results = [None]

        def predicate(driver):
            results[0] = tuple(condition() for condition in conditions)
            return all(results[0])

        WebDriverWait(self.driver, timeout).until(predicate, message=message)
        self.check_after_wait()
        return results[0]

    def wait_and_locate(self, *locators, timeout=30, only_displayed=False):
        conditions = []
        for locator in locators:

            def condition(locator=locator):
                element = self.driver.find_element(*locator)
                if only_displayed:
                    if not is_displayed(element):
                        raise NoSuchElementException
                return element

            conditions.append(condition)
        return self.wait_and_return(
            *conditions, timeout=timeout,
            message='Waiting to locate %r' % (locators, ))

    def for_each_frame(self):
        self.driver.switch_to.default_content()

        seen_ids = set()
        def helper(nesting_level=0):
            def handle_frames(frames):
                frames = [f for f in frames if f.id not in seen_ids]
                seen_ids.update(f.id for f in frames)
                for frame in frames:
                    self.driver.switch_to.frame(frame)
                    yield from helper(nesting_level=nesting_level + 1)
                    self.driver.switch_to.parent_frame()
            yield
            for element_name in ['frame', 'iframe']:
                try:
                    other_frames = self.find_visible_elements(
                        By.TAG_NAME, element_name)
                    yield from handle_frames(other_frames)
                except:
                    pass

        yield from helper()

    def find_elements_in_any_frame(self, by_method, locator, predicate=None,
                                   only_displayed=False):
        for frame in self.for_each_frame():
            try:
                for element in self.driver.find_elements(by_method, locator):
                    if only_displayed:
                        try:
                            if not is_displayed(element):
                                continue
                        except:
                            import traceback
                            traceback.print_exc()
                            continue
                    if predicate is None or predicate(element):
                        yield element
            except NoSuchElementException:
                pass

    def find_element_in_any_frame(self, by_method, locator, **kwargs):
        for element in self.find_elements_in_any_frame(by_method, locator,
                                                       **kwargs):
            return element
        raise NoSuchElementException

    def interact(self, global_vars, local_vars):
        import IPython
        # ipshell = InteractiveShellEmbed(banner1='', exit_msg='')
        # ipshell.extension_manager.load_extension('autoreload')
        # ipshell.run_line_magic('autoreload', '2')
        # ipshell.autoindent = False
        ns = global_vars.copy()
        ns.update(local_vars)
        ns['self'] = self
        IPython.terminal.ipapp.launch_new_instance(argv=[], user_ns=ns)
        # ipshell(local_ns=ns)
        # vars = global_vars.copy()
        # vars.update(local_vars)
        # shell = code.InteractiveConsole(vars)
        # shell.interact()

    def find_username_and_password(self):
        passwords = self.driver.find_elements(By.XPATH,
                                              '//input[@type="password"]')
        passwords = [x for x in passwords if is_displayed(x)]
        if len(passwords) == 0:
            raise NoSuchElementException()
        password = passwords[0]
        username = password.find_elements(
            By.XPATH, 'preceding::input[@type="text" or @type="email"]')[-1]
        if not is_displayed(username):
            raise NoSuchElementException()
        return username, password

    def find_username_and_password_in_any_frame(self):
        for frame in self.for_each_frame():
            try:
                return self.find_username_and_password()
            except NoSuchElementException:
                pass
        raise NoSuchElementException()

    def find_visible_elements_by_descendant_partial_text(
            self, text, element_name):
        return self.find_elements_by_descendant_partial_text(
            text, element_name, only_displayed=True)

    def find_elements_by_descendant_partial_text(self, text, element_name,
                                                 only_displayed=False):
        all_elements = self.driver.find_elements_by_xpath(
            "//text()[contains(.,%r)]/ancestor::*[self::%s][1]" %
            (text, element_name))
        if only_displayed:
            return [x for x in all_elements if is_displayed(x)]
        return all_elements

    def find_elements_by_descendant_text_match(self, text_match, element_name,
                                               only_displayed=False):
        all_elements = self.driver.find_elements_by_xpath(
            "//text()[%s]/ancestor::*[self::%s][1]" % (text_match,
                                                       element_name))
        if only_displayed:
            return [x for x in all_elements if is_displayed(x)]
        return all_elements

    def find_visible_elements_by_partial_text(self, text, element_name):
        all_elements = self.driver.find_elements_by_xpath(
            "//%s[contains(.,%r)]" % (element_name, text))
        return [x for x in all_elements if is_displayed(x)]

    def find_visible_elements(self, by_method, locator):
        elements = self.driver.find_elements(by_method, locator)
        return [x for x in elements if is_displayed(x)]

    def click(self, link):
        self.driver.execute_script('arguments[0].scrollIntoView(true);', link)
        link.click()


@contextlib.contextmanager
def temp_scraper(scraper_type, *args, headless=True, connect=None,
                 session_id=None, **kwargs):
    download_dir = tempfile.mkdtemp()
    try:
        scraper = scraper_type(*args, download_dir=download_dir,
                               connect=connect, session_id=session_id,
                               headless=headless, **kwargs)
        try:
            yield scraper
        finally:
            if connect is None:
                try:
                    scraper.driver.quit()
                except Exception as e:
                    print('Error quitting driver: %r' % e)
    finally:
        shutil.rmtree(download_dir)


def retry(func, num_tries=3, retry_delay=0):
    while True:
        try:
            return func()
        except Exception as e:
            import traceback
            traceback.print_exc()
            num_tries -= 1
            if num_tries <= 0:
                raise
        print('Waiting %g seconds before retrying' % (retry_delay, ))
        time.sleep(retry_delay)


def run_with_scraper(scraper_class, **kwargs):
    first_call = True

    def fetch():
        nonlocal first_call
        if not first_call:
            kwargs['headless'] = False
        first_call = False
        with temp_scraper(scraper_class, **kwargs) as scraper:
            scraper.run()

    retry(fetch)


@contextlib.contextmanager
def interact_with_scraper(scraper_class, **kwargs):
    with temp_scraper(scraper_class, **kwargs) as scraper:
        yield dict(
            scraper=scraper,
            self=scraper,
            By=By,
            Select=Select,
            Keys=Keys,
        )
