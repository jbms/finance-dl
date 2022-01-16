"""Retrieves OFX transaction and balance information using the OFX protocol.

This module uses the `ofxclient` Python package to connect directly to financial
institutions that support the OFX protocol.

Refer to https://www.ofxhome.com/ to search for OFX connection information for
your financial institution.

Configuration:
==============

The following keys may be specified as part of the configuration dict:

- `ofx_params`: Required.  Must be a `dict` with the following fields:
  - `id`: FI Id value (refer to https://www.ofxhome.com/)
  - `org`: FI Org value (refer to https://www.ofxhome.com/)
  - `url`: FI Url value (refer to https://www.ofxhome.com/)
  - `username`: Username for your account.
  - `password`: Password for your account.
  - `client_args`: Optional.  `dict` of additional arguments to pass to the
    `ofxclient` library.  Some banks, such as Chase, require that the OFX
    version be set to at least 103 and a unique client id be specified.  This
    can be achieved using a `client_args` value of:

        dict(
            ofx_version='103',
            id='64f0e0bfe04f1a2d32cbddc8d30a3017',
        )

    where `id` is a random hex string obtained from e.g.:
    `openssl rand -hex 16`.

- `output_directory`: Required.  Must be a `str` that specifies the path to the
  directory where OFX files are to be written.  If it does not exist, it will be
  created.

- `acct_dir_map`: Optional. A `dict` that maps account numbers as found in the
  OFX output to the directory name to use to hold OFX files for that account.
  You can use this to give mnemonic names to the directories in case you have
  multiple accounts with an institution and don't want to keep track of them
  by number alone. If you supply a mapping for an account, it will be used
  *exactly*; if that mapping is not a valid directory name, finance-dl will
  fail.

- `overlap_days`: Optional.  An `int` that specifies the number of days of
  overlap to use when retrieving additional transactions.  This is intended to
  reduce the chances of transactions being missed (and duplicate transactions
  can easily be filtered when processing the downloaded data).  The default
  value of `2` should be suitable in almost all cases.

- `min_start_date`: Optional.  A `datetime.date` object specifying the earliest
  date at which to attempt to retrieve data.  If no existing files are present
  for this account in the output directory, a binary search is done starting
  from this date to determine the first date for which the server returns a
  valid response.  Otherwise, it is ignored.  Defaults to `1990-01-01`, which
  should be suitable in almost all cases.

- `min_days_retrieved`: Optional.  An `int` specifying the minimum number of
  days for which the server is expected to give data.  It is assumed that if a
  request is made starting no more than this many days from today, that all
  transactions will be received, and no additional request will be made.  The
  default value of `20` should be suitable in most cases, as most servers
  support returning at least 30 days of transactions per request.

Output format:
==============

This module downloads OFX data for all accounts that are accessible using the
specified `username`.  The data for each account is stored in the sub-directory
of the specified `output_directory` with a name equal to the account number.  If
the sub-directory does not exist, it will be created.

Within each account sub-directory, OFX files are saved using the file naming
scheme:

    <start-date>-<end-date>--<fetch-timestamp>.ofx

where <start-date> and <end-date> are in YYYYMMDD format and <fetch-timestamp>
is in seconds since epoch.  The start and end dates reflect the DTSTART and
DTEND fields in the OFX file.

Because some institutions only allow a limited number of days of data to be
retrieved in a single request, this program automatically issues repeated
requests in order to download all available.

If no files have already been downloaded, a binary search is used to find the
oldest point at which data is available.

Requests are issued repeatedly to fill any gaps in the range of downloaded data,
and to extend the range towards the present date.

At least one request extending up to the present date is always issued in order
to ensure up-to-date information is available.

Example:
========

    def CONFIG_vanguard():
        # To determine the correct values for `id`, `org`, and `url` for your
        # financial institution, search on https://www.ofxhome.com/
        ofx_params = {
            'id': '15103',
            'org': 'Vanguard',
            'url': 'https://vesnc.vanguard.com/us/OfxDirectConnectServlet',
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        }
        return dict(
            module='finance_dl.ofx',
            ofx_params=ofx_params,
            output_directory=os.path.join(data_dir, 'vanguard'),
            acct_dir_map={
                '880012345': 'Roth IRA',
                '880045678': 'FooCorp 401(k)',
                '880078901': 'Taxable Account'
            }
        )
"""

import contextlib
import warnings
import datetime
import os
import time
import re
import logging
import io

from atomicwrites import atomic_write
import bs4
import dateutil.parser
import ofxclient.institution
import ofxclient

