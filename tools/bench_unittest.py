"""Run chosen CPython tests by dotted name (module.Class or module.Class.test). Executed under pp."""

import sys
import unittest

suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() or result.testsRun else 1)
