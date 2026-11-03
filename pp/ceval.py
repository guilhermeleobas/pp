"""The eval loop and opcode handlers. Spec: CPython 3.15 Python/bytecodes.c."""

import os
import sys
import types

import opcode as _opcode

from pp import call as _call
from pp import errors as _errors
from pp import typeobject as _typeobject
from pp import object as _obj
from pp.abstract import (PYGEN_RETURN, PyIter_Next, PyIter_Send, PyNumber_Add, PyNumber_And, PyNumber_FloorDivide,
                         PyNumber_InPlaceAdd, PyNumber_InPlaceAnd, PyNumber_InPlaceFloorDivide,
                         PyNumber_InPlaceLshift, PyNumber_InPlaceMatrixMultiply,
                         PyNumber_InPlaceMultiply, PyNumber_InPlaceOr, PyNumber_InPlaceRemainder,
                         PyNumber_InPlaceRshift, PyNumber_InPlaceSubtract,
                         PyNumber_InPlaceTrueDivide, PyNumber_InPlaceXor, PyNumber_Invert,
                         PyNumber_Lshift, PyNumber_MatrixMultiply, PyNumber_Multiply,
                         PyNumber_Negative, PyNumber_Or, PyNumber_Positive, PyNumber_Remainder,
                         PyNumber_Rshift, PyNumber_Subtract, PyNumber_TrueDivide, PyNumber_Xor,
                         PyObject_DelItem, PyObject_GetItem, PyObject_GetIter, PyObject_SetItem,
                         PyObject_Size, PySequence_Check, PySequence_Contains, PySequence_Tuple,
                         _PyNumber_InPlacePowerNoMod, _PyNumber_PowerNoMod)
from pp.bytecode import compile_source
from pp.object import (PyObject_GetAttr, PyObject_GetOptionalAttr, PyObject_IsInstance,
                       PyObject_IsTrue, PyObject_RichCompare, PyObject_SetAttr,
                       _PyObject_GetMethod, _PyObject_LookupSpecialMethod)
from pp.typeobject import (Py_TYPE, PyObject_TypeCheck, PyType_Check, PyType_IsSubtype,
                           PyType_View, _PyType_Lookup,
                           _PySuper_Lookup)
from pp.errors import (PyErr_GivenExceptionMatches, PyExceptionClass_Check, PyThreadState,
                       UnimplementedOpcode, _PyErr_Clear, _PyExceptionInstance_Check,
                       _PyThreadState_GET,
                       _PyErr_GetTopmostException, _PyErr_SetObject,
                       _PyErr_SetRaisedException, _PyThreadState_Swap)
from pp.frame import NULL, Frame  # noqa: F401  (NULL is part of the pp.vm API)
from pp.funcobject import Function, PyFunction_New, bind_arguments, builtins_from_globals
from pp.genobject import (FRAME_SUSPENDED_YIELD_FROM, FRAME_SUSPENDED_YIELD_FROM_LOCKED,
                          PyAsyncGenObject, PyAsyncGenWrappedValue, PyCoro_CheckExact, PyCoro_GetAwaitableIter,
                          PyCoroObject, PyGenObject, gen_is_coroutine)

_GenericGetAttr = _obj.PyObject_GenericGetAttr
_GenericSetAttr = _obj.PyObject_GenericSetAttr
_object_getattribute = _typeobject._object_getattribute
DICT_STD = _typeobject.DICT_STD
DICT_NONE = _typeobject.DICT_NONE
_ITER_TYPES = frozenset((list, tuple, dict, set, frozenset, str, bytes, range))
_NB_SUBSCR = [n for n, _ in _opcode._nb_ops].index("NB_SUBSCR")
_SUBSCRIPT_TYPES = frozenset((list, tuple, dict, str))
_CONTAINS_TYPES = frozenset((dict, set, frozenset))
_MethodDescriptorType = types.MethodDescriptorType
_BuiltinFunction = types.BuiltinFunctionType
_MethodType = types.MethodType
_views_get = _typeobject._views_get

_next = next
_FAST_ITERATORS = frozenset((type(iter([])), type(iter(())), type(iter(range(1))), type(iter("")),
                             type(iter({})), type(iter({}.values())), type(iter({}.items())),
                             type(iter(set())), type(iter(b"")), enumerate, zip, reversed,
                             type(reversed([])), map, filter, type(iter(range(1 << 70)))))

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


# --- BINARY_OP table (index = oparg, order from opcode._nb_ops): _PyEval_BinaryOps ---