from beancount.ingest.importers.ofx import parse_ofx_time, find_child

warnings.filterwarnings('ignore', message='split()', module='re')

logger = logging.getLogger('ofx')

# Discover hack. Must have at least 5 seconds between requests.
last_request_time = 0.0

def sanitize_account_name(account_name: str):
    """Replaces any sequence of invalid characters in the account name with a dash.

    Returns the sanitized account name.
    """
    if account_name == '.' or account_name == '..':
        raise ValueError('Invalid account name: %s' % account_name)

    return re.sub('[^a-z0-9A-Z.-]+', '-', account_name)


def download_account_data_starting_from(account: ofxclient.account.Account,
                                        date: datetime.date, slowdown = False):
    logger.info('Trying to retrieve data for %s starting at %s.',
                account.number, date)
    num_days = (datetime.date.today() - date).days
    global last_request_time
    if slowdown:
        tdiff = time.time() - last_request_time
        if tdiff < 5.0: # if less than 5 seconds
            logger.debug('Discover hack: waiting between requests {:1f}'.format(tdiff))
            time.sleep(5)
        else:
            msg = 'ofx.py  last_ts: {:.1f}  time_now: {:.1f}  diff: {:.1f}'.format(last_request_time, time.time(), tdiff)
            logger.debug(msg)
    last_request_time  = time.time()

    return account.download(days=num_days).read().encode('ascii')


def get_ofx_date_range(data: bytes):
    soup = bs4.BeautifulSoup(io.BytesIO(data), 'html.parser')
    dtstart = find_child(soup, 'dtstart', parse_ofx_time)
    dtend = find_child(soup, 'dtend', parse_ofx_time)
    if dtstart is None or dtend is None:
        logger.debug('Data received: %r', data)
        messages = soup.find_all('message')
        logger.info('Messages: %r', [message.text for message in messages])
        return None
    return dtstart, dtend


