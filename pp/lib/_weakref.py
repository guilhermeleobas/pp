"""Pure-Python _weakref, executed by the pp VM (replaces the C module).

Semantics follow Objects/weakrefobject.c and Modules/_weakref.c (3.15), with
one deliberate limitation: guest values are host objects and pp cannot observe
their death, so

  * a weak reference keeps its referent alive (it is a strong reference);
  * a reference never becomes dead by itself: ``ref()`` always returns the
    referent, proxies never raise ReferenceError, and callbacks never fire;
  * a ref holds its referent only for as long as the ref itself lives:
    ``weakref.ref(C())`` frees the object immediately, finalizers included;
  * ``getweakrefcount`` counts live refs (per-object count kept by id and
    dropped with the last ref), but the refs themselves are not kept, so
    ``getweakrefs`` always returns ``[]`` and ``ref(o) is ref(o)`` is False
    (CPython shares the basic ref of an object).

Kept from CPython: ``ref`` hash is the referent's hash and equality compares
referents, ``ref`` is subclassable, ``__callback__``, repr, ``ref[int]``, and
TypeError for objects whose type has no weakref slot (``int``, ``str``,
``tuple``, ``list``, ``dict``, ... and instances of classes without
``__weakref__``), decided from ``type(obj).__weakrefoffset__``.
Proxies forward attribute access, operators, ``len``/``iter``/``in``/indexing
and ``bool``/``str``; they are not hashable and not subclassable.
"""

import operator as _operator

_GenericAlias = type(list[int])

# id(obj) -> number of live refs/proxies. Only the count is kept (never the
# refs or the referent), so nothing is pinned beyond what each live ref holds;
# the entry goes away when the last ref is dropped (``__del__``).
_counts = {}


def _fq(tp):
    """Fully qualified type name, as ``%T`` / ``PyType_GetFullyQualifiedName``."""
    mod = tp.__module__
    if mod == "builtins" or mod == "__main__" or mod is None:
        return tp.__qualname__
    return f"{mod}.{tp.__qualname__}"


_HEAPTYPE = 1 << 9


def _tp_name(tp):
    """``tp_name``: ``__name__`` for heap types, ``module.name`` for static ones."""
    if tp.__flags__ & _HEAPTYPE:
        return tp.__name__
    mod = tp.__module__
    if mod == "builtins" or mod is None:
        return tp.__name__
    return f"{mod}.{tp.__name__}"


def _check_weakrefable(ob):
    if type(ob).__weakrefoffset__ == 0:
        raise TypeError(f"cannot create weak reference to '{_tp_name(type(ob))}' object")


def _incr(ob):
    k = id(ob)
    _counts[k] = _counts.get(k, 0) + 1


def _decr(wr, _counts=_counts, _get=object.__getattribute__):
    try:
        k = id(_get(wr, "_o"))
    except AttributeError:
        return
    n = _counts.get(k, 0) - 1
    if n > 0:
        _counts[k] = n
    else:
        _counts.pop(k, None)


def _check_args(name, n):
    if n < 1:
        raise TypeError(f"{name} expected at least 1 argument, got {n}")
    if n > 2:
        raise TypeError(f"{name} expected at most 2 arguments, got {n}")


def _special(obj, name):
    """_PyObject_LookupSpecial: look *name* up on the type, then bind it."""
    for klass in type(obj).__mro__:
        if name in klass.__dict__:
            attr = klass.__dict__[name]
            get = getattr(type(attr), "__get__", None)
            return get(attr, obj, type(obj)) if get is not None else attr
    raise AttributeError(name)


