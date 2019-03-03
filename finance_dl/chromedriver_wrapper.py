"""Runs chromedriver in a new process group.

This prevents it from being killed when typing Control+c in an interactive
shell.
"""

import os
import sys
import chromedriver_binary


def main():

    try:
        os.setpgrp()
    except:
        # os.setpgrp not available on Windows
        pass

    executable_path = os.getenv('ACTUAL_CHROMEDRIVER_PATH', 'chromedriver')
    os.execvp(executable_path, [executable_path] + sys.argv[1:])
