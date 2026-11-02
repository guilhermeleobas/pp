"""Static guard: pp/ must not lean on CPython internals beyond the host boundary.

Parses every .py file under pp/ with ast (nothing is imported) and checks its
imports against the rules in DESIGN.md ("Rules for code under `pp/`").

Known limitations (a static scan cannot see these): `exec(...)`/`eval(...)` of
strings that import something, and `sys.modules[...]` lookups. Review those by hand.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PP = ROOT / "pp"
LIB = PP / "lib"

# The only host modules code under pp/ may import. Keep in sync with DESIGN.md,
# "Rules for code under `pp/`"; ask before adding to this list.
ALLOWED_HOST_IMPORTS = frozenset({
    "sys", "types", "builtins", "opcode", "dataclasses", "enum", "typing", "io",
    "argparse", "os", "_imp",
})

# Allowed only in these files (DESIGN.md: "_imp (importer only)").
IMP_ONLY_IN = {"pp/importer.py"}

FORBIDDEN = {
    "dis": "`dis` is the test oracle, not a dependency",
    "ctypes": "`ctypes` is forbidden under pp/",
    "_testinternalcapi": "`_testinternalcapi` is a CPython-internal test module",
    "_testcapi": "`_testcapi` is a CPython-internal test module",
}

# References to `__import__` (Name, Attribute, or the string "__import__") are
# flagged everywhere except these exact sites. Key: (file, enclosing scope, kind);
# value: how many such nodes must exist (the test fails if code moves or grows).
#   host-call: `_host_builtins.__import__(spec.name)`, the host-module hand-out
#              (HOST_MODULES) -- the documented host boundary;
#   name/str:  the VM's own guest-visible `__import__` builtin, registered in
#              make_builtins and looked up by IMPORT_NAME. These never reach the host.
EXEMPT_SITES = {
    ("pp/importer.py", "HostLoader.create_module", "host-call"): 1,
    ("pp/builtins.py", "make_builtins", "name"): 1,
    ("pp/ceval.py", "VirtualMachine.IMPORT_NAME", "str"): 1,
}


def _rel(path):
    return path.relative_to(ROOT).as_posix()


def _files(root):
    return sorted(root.rglob("*.py"))


def _guest_modules():
    names = set()
    for p in LIB.iterdir():
        if p.suffix == ".py" or (p.is_dir() and (p / "__init__.py").exists()):
            names.add(p.stem)
    return names


class _Scanner(ast.NodeVisitor):
    def __init__(self, rel, guest_modules):
        self.rel = rel
        self.in_lib = rel.startswith("pp/lib/")
        self.guest_modules = guest_modules
        self.scope = []
        self.problems = []
        self.exempt_hits = {}
        self._skip = set()  # ids of nodes covered by the host-call exemption

    def _add(self, node, msg):
        self.problems.append(f"{self.rel}:{node.lineno}: {msg}")

    def _exempt(self, node, kind):
        key = (self.rel, ".".join(self.scope), kind)
        if key in EXEMPT_SITES:
            self.exempt_hits[key] = self.exempt_hits.get(key, 0) + 1
            return True
        return False

    def _scoped(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scoped

    def visit_Import(self, node):
        for alias in node.names:
            self._check_import(node, alias.name)

    def visit_ImportFrom(self, node):
        if node.level:
            if self.in_lib:
                self._add(node, f"relative import {'.' * node.level + (node.module or '')!r}"
                                " in guest code under pp/lib/")
            return
        self._check_import(node, node.module)

    def _check_import(self, node, full):
        top = full.split(".")[0]
        if top in FORBIDDEN:
            self._add(node, f"forbidden import {full!r}: {FORBIDDEN[top]}")
        elif top == "pp":
            if self.in_lib:
                self._add(node, f"guest module imports host implementation {full!r}")
        elif top == "_imp" and self.rel not in IMP_ONLY_IN:
            self._add(node, f"`_imp` may only be imported by {sorted(IMP_ONLY_IN)}")
        elif top in ALLOWED_HOST_IMPORTS:
            pass
        elif self.in_lib and top in self.guest_modules:
            pass  # another guest module
        else:
            self._add(node, f"import of {full!r} is not in the allowlist (DESIGN.md)")

    def visit_Call(self, node):
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr == "__import__"
                and isinstance(f.value, ast.Name) and f.value.id == "_host_builtins"
                and len(node.args) == 1 and not node.keywords
                and isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "name"
                and isinstance(node.args[0].value, ast.Name) and node.args[0].value.id == "spec"
                and self._exempt(node, "host-call")):
            self._skip.add(id(f))
        elif isinstance(f, ast.Name) and f.id == "import_module":
            self._add(node, "dynamic import by name via import_module(...)")
        elif (isinstance(f, ast.Attribute) and f.attr == "import_module"
              and isinstance(f.value, ast.Name) and f.value.id == "importlib"):
            # Other receivers' `.import_module` is the VM's own Importer method.
            self._add(node, "dynamic import by name via importlib.import_module(...)")
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id == "__import__" and not self._exempt(node, "name"):
            self._add(node, "reference to `__import__` (dynamic import by name)")

    def visit_Attribute(self, node):
        if node.attr == "__import__" and id(node) not in self._skip:
            self._add(node, "reference to `.__import__` (dynamic import by name)")
        self.generic_visit(node)

    def visit_Constant(self, node):
        if node.value == "__import__" and not self._exempt(node, "str"):
            self._add(node, 'string "__import__" (dynamic import by name)')


def _scan(rel, src, guest_modules=None):
    sc = _Scanner(rel, _guest_modules() if guest_modules is None else guest_modules)
    sc.visit(ast.parse(src, filename=rel))
    return sc


def _check_source(rel, src, guest_modules=None):
    return _scan(rel, src, guest_modules).problems


@pytest.mark.parametrize("path", _files(PP), ids=_rel)
def test_host_boundary(path):
    problems = _check_source(_rel(path), path.read_text(encoding="utf-8"))
    assert not problems, "\n" + "\n".join(problems)


def test_exempt_sites_exist_exactly_once():
    hits = {}
    for path in _files(PP):
        for key, n in _scan(_rel(path), path.read_text(encoding="utf-8")).exempt_hits.items():
            hits[key] = hits.get(key, 0) + n
    assert hits == EXEMPT_SITES


def test_files_found():
    assert any(p.name == "importer.py" for p in _files(PP))
    assert _files(LIB), "pp/lib guest modules not found"


HOST_CALL = (
    "class HostLoader:\n"
    "    def create_module(self, spec):\n"
    "        return _host_builtins.__import__(spec.name)\n"
)

# (rel path, source, expected substring of a problem, or None when clean)
CASES = [
    ("pp/x.py", "import sys, types\nfrom enum import Enum\n", None),
    ("pp/x.py", "from . import y\nfrom pp.ceval import z\n", None),
    ("pp/x.py", "import dis", "forbidden import 'dis'"),
    ("pp/x.py", "import ctypes.util", "forbidden import 'ctypes.util'"),
    ("pp/x.py", "from _testcapi import x", "_testcapi"),
    ("pp/x.py", "from _testinternalcapi import x", "_testinternalcapi"),
    ("pp/x.py", "import json", "not in the allowlist"),
    ("pp/x.py", "import collections.abc as c", "not in the allowlist"),
    ("pp/x.py", "def f():\n    if 1:\n        import dis\n", "pp/x.py:3"),
    ("pp/x.py", "import os.path as p", None),
    ("pp/x.py", "import _imp", "`_imp` may only be imported"),
    ("pp/importer.py", "def f():\n    import _imp\n", None),
    ("pp/x.py", "__import__('os')", "__import__"),
    ("pp/x.py", "x = __import__", "__import__"),
    ("pp/x.py", "import builtins\nbuiltins.__import__('os')", ".__import__"),
    ("pp/x.py", "getattr(b, '__import__')", '"__import__"'),
    ("pp/x.py", "b.__dict__['__import__']", '"__import__"'),
    ("pp/x.py", "import_module('os')", "import_module"),
    ("pp/x.py", "import importlib\nimportlib.import_module('os')", "importlib.import_module"),
    ("pp/x.py", "self.importer.import_module('_typing')", None),
    ("pp/importer.py", HOST_CALL, None),
    ("pp/importer.py", HOST_CALL.replace("spec.name", "'ctypes'"), ".__import__"),
    ("pp/importer.py", HOST_CALL.replace("_host_builtins", "other"), ".__import__"),
    ("pp/importer.py", HOST_CALL.replace("create_module", "other_method"), ".__import__"),
    ("pp/importer.py", "_host_builtins.__import__('ctypes')", ".__import__"),
    ("pp/other.py", HOST_CALL, ".__import__"),
    ("pp/lib/m.py", "import sys as _sys\nimport itertools", None),
    ("pp/lib/m.py", "import dis", "forbidden import"),
    ("pp/lib/m.py", "import json", "not in the allowlist"),
    ("pp/lib/m.py", "from . import x", "relative import"),
    ("pp/lib/m.py", "from pp.ceval import x", "host implementation"),
    ("pp/lib/m.py", "__import__('os')", "__import__"),
    ("pp/lib/m.py", "import _imp", "`_imp` may only be imported"),
]


@pytest.mark.parametrize("rel,src,expected", CASES, ids=range(len(CASES)))
def test_check_source(rel, src, expected):
    problems = _check_source(rel, src, guest_modules={"itertools", "m"})
    if expected is None:
        assert problems == []
    else:
        assert problems and any(expected in p for p in problems), problems


def test_guest_modules_only_counts_modules_and_packages():
    names = _guest_modules()
    assert "itertools" in names
    assert "__pycache__" not in names
