"""The abstract object layer, modeled on Objects/abstract.c.

Number, sequence/mapping and iterator protocols dispatching through the
slots of `pp.typeobject`. Only what the VM calls exists here.
"""

import types

from pp.errors import _PyErr_Clear, _PyThreadState_GET
from pp.frame import NULL
from pp.object import (PyObject_GetAttr, PyObject_GetOptionalAttr, PyObject_RichCompareBool,
                       Py_EQ, _type_fullname)
from pp.typeobject import (Py_TPFLAGS_HEAPTYPE, Py_TYPE, PyType_Check, PyType_IsSubtype, PyType_View,
                           _PyObject_NextNotImplemented, register_static_slots)
from pp import call as _call

PY_ITERSEARCH_COUNT = 1
PY_ITERSEARCH_INDEX = 2
PY_ITERSEARCH_CONTAINS = 3

_int_lt = int.__lt__
_GenericAlias = types.GenericAlias


def _type_error(msg, obj):
    return TypeError(msg % Py_TYPE(obj).tp_name)


# --- index ----------------------------------------------------------------------

def _PyIndex_Check(obj) -> bool:
    return Py_TYPE(obj).nb_index is not None


def PyLong_Check(obj) -> bool:
    if type(obj) is int:
        return True
    return PyType_IsSubtype(Py_TYPE(obj), PyType_View(int))


def _PyLong_IsNegative(x) -> bool:
    return _int_lt(x, 0)


def _PyNumber_Index(item):
    """An int from `item`; raises TypeError if it cannot be interpreted as one."""
    if PyLong_Check(item):
        return item
    if not _PyIndex_Check(item):
        raise TypeError(f"'{Py_TYPE(item).tp_name}' object cannot be interpreted as an integer")
    result = Py_TYPE(item).nb_index(item)
    if not PyLong_Check(result):
        raise TypeError(f"__index__ returned non-int (type {Py_TYPE(result).tp_name})")
    return result


# --- numbers --------------------------------------------------------------------

def binary_op1(v, w, op_slot):
    v_view = Py_TYPE(v)
    w_view = Py_TYPE(w)
    slotv = getattr(v_view, op_slot)
    if w_view is not v_view:
        slotw = getattr(w_view, op_slot)
        if slotw is slotv:
            slotw = None
    else:
        slotw = None

    if slotv is not None:
        if slotw is not None and PyType_IsSubtype(w_view, v_view):
            x = slotw(v, w)
            if x is not NotImplemented:
                return x
            slotw = None
        x = slotv(v, w)
        if x is not NotImplemented:
            return x
    if slotw is not None:
        x = slotw(v, w)
        if x is not NotImplemented:
            return x
    return NotImplemented


def binop_type_error(v, w, op_name):
    return TypeError(f"unsupported operand type(s) for {op_name}: "
                     f"'{Py_TYPE(v).tp_name}' and '{Py_TYPE(w).tp_name}'")


def ternary_op(v, w, z, op_slot, op_name):
    v_view = Py_TYPE(v)
    w_view = Py_TYPE(w)
    slotv = getattr(v_view, op_slot)
    if w_view is not v_view:
        slotw = getattr(w_view, op_slot)
        if slotw is slotv:
            slotw = None
    else:
        slotw = None

    if slotv is not None:
        if slotw is not None and PyType_IsSubtype(w_view, v_view):
            x = slotw(v, w, z)
            if x is not NotImplemented:
                return x
            slotw = None
        x = slotv(v, w, z)
        if x is not NotImplemented:
            return x
    if slotw is not None:
        x = slotw(v, w, z)
        if x is not NotImplemented:
            return x
    slotz = getattr(Py_TYPE(z), op_slot)
    if slotz is slotv or slotz is slotw:
        slotz = None
    if slotz is not None:
        x = slotz(v, w, z)
        if x is not NotImplemented:
            return x
    if z is None:
        raise TypeError(f"unsupported operand type(s) for {op_name}: "
                        f"'{v_view.tp_name}' and '{w_view.tp_name}'")
    raise TypeError(f"unsupported operand type(s) for {op_name}: "
                    f"'{v_view.tp_name}', '{w_view.tp_name}', '{Py_TYPE(z).tp_name}'")


