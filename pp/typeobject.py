"""Type slots, modeled on Objects/typeobject.c.

`Py_TYPE(o)` returns the `PyTypeObject` view of `type(o)`: a table of slot
fields, filled like `fixup_slot_dispatchers` / `update_one_slot` from the
type's MRO. Slot growth rule: a field exists only if some pp code reads it.

* A dunder defined in Python (a VM `Function`, a host function, ...) gets the
  matching generic `slot_*` function (`slot_tp_getattr_hook`, `slot_nb_add`
  via the SLOT1BINFULL logic, `slot_tp_richcompare`, ...), which looks the
  dunder up at call time.
* A dunder that is a host C wrapper_descriptor gets a "C slot": an adapter,
  cached per wrapper, that calls the wrapper directly (the host type's own
  implementation). Slot values are compared by identity, as C function
  pointers are (`binary_op1`'s `slotw == slotv`, SLOT1BINFULL's
  `slot == TESTFUNC`).

Calling convention: C returns NULL with an exception set; here the slot
functions raise. "Missing" is the `NULL` sentinel.
"""

import types

from pp.errors import _PyErr_Clear, _PyThreadState_GET
from pp.frame import NULL

# These modules depend on this one; bound at the bottom.
_call = None
_object = None

Py_TPFLAGS_HEAPTYPE = 1 << 9
Py_TPFLAGS_METHOD_DESCRIPTOR = 1 << 17

# Field accessors that user subclasses of `type` cannot shadow.
_tp_dict = type.__dict__["__dict__"].__get__
_tp_mro = type.__dict__["__mro__"].__get__
_tp_flags = type.__dict__["__flags__"].__get__
_tp_name_attr = type.__dict__["__name__"].__get__
_tp_module = type.__dict__["__module__"].__get__
_tp_subclasses = type.__subclasses__
_type_dictget = types.MappingProxyType.get

_WrapperDescr = types.WrapperDescriptorType
_GetSetDescr = types.GetSetDescriptorType
_MemberDescr = types.MemberDescriptorType

# --- slot table ---------------------------------------------------------------

# name, dunder, generic function (filled below), kind ("sq"/"nb" for dunders that
# serve both protocols: only a C wrapper of that protocol may fill the slot).
_SLOTDEF_SPECS = (
    ("tp_getattro", "__getattribute__", "slot_tp_getattr_hook", None),
    ("tp_getattro", "__getattr__", "slot_tp_getattr_hook", None),
    ("tp_setattro", "__setattr__", "slot_tp_setattro", None),
    ("tp_setattro", "__delattr__", "slot_tp_setattro", None),
    ("tp_call", "__call__", "slot_tp_call", None),
    ("tp_richcompare", "__lt__", "slot_tp_richcompare", None),
    ("tp_richcompare", "__le__", "slot_tp_richcompare", None),
    ("tp_richcompare", "__eq__", "slot_tp_richcompare", None),
    ("tp_richcompare", "__ne__", "slot_tp_richcompare", None),
    ("tp_richcompare", "__gt__", "slot_tp_richcompare", None),
    ("tp_richcompare", "__ge__", "slot_tp_richcompare", None),
    ("tp_iter", "__iter__", "slot_tp_iter", None),
    ("tp_iternext", "__next__", "slot_tp_iternext", None),
    ("tp_descr_get", "__get__", "slot_tp_descr_get", None),
    ("tp_descr_set", "__set__", "slot_tp_descr_set", None),
    ("tp_descr_set", "__delete__", "slot_tp_descr_set", None),
    ("sq_length", "__len__", "slot_sq_length", None),
    ("mp_length", "__len__", "slot_sq_length", None),
    ("sq_concat", "__add__", None, "sq"),
    ("sq_repeat", "__mul__", None, "sq"),
    ("sq_repeat", "__rmul__", None, "sq"),
    ("sq_item", "__getitem__", "slot_sq_item", None),
    ("sq_contains", "__contains__", "slot_sq_contains", None),
    ("sq_inplace_concat", "__iadd__", None, "sq"),
    ("sq_inplace_repeat", "__imul__", None, "sq"),
    ("mp_subscript", "__getitem__", "slot_mp_subscript", None),
    ("mp_ass_subscript", "__setitem__", "slot_mp_ass_subscript", None),
    ("mp_ass_subscript", "__delitem__", "slot_mp_ass_subscript", None),
    ("nb_add", "__add__", "slot_nb_add", "nb"),
    ("nb_add", "__radd__", "slot_nb_add", "nb"),
    ("nb_subtract", "__sub__", "slot_nb_subtract", None),
    ("nb_subtract", "__rsub__", "slot_nb_subtract", None),
    ("nb_multiply", "__mul__", "slot_nb_multiply", "nb"),
    ("nb_multiply", "__rmul__", "slot_nb_multiply", "nb"),
    ("nb_remainder", "__mod__", "slot_nb_remainder", None),
    ("nb_remainder", "__rmod__", "slot_nb_remainder", None),
    ("nb_power", "__pow__", "slot_nb_power", None),
    ("nb_power", "__rpow__", "slot_nb_power", None),
    ("nb_negative", "__neg__", "slot_nb_negative", None),
    ("nb_positive", "__pos__", "slot_nb_positive", None),
    ("nb_bool", "__bool__", "slot_nb_bool", None),
    ("nb_invert", "__invert__", "slot_nb_invert", None),
    ("nb_lshift", "__lshift__", "slot_nb_lshift", None),
    ("nb_lshift", "__rlshift__", "slot_nb_lshift", None),
    ("nb_rshift", "__rshift__", "slot_nb_rshift", None),
    ("nb_rshift", "__rrshift__", "slot_nb_rshift", None),
    ("nb_and", "__and__", "slot_nb_and", None),
    ("nb_and", "__rand__", "slot_nb_and", None),
    ("nb_xor", "__xor__", "slot_nb_xor", None),
    ("nb_xor", "__rxor__", "slot_nb_xor", None),
    ("nb_or", "__or__", "slot_nb_or", None),
    ("nb_or", "__ror__", "slot_nb_or", None),
    ("nb_index", "__index__", "slot_nb_index", None),
    ("nb_inplace_add", "__iadd__", "slot_nb_inplace_add", "nb"),
    ("nb_inplace_subtract", "__isub__", "slot_nb_inplace_subtract", None),
    ("nb_inplace_multiply", "__imul__", "slot_nb_inplace_multiply", "nb"),
    ("nb_inplace_remainder", "__imod__", "slot_nb_inplace_remainder", None),
    ("nb_inplace_power", "__ipow__", "slot_nb_inplace_power", None),
    ("nb_inplace_lshift", "__ilshift__", "slot_nb_inplace_lshift", None),
    ("nb_inplace_rshift", "__irshift__", "slot_nb_inplace_rshift", None),
    ("nb_inplace_and", "__iand__", "slot_nb_inplace_and", None),
    ("nb_inplace_xor", "__ixor__", "slot_nb_inplace_xor", None),
    ("nb_inplace_or", "__ior__", "slot_nb_inplace_or", None),
    ("nb_floor_divide", "__floordiv__", "slot_nb_floor_divide", None),
    ("nb_floor_divide", "__rfloordiv__", "slot_nb_floor_divide", None),
    ("nb_true_divide", "__truediv__", "slot_nb_true_divide", None),
    ("nb_true_divide", "__rtruediv__", "slot_nb_true_divide", None),
    ("nb_inplace_floor_divide", "__ifloordiv__", "slot_nb_inplace_floor_divide", None),
    ("nb_inplace_true_divide", "__itruediv__", "slot_nb_inplace_true_divide", None),
    ("nb_matrix_multiply", "__matmul__", "slot_nb_matrix_multiply", None),
    ("nb_matrix_multiply", "__rmatmul__", "slot_nb_matrix_multiply", None),
    ("nb_inplace_matrix_multiply", "__imatmul__", "slot_nb_inplace_matrix_multiply", None),
)

