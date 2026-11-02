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
from weakref import getweakrefcount as _getweakrefcount, ref as _ref

from pp.errors import _PyErr_Clear, _PyThreadState_GET
from pp.frame import NULL

# These modules depend on this one; bound at the bottom.
_call = None
_object = None

Py_TPFLAGS_IMMUTABLETYPE = 1 << 8
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

# field, dunder, generic function (filled below), wrapper token. The token is the
# `wrapper` member of CPython's slotdef: it tells apart the slots that share a
# dunder (a wrapper_descriptor only stands for a slot whose wrapper matches).
# Entries of one dunder are listed in slotdefs order: number, mapping, sequence.
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
    ("nb_add", "__add__", "slot_nb_add", "binaryfunc_l"),
    ("nb_add", "__radd__", "slot_nb_add", None),
    ("nb_subtract", "__sub__", "slot_nb_subtract", None),
    ("nb_subtract", "__rsub__", "slot_nb_subtract", None),
    ("nb_multiply", "__mul__", "slot_nb_multiply", "binaryfunc_l"),
    ("nb_multiply", "__rmul__", "slot_nb_multiply", "binaryfunc_r"),
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
    ("nb_inplace_add", "__iadd__", "slot_nb_inplace_add", "binaryfunc"),
    ("nb_inplace_subtract", "__isub__", "slot_nb_inplace_subtract", None),
    ("nb_inplace_multiply", "__imul__", "slot_nb_inplace_multiply", "binaryfunc"),
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
    ("mp_length", "__len__", "slot_sq_length", "lenfunc"),
    ("mp_subscript", "__getitem__", "slot_mp_subscript", "binaryfunc"),
    ("mp_ass_subscript", "__setitem__", "slot_mp_ass_subscript", "objobjargproc"),
    ("mp_ass_subscript", "__delitem__", "slot_mp_ass_subscript", "delitem"),
    ("sq_length", "__len__", "slot_sq_length", "lenfunc"),
    # Heap types defining __add__/__mul__ have sq_concat/sq_repeat == NULL (no generic).
    ("sq_concat", "__add__", None, "binaryfunc"),
    ("sq_repeat", "__mul__", None, "indexargfunc"),
    ("sq_repeat", "__rmul__", None, "indexargfunc"),
    ("sq_item", "__getitem__", "slot_sq_item", "sq_item"),
    ("sq_ass_item", "__setitem__", "slot_sq_ass_item", "sq_setitem"),
    ("sq_ass_item", "__delitem__", "slot_sq_ass_item", "sq_delitem"),
    ("sq_contains", "__contains__", "slot_sq_contains", None),
    ("sq_inplace_concat", "__iadd__", None, "binaryfunc"),
    ("sq_inplace_repeat", "__imul__", None, "indexargfunc"),
)

SLOT_FIELDS = tuple(dict.fromkeys(spec[0] for spec in _SLOTDEF_SPECS))

# Slots with no dunder behind them: only types pp implements natively define them.
STATIC_FIELDS = ("am_send",)

# Every dunder some slot is made of (`update_slot` only reacts to these).
SLOT_DUNDERS = frozenset(spec[1] for spec in _SLOTDEF_SPECS) | {"__bases__"}

# dunder -> its slots, in slotdefs order; (field, dunder) -> wrapper token.
_DUNDER_FIELDS: dict = {}
_TOKENS: dict = {}
for _f, _d, _g, _t in _SLOTDEF_SPECS:
    _DUNDER_FIELDS.setdefault(_d, []).append(_f)
    _TOKENS[(_f, _d)] = _t
_AMBIGUOUS_DUNDERS = frozenset(d for d, fields in _DUNDER_FIELDS.items() if len(fields) > 1)
_AMBIGUOUS_FIELDS = frozenset(f for d in _AMBIGUOUS_DUNDERS for f in _DUNDER_FIELDS[d])
del _f, _d, _g, _t

_TYPE_ID = id(type)

DICT_NONE, DICT_STD, DICT_SPECIAL = 0, 1, 2


