"""pp.bytecode.decode vs the `dis` oracle."""
import dis
import pathlib
import sysconfig
import types

import pytest

from pp import bytecode


def iter_code(code):
    stack = [code]
    while stack:
        c = stack.pop()
        yield c
        stack.extend(k for k in c.co_consts if isinstance(k, types.CodeType))


def cache_count(ins):
    return sum(size for _, size, _ in ins.cache_info) if ins.cache_info else 0


def check_code(code):
    for c in iter_code(code):
        d = bytecode.decode(c)
        assert d.code is c
        expected = list(dis.get_instructions(c))
        got = list(d.instructions)
        assert len(got) == len(expected), c
        for g, e in zip(got, expected):
            where = (c.co_qualname, e.offset, e.opname)
            assert g.offset == e.offset, where
            assert g.opcode == e.opcode, where
            assert g.opname == e.opname, where
            assert g.arg == e.arg, where
            assert g.jump_target == e.jump_target, where
            assert g.cache_entries == cache_count(e), where
            assert g.next_offset == g.offset + 2 + 2 * g.cache_entries, where
        exp_tab = [(e.start, e.end, e.target, e.depth, e.lasti)
                   for e in dis._parse_exception_table(c)]
        got_tab = [(e.start, e.end, e.target, e.depth, e.lasti)
                   for e in d.exception_table]
        assert got_tab == exp_tab, c.co_qualname


MANY_CONSTS = "x = [" + ", ".join(f"{i}.5" for i in range(300)) + "]\n"
LONG_JUMP = "if a:\n" + "    b = c + d\n" * 200 + "else:\n    e = 1\n"
LONG_LOOP = "while a:\n" + "    b = c + d\n" * 200

SNIPPETS = {
    "simple": "x = 1\nprint(x + 2)\n",
    "many_consts": MANY_CONSTS,
    "many_names": "".join(f"v{i} = {i}\n" for i in range(300)),
    "long_forward_jump": LONG_JUMP,
    "long_backward_jump": LONG_LOOP,
    "for_loop": "for i in range(3):\n    if i: continue\n    print(i)\nelse:\n    pass\n",
    "try_except": "try:\n    x\nexcept (E, F) as e:\n    y\nelse:\n    z\nfinally:\n    w\n",
    "with": "with a as b, c:\n    d\n",
    "except_star": "try:\n    x\nexcept* E:\n    y\n",
    "generator": "def g(x):\n    yield x\n    y = yield from x\n    return y\n",
    "async": "async def f(x):\n    async with x as y:\n        async for z in y:\n            await z\n",
    "comprehensions": "a = [x for x in y if x]\nb = {k: v for k, v in z}\nc = {x for x in y}\nd = (x for x in y)\n",
    "closure": "def f():\n    x = 1\n    def g():\n        nonlocal x\n        x += 1\n        return x\n    return g\n",
    "class": "class C(B, metaclass=M):\n    a = 1\n    def m(self):\n        return super().m()\n",
    "match": (
        "match p:\n"
        "    case 0 | 1: a\n"
        "    case [x, *rest]: b\n"
        "    case {'k': v, **kw}: c\n"
        "    case Point(x=0, y=yy): d\n"
        "    case str() if p: e\n"
        "    case _: f\n"
    ),
    "fstrings": "f'{a!r:>{w}} {b=} {c!s} {d:.2f}'\n",
    "lambda_defaults": "f = lambda a, b=1, *c, d, e=2, **g: (a, b, c, d, e, g)\n",
}


@pytest.mark.parametrize("name", sorted(SNIPPETS))
def test_snippet(name):
    check_code(bytecode.compile_source(SNIPPETS[name]))


def test_extended_arg_present():
    for src in (MANY_CONSTS, LONG_JUMP, LONG_LOOP):
        code = bytecode.compile_source(src)
        names = [i.opname for i in bytecode.decode(code).instructions]
        assert "EXTENDED_ARG" in names


def test_no_cache_units_and_backward_jump():
    d = bytecode.decode(bytecode.compile_source(SNIPPETS["for_loop"]))
    assert all(i.opname != "CACHE" for i in d.instructions)
    back = [i for i in d.instructions if i.opname == "JUMP_BACKWARD"]
    assert back and all(i.jump_target < i.offset for i in back)


def test_compile_source():
    src = "a = 1\nb = a + 2\n"
    code = bytecode.compile_source(src, "f.py")
    assert isinstance(code, types.CodeType)
    assert code.co_filename == "f.py"
    assert code.co_code == compile(src, "f.py", "exec").co_code
    assert bytecode.compile_source("1 + 2", mode="eval").co_code == compile("1 + 2", "<string>", "eval").co_code
    with pytest.raises(SyntaxError):
        bytecode.compile_source("x = = 1")


def test_at_index_of_and_cache():
    code = bytecode.compile_source(SNIPPETS["try_except"])
    d = bytecode.decode(code)
    assert bytecode.decode(code) is d
    for idx, ins in enumerate(d.instructions):
        assert d.at(ins.offset) is ins
        assert d.index_of(ins.offset) == idx
    starts = {ins.offset for ins in d.instructions}
    bad = [o for o in range(1, d.instructions[-1].offset + 2) if o not in starts]
    assert bad
    for o in bad[:20] + [-2, 10**6]:
        with pytest.raises(KeyError):
            d.at(o)
        with pytest.raises(KeyError):
            d.index_of(o)


def _stdlib_files():
    root = pathlib.Path(sysconfig.get_paths()["stdlib"])
    files = sorted(p for p in root.rglob("*.py") if "site-packages" not in p.parts)
    return [pytest.param(p, id=str(p.relative_to(root))) for p in files]


@pytest.mark.parametrize("path", _stdlib_files())
def test_stdlib(path):
    try:
        code = compile(path.read_bytes(), str(path), "exec")
    except (SyntaxError, ValueError):
        pytest.skip("host cannot compile")
    check_code(code)