SLOT_FIELDS = tuple(dict.fromkeys(spec[0] for spec in _SLOTDEF_SPECS))

# Slots with no dunder behind them: only types pp implements natively define them.
STATIC_FIELDS = ("am_send",)

# Every dunder some slot is made of (`update_slot` only reacts to these).
SLOT_DUNDERS = frozenset(spec[1] for spec in _SLOTDEF_SPECS) | {"__bases__"}


class PyTypeObject:
    """The slot table of one host type."""
    __slots__ = ("type", "tp_name", "tp_flags", "tp_mro", "tp_mro_dicts",
                 "tp_dictdescr") + SLOT_FIELDS + STATIC_FIELDS

    def __init__(self, tp):
        self.type = tp
        mro = _tp_mro(tp)
        self.tp_mro = mro
        self.tp_mro_dicts = tuple([_tp_dict(base) for base in mro])
        self.tp_flags = _tp_flags(tp) | _EXTRA_FLAGS.get(tp, 0)
        self.tp_name = _compute_tp_name(tp, self.tp_flags)
        self.tp_dictdescr = NULL
        for field in SLOT_FIELDS + STATIC_FIELDS:
            setattr(self, field, None)

    def __repr__(self):
        return f"<PyTypeObject {self.tp_name}>"


def _compute_tp_name(tp, flags) -> str:
    name = _tp_name_attr(tp)
    if flags & Py_TPFLAGS_HEAPTYPE:
        return name
    module = _tp_module(tp)
    if type(module) is not str or module == "builtins":
        return name
    return f"{module}.{name}"


# --- views --------------------------------------------------------------------

_views: dict = {}              # id(host type) -> PyTypeObject (the view keeps the type alive)
_EXTRA_FLAGS: dict = {}        # host type -> extra tp_flags (types pp defines in Python)
_STATIC_SLOTS: dict = {}       # host type -> {field: function}: "C" slots implemented by pp
_C_WRAPPER_SLOTS: dict = {}    # (field, id(wrapper_descriptor)) -> function implemented by pp


def register_static_slots(tp, flags=0, **slots) -> None:
    """Declare slots of a type pp implements itself (the C struct's initializers)."""
    _EXTRA_FLAGS[tp] = flags
    _STATIC_SLOTS[tp] = slots
    _views.pop(id(tp), None)


def register_wrapper_slot(field, wrapper, function) -> None:
    """A host wrapper_descriptor whose slot function pp implements itself."""
    _C_WRAPPER_SLOTS[(field, id(wrapper))] = (wrapper, function)


