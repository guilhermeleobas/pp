"""The VM's _string helpers match CPython without using the host module."""
import _string as host_string
import pathlib
import sys

import pytest

import pp
import pp.function
from pp.importer import HOST_MODULES


@pytest.fixture(scope="module")
def guest():
    return pp.run_source("import _string\n")["_string"]


def test_import_boundary(guest):
    assert "_string" not in HOST_MODULES
    assert guest is not host_string
    assert pathlib.Path(guest.__file__).resolve().name == "_string.py"
    assert isinstance(guest.formatter_parser, pp.function.Function)
    assert pp.run_source("import _imp\nresult = _imp.is_builtin('_string')\n")["result"] == 0


def consume(iterator):
    # Continue after errors: the C iterators retain their advanced position.
    results = []
    for _ in range(100):
        try:
            results.append(("value", next(iterator)))
        except StopIteration:
            return results
        except ValueError as exc:
            results.append(("error", str(exc)))
    raise AssertionError("iterator did not terminate")


@pytest.mark.parametrize("text", [
    "", "literal", "a{{b}}c", "{0}", "{name!r:>{width}}", "{}{}",
    "a{foo[!}:][0]!s:{{{x}}}}b", "{", "}", "{x", "{x!", "{x!r",
    "{x!rs}", "{x:{y}", "{x{y}", "prefix{{broken}", "{x!\0}",
])
def test_parser_matches_host(guest, text):
    assert consume(guest.formatter_parser(text)) == consume(host_string.formatter_parser(text))


@pytest.mark.parametrize("text", [
    "", "field", "0.foo[123][name]", "١٢.α[٢]", ".a[0]", "[x]",
    "x[]", "x.", "x[", "x[y]z", "x[2][", "a b.c d",
    str(sys.maxsize), str(sys.maxsize + 1), "9" * 40 + "a", "a[" + "9" * 40 + "]",
])
def test_field_name_split_matches_host(guest, text):
    def result(module):
        try:
            first, rest = module.formatter_field_name_split(text)
        except ValueError as exc:
            return "error", str(exc)
        return first, consume(rest)

    assert result(guest) == result(host_string)


@pytest.mark.parametrize("name", ["formatter_parser", "formatter_field_name_split"])
def test_bad_argument(guest, name):
    with pytest.raises(TypeError, match="expected str, got int"):
        getattr(guest, name)(42)


def test_formatter_integration():
    result = pp.run_source('''
import string
class Example:
    name = 'hello'
result = string.Formatter().format(
    '{0.name}: {val!r:>{width}}', Example(), val='x', width=5)
''')
    assert result["result"] == "hello:   'x'"
