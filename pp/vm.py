"""The eval loop and opcode handlers. Spec: CPython 3.15 Python/bytecodes.c."""

import builtins as _builtins
import os
import sys
import types

import opcode as _opcode

from pp.bytecode import compile_source
from pp.errors import UnimplementedOpcode
from pp.frame import NULL, Frame  # noqa: F401  (NULL is part of the pp.vm API)
from pp.function import Function, bind_arguments, builtins_from_globals
from pp.generator import AsyncGenerator, Coroutine, ExcInfo, Generator

_EXIT = object()  # returned by a handler to leave the eval loop

CO_OPTIMIZED = 0x1
CO_GENERATOR = 0x20
CO_COROUTINE = 0x80
CO_ITERABLE_COROUTINE = 0x100
CO_ASYNC_GENERATOR = 0x200

_TPFLAGS_SEQUENCE = 1 << 5
_TPFLAGS_MAPPING = 1 << 6
_TPFLAGS_MATCH_SELF = 1 << 22

if sys.getrecursionlimit() < 10000:
    sys.setrecursionlimit(10000)


# --- BINARY_OP table (index = oparg, order from opcode._nb_ops) ---

def _iadd(a, b): a += b; return a
def _iand(a, b): a &= b; return a
def _ifloordiv(a, b): a //= b; return a
def _ilshift(a, b): a <<= b; return a
def _imatmul(a, b): a @= b; return a
def _imul(a, b): a *= b; return a
def _imod(a, b): a %= b; return a
def _ior(a, b): a |= b; return a
def _ipow(a, b): a **= b; return a
def _irshift(a, b): a >>= b; return a
def _isub(a, b): a -= b; return a
def _itruediv(a, b): a /= b; return a
def _ixor(a, b): a ^= b; return a


_NB_FUNCS = {
    "NB_ADD": lambda a, b: a + b,
    "NB_AND": lambda a, b: a & b,
    "NB_FLOOR_DIVIDE": lambda a, b: a // b,
    "NB_LSHIFT": lambda a, b: a << b,
    "NB_MATRIX_MULTIPLY": lambda a, b: a @ b,
    "NB_MULTIPLY": lambda a, b: a * b,
    "NB_REMAINDER": lambda a, b: a % b,
    "NB_OR": lambda a, b: a | b,
    "NB_POWER": lambda a, b: a ** b,
    "NB_RSHIFT": lambda a, b: a >> b,
    "NB_SUBTRACT": lambda a, b: a - b,
    "NB_TRUE_DIVIDE": lambda a, b: a / b,
    "NB_XOR": lambda a, b: a ^ b,
    "NB_INPLACE_ADD": _iadd,
    "NB_INPLACE_AND": _iand,
    "NB_INPLACE_FLOOR_DIVIDE": _ifloordiv,
    "NB_INPLACE_LSHIFT": _ilshift,
    "NB_INPLACE_MATRIX_MULTIPLY": _imatmul,
    "NB_INPLACE_MULTIPLY": _imul,
    "NB_INPLACE_REMAINDER": _imod,
    "NB_INPLACE_OR": _ior,
    "NB_INPLACE_POWER": _ipow,
    "NB_INPLACE_RSHIFT": _irshift,
    "NB_INPLACE_SUBTRACT": _isub,
    "NB_INPLACE_TRUE_DIVIDE": _itruediv,
    "NB_INPLACE_XOR": _ixor,
    "NB_SUBSCR": lambda a, b: a[b],
}
BINARY_OPS = tuple(_NB_FUNCS[name] for name, _ in _opcode._nb_ops)

# COMPARE_OP: op = oparg >> 5, indexes opcode.cmp_op ('<', '<=', '==', '!=', '>', '>=')
COMPARE_OPS = (
    lambda a, b: a < b,
    lambda a, b: a <= b,
    lambda a, b: a == b,
    lambda a, b: a != b,
    lambda a, b: a > b,
    lambda a, b: a >= b,
)

# CONVERT_VALUE: FVC_STR=1, FVC_REPR=2, FVC_ASCII=3
CONVERSIONS = (None, str, repr, ascii)

COMMON_CONSTANTS = tuple(_opcode._common_constants)

# Template strings: host object-model types (string.templatelib).
_Template = type(t"")
_Interpolation = type(t"{0}".interpolations[0])
_CONVERSION_CHARS = (None, "s", "r", "a")
SPECIAL_METHODS = tuple(_opcode._special_method_names)

_SPECIAL_ERRORS = {
    "__enter__": "'{}' object does not support the context manager protocol (missed __enter__ method)",
    "__exit__": "'{}' object does not support the context manager protocol (missed __exit__ method)",
    "__aenter__": "'{}' object does not support the asynchronous context manager protocol "
                  "(missed __aenter__ method)",
    "__aexit__": "'{}' object does not support the asynchronous context manager protocol "
                 "(missed __aexit__ method)",
}
_SPECIAL_SUGGEST = {
    "__enter__": ("__aenter__", " but it supports the asynchronous context manager protocol. "
                  "Did you mean to use 'async with'?"),
    "__exit__": ("__aexit__", " but it supports the asynchronous context manager protocol. "
                 "Did you mean to use 'async with'?"),
    "__aenter__": ("__enter__", " but it supports the context manager protocol. "
                   "Did you mean to use 'with'?"),
    "__aexit__": ("__exit__", " but it supports the context manager protocol. "
                  "Did you mean to use 'with'?"),
}

CANNOT_CATCH_MSG = "catching classes that do not inherit from BaseException is not allowed"
CANNOT_EXCEPT_STAR_EG = "catching ExceptionGroup with except* is not allowed. Use except instead."

_MISSING = object()
_FUNCTION_TYPES = (Function, types.FunctionType, types.BuiltinFunctionType,
                   types.MethodDescriptorType, types.WrapperDescriptorType)


def _name_error(name: str) -> NameError:
    return NameError(f"name '{name}' is not defined", name=name)


_TYPE_NEW = type.__new__
_IMPLICIT_WRAPPERS = (("__new__", staticmethod), ("__init_subclass__", classmethod),
                      ("__class_getitem__", classmethod))


