import os
from setuptools import setup

with open(os.path.join(os.path.dirname(__file__), 'README.md'), 'r') as f:
    long_description = f.read()

setup(
    name='finance-dl',
    description='Tools for scraping personal financial data.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    version='1.0.2',
    url='https://github.com/jbms/finance-dl',
    author='Jeremy Maitin-Shepard',
    author_email="jeremy@jeremyms.com",
    license='GPLv2',
    packages=["finance_dl"],
    entry_points={
        'console_scripts': [
            'finance-dl = finance_dl.cli:main',
        ],
    },
    python_requires='>=3.5',
    install_requires=[
        'bs4',
        'mintapi>=1.31',
        'ofxclient',
        'selenium',
        'ipython',
        'selenium-requests',
        'chromedriver_installer',
        'beancount>=2.1.2',
        'atomicwrites',
        'jsonschema',
    ],
)