class PyTypeObject:
    """The slot table of one host type.

    CPython keeps the slots in the type object; a host type cannot be extended, so
    the tables live in `_views`, keyed by the id of the type with a weak reference
    that drops the entry when the type dies. A table holds data only (ids, flags,
    slot functions, a version tag), nothing that owns the type, and every lookup is
    given the type itself."""
    __slots__ = ("tp_ref", "tp_id", "tp_name", "tp_flags", "tp_mro_ids", "tp_version_tag",
                 "tp_cache", "tp_dictkind", "tp_has_sequence") + SLOT_FIELDS + STATIC_FIELDS

    def __init__(self, tp):
        ident = id(tp)
        self.tp_id = ident
        self.tp_ref = None
        self.tp_mro_ids = frozenset([id(base) for base in _tp_mro(tp) or ()])
        self.tp_version_tag = _next_version_tag()
        self.tp_cache = {}      # the method cache (see _PyType_Lookup)
        self.tp_flags = _tp_flags(tp) | _EXTRA_FLAGS.get(ident, 0)
        self.tp_name = _compute_tp_name(tp, self.tp_flags)
        self.tp_dictkind = DICT_NONE
        # A heap type always carries a PySequenceMethods; a static one only if it
        # defines sq_* slots (listed in _HOST_TYPES).
        self.tp_has_sequence = bool(self.tp_flags & Py_TPFLAGS_HEAPTYPE)
        for field in SLOT_FIELDS + STATIC_FIELDS:
            setattr(self, field, None)

    def __repr__(self):
        return f"<PyTypeObject {self.tp_name}>"


def _compute_tp_name(tp, flags) -> str:
    name = _tp_name_attr(tp)
    # Classes defined in Python have tp_name == __name__; C types made from a
    # PyType_Spec (heap types, immutable) have a dotted "module.name".
    if flags & Py_TPFLAGS_HEAPTYPE and not flags & Py_TPFLAGS_IMMUTABLETYPE:
        return name
    module = _tp_module(tp)
    if type(module) is not str or module == "builtins":
        return name
    return f"{module}.{name}"


# --- the real slots of host C types ---------------------------------------------
#
# CPython knows, from `d_base` of a wrapper_descriptor, which slot a dunder of a C
# type stands for. The host only gives the descriptor, so the slots of the host's
# builtin types are listed here, from their PyTypeObject definitions (the
# PySequenceMethods / PyMappingMethods / PyNumberMethods initializers, and the
# PyType_Spec slot arrays of the heap types). Only slots that share a dunder with
# another slot are listed ("nb_add" vs "sq_concat", "sq_item" vs "mp_subscript",
# ...); the others follow from the dunder alone. Entry: (has tp_as_sequence,
# has tp_as_mapping, those slots).
# A host type that is not listed is treated like a heap type: its dunders are
# dispatched through the generic slot_* functions, no guessing.

def _sq(*fields):
    return fields


_SEQ_LIST = ("sq_length", "sq_concat", "sq_repeat", "sq_item", "sq_ass_item",
             "sq_inplace_concat", "sq_inplace_repeat")
_HOST_TYPES: dict = {}      # id(host type) -> (has_sequence, has_mapping, frozenset of slots)


def _register_host_type(tp, has_sequence, has_mapping, fields) -> None:
    _HOST_TYPES[id(tp)] = (has_sequence, has_mapping, frozenset(fields))


def _register_host_types() -> None:
    reg = _register_host_type
    # Objects/listobject.c: list_as_sequence, list_as_mapping
    reg(list, True, True, _SEQ_LIST + ("mp_length", "mp_subscript", "mp_ass_subscript"))
    # Objects/tupleobject.c
    reg(tuple, True, True, ("sq_length", "sq_concat", "sq_repeat", "sq_item",
                            "mp_length", "mp_subscript"))
    # Objects/unicodeobject.c
    reg(str, True, True, ("sq_length", "sq_concat", "sq_repeat", "sq_item",
                          "mp_length", "mp_subscript"))
    # Objects/bytesobject.c
    reg(bytes, True, True, ("sq_length", "sq_concat", "sq_repeat", "sq_item",
                            "mp_length", "mp_subscript"))
    # Objects/bytearrayobject.c
    reg(bytearray, True, True, _SEQ_LIST + ("mp_length", "mp_subscript", "mp_ass_subscript"))
    # Objects/rangeobject.c
    reg(range, True, True, ("sq_length", "sq_item", "mp_length", "mp_subscript"))
    # Objects/dictobject.c: dict_as_sequence only has sq_contains
    reg(dict, True, True, ("mp_length", "mp_subscript", "mp_ass_subscript"))
    # Objects/setobject.c
    reg(set, True, False, ("sq_length",))
    reg(frozenset, True, False, ("sq_length",))
    # Objects/dictobject.c: dictkeys_as_sequence & co
    reg(type({}.keys()), True, False, ("sq_length",))
    reg(type({}.values()), True, False, ("sq_length",))
    reg(type({}.items()), True, False, ("sq_length",))
    # Objects/descrobject.c: mappingproxy_as_mapping, mappingproxy_as_sequence
    reg(types.MappingProxyType, True, True, ("mp_length", "mp_subscript"))
    # Objects/memoryobject.c
    reg(memoryview, True, True, ("sq_length", "sq_item", "mp_length", "mp_subscript",
                                 "mp_ass_subscript"))
    # Number types: nb_add / nb_multiply, no sequence or mapping (bool inherits int's)
    for tp in (int, bool, float, complex):
        reg(tp, False, False, ("nb_add", "nb_multiply"))
    for tp in (object, type, type(None)):
        reg(tp, False, False, ())


