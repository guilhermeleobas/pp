"""Static guard: pp/ must not lean on CPython internals beyond the host boundary.

Parses every .py file under pp/ with ast (nothing is imported) and checks its
imports against the rules in DESIGN.md ("Rules for code under `pp/`").
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

# Dynamic imports by name that are the documented host boundary: HostLoader
# hands out the host C modules listed in HOST_MODULES.
DYNAMIC_IMPORT_EXEMPT = {("pp/importer.py", "__import__")}

# Dynamic-import callables. `.import_module` on a receiver other than
# `importlib` is the VM's own Importer method, so only bare names and
# `importlib.import_module` are flagged; `__import__` is flagged on any receiver.
DYNAMIC_NAMES = ("__import__", "import_module")


def _rel(path):
    return path.relative_to(ROOT).as_posix()


def _files(root):
    return sorted(root.rglob("*.py"))


def _imports(tree):
    """Yield (lineno, top-level name or None for relative, full name) for every import."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0], alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield node.lineno, None, "." * node.level + (node.module or "")
            else:
                yield node.lineno, node.module.split(".")[0], node.module


def _dynamic_calls(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in DYNAMIC_NAMES:
            yield node.lineno, f.id
        elif isinstance(f, ast.Attribute):
            if f.attr == "__import__":
                yield node.lineno, f.attr
            elif (f.attr == "import_module" and isinstance(f.value, ast.Name)
                  and f.value.id == "importlib"):
                yield node.lineno, f.attr


def _violations(path):
    rel = _rel(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    in_lib = LIB in path.parents
    guest_modules = {p.stem for p in LIB.glob("*.py")} | {p.name for p in LIB.iterdir() if p.is_dir()}
    out = []
    for lineno, top, full in _imports(tree):
        where = f"{rel}:{lineno}"
        if top is None:
            if in_lib:
                out.append(f"{where}: relative import {full!r} in guest code under pp/lib/")
            continue
        if top in FORBIDDEN:
            out.append(f"{where}: forbidden import {full!r}: {FORBIDDEN[top]}")
        elif top == "pp":
            if in_lib:
                out.append(f"{where}: guest module imports host implementation {full!r}")
        elif top == "_imp" and rel not in IMP_ONLY_IN:
            out.append(f"{where}: `_imp` may only be imported by {sorted(IMP_ONLY_IN)}")
        elif top in ALLOWED_HOST_IMPORTS:
            pass
        elif in_lib and top in guest_modules:
            pass  # another guest module
        else:
            out.append(f"{where}: import of {full!r} is not in the allowlist (DESIGN.md)")
    for lineno, name in _dynamic_calls(tree):
        if (rel, name) not in DYNAMIC_IMPORT_EXEMPT:
            out.append(f"{rel}:{lineno}: dynamic import by name via {name}(...)")
    return out


@pytest.mark.parametrize("path", _files(PP), ids=_rel)
def test_host_boundary(path):
    problems = _violations(path)
    assert not problems, "\n" + "\n".join(problems)


def test_files_found():
    assert any(p.name == "importer.py" for p in _files(PP))
    assert _files(LIB), "pp/lib guest modules not found"
