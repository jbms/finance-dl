#!/usr/bin/env python
"""Runs chromedriver in a new process group.

This prevents it from being killed when typing Control+c in an interactive
shell.
"""

import os
import sys

os.setpgrp()
executable_path = os.getenv('ACTUAL_CHROMEDRIVER_PATH', 'chromedriver')
os.execvp(executable_path, [executable_path] + sys.argv[1:])
