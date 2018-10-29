"""Retrieves OFX transaction and balance information using the OFX protocol.

This module uses the `ofxclient` Python packaeg to connect directly to financial
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

import bs4
import dateutil.parser
import ofxclient.institution
import ofxclient

from beancount.ingest.importers.ofx import parse_ofx_time

warnings.filterwarnings('ignore', message='split()', module='re')

logger = logging.getLogger('ofx')

def check_path_component(name: str):
    if name == '.' or name == '..':
        return False
    if re.match(r'^[a-z0-9A-Z.\-]+$', name):
        return True
    return False


def download_account_data_starting_from(account: ofxclient.account.Account,
                                        date: datetime.date):
    logger.info('Trying to retrieve data for %s starting at %s.',
                account.number, date)
    num_days = (datetime.date.today() - date).days
    return account.download(days=num_days).read().encode('ascii')


def get_ofx_date_range(data: bytes):
    soup = bs4.BeautifulSoup(io.BytesIO(data), 'html.parser')
    dtstart_nodes = list(soup.find_all('dtstart'))
    dtend_nodes = list(soup.find_all('dtend'))
    if len(dtstart_nodes) == 0 or len(dtend_nodes) == 0:
        logger.debug('Data received: %r', data)
        messages = soup.find_all('message')
        logger.info('Messages: %r', [message.text for message in messages])
        return None
    if len(dtstart_nodes) != 1 or len(dtend_nodes) != 1:
        raise RuntimeError(
            'More than one dtstart or dtend found in OFX document: %s' %
            (data, ))
    dtstart = parse_ofx_time(dtstart_nodes[0].text)
    dtend = parse_ofx_time(dtend_nodes[0].text)
    return dtstart, dtend


def get_earliest_data(account, start_date):
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
        data = download_account_data_starting_from(account, mid)
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
        min_start_date: datetime.date=dateutil.parser.parse(
            '1990-01-01').date()):
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
        date for which the server returns a valid response.
    """

    # Minimum number of days that the server is expected to give data for.
    #
    # We will assume that if we request data starting within this many
    # days of today, that we will receive all available data.
    min_days_retrieved = 20

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
            # fetch_time = datetime.datetime.fromtimestamp(int(match.group(3)))
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
        with open(os.path.join(output_dir, filename), 'wb') as f:
            f.write(data)
        date_ranges.append((date_range[0].date(), date_range[1].date()))
        date_ranges.sort()

    if len(date_ranges) == 0:
        date_range, data = get_earliest_data(account,
                                             start_date=min_start_date)
        save_data(date_range, data)

    def retrieve_more():
        # Find next gap
        i = 0
        cur_range = None
        for i, cur_range in enumerate(date_ranges):
            if (i + 1 < len(date_ranges) and
                    cur_range[1] > date_ranges[i + 1][0]):
                # If end date of current range is greater than start date of
                # next range, then there is no gap.
                continue
            break
        data = download_account_data_starting_from(
            account, cur_range[1] - datetime.timedelta(days=overlap_days))
        date_range = get_ofx_date_range(data)
        if date_range is None:
            logger.warning('Failed to retrieve newer data for account %s',
                           account.number)
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
                          output_dir: str, **kwargs):
    """Attempts to download data for all accounts.

    :param inst: The institution connection.
    :param output_dir: The base output directory in which to store the
        downloaded OFX files.  The data for each account is saved in a
        subdirectory of `output_dir`, with a name equal to the account number.
    :param kwargs: Additional arguments to pass to save_single_account_data.
    """
    accounts = inst.accounts()
    for a in accounts:
        name = a.number
        if not check_path_component(name):
            logger.warning('Account number is invalid path component: %r',
                           name)
            continue
        save_single_account_data(
            account=a, output_dir=os.path.join(output_dir, name), **kwargs)


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
