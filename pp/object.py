"""Generic object operations, modeled on Objects/object.c.

Attribute access (`PyObject_GetAttr` ... `_PyObject_GetMethod`), rich
comparison (`do_richcompare`) and truth (`PyObject_IsTrue`), all dispatching
through the type slots of `pp.typeobject`.

Where CPython returns NULL with an exception set, these raise; "no result" for
the optional/suppressing variants is the `NULL` sentinel.
"""

from pp.errors import _PyErr_Clear, _PyThreadState_GET
from pp.frame import NULL
from pp.typeobject import (Py_TPFLAGS_METHOD_DESCRIPTOR, Py_TYPE, PyObject_TypeCheck,
                           PyType_Check, PyType_IsSubtype, PyType_View, _PyObject_GetDictPtr,
                           _PyType_Lookup, DICT_NONE, DICT_SPECIAL, DICT_STD,
                           _tp_dict, _type_dictget, _views_get, _object_getattribute,
                           _new_view, _object_setattr, _object_delattr,
                           register_wrapper_slot, update_slot)

Py_LT, Py_LE, Py_EQ, Py_NE, Py_GT, Py_GE = range(6)
_Py_SwappedOp = (Py_GT, Py_GE, Py_EQ, Py_NE, Py_LT, Py_LE)
_opstrings = ("<", "<=", "==", "!=", ">", ">=")

_dict_get = dict.get
_dict_setitem = dict.__setitem__
_dict_pop = dict.pop
_STR_VIEW = None


def _type_fullname(tp) -> str:
    """The `%T` format: the fully qualified type name."""
    mod = tp.__module__
    if mod in ("builtins", "__main__") or not isinstance(mod, str):
        return tp.__qualname__
    return f"{mod}.{tp.__qualname__}"


def PyUnicode_Check(o) -> bool:
    global _STR_VIEW
    if type(o) is str:
        return True
    if _STR_VIEW is None:
        _STR_VIEW = PyType_View(str)
    return PyType_IsSubtype(Py_TYPE(o), _STR_VIEW)


def _name_error(name):
    return TypeError(f"attribute name must be string, not '{Py_TYPE(name).tp_name}'")


# --- attributes ----------------------------------------------------------------

def _PyObject_SetAttributeErrorContext(exc, v, name) -> None:
    """Augment an AttributeError with the name and object (for suggestions)."""
    if exc.name is not None or exc.obj is not None:
        return
    exc.name = name
    exc.obj = v


def PyObject_GetAttr(v, name):
    tp = Py_TYPE(v)
    if not PyUnicode_Check(name):
        raise _name_error(name)
    getattro = tp.tp_getattro
    if getattro is None:
        raise AttributeError(f"'{tp.tp_name}' object has no attribute '{name}'",
                             name=name, obj=v)
    try:
        return getattro(v, name)
    except AttributeError as e:
        _PyObject_SetAttributeErrorContext(e, v, name)
        raise


def PyObject_GetOptionalAttr(v, name):
    """Like PyObject_GetAttr, but returns NULL when the attribute is missing."""
    tp = Py_TYPE(v)
    if not PyUnicode_Check(name):
        raise _name_error(name)
    getattro = tp.tp_getattro
    if getattro is PyObject_GenericGetAttr:
        return _PyObject_GenericGetAttrWithDict(v, name, NULL, True)
    if getattro is None:
        return NULL
    err = None
    result = NULL
    try:
        result = getattro(v, name)
    except AttributeError as e:
        err = True    # not the exception itself: it would form a cycle with its traceback
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        return NULL
    return result


def PyObject_SetAttr(v, name, value) -> None:
    """Set (or, with value NULL, delete) an attribute."""
    tp = Py_TYPE(v)
    if not PyUnicode_Check(name):
        raise _name_error(name)
    setattro = tp.tp_setattro
    if setattro is not None:
        setattro(v, name, value)
        if PyType_Check(v):
            update_slot(v, name)
        return
    if tp.tp_getattro is None:
        raise TypeError(f"'{tp.tp_name}' object has no attributes "
                        f"({'del' if value is NULL else 'assign to'} .{name})")
    raise TypeError(f"'{tp.tp_name}' object has only read-only attributes "
                    f"({'del' if value is NULL else 'assign to'} .{name})")


def _PyObject_GetDict(obj, tp):
    """The instance dict (`_PyObject_GetDictPtr`), or None if the type has none."""
    return _PyObject_GetDictPtr(obj, tp)


def _PyObject_GenericGetAttrWithDict(obj, name, dict_, suppress):
    """When `suppress` is true an AttributeError is suppressed and NULL returned."""
    tp = Py_TYPE(obj)
    if not PyUnicode_Check(name):
        raise _name_error(name)

    descr = _PyType_Lookup(type(obj), name)
    f = None
    if descr is not NULL:
        descr_type = Py_TYPE(descr)
        f = descr_type.tp_descr_get
        if f is not None and descr_type.tp_descr_set is not None:
            return _call_descr_get(f, descr, obj, tp, suppress)
    if dict_ is NULL:
        dict_ = _PyObject_GetDict(obj, tp)
    if dict_ is not None:
        res = _dict_get(dict_, name, NULL)
        if res is not NULL:
            return res
    if f is not None:
        return _call_descr_get(f, descr, obj, tp, suppress)
    if descr is not NULL:
        return descr
    if suppress:
        return NULL
    raise AttributeError(f"'{tp.tp_name}' object has no attribute '{name}'",
                         name=name, obj=obj)


