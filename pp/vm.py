"""Compatibility shim: the eval loop lives in pp.ceval."""

from pp.ceval import VirtualMachine, run_file, run_source  # noqa: F401
from pp.frame import NULL, Frame  # noqa: F401