def Py_TYPE(o) -> PyTypeObject:
    tp = type(o)
    view = _views.get(id(tp))
    if view is None:
        view = _new_view(tp)
    return view


def PyType_View(tp) -> PyTypeObject:
    """The PyTypeObject of a host type object."""
    view = _views.get(id(tp))
    if view is None:
        view = _new_view(tp)
    return view


def _new_view(tp) -> PyTypeObject:
    view = PyTypeObject(tp)
    _views[id(tp)] = view
    fixup_slot_dispatchers(view)
    view.tp_dictdescr = _find_dict_descriptor(view)
    return view


def _find_dict_descriptor(view):
    descr = _PyType_Lookup(view, "__dict__")
    if type(descr) is _GetSetDescr or type(descr) is _MemberDescr:
        return descr
    return NULL


def PyType_Modified(tp) -> None:
    """Drop the slot tables of `tp` and its subclasses (rebuilt lazily from the
    MRO). Called after attribute assignment on a type (update_slot)."""
    _views.pop(id(tp), None)
    for sub in _tp_subclasses(tp):
        PyType_Modified(sub)


def update_slot(tp, name) -> None:
    if name in SLOT_DUNDERS:
        PyType_Modified(tp)


def PyType_Check(o) -> bool:
    return PyType_IsSubtype(Py_TYPE(o), _TYPE_VIEW())


def _TYPE_VIEW():
    return PyType_View(type)


def PyType_IsSubtype(a, b) -> bool:
    """a, b are PyTypeObject views."""
    target = b.type
    for base in a.tp_mro:
        if base is target:
            return True
    return False


def _PyType_Lookup(tp, name):
    """MRO lookup; `tp` is a PyTypeObject view. Returns NULL if absent."""
    for d in tp.tp_mro_dicts:
        res = _type_dictget(d, name, NULL)
        if res is not NULL:
            return res
    return NULL


def PyObject_TypeCheck(o, tp) -> bool:
    """tp is a host type."""
    cls = type(o)
    if cls is tp:
        return True
    for base in Py_TYPE(o).tp_mro:
        if base is tp:
            return True
    return False


# --- filling slots (update_one_slot / fixup_slot_dispatchers) -----------------

_SLOT_GROUPS: dict = {}


def _group_slotdefs():
    for field, dunder, function, kind in _SLOTDEF_SPECS:
        _SLOT_GROUPS.setdefault(field, []).append((dunder, function, kind))


_group_slotdefs()


def _wrapper_kind(descr, name) -> str:
    """Which protocol (`nb` or `sq`) a host wrapper_descriptor of a dunder shared by
    both belongs to. CPython knows it from `d_base`; the host does not say, so
    infer it from the owning type: sequence types (`__len__`, no `__radd__`)
    define `__add__`/`__mul__`/`__iadd__`/`__imul__` through sq_concat/sq_repeat."""
    owner_dict = _tp_dict(descr.__objclass__)
    if name == "__add__":
        return "nb" if "__radd__" in owner_dict else "sq"
    return "sq" if "__len__" in owner_dict else "nb"


def update_one_slot(tp, field) -> None:
    specific_found = {}
    owner = None
    generic = None
    use_generic = False
    have_specific = False
    missing_iternext = False
    for dunder, function, kind in _SLOT_GROUPS[field]:
        descr = _PyType_Lookup(tp, dunder)
        if descr is NULL:
            if field == "tp_iternext":
                missing_iternext = True
            continue
        if type(descr) is _WrapperDescr and descr.__name__ == dunder:
            if kind is not None and _wrapper_kind(descr, dunder) != kind:
                # The wrapper wraps the other protocol's slot (tptr != ptr).
                use_generic = True
                continue
            generic = _GENERIC.get(function)
            objclass = descr.__objclass__
            if (owner is None or owner is objclass) and _is_subtype_with_mro(tp, objclass):
                owner = objclass
                specific_found[dunder] = descr
                have_specific = True
            else:
                use_generic = True
        else:
            use_generic = True
            generic = _GENERIC.get(function)
    if have_specific and not use_generic:
        value = _c_slot(field, specific_found)
    elif missing_iternext and not use_generic and not have_specific:
        value = _PyObject_NextNotImplemented
    else:
        value = generic
    setattr(tp, field, value)


def _is_subtype_with_mro(tp, objclass) -> bool:
    for base in tp.tp_mro:
        if base is objclass:
            return True
    return False


def fixup_slot_dispatchers(tp) -> None:
    for field in SLOT_FIELDS:
        update_one_slot(tp, field)
    static = _STATIC_SLOTS.get(tp.type)
    if static:
        for field, function in static.items():
            setattr(tp, field, function)


def _PyObject_NextNotImplemented(self):
    raise TypeError(f"'{Py_TYPE(self).tp_name}' object is not an iterator")


# --- C slots: adapters over host wrapper_descriptors --------------------------

_adapter_cache: dict = {}


