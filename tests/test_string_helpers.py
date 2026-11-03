"""Differential tests for the guest implementation of CPython's _string helpers."""

import pathlib
import sys

import pytest

import pp
import pp.function


# Execute the same code in both interpreters.  In particular, consume one
# element at a time: invalid input may fail only after earlier values were
# returned, or only when advancing the field-name iterator.
PROBE = '''
import _string

def outcome(call):
    try:
        return ("ok", call())
    except Exception as exc:
        return ("error", type(exc).__name__, str(exc))

def consume(iterator):
    result = [iter(iterator) is iterator]
    for unused in range(12):
        item = outcome(lambda: next(iterator))
        result.append(item)
        if item[0] == "error":
            # Exhaustion and error state should remain observable on another next.
            result.append(outcome(lambda: next(iterator)))
            break
    return result

def run():
    call = getattr(_string, helper)
    created = outcome(lambda: call(*args, **kwargs))
    if created[0] == "error":
        return created
    if helper == "formatter_parser":
        return ("ok", consume(created[1]))
    first, rest = created[1]
    return ("ok", first, type(first).__name__, consume(rest))

result = run()
'''


def compare(helper, *args, **kwargs):
    inputs = {"helper": helper, "args": args, "kwargs": kwargs}
    host = dict(inputs)
    exec(PROBE, host)
    guest = dict(inputs)
    pp.run_source(PROBE, "<string-helper-probe>", guest)
    assert guest["result"] == host["result"]


def test_guest_module_is_not_host_accelerator():
    guest = pp.run_source("import _string\n")["_string"]
    assert guest is not sys.modules["_string"]
    assert pathlib.Path(guest.__file__).resolve().is_relative_to(
        (pathlib.Path(__file__).resolve().parent.parent / "pp" / "lib").resolve()
    )
    assert isinstance(guest.formatter_parser, pp.function.Function)
    assert isinstance(guest.formatter_field_name_split, pp.function.Function)


@pytest.mark.parametrize("text", [
    "", "prefix {} suffix", "{0}{name!r:>10}", "a{{b}}c",
    "{x:{width}.{precision}f}", "雪\x00{名[١]!s:宽}",
    "ok {} then {", "before }", "{x!}", "{x:abc",
])
def test_formatter_parser(text):
    compare("formatter_parser", text)


@pytest.mark.parametrize("text", [
    "", "0", "١٢", "obj.arg[key1][2]", "obj[雪].属性",
    "a.", "a[]", "a[x", "a[x]tail", "a[0].good[]",
])
def test_formatter_field_name_split(text):
    compare("formatter_field_name_split", text)


@pytest.mark.parametrize("helper", ["formatter_parser", "formatter_field_name_split"])
@pytest.mark.parametrize("args,kwargs", [
    ((), {}), ((1,), {}), (("x", "y"), {}), ((), {"object": "x"}),
])
def test_argument_errors(helper, args, kwargs):
    compare(helper, *args, **kwargs)


def test_string_subclasses():
    # Define the subclass on the host; both VMs receive the same input object.
    class Text(str):
        def __str__(self):
            raise AssertionError("the helpers must not coerce via __str__")

    compare("formatter_parser", Text("hi {name} end"))
    compare("formatter_field_name_split", Text("12.attr[٣]"))
