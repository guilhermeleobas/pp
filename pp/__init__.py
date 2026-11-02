"""pp: a Python 3.15 bytecode interpreter written in Python."""

from pp.vm import run_file, run_source

__all__ = ["run_source", "run_file"]