_NB_FUNCS = {
    "NB_ADD": PyNumber_Add,
    "NB_AND": PyNumber_And,
    "NB_FLOOR_DIVIDE": PyNumber_FloorDivide,
    "NB_LSHIFT": PyNumber_Lshift,
    "NB_MATRIX_MULTIPLY": PyNumber_MatrixMultiply,
    "NB_MULTIPLY": PyNumber_Multiply,
    "NB_REMAINDER": PyNumber_Remainder,
    "NB_OR": PyNumber_Or,
    "NB_POWER": _PyNumber_PowerNoMod,
    "NB_RSHIFT": PyNumber_Rshift,
    "NB_SUBTRACT": PyNumber_Subtract,
    "NB_TRUE_DIVIDE": PyNumber_TrueDivide,
    "NB_XOR": PyNumber_Xor,
    "NB_INPLACE_ADD": PyNumber_InPlaceAdd,
    "NB_INPLACE_AND": PyNumber_InPlaceAnd,
    "NB_INPLACE_FLOOR_DIVIDE": PyNumber_InPlaceFloorDivide,
    "NB_INPLACE_LSHIFT": PyNumber_InPlaceLshift,
    "NB_INPLACE_MATRIX_MULTIPLY": PyNumber_InPlaceMatrixMultiply,
    "NB_INPLACE_MULTIPLY": PyNumber_InPlaceMultiply,
    "NB_INPLACE_REMAINDER": PyNumber_InPlaceRemainder,
    "NB_INPLACE_OR": PyNumber_InPlaceOr,
    "NB_INPLACE_POWER": _PyNumber_InPlacePowerNoMod,
    "NB_INPLACE_RSHIFT": PyNumber_InPlaceRshift,
    "NB_INPLACE_SUBTRACT": PyNumber_InPlaceSubtract,
    "NB_INPLACE_TRUE_DIVIDE": PyNumber_InPlaceTrueDivide,
    "NB_INPLACE_XOR": PyNumber_InPlaceXor,
    "NB_SUBSCR": PyObject_GetItem,
}
BINARY_OPS = tuple(_NB_FUNCS[name] for name, _ in _opcode._nb_ops)

