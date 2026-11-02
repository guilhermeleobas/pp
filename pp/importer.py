"""The VM's import system, modeled on Lib/importlib/_bootstrap.py
(_find_and_load, _handle_fromlist, _calc___package__, _resolve_name)."""

import builtins as _host_builtins
import os
import sys
import types

from pp.bytecode import compile_source
from pp.errors import _PyErr_GetTopmostException

_PP_DIR = os.path.dirname(os.path.realpath(__file__))
PP_LIB = os.path.join(_PP_DIR, "lib")
HOST_STDLIB = os.path.dirname(os.__file__)
STDLIB = os.path.join(os.path.dirname(_PP_DIR), "vendor", "cpython-3.15.2", "Lib")

# C modules (builtin or extension) that VM code may import from the host.
# Anything not listed here and not found as a .py file raises ImportError, so
# pure-Python fallbacks run. Accelerators (_heapq, _bisect, _functools,
# _operator, _json, _pickle, _datetime, _decimal, _abc, _types, ...) are never
# listed.

# Permanent: the host boundary (runtime services the VM cannot provide itself).
HOST_MODULES_PERMANENT = frozenset({
    "sys",          # served as a VM-side proxy (see _make_sys)
    "builtins",     # served as the VM's own builtins module
    "_imp",
    "_thread",
    "_io",
    "posix",
    "errno",
    "time",
    "marshal",
    "_warnings",
    "_typing",      # TypeVar & co. are object-model types (also used by intrinsics)
    "_codecs",
    "_signal",
    "_opcode",      # opcode metadata tables of the host compiler
    "atexit",
    "_ast",         # AST node types; compilation is borrowed from the host
    "_tokenize",    # tokenizer; same boundary as compile()
})

# Temporary: C modules we intend to replace with pure Python (pp/lib). Each
# entry is tracked debt.
HOST_MODULES_TEMPORARY = frozenset({
    "_collections",  # deque, defaultdict, OrderedDict, _count_elements, _tuplegetter
    "_sre",          # re engine
    "math",
    "_struct",
    "_string",       # string.Formatter helpers
    "_contextvars",
    "_random",
    "binascii",
    "zlib",
    "unicodedata",
    "_locale",
    "select",
    "fcntl",
    "_posixsubprocess",
    "_socket",       # socket (needed by test.support)
    "faulthandler",  # needed by test.support / unittest runner
    "resource",      # needed by test.support
})

HOST_MODULES = HOST_MODULES_PERMANENT | HOST_MODULES_TEMPORARY

_NEEDS_LOADING = object()


class ModuleSpec:
    """Minimal stand-in for importlib.machinery.ModuleSpec."""

    def __init__(self, name, loader, *, origin=None, is_package=False):
        self.name = name
        self.loader = loader
        self.origin = origin
        self.loader_state = None
        self.submodule_search_locations = [os.path.dirname(origin)] if is_package else None
        self.cached = None
        self.has_location = origin is not None
        self._set_fileattr = origin is not None
        self._initializing = False
        self._uninitialized_submodules = []

    @property
    def parent(self):
        if self.submodule_search_locations is None:
            return self.name.rpartition(".")[0]
        return self.name

    def __repr__(self):
        args = [f"name={self.name!r}", f"loader={self.loader!r}"]
        if self.origin is not None:
            args.append(f"origin={self.origin!r}")
        if self.submodule_search_locations is not None:
            args.append(f"submodule_search_locations={self.submodule_search_locations}")
        return f"ModuleSpec({', '.join(args)})"


class SourceLoader:
    """Loads .py files from source and executes them in the VM."""

    def __init__(self, importer, name, path):
        self._importer = importer
        self.name = name
        self.path = path

    def get_filename(self, name=None):
        return self.path

    def get_source(self, name=None):
        with open(self.path, encoding="utf-8") as fh:
            return fh.read()

    def is_package(self, name=None):
        return os.path.basename(self.path) == "__init__.py"

    # importlib loader protocol (used when VM code goes through importlib)
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self._importer.exec_source(module, self.path)

    def __repr__(self):
        return f"<pp.importer.SourceLoader object for {self.name!r}>"


class HostLoader:
    """Hands out a host C module (one of HOST_MODULES)."""

    def create_module(self, spec):
        return _host_builtins.__import__(spec.name)

    def exec_module(self, module):
        pass

    def __repr__(self):
        return "<class 'pp.importer.HostLoader'>"


_HOST_LOADER = HostLoader()


class VMFinder:
    """sys.meta_path entry so that importlib (run by the VM) finds what pp finds."""

    def __init__(self, importer):
        self._importer = importer

    def find_spec(self, name, path=None, target=None):
        return self._importer.find_spec(name, path)

    def invalidate_caches(self):
        self._importer._dir_cache.clear()

    def __repr__(self):
        return "<pp.importer.VMFinder>"