def _c_slot(field, found):
    key = (field, tuple([(name, id(d)) for name, d in found.items()]))
    hit = _adapter_cache.get(key)
    if hit is not None:
        return hit[0]
    fns = set()
    for d in found.values():
        known = _C_WRAPPER_SLOTS.get((field, id(d)))
        fns.add(known[1] if known is not None and known[0] is d else None)
    if len(fns) == 1 and None not in fns:
        fn = fns.pop()          # a slot function pp implements itself
    else:
        fn = _ADAPTERS[field](found)
    _adapter_cache[key] = (fn, tuple(found.values()))  # keep the wrappers (ids) alive
    return fn


def _unary_adapter(found):
    d = next(iter(found.values()))

    def adapter(o):
        return d(o)
    return adapter


def _binary_adapter(found):
    d = next(iter(found.values()))

    def adapter(o, x):
        return d(o, x)
    return adapter


def _ternary_adapter(found):
    d = next(iter(found.values()))

    def adapter(o, x, y):
        return d(o, x, y)
    return adapter


def _call_adapter(found):
    d = found["__call__"]

    def adapter(o, args, kwargs):
        if kwargs:
            return d(o, *args, **kwargs)
        return d(o, *args)
    return adapter


def _descr_get_adapter(found):
    d = found["__get__"]

    def adapter(self, obj, tp):
        return d(self, None if obj is NULL else obj, None if tp is NULL else tp)
    return adapter


def _setter_deleter_adapter(setname, delname):
    def build(found):
        s = found.get(setname)
        dl = found.get(delname)

        def adapter(o, key, value):
            if value is NULL:
                if dl is None:
                    raise AttributeError(delname)
                return dl(o, key)
            if s is None:
                raise AttributeError(setname)
            return s(o, key, value)
        return adapter
    return build


def _richcompare_adapter(found):
    table = tuple([found.get(name) for name in
                   ("__lt__", "__le__", "__eq__", "__ne__", "__gt__", "__ge__")])

    def adapter(o, w, op):
        d = table[op]
        if d is None:
            return NotImplemented
        return d(o, w)
    return adapter


def _nb_binary_adapter(fwd_name, rev_name):
    """A C binary slot handles both operand orders itself (`slotw(v, w)` is called
    with `v` not of the slot's type): forward when the left operand is the owner
    type, reflected when the right one is."""
    def build(found):
        fwd = found.get(fwd_name)
        rev = found.get(rev_name)
        fwd_cls = fwd.__objclass__ if fwd is not None else None
        rev_cls = rev.__objclass__ if rev is not None else None

        def adapter(a, b):
            if fwd is not None and PyObject_TypeCheck(a, fwd_cls):
                r = fwd(a, b)
                if r is not NotImplemented:
                    return r
            if rev is not None and PyObject_TypeCheck(b, rev_cls):
                return rev(b, a)
            return NotImplemented
        return adapter
    return build


def _nb_power_adapter(found):
    fwd = found.get("__pow__")
    rev = found.get("__rpow__")
    fwd_cls = fwd.__objclass__ if fwd is not None else None
    rev_cls = rev.__objclass__ if rev is not None else None

    def adapter(a, b, z):
        if fwd is not None and PyObject_TypeCheck(a, fwd_cls):
            r = fwd(a, b, z)
            if r is not NotImplemented:
                return r
        if rev is not None and PyObject_TypeCheck(b, rev_cls):
            return rev(b, a, z)
        return NotImplemented
    return adapter


_ADAPTERS = {
    "tp_getattro": _binary_adapter,
    "tp_setattro": _setter_deleter_adapter("__setattr__", "__delattr__"),
    "tp_call": _call_adapter,
    "tp_richcompare": _richcompare_adapter,
    "tp_iter": _unary_adapter,
    "tp_iternext": _unary_adapter,
    "tp_descr_get": _descr_get_adapter,
    "tp_descr_set": _setter_deleter_adapter("__set__", "__delete__"),
    "sq_length": _unary_adapter,
    "mp_length": _unary_adapter,
    "sq_concat": _binary_adapter,
    "sq_repeat": _binary_adapter,
    "sq_item": _binary_adapter,
    "sq_contains": _binary_adapter,
    "sq_inplace_concat": _binary_adapter,
    "sq_inplace_repeat": _binary_adapter,
    "mp_subscript": _binary_adapter,
    "mp_ass_subscript": _setter_deleter_adapter("__setitem__", "__delitem__"),
    "nb_add": _nb_binary_adapter("__add__", "__radd__"),
    "nb_subtract": _nb_binary_adapter("__sub__", "__rsub__"),
    "nb_multiply": _nb_binary_adapter("__mul__", "__rmul__"),
    "nb_remainder": _nb_binary_adapter("__mod__", "__rmod__"),
    "nb_power": _nb_power_adapter,
    "nb_negative": _unary_adapter,
    "nb_positive": _unary_adapter,
    "nb_bool": _unary_adapter,
    "nb_invert": _unary_adapter,
    "nb_lshift": _nb_binary_adapter("__lshift__", "__rlshift__"),
    "nb_rshift": _nb_binary_adapter("__rshift__", "__rrshift__"),
    "nb_and": _nb_binary_adapter("__and__", "__rand__"),
    "nb_xor": _nb_binary_adapter("__xor__", "__rxor__"),
    "nb_or": _nb_binary_adapter("__or__", "__ror__"),
    "nb_index": _unary_adapter,
    "nb_inplace_add": _binary_adapter,
    "nb_inplace_subtract": _binary_adapter,
    "nb_inplace_multiply": _binary_adapter,
    "nb_inplace_remainder": _binary_adapter,
    "nb_inplace_power": _ternary_adapter,
    "nb_inplace_lshift": _binary_adapter,
    "nb_inplace_rshift": _binary_adapter,
    "nb_inplace_and": _binary_adapter,
    "nb_inplace_xor": _binary_adapter,
    "nb_inplace_or": _binary_adapter,
    "nb_floor_divide": _nb_binary_adapter("__floordiv__", "__rfloordiv__"),
    "nb_true_divide": _nb_binary_adapter("__truediv__", "__rtruediv__"),
    "nb_inplace_floor_divide": _binary_adapter,
    "nb_inplace_true_divide": _binary_adapter,
    "nb_matrix_multiply": _nb_binary_adapter("__matmul__", "__rmatmul__"),
    "nb_inplace_matrix_multiply": _binary_adapter,
}
assert set(_ADAPTERS) == set(SLOT_FIELDS), set(SLOT_FIELDS) ^ set(_ADAPTERS)