def _wrap_type_namespace(ns):
    """type_new_set_attrs (Objects/typeobject.c) turns plain functions named
    __new__ / __init_subclass__ / __class_getitem__ into static/class methods,
    but only checks PyFunction_Check; do the same for VM functions. Like
    type.__new__, works on a copy and leaves the caller's namespace alone."""
    if not isinstance(ns, dict):
        return ns
    repl = {name: wrap(ns[name]) for name, wrap in _IMPLICIT_WRAPPERS
            if type(ns.get(name)) is Function}
    if not repl:
        return ns
    ns = dict(ns)
    ns.update(repl)
    return ns


def _type_fullname(tp: type) -> str:
    mod = tp.__module__
    if mod in ("builtins", "__main__") or not isinstance(mod, str):
        return tp.__qualname__
    return f"{mod}.{tp.__qualname__}"


def _function_str(func) -> str:
    """_PyObject_FunctionStr."""
    qualname = getattr(func, "__qualname__", None)
    if qualname is None:
        return str(func)
    module = getattr(func, "__module__", None)
    if module is not None and module != "builtins":
        return f"{module}.{qualname}()"
    return f"{qualname}()"


def _is_iterable(obj) -> bool:
    tp = type(obj)
    return hasattr(tp, "__iter__") or hasattr(tp, "__getitem__")


def _unpack(seq, before: int, after: int | None) -> list:
    """Return the unpacked values in source order (after=None: exact count)."""
    try:
        it = iter(seq)
    except TypeError:
        if not _is_iterable(seq):
            it = None
        else:
            raise
    if it is None:
        raise TypeError(f"cannot unpack non-iterable {type(seq).__name__} object")
    if after is None:
        vals = []
        for v in it:
            if len(vals) == before:
                try:
                    n = len(seq)
                except TypeError:
                    n = None
                if n is None:
                    raise ValueError(f"too many values to unpack (expected {before})")
                raise ValueError(f"too many values to unpack (expected {before}, got {n})")
            vals.append(v)
        if len(vals) < before:
            raise ValueError(f"not enough values to unpack (expected {before}, got {len(vals)})")
        return vals
    vals = list(it)
    if len(vals) < before + after:
        raise ValueError(
            f"not enough values to unpack (expected at least {before + after}, got {len(vals)})")
    middle = vals[before:len(vals) - after]
    return vals[:before] + [middle] + vals[len(vals) - after:]


def _check_except_type(right) -> None:
    items = right if isinstance(right, tuple) else (right,)
    for exc in items:
        if not (isinstance(exc, type) and issubclass(exc, BaseException)):
            raise TypeError(CANNOT_CATCH_MSG)


def _exception_group_match(exc_value, match_type):
    """_PyEval_ExceptionGroupMatch -> (match, rest)."""
    if exc_value is None:
        return None, None
    if isinstance(exc_value, match_type):
        if isinstance(exc_value, BaseExceptionGroup):
            return exc_value, None
        return BaseExceptionGroup("", (exc_value,)), None
    if isinstance(exc_value, BaseExceptionGroup):
        pair = exc_value.split(match_type)
        if not isinstance(pair, tuple):
            raise TypeError(f"{type(exc_value).__name__}.split must return a tuple, "
                            f"not {type(pair).__name__}")
        if len(pair) < 2:
            raise TypeError(f"{type(exc_value).__name__}.split must return a 2-tuple, "
                            f"got tuple of size {len(pair)}")
        return pair[0], pair[1]
    return None, exc_value


def _same_exception_metadata(e1, e2) -> bool:
    return (getattr(e1, "__notes__", None) is getattr(e2, "__notes__", None)
            and e1.__traceback__ is e2.__traceback__
            and e1.__cause__ is e2.__cause__
            and e1.__context__ is e2.__context__)


def _collect_leaf_ids(e, ids: set) -> None:
    if e is None:
        return
    if not isinstance(e, BaseExceptionGroup):
        ids.add(id(e))
        return
    for child in e.exceptions:
        _collect_leaf_ids(child, ids)


def _prep_reraise_star(orig, excs):
    """_PyExc_PrepReraiseStar (Objects/exceptions.c)."""
    if not excs:
        return None
    if not isinstance(orig, BaseExceptionGroup):
        # A naked exception was caught and wrapped: at most one to raise.
        return excs[0]
    raised, reraised = [], []
    for e in excs:
        if e is None:
            continue
        (reraised if _same_exception_metadata(e, orig) else raised).append(e)
    ids: set = set()
    for e in reraised:
        _collect_leaf_ids(e, ids)
    if ids:
        reraised_eg = orig.split(
            lambda leaf: not isinstance(leaf, BaseExceptionGroup) and id(leaf) in ids)[0]
    else:
        reraised_eg = None
    if not raised:
        return reraised_eg
    if reraised_eg is not None:
        raised.append(reraised_eg)
    if len(raised) > 1:
        return BaseExceptionGroup("", raised)
    return raised[0]


def _has_tpflag(tp: type, flag: int, abc_attr: bool = True) -> bool:
    if tp.__flags__ & flag:
        return True
    if abc_attr:
        # abc falls back to _py_abc, which cannot set tp_flags from
        # __abc_tpflags__; honour the attribute ourselves.
        for klass in tp.__mro__:
            f = klass.__dict__.get("__abc_tpflags__")
            if f is not None:
                return bool(f & flag)
    return False


def _match_class_attr(subject, type_, name, seen):
    if seen is not None:
        if name in seen:
            raise TypeError(f"{type_.__name__}() got multiple sub-patterns for attribute {name!r}")
        seen.add(name)
    return getattr(subject, name, _MISSING)


