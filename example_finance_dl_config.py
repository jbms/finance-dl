"""Example configuration file for finance_dl.

Configuration entries are defined by defining a top-level function with a name
beginning with `CONFIG_`.  The portion after the `CONFIG_` prefix is the name
of the configuration.

Rather than hard code your usernames and passwords into this configuration
file, you may instead wish to write some code to retrieve them from some
external password store.
"""

import os

# Directory for persistent browser profiles.
profile_dir = os.path.join(os.getenv('HOME'), '.cache', 'finance_dl')
data_dir = '/path/where/data/will/be/saved'


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


def CONFIG_mint():
    return dict(
        module='finance_dl.mint',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'mint'),
        # profile_dir is optional, but highly recommended to avoid having to
        # enter multi-factor authentication code each time.
        profile_dir=os.path.join(profile_dir, 'mint'),
    )


def CONFIG_healthequity():
    return dict(
        module='finance_dl.healthequity',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        # Use your HealthEquity account number as the last directory component.
        output_directory=os.path.join(data_dir, 'healthequity', '1234567'),

        # profile_dir is optional but highly recommended to avoid having to
        # enter multi-factor authentication code each time.
        profile_dir=os.path.join(profile_dir, 'healthequity'),
    )


def CONFIG_venmo():
    return dict(
        module='finance_dl.venmo',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'venmo'),

        # profile_dir is optional but highly recommended to avoid having to
        # enter multi-factor authentication code each time.
        profile_dir=os.path.join(profile_dir, 'venmo'),
    )


def CONFIG_paypal():
    return dict(
        module='finance_dl.paypal',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'paypal'),
    )


def CONFIG_google_purchases():
    return dict(
        module='finance_dl.google_purchases',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'google_purchases'),
    )


def CONFIG_stockplanconnect():
    return dict(
        module='finance_dl.stockplanconnect',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'stockplanconnect'),
        headless=False,
    )


def CONFIG_pge():
    return dict(
        module='finance_dl.pge',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'pge'),
    )


def CONFIG_comcast():
    return dict(
        module='finance_dl.comcast',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'comcast'),
    )


def CONFIG_ebmud():
    return dict(
        module='finance_dl.ebmud',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'ebmud'),
    )


def CONFIG_anthem():
    return dict(
        module='finance_dl.anthem',
        login_url='https://anthem.com',
        output_directory=os.path.join(data_dir, 'anthem'),
        profile_dir=os.path.join(profile_dir, 'anthem'),
        headless=False,
    )


def CONFIG_waveapps():
    return dict(
        module='finance_dl.waveapps',
        credentials=dict(
            token='XXXXXXXX',
        ),
        output_directory=os.path.join(data_dir, 'waveapps'),
    )


def CONFIG_google_payroll():
    return dict(
        module='finance_dl.ultipro_google',
        credentials={
            'username': 'XXXXXX',
            'password': 'XXXXXX',
        },
        output_directory=os.path.join(data_dir, 'documents', 'Income',
                                      'Google'),

        # profile_dir is optional but recommended.
        profile_dir=os.path.join(profile_dir, 'google_payroll'),

        # Recommended for greater reliability.
        headless=False,
    )