# --- method lookup helpers (lookup_maybe_method & co) --------------------------

def _suppressing_attribute_error(fn, *args):
    """fn(*args), with an AttributeError turned into NULL (PyErr_Clear)."""
    err = None
    res = NULL
    try:
        res = fn(*args)
    except AttributeError as e:
        err = e
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        return NULL
    return res


def lookup_maybe_method(self, name):
    """-> (method, unbound); method is NULL if the lookup failed."""
    tp = Py_TYPE(self)
    value = _PyType_Lookup(tp, name)
    if value is NULL:
        return NULL, False
    vt = Py_TYPE(value)
    if vt.tp_flags & Py_TPFLAGS_METHOD_DESCRIPTOR:
        return value, True          # avoid a temporary bound method
    f = vt.tp_descr_get
    if f is not None:
        return _suppressing_attribute_error(f, value, self, tp.type), False
    return value, False


def lookup_method(self, name):
    method, unbound = lookup_maybe_method(self, name)
    if method is NULL:
        raise AttributeError(name)
    return method, unbound


def vectorcall_unbound(unbound, func, args):
    if not unbound:
        args = args[1:]
    return _call.PyObject_Vectorcall(func, args)


def vectorcall_method(name, args):
    func, unbound = lookup_method(args[0], name)
    return vectorcall_unbound(unbound, func, args)


def vectorcall_maybe(name, args):
    func, unbound = lookup_maybe_method(args[0], name)
    if func is NULL:
        return NotImplemented
    return vectorcall_unbound(unbound, func, args)


def call_method(self, name, args, kwds):
    meth, unbound = lookup_method(self, name)
    if unbound:
        return _call._PyObject_Call_Prepend(meth, self, args, kwds)
    return _call._PyObject_Call(meth, args, kwds)


def maybe_call_special_no_args(self, name, check_none=True):
    """-> (result, attr_is_none); result is NULL if the method is missing.
    Without `check_none` a `None` attribute is called (and fails)."""
    func, unbound = lookup_maybe_method(self, name)
    if func is NULL:
        return NULL, False
    if func is None and check_none:
        return NULL, True
    if unbound:
        return _call.PyObject_Vectorcall(func, (self,)), False
    return _call.PyObject_Vectorcall(func, ()), False


def maybe_call_special_one_arg(self, name, arg, check_none=True):
    func, unbound = lookup_maybe_method(self, name)
    if func is NULL:
        return NULL, False
    if func is None and check_none:
        return NULL, True
    if unbound:
        return _call.PyObject_Vectorcall(func, (self, arg)), False
    return _call.PyObject_Vectorcall(func, (arg,)), False


# --- generic slot functions ---------------------------------------------------

def slot_sq_length(self):
    res = vectorcall_method("__len__", (self,))
    res = _abstract._PyNumber_Index(res)
    if _abstract._PyLong_IsNegative(res):
        raise ValueError("__len__() should return >= 0")
    return res


def slot_sq_item(self, i):
    return vectorcall_method("__getitem__", (self, i))


def slot_sq_contains(self, value):
    res, attr_is_none = maybe_call_special_one_arg(self, "__contains__", value)
    if attr_is_none:
        raise TypeError(f"'{Py_TYPE(self).tp_name}' object is not a container")
    if res is NULL:
        return _abstract._PySequence_IterSearch(self, value, _abstract.PY_ITERSEARCH_CONTAINS)
    return _object.PyObject_IsTrue(res)


def slot_mp_subscript(self, key):
    return vectorcall_method("__getitem__", (self, key))


def slot_mp_ass_subscript(self, key, value):
    if value is NULL:
        vectorcall_method("__delitem__", (self, key))
    else:
        vectorcall_method("__setitem__", (self, key, value))