def get_earliest_data(account, start_date, slowdown = False):
    """Try to retrieve earliest batch of account data, starting at `start_date'.

    Uses binary search to find the earliest point after start_date that yields a valid response.

    Returns ((startdate, enddate), data).
    """
    logger.info(
        'Binary searching to find earliest data available for account %s.',
        account.number)
    lower_bound = start_date
    upper_bound = datetime.date.today()
    valid_data = None
    valid_date_range = None
    while lower_bound + datetime.timedelta(days=1) < upper_bound:
        mid = lower_bound + datetime.timedelta(days=(upper_bound - lower_bound
                                                     ).days // 2)
        data = download_account_data_starting_from(account, mid, slowdown = slowdown)
        date_range = get_ofx_date_range(data)
        if date_range is not None:
            upper_bound = mid
            valid_data = data
            valid_date_range = date_range
        else:
            lower_bound = mid
    if not valid_data:
        raise RuntimeError('Failed to retrieve any data for account: %s' %
                           account.number)
    return valid_date_range, valid_data


def save_single_account_data(
        account: ofxclient.account.Account, output_dir: str, overlap_days=2,
        min_days_retrieved=20,
        min_start_date: datetime.date = dateutil.parser.parse(
            '1990-01-01').date(),
        always_save=True, slowdown = False):
    """Attempts to download all transactions for the specified account.

    :param account: The connected account for which to download data.
    :param output_dir: Path to filesystem directory in which to store the
        downloaded OFX files.  It will be (recursively) created if it does not
        exist.  Saved files will be named
        "<start-date>-<end-date>--<fetch-timestamp>.ofx", where <start-date> and
        <end-date> are in YYYYMMDD format and <fetch-timestamp> is in seconds
        since epoch.  Date ranges corresponding to existing files with this
        naming pattern will not be re-downloaded.
    :param overlap_days: The number of days of overlap to use when retrieving
        additional transactions.  This is intended to reduce the chances of
        transactions being missed (and duplicate transactions can easily be
        filtered when processing the downloaded data).  The default value should
        be suitable in almost all cases.
    :param min_days_retrieved: The minimum number of days the server is expected
        to give data for.  This function assumes that if a request is made
        starting no more than this many days from today, that all transactions
        will be received, and no additional request will be made.  The default
        value should be suitable in most cases, as most servers support
        returning at least 30 days of transactions per request.
    :param min_start_date: If no existing files are present in `output_dir`, a
        binary search is done starting from this date to determine the first
        date for which the server returns a valid response. If this search turns
        up zero transactions, then nothing is saved for this account.
    :param always_save: When a new OFX file is downloaded that contains an
        end-date that matches a previously downloaded file's end-date, this flag
        determines if the new file should be saved or not. By not saving it,
        some transactions that occur later in the day could be missed (until
        additional transactions arrive on later days and they get included in
        the next download). By always saving the file, superfluous files could
        be created.
    """

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    date_format = '%Y%m%d'

    date_ranges = []

    # Read all OFX files in output directory.
    for name in os.listdir(output_dir):
        match = re.match(r'^([0-9]{8})-([0-9]{8})--([0-9]+)\.ofx', name)
        if match is not None:
            start_date = datetime.datetime.strptime(
                match.group(1), date_format).date()
            end_date = datetime.datetime.strptime(match.group(2),
                                                  date_format).date()
            if start_date > end_date:
                logger.warning('Invalid filename: %r',
                               os.path.join(output_dir, name))
                continue
            date_ranges.append((start_date, end_date))
    date_ranges.sort()

    def save_data(date_range, data):
        t = time.time()
        logger.info('Received data %s -- %s', date_range[0], date_range[1])
        filename = ('%s-%s--%d.ofx' % (date_range[0].strftime(date_format),
                                       date_range[1].strftime(date_format), t))
        with atomic_write(os.path.join(output_dir, filename), mode='wb') as f:
            f.write(data)
        date_ranges.append((date_range[0].date(), date_range[1].date()))
        date_ranges.sort()

    if len(date_ranges) == 0:
        try:
            date_range, data = get_earliest_data(account,
                                                 start_date=min_start_date, slowdown = slowdown)
        except RuntimeError as error:
            logger.warning(error)
            return

        save_data(date_range, data)

    def retrieve_more():
        # Find next gap
        cur_range = None
        for i, cur_range in enumerate(date_ranges):
            if (i + 1 < len(date_ranges) and
                    cur_range[1] > date_ranges[i + 1][0]):
                # If end date of current range is greater than start date of
                # next range, then there is no gap.
                continue
            break
        data = download_account_data_starting_from(
            account, cur_range[1] - datetime.timedelta(days=overlap_days), slowdown = slowdown)
        date_range = get_ofx_date_range(data)
        if date_range is None:
            logger.warning('Failed to retrieve newer data for account %s',
                           account.number)
            return False
        if (date_range[1].date() - cur_range[1]).days == 0:
            if always_save:
                save_data(date_range, data)
            return False
        save_data(date_range, data)
        return True

    while True:
        if not retrieve_more():
            break
        if (datetime.date.today() - date_ranges[-1][0]
            ).days <= min_days_retrieved:
            break


def save_all_account_data(inst: ofxclient.institution.Institution,
                          output_dir: str,
                          acct_dir_map: dict={}, **kwargs):
    """Attempts to download data for all accounts.

    :param inst: The institution connection.
    :param output_dir: The base output directory in which to store the
        downloaded OFX files.  The data for each account is saved in a
        subdirectory of `output_dir`, with a name equal to the account number.
    :param kwargs: Additional arguments to pass to save_single_account_data.
    """
    accounts = inst.accounts()
    slowdown = 'Discover' in inst.org
    if slowdown:
        time.sleep(5)
    for a in accounts:
        if a.number in acct_dir_map:
            name = acct_dir_map[a.number]
        else:
            try:
                name = sanitize_account_name(a.number)
            except ValueError:
                name = 'blank'
                logger.warning(f"Account number is invalid path component: {a.number}; using {name}")
        save_single_account_data(
            account=a, output_dir=os.path.join(output_dir, name), slowdown = slowdown, **kwargs)


def connect(params: dict) -> ofxclient.institution.Institution:
    """Connects to an OFX server.

    :param params: A dict containing the following string fields:

            - id: FI Id (see ofxhome.com)

            - org: FI Org (see ofxhome.com)

            - url: FI Url (see ofxhome.com)

            - broker_id: Optional.  FI Broker Id (see ofxhome.com)

            - username: Your username

            - password: Your password

    :returns: A connected ofxclient.institution.Institution object.
    """
    inst = ofxclient.institution.Institution(**params)
    inst.authenticate()
    return inst


def run(ofx_params, output_directory, headless=False, **kwargs):
    """Download non-interactively."""
    del headless
    inst = connect(ofx_params)
    save_all_account_data(inst, output_directory, **kwargs)


@contextlib.contextmanager
def interactive(ofx_params, output_directory, headless=False):
    """Returns variables for interactive session."""
    del headless
    yield dict(
        ofx_params=ofx_params,
        output_directory=output_directory,
        inst=connect(ofx_params),
    )