def _host_base_field(owner, dunder):
    """The slot a wrapper_descriptor of `owner` for `dunder` was made from
    (`d_base`): the first slot, in slotdefs order, that `owner` has. None when
    `owner` is not a known host type."""
    entry = _HOST_TYPES.get(id(owner))
    if entry is None:
        return None
    for field in _DUNDER_FIELDS[dunder]:
        if field in entry[2]:
            return field
    return None


def _mro_host_fields(tp) -> frozenset:
    """The ambiguous slots set on the host types of the MRO (what a heap subtype
    inherits)."""
    fields = set()
    for base in _tp_mro(tp):
        entry = _HOST_TYPES.get(id(base))
        if entry is not None:
            fields |= entry[2]
    return fields


# --- views --------------------------------------------------------------------

_views: dict = {}              # id(type) -> PyTypeObject, dropped when the type dies
_views_get = _views.get
_EXTRA_FLAGS: dict = {}        # id(host type) -> extra tp_flags (types pp defines in Python)
_STATIC_SLOTS: dict = {}       # id(host type) -> {field: function}: "C" slots implemented by pp
_C_WRAPPER_SLOTS: dict = {}    # (field, id(wrapper_descriptor)) -> function implemented by pp
_object_getattribute = object.__dict__["__getattribute__"]
_object_setattr = object.__setattr__
_object_delattr = object.__delattr__
_object_getstate = object.__dict__["__getstate__"]
_tp_dictoffset = type.__dict__["__dictoffset__"].__get__

# Type version tags (Objects/typeobject.c): a table gets a new tag whenever the
# type or a base changes, so entries of the method cache made under the old one
# can never match again. Tags are never reused.
_version_tag = 0


def _next_version_tag() -> int:
    global _version_tag
    _version_tag += 1
    return _version_tag


def register_static_slots(tp, flags=0, **slots) -> None:
    """Declare slots of a type pp implements itself (the C struct's initializers)."""
    _EXTRA_FLAGS[id(tp)] = flags
    _STATIC_SLOTS[id(tp)] = slots
    PyType_Modified(tp)


def register_wrapper_slot(field, wrapper, function) -> None:
    """A host wrapper_descriptor whose slot function pp implements itself."""
    _C_WRAPPER_SLOTS[(field, id(wrapper))] = (wrapper, function)


def Py_TYPE(o) -> PyTypeObject:
    tp = type(o)
    return _views_get(id(tp)) or _new_view(tp)      # PyType_View(type(o)), inlined


def PyType_View(tp) -> PyTypeObject:
    """The PyTypeObject of a host type object."""
    return _views_get(id(tp)) or _new_view(tp)


def _drop_view(ident, ref) -> None:
    """The weakref callback of a type: forget its table (unless a newer type took
    the id and already has its own)."""
    view = _views_get(ident)
    if view is not None and view.tp_ref is ref:
        del _views[ident]