def _match_class(subject, type_, nargs, kwargs):
    """_PyEval_MatchClass: tuple of attributes, or None if no match."""
    if not isinstance(type_, type):
        raise TypeError("class pattern must refer to a class")
    if not isinstance(subject, type_):
        return None
    nattrs = nargs + len(kwargs)
    if not nattrs:
        return ()
    seen = set() if nargs > 0 and nattrs > 1 else None
    attrs = []
    if nargs:
        match_self = False
        match_args = getattr(type_, "__match_args__", _MISSING)
        if match_args is not _MISSING:
            if type(match_args) is not tuple:
                raise TypeError(f"{type_.__name__}.__match_args__ must be a tuple "
                                f"(got {type(match_args).__name__})")
        else:
            match_args = ()
            match_self = bool(type_.__flags__ & _TPFLAGS_MATCH_SELF)
        allowed = 1 if match_self else len(match_args)
        if allowed < nargs:
            plural = "" if allowed == 1 else "s"
            raise TypeError(f"{type_.__name__}() accepts {allowed} positional "
                            f"sub-pattern{plural} ({nargs} given)")
        if match_self:
            attrs.append(subject)
        else:
            for k in range(nargs):
                name = match_args[k]
                if type(name) is not str:
                    raise TypeError("__match_args__ elements must be strings "
                                    f"(got {type(name).__name__})")
                attr = _match_class_attr(subject, type_, name, seen)
                if attr is _MISSING:
                    return None
                attrs.append(attr)
    for name in kwargs:
        attr = _match_class_attr(subject, type_, name, seen)
        if attr is _MISSING:
            return None
        attrs.append(attr)
    return tuple(attrs)


def _match_keys(subject, keys):
    """_PyEval_MatchKeys: tuple of values, or None if a key is missing."""
    if not keys:
        return ()
    get = subject.get
    seen = set()
    dummy = object()
    values = []
    for key in keys:
        if key in seen:
            raise ValueError(f"mapping pattern checks duplicate key ({key!r})")
        seen.add(key)
        v = get(key, dummy)
        if v is dummy:
            return None
        values.append(v)
    return tuple(values)