def _slot1binfull(slotname, dunder, rdunder):
    def slot(self, other):
        self_view = Py_TYPE(self)
        other_view = Py_TYPE(other)
        do_other = self_view is not other_view and getattr_slot(other_view, slotname) is slot
        if getattr_slot(self_view, slotname) is slot:
            if do_other and PyType_IsSubtype(other_view, self_view):
                if _method_is_overloaded(self, other, rdunder):
                    r = vectorcall_maybe(rdunder, (other, self))
                    if r is not NotImplemented:
                        return r
                    do_other = False
            r = vectorcall_maybe(dunder, (self, other))
            if r is not NotImplemented or other_view is self_view:
                return r
        if do_other:
            return vectorcall_maybe(rdunder, (other, self))
        return NotImplemented
    slot.__name__ = slot.__qualname__ = "slot_" + slotname
    return slot


def getattr_slot(view, field):
    return getattr(view, field)


def _method_is_overloaded(left, right, name) -> bool:
    b = _object.PyObject_GetOptionalAttr(Py_TYPE(right).type, name)
    if b is NULL:
        return False        # if right doesn't have it, it's not overloaded
    a = _object.PyObject_GetOptionalAttr(Py_TYPE(left).type, name)
    if a is NULL:
        return True         # if right has it but left doesn't, it's overloaded
    return _object.PyObject_RichCompareBool(a, b, _object.Py_NE)


slot_nb_add = _slot1binfull("nb_add", "__add__", "__radd__")
slot_nb_subtract = _slot1binfull("nb_subtract", "__sub__", "__rsub__")
slot_nb_multiply = _slot1binfull("nb_multiply", "__mul__", "__rmul__")
slot_nb_matrix_multiply = _slot1binfull("nb_matrix_multiply", "__matmul__", "__rmatmul__")
slot_nb_remainder = _slot1binfull("nb_remainder", "__mod__", "__rmod__")
slot_nb_lshift = _slot1binfull("nb_lshift", "__lshift__", "__rlshift__")
slot_nb_rshift = _slot1binfull("nb_rshift", "__rshift__", "__rrshift__")
slot_nb_and = _slot1binfull("nb_and", "__and__", "__rand__")
slot_nb_xor = _slot1binfull("nb_xor", "__xor__", "__rxor__")
slot_nb_or = _slot1binfull("nb_or", "__or__", "__ror__")
slot_nb_floor_divide = _slot1binfull("nb_floor_divide", "__floordiv__", "__rfloordiv__")
slot_nb_true_divide = _slot1binfull("nb_true_divide", "__truediv__", "__rtruediv__")


def slot_nb_power(self, other, modulus):
    if modulus is None:
        return _slot_nb_power_binary(self, other)
    # A copy of SLOT1BINFULL, but for three arguments.
    self_view = Py_TYPE(self)
    other_view = Py_TYPE(other)
    do_other = self_view is not other_view and other_view.nb_power is slot_nb_power
    if self_view.nb_power is slot_nb_power:
        if do_other and PyType_IsSubtype(other_view, self_view):
            if _method_is_overloaded(self, other, "__rpow__"):
                r = vectorcall_maybe("__rpow__", (other, self, modulus))
                if r is not NotImplemented:
                    return r
                do_other = False
        r = vectorcall_maybe("__pow__", (self, other, modulus))
        if r is not NotImplemented or other_view is self_view:
            return r
    if do_other:
        return vectorcall_maybe("__rpow__", (other, self, modulus))
    return NotImplemented


def _slot_nb_power_binary(self, other):
    self_view = Py_TYPE(self)
    other_view = Py_TYPE(other)
    do_other = self_view is not other_view and other_view.nb_power is slot_nb_power
    if self_view.nb_power is slot_nb_power:
        if do_other and PyType_IsSubtype(other_view, self_view):
            if _method_is_overloaded(self, other, "__rpow__"):
                r = vectorcall_maybe("__rpow__", (other, self))
                if r is not NotImplemented:
                    return r
                do_other = False
        r = vectorcall_maybe("__pow__", (self, other))
        if r is not NotImplemented or other_view is self_view:
            return r
    if do_other:
        return vectorcall_maybe("__rpow__", (other, self))
    return NotImplemented


def _slot0(dunder):
    def slot(self):
        return vectorcall_method(dunder, (self,))
    return slot


def _slot1(dunder):
    def slot(self, arg1):
        return vectorcall_method(dunder, (self, arg1))
    return slot


slot_nb_negative = _slot0("__neg__")
slot_nb_positive = _slot0("__pos__")
slot_nb_invert = _slot0("__invert__")
slot_nb_index = _slot0("__index__")
slot_nb_inplace_add = _slot1("__iadd__")
slot_nb_inplace_subtract = _slot1("__isub__")
slot_nb_inplace_multiply = _slot1("__imul__")
slot_nb_inplace_matrix_multiply = _slot1("__imatmul__")
slot_nb_inplace_remainder = _slot1("__imod__")
slot_nb_inplace_lshift = _slot1("__ilshift__")
slot_nb_inplace_rshift = _slot1("__irshift__")
slot_nb_inplace_and = _slot1("__iand__")
slot_nb_inplace_xor = _slot1("__ixor__")
slot_nb_inplace_or = _slot1("__ior__")
slot_nb_inplace_floor_divide = _slot1("__ifloordiv__")
slot_nb_inplace_true_divide = _slot1("__itruediv__")


def slot_nb_inplace_power(self, arg1, arg2):
    # Can't use _slot1: nb_inplace_power is ternary.
    return vectorcall_method("__ipow__", (self, arg1))