class ReferenceType:
    """Create a weak reference to 'object'.

Here the reference is strong and never dies (see the module docstring)."""

    __slots__ = ("_o", "_cb", "_h")

    def __new__(cls, *args, **kwargs):
        _check_args("__new__", len(args))
        ob = args[0]
        callback = args[1] if len(args) > 1 else None
        _check_weakrefable(ob)
        self = object.__new__(cls)
        self._o = ob
        self._cb = callback
        self._h = None
        _incr(ob)
        return self

    def __del__(self, _decr=_decr):
        _decr(self)

    def __init__(self, *args, **kwargs):
        if kwargs:
            raise TypeError("ref() takes no keyword arguments")
        _check_args("__init__", len(args))

    @property
    def __callback__(self):
        return self._cb

    def __call__(self):
        return self._o

    def __hash__(self):
        h = self._h
        if h is None:
            h = self._h = hash(self._o)
        return h

    def __eq__(self, other):
        if not isinstance(other, ReferenceType):
            return NotImplemented
        return self._o == other._o

    def __ne__(self, other):
        if not isinstance(other, ReferenceType):
            return NotImplemented
        return self._o != other._o

    def __repr__(self):
        o = self._o
        try:
            name = _special(o, "__name__")
        except AttributeError:
            name = None
        if not isinstance(name, str):
            return f"<weakref at {id(self):#x}; to '{_fq(type(o))}' at {id(o):#x}>"
        return (f"<weakref at {id(self):#x}; to '{_fq(type(o))}' at {id(o):#x} "
                f"({name})>")

    __class_getitem__ = classmethod(_GenericAlias)


ReferenceType.__module__ = "weakref"
ref = ReferenceType


def _obj(p):
    return object.__getattribute__(p, "_o")


def _unwrap(x):
    if type(x) is ProxyType or type(x) is CallableProxyType:
        return object.__getattribute__(x, "_o")
    return x


