"""The VM's builtins: the host namespace with frame-aware functions overridden
(Python/bltinmodule.c)."""

import builtins as _host_builtins
import types

from pp.bytecode import compile_source
from pp.frame import NULL
from pp.function import Function

_host_super = _host_builtins.super
_MISSING = object()


def _calculate_meta(meta, bases):
    """_PyType_CalculateMetaclass."""
    winner = meta
    for base in bases:
        base_meta = type(base)
        if issubclass(winner, base_meta):
            continue
        if issubclass(base_meta, winner):
            winner = base_meta
            continue
        raise TypeError("metaclass conflict: the metaclass of a derived class must be "
                        "a (non-strict) subclass of the metaclasses of all its bases")
    return winner


def make_builtins(vm) -> types.ModuleType:
    """Build the VM's `builtins` module; its __dict__ is the frames' builtins."""
    mod = types.ModuleType("builtins")
    ns = mod.__dict__
    ns.update(_host_builtins.__dict__)

    def _caller():
        frame = vm.frame
        if frame is None:
            raise SystemError("no current frame")
        return frame

    def _locals_of(frame):
        if frame.locals is not None:
            return frame.locals
        return frame.fast_locals_dict()

    def __build_class__(func, name, /, *bases, metaclass=_MISSING, **kwds):
        if not isinstance(func, Function):
            raise TypeError("__build_class__: func must be a function")
        if not isinstance(name, str):
            raise TypeError("__build_class__: name is not a string")
        orig_bases = bases
        bases = types.resolve_bases(bases)
        if metaclass is _MISSING:
            meta = type(bases[0]) if bases else type
            isclass = True
        else:
            meta = metaclass
            isclass = isinstance(meta, type)
        if isclass:
            meta = _calculate_meta(meta, bases)
        prepare = getattr(meta, "__prepare__", _MISSING)
        if prepare is _MISSING:
            namespace = {}
        else:
            namespace = vm.call(prepare, (name, bases), kwds)
        if not hasattr(type(namespace), "__getitem__"):
            who = meta.__name__ if isclass else "<metaclass>"
            raise TypeError(f"{who}.__prepare__() must return a mapping, "
                            f"not {type(namespace).__name__}")
        cell = vm.run_class_body(func, namespace)
        if bases is not orig_bases:
            namespace["__orig_bases__"] = orig_bases
        cls = vm.call(meta, (name, bases, namespace), kwds)
        if isinstance(cls, type) and isinstance(cell, types.CellType):
            try:
                cell_cls = cell.cell_contents
            except ValueError:
                cell_cls = _MISSING
            if cell_cls is not cls:
                if cell_cls is _MISSING:
                    raise RuntimeError(
                        f"__class__ not set defining {name!r} as {cls!r}. "
                        "Was __classcell__ propagated to type.__new__?")
                raise TypeError(f"__class__ set to {cell_cls!r} defining {name!r} as {cls!r}")
        return cls

    class super(_host_super):
        def __init__(self, *args):
            if not args:
                args = _super_args(_caller())
            _host_super.__init__(self, *args)

    super.__module__ = "builtins"
    super.__qualname__ = "super"

    def _super_args(frame):
        """super_init_without_args (Objects/typeobject.c)."""
        co = frame.code
        if co.co_argcount == 0:
            raise RuntimeError("super(): no arguments")
        firstarg = frame.localsplus[0]
        if co.co_varnames and co.co_varnames[0] in co.co_cellvars \
                and isinstance(firstarg, types.CellType):
            try:
                firstarg = firstarg.cell_contents
            except ValueError:
                firstarg = NULL
        if firstarg is NULL:
            raise RuntimeError("super(): arg[0] deleted")
        try:
            k = co.co_freevars.index("__class__")
        except ValueError:
            raise RuntimeError("super(): __class__ cell not found") from None
        cell = frame.localsplus[frame.first_free + k]
        try:
            cls = cell.cell_contents
        except ValueError:
            cls = _MISSING
        if cls is _MISSING:
            raise RuntimeError("super(): empty __class__ cell")
        if not isinstance(cls, type):
            raise RuntimeError(f"super(): __class__ is not a type ({type(cls).__name__})")
        return cls, firstarg

    def globals():
        return _caller().globals

    def locals():
        return _locals_of(_caller())

    def vars(*args):
        if not args:
            return _locals_of(_caller())
        if len(args) > 1:
            raise TypeError(f"vars expected at most 1 argument, got {len(args)}")
        return _host_builtins.vars(args[0])

    def dir(*args):
        if not args:
            return sorted(_locals_of(_caller()).keys())
        return _host_builtins.dir(*args)

    def _resolve_namespaces(fname, globals_, locals_):
        if globals_ is None:
            frame = _caller()
            globals_ = frame.globals
            if locals_ is None:
                locals_ = _locals_of(frame)
        elif locals_ is None:
            locals_ = globals_
        if not isinstance(globals_, dict):
            raise TypeError(f"{fname}() globals must be a dict, not {type(globals_).__name__}")
        if "__builtins__" not in globals_:
            globals_["__builtins__"] = ns  # the dict, as PyEval_GetBuiltins() returns
        return globals_, locals_

    def exec(source, globals=None, locals=None, /, *, closure=None):
        globals, locals = _resolve_namespaces("exec", globals, locals)
        if isinstance(source, types.CodeType):
            code = source
        elif isinstance(source, (str, bytes, bytearray)):
            if not isinstance(source, str):
                source = bytes(source).decode()
            code = compile_source(source, "<string>", "exec")
        else:
            raise TypeError("exec() arg 1 must be a string, bytes or code object")
        return vm.exec_code(code, globals, locals, closure)

    def eval(source, globals=None, locals=None, /):
        globals, locals = _resolve_namespaces("eval", globals, locals)
        if isinstance(source, types.CodeType):
            code = source
        elif isinstance(source, (str, bytes, bytearray)):
            if not isinstance(source, str):
                source = bytes(source).decode()
            code = compile_source(source.lstrip(" \t"), "<string>", "eval")
        else:
            raise TypeError("eval() arg 1 must be a string, bytes or code object")
        return vm.exec_code(code, globals, locals, None)

    def __import__(name, globals=None, locals=None, fromlist=(), level=0):
        return vm.importer.import_(name, globals, locals, fromlist, level)

    def print(*args, sep=" ", end="\n", file=None, flush=False):
        if file is None:
            file = vm.sys_module.stdout
        return _host_builtins.print(*args, sep=sep, end=end, file=file, flush=flush)

    for f in (__build_class__, globals, locals, vars, dir, exec, eval, __import__, print):
        f.__module__ = "builtins"
        f.__qualname__ = f.__name__
        ns[f.__name__] = f
    ns["super"] = super
    return mod