# Specialized BINARY_OP / COMPARE_OP / TO_BOOL (BINARY_OP_ADD_INT, COMPARE_OP_INT,
# TO_BOOL_LIST, ...): for exact builtin operand types the slot functions are the
# C implementations of the very same operations, so call them directly.
# (Lib/operator.py's pure-Python definitions.)
class _operator:
    add = staticmethod(lambda a, b: a + b)
    and_ = staticmethod(lambda a, b: a & b)
    floordiv = staticmethod(lambda a, b: a // b)
    lshift = staticmethod(lambda a, b: a << b)
    mul = staticmethod(lambda a, b: a * b)
    mod = staticmethod(lambda a, b: a % b)
    or_ = staticmethod(lambda a, b: a | b)
    pow = staticmethod(lambda a, b: a ** b)
    rshift = staticmethod(lambda a, b: a >> b)
    sub = staticmethod(lambda a, b: a - b)
    truediv = staticmethod(lambda a, b: a / b)
    xor = staticmethod(lambda a, b: a ^ b)
    lt = staticmethod(lambda a, b: a < b)
    le = staticmethod(lambda a, b: a <= b)
    eq = staticmethod(lambda a, b: a == b)
    ne = staticmethod(lambda a, b: a != b)
    gt = staticmethod(lambda a, b: a > b)
    ge = staticmethod(lambda a, b: a >= b)


_OPERATOR_FOR_NB = {
    "NB_ADD": _operator.add, "NB_AND": _operator.and_, "NB_FLOOR_DIVIDE": _operator.floordiv,
    "NB_LSHIFT": _operator.lshift, "NB_MULTIPLY": _operator.mul,
    "NB_REMAINDER": _operator.mod, "NB_OR": _operator.or_, "NB_POWER": _operator.pow,
    "NB_RSHIFT": _operator.rshift, "NB_SUBTRACT": _operator.sub,
    "NB_TRUE_DIVIDE": _operator.truediv, "NB_XOR": _operator.xor,
    "NB_INPLACE_ADD": _operator.add, "NB_INPLACE_AND": _operator.and_,
    "NB_INPLACE_FLOOR_DIVIDE": _operator.floordiv, "NB_INPLACE_LSHIFT": _operator.lshift,
    "NB_INPLACE_MULTIPLY": _operator.mul, "NB_INPLACE_REMAINDER": _operator.mod,
    "NB_INPLACE_OR": _operator.or_, "NB_INPLACE_POWER": _operator.pow,
    "NB_INPLACE_RSHIFT": _operator.rshift, "NB_INPLACE_SUBTRACT": _operator.sub,
    "NB_INPLACE_TRUE_DIVIDE": _operator.truediv, "NB_INPLACE_XOR": _operator.xor,
}
_NUMBER_BINOPS = tuple(_OPERATOR_FOR_NB.get(name) for name, _ in _opcode._nb_ops)
_ADD_ONLY = tuple(_operator.add if name == "NB_ADD" else None
                  for name, _ in _opcode._nb_ops)
_ADD_IMMUTABLE = tuple(_operator.add if name in ("NB_ADD", "NB_INPLACE_ADD") else None
                       for name, _ in _opcode._nb_ops)    # str, tuple: += is +
_NUMBER_TYPES = frozenset((int, float))
_COMPARE_FUNCS = (_operator.lt, _operator.le, _operator.eq, _operator.ne, _operator.gt,
                  _operator.ge)
_COMPARE_TYPES = frozenset((int, float, str))
_TRUTH_TYPES = frozenset((int, float, str, bytes, list, tuple, dict, set, frozenset))

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


_type_fullname = _obj._type_fullname


def _function_str(func) -> str:
    """_PyObject_FunctionStr."""
    qualname = PyObject_GetOptionalAttr(func, "__qualname__")
    if qualname is NULL or qualname is None:
        return str(func)
    module = PyObject_GetOptionalAttr(func, "__module__")
    if module is not NULL and module is not None and module != "builtins":
        return f"{module}.{qualname}()"
    return f"{qualname}()"


def _check_iterable(obj, what: str) -> None:
    """Value after * (or **) must be an iterable (check_args_iterable)."""
    tp = Py_TYPE(obj)
    if tp.tp_iter is None and not PySequence_Check(obj):
        raise TypeError(f"Value after * must be an iterable, not {tp.tp_name}")


def _PyMapping_GetOptionalItem(mapping, key):
    """The item, or _MISSING if the key is absent (a KeyError is suppressed)."""
    if type(mapping) is dict:
        return _dict_get(mapping, key, _MISSING)
    err = None
    res = _MISSING
    try:
        res = PyObject_GetItem(mapping, key)
    except KeyError as e:
        err = True    # not the exception itself: it would form a cycle with its traceback
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        return _MISSING
    return res


_dict_get = dict.get
_dict_setitem = dict.__setitem__
_dict_update = dict.update
_list_append = list.append
_set_add = set.add
_tb_get = BaseException.__dict__["__traceback__"].__get__
_set_cause = BaseException.__dict__["__cause__"].__set__


def _PyDict_Update(a: dict, b) -> None:
    """PyDict_Update(a, b): `b` is a dict or has the mapping protocol (keys + getitem)."""
    if type(b) is dict:
        _dict_update(a, b)
        return
    keys_attr = PyObject_GetOptionalAttr(b, "keys")
    if keys_attr is NULL:
        raise TypeError(f"'{Py_TYPE(b).tp_name}' object is not a mapping")
    keys = _call.PyObject_CallNoArgs(keys_attr)
    it = PyObject_GetIter(keys)
    while True:
        key = PyIter_Next(it)
        if key is NULL:
            return
        _dict_setitem(a, key, PyObject_GetItem(b, key))


def _PyList_Extend(lst: list, iterable) -> None:
    it = PyObject_GetIter(iterable)
    while True:
        item = PyIter_Next(it)
        if item is NULL:
            return
        _list_append(lst, item)


def _unpack(seq, before: int, after: int | None) -> list:
    """_PyEval_UnpackIterable: the unpacked values in source order (after=None: exact count)."""
    err = None
    it = NULL
    try:
        it = PyObject_GetIter(seq)
    except TypeError as e:
        err = True    # not the exception itself: it would form a cycle with its traceback
    if err is not None:
        # Re-raise unless the object is simply not iterable.
        _PyErr_Clear(_PyThreadState_GET())
        if Py_TYPE(seq).tp_iter is None and not PySequence_Check(seq):
            raise TypeError(f"cannot unpack non-iterable {Py_TYPE(seq).tp_name} object")
        raise err
    vals = []
    for _ in range(before):
        w = PyIter_Next(it)
        if w is NULL:
            raise ValueError(f"not enough values to unpack (expected "
                             f"{'at least ' if after is not None else ''}"
                             f"{before + (after or 0)}, got {len(vals)})")
        vals.append(w)
    if after is None:
        w = PyIter_Next(it)
        if w is not NULL:
            # We better have exhausted the iterator now.
            tp = type(seq)
            if tp is list or tp is tuple or tp is dict:
                raise ValueError(f"too many values to unpack "
                                 f"(expected {before}, got {len(seq)})")
            raise ValueError(f"too many values to unpack (expected {before})")
        return vals
    rest = []
    while True:
        w = PyIter_Next(it)
        if w is NULL:
            break
        rest.append(w)
    if len(rest) < after:
        raise ValueError(f"not enough values to unpack (expected at least "
                         f"{before + after}, got {before + len(rest)})")
    cut = len(rest) - after
    return vals + [rest[:cut]] + rest[cut:]


def _check_except_type(right) -> None:
    items = right if type(right) is tuple else (right,)
    for exc in items:
        if not PyExceptionClass_Check(exc):
            raise TypeError(CANNOT_CATCH_MSG)


def _exception_group_match(exc_value, match_type):
    """_PyEval_ExceptionGroupMatch -> (match, rest)."""
    if exc_value is None:
        return None, None
    if PyErr_GivenExceptionMatches(exc_value, match_type):
        # Full match of exc itself
        if PyObject_TypeCheck(exc_value, BaseExceptionGroup):
            return exc_value, None
        # Naked exception: wrap it in an exception group
        return _call.PyObject_Vectorcall(BaseExceptionGroup, ("", [exc_value])), None
    # exc_value does not match match_type; maybe it's a group that contains matches.
    if PyObject_TypeCheck(exc_value, BaseExceptionGroup):
        split = _call.PyObject_CallOneArg(PyObject_GetAttr(exc_value, "split"), match_type)
        if type(split) is not tuple:
            raise TypeError(f"{Py_TYPE(exc_value).tp_name}.split must return a tuple, "
                            f"not {Py_TYPE(split).tp_name}")
        if len(split) < 2:
            raise TypeError(f"{Py_TYPE(exc_value).tp_name}.split must return a 2-tuple, "
                            f"got tuple of size {len(split)}")
        return split[0], split[1]
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
    return PyObject_GetOptionalAttr(subject, name)


def _match_class(subject, type_, nargs, kwargs):
    """_PyEval_MatchClass: tuple of attributes, or None if no match."""
    if not PyType_Check(type_):
        raise TypeError("class pattern must refer to a class")
    if not PyObject_IsInstance(subject, type_):
        return None
    nattrs = nargs + len(kwargs)
    if not nattrs:
        return ()
    seen = set() if nargs > 0 and nattrs > 1 else None
    attrs = []
    if nargs:
        match_self = False
        match_args = PyObject_GetOptionalAttr(type_, "__match_args__")
        if match_args is not NULL:
            if type(match_args) is not tuple:
                raise TypeError(f"{type_.__name__}.__match_args__ must be a tuple "
                                f"(got {Py_TYPE(match_args).tp_name})")
        else:
            match_args = ()
            match_self = bool(PyType_View(type_).tp_flags & _TPFLAGS_MATCH_SELF)
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
                                    f"(got {Py_TYPE(name).tp_name})")
                attr = _match_class_attr(subject, type_, name, seen)
                if attr is NULL:
                    return None
                attrs.append(attr)
    for name in kwargs:
        attr = _match_class_attr(subject, type_, name, seen)
        if attr is NULL:
            return None
        attrs.append(attr)
    return tuple(attrs)