class ProxyType:
    __slots__ = ("_o", "_cb")

    def __new__(cls, *args, **kwargs):
        raise TypeError(f"cannot create '{cls.__module__}.{cls.__name__}' instances")

    def __del__(self, _decr=_decr):
        _decr(self)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("type 'weakref.ProxyType' is not an acceptable base type")

    def __getattribute__(self, name):
        return getattr(object.__getattribute__(self, "_o"), name)

    def __setattr__(self, name, value):
        setattr(_obj(self), name, value)

    def __delattr__(self, name):
        delattr(_obj(self), name)

    def __repr__(self):
        o = _obj(self)
        return f"<weakproxy at {id(self):#x}; to '{_fq(type(o))}' at {id(o):#x}>"

    def __str__(self):
        return str(_obj(self))

    def __bytes__(self):
        return bytes(_obj(self))

    def __hash__(self):
        raise TypeError("unhashable type: 'weakref.ProxyType'")

    def __bool__(self):
        return bool(_obj(self))

    def __len__(self):
        return len(_obj(self))

    def __length_hint__(self):
        return _operator.length_hint(_obj(self))

    def __iter__(self):
        return iter(_obj(self))

    def __next__(self):
        o = _obj(self)
        try:
            nxt = type(o).__next__
        except AttributeError:
            raise TypeError(f"Weakref proxy referenced a non-iterator '{_fq(type(o))}' object") from None
        return nxt(o)

    def __reversed__(self):
        return reversed(_obj(self))

    def __contains__(self, item):
        return _unwrap(item) in _obj(self)

    def __getitem__(self, key):
        return _obj(self)[_unwrap(key)]

    def __setitem__(self, key, value):
        _obj(self)[_unwrap(key)] = _unwrap(value)

    def __delitem__(self, key):
        del _obj(self)[_unwrap(key)]

    def __eq__(self, other):
        return _obj(self) == _unwrap(other)

    def __ne__(self, other):
        return _obj(self) != _unwrap(other)

    def __lt__(self, other):
        return _obj(self) < _unwrap(other)

    def __le__(self, other):
        return _obj(self) <= _unwrap(other)

    def __gt__(self, other):
        return _obj(self) > _unwrap(other)

    def __ge__(self, other):
        return _obj(self) >= _unwrap(other)

    def __int__(self):
        return int(_obj(self))

    def __float__(self):
        return float(_obj(self))

    def __index__(self):
        return _operator.index(_obj(self))

    def __abs__(self):
        return abs(_obj(self))

    def __divmod__(self, other):
        return divmod(_obj(self), _unwrap(other))

    def __rdivmod__(self, other):
        return divmod(_unwrap(other), _obj(self))

    def __pow__(self, other, mod=None):
        if mod is None:
            return pow(_obj(self), _unwrap(other))
        return pow(_obj(self), _unwrap(other), _unwrap(mod))

    def __rpow__(self, other, mod=None):
        if mod is None:
            return pow(_unwrap(other), _obj(self))
        return pow(_unwrap(other), _obj(self), _unwrap(mod))

    def __ipow__(self, other, mod=None):
        o = _obj(self)
        if mod is None:
            o **= _unwrap(other)
            return o
        return pow(o, _unwrap(other), _unwrap(mod))

    def __add__(self, other):
        return _obj(self) + _unwrap(other)

    def __radd__(self, other):
        return _unwrap(other) + _obj(self)

    def __iadd__(self, other):
        o = _obj(self)
        o += _unwrap(other)
        return o

    def __sub__(self, other):
        return _obj(self) - _unwrap(other)

    def __rsub__(self, other):
        return _unwrap(other) - _obj(self)

    def __isub__(self, other):
        o = _obj(self)
        o -= _unwrap(other)
        return o

    def __mul__(self, other):
        return _obj(self) * _unwrap(other)

    def __rmul__(self, other):
        return _unwrap(other) * _obj(self)

    def __imul__(self, other):
        o = _obj(self)
        o *= _unwrap(other)
        return o

    def __truediv__(self, other):
        return _obj(self) / _unwrap(other)

    def __rtruediv__(self, other):
        return _unwrap(other) / _obj(self)

    def __itruediv__(self, other):
        o = _obj(self)
        o /= _unwrap(other)
        return o

    def __floordiv__(self, other):
        return _obj(self) // _unwrap(other)

    def __rfloordiv__(self, other):
        return _unwrap(other) // _obj(self)

    def __ifloordiv__(self, other):
        o = _obj(self)
        o //= _unwrap(other)
        return o

    def __mod__(self, other):
        return _obj(self) % _unwrap(other)

    def __rmod__(self, other):
        return _unwrap(other) % _obj(self)

    def __imod__(self, other):
        o = _obj(self)
        o %= _unwrap(other)
        return o

    def __lshift__(self, other):
        return _obj(self) << _unwrap(other)

    def __rlshift__(self, other):
        return _unwrap(other) << _obj(self)

    def __ilshift__(self, other):
        o = _obj(self)
        o <<= _unwrap(other)
        return o

    def __rshift__(self, other):
        return _obj(self) >> _unwrap(other)

    def __rrshift__(self, other):
        return _unwrap(other) >> _obj(self)

    def __irshift__(self, other):
        o = _obj(self)
        o >>= _unwrap(other)
        return o

    def __and__(self, other):
        return _obj(self) & _unwrap(other)

    def __rand__(self, other):
        return _unwrap(other) & _obj(self)

    def __iand__(self, other):
        o = _obj(self)
        o &= _unwrap(other)
        return o

    def __or__(self, other):
        return _obj(self) | _unwrap(other)

    def __ror__(self, other):
        return _unwrap(other) | _obj(self)

    def __ior__(self, other):
        o = _obj(self)
        o |= _unwrap(other)
        return o

    def __xor__(self, other):
        return _obj(self) ^ _unwrap(other)

    def __rxor__(self, other):
        return _unwrap(other) ^ _obj(self)

    def __ixor__(self, other):
        o = _obj(self)
        o ^= _unwrap(other)
        return o

    def __matmul__(self, other):
        return _obj(self) @ _unwrap(other)

    def __rmatmul__(self, other):
        return _unwrap(other) @ _obj(self)

    def __imatmul__(self, other):
        o = _obj(self)
        o @= _unwrap(other)
        return o

    def __neg__(self):
        return -_obj(self)

    def __pos__(self):
        return +_obj(self)

    def __invert__(self):
        return ~_obj(self)


