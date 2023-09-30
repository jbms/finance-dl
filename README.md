Python package for scraping personal financial data from financial
institutions.

[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/finance-dl)](https://pypi.org/project/finance-dl)
[![Build](https://github.com/jbms/finance-dl/workflows/Build/badge.svg)](https://github.com/jbms/finance-dl/actions?query=workflow%3ABuild)

This package may be useful on its own, but is specifically designed to be
used with
[beancount-import](https://github.com/jbms/beancount-import).

Supported data sources
==

- [finance_dl.ofx](finance_dl/ofx.py): uses
  [ofxclient](https://github.com/captin411/ofxclient) to download data
  using the OFX protocol.
- [finance_dl.mint](finance_dl/mint.py): uses
  [mintapi](https://github.com/mrooney/mintapi) to download data from
  the Mint.com website.
- [finance_dl.venmo](finance_dl/venmo.py): downloads transaction and
  balance information from the Venmo.com website
- [finance_dl.paypal](finance_dl/paypal.py): downloads transactions
  from the Paypal.com website
- [finance_dl.amazon](finance_dl/amazon.py): downloads order invoices
  from the Amazon website
- [finance_dl.healthequity](finance_dl/healthequity.py): downloads
  transaction history and balance information from the HealthEquity
  website.
- [finance_dl.google_purchases](finance_dl/google_purchases.py):
  downloads purchases that Google has heuristically extracted from
  Gmail messages.
- [finance_dl.stockplanconnect](finance_dl/stockplanconnect.py):
  downloads PDF documents (including release and trade confirmations)
  from the Morgan Stanley Stockplanconnect website.
- [finance_dl.pge](finance_dl/pge.py): downloads Pacific Gas &
  Electric (PG&E) PDF bills.
- [finance_dl.comcast](finance_dl/comcast.py): downloads Comcast PDF
  bills.
- [finance_dl.ebmud](finance_dl/ebmud.py): downloads East Bay
  Municipal Utility District (EBMUD) water bills.
- [finance_dl.anthem](finance_dl/anthem.py): downloads Anthem
  BlueCross insurance claim statements.
- [finance_dl.waveapps](finance_dl/waveapps.py): downloads receipt
  images and extracted transaction data from
  [Wave](https://waveapps.com), which is a free receipt-scanning
  website/mobile app.
- [finance_dl.ultipro_google](finance_dl/ultipro_google.py): downloads
  Google employee payroll statements in PDF format from Ultipro.
- [finance_dl.usbank](finance_dl/usbank.py): downloads data from US Bank credit cards in OFX format.
- [finance_dl.radiusbank](finance_dl/radiusbank.py): downloads data from Radius Bank in QFX format.
- [finance_dl.schwab](finance_dl/schwab.py): downloads data from Schwab Brokerage accounts in CSV format.
- [finance_dl.gemini](finance_dl/gemini.py): downloads trades, transfers and balances from Gemini crypto exchange using REST API, stores in a custom CSV format.

Setup
==

To install the most recent published package from PyPi, simply type:

```shell
pip install finance-dl
```

To install from a clone of the repository, type:

```shell
pip install .
```

or for development:

```shell
pip install -e .
```

Configuration
==

Create a configuration file called something like `finance_dl_config.py`.
For a complete example of this file and some documentation, 
see [example_finance_dl_config.py](example_finance_dl_config.py).

Refer to the documentation of the individual scraper modules for
further details.

Basic Usage
==

You can run a scraping configuration named `myconfig` as follows:

    python -m finance_dl.cli --config-module example_finance_dl_config --config myconfig

The configuration `myconfig` refers to a function named
`CONFIG_myconfig` in the configuration module.

Make sure that your configuration module is accessible in your Python
`sys.path`.  Since `sys.path` includes the current directory by
default, you can simply run this command from the directory that
contains your configuration module.

By default, the scrapers run fully automatically, and the ones based
on `selenium` and `chromedriver` run in headless mode.  If the initial
attempt for a `selenium`-based scraper fails, it is automatically
retried again with the browser window visible.  This allows you to
manually complete the login process and enter any multi-factor
authentication code that is required.

To debug a scraper, you can run it in interactive mode by specifying
the `-i` command-line argument.  This runs an interactive IPython
shell that lets you manually invoke parts of the scraping process.

Automatic Usage
==

To run multiple configurations at once, and keep track of when each
configuration was last updated, you can use the `finance_dl.update`
tool.

To display the update status, first create a `logs` directory and run:

    python -m finance_dl.update --config-module example_finance_dl_config --log-dir logs status

Initially, this will indicate that none of the configurations have
been updated.  To update a single configuration `myconfig`, run:

    python -m finance_dl.update --config-module example_finance_dl_config --log-dir logs update myconfig

With a single configuration specified, this does the same thing as the
`finance_dl.cli` tool, except that the log messages are written to
`logs/myconfig.txt` and a `logs/myconfig.lastupdate` file is created
if it is successful.

If multiple configurations are specified, as in:

    python -m finance_dl.update --config-module example_finance_dl_config --log-dir logs update myconfig1 myconfig2

then all specified configurations are run in parallel.

To update all configurations, run:

    python -m finance_dl.update --config-module example_finance_dl_config --log-dir logs update --all

Note on Chromedriver Versioning
==

Chromedriver and Chrome are very tightly coupled; their versions need to
match. `finance_dl` uses Chromedriver from the `chromedriver_binary` Python
package (not your system's installed Chromedriver binary). However,
Chromedriver, by default, uses your system's installed version of Chrome.
Depending on how you manage the two installations on your system, this
combination may frequently end up causing `finance_dl` to fail with messages
like

    selenium.common.exceptions.SessionNotCreatedException: Message: session not created: This version of ChromeDriver only supports Chrome version 97
    Current browser version is 96.0.4664.45 with binary path /usr/bin/google-chrome

In this event, you have a few options:

1. Explicitly manage your version of the `chromedriver_binary` Python package
   to match your installed version of Chrome;
1. Explicitly manage your installed version of Chrome to match your version of
   the `chromedriver_binary` Python package; or
1. Install the version of Chrome matching your version of
   `chromedriver_binary` somewhere other than your system's default Chrome
   version, and set the environment variable `CHROMEDRIVER_CHROME_BINARY` to
   point to it. (You can do this from within your finance_dl config script,
   e.g. with a line like `os.environ["CHROMEDRIVER_CHROME_BINARY"] = "/usr/bin/google-chrome-beta"`).

License
==

Copyright (C) 2014-2018 Jeremy Maitin-Shepard.

Distributed under the GNU General Public License, Version 2.0 only.
See [LICENSE](LICENSE) file for details.
