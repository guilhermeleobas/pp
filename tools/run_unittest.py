"""Run one CPython test module with unittest. Executed under pp: `python -m pp run tools/run_unittest.py test.test_x`."""

import sys
import unittest

name = sys.argv[1]
unittest.main(module=name, argv=[name], verbosity=1)