def _call_descr_get(f, descr, obj, tp, suppress):
    if not suppress:
        return f(descr, obj, type(obj))
    err = None
    res = NULL
    try:
        res = f(descr, obj, type(obj))
    except AttributeError as e:
        err = True    # not the exception itself: it would form a cycle with its traceback
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        return NULL
    return res


def PyObject_GenericGetAttr(obj, name):
    # _PyObject_GenericGetAttrWithDict(obj, name, NULL, 0), flattened: this is the
    # one function every attribute load of an ordinary object goes through.
    cls = type(obj)
    tp = _views_get(id(cls)) or Py_TYPE(obj)
    if type(name) is not str and not PyUnicode_Check(name):
        raise _name_error(name)
    return _PyObject_GenericGetAttrDescr(obj, name, tp, _PyType_Lookup(cls, name))


def _PyObject_GenericGetAttrDescr(obj, name, tp, descr):
    """The rest of PyObject_GenericGetAttr, given the type's slot table `tp` and
    what _PyType_Lookup found (`name` is a str)."""
    f = None
    if descr is not NULL:
        descr_type = _views_get(id(type(descr))) or Py_TYPE(descr)
        f = descr_type.tp_descr_get
        if f is not None and descr_type.tp_descr_set is not None:
            return f(descr, obj, type(obj))
    kind = tp.tp_dictkind                        # _PyObject_GetDictPtr
    if kind == DICT_STD:
        dict_ = _object_getattribute(obj, "__dict__")
    elif kind == DICT_NONE:
        dict_ = None
    else:
        dict_ = _PyObject_GetDictPtr(obj, tp)
    if dict_ is not None:
        res = _dict_get(dict_, name, NULL)
        if res is not NULL:
            return res
    if f is not None:
        return f(descr, obj, type(obj))
    if descr is not NULL:
        return descr
    raise AttributeError(f"'{tp.tp_name}' object has no attribute '{name}'",
                         name=name, obj=obj)


def _PyObject_GenericSetAttrWithDict(obj, name, value, dict_):
    tp = Py_TYPE(obj)
    if not PyUnicode_Check(name):
        raise _name_error(name)
    descr = _PyType_Lookup(type(obj), name)
    if descr is not NULL:
        f = Py_TYPE(descr).tp_descr_set
        if f is not None:
            f(descr, obj, value)
            return
    if dict_ is NULL and tp.tp_dictkind == DICT_SPECIAL:
        # The dict is at tp_dictoffset although `__dict__` means something else to
        # the class, and it may not exist yet: let the host create and use it.
        if value is NULL:
            _object_delattr(obj, name)
        else:
            _object_setattr(obj, name, value)
        return
    if dict_ is NULL:
        dict_ = _PyObject_GetDict(obj, tp)
        if dict_ is None:
            if descr is NULL:
                if tp.tp_setattro is PyObject_GenericSetAttr:
                    raise AttributeError(
                        f"'{tp.tp_name}' object has no attribute '{name}' and no "
                        "__dict__ for setting new attributes", name=name, obj=obj)
                raise AttributeError(f"'{tp.tp_name}' object has no attribute '{name}'",
                                     name=name, obj=obj)
            raise AttributeError(f"'{tp.tp_name}' object attribute '{name}' is read-only",
                                 name=name, obj=obj)
    if value is NULL:
        if _dict_pop(dict_, name, NULL) is NULL:
            raise AttributeError(f"'{tp.tp_name}' object has no attribute '{name}'",
                                 name=name, obj=obj)
    else:
        _dict_setitem(dict_, name, value)


def PyObject_GenericSetAttr(obj, name, value):
    return _PyObject_GenericSetAttrWithDict(obj, name, value, NULL)


def _PyObject_GetMethod(obj, name):
    """-> (value, meth_found). With meth_found true, `value` is an unbound method
    to call with `obj` as the first argument."""
    cls = type(obj)
    tp = _views_get(id(cls)) or Py_TYPE(obj)
    if tp.tp_getattro is not PyObject_GenericGetAttr or type(name) is not str:
        return PyObject_GetAttr(obj, name), False

    descr = _PyType_Lookup(cls, name)
    f = None
    meth_found = False
    if descr is not NULL:
        descr_type = _views_get(id(type(descr))) or Py_TYPE(descr)
        if descr_type.tp_flags & Py_TPFLAGS_METHOD_DESCRIPTOR:
            meth_found = True
        else:
            f = descr_type.tp_descr_get
            if f is not None and descr_type.tp_descr_set is not None:
                return f(descr, obj, type(obj)), False
    kind = tp.tp_dictkind                        # _PyObject_GetDictPtr
    if kind == DICT_STD:
        dict_ = _object_getattribute(obj, "__dict__")
    elif kind == DICT_NONE:
        dict_ = None
    else:
        dict_ = _PyObject_GetDictPtr(obj, tp)
    if dict_ is not None:
        attr = _dict_get(dict_, name, NULL)
        if attr is not NULL:
            return attr, False
    if meth_found:
        return descr, True
    if f is not None:
        return f(descr, obj, type(obj)), False
    if descr is not NULL:
        return descr, False
    raise AttributeError(f"'{tp.tp_name}' object has no attribute '{name}'",
                         name=name, obj=obj)