def _new_view(tp) -> PyTypeObject:
    view = PyTypeObject(tp)
    if _tp_mro(tp) is None:
        # A class under construction, asked about by an overridden mro(): no MRO
        # yet, so no slots; not kept.
        return view
    ident = view.tp_id
    # Every live heap type is weakly referenced (by its base's subclasses): none
    # left means its weakrefs were cleared and it is being finalized, so a
    # callback would never run; use the table without keeping it.
    dying = view.tp_flags & Py_TPFLAGS_HEAPTYPE and _getweakrefcount(tp) == 0
    if not dying:
        view.tp_ref = _ref(tp, lambda ref, ident=ident: _drop_view(ident, ref))
    _views[ident] = view
    try:
        fixup_slot_dispatchers(tp, view)
        view.tp_dictkind = _find_dict_kind(tp)
        host = _HOST_TYPES.get(ident)
        if host is not None:
            view.tp_has_sequence = host[0]
    finally:
        if dying:
            del _views[ident]
    return view


def _find_dict_kind(tp) -> int:
    """How `_PyObject_GetDictPtr` finds the dict of an instance."""
    if _tp_dictoffset(tp) == 0:
        return DICT_NONE
    descr = _PyType_Lookup(tp, "__dict__")
    if type(descr) is _GetSetDescr or type(descr) is _MemberDescr:
        return DICT_STD
    return DICT_SPECIAL         # e.g. a class defining `__dict__` as a property


def _PyObject_GetDictPtr(obj, view):
    """The instance dict of `obj`, or None if its type has none (or, for a type
    whose `__dict__` attribute is not the dict's descriptor, none yet)."""
    kind = view.tp_dictkind
    if kind == DICT_STD:
        return _object_getattribute(obj, "__dict__")
    if kind == DICT_NONE:
        return None
    # The dict lives at tp_dictoffset whatever `__dict__` means to the class.
    # `object.__getstate__` hands out that very dict (None when it is empty).
    state = _object_getstate(obj)
    if type(state) is tuple:
        state = state[0]
    return state


def PyType_Modified(tp) -> None:
    """Drop the slot tables of `tp` and its subclasses (rebuilt lazily from the
    MRO). Called after any change to a type's dict or bases."""
    _views.pop(id(tp), None)
    for sub in _tp_subclasses(tp):
        PyType_Modified(sub)


def _clear_lookup_cache(tp) -> None:
    """`type_modified` for a change that leaves the slots alone: a new version tag
    retires every method-cache entry of `tp` and its subclasses."""
    view = _views_get(id(tp))
    if view is not None:
        view.tp_version_tag = _next_version_tag()
        view.tp_cache = {}
    for sub in _tp_subclasses(tp):
        _clear_lookup_cache(sub)


def update_slot(tp, name) -> None:
    if type(name) is str and name in SLOT_DUNDERS:
        PyType_Modified(tp)
    else:
        _clear_lookup_cache(tp)


def PyType_Check(o) -> bool:
    if type(o) is type:
        return True
    return _TYPE_ID in Py_TYPE(o).tp_mro_ids


def PyType_IsSubtype(a, b) -> bool:
    """a, b are PyTypeObject views."""
    return b.tp_id in a.tp_mro_ids


# The method cache. CPython's is a global array indexed by a hash of
# (tp_version_tag, name); here each slot table keeps its own dict, name -> result,
# emptied whenever the version tag changes (and gone with the table when the type
# is modified or dies). It does not own the type: what the lookup found in the
# type's own dict is stored only as a weak reference (a method using `__class__`
# would keep its class alive), and only for functions; what a base provides, or
# that nothing was found, is stored as is.
_MISS = object()


class _OwnRef(_ref):
    """A method-cache entry for something found in the type's own dict."""
    __slots__ = ()


_OWN_CACHEABLE: set = {types.FunctionType}   # weakly referenceable function types


def register_function_type(tp) -> None:
    """Functions of type `tp` found in a type's own dict are method-cached (weakly)."""
    _OWN_CACHEABLE.add(tp)


def _PyType_Lookup(tp, name):
    """MRO lookup in the host type `tp`. Returns NULL if absent."""
    view = _views_get(id(tp)) or _new_view(tp)
    if type(name) is str:
        cache = view.tp_cache
        res = cache.get(name, _MISS)
        if res is not _MISS:
            if type(res) is not _OwnRef:
                return res
            res = res()
            if res is not None:
                return res
    else:
        cache = None
    depth = 0
    for base in _tp_mro(tp):
        res = _type_dictget(_tp_dict(base), name, NULL)
        if res is not NULL:
            if cache is not None:
                if depth:
                    cache[name] = res
                elif type(res) in _OWN_CACHEABLE:
                    cache[name] = _OwnRef(res)
            return res
        depth += 1
    if cache is not None:
        cache[name] = NULL
    return NULL


