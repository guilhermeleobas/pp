"""The VM's _string helpers are guest code, not the host accelerator.

Behavior is compared with CPython in tests/snippets/lib_string_formatter.py.
"""
import _string as host_string
import pathlib

import pp
import pp.function
from pp.importer import HOST_MODULES


def test_import_boundary():
    guest = pp.run_source("import _string\n")["_string"]
    assert "_string" not in HOST_MODULES
    assert guest is not host_string
    assert pathlib.Path(guest.__file__).resolve().is_relative_to(
        (pathlib.Path(__file__).resolve().parent.parent / "pp" / "lib").resolve()
    )
    assert isinstance(guest.formatter_parser, pp.function.Function)
    assert isinstance(guest.formatter_field_name_split, pp.function.Function)
    assert pp.run_source("import _imp\nresult = _imp.is_builtin('_string')\n")["result"] == 0
