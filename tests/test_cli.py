"""Smoke tests for `python -m pp`."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=120)


def test_run_and_dis(tmp_path):
    f = tmp_path / "prog.py"
    f.write_text("total = 0\nfor i in range(5):\n    total += i * i\nprint(f'total={total!r}')\n")
    host = run(str(f))
    res = run("-m", "pp", "run", str(f))
    assert res.returncode == 0, res.stderr
    assert res.stdout == host.stdout == "total=30\n"

    g = tmp_path / "nested.py"
    g.write_text("def f(a, b):\n    return a * b\nx = 1\n")
    res = run("-m", "pp", "dis", str(g))
    assert res.returncode == 0, res.stderr
    for name in ("RESUME", "MAKE_FUNCTION", "STORE_NAME", "BINARY_OP", "RETURN_VALUE"):
        assert name in res.stdout, name


def test_run_uncaught_exception(tmp_path):
    f = tmp_path / "boom.py"
    f.write_text("print('before')\nd = {}\nd['nope']\n")
    res = run("-m", "pp", "run", str(f))
    assert res.returncode == 1
    assert res.stdout == "before\n"
    assert "Traceback" in res.stderr and "KeyError" in res.stderr and "nope" in res.stderr