def _binary_func(op_slot, op_name):
    def func(v, w):
        result = binary_op1(v, w, op_slot)
        if result is NotImplemented:
            raise binop_type_error(v, w, op_name)
        return result
    return func


PyNumber_Or = _binary_func("nb_or", "|")
PyNumber_Xor = _binary_func("nb_xor", "^")
PyNumber_And = _binary_func("nb_and", "&")
PyNumber_Lshift = _binary_func("nb_lshift", "<<")
PyNumber_Rshift = _binary_func("nb_rshift", ">>")
PyNumber_Subtract = _binary_func("nb_subtract", "-")
PyNumber_MatrixMultiply = _binary_func("nb_matrix_multiply", "@")
PyNumber_FloorDivide = _binary_func("nb_floor_divide", "//")
PyNumber_TrueDivide = _binary_func("nb_true_divide", "/")
PyNumber_Remainder = _binary_func("nb_remainder", "%")


def PyNumber_Add(v, w):
    result = binary_op1(v, w, "nb_add")
    if result is not NotImplemented:
        return result
    sq_concat = Py_TYPE(v).sq_concat
    if sq_concat is not None:
        return sq_concat(v, w)
    raise binop_type_error(v, w, "+")


def sequence_repeat(repeatfunc, seq, n):
    if not _PyIndex_Check(n):
        raise _type_error("can't multiply sequence by non-int of type '%.200s'", n)
    return repeatfunc(seq, n)


def PyNumber_Multiply(v, w):
    result = binary_op1(v, w, "nb_multiply")
    if result is NotImplemented:
        mv = Py_TYPE(v).sq_repeat
        mw = Py_TYPE(w).sq_repeat
        if mv is not None:
            return sequence_repeat(mv, v, w)
        if mw is not None:
            return sequence_repeat(mw, w, v)
        raise binop_type_error(v, w, "*")
    return result


def PyNumber_Power(v, w, z):
    return ternary_op(v, w, z, "nb_power", "** or pow()")


def _PyNumber_PowerNoMod(lhs, rhs):
    return PyNumber_Power(lhs, rhs, None)


# In-place operators fall back to the "normal" operation if the in-place
# method is missing.

def binary_iop1(v, w, iop_slot, op_slot):
    slot = getattr(Py_TYPE(v), iop_slot)
    if slot is not None:
        x = slot(v, w)
        if x is not NotImplemented:
            return x
    return binary_op1(v, w, op_slot)


def _inplace_func(iop_slot, op_slot, op_name):
    def func(v, w):
        result = binary_iop1(v, w, iop_slot, op_slot)
        if result is NotImplemented:
            raise binop_type_error(v, w, op_name)
        return result
    return func


PyNumber_InPlaceOr = _inplace_func("nb_inplace_or", "nb_or", "|=")
PyNumber_InPlaceXor = _inplace_func("nb_inplace_xor", "nb_xor", "^=")
PyNumber_InPlaceAnd = _inplace_func("nb_inplace_and", "nb_and", "&=")
PyNumber_InPlaceLshift = _inplace_func("nb_inplace_lshift", "nb_lshift", "<<=")
PyNumber_InPlaceRshift = _inplace_func("nb_inplace_rshift", "nb_rshift", ">>=")
PyNumber_InPlaceSubtract = _inplace_func("nb_inplace_subtract", "nb_subtract", "-=")
PyNumber_InPlaceMatrixMultiply = _inplace_func("nb_inplace_matrix_multiply",
                                               "nb_matrix_multiply", "@=")
PyNumber_InPlaceFloorDivide = _inplace_func("nb_inplace_floor_divide", "nb_floor_divide", "//=")
PyNumber_InPlaceTrueDivide = _inplace_func("nb_inplace_true_divide", "nb_true_divide", "/=")
PyNumber_InPlaceRemainder = _inplace_func("nb_inplace_remainder", "nb_remainder", "%=")