def PyObject_TypeCheck(o, tp) -> bool:
    """tp is a host type."""
    cls = type(o)
    if cls is tp:
        return True
    return id(tp) in Py_TYPE(o).tp_mro_ids


# --- filling slots (update_one_slot / fixup_slot_dispatchers) -----------------

_SLOT_GROUPS: dict = {}


def _group_slotdefs():
    for field, dunder, function, token in _SLOTDEF_SPECS:
        _SLOT_GROUPS.setdefault(field, []).append((dunder, function, token))


_group_slotdefs()


def update_one_slot(tp, view, field) -> None:
    specific_found = {}
    owner = None
    generic = None
    use_generic = False
    have_specific = False
    missing_iternext = False
    host_fields = None
    for dunder, function, token in _SLOT_GROUPS[field]:
        descr = _PyType_Lookup(tp, dunder)
        if descr is NULL:
            if field == "tp_iternext":
                missing_iternext = True
            continue
        if type(descr) is _WrapperDescr and descr.__name__ == dunder:
            objclass = descr.__objclass__
            if dunder in _AMBIGUOUS_DUNDERS:
                base_field = _host_base_field(objclass, dunder)
                if base_field is None:
                    # A wrapper of a host type whose slots are not known: a plain
                    # method, called through the generic slot function.
                    use_generic = True
                    generic = _GENERIC.get(function)
                    continue
                if host_fields is None:
                    host_fields = _mro_host_fields(tp)
                present = [f for f in _DUNDER_FIELDS[dunder] if f in host_fields]
                if len(present) != 1 or present[0] == field:
                    generic = _GENERIC.get(function)
                matches = _TOKENS[(base_field, dunder)] == token
            else:
                generic = _GENERIC.get(function)
                matches = True
            if matches and (owner is None or owner is objclass) \
                    and id(objclass) in view.tp_mro_ids:
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
    setattr(view, field, value)


def _host_slot(tp, view, field, fields):
    """A slot of a known host type itself: set exactly when the C type sets it."""
    if field not in fields:
        return None
    found = {}
    for dunder, function, token in _SLOT_GROUPS[field]:
        descr = _PyType_Lookup(tp, dunder)
        if descr is not NULL:
            found[dunder] = descr
    if not found:
        return None
    return _c_slot(field, found)


def fixup_slot_dispatchers(tp, view) -> None:
    host = _HOST_TYPES.get(view.tp_id)
    for field in SLOT_FIELDS:
        if host is not None and field in _AMBIGUOUS_FIELDS:
            setattr(view, field, _host_slot(tp, view, field, host[2]))
        else:
            update_one_slot(tp, view, field)
    static = _STATIC_SLOTS.get(view.tp_id)
    if static:
        for field, function in static.items():
            setattr(view, field, function)


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
    # Cache only adapters over descriptors of static types: they live forever
    # anyway, so the cache cannot keep a class alive. (The cache entry keeps the
    # descriptors, whose ids are in the key.)
    if all(_descr_owner(d) is not None and not (_tp_flags(_descr_owner(d)) & Py_TPFLAGS_HEAPTYPE)
           for d in found.values()):
        _adapter_cache[key] = (fn, tuple(found.values()))
    return fn


def _descr_owner(d):
    return getattr(d, "__objclass__", None)


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
        if obj is None and tp is not NULL:
            # Host wrappers read an obj of None as "class access"; the instance
            # `None` can only be reached through the host's own generic getattr.
            return _object_getattribute(None, self.__name__)
        return d(self, None if obj is NULL else obj, None if tp is NULL else tp)
    return adapter


_object_getattribute = object.__dict__["__getattribute__"]


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
    "sq_ass_item": _setter_deleter_adapter("__setitem__", "__delitem__"),
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
        err = True    # not the exception itself: it would form a cycle with its traceback
    if err is not None:
        _PyErr_Clear(_PyThreadState_GET())
        return NULL
    return res


def lookup_maybe_method(self, name):
    """-> (method, unbound); method is NULL if the lookup failed."""
    value = _PyType_Lookup(type(self), name)
    if value is NULL:
        return NULL, False
    vt = Py_TYPE(value)
    if vt.tp_flags & Py_TPFLAGS_METHOD_DESCRIPTOR:
        return value, True          # avoid a temporary bound method
    f = vt.tp_descr_get
    if f is not None:
        return _suppressing_attribute_error(f, value, self, type(self)), False
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