class _VMFrameView:
    """What sys._getframe() returns to VM code: a read-only view of a VM frame."""

    def __init__(self, frame):
        self._frame = frame

    @property
    def f_globals(self):
        return self._frame.globals

    @property
    def f_locals(self):
        fr = self._frame
        return fr.locals if fr.locals is not None else fr.fast_locals_dict()

    @property
    def f_builtins(self):
        return self._frame.builtins

    @property
    def f_code(self):
        return self._frame.code

    @property
    def f_lineno(self):
        return self._frame.lineno()

    @property
    def f_lasti(self):
        return self._frame.lasti

    @property
    def f_back(self):
        prev = self._frame.previous
        return _VMFrameView(prev) if prev is not None else None

    def __repr__(self):
        return f"<frame at {id(self):#x}, code {self._frame.code.co_name}>"


class Importer:
    def __init__(self, vm):
        self.vm = vm
        self._dir_cache = {}
        # Search order (DESIGN.md): pp/lib, the stdlib, the script's directory
        # (inserted by run_file), then the VM's extra `path`.
        self.sys_path = [PP_LIB, STDLIB] + list(vm.path)
        self.sys_module = self._make_sys()
        vm.modules["sys"] = self.sys_module
        vm.modules["_imp"] = self._make_imp()
        vm.modules["builtins"] = vm.builtins_module

    def add_script_dir(self, directory):
        if directory not in self.sys_path:
            self.sys_path.insert(2, directory)

    # --- the VM's _imp module: no frozen modules, builtins only from HOST_MODULES ---

    def _make_imp(self):
        import _imp as host_imp
        mod = types.ModuleType("_imp", host_imp.__doc__)

        def __getattr__(name):
            return getattr(host_imp, name)

        def is_frozen(name, /):
            return False

        def find_frozen(name, /, *, withdata=False):
            return None

        def is_builtin(name, /):
            return host_imp.is_builtin(name) if name in HOST_MODULES else 0

        mod.__dict__.update(__getattr__=__getattr__, is_frozen=is_frozen,
                            find_frozen=find_frozen, is_builtin=is_builtin)
        return mod

    # --- the VM's sys module ---

    def _make_sys(self):
        vm = self.vm
        mod = types.ModuleType("sys", sys.__doc__)

        def __getattr__(name):
            return getattr(sys, name)

        def exc_info():
            exc = _PyErr_GetTopmostException(vm.tstate).exc_value
            if exc is None:
                return (None, None, None)
            return (type(exc), exc, exc.__traceback__)

        def exception():
            return _PyErr_GetTopmostException(vm.tstate).exc_value

        def _getframe(depth=0, /):
            frame = vm.frame
            for _ in range(depth):
                if frame is None:
                    break
                frame = frame.previous
            if frame is None:
                raise ValueError("call stack is not deep enough")
            return _VMFrameView(frame)

        def _getframemodulename(depth=0):
            frame = vm.frame
            for _ in range(depth):
                if frame is None:
                    return None
                frame = frame.previous
            while frame is not None and frame.func is None and frame.previous is not None \
                    and frame.locals is not None and frame.locals is not frame.globals:
                frame = frame.previous  # skip class bodies / exec namespaces
            if frame is None:
                return None
            return frame.globals.get("__name__")

        # Audit hooks stay VM-side: a VM function installed as a host hook would
        # be called for every host audit event, including pp's own.
        audit_hooks = []

        def addaudithook(hook):
            audit_hooks.append(hook)

        def audit(event, *args):
            for hook in list(audit_hooks):
                hook(event, args)

        ns = mod.__dict__
        ns.update(addaudithook=addaudithook, audit=audit)
        # conda-forge adds "| packaged by ... |" to sys.version and patches its own
        # platform.py to parse it; the vendored platform.py cannot, so drop it.
        version = sys.version
        if version.count("|") >= 2:
            head, _, rest = version.partition("|")
            version = head.rstrip() + " " + rest.partition("|")[2].lstrip()
        ns["version"] = version
        ns.update(__getattr__=__getattr__, exc_info=exc_info, exception=exception,
                  _getframe=_getframe, _getframemodulename=_getframemodulename,
                  modules=vm.modules, path=self.sys_path, meta_path=[VMFinder(self)], path_hooks=[],
                  path_importer_cache={},
                  builtin_module_names=tuple(n for n in sys.builtin_module_names
                                             if n in HOST_MODULES))
        return mod

    # --- importlib._bootstrap ---

    def import_(self, name, globals=None, locals=None, fromlist=(), level=0):
        if not isinstance(name, str):
            raise TypeError(f"module name must be str, not {type(name).__name__}")
        if level < 0:
            raise ValueError("level must be >= 0")
        if level == 0:
            module = self._gcd_import(name)
        else:
            package = self._calc___package__(globals if globals is not None else {})
            module = self._gcd_import(name, package, level)
        if not fromlist:
            if level == 0:
                return self._gcd_import(name.partition(".")[0])
            if not name:
                return module
            cut_off = len(name) - len(name.partition(".")[0])
            return self.vm.modules[module.__name__[:len(module.__name__) - cut_off]]
        if hasattr(module, "__path__"):
            return self._handle_fromlist(module, fromlist)
        return module

    def import_module(self, name):
        return self._gcd_import(name)

    def _calc___package__(self, globals):
        package = globals.get("__package__")
        spec = globals.get("__spec__")
        if package is not None:
            return package
        if spec is not None:
            return spec.parent
        package = globals["__name__"]
        if "__path__" not in globals:
            package = package.rpartition(".")[0]
        return package

    def _resolve_name(self, name, package, level):
        bits = package.rsplit(".", level - 1)
        if len(bits) < level:
            raise ImportError("attempted relative import beyond top-level package")
        base = bits[0]
        return f"{base}.{name}" if name else base

    def _gcd_import(self, name, package=None, level=0):
        if level > 0:
            if not isinstance(package, str):
                raise TypeError("__package__ not set to a string")
            if not package:
                raise ImportError("attempted relative import with no known parent package")
            name = self._resolve_name(name, package, level)
        elif not name:
            raise ValueError("Empty module name")
        return self._find_and_load(name)

    def _find_and_load(self, name):
        modules = self.vm.modules
        module = modules.get(name, _NEEDS_LOADING)
        if module is _NEEDS_LOADING:
            return self._find_and_load_unlocked(name)
        if module is None:
            raise ModuleNotFoundError(f"import of {name} halted; None in sys.modules", name=name)
        return module

    def _find_and_load_unlocked(self, name):
        modules = self.vm.modules
        path = None
        parent = name.rpartition(".")[0]
        parent_module = None
        if parent:
            if parent not in modules:
                self._find_and_load(parent)
            if name in modules:
                return modules[name]
            parent_module = modules[parent]
            try:
                path = parent_module.__path__
            except AttributeError:
                path = None
            if path is None:
                raise ModuleNotFoundError(
                    f"No module named {name!r}; {parent!r} is not a package", name=name)
        module = self._load(name, path)
        if parent_module is not None:
            try:
                setattr(parent_module, name.rpartition(".")[2], module)
            except AttributeError:
                pass
        return module

    def _find_source(self, name, path):
        tail = name.rpartition(".")[2]
        dirs = self.sys_path if path is None else path
        if path is None and name.startswith("_sysconfigdata"):
            # Generated at host build time; lives only in the host stdlib dir.
            dirs = list(dirs) + [HOST_STDLIB]
        for directory in dirs:
            if not isinstance(directory, str):
                continue
            entries = self._listdir(directory)
            if tail in entries:
                pkg_dir = os.path.join(directory, tail)
                if "__init__.py" in self._listdir(pkg_dir) \
                        and os.path.isfile(os.path.join(pkg_dir, "__init__.py")):
                    return os.path.join(pkg_dir, "__init__.py"), True
            if tail + ".py" in entries:
                src = os.path.join(directory, tail + ".py")
                if os.path.isfile(src):
                    return src, False
        return None, False

    def _listdir(self, directory):
        """Directory contents, cached until the directory's mtime changes.
        Membership tests on the listing make lookups case-sensitive even on
        case-insensitive filesystems, like FileFinder."""
        try:
            mtime = os.stat(directory).st_mtime
        except OSError:
            return frozenset()
        cached = self._dir_cache.get(directory)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        try:
            entries = frozenset(os.listdir(directory))
        except OSError:
            entries = frozenset()
        self._dir_cache[directory] = (mtime, entries)
        return entries

    def find_spec(self, name, path=None):
        filename, is_package = self._find_source(name, path)
        if filename is None:
            if path is None and name in HOST_MODULES:
                return ModuleSpec(name, _HOST_LOADER, origin="built-in")
            # PEP 420 namespace package: directories without __init__.py.
            tail = name.rpartition(".")[2]
            dirs = [os.path.join(d, tail) for d in (self.sys_path if path is None else path)
                    if isinstance(d, str) and tail in self._listdir(d)
                    and os.path.isdir(os.path.join(d, tail))]
            if dirs:
                spec = ModuleSpec(name, None)
                spec.submodule_search_locations = dirs
                return spec
            return None
        filename = os.path.realpath(filename)
        return ModuleSpec(name, SourceLoader(self, name, filename), origin=filename,
                          is_package=is_package)

    def exec_source(self, module, filename):
        ns = module.__dict__
        ns.setdefault("__builtins__", self.vm.builtins)
        with open(filename, encoding="utf-8") as fh:
            source = fh.read()
        code = compile_source(source, filename)
        self.vm.exec_code(code, ns, ns)

    def _load(self, name, path):
        modules = self.vm.modules
        spec = self.find_spec(name, path)
        if spec is None:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        if spec.loader is _HOST_LOADER:
            module = _HOST_LOADER.create_module(spec)
            modules[name] = module
            return module
        if spec.loader is None:  # namespace package
            module = types.ModuleType(name)
            module.__spec__ = spec
            module.__path__ = list(spec.submodule_search_locations)
            module.__package__ = name
            modules[name] = module
            return module
        module = types.ModuleType(name)
        ns = module.__dict__
        ns["__file__"] = spec.origin
        ns["__loader__"] = spec.loader
        ns["__spec__"] = spec
        ns["__builtins__"] = self.vm.builtins
        if spec.submodule_search_locations is not None:
            ns["__path__"] = list(spec.submodule_search_locations)
            ns["__package__"] = name
        else:
            ns["__package__"] = name.rpartition(".")[0]
        modules[name] = module
        spec._initializing = True
        try:
            self.exec_source(module, spec.origin)
        except BaseException:
            modules.pop(name, None)
            raise
        finally:
            spec._initializing = False
        if name == "types" and not hasattr(module, "LazyImportType"):
            # Lib/types.py has no pure-Python fallback for it; pp never creates
            # lazy-import objects, so the host type is only used in isinstance checks.
            module.LazyImportType = types.LazyImportType
        return modules[name]

    def _handle_fromlist(self, module, fromlist, recursive=False):
        for x in fromlist:
            if not isinstance(x, str):
                where = f"{module.__name__}.__all__" if recursive else "``from list''"
                raise TypeError(f"Item in {where} must be str, not {type(x).__name__}")
            if x == "*":
                if not recursive and hasattr(module, "__all__"):
                    self._handle_fromlist(module, module.__all__, recursive=True)
            elif not hasattr(module, x):
                from_name = f"{module.__name__}.{x}"
                err = None
                try:
                    self._gcd_import(from_name)
                except ModuleNotFoundError as exc:
                    if exc.name == from_name and \
                            self.vm.modules.get(from_name, _NEEDS_LOADING) is not None:
                        continue
                    err = exc
                if err is not None:
                    raise err
        return module

    # --- IMPORT_FROM / import * (Python/ceval.c, intrinsics.c) ---

    def import_from(self, module, name):
        try:
            return getattr(module, name)
        except AttributeError:
            pass
        mod_name = getattr(module, "__name__", None)
        if isinstance(mod_name, str):
            x = self.vm.modules.get(f"{mod_name}.{name}")
            if x is not None:
                return x
        else:
            mod_name = "<unknown module name>"
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None) if spec is not None else None
        if spec is None:
            msg = f"cannot import name {name!r} from {mod_name!r} (unknown location)"
        elif getattr(spec, "_initializing", False):
            msg = (f"cannot import name {name!r} from partially initialized module "
                   f"{mod_name!r} (most likely due to a circular import)")
            if origin:
                msg += f" ({origin})"
        elif origin:
            msg = f"cannot import name {name!r} from {mod_name!r} ({origin})"
        else:
            msg = f"cannot import name {name!r} from {mod_name!r} (unknown location)"
        raise ImportError(msg, name=mod_name, path=origin)

    def import_all_from(self, locals, module):
        try:
            names = module.__all__
            skip_leading_underscores = False
        except AttributeError:
            names = _MISSING_ALL
        if names is _MISSING_ALL:
            try:
                d = module.__dict__
            except AttributeError:
                d = None
            if d is None:
                raise ImportError("from-import-* object has no __dict__ and no __all__")
            names = list(d.keys())
            skip_leading_underscores = True
        for name in names:
            if not isinstance(name, str):
                modname = getattr(module, "__name__", "?")
                where = f"{modname}.__all__" if not skip_leading_underscores \
                    else f"{modname}.__dict__"
                raise TypeError(f"{'Item' if not skip_leading_underscores else 'Key'} in "
                                f"{where} must be str, not {type(name).__name__}")
            if skip_leading_underscores and name.startswith("_"):
                continue
            locals[name] = getattr(module, name)


_MISSING_ALL = object()