class VirtualMachine:
    def __init__(self, path: list | None = None):
        from pp.builtins import make_builtins
        from pp.importer import Importer

        self.frame: Frame | None = None
        self.exc_info = ExcInfo()
        self._raised = None  # exception being re-raised/propagated (not to be chained)
        self.path: list = list(path or [])
        self.modules: dict = {}
        self.builtins_module = make_builtins(self)
        self.builtins: dict = self.builtins_module.__dict__
        self.importer = Importer(self)
        self.dispatch = {}
        table = [None] * 256
        for name, op in _opcode.opmap.items():
            handler = getattr(self, name, None)
            if handler is not None and op < 256:
                self.dispatch[name] = handler
                table[op] = handler
        for op in range(256):
            if table[op] is None:
                table[op] = self._make_unimplemented(_opcode.opname[op])
        self._table = table

    @staticmethod
    def _make_unimplemented(opname):
        def handler(f, i):
            raise UnimplementedOpcode(opname)
        return handler

    def add_script_dir(self, directory: str) -> None:
        """Search `directory` after pp/lib and the stdlib, before the extra `path`."""
        if directory not in self.path:
            self.path.insert(0, directory)
        self.importer.add_script_dir(directory)

    def builtins_for(self, globals: dict) -> dict:
        return builtins_from_globals(globals, self.builtins)

    # --- entry points ---

    def run_code(self, code: types.CodeType, globals: dict | None = None, locals=_MISSING) -> object:
        if globals is None:
            globals = {"__name__": "__main__", "__builtins__": _builtins}
        if "__builtins__" not in globals:
            globals["__builtins__"] = _builtins
        if locals is _MISSING:
            locals = globals
        return self.exec_code(code, globals, locals)

    def exec_code(self, code: types.CodeType, globals: dict, locals, closure=None) -> object:
        """Run module-like code (exec/eval): `locals` is the frame's namespace."""
        if code.co_flags & CO_OPTIMIZED:
            locals = None
        func = None
        if code.co_freevars:
            if closure is None or len(closure) != len(code.co_freevars):
                raise TypeError("code object requires a closure of exactly length "
                                f"{len(code.co_freevars)}")
            func = Function(code, globals, self)
            func.__closure__ = tuple(closure)
        elif closure is not None:
            raise TypeError("cannot use a closure with this code object")
        frame = Frame(code, globals, self.builtins_for(globals), locals, func=func)
        return self.run_frame(frame)

    def run_class_body(self, func: Function, namespace) -> object:
        frame = Frame(func.__code__, func.__globals__, func.__builtins__, namespace, func=func)
        return self.run_frame(frame)

    @property
    def sys_module(self):
        return self.importer.sys_module

    def call_function(self, func: Function, args, kwargs) -> object:
        code = func.__code__
        locals = None if code.co_flags & CO_OPTIMIZED else func.__globals__
        frame = Frame(code, func.__globals__, func.__builtins__, locals, func=func)
        bind_arguments(func, frame.localsplus, frame.localsplusnames, args, kwargs)
        return self.run_frame(frame)

    def call(self, callable, args, kwargs=None):
        tp = type(callable)
        if tp is Function:
            return self.call_function(callable, args, kwargs)
        if tp is types.MethodType and type(callable.__func__) is Function:
            return self.call_function(callable.__func__, (callable.__self__, *args), kwargs)
        if len(args) == 3 and isinstance(callable, type) and issubclass(callable, type) \
                and callable.__new__ == _TYPE_NEW:
            args = (args[0], args[1], _wrap_type_namespace(args[2]))
        elif len(args) == 4 and callable is _TYPE_NEW:
            args = (args[0], args[1], args[2], _wrap_type_namespace(args[3]))
        if kwargs:
            return callable(*args, **kwargs)
        return callable(*args)

    def run_frame(self, frame: Frame, throw: BaseException | None = None) -> object:
        """Execute `frame` until it returns or yields; `throw` resumes it with an exception."""
        frame.previous = self.frame
        self.frame = frame
        decoded = frame.decoded
        index = decoded._index
        instrs = decoded.instructions
        table = self._table
        stack = frame.stack
        exc = throw
        cur = frame.lasti
        try:
            while True:
                if exc is None:
                    try:
                        while True:
                            instr = instrs[index[frame.instr_offset]]
                            cur = frame.lasti = instr.offset
                            frame.instr_offset = instr.next_offset
                            if table[instr.opcode](frame, instr) is not None:
                                return frame.return_value
                    except UnimplementedOpcode:
                        raise
                    except BaseException as e:
                        exc = e
                        if e is not self._raised:
                            # Raised by host code during this instruction:
                            # _PyErr_SetObject chains it to the handled exception.
                            self._chain(e)
                # exception_unwind: find the handler for the faulting instruction.
                entry = None
                for e in decoded.exception_table:
                    if e.start <= cur < e.end:
                        entry = e
                        break
                if entry is None:
                    self._raised = exc
                    raise exc
                del stack[entry.depth:]
                if entry.lasti:
                    stack.append(frame.lasti)
                stack.append(exc)
                frame.instr_offset = entry.target
                exc = None
        finally:
            self.frame = frame.previous

    # --- handled-exception stack (tstate->exc_info) ---

    def topmost_exception(self):
        info = self.exc_info
        while info is not None:
            if info.exc_value is not None:
                return info.exc_value
            info = info.previous
        return None

    def _chain(self, exc, top=_MISSING) -> None:
        """Implicit __context__ chaining at a raise site, as in _PyErr_SetObject.

        Only fresh raises are chained: re-raises (RERAISE, bare `raise`) and
        exceptions propagating out of a callee VM frame are marked in
        `self._raised` and left alone."""
        if top is _MISSING:
            top = self.topmost_exception()
        if top is None or top is exc:
            return
        o = top
        seen = set()
        while True:
            ctx = o.__context__
            if ctx is None or id(ctx) in seen:
                break
            if ctx is exc:
                o.__context__ = None
                break
            seen.add(id(o))
            o = ctx
        exc.__context__ = top

    # --- no-ops ---

    def RESUME(self, f, i): pass
    def NOP(self, f, i): pass
    def NOT_TAKEN(self, f, i): pass
    def EXTENDED_ARG(self, f, i): pass  # the decoder already folds it into the next arg

    # --- constants and names ---

    def LOAD_CONST(self, f, i):
        f.stack.append(f.code.co_consts[i.arg])

    def LOAD_SMALL_INT(self, f, i):
        f.stack.append(i.arg)

    def LOAD_COMMON_CONSTANT(self, f, i):
        f.stack.append(COMMON_CONSTANTS[i.arg])

    def LOAD_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        if f.locals is None:
            raise SystemError(f"no locals when loading {name!r}")
        v = _MISSING
        for ns in (f.locals, f.globals, f.builtins):
            try:
                v = ns[name]
                break
            except KeyError:
                pass
        if v is _MISSING:
            raise _name_error(name)
        f.stack.append(v)

    def STORE_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        if f.locals is None:
            raise SystemError(f"no locals found when storing {name!r}")
        f.locals[name] = f.stack.pop()

    def DELETE_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        if f.locals is None:
            raise SystemError(f"no locals when deleting {name!r}")
        try:
            del f.locals[name]
            return
        except KeyError:
            pass
        raise _name_error(name)

    def _load_global(self, f, name):
        try:
            return f.globals[name]
        except KeyError:
            pass
        try:
            return f.builtins[name]
        except KeyError:
            pass
        raise _name_error(name)

    def LOAD_GLOBAL(self, f, i):
        f.stack.append(self._load_global(f, f.code.co_names[i.arg >> 1]))
        if i.arg & 1:
            f.stack.append(NULL)

    def STORE_GLOBAL(self, f, i):
        f.globals[f.code.co_names[i.arg]] = f.stack.pop()

    def DELETE_GLOBAL(self, f, i):
        name = f.code.co_names[i.arg]
        try:
            del f.globals[name]
            return
        except KeyError:
            pass
        raise _name_error(name)

    def LOAD_LOCALS(self, f, i):
        if f.locals is None:
            raise SystemError("no locals found")
        f.stack.append(f.locals)

    def LOAD_FROM_DICT_OR_GLOBALS(self, f, i):
        mapping = f.stack.pop()
        name = f.code.co_names[i.arg]
        try:
            v = mapping[name]
        except KeyError:
            v = _MISSING
        if v is _MISSING:
            v = self._load_global(f, name)
        f.stack.append(v)

    # --- fast locals ---

    def _unbound(self, f, idx):
        name = f.localsplusnames[idx]
        if idx < f.first_free:
            return UnboundLocalError(
                f"cannot access local variable '{name}' where it is not associated with a value")
        return NameError(
            f"cannot access free variable '{name}' where it is not associated with a value"
            " in enclosing scope", name=name)

    def LOAD_FAST(self, f, i):
        v = f.localsplus[i.arg]
        if v is NULL:
            raise self._unbound(f, i.arg)
        f.stack.append(v)

    LOAD_FAST_BORROW = LOAD_FAST
    LOAD_FAST_CHECK = LOAD_FAST

    def LOAD_FAST_LOAD_FAST(self, f, i):
        lp = f.localsplus
        a, b = lp[i.arg >> 4], lp[i.arg & 15]
        if a is NULL:
            raise self._unbound(f, i.arg >> 4)
        if b is NULL:
            raise self._unbound(f, i.arg & 15)
        f.stack.append(a)
        f.stack.append(b)

    LOAD_FAST_BORROW_LOAD_FAST_BORROW = LOAD_FAST_LOAD_FAST

    def LOAD_FAST_AND_CLEAR(self, f, i):
        f.stack.append(f.localsplus[i.arg])
        f.localsplus[i.arg] = NULL

    def STORE_FAST(self, f, i):
        f.localsplus[i.arg] = f.stack.pop()

    def STORE_FAST_LOAD_FAST(self, f, i):
        f.localsplus[i.arg >> 4] = f.stack.pop()
        v = f.localsplus[i.arg & 15]
        if v is NULL:
            raise self._unbound(f, i.arg & 15)
        f.stack.append(v)

    def STORE_FAST_STORE_FAST(self, f, i):
        value1 = f.stack.pop()
        value2 = f.stack.pop()
        f.localsplus[i.arg >> 4] = value1
        f.localsplus[i.arg & 15] = value2

    def DELETE_FAST(self, f, i):
        if f.localsplus[i.arg] is NULL:
            raise self._unbound(f, i.arg)
        f.localsplus[i.arg] = NULL

    # --- cells ---

    def MAKE_CELL(self, f, i):
        initial = f.localsplus[i.arg]
        f.localsplus[i.arg] = types.CellType() if initial is NULL else types.CellType(initial)

    def COPY_FREE_VARS(self, f, i):
        closure = f.func.__closure__
        offset = len(f.localsplus) - i.arg
        for k in range(i.arg):
            f.localsplus[offset + k] = closure[k]

    def _cell_get(self, f, idx):
        try:
            return f.localsplus[idx].cell_contents
        except ValueError:
            pass
        raise self._unbound(f, idx)

    def LOAD_DEREF(self, f, i):
        f.stack.append(self._cell_get(f, i.arg))

    def STORE_DEREF(self, f, i):
        f.localsplus[i.arg].cell_contents = f.stack.pop()

    def DELETE_DEREF(self, f, i):
        cell = f.localsplus[i.arg]
        try:
            del cell.cell_contents
            return
        except ValueError:
            pass
        raise self._unbound(f, i.arg)

    def LOAD_FROM_DICT_OR_DEREF(self, f, i):
        class_dict = f.stack.pop()
        name = f.localsplusnames[i.arg]
        try:
            v = class_dict[name]
        except KeyError:
            v = _MISSING
        if v is _MISSING:
            v = self._cell_get(f, i.arg)
        f.stack.append(v)

    # --- stack manipulation ---

    def PUSH_NULL(self, f, i):
        f.stack.append(NULL)

    def POP_TOP(self, f, i):
        f.stack.pop()

    def COPY(self, f, i):
        f.stack.append(f.stack[-i.arg])

    def SWAP(self, f, i):
        s = f.stack
        s[-1], s[-i.arg] = s[-i.arg], s[-1]

    # --- functions and calls ---

    def MAKE_FUNCTION(self, f, i):
        code = f.stack.pop()
        f.stack.append(Function(code, f.globals, self))

    _FUNC_ATTRS = {1: "__defaults__", 2: "__kwdefaults__", 4: "_annotations",
                   8: "__closure__", 16: "__annotate__"}

    def SET_FUNCTION_ATTRIBUTE(self, f, i):
        func = f.stack.pop()
        attr = f.stack.pop()
        setattr(func, self._FUNC_ATTRS[i.arg], attr)
        f.stack.append(func)

    def _call(self, f, nargs, kwnames):
        args = f.popn(nargs)
        self_or_null = f.stack.pop()
        callable = f.stack.pop()
        if self_or_null is not NULL:
            args.insert(0, self_or_null)
        if kwnames:
            npos = len(args) - len(kwnames)
            kwargs = dict(zip(kwnames, args[npos:]))
            del args[npos:]
        else:
            kwargs = None
        f.stack.append(self.call(callable, args, kwargs))

    def CALL(self, f, i):
        self._call(f, i.arg, ())

    def CALL_KW(self, f, i):
        kwnames = f.stack.pop()
        self._call(f, i.arg, kwnames)

    def CALL_FUNCTION_EX(self, f, i):
        kwargs = f.stack.pop()
        callargs = f.stack.pop()
        f.stack.pop()  # null
        func = f.stack.pop()
        if type(callargs) is not tuple:
            if not _is_iterable(callargs):
                raise TypeError(
                    f"Value after * must be an iterable, not {type(callargs).__name__}")
            callargs = tuple(callargs)
        if kwargs is NULL:
            kwargs = None
        f.stack.append(self.call(func, callargs, kwargs))

    def DICT_MERGE(self, f, i):
        update = f.stack.pop()
        d = f.stack[-i.arg]
        callable = f.stack[-i.arg - 3]
        if not hasattr(update, "keys"):
            raise TypeError(f"Value after ** must be a mapping, not {type(update).__name__}")
        items = update.items() if isinstance(update, dict) else \
            [(k, update[k]) for k in update.keys()]
        dup = _MISSING
        for k, v in items:
            if k in d:
                dup = k
                break
            d[k] = v
        if dup is not _MISSING:
            raise TypeError(
                f"{_function_str(callable)} got multiple values for keyword argument '{dup}'")

    def CALL_INTRINSIC_1(self, f, i):
        v = f.stack.pop()
        f.stack.append(self._INTRINSICS_1[i.arg](self, f, v))

    def CALL_INTRINSIC_2(self, f, i):
        value1 = f.stack.pop()
        value2 = f.stack.pop()
        f.stack.append(self._INTRINSICS_2[i.arg](self, f, value2, value1))

    def RETURN_VALUE(self, f, i):
        f.return_value = f.stack.pop()
        f.yielded = False
        return _EXIT

    # --- generators ---

    def RETURN_GENERATOR(self, f, i):
        flags = f.code.co_flags
        if flags & CO_COROUTINE:
            cls = Coroutine
        elif flags & CO_ASYNC_GENERATOR:
            cls = AsyncGenerator
        else:
            cls = Generator
        f.return_value = cls(f, f.func, self)
        f.yielded = False
        return _EXIT

    def YIELD_VALUE(self, f, i):
        f.return_value = f.stack.pop()
        f.yielded = True
        f.yield_oparg = i.arg
        return _EXIT

    def SEND(self, f, i):
        v = f.stack.pop()
        receiver = f.stack[-2]
        if isinstance(receiver, Generator):
            is_return, res = receiver._send_ex(v)
        else:
            is_return = False
            try:
                res = next(receiver) if v is None and hasattr(type(receiver), "__next__") \
                    else receiver.send(v)
            except StopIteration as e:
                is_return, res = True, e.value
        f.stack.append(res)
        if is_return:
            f.instr_offset = i.jump_target

    def END_SEND(self, f, i):
        value = f.stack.pop()
        f.stack.pop()
        f.stack.pop()
        f.stack.append(value)

    def CLEANUP_THROW(self, f, i):
        exc_value = f.stack.pop()
        if not isinstance(exc_value, StopIteration):
            self._raised = exc_value
            raise exc_value
        f.stack.pop()            # last_sent_val
        null = f.stack.pop()
        f.stack.pop()            # sub_iter
        f.stack.append(None)
        f.stack.append(null)
        f.stack.append(exc_value.value)

    # --- exceptions ---

    def RAISE_VARARGS(self, f, i):
        cause = f.stack.pop() if i.arg == 2 else _MISSING
        exc = f.stack.pop() if i.arg >= 1 else _MISSING
        if exc is _MISSING:
            top = self.topmost_exception()
            if top is None:
                raise RuntimeError("No active exception to reraise")
            self._raised = top
            raise top
        if isinstance(exc, type) and issubclass(exc, BaseException):
            value = exc()
            if not isinstance(value, BaseException):
                raise TypeError(f"calling {exc!r} should have returned an instance of "
                                f"BaseException, not {type(value)!r}")
        elif isinstance(exc, BaseException):
            value = exc
        else:
            raise TypeError("exceptions must derive from BaseException")
        if cause is not _MISSING:
            if isinstance(cause, type) and issubclass(cause, BaseException):
                fixed = cause()
                if not isinstance(fixed, BaseException):
                    raise TypeError(f"calling {cause!r} should have returned an instance of "
                                    f"BaseException, not {type(fixed)!r}")
            elif isinstance(cause, BaseException) or cause is None:
                fixed = cause
            else:
                raise TypeError("exception causes must derive from BaseException")
            value.__cause__ = fixed
        self._chain(value)
        self._raised = value
        raise value

    def RERAISE(self, f, i):
        exc = f.stack.pop()
        if i.arg:
            f.lasti = f.stack[-i.arg]
        self._raised = exc
        raise exc

    def PUSH_EXC_INFO(self, f, i):
        exc = f.stack.pop()
        info = self.exc_info
        f.stack.append(info.exc_value)
        info.exc_value = exc
        f.stack.append(exc)

    def POP_EXCEPT(self, f, i):
        self.exc_info.exc_value = f.stack.pop()

    def CHECK_EXC_MATCH(self, f, i):
        right = f.stack.pop()
        left = f.stack[-1]
        _check_except_type(right)
        f.stack.append(isinstance(left, right))

    def CHECK_EG_MATCH(self, f, i):
        match_type = f.stack.pop()
        exc_value = f.stack.pop()
        _check_except_type(match_type)
        items = match_type if isinstance(match_type, tuple) else (match_type,)
        if any(issubclass(t, BaseExceptionGroup) for t in items):
            raise TypeError(CANNOT_EXCEPT_STAR_EG)
        match, rest = _exception_group_match(exc_value, match_type)
        if match is not None:
            self.exc_info.exc_value = match
        f.stack.append(rest)
        f.stack.append(match)

    def WITH_EXCEPT_START(self, f, i):
        val = f.stack[-1]
        exit_self = f.stack[-4]
        exit_func = f.stack[-5]
        tb = val.__traceback__
        if exit_self is NULL:
            res = self.call(exit_func, (type(val), val, tb))
        else:
            res = self.call(exit_func, (exit_self, type(val), val, tb))
        f.stack.append(res)

    def LOAD_SPECIAL(self, f, i):
        owner = f.stack.pop()
        name = SPECIAL_METHODS[i.arg]
        tp = type(owner)
        attr = _MISSING
        for klass in tp.__mro__:
            if name in klass.__dict__:
                attr = klass.__dict__[name]
                break
        if attr is _MISSING:
            msg = _SPECIAL_ERRORS[name].format(_type_fullname(tp))
            other, suggestion = _SPECIAL_SUGGEST[name]
            if hasattr(tp, other):
                msg += suggestion
            raise TypeError(msg)
        if isinstance(attr, _FUNCTION_TYPES):
            f.stack.append(attr)
            f.stack.append(owner)
        else:
            get = getattr(type(attr), "__get__", None)
            f.stack.append(get(attr, owner, tp) if get is not None else attr)
            f.stack.append(NULL)

    # --- operators ---

    def BINARY_OP(self, f, i):
        rhs = f.stack.pop()
        lhs = f.stack.pop()
        f.stack.append(BINARY_OPS[i.arg](lhs, rhs))

    def BINARY_SLICE(self, f, i):
        stop = f.stack.pop()
        start = f.stack.pop()
        container = f.stack.pop()
        f.stack.append(container[start:stop])

    def STORE_SLICE(self, f, i):
        stop = f.stack.pop()
        start = f.stack.pop()
        container = f.stack.pop()
        v = f.stack.pop()
        container[start:stop] = v

    def STORE_SUBSCR(self, f, i):
        sub = f.stack.pop()
        container = f.stack.pop()
        v = f.stack.pop()
        container[sub] = v

    def DELETE_SUBSCR(self, f, i):
        sub = f.stack.pop()
        container = f.stack.pop()
        del container[sub]

    def UNARY_NEGATIVE(self, f, i):
        f.stack.append(-f.stack.pop())

    def UNARY_INVERT(self, f, i):
        f.stack.append(~f.stack.pop())

    def UNARY_NOT(self, f, i):
        f.stack.append(not f.stack.pop())

    def TO_BOOL(self, f, i):
        f.stack.append(bool(f.stack.pop()))

    def COMPARE_OP(self, f, i):
        right = f.stack.pop()
        left = f.stack.pop()
        res = COMPARE_OPS[i.arg >> 5](left, right)
        if i.arg & 16:
            res = bool(res)
        f.stack.append(res)

    def IS_OP(self, f, i):
        right = f.stack.pop()
        left = f.stack.pop()
        f.stack.append((left is right) ^ bool(i.arg))

    def CONTAINS_OP(self, f, i):
        right = f.stack.pop()
        left = f.stack.pop()
        f.stack.append((left in right) ^ bool(i.arg))

    # --- control flow ---

    def POP_JUMP_IF_TRUE(self, f, i):
        if f.stack.pop():
            f.instr_offset = i.jump_target

    def POP_JUMP_IF_FALSE(self, f, i):
        if not f.stack.pop():
            f.instr_offset = i.jump_target

    def POP_JUMP_IF_NONE(self, f, i):
        if f.stack.pop() is None:
            f.instr_offset = i.jump_target

    def POP_JUMP_IF_NOT_NONE(self, f, i):
        if f.stack.pop() is not None:
            f.instr_offset = i.jump_target

    def JUMP_FORWARD(self, f, i):
        f.instr_offset = i.jump_target

    def JUMP_BACKWARD(self, f, i):
        f.instr_offset = i.jump_target

    def JUMP_BACKWARD_NO_INTERRUPT(self, f, i):
        f.instr_offset = i.jump_target

    # --- iteration ---

    def GET_ITER(self, f, i):
        f.stack.append(iter(f.stack.pop()))
        f.stack.append(NULL)  # index_or_null: always NULL in pp

    def FOR_ITER(self, f, i):
        it = f.stack[-2]
        try:
            v = next(it)
        except StopIteration:
            # Exhausted: jump past the END_FOR at the target, leaving iter/null for POP_ITER.
            f.instr_offset = i.jump_target + 2
            return
        f.stack.append(v)

    def END_FOR(self, f, i):
        f.stack.pop()

    def POP_ITER(self, f, i):
        f.stack.pop()
        f.stack.pop()

    def GET_LEN(self, f, i):
        f.stack.append(len(f.stack[-1]))

    # --- building containers ---

    def BUILD_TUPLE(self, f, i):
        f.stack.append(tuple(f.popn(i.arg)))

    def BUILD_LIST(self, f, i):
        f.stack.append(f.popn(i.arg))

    def BUILD_SET(self, f, i):
        f.stack.append(set(f.popn(i.arg)))

    def BUILD_MAP(self, f, i):
        vals = f.popn(2 * i.arg)
        d = {}
        for k in range(0, len(vals), 2):
            d[vals[k]] = vals[k + 1]
        f.stack.append(d)

    def BUILD_INTERPOLATION(self, f, i):
        fmt = f.stack.pop() if i.arg & 1 else ""
        expr = f.stack.pop()
        value = f.stack.pop()
        f.stack.append(_Interpolation(value, expr, _CONVERSION_CHARS[i.arg >> 2], fmt))

    def BUILD_TEMPLATE(self, f, i):
        interpolations = f.stack.pop()
        strings = f.stack.pop()
        args = []
        for k, s in enumerate(strings):
            args.append(s)
            if k < len(interpolations):
                args.append(interpolations[k])
        f.stack.append(_Template(*args))

    def BUILD_SLICE(self, f, i):
        f.stack.append(slice(*f.popn(i.arg)))

    def BUILD_STRING(self, f, i):
        f.stack.append("".join(f.popn(i.arg)))

    def LIST_APPEND(self, f, i):
        v = f.stack.pop()
        f.stack[-i.arg].append(v)

    def LIST_EXTEND(self, f, i):
        iterable = f.stack.pop()
        if not _is_iterable(iterable):
            raise TypeError(f"Value after * must be an iterable, not {type(iterable).__name__}")
        f.stack[-i.arg].extend(iterable)

    def SET_ADD(self, f, i):
        v = f.stack.pop()
        f.stack[-i.arg].add(v)

    def SET_UPDATE(self, f, i):
        iterable = f.stack.pop()
        f.stack[-i.arg].update(iterable)

    def MAP_ADD(self, f, i):
        value = f.stack.pop()
        key = f.stack.pop()
        f.stack[-i.arg][key] = value

    def DICT_UPDATE(self, f, i):
        update = f.stack.pop()
        if not hasattr(update, "keys"):
            raise TypeError(f"'{type(update).__name__}' object is not a mapping")
        f.stack[-i.arg].update(update)

    def UNPACK_SEQUENCE(self, f, i):
        vals = _unpack(f.stack.pop(), i.arg, None)
        f.stack.extend(reversed(vals))

    def UNPACK_EX(self, f, i):
        vals = _unpack(f.stack.pop(), i.arg & 0xFF, i.arg >> 8)
        f.stack.extend(reversed(vals))

    # --- formatting ---

    def FORMAT_SIMPLE(self, f, i):
        v = f.stack.pop()
        f.stack.append(v if type(v) is str else format(v))

    def FORMAT_WITH_SPEC(self, f, i):
        spec = f.stack.pop()
        v = f.stack.pop()
        f.stack.append(format(v, spec))

    def CONVERT_VALUE(self, f, i):
        f.stack.append(CONVERSIONS[i.arg](f.stack.pop()))

    # --- attributes ---

    def LOAD_ATTR(self, f, i):
        owner = f.stack.pop()
        attr = getattr(owner, f.code.co_names[i.arg >> 1])
        if i.arg & 1:
            # Method form: push (unbound function, self) for VM methods, else (attr, NULL).
            if type(attr) is types.MethodType and attr.__self__ is owner \
                    and type(attr.__func__) is Function:
                f.stack.append(attr.__func__)
                f.stack.append(owner)
                return
            f.stack.append(attr)
            f.stack.append(NULL)
            return
        f.stack.append(attr)

    def STORE_ATTR(self, f, i):
        owner = f.stack.pop()
        v = f.stack.pop()
        setattr(owner, f.code.co_names[i.arg], v)

    def DELETE_ATTR(self, f, i):
        delattr(f.stack.pop(), f.code.co_names[i.arg])

    # --- classes ---

    def LOAD_BUILD_CLASS(self, f, i):
        try:
            bc = f.builtins["__build_class__"]
        except KeyError:
            bc = _MISSING
        if bc is _MISSING:
            raise NameError("__build_class__ not found")
        f.stack.append(bc)

    def LOAD_SUPER_ATTR(self, f, i):
        self_ = f.stack.pop()
        cls = f.stack.pop()
        global_super = f.stack.pop()
        name = f.code.co_names[i.arg >> 2]
        if global_super is self.builtins.get("super") or global_super is super:
            sup = super(cls, self_)
        elif i.arg & 2:
            sup = self.call(global_super, (cls, self_))
        else:
            sup = self.call(global_super, ())
        attr = getattr(sup, name)
        if i.arg & 1:
            if type(attr) is types.MethodType and attr.__self__ is self_ \
                    and type(attr.__func__) is Function:
                f.stack.append(attr.__func__)
                f.stack.append(self_)
            else:
                f.stack.append(attr)
                f.stack.append(NULL)
        else:
            f.stack.append(attr)

    def SETUP_ANNOTATIONS(self, f, i):
        if f.locals is None:
            raise SystemError("no locals found when setting up annotations")
        try:
            f.locals["__annotations__"]
            return
        except KeyError:
            pass
        f.locals["__annotations__"] = {}

    # --- imports ---

    def IMPORT_NAME(self, f, i):
        fromlist = f.stack.pop()
        level = f.stack.pop()
        name = f.code.co_names[i.arg >> 2]
        try:
            import_func = f.builtins["__import__"]
        except KeyError:
            import_func = _MISSING
        if import_func is _MISSING:
            raise ImportError("__import__ not found")
        f.stack.append(self.call(import_func, (name, f.globals, f.locals, fromlist, level)))

    def IMPORT_FROM(self, f, i):
        f.stack.append(self.importer.import_from(f.stack[-1], f.code.co_names[i.arg]))

    # --- pattern matching ---

    def MATCH_MAPPING(self, f, i):
        f.stack.append(_has_tpflag(type(f.stack[-1]), _TPFLAGS_MAPPING))

    def MATCH_SEQUENCE(self, f, i):
        f.stack.append(_has_tpflag(type(f.stack[-1]), _TPFLAGS_SEQUENCE))

    def MATCH_KEYS(self, f, i):
        f.stack.append(_match_keys(f.stack[-2], f.stack[-1]))

    def MATCH_CLASS(self, f, i):
        names = f.stack.pop()
        type_ = f.stack.pop()
        subject = f.stack.pop()
        f.stack.append(_match_class(subject, type_, i.arg, names))

    # --- intrinsics (Python/intrinsics.c) ---

    def _intrinsic_print(self, f, v):
        sys.displayhook(v)
        return None

    def _intrinsic_import_star(self, f, module):
        if f.locals is None:
            raise SystemError("no locals found during 'import *'")
        self.importer.import_all_from(f.locals, module)
        return None

    def _intrinsic_stopiteration_error(self, f, exc):
        flags = f.code.co_flags
        if isinstance(exc, StopIteration):
            if flags & CO_ASYNC_GENERATOR:
                msg = "async generator raised StopIteration"
            elif flags & CO_COROUTINE:
                msg = "coroutine raised StopIteration"
            else:
                msg = "generator raised StopIteration"
        elif flags & CO_ASYNC_GENERATOR and isinstance(exc, StopAsyncIteration):
            msg = "async generator raised StopAsyncIteration"
        else:
            return exc
        new = RuntimeError(msg)
        new.__cause__ = exc
        new.__context__ = exc
        return new

    def _typing(self):
        return self.importer.import_module("_typing")

    def _intrinsic_typevar(self, f, name):
        return self._typing().TypeVar(name, infer_variance=True)

    def _intrinsic_paramspec(self, f, name):
        return self._typing().ParamSpec(name, infer_variance=True)

    def _intrinsic_typevartuple(self, f, name):
        return self._typing().TypeVarTuple(name)

    def _intrinsic_subscript_generic(self, f, params):
        return self._typing().Generic[params]

    def _intrinsic_typealias(self, f, args):
        name, type_params, compute_value = args
        return self._typing().TypeAliasType(name, self.call(compute_value, (1,)),
                                            type_params=type_params or ())

    _INTRINSICS_1 = (
        None,
        _intrinsic_print,
        _intrinsic_import_star,
        _intrinsic_stopiteration_error,
        lambda self, f, v: v,                 # INTRINSIC_ASYNC_GEN_WRAP (async: out of scope)
        lambda self, f, v: +v,                # INTRINSIC_UNARY_POSITIVE
        lambda self, f, v: tuple(v),          # INTRINSIC_LIST_TO_TUPLE
        _intrinsic_typevar,
        _intrinsic_paramspec,
        _intrinsic_typevartuple,
        _intrinsic_subscript_generic,
        _intrinsic_typealias,
    )

    def _intrinsic_typevar_with_bound(self, f, name, evaluate_bound):
        return self._typing().TypeVar(name, bound=self.call(evaluate_bound, (1,)),
                                      infer_variance=True)

    def _intrinsic_typevar_with_constraints(self, f, name, evaluate_constraints):
        return self._typing().TypeVar(name, *self.call(evaluate_constraints, (1,)),
                                      infer_variance=True)

    def _intrinsic_set_function_type_params(self, f, func, params):
        func.__type_params__ = params
        return func

    def _intrinsic_set_typeparam_default(self, f, typeparam, evaluate_default):
        # Host type parameters do not allow setting a lazy default from Python.
        return typeparam

    _INTRINSICS_2 = (
        None,
        lambda self, f, orig, excs: _prep_reraise_star(orig, excs),
        _intrinsic_typevar_with_bound,
        _intrinsic_typevar_with_constraints,
        _intrinsic_set_function_type_params,
        _intrinsic_set_typeparam_default,
    )