def slot_nb_bool(self):
    using_len = False
    value, attr_is_none = maybe_call_special_no_args(self, "__bool__")
    if attr_is_none:
        raise TypeError(f"'{Py_TYPE(self).tp_name}' cannot be interpreted as a boolean")
    if value is NULL:
        value, _ = maybe_call_special_no_args(self, "__len__", False)
        if value is NULL:
            return True
        using_len = True
    if using_len:
        # bool type enforced by slot_nb_len
        return _object.PyObject_IsTrue(value)
    if type(value) is bool:
        return _object.PyObject_IsTrue(value)
    raise TypeError(f"{_object._type_fullname(type(self))}.__bool__() must return a bool, "
                    f"not {_object._type_fullname(type(value))}")


def slot_tp_call(self, args, kwds):
    return call_method(self, "__call__", args, kwds)


def _call_attribute(self, attr, name):
    vt = Py_TYPE(attr)
    if vt.tp_flags & Py_TPFLAGS_METHOD_DESCRIPTOR:
        return _call.PyObject_Vectorcall(attr, (self, name))
    f = vt.tp_descr_get
    if f is not None:
        attr = f(attr, self, Py_TYPE(self).type)
    return _call.PyObject_Vectorcall(attr, (name,))


def _slot_tp_getattro(self, name):
    return vectorcall_method("__getattribute__", (self, name))


def slot_tp_getattr_hook(self, name):
    tp = Py_TYPE(self)
    getattr_ = _PyType_Lookup(tp, "__getattr__")
    if getattr_ is NULL:
        # No __getattr__ hook: use a simpler dispatcher.
        return _slot_tp_getattro(self, name)
    getattribute = _PyType_Lookup(tp, "__getattribute__")
    if getattribute is NULL or (type(getattribute) is _WrapperDescr
                                and _C_WRAPPER_SLOTS.get(("tp_getattro", id(getattribute)),
                                                         (None, None))[1] is _object.PyObject_GenericGetAttr):
        res = _object._PyObject_GenericGetAttrWithDict(self, name, NULL, True)
        # NULL here is an AttributeError suppressed by us.
        if res is NULL:
            res = _call_attribute(self, getattr_, name)
        return res
    err = None
    res = NULL
    try:
        res = _call_attribute(self, getattribute, name)
    except AttributeError as e:
        err = e
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        res = _call_attribute(self, getattr_, name)
    return res


def slot_tp_setattro(self, name, value):
    if value is NULL:
        vectorcall_method("__delattr__", (self, name))
    else:
        vectorcall_method("__setattr__", (self, name, value))


_OP_NAMES = ("__lt__", "__le__", "__eq__", "__ne__", "__gt__", "__ge__")


def slot_tp_richcompare(self, other, op):
    res, _ = maybe_call_special_one_arg(self, _OP_NAMES[op], other, False)
    if res is NULL:
        return NotImplemented
    return res


def _has_dunder_getitem(self) -> bool:
    method, _ = lookup_maybe_method(self, "__getitem__")
    return method is not NULL


def slot_tp_iter(self):
    res, attr_is_none = maybe_call_special_no_args(self, "__iter__")
    if res is not NULL:
        return res
    if attr_is_none or not _has_dunder_getitem(self):
        raise TypeError(f"'{Py_TYPE(self).tp_name}' object is not iterable")
    return _abstract.PySeqIter_New(self)


def slot_tp_iternext(self):
    return vectorcall_method("__next__", (self,))


def slot_tp_descr_get(self, obj, type_):
    tp = Py_TYPE(self)
    get = _PyType_Lookup(tp, "__get__")
    if get is NULL:
        # Avoid further slowdowns
        if tp.tp_descr_get is slot_tp_descr_get:
            tp.tp_descr_get = None
        return self
    if obj is NULL:
        obj = None
    if type_ is NULL:
        type_ = None
    return _call.PyObject_Vectorcall(get, (self, obj, type_))


def slot_tp_descr_set(self, target, value):
    if value is NULL:
        vectorcall_method("__delete__", (self, target))
    else:
        vectorcall_method("__set__", (self, target, value))


_GENERIC = {None: None}
for _n in ("slot_tp_getattr_hook", "slot_tp_setattro", "slot_tp_call", "slot_tp_richcompare",
           "slot_tp_iter", "slot_tp_iternext", "slot_tp_descr_get", "slot_tp_descr_set",
           "slot_sq_length", "slot_sq_item", "slot_sq_contains", "slot_mp_subscript",
           "slot_mp_ass_subscript", "slot_nb_add", "slot_nb_subtract", "slot_nb_multiply",
           "slot_nb_remainder", "slot_nb_power", "slot_nb_negative", "slot_nb_positive",
           "slot_nb_bool", "slot_nb_invert", "slot_nb_lshift", "slot_nb_rshift", "slot_nb_and",
           "slot_nb_xor", "slot_nb_or", "slot_nb_index", "slot_nb_inplace_add",
           "slot_nb_inplace_subtract", "slot_nb_inplace_multiply", "slot_nb_inplace_remainder",
           "slot_nb_inplace_power", "slot_nb_inplace_lshift", "slot_nb_inplace_rshift",
           "slot_nb_inplace_and", "slot_nb_inplace_xor", "slot_nb_inplace_or",
           "slot_nb_floor_divide", "slot_nb_true_divide", "slot_nb_inplace_floor_divide",
           "slot_nb_inplace_true_divide", "slot_nb_matrix_multiply",
           "slot_nb_inplace_matrix_multiply"):
    _GENERIC[_n] = globals()[_n]