ProxyType.__module__ = "weakref"


class CallableProxyType:
    __slots__ = ("_o", "_cb")

    def __new__(cls, *args, **kwargs):
        raise TypeError(f"cannot create '{cls.__module__}.{cls.__name__}' instances")

    def __del__(self, _decr=_decr):
        _decr(self)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("type 'weakref.CallableProxyType' is not an acceptable base type")

    def __getattribute__(self, name):
        return getattr(object.__getattribute__(self, "_o"), name)

    def __setattr__(self, name, value):
        setattr(_obj(self), name, value)

    def __delattr__(self, name):
        delattr(_obj(self), name)

    def __repr__(self):
        o = _obj(self)
        return f"<weakproxy at {id(self):#x}; to '{_fq(type(o))}' at {id(o):#x}>"

    def __str__(self):
        return str(_obj(self))

    def __bytes__(self):
        return bytes(_obj(self))

    def __hash__(self):
        raise TypeError("unhashable type: 'weakref.CallableProxyType'")

    def __bool__(self):
        return bool(_obj(self))

    def __len__(self):
        return len(_obj(self))

    def __length_hint__(self):
        return _operator.length_hint(_obj(self))

    def __iter__(self):
        return iter(_obj(self))

    def __next__(self):
        o = _obj(self)
        try:
            nxt = type(o).__next__
        except AttributeError:
            raise TypeError(f"Weakref proxy referenced a non-iterator '{_fq(type(o))}' object") from None
        return nxt(o)

    def __reversed__(self):
        return reversed(_obj(self))

    def __contains__(self, item):
        return _unwrap(item) in _obj(self)

    def __getitem__(self, key):
        return _obj(self)[_unwrap(key)]

    def __setitem__(self, key, value):
        _obj(self)[_unwrap(key)] = _unwrap(value)

    def __delitem__(self, key):
        del _obj(self)[_unwrap(key)]

    def __eq__(self, other):
        return _obj(self) == _unwrap(other)

    def __ne__(self, other):
        return _obj(self) != _unwrap(other)

    def __lt__(self, other):
        return _obj(self) < _unwrap(other)

    def __le__(self, other):
        return _obj(self) <= _unwrap(other)

    def __gt__(self, other):
        return _obj(self) > _unwrap(other)

    def __ge__(self, other):
        return _obj(self) >= _unwrap(other)

    def __int__(self):
        return int(_obj(self))

    def __float__(self):
        return float(_obj(self))

    def __index__(self):
        return _operator.index(_obj(self))

    def __abs__(self):
        return abs(_obj(self))

    def __divmod__(self, other):
        return divmod(_obj(self), _unwrap(other))

    def __rdivmod__(self, other):
        return divmod(_unwrap(other), _obj(self))

    def __pow__(self, other, mod=None):
        if mod is None:
            return pow(_obj(self), _unwrap(other))
        return pow(_obj(self), _unwrap(other), _unwrap(mod))

    def __rpow__(self, other, mod=None):
        if mod is None:
            return pow(_unwrap(other), _obj(self))
        return pow(_unwrap(other), _obj(self), _unwrap(mod))

    def __ipow__(self, other, mod=None):
        o = _obj(self)
        if mod is None:
            o **= _unwrap(other)
            return o
        return pow(o, _unwrap(other), _unwrap(mod))

    def __call__(self, *args, **kwargs):
        return _obj(self)(*args, **kwargs)

    def __add__(self, other):
        return _obj(self) + _unwrap(other)

    def __radd__(self, other):
        return _unwrap(other) + _obj(self)

    def __iadd__(self, other):
        o = _obj(self)
        o += _unwrap(other)
        return o

    def __sub__(self, other):
        return _obj(self) - _unwrap(other)

    def __rsub__(self, other):
        return _unwrap(other) - _obj(self)

    def __isub__(self, other):
        o = _obj(self)
        o -= _unwrap(other)
        return o

    def __mul__(self, other):
        return _obj(self) * _unwrap(other)

    def __rmul__(self, other):
        return _unwrap(other) * _obj(self)

    def __imul__(self, other):
        o = _obj(self)
        o *= _unwrap(other)
        return o

    def __truediv__(self, other):
        return _obj(self) / _unwrap(other)

    def __rtruediv__(self, other):
        return _unwrap(other) / _obj(self)

    def __itruediv__(self, other):
        o = _obj(self)
        o /= _unwrap(other)
        return o

    def __floordiv__(self, other):
        return _obj(self) // _unwrap(other)

    def __rfloordiv__(self, other):
        return _unwrap(other) // _obj(self)

    def __ifloordiv__(self, other):
        o = _obj(self)
        o //= _unwrap(other)
        return o

    def __mod__(self, other):
        return _obj(self) % _unwrap(other)

    def __rmod__(self, other):
        return _unwrap(other) % _obj(self)

    def __imod__(self, other):
        o = _obj(self)
        o %= _unwrap(other)
        return o

    def __lshift__(self, other):
        return _obj(self) << _unwrap(other)

    def __rlshift__(self, other):
        return _unwrap(other) << _obj(self)

    def __ilshift__(self, other):
        o = _obj(self)
        o <<= _unwrap(other)
        return o

    def __rshift__(self, other):
        return _obj(self) >> _unwrap(other)

    def __rrshift__(self, other):
        return _unwrap(other) >> _obj(self)

    def __irshift__(self, other):
        o = _obj(self)
        o >>= _unwrap(other)
        return o

    def __and__(self, other):
        return _obj(self) & _unwrap(other)

    def __rand__(self, other):
        return _unwrap(other) & _obj(self)

    def __iand__(self, other):
        o = _obj(self)
        o &= _unwrap(other)
        return o

    def __or__(self, other):
        return _obj(self) | _unwrap(other)

    def __ror__(self, other):
        return _unwrap(other) | _obj(self)

    def __ior__(self, other):
        o = _obj(self)
        o |= _unwrap(other)
        return o

    def __xor__(self, other):
        return _obj(self) ^ _unwrap(other)

    def __rxor__(self, other):
        return _unwrap(other) ^ _obj(self)

    def __ixor__(self, other):
        o = _obj(self)
        o ^= _unwrap(other)
        return o

    def __matmul__(self, other):
        return _obj(self) @ _unwrap(other)

    def __rmatmul__(self, other):
        return _unwrap(other) @ _obj(self)

    def __imatmul__(self, other):
        o = _obj(self)
        o @= _unwrap(other)
        return o

    def __neg__(self):
        return -_obj(self)

    def __pos__(self):
        return +_obj(self)

    def __invert__(self):
        return ~_obj(self)


CallableProxyType.__module__ = "weakref"


def getweakrefcount(object, /):
    """Return the number of weak references to 'object'.

Counts the references that are still alive (not dropped)."""
    return _counts.get(id(object), 0)


def getweakrefs(object, /):
    """Return a list of all weak reference and proxy objects that refer to 'object'.

Always empty here: the module does not keep the references (that would pin
them and their referent forever), so it cannot hand them back."""
    return []


def proxy(object, callback=None, /):
    """Create a proxy object that weakly references 'object'.

'callback', if given, is called with a reference to the proxy when 'object'
is about to be finalized (never, here)."""
    _check_weakrefable(object)
    kind = CallableProxyType if callable(object) else ProxyType
    p = _new(kind)
    _setattr(p, "_o", object)
    _setattr(p, "_cb", callback)
    _incr(object)
    return p


_new = object.__new__
_setattr = object.__setattr__


def _remove_dead_weakref(dct, key, /):
    """Atomically remove key from dict if it points to a dead weakref.

References never die here, so this never removes anything."""
    if not isinstance(dct, dict):
        raise TypeError("_remove_dead_weakref() argument 'dict' must be dict, "
                        f"not {type(dct).__name__}")
