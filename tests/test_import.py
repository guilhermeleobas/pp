"""Milestone 2 imports: tier-1 stdlib modules executed by the VM, not the host."""
import builtins
import contextlib
import io
import pathlib
import sys

import pytest

import pp

import pp.vm

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWED_ROOTS = (ROOT / "vendor" / "cpython-3.15.2" / "Lib", ROOT / "pp" / "lib")

# module -> source exercising a couple of its functions (prints results).
TIER1 = {
    "operator": "print(operator.add(2, 3), operator.itemgetter(1, 0)('ab'),"
                " operator.attrgetter('real')(5), operator.methodcaller('upper')('x'))",
    "keyword": "print(keyword.iskeyword('def'), keyword.iskeyword('x'),"
               " 'match' in keyword.softkwlist, len(keyword.kwlist) > 30)",
    "types": "print(types.SimpleNamespace(a=1), types.FunctionType.__name__,"
             " isinstance(types.ModuleType('m'), types.ModuleType))",
    "functools": "f = functools.partial(int, base=2)\n"
                 "@functools.lru_cache\ndef fib(n): return n if n < 2 else fib(n-1) + fib(n-2)\n"
                 "print(f('101'), functools.reduce(lambda a, b: a * b, [1, 2, 3, 4]), fib(30),"
                 " fib.cache_info().hits)",
    "collections": "P = collections.namedtuple('P', 'x y')\n"
                   "print(P(1, 2), collections.Counter('abracadabra').most_common(2),"
                   " collections.deque(range(5), maxlen=3), collections.ChainMap({'a': 1}, {'b': 2})['b'])",
    "heapq": "h = []\nfor v in [5, 1, 8, 3]: heapq.heappush(h, v)\n"
             "print([heapq.heappop(h) for _ in range(4)], heapq.nsmallest(2, [9, 4, 7]),"
             " list(heapq.merge([1, 4], [2, 3])))",
    "reprlib": "print(reprlib.repr(list(range(100))), reprlib.repr('x' * 100))",
    "copyreg": "class K: pass\ncopyreg.pickle(K, lambda k: (K, ()))\n"
               "print(K in copyreg.dispatch_table, copyreg.__newobj__.__name__)",
    "itertools": "print(list(itertools.islice(itertools.count(3, 2), 4)),"
                 " list(itertools.permutations('abc', 2))[:3],"
                 " [(k, list(g)) for k, g in itertools.groupby('aabbbc')],"
                 " list(itertools.zip_longest([1], [2, 3], fillvalue=0)))",
}


def capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn()
    return buf.getvalue(), res


def under_allowed_root(path):
    p = pathlib.Path(path).resolve()
    return any(p.is_relative_to(r.resolve()) for r in ALLOWED_ROOTS)


@pytest.mark.parametrize("name", sorted(TIER1))
def test_tier1_module(name):
    src = f"import {name}\n{TIER1[name]}\n"
    host_out, _ = capture(lambda: exec(src, {"__name__": "__main__", "__builtins__": builtins}))
    out, g = capture(lambda: pp.run_source(src))
    assert out == host_out
    mod = g[name]
    assert mod is not sys.modules.get(name)
    assert mod.__name__ == name
    assert under_allowed_root(mod.__file__), mod.__file__
    assert pathlib.Path(mod.__file__).is_absolute()
    assert str(pathlib.Path(mod.__file__).resolve()) == mod.__file__


def test_module_functions_are_vm_functions():
    import pp.function
    g = pp.run_source("import heapq, functools\n")
    assert isinstance(g["heapq"].heappush, pp.function.Function)  # not _heapq's
    assert isinstance(g["functools"].reduce, pp.function.Function)  # not _functools'


@pytest.mark.parametrize("name", ["_heapq", "_functools", "_operator", "_bisect", "_json"])
def test_blocked_accelerator(name):
    __import__(name)  # host has it
    with pytest.raises(ImportError):
        pp.run_source(f"import {name}\n")
    g = pp.run_source(f"try:\n    import {name}\nexcept ImportError as e:\n    r = type(e).__name__\n")
    assert g["r"] in ("ImportError", "ModuleNotFoundError")


def test_missing_module():
    with pytest.raises(ModuleNotFoundError):
        pp.run_source("import does_not_exist_xyz\n")