del _n


# --- type.__call__ and builtin calls: pp-side C slots -------------------------

_TYPE_NEW = type.__dict__["__new__"]
_TYPE_CALL = type.__dict__["__call__"]
_IMPLICIT_WRAPPERS = (("__new__", staticmethod), ("__init_subclass__", classmethod),
                      ("__class_getitem__", classmethod))


def _wrap_type_namespace(ns):
    """type_new_set_attrs (Objects/typeobject.c) turns plain functions named
    __new__ / __init_subclass__ / __class_getitem__ into static/class methods,
    but only checks PyFunction_Check; do the same for VM functions. Like
    type.__new__, works on a copy and leaves the caller's namespace alone."""
    from pp.funcobject import Function
    if not isinstance(ns, dict):
        return ns
    repl = {name: wrap(ns[name]) for name, wrap in _IMPLICIT_WRAPPERS
            if type(ns.get(name)) is Function}
    if not repl:
        return ns
    ns = dict(ns)
    ns.update(repl)
    return ns


def type_call(callable, args, kwds):
    """tp_call of `type`: calling a class. `type(name, bases, ns)` and metaclass
    calls get the VM-function-aware namespace (see _wrap_type_namespace)."""
    if len(args) == 3 and PyType_IsSubtype(PyType_View(callable), PyType_View(type)) \
            and _PyType_Lookup(PyType_View(callable), "__new__") is _TYPE_NEW:
        args = (args[0], args[1], _wrap_type_namespace(args[2]))
    if kwds:
        return _TYPE_CALL(callable, *args, **kwds)
    return _TYPE_CALL(callable, *args)


def cfunction_call(func, args, kwds):
    """tp_call of builtin functions."""
    if len(args) == 4 and func is _TYPE_NEW_FUNC:
        args = (args[0], args[1], args[2], _wrap_type_namespace(args[3]))
    if kwds:
        return func(*args, **kwds)
    return func(*args)




# --- super() lookup (supercheck / _PySuper_Lookup) ------------------------------

def _supercheck(su_type, obj):
    """The type to start the MRO walk from (a host type)."""
    su_type_view = PyType_View(su_type)
    # Check for the special case: obj is a class (class methods).
    if PyType_Check(obj) and PyType_IsSubtype(PyType_View(obj), su_type_view):
        return obj
    obj_view = Py_TYPE(obj)
    if PyType_IsSubtype(obj_view, su_type_view):
        return obj_view.type
    # Try the slow way: obj.__class__ may be a proxy's.
    class_attr = _object.PyObject_GetOptionalAttr(obj, "__class__")
    if class_attr is not NULL and PyType_Check(class_attr) and class_attr is not obj_view.type:
        if PyType_IsSubtype(PyType_View(class_attr), su_type_view):
            return class_attr
    if PyType_Check(obj):
        type_or_instance, obj_str = "type", PyType_View(obj).tp_name
    else:
        type_or_instance, obj_str = "instance of", obj_view.tp_name
    raise TypeError(f"super(type, obj): obj ({type_or_instance} {obj_str}) is not "
                    f"an instance or subtype of type ({su_type_view.tp_name}).")


def _PySuper_LookupDescr(su_type, su_obj_type, name):
    mro = PyType_View(su_obj_type).tp_mro
    n = len(mro)
    i = 0
    # No need to check the last one: it's gonna be skipped anyway.
    while i + 1 < n:
        if mro[i] is su_type:
            break
        i += 1
    i += 1      # skip su->type (if any)
    while i < n:
        res = _type_dictget(_tp_dict(mro[i]), name, NULL)
        if res is not NULL:
            return res
        i += 1
    return NULL


def _PySuper_Lookup(su_type, su_obj, name, super_type, method_ok):
    """-> (result, method): with `method` true, result is an unbound method to
    call with `su_obj`."""
    su_obj_type = _supercheck(su_type, su_obj)
    res = _PySuper_LookupDescr(su_type, su_obj_type, name)
    if res is not NULL:
        res_view = Py_TYPE(res)
        if method_ok and res_view.tp_flags & Py_TPFLAGS_METHOD_DESCRIPTOR:
            return res, True
        f = res_view.tp_descr_get
        if f is not None:
            # Only pass 'obj' if this is instance-mode super.
            res = f(res, NULL if su_obj is su_obj_type else su_obj, su_obj_type)
        return res, False
    su = _call.PyObject_Vectorcall(super_type, (su_type, su_obj))
    return _object.PyObject_GenericGetAttr(su, name), False

_TYPE_NEW_FUNC = type.__new__
register_wrapper_slot("tp_call", _TYPE_CALL, type_call)
register_static_slots(types.BuiltinFunctionType, tp_call=cfunction_call)

from pp import call as _call        # noqa: E402,F811
from pp import object as _object    # noqa: E402,F811
from pp import abstract as _abstract    # noqa: E402,F811