def _PyObject_LookupSpecialMethod(name, owner):
    """LOAD_SPECIAL's lookup -> (method, self_or_NULL), or None if the type has no
    such special method."""
    method = _PyType_Lookup(type(owner), name)
    if method is NULL:
        return None
    mt = Py_TYPE(method)
    if mt.tp_flags & Py_TPFLAGS_METHOD_DESCRIPTOR:
        return method, owner        # avoid a temporary bound method
    f = mt.tp_descr_get
    if f is not None:
        return f(method, owner, type(owner)), NULL
    return method, NULL


register_wrapper_slot("tp_getattro", object.__dict__["__getattribute__"], PyObject_GenericGetAttr)
register_wrapper_slot("tp_setattro", object.__dict__["__setattr__"], PyObject_GenericSetAttr)
register_wrapper_slot("tp_setattro", object.__dict__["__delattr__"], PyObject_GenericSetAttr)


# --- rich comparison -----------------------------------------------------------

def do_richcompare(v, w, op):
    v_view = Py_TYPE(v)
    w_view = Py_TYPE(w)
    checked_reverse_op = False
    if v_view is not w_view and PyType_IsSubtype(w_view, v_view) \
            and w_view.tp_richcompare is not None:
        checked_reverse_op = True
        res = w_view.tp_richcompare(w, v, _Py_SwappedOp[op])
        if res is not NotImplemented:
            return res
    f = v_view.tp_richcompare
    if f is not None:
        res = f(v, w, op)
        if res is not NotImplemented:
            return res
    if not checked_reverse_op:
        f = w_view.tp_richcompare
        if f is not None:
            res = f(w, v, _Py_SwappedOp[op])
            if res is not NotImplemented:
                return res
    # If neither object implements it, provide a sensible default for == and !=,
    # but raise an exception for ordering.
    if op == Py_EQ:
        return v is w
    if op == Py_NE:
        return v is not w
    raise TypeError(f"'{_opstrings[op]}' not supported between instances of "
                    f"'{v_view.tp_name}' and '{w_view.tp_name}'")


def PyObject_RichCompare(v, w, op):
    return do_richcompare(v, w, op)


def PyObject_RichCompareBool(v, w, op) -> bool:
    # Quick result when objects are the same: identity implies equality.
    if v is w:
        if op == Py_EQ:
            return True
        if op == Py_NE:
            return False
    res = do_richcompare(v, w, op)
    if res is True or res is False:
        return res
    return PyObject_IsTrue(res)


# --- truth ---------------------------------------------------------------------

def PyObject_IsTrue(v) -> bool:
    if v is True:
        return True
    if v is False or v is None:
        return False
    tp = Py_TYPE(v)
    f = tp.nb_bool
    if f is not None:
        return f(v)
    f = tp.mp_length
    if f is not None:
        return _is_positive(f(v))
    f = tp.sq_length
    if f is not None:
        return _is_positive(f(v))
    return True


def _is_positive(res) -> bool:
    return int.__gt__(res, 0)


# --- isinstance ----------------------------------------------------------------

def _PyObject_LookupSpecial(self, name):
    res = _PyType_Lookup(type(self), name)
    if res is not NULL:
        f = Py_TYPE(res).tp_descr_get
        if f is not None:
            res = f(res, self, type(self))
    return res


def object_isinstance(inst, cls) -> bool:
    if PyType_Check(cls):
        if PyObject_TypeCheck(inst, cls):
            return True
        icls = PyObject_GetOptionalAttr(inst, "__class__")
        if icls is not NULL and icls is not type(inst) and PyType_Check(icls):
            return PyType_IsSubtype(PyType_View(icls), PyType_View(cls))
        return False
    raise TypeError("isinstance() arg 2 must be a type, a tuple of types, or a union")


def PyObject_IsInstance(inst, cls) -> bool:
    # Quick test for an exact match
    if type(inst) is cls:
        return True
    # We know what type's __instancecheck__ does.
    if type(cls) is type:
        return object_isinstance(inst, cls)
    if type(cls) is tuple:
        for item in cls:
            if PyObject_IsInstance(inst, item):
                return True
        return False
    checker = _PyObject_LookupSpecial(cls, "__instancecheck__")
    if checker is not NULL:
        from pp import call
        return PyObject_IsTrue(call.PyObject_CallOneArg(checker, inst))
    return object_isinstance(inst, cls)
