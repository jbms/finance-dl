"""Handles Google account login."""

import logging
from typing import Dict, cast, Any

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from . import scrape_lib

logger = logging.getLogger('google_login')


def login(scraper: scrape_lib.Scraper, login_url: str):
    logger.info('Initiating log in')
    with scraper.wait_for_page_load():
        scraper.driver.get(login_url)

    cur_url = scraper.driver.current_url
    if not cur_url.startswith('https://accounts.google.com/'):
        logger.info('Assuming already logged in due to url of %s', cur_url)
        return

    logger.info('Waiting for username field')

    def find_username_or_other_account_button():
        username = scraper.find_visible_elements(By.XPATH,
                                                 '//input[@type="email"]')
        other_account = scraper.find_visible_elements(
            By.XPATH, '//div[text()="Use another account"]')
        if len(username) == 1:
            return username[0], None
        if len(other_account) == 1:
            return None, other_account[0]
        return None

    (username, other_account_button
     ), = scraper.wait_and_return(find_username_or_other_account_button)
    if other_account_button:
        scraper.click(other_account_button)
        (username, ), = scraper.wait_and_return(
            lambda: scraper.find_visible_elements(By.XPATH, '//input[@type="email"]')
        )
    logger.info('Entering username')
    credentials = cast(Any, scraper).credentials  # type:  Dict[str, str]
    username.send_keys(credentials['username'])
    username.send_keys(Keys.ENTER)
    logger.info('Waiting for password field')
    (password, ), = scraper.wait_and_return(
        lambda: scraper.find_visible_elements(By.XPATH, '//input[@type="password"]')
    )
    logger.info('Entering password')
    password.send_keys(credentials['password'])
    password.send_keys(Keys.ENTER)