def run_source(source: str, filename: str = "<string>", globals: dict | None = None,
               vm: VirtualMachine | None = None) -> dict:
    if vm is None:
        vm = VirtualMachine()
    if globals is None:
        globals = _main_module(vm).__dict__
    code = compile_source(source, filename, "exec")
    vm.run_code(code, globals)
    return globals


def run_file(path: str, vm: VirtualMachine | None = None) -> dict:
    path = os.path.realpath(path)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    if vm is None:
        vm = VirtualMachine()
    vm.add_script_dir(os.path.dirname(path))
    globals = _main_module(vm).__dict__
    globals["__builtins__"] = vm.builtins_module  # like CPython's __main__
    globals["__file__"] = path
    from pp.importer import SourceLoader
    globals["__loader__"] = SourceLoader(vm.importer, "__main__", path)
    return run_source(source, path, globals, vm)


def _main_module(vm: VirtualMachine) -> types.ModuleType:
    """A fresh `__main__` module registered in vm.modules (unittest.main() needs it)."""
    mod = types.ModuleType("__main__")
    # DESIGN.md: run_source's default globals carry the host `builtins` module
    # (frames still run with the VM's builtins); run_file uses the VM's module.
    mod.__dict__["__builtins__"] = _builtins
    vm.modules["__main__"] = mod
    return mod