def PyNumber_InPlaceAdd(v, w):
    result = binary_iop1(v, w, "nb_inplace_add", "nb_add")
    if result is NotImplemented:
        m = Py_TYPE(v)
        func = m.sq_inplace_concat
        if func is None:
            func = m.sq_concat
        if func is not None:
            return func(v, w)
        raise binop_type_error(v, w, "+=")
    return result


def PyNumber_InPlaceMultiply(v, w):
    result = binary_iop1(v, w, "nb_inplace_multiply", "nb_multiply")
    if result is NotImplemented:
        mv = Py_TYPE(v)
        mw = Py_TYPE(w)
        f = mv.sq_inplace_repeat
        if f is None:
            f = mv.sq_repeat
        if f is not None:
            return sequence_repeat(f, v, w)
        if mw.sq_repeat is not None:
            # The right hand operand is not mutated: sq_inplace_repeat is not used.
            return sequence_repeat(mw.sq_repeat, w, v)
        raise binop_type_error(v, w, "*=")
    return result


def PyNumber_InPlacePower(v, w, z):
    slot = Py_TYPE(v).nb_inplace_power
    if slot is not None:
        x = slot(v, w, z)
        if x is not NotImplemented:
            return x
    return ternary_op(v, w, z, "nb_power", "**=")


def _PyNumber_InPlacePowerNoMod(lhs, rhs):
    return PyNumber_InPlacePower(lhs, rhs, None)


def _unary_func(slot, descr):
    def func(o):
        f = getattr(Py_TYPE(o), slot)
        if f is not None:
            return f(o)
        raise TypeError(f"bad operand type for {descr}: '{Py_TYPE(o).tp_name}'")
    return func


PyNumber_Negative = _unary_func("nb_negative", "unary -")
PyNumber_Positive = _unary_func("nb_positive", "unary +")
PyNumber_Invert = _unary_func("nb_invert", "unary ~")


# --- sequences and mappings -----------------------------------------------------

def PyObject_Size(o):
    tp = Py_TYPE(o)
    f = tp.sq_length
    if f is not None:
        return f(o)
    f = tp.mp_length
    if f is not None:
        return f(o)
    raise TypeError(f"object of type '{tp.tp_name}' has no len()")


def PyObject_GetItem(o, key):
    f = Py_TYPE(o).mp_subscript
    if f is not None:
        return f(o, key)
    if PyType_Check(o):
        # Special case type[int], but disallow other types so str[int] fails
        if o is type:
            return _GenericAlias(o, key)
        meth = PyObject_GetOptionalAttr(o, "__class_getitem__")
        if meth is not NULL and meth is not None:
            return _call.PyObject_CallOneArg(meth, key)
        raise TypeError(f"type '{PyType_View(o).tp_name}' is not subscriptable")
    raise _type_error("'%.200s' object is not subscriptable", o)


def PyObject_SetItem(o, key, value) -> None:
    f = Py_TYPE(o).mp_ass_subscript
    if f is not None:
        f(o, key, value)
        return
    raise _type_error("'%.200s' object does not support item assignment", o)


def _has_tp_as_sequence(view) -> bool:
    """Whether `tp_as_sequence` is non-NULL: heap types always have one."""
    if view.tp_flags & Py_TPFLAGS_HEAPTYPE:
        return True
    return (view.sq_length is not None or view.sq_item is not None
            or view.sq_contains is not None or view.sq_concat is not None
            or view.sq_repeat is not None)


def PyObject_DelItem(o, key) -> None:
    view = Py_TYPE(o)
    f = view.mp_ass_subscript
    if f is not None:
        f(o, key, NULL)
        return
    if _has_tp_as_sequence(view) and _PyIndex_Check(key):
        # PySequence_DelItem: there is no sq_ass_item without mp_ass_subscript.
        raise _type_error("'%.200s' object doesn't support item deletion", o)
    raise _type_error("'%.200s' object does not support item deletion", o)


def PySequence_Check(s) -> bool:
    if PyType_IsSubtype(Py_TYPE(s), PyType_View(dict)):
        return False
    return Py_TYPE(s).sq_item is not None


