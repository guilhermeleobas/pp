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

# Milestone 2 opcodes (DESIGN.md "Milestone 2"); the LOAD_FAST*/STORE_FAST*
# families are expanded to every 3.15 opcode with those prefixes.
MILESTONE_2 = frozenset("""
DELETE_FAST LOAD_FAST_AND_CLEAR LOAD_FAST_CHECK MAKE_CELL LOAD_DEREF STORE_DEREF
DELETE_DEREF DELETE_GLOBAL COPY_FREE_VARS LOAD_FROM_DICT_OR_DEREF LOAD_FROM_DICT_OR_GLOBALS
LOAD_LOCALS MAKE_FUNCTION SET_FUNCTION_ATTRIBUTE RETURN_GENERATOR YIELD_VALUE
SEND END_SEND CLEANUP_THROW CALL_FUNCTION_EX CALL_INTRINSIC_1 CALL_INTRINSIC_2
LOAD_BUILD_CLASS LOAD_SUPER_ATTR SETUP_ANNOTATIONS RAISE_VARARGS RERAISE
PUSH_EXC_INFO POP_EXCEPT CHECK_EXC_MATCH CHECK_EG_MATCH WITH_EXCEPT_START
LOAD_SPECIAL IMPORT_NAME IMPORT_FROM GET_LEN MATCH_CLASS MATCH_MAPPING
MATCH_SEQUENCE MATCH_KEYS DICT_MERGE
""".split()) | {op for op in dis.opmap
                if op.startswith(("LOAD_FAST", "STORE_FAST")) and op != "STORE_FAST_MAYBE_NULL"}
SUPPORTED = MILESTONE_1 | MILESTONE_2

# Snippets expected to need features beyond Milestone 2 (feature name).
# Cross-checked against `dis` by test_scope_table.
OUT_OF_SCOPE = {
    "xfail_async": "async def / await",
    "xfail_tstring": "template strings",
}


def missing_opcodes(src, filename):
    stack, ops = [compile(src, filename, "exec")], set()
    while stack:
        c = stack.pop()
        ops |= {i.opname for i in dis.get_instructions(c)}
        stack += [k for k in c.co_consts if isinstance(k, types.CodeType)]
    return sorted(ops - SUPPORTED)


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
    src = 'x = 1\nt = t"{x}"\n'
    assert "BUILD_TEMPLATE" in missing_opcodes(src, "<s>")
    with pytest.raises(pp.errors.UnimplementedOpcode) as ei:
        pp.run_source(src)
    assert "BUILD_INTERPOLATION" in str(ei.value) or "BUILD_TEMPLATE" in str(ei.value)


def test_globals_without_builtins_gets_them():
    g = {"__name__": "m", "x": 2}
    res = pp.run_source("y = x + len([1])\n", globals=g)
    assert res is g and g["y"] == 3
    assert "__builtins__" in g


def test_uncaught_exception_type_and_args():
    with pytest.raises(KeyError) as ei:
        pp.run_source("def f():\n    return {}['k']\nf()\n")
    assert ei.value.args == ("k",)