def _match_keys(subject, keys):
    """_PyEval_MatchKeys: tuple of values, or None if a key is missing."""
    if not keys:
        return ()
    get = PyObject_GetAttr(subject, "get")
    seen = set()
    dummy = object()
    values = []
    for key in keys:
        if key in seen:
            raise ValueError(f"mapping pattern checks duplicate key ({key!r})")
        seen.add(key)
        v = _call.PyObject_Vectorcall(get, (key, dummy))
        if v is dummy:
            return None
        values.append(v)
    return tuple(values)


def _PyEval_GetAwaitable(iterable, oparg):
    tp = PyType_View(type(iterable))
    if tp.am_await is None and not gen_is_coroutine(iterable):
        if oparg == 1:
            raise TypeError("'async with' received an object from __aenter__ that does not "
                            f"implement __await__: {tp.tp_name[:100]}")
        if oparg == 2:
            raise TypeError("'async with' received an object from __aexit__ that does not "
                            f"implement __await__: {tp.tp_name[:100]}")
    it = PyCoro_GetAwaitableIter(iterable)
    if PyCoro_CheckExact(it) and it.gi_frame_state in (FRAME_SUSPENDED_YIELD_FROM,
                                                       FRAME_SUSPENDED_YIELD_FROM_LOCKED):
        raise RuntimeError("coroutine is being awaited already")
    return it


def _PyEval_GetANext(aiter):
    tp = PyType_View(type(aiter))
    if type(aiter) is PyAsyncGenObject:
        return tp.am_anext(aiter)
    getter = tp.am_anext
    if getter is None:
        raise TypeError("'async for' requires an iterator with __anext__ method, "
                        f"got {tp.tp_name[:100]}")
    next_iter = getter(aiter)
    err = None
    try:
        return PyCoro_GetAwaitableIter(next_iter)
    except TypeError as e:
        err = e
    new = TypeError("'async for' received an invalid object from __anext__: "
                    f"{PyType_View(type(next_iter)).tp_name[:100]}")
    new.__cause__ = err
    raise new