def slot_sq_ass_item(self, index, value):
    if value is NULL:
        vectorcall_method("__delitem__", (self, index))
    else:
        vectorcall_method("__setitem__", (self, index, value))


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
    b = _object.PyObject_GetOptionalAttr(type(right), name)
    if b is NULL:
        return False        # if right doesn't have it, it's not overloaded
    a = _object.PyObject_GetOptionalAttr(type(left), name)
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
        attr = f(attr, self, type(self))
    return _call.PyObject_Vectorcall(attr, (name,))


def _slot_tp_getattro(self, name):
    return vectorcall_method("__getattribute__", (self, name))


def slot_tp_getattr_hook(self, name):
    cls = type(self)
    getattr_ = _PyType_Lookup(cls, "__getattr__")
    if getattr_ is NULL:
        # No __getattr__ hook: use a simpler dispatcher.
        return _slot_tp_getattro(self, name)
    getattribute = _PyType_Lookup(cls, "__getattribute__")
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
        err = True    # not the exception itself: it would form a cycle with its traceback
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
    get = _PyType_Lookup(type(self), "__get__")
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
           "slot_sq_length", "slot_sq_item", "slot_sq_ass_item", "slot_sq_contains", "slot_mp_subscript",
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
            and _PyType_Lookup(callable, "__new__") is _TYPE_NEW:
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
        return type(obj)
    # Try the slow way: obj.__class__ may be a proxy's.
    class_attr = _object.PyObject_GetOptionalAttr(obj, "__class__")
    if class_attr is not NULL and PyType_Check(class_attr) and class_attr is not type(obj):
        if PyType_IsSubtype(PyType_View(class_attr), su_type_view):
            return class_attr
    if PyType_Check(obj):
        type_or_instance, obj_str = "type", PyType_View(obj).tp_name
    else:
        type_or_instance, obj_str = "instance of", obj_view.tp_name
    raise TypeError(f"super(type, obj): obj ({type_or_instance} {obj_str}) is not "
                    f"an instance or subtype of type ({su_type_view.tp_name}).")


def _PySuper_LookupDescr(su_type, su_obj_type, name):
    mro = _tp_mro(su_obj_type)
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


# --- calling the host's `type.__setattr__` & co ------------------------------------
#
# In CPython `type_setattro` (the slot behind `type.__setattr__`) calls
# `update_slot` itself, so every way of changing a type's attributes refreshes its
# slots. The host's wrapper cannot do that, so calls of wrapper_descriptors and
# method-wrappers (`type.__setattr__(C, ...)`, `super().__setattr__(...)` in a
# metaclass, `descr.__set__(C, ...)`) are routed through here.

_TYPE_MUTATORS = frozenset(("__setattr__", "__delattr__", "__set__", "__delete__"))


def _call_host(func, args, kwds):
    if kwds:
        return func(*args, **kwds)
    return func(*args)


def _type_changed(target, name) -> None:
    if PyType_Check(target):
        if name is NULL:
            PyType_Modified(target)
        else:
            update_slot(target, name)


def wrapperdescr_call(descr, args, kwds):
    res = _call_host(descr, args, kwds)
    name = descr.__name__
    if name in _TYPE_MUTATORS and args:
        if name == "__setattr__" or name == "__delattr__":
            _type_changed(args[0], args[1] if len(args) > 1 else NULL)
        elif len(args) > 1:
            _type_changed(args[1], NULL)
    return res


def methodwrapper_call(mw, args, kwds):
    res = _call_host(mw, args, kwds)
    name = mw.__name__
    if name in _TYPE_MUTATORS:
        if name == "__setattr__" or name == "__delattr__":
            _type_changed(mw.__self__, args[0] if args else NULL)
        elif args:
            _type_changed(args[0], NULL)
    return res


register_static_slots(types.WrapperDescriptorType, tp_call=wrapperdescr_call)
register_static_slots(types.MethodWrapperType, tp_call=methodwrapper_call)
_register_host_types()

from pp import call as _call        # noqa: E402,F811
from pp import object as _object    # noqa: E402,F811
from pp import abstract as _abstract    # noqa: E402,F811
