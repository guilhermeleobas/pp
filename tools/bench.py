"""Time pp on a small benchmark set and print a table.

    python tools/bench.py                  # every benchmark, best of 1
    python tools/bench.py -n 3 calls regex # chosen benchmarks, best of 3
    python tools/bench.py --host           # also time the host interpreter (scripts only)

Times are CPU seconds (user + system) of the child process. Benchmarks are the scripts in tools/bench/ plus a couple of CPython test modules
(run through tools/bench_unittest.py). Each runs in a fresh `python -m pp run` process.
"""

import argparse
import os
import resource
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "tools", "bench")
UNITTEST = os.path.join(ROOT, "tools", "bench_unittest.py")

# name -> argv after `python -m pp run`
TESTS = {
    "test_textwrap": [UNITTEST, "test.test_textwrap"],
    # All of test_difflib but TestSFpatches.test_recursion_limit, which diffs
    # 2 * sys.getrecursionlimit() lines (pp reports the host's raised limit).
    "test_difflib": [UNITTEST] + [f"test.test_difflib.{c}" for c in (
        "TestWithAscii", "TestAutojunk", "TestSFbugs", "TestDiffer", "TestOutputFormat",
        "TestBytes", "TestInputTypes", "TestJunkAPIs", "TestFindLongest", "TestCloseMatches",
        "TestRestore")] + [f"test.test_difflib.TestSFpatches.{t}" for t in (
        "test_html_diff", "test_make_file_default_charset", "test_make_file_iso88591_charset",
        "test_make_file_usascii_charset_with_nonascii_input",
        "test_strip_trailing_newlines_before_diff")],
}


def benchmarks():
    out = {}
    for f in sorted(os.listdir(BENCH)):
        if f.endswith(".py"):
            out[f[:-3]] = [os.path.join(BENCH, f)]
    out.update(TESTS)
    return out


def run(argv, host=False):
    cmd = [sys.executable] + (argv if host else ["-m", "pp", "run"] + argv)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    dt = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
        return dt, f"exit {proc.returncode}: {tail[0] if tail else ''}"
    return dt, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("-n", type=int, default=1, help="repeats (best time is reported)")
    ap.add_argument("--host", action="store_true", help="also time the scripts on the host")
    ns = ap.parse_args()
    all_b = benchmarks()
    names = ns.names or list(all_b)
    print(f"{'benchmark':<16} {'pp (s)':>9}" + (f" {'host (s)':>9}" if ns.host else ""))
    total = 0.0
    for name in names:
        argv = all_b[name]
        best, err = min(run(argv) for _ in range(ns.n))
        total += best
        line = f"{name:<16} {best:9.2f}"
        if ns.host and name not in TESTS:
            line += f" {min(run(argv, host=True)[0] for _ in range(ns.n)):9.3f}"
        print(line + (f"  {err}" if err else ""), flush=True)
    print(f"{'total':<16} {total:9.2f}")


if __name__ == "__main__":
    main()