class VirtualMachine:
    def __init__(self, path: list | None = None):
        from pp.builtins import make_builtins
        from pp.importer import Importer

        self.frame: Frame | None = None
        self.tstate = PyThreadState()
        self.tstate.eval_frame = self.run_frame
        self.tstate.vm = self
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
            globals = {"__name__": "__main__", "__builtins__": self.builtins_module}
        if "__builtins__" not in globals:
            globals["__builtins__"] = self.builtins_module
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
            func.func_closure = tuple(closure)
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
        nargs = len(args)
        if (nargs == code.co_argcount and not kwargs and not code.co_flags & 0xC
                and not code.co_kwonlyargcount):
            frame.localsplus[:nargs] = args          # the plain positional case
        else:
            bind_arguments(func, frame.localsplus, frame.localsplusnames, args, kwargs)
        return self.run_frame(frame)

    def call(self, callable, args, kwargs=None):
        return _call._PyObject_Call(callable, tuple(args), kwargs or None)

    def run_frame(self, frame: Frame, throw: BaseException | None = None) -> object:
        """Execute `frame` until it returns or yields; `throw` resumes it with an exception."""
        tstate = self.tstate
        prev_tstate = _errors._current_tstate
        if prev_tstate is not tstate:
            _PyThreadState_Swap(tstate)
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
                        if e is not tstate.current_exception:
                            # Raised by host code during this instruction:
                            # _PyErr_SetObject chains it to the handled exception.
                            _PyErr_SetObject(tstate, e)
                # exception_unwind: find the handler for the faulting instruction.
                entry = None
                for e in decoded.exception_table:
                    if e.start <= cur < e.end:
                        entry = e
                        break
                if entry is None:
                    _PyErr_SetRaisedException(tstate, exc)
                    raise exc
                _PyErr_Clear(tstate)
                del stack[entry.depth:]
                if entry.lasti:
                    stack.append(frame.lasti)
                stack.append(exc)
                frame.instr_offset = entry.target
                exc = None
        finally:
            self.frame = frame.previous
            if prev_tstate is not tstate:
                _PyThreadState_Swap(prev_tstate)

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
        v = _PyMapping_GetOptionalItem(f.locals, name)
        if v is _MISSING:
            v = _dict_get(f.globals, name, _MISSING)
            if v is _MISSING:
                v = _dict_get(f.builtins, name, _MISSING)
                if v is _MISSING:
                    raise _name_error(name)
        f.stack.append(v)

    def STORE_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        ns = f.locals
        if ns is None:
            raise SystemError(f"no locals found when storing {name!r}")
        v = f.stack.pop()
        if type(ns) is dict:
            _dict_setitem(ns, name, v)
        else:
            PyObject_SetItem(ns, name, v)

    def DELETE_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        ns = f.locals
        if ns is None:
            raise SystemError(f"no locals when deleting {name!r}")
        err = None
        try:
            PyObject_DelItem(ns, name)
        except KeyError as e:
            err = True    # not the exception itself: it would form a cycle with its traceback
        if err is not None:
            _PyErr_Clear(_PyThreadState_GET())
            raise _name_error(name)

    def _load_global(self, f, name):
        v = _dict_get(f.globals, name, _MISSING)
        if v is _MISSING:
            v = _dict_get(f.builtins, name, _MISSING)
            if v is _MISSING:
                raise _name_error(name)
        return v

    def LOAD_GLOBAL(self, f, i):
        name = f.code.co_names[i.arg >> 1]
        v = _dict_get(f.globals, name, _MISSING)
        if v is _MISSING:
            v = _dict_get(f.builtins, name, _MISSING)
            if v is _MISSING:
                raise _name_error(name)
        f.stack.append(v)
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
        v = _PyMapping_GetOptionalItem(mapping, name)
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
        closure = f.func.func_closure
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
        v = _PyMapping_GetOptionalItem(class_dict, name)
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
        f.stack.append(PyFunction_New(code, f.globals, self))

    def SET_FUNCTION_ATTRIBUTE(self, f, i):
        func = f.stack.pop()
        attr = f.stack.pop()
        flag = i.arg
        if flag == 0x01:
            func.func_defaults = attr
        elif flag == 0x02:
            func.func_kwdefaults = attr
        elif flag == 0x04:
            func.func_annotations = attr
        elif flag == 0x08:
            func.func_closure = attr
        elif flag == 0x10:
            func.func_annotate = attr
        else:
            raise SystemError(f"bad oparg {flag} for SET_FUNCTION_ATTRIBUTE")
        f.stack.append(func)

    def _call(self, f, nargs, kwnames):
        stack = f.stack
        if nargs:
            args = stack[-nargs:]
            del stack[-nargs:]
        else:
            args = []
        self_or_null = stack.pop()
        callable = stack.pop()
        if self_or_null is not NULL:
            args.insert(0, self_or_null)
        if not kwnames:
            tc = type(callable)
            if tc is Function:
                # _PyFunction_Vectorcall
                stack.append(callable._vm.call_function(callable, args, None))
                return
            if tc is _MethodType:
                # _PyObject_Vectorcall of a bound method: prepend self
                func = callable.__func__
                if type(func) is Function:
                    args.insert(0, callable.__self__)
                    stack.append(func._vm.call_function(func, args, None))
                    return
            elif tc is _MethodDescriptorType:
                # CALL_METHOD_DESCRIPTOR_*: method_vectorcall of a host C method
                stack.append(callable(*args))
                return
            elif tc is _BuiltinFunction and len(args) != 4:
                # CALL_BUILTIN_FAST: cfunction_call minus the type.__new__ special case
                stack.append(callable(*args))
                return
        stack.append(_call.PyObject_Vectorcall(callable, args, kwnames))

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
            _check_iterable(callargs, "*")
            callargs = PySequence_Tuple(callargs)
        if kwargs is NULL:
            kwargs = None
        f.stack.append(_call._PyObject_Call(func, callargs, kwargs))

    def DICT_MERGE(self, f, i):
        update = f.stack.pop()
        d = f.stack[-i.arg]
        callable = f.stack[-i.arg - 3]
        if type(update) is dict:
            items = update.items()
        else:
            keys_attr = PyObject_GetOptionalAttr(update, "keys")
            if keys_attr is NULL:
                raise TypeError(f"Value after ** must be a mapping, not {Py_TYPE(update).tp_name}")
            it = PyObject_GetIter(_call.PyObject_CallNoArgs(keys_attr))
            items = []
            while True:
                k = PyIter_Next(it)
                if k is NULL:
                    break
                items.append((k, PyObject_GetItem(update, k)))
        for k, v in items:
            if _dict_get(d, k, _MISSING) is not _MISSING:
                raise TypeError(
                    f"{_function_str(callable)} got multiple values for keyword argument '{k}'")
            _dict_setitem(d, k, v)

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
            cls = PyCoroObject
        elif flags & CO_ASYNC_GENERATOR:
            cls = PyAsyncGenObject
        else:
            cls = PyGenObject
        f.return_value = cls(f, f.func, self.tstate)
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
        kind, res = PyIter_Send(receiver, v)
        f.stack.append(res)
        if kind == PYGEN_RETURN:
            f.instr_offset = i.jump_target

    def END_SEND(self, f, i):
        value = f.stack.pop()
        f.stack.pop()
        f.stack.pop()
        f.stack.append(value)

    def CLEANUP_THROW(self, f, i):
        exc_value = f.stack.pop()
        if not PyObject_TypeCheck(exc_value, StopIteration):
            _PyErr_SetRaisedException(self.tstate, exc_value)
            raise exc_value
        f.stack.pop()            # last_sent_val
        null = f.stack.pop()
        f.stack.pop()            # sub_iter
        f.stack.append(None)
        f.stack.append(null)
        f.stack.append(exc_value.value)

    # --- coroutines (async def / await / async for / async with) ---

    def GET_AWAITABLE(self, f, i):
        f.stack.append(_PyEval_GetAwaitable(f.stack.pop(), i.arg))

    def GET_AITER(self, f, i):
        obj = f.stack.pop()
        tp = PyType_View(type(obj))
        getter = tp.am_aiter
        if getter is None:
            raise TypeError("'async for' requires an object with __aiter__ method, "
                            f"got {tp.tp_name[:100]}")
        it = getter(obj)
        it_tp = PyType_View(type(it))
        if it_tp.am_anext is None:
            raise TypeError("'async for' received an object from __aiter__ that does not "
                            f"implement __anext__: {it_tp.tp_name[:100]}")
        f.stack.append(it)

    def GET_ANEXT(self, f, i):
        f.stack.append(_PyEval_GetANext(f.stack[-1]))

    def END_ASYNC_FOR(self, f, i):
        exc = f.stack.pop()
        f.stack.pop()            # awaitable
        if not PyErr_GivenExceptionMatches(exc, StopAsyncIteration):
            _PyErr_SetRaisedException(self.tstate, exc)
            raise exc

    # --- exceptions ---

    def RAISE_VARARGS(self, f, i):
        cause = f.stack.pop() if i.arg == 2 else _MISSING
        exc = f.stack.pop() if i.arg >= 1 else _MISSING
        if exc is _MISSING:
            top = _PyErr_GetTopmostException(self.tstate).exc_value
            if top is None:
                raise RuntimeError("No active exception to reraise")
            _PyErr_SetRaisedException(self.tstate, top)
            raise top
        if PyExceptionClass_Check(exc):
            value = _call.PyObject_CallNoArgs(exc)
            if not _PyExceptionInstance_Check(value):
                raise TypeError(f"calling {exc!r} should have returned an instance of "
                                f"BaseException, not {type(value)!r}")
        elif _PyExceptionInstance_Check(exc):
            value = exc
        else:
            raise TypeError("exceptions must derive from BaseException")
        if cause is not _MISSING:
            if PyExceptionClass_Check(cause):
                fixed = _call.PyObject_CallNoArgs(cause)
                if not _PyExceptionInstance_Check(fixed):
                    raise TypeError(f"calling {cause!r} should have returned an instance of "
                                    f"BaseException, not {type(fixed)!r}")
            elif _PyExceptionInstance_Check(cause) or cause is None:
                fixed = cause
            else:
                raise TypeError("exception causes must derive from BaseException")
            _set_cause(value, fixed)
        _PyErr_SetObject(self.tstate, value)
        raise value

    def RERAISE(self, f, i):
        exc = f.stack.pop()
        if i.arg:
            f.lasti = f.stack[-i.arg]
        _PyErr_SetRaisedException(self.tstate, exc)
        raise exc

    def PUSH_EXC_INFO(self, f, i):
        exc = f.stack.pop()
        info = self.tstate.exc_info
        f.stack.append(info.exc_value)
        info.exc_value = exc
        f.stack.append(exc)

    def POP_EXCEPT(self, f, i):
        self.tstate.exc_info.exc_value = f.stack.pop()

    def CHECK_EXC_MATCH(self, f, i):
        right = f.stack.pop()
        left = f.stack[-1]
        _check_except_type(right)
        f.stack.append(PyErr_GivenExceptionMatches(left, right))

    def CHECK_EG_MATCH(self, f, i):
        match_type = f.stack.pop()
        exc_value = f.stack.pop()
        _check_except_type(match_type)
        items = match_type if type(match_type) is tuple else (match_type,)
        if any(PyType_IsSubtype(PyType_View(t), PyType_View(BaseExceptionGroup)) for t in items):
            raise TypeError(CANNOT_EXCEPT_STAR_EG)
        match, rest = _exception_group_match(exc_value, match_type)
        if match is not None:
            self.tstate.exc_info.exc_value = match
        f.stack.append(rest)
        f.stack.append(match)

    def WITH_EXCEPT_START(self, f, i):
        val = f.stack[-1]
        exit_self = f.stack[-4]
        exit_func = f.stack[-5]
        tb = _tb_get(val)
        if exit_self is NULL:
            res = _call.PyObject_Vectorcall(exit_func, (type(val), val, tb))
        else:
            res = _call.PyObject_Vectorcall(exit_func, (exit_self, type(val), val, tb))
        f.stack.append(res)

    def LOAD_SPECIAL(self, f, i):
        owner = f.stack.pop()
        name = SPECIAL_METHODS[i.arg]
        found = _PyObject_LookupSpecialMethod(name, owner)
        if found is None:
            tp = type(owner)
            msg = _SPECIAL_ERRORS[name].format(_type_fullname(tp))
            other, suggestion = _SPECIAL_SUGGEST[name]
            if _PyType_Lookup(type(owner), other) is not NULL:
                msg += suggestion
            raise TypeError(msg)
        method, self_or_null = found
        f.stack.append(method)
        f.stack.append(self_or_null)

    # --- operators ---

    def BINARY_OP(self, f, i):
        stack = f.stack
        rhs = stack.pop()
        lhs = stack.pop()
        tl = type(lhs)
        tr = type(rhs)
        if tl in _NUMBER_TYPES and tr in _NUMBER_TYPES:
            fn = _NUMBER_BINOPS[i.arg]
            if fn is not None:
                stack.append(fn(lhs, rhs))
                return
        elif tl is tr and (tl is str or tl is list or tl is tuple):
            fn = (_ADD_ONLY if tl is list else _ADD_IMMUTABLE)[i.arg]
            if fn is not None:
                stack.append(fn(lhs, rhs))
                return
        if tl in _SUBSCRIPT_TYPES and i.arg == _NB_SUBSCR:
            # BINARY_OP_SUBSCR_LIST_INT / _TUPLE_INT / _DICT / _STR_INT & co: the
            # exact builtin container's own mp_subscript.
            stack.append(lhs[rhs])
            return
        stack.append(BINARY_OPS[i.arg](lhs, rhs))

    def BINARY_SLICE(self, f, i):
        stop = f.stack.pop()
        start = f.stack.pop()
        container = f.stack.pop()
        f.stack.append(PyObject_GetItem(container, slice(start, stop)))

    def STORE_SLICE(self, f, i):
        stop = f.stack.pop()
        start = f.stack.pop()
        container = f.stack.pop()
        v = f.stack.pop()
        PyObject_SetItem(container, slice(start, stop), v)

    def STORE_SUBSCR(self, f, i):
        sub = f.stack.pop()
        container = f.stack.pop()
        v = f.stack.pop()
        if type(container) is dict or type(container) is list:
            container[sub] = v          # STORE_SUBSCR_DICT / _LIST_INT
            return
        PyObject_SetItem(container, sub, v)

    def DELETE_SUBSCR(self, f, i):
        sub = f.stack.pop()
        container = f.stack.pop()
        PyObject_DelItem(container, sub)

    def UNARY_NEGATIVE(self, f, i):
        f.stack.append(PyNumber_Negative(f.stack.pop()))

    def UNARY_INVERT(self, f, i):
        f.stack.append(PyNumber_Invert(f.stack.pop()))

    def UNARY_NOT(self, f, i):
        f.stack.append(f.stack.pop() is False)  # TO_BOOL always precedes

    def TO_BOOL(self, f, i):
        stack = f.stack
        v = stack.pop()
        if v is True or v is False:
            stack.append(v)
        elif v is None:
            stack.append(False)
        elif type(v) in _TRUTH_TYPES:
            stack.append(bool(v))
        else:
            stack.append(PyObject_IsTrue(v))

    def COMPARE_OP(self, f, i):
        stack = f.stack
        right = stack.pop()
        left = stack.pop()
        tl = type(left)
        tr = type(right)
        if tl in _COMPARE_TYPES and (tl is tr or (tl is not str and tr is not str and tr in _COMPARE_TYPES)):
            stack.append(_COMPARE_FUNCS[i.arg >> 5](left, right))
            return
        res = PyObject_RichCompare(left, right, i.arg >> 5)
        if i.arg & 16:
            res = PyObject_IsTrue(res)
        stack.append(res)

    def IS_OP(self, f, i):
        right = f.stack.pop()
        left = f.stack.pop()
        f.stack.append((left is right) ^ bool(i.arg))

    def CONTAINS_OP(self, f, i):
        right = f.stack.pop()
        left = f.stack.pop()
        if type(right) in _CONTAINS_TYPES:
            # CONTAINS_OP_DICT / _SET: the exact builtin's own sq_contains.
            f.stack.append((left in right) ^ bool(i.arg))
            return
        f.stack.append(PySequence_Contains(right, left) ^ bool(i.arg))

    # --- control flow ---

    def POP_JUMP_IF_TRUE(self, f, i):
        if f.stack.pop() is True:
            f.instr_offset = i.jump_target

    def POP_JUMP_IF_FALSE(self, f, i):
        if f.stack.pop() is False:
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
        v = f.stack.pop()
        f.stack.append(iter(v) if type(v) in _ITER_TYPES else PyObject_GetIter(v))
        f.stack.append(NULL)  # index_or_null: always NULL in pp

    def FOR_ITER(self, f, i, _fast=_FAST_ITERATORS, _next=_next, _MISSING=_MISSING, _type=type):
        stack = f.stack
        it = stack[-2]
        if _type(it) in _fast:
            # FOR_ITER_LIST / _TUPLE / _RANGE & co: the C tp_iternext of an exact
            # builtin iterator, without the exception for the exhausted case.
            v = _next(it, _MISSING)
            if v is not _MISSING:
                stack.append(v)
                return
        else:
            try:
                stack.append(Py_TYPE(it).tp_iternext(it))
                return
            except StopIteration:
                _PyErr_Clear(self.tstate)
        # Exhausted: jump past the END_FOR at the target, leaving iter/null for POP_ITER.
        f.instr_offset = i.jump_target + 2

    def END_FOR(self, f, i):
        f.stack.pop()

    def POP_ITER(self, f, i):
        f.stack.pop()
        f.stack.pop()

    def GET_LEN(self, f, i):
        f.stack.append(PyObject_Size(f.stack[-1]))

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
            _dict_setitem(d, vals[k], vals[k + 1])
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
        _check_iterable(iterable, "*")
        _PyList_Extend(f.stack[-i.arg], iterable)

    def SET_ADD(self, f, i):
        v = f.stack.pop()
        f.stack[-i.arg].add(v)

    def SET_UPDATE(self, f, i):
        iterable = f.stack.pop()
        it = PyObject_GetIter(iterable)
        st = f.stack[-i.arg]
        while True:
            item = PyIter_Next(it)
            if item is NULL:
                break
            _set_add(st, item)

    def MAP_ADD(self, f, i):
        value = f.stack.pop()
        key = f.stack.pop()
        _dict_setitem(f.stack[-i.arg], key, value)

    def DICT_UPDATE(self, f, i):
        update = f.stack.pop()
        _PyDict_Update(f.stack[-i.arg], update)

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
        name = f.code.co_names[i.arg >> 1]
        if i.arg & 1:
            # Method form: (unbound method, self) if the attribute is a method, else (attr, NULL).
            view = _views_get(id(type(owner))) or Py_TYPE(owner)
            if view.tp_getattro is _GenericGetAttr:
                # _PyObject_GetMethod for the common case: a plain function or a C
                # method descriptor in the type, not shadowed by the instance dict.
                descr = _PyType_Lookup(type(owner), name)
                if type(descr) is Function or type(descr) is _MethodDescriptorType:
                    kind = view.tp_dictkind
                    if kind == DICT_NONE or (kind == DICT_STD and name not in owner.__dict__):
                        f.stack.append(descr)
                        f.stack.append(owner)
                        return
            attr, meth_found = _PyObject_GetMethod(owner, name)
            f.stack.append(attr)
            f.stack.append(owner if meth_found else NULL)
        else:
            view = _views_get(id(type(owner))) or Py_TYPE(owner)
            if view.tp_getattro is _GenericGetAttr:
                # PyObject_GetAttr -> tp_getattro, minus the error-context wrapper
                # (the generic getattr sets name/obj itself).
                if view.tp_dictkind == DICT_STD:
                    # An instance attribute of a plain object: nothing in the type
                    # (not even a non-data descriptor) shadows it.
                    if _PyType_Lookup(type(owner), name) is NULL:
                        res = owner.__dict__.get(name, NULL)
                        if res is not NULL:
                            f.stack.append(res)
                            return
                f.stack.append(_GenericGetAttr(owner, name))
            else:
                f.stack.append(PyObject_GetAttr(owner, name))

    def STORE_ATTR(self, f, i):
        owner = f.stack.pop()
        v = f.stack.pop()
        name = f.code.co_names[i.arg]
        view = _views_get(id(type(owner))) or Py_TYPE(owner)
        if view.tp_setattro is _GenericSetAttr and view.tp_getattro is _GenericGetAttr \
                and view.tp_dictkind == DICT_STD:
            # PyObject_GenericSetAttr for a plain instance: no descriptor in the way.
            if _PyType_Lookup(type(owner), name) is NULL:
                _dict_setitem(owner.__dict__, name, v)
                return
        PyObject_SetAttr(owner, name, v)

    def DELETE_ATTR(self, f, i):
        PyObject_SetAttr(f.stack.pop(), f.code.co_names[i.arg], NULL)

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
        super_type = self.builtins.get("super")
        if global_super is super_type and PyType_Check(cls):
            # The specialized LOAD_SUPER_ATTR_ATTR / _METHOD: _PySuper_Lookup.
            attr, method = _PySuper_Lookup(
                cls, self_, name, super_type,
                (i.arg & 1) and Py_TYPE(self_).tp_getattro is _obj.PyObject_GenericGetAttr)
        else:
            sup = _call.PyObject_Vectorcall(global_super, (cls, self_) if i.arg & 2 else ())
            attr = PyObject_GetAttr(sup, name)
            method = False
        f.stack.append(attr)
        if i.arg & 1:
            f.stack.append(self_ if method else NULL)

    def SETUP_ANNOTATIONS(self, f, i):
        if f.locals is None:
            raise SystemError("no locals found when setting up annotations")
        if _PyMapping_GetOptionalItem(f.locals, "__annotations__") is not _MISSING:
            return
        if type(f.locals) is dict:
            _dict_setitem(f.locals, "__annotations__", {})
        else:
            PyObject_SetItem(f.locals, "__annotations__", {})

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
        if PyObject_TypeCheck(exc, StopIteration):
            if flags & CO_ASYNC_GENERATOR:
                msg = "async generator raised StopIteration"
            elif flags & CO_COROUTINE:
                msg = "coroutine raised StopIteration"
            else:
                msg = "generator raised StopIteration"
        elif flags & CO_ASYNC_GENERATOR and PyObject_TypeCheck(exc, StopAsyncIteration):
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
        lambda self, f, v: PyAsyncGenWrappedValue(v),   # INTRINSIC_ASYNC_GEN_WRAP
        lambda self, f, v: PyNumber_Positive(v),   # INTRINSIC_UNARY_POSITIVE
        lambda self, f, v: tuple(v),          # INTRINSIC_LIST_TO_TUPLE (v is always a list)
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
        func.func_typeparams = params
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
    mod.__dict__["__builtins__"] = vm.builtins_module  # like CPython's __main__
    vm.modules["__main__"] = mod
    return mod
