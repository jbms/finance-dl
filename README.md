Python package for scraping personal financial data from financial
institutions.

[![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)](LICENSE)
[![Build Status](https://travis-ci.com/jbms/finance-dl.svg?branch=master)](https://travis-ci.com/jbms/finance-dl)

This package may be useful on its, but is specifically designed to be
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
- [finance_dl.amazon](finance_dl/amazon.py): downloads order invoices
  from the Amazon.com website
- [finance_dl.healthequity](finance_dl/healthequity.py): downloads
  transaction history and balance information from the HealthEquity
  website.

Setup
==

To install the most recent published package from PyPi, simply type:

```shell
pip install finance-dl
```

To install from a clone of the repository, type:

```shell
python setup.py install
```

or for development:

```shell
python setup.py develop
```

Configuration
==

Create a Python file like `example_finance_dl_config.py`.

Refer to the documentation of the individual scraper modules for
details.

Usage
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
the `-i` command-line arugment.  This runs an interactive IPython
shell that lets you manually invoke parts of the scraping process.

License
==

Copyright (C) 2014-2018 Jeremy Maitin-Shepard.

Distributed under the GNU General Public License, Version 2.0 only.
See [LICENSE](LICENSE) file for details.
