"""Differential tests: host exec vs pp.run_source on tests/snippets/*.py."""
import builtins
import contextlib
import dis
import io
import pathlib
import types

import pytest

import pp
import pp.errors
import pp.vm
from pp import bytecode

SNIPPETS = pathlib.Path(__file__).parent / "snippets"

MILESTONE_1 = frozenset("""
RESUME NOP NOT_TAKEN EXTENDED_ARG CACHE LOAD_CONST LOAD_SMALL_INT
LOAD_COMMON_CONSTANT LOAD_NAME STORE_NAME DELETE_NAME LOAD_GLOBAL STORE_GLOBAL
PUSH_NULL POP_TOP COPY SWAP CALL CALL_KW BINARY_OP BINARY_SLICE STORE_SLICE
STORE_SUBSCR DELETE_SUBSCR UNARY_NEGATIVE UNARY_INVERT UNARY_NOT TO_BOOL
COMPARE_OP IS_OP CONTAINS_OP POP_JUMP_IF_TRUE POP_JUMP_IF_FALSE
POP_JUMP_IF_NONE POP_JUMP_IF_NOT_NONE JUMP_FORWARD JUMP_BACKWARD
JUMP_BACKWARD_NO_INTERRUPT GET_ITER FOR_ITER END_FOR POP_ITER BUILD_TUPLE
BUILD_LIST BUILD_SET BUILD_MAP BUILD_SLICE BUILD_STRING LIST_APPEND LIST_EXTEND
SET_ADD SET_UPDATE MAP_ADD DICT_UPDATE UNPACK_SEQUENCE UNPACK_EX FORMAT_SIMPLE
FORMAT_WITH_SPEC CONVERT_VALUE LOAD_ATTR STORE_ATTR DELETE_ATTR RETURN_VALUE
""".split())

# Snippets expected to need features beyond Milestone 1 (feature name).
# Cross-checked against `dis` by test_scope_table.
OUT_OF_SCOPE = {
    "xfail_def": "def / function calls",
    "xfail_listcomp": "comprehensions (fast locals)",
    "xfail_try_except": "exception handling",
}


def missing_opcodes(src, filename):
    stack, ops = [compile(src, filename, "exec")], set()
    while stack:
        c = stack.pop()
        ops |= {i.opname for i in dis.get_instructions(c)}
        stack += [k for k in c.co_consts if isinstance(k, types.CodeType)]
    return sorted(ops - MILESTONE_1)


def _params():
    out = []
    for p in sorted(SNIPPETS.glob("*.py")):
        missing = missing_opcodes(p.read_text(), str(p))
        marks = []
        if missing:
            reason = f"{OUT_OF_SCOPE.get(p.stem, '?')}: needs {', '.join(missing)}"
            marks.append(pytest.mark.xfail(strict=True, reason=reason))
        out.append(pytest.param(p, id=p.stem, marks=marks))
    return out


def run_capture(fn):
    buf = io.StringIO()
    exc = None
    with contextlib.redirect_stdout(buf):
        try:
            g = fn()
        except Exception as e:  # noqa: BLE001
            exc, g = e, None
    return buf.getvalue(), exc, g


def plain(g):
    return {k: repr(v) for k, v in g.items()
            if not k.startswith("__") and type(v) in (int, float, str, list, tuple, dict, bool, bytes)}


@pytest.mark.parametrize("path", _params())
def test_snippet(path):
    src = path.read_text()

    def host():
        g = {"__name__": "__main__", "__builtins__": builtins}
        exec(compile(src, str(path), "exec"), g)
        return g

    h_out, h_exc, h_g = run_capture(host)
    p_out, p_exc, p_g = run_capture(lambda: pp.run_source(src, str(path)))
    if isinstance(p_exc, NotImplementedError) and not isinstance(h_exc, NotImplementedError):
        raise p_exc
    assert p_out == h_out
    assert type(p_exc) is type(h_exc), (h_exc, p_exc)
    if h_exc is None:
        assert plain(p_g) == plain(h_g)


def test_scope_table():
    computed = {p.stem for p in SNIPPETS.glob("*.py")
                if missing_opcodes(p.read_text(), str(p))}
    assert computed == set(OUT_OF_SCOPE)


def test_run_source_returns_globals():
    g = pp.run_source("a = 1\nb = a + 41\nc = [a, b]\n")
    assert isinstance(g, dict)
    assert g["a"] == 1 and g["b"] == 42 and g["c"] == [1, 42]
    assert g["__name__"] == "__main__"
    assert g["__builtins__"] is builtins


def test_run_source_custom_globals():
    g = {"__name__": "m", "__builtins__": builtins, "x": 5}
    res = pp.run_source("y = x * 2\n", globals=g)
    assert res is g and g["y"] == 10


def test_reexports_and_run_file(tmp_path):
    assert pp.run_source is pp.vm.run_source
    assert pp.run_file is pp.vm.run_file
    f = tmp_path / "m.py"
    f.write_text("z = 3 * 7\n")
    assert pp.run_file(str(f))["z"] == 21


def test_run_code_returns_value():
    vm = pp.vm.VirtualMachine()
    assert vm.run_code(bytecode.compile_source("2 * 21", mode="eval")) == 42
    assert vm.run_code(bytecode.compile_source("q = 1")) is None


def test_null_sentinel():
    assert pp.vm.NULL is not None


def test_exceptions_not_wrapped():
    with pytest.raises(ZeroDivisionError) as ei:
        pp.run_source("x = 1\ny = x / 0\n")
    assert type(ei.value) is ZeroDivisionError
    with pytest.raises(NameError):
        pp.run_source("print(nope)\n")


def test_unimplemented_opcode():
    assert issubclass(pp.errors.UnimplementedOpcode, NotImplementedError)
    src = "x = 1\nimport os\n"
    assert "IMPORT_NAME" in missing_opcodes(src, "<s>")
    with pytest.raises(pp.errors.UnimplementedOpcode) as ei:
        pp.run_source(src)
    assert "IMPORT_NAME" in str(ei.value)