def PySequence_Contains(seq, ob) -> bool:
    f = Py_TYPE(seq).sq_contains
    if f is not None:
        return f(seq, ob)
    return _PySequence_IterSearch(seq, ob, PY_ITERSEARCH_CONTAINS)


def _PySequence_IterSearch(seq, obj, operation):
    err = None
    it = NULL
    try:
        it = PyObject_GetIter(seq)
    except TypeError as e:
        err = e
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        raise _type_error("argument of type '%.200s' is not a container or iterable", seq)
    n = 0
    while True:
        item = PyIter_Next(it)
        if item is NULL:
            break
        if PyObject_RichCompareBool(item, obj, Py_EQ):
            if operation == PY_ITERSEARCH_COUNT:
                n += 1
            elif operation == PY_ITERSEARCH_CONTAINS:
                return True
            else:
                return n
        elif operation == PY_ITERSEARCH_INDEX:
            n += 1
    if operation == PY_ITERSEARCH_CONTAINS:
        return False
    if operation == PY_ITERSEARCH_COUNT:
        return n
    raise ValueError("sequence.index(x): x not in sequence")


def PySequence_Tuple(v):
    it = PyObject_GetIter(v)
    items = []
    while True:
        item = PyIter_Next(it)
        if item is NULL:
            return tuple(items)
        items.append(item)


# --- iterators ------------------------------------------------------------------

def PyIter_Check(obj) -> bool:
    f = Py_TYPE(obj).tp_iternext
    return f is not None and f is not _PyObject_NextNotImplemented


def PyObject_GetIter(o):
    t = Py_TYPE(o)
    f = t.tp_iter
    if f is None:
        if PySequence_Check(o):
            return PySeqIter_New(o)
        raise _type_error("'%.200s' object is not iterable", o)
    res = f(o)
    if not PyIter_Check(res):
        raise TypeError(f"{_type_fullname(type(o))}.__iter__() must return an iterator, "
                        f"not {_type_fullname(type(res))}")
    return res


def PyIter_Next(iterator):
    """The next item, or NULL when the iterator is exhausted."""
    f = Py_TYPE(iterator).tp_iternext
    stop = None
    try:
        return f(iterator)
    except StopIteration as e:
        stop = e
    _PyErr_Clear(_PyThreadState_GET())
    return NULL


PYGEN_RETURN = 0
PYGEN_NEXT = 1


def PyIter_Send(iterator, arg):
    """-> (PYGEN_NEXT, yielded) or (PYGEN_RETURN, return value); errors raise."""
    am_send = Py_TYPE(iterator).am_send
    if am_send is not None:
        return am_send(iterator, arg)
    stop = None
    result = NULL
    try:
        if arg is None and PyIter_Check(iterator):
            result = Py_TYPE(iterator).tp_iternext(iterator)
        else:
            result = _call.PyObject_CallOneArg(PyObject_GetAttr(iterator, "send"), arg)
    except StopIteration as e:
        stop = e
    if stop is not None:
        # _PyGen_FetchStopIterationValue
        _PyErr_Clear(_PyThreadState_GET())
        return PYGEN_RETURN, stop.value
    return PYGEN_NEXT, result


class _SeqIter:
    """PySeqIter_Type: iteration over an object with only `__getitem__`."""
    __slots__ = ("it_index", "it_seq")

    def __init__(self, seq):
        self.it_index = 0
        self.it_seq = seq

    def __iter__(self):
        return self

    def __next__(self):
        return seqiter_next(self)


def PySeqIter_New(seq):
    return _SeqIter(seq)


def seqiter_next(it):
    seq = it.it_seq
    if seq is None:
        raise StopIteration
    err = None
    result = NULL
    try:
        result = Py_TYPE(seq).sq_item(seq, it.it_index)
    except (IndexError, StopIteration) as e:
        err = e
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        it.it_seq = None
        raise StopIteration
    it.it_index += 1
    return result


register_static_slots(_SeqIter, tp_iter=lambda it: it, tp_iternext=seqiter_next)
_SeqIter.__name__ = _SeqIter.__qualname__ = "iterator"