def test_vm_modules_table():
    vm = pp.vm.VirtualMachine()
    g = pp.run_source("import heapq\nimport collections.abc\n", vm=vm)
    assert vm.modules is not sys.modules
    assert vm.modules["heapq"] is g["heapq"]
    assert "collections" in vm.modules and "collections.abc" in vm.modules
    assert g["collections"].abc is vm.modules["collections.abc"]
    assert "_heapq" not in vm.modules
    # modules are cached: a second import returns the same object
    g2 = pp.run_source("import heapq as h2\n", vm=vm)
    assert g2["h2"] is g["heapq"]
    # a fresh VM (the default) gets a fresh module table
    assert pp.run_source("import heapq\n")["heapq"] is not g["heapq"]


def _write_pkg(tmp_path):
    pkg = tmp_path / "mypkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("from .core import VALUE\nfrom . import util\nINIT = 'init'\n")
    (pkg / "core.py").write_text("VALUE = 41\n")
    (pkg / "util.py").write_text(
        "__all__ = ['double', 'PUBLIC']\nPUBLIC = 1\n_private = 2\nNOT_EXPORTED = 3\n"
        "def double(x):\n    return 2 * x\n")
    (pkg / "sub" / "__init__.py").write_text("")
    (pkg / "sub" / "leaf.py").write_text(
        "from ..core import VALUE\nfrom .. import util\nRESULT = util.double(VALUE + 1)\n")
    (tmp_path / "plain.py").write_text("A = 1\n_B = 2\ndef c():\n    return 3\n")
    return pkg


def test_local_package_relative_imports(tmp_path):
    pkg = _write_pkg(tmp_path)
    main = tmp_path / "main.py"
    main.write_text(
        "import mypkg\nfrom mypkg.sub import leaf\nimport mypkg.sub.leaf as L\n"
        "print(mypkg.VALUE, mypkg.INIT, mypkg.util.double(4), leaf.RESULT, L is leaf)\n"
        "print(mypkg.__package__, leaf.__package__, leaf.__name__, hasattr(mypkg, '__path__'))\n"
        "print(mypkg.__spec__.name)\n")
    out, g = capture(lambda: pp.run_file(str(main)))
    assert out == ("41 init 8 84 True\n"
                   "mypkg mypkg.sub mypkg.sub.leaf True\n"
                   "mypkg\n")
    assert g["mypkg"].__file__ == str((pkg / "__init__.py").resolve())
    assert "mypkg" not in sys.modules


def test_vm_path_and_shared_vm(tmp_path):
    _write_pkg(tmp_path)
    vm = pp.vm.VirtualMachine(path=[str(tmp_path)])
    g = pp.run_source("from mypkg.sub import leaf\nimport mypkg\n", vm=vm)
    assert g["leaf"].RESULT == 84 and vm.modules["mypkg"] is g["mypkg"]
    assert "mypkg.sub.leaf" in vm.modules
    # without the path entry the package is not found
    with pytest.raises(ModuleNotFoundError):
        pp.run_source("import mypkg\n")
    # run_file accepts a VM and reuses its module table
    main = tmp_path / "again.py"
    main.write_text("import mypkg\n")
    assert pp.run_file(str(main), vm=vm)["mypkg"] is g["mypkg"]


def test_relative_import_beyond_top(tmp_path):
    _write_pkg(tmp_path)
    (tmp_path / "mypkg" / "bad.py").write_text("from ... import x\n")
    main = tmp_path / "main2.py"
    main.write_text("import mypkg.bad\n")
    with pytest.raises(ImportError):
        pp.run_file(str(main))


def test_import_star(tmp_path):
    _write_pkg(tmp_path)
    vm = pp.vm.VirtualMachine(path=[str(tmp_path)])
    g = pp.run_source("from mypkg.util import *\nfrom plain import *\n", vm=vm)
    assert g["double"](3) == 6 and g["PUBLIC"] == 1
    assert "NOT_EXPORTED" not in g and "_private" not in g   # __all__ respected
    assert g["A"] == 1 and g["c"]() == 3 and "_B" not in g   # no __all__: skip _names
    # stdlib star import
    g = pp.run_source("from heapq import *\nh = [3, 1]\nheapify(h)\n")
    assert g["h"] == [1, 3] and "heappush" in g


def test_import_from_errors():
    with pytest.raises(ImportError) as ei:
        pp.run_source("from heapq import nope\n")
    assert "nope" in str(ei.value)
