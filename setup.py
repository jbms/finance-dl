# Import setuptools before distutils because setuptools monkey patches
# distutils:
#
# https://github.com/pypa/setuptools/commit/bd1102648109c85c782286787e4d5290ae280abe
import setuptools

import atexit
import distutils.command.build
import os
import tempfile

import setuptools.command.install
import setuptools.command.sdist

with open(os.path.join(os.path.dirname(__file__), 'README.md'), 'r') as f:
    long_description = f.read()


def _setup_temp_egg_info(cmd):
    """Use a temporary directory for the `.egg-info` directory.

  When building an sdist (source distribution) or installing, locate the
  `.egg-info` directory inside a temporary directory so that it
  doesn't litter the source directory and doesn't pick up a stale SOURCES.txt
  from a previous build.
  """
    egg_info_cmd = cmd.distribution.get_command_obj('egg_info')
    if egg_info_cmd.egg_base is None:
        tempdir = tempfile.TemporaryDirectory(dir=os.curdir)
        egg_info_cmd.egg_base = tempdir.name
        atexit.register(tempdir.cleanup)


class SdistCommand(setuptools.command.sdist.sdist):
    def run(self):
        # Build the client bundle if it does not already exist.  If it has
        # already been built but is stale, the user is responsible for
        # rebuilding it.
        _setup_temp_egg_info(self)
        super().run()

    def make_release_tree(self, base_dir, files):
        # Exclude .egg-info from source distribution.  These aren't actually
        # needed, and due to the use of the temporary directory in `run`, the
        # path isn't correct if it gets included.
        files = [x for x in files if '.egg-info' not in x]
        super().make_release_tree(base_dir, files)


class BuildCommand(distutils.command.build.build):
    def finalize_options(self):
        if self.build_base == 'build':
            # Use temporary directory instead, to avoid littering the source directory
            # with a `build` sub-directory.
            tempdir = tempfile.TemporaryDirectory()
            self.build_base = tempdir.name
            atexit.register(tempdir.cleanup)
        super().finalize_options()


class InstallCommand(setuptools.command.install.install):
    def run(self):
        _setup_temp_egg_info(self)
        super().run()


setuptools.setup(
    name='finance-dl',
    # Use setuptools_scm to determine version from git tags
    use_scm_version={
        # It would be nice to include the commit hash in the version, but that
        # can't be done in a PEP 440-compatible way.
        'version_scheme': 'no-guess-dev',
        # Test PyPI does not support local versions.
        'local_scheme': 'no-local-version',
        'fallback_version': '0.0.0',
    },
    description='Tools for scraping personal financial data.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/jbms/finance-dl',
    author='Jeremy Maitin-Shepard',
    author_email="jeremy@jeremyms.com",
    license='GPLv2',
    packages=["finance_dl"],
    entry_points={
        'console_scripts': [
            'finance-dl = finance_dl.cli:main',
            'finance-dl-chromedriver-wrapper = finance_dl.chromedriver_wrapper:main',
        ],
    },
    python_requires='>=3.5',
    setup_requires=['setuptools_scm>=5.0.2'],
    install_requires=[
        'bs4',
        'mintapi>=1.31',
        'ofxclient',
        'selenium',
        'ipython',
        'selenium-requests',
        'chromedriver-binary',
        'beancount>=2.1.2',
        'atomicwrites>=1.3.0',
        'jsonschema',
    ],
    tests_require=[
        'pytest',
    ],
    cmdclass={
        'sdist': SdistCommand,
        'build': BuildCommand,
        'install': InstallCommand,
    },
)
