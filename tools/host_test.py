"""Run CPython Lib/test modules on plain host CPython (not under pp) with some C
modules replaced by their pure-Python versions from pp/lib.

    pixi run python tools/host_test.py --swap _struct,binascii test.test_struct test.test_binascii

A fast loop for developing a pp/lib stand-in: the pp run is the final check.
Modules that need the VM itself (gc, _weakref) are out of scope.

Caveat: tests that start a child interpreter (``assert_python_ok`` and friends)
see the C modules, not the swapped ones. In test_struct those are
``test_cache_bytes_vs_str_bb`` and ``test_struct_cleans_up_at_runtime_shutdown``;
test_base64's ``-m base64`` command-line tests do the same.
"""

import argparse
import importlib.abc
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PPLIB = os.path.join(ROOT, "pp", "lib")
VENDOR_LIB = os.path.join(ROOT, "vendor", "cpython-3.15.2", "Lib")


class SwapFinder(importlib.abc.MetaPathFinder):
    """Serve only the swapped names, from pp/lib/<name>.py."""

    def __init__(self, names):
        self.names = set(names)

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.names:
            return None
        return importlib.util.spec_from_file_location(
            fullname, os.path.join(PPLIB, fullname + ".py"))


# Python wrappers whose name is not the swapped name without its leading "_".
EXTRA_WRAPPERS = {
    "binascii": ["base64"],
    "_sre": ["re"],
}


def wrappers_of(name):
    """Loaded modules that wrap the swapped C module (struct for _struct, ...)."""
    base = name.lstrip("_")
    names = {base} | set(EXTRA_WRAPPERS.get(name, ()))
    return [m for m in list(sys.modules)
            if m != name and any(m == w or m.startswith(w + ".") for w in names)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--swap", default="", help="comma-separated module names served from pp/lib")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("tests", nargs="+", help="test modules, e.g. test.test_struct")
    args = ap.parse_args()

    swap = [n for n in args.swap.split(",") if n]
    for n in swap:
        if not os.path.exists(os.path.join(PPLIB, n + ".py")):
            sys.exit(f"host_test: no pp/lib/{n}.py")

    # Tests must match 3.15.2: put the vendored Lib first.
    sys.path.insert(0, VENDOR_LIB)
    # Evict already-imported copies, then make the finder beat BuiltinImporter.
    for n in swap:
        sys.modules.pop(n, None)
    # Evict the Python wrappers too, so they re-import against the swapped module.
    for n in swap:
        for wrapper in wrappers_of(n):
            sys.modules.pop(wrapper, None)
    sys.meta_path.insert(0, SwapFinder(swap))

    for n in swap:
        mod = __import__(n)
        want = os.path.join(PPLIB, n + ".py")
        got = getattr(mod, "__file__", None)
        if got is None or os.path.realpath(got) != os.path.realpath(want):
            sys.exit(f"host_test: {n} came from {got!r}, expected {want}")

    import unittest
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for t in args.tests:
        suite.addTests(loader.loadTestsFromName(t))
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)

    failed, errors = len(result.failures), len(result.errors)
    skipped = len(result.skipped)
    passed = result.testsRun - failed - errors - skipped
    print(f"passed={passed} failed={failed} errors={errors} skipped={skipped}")
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
