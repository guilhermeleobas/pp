"""Pure-Python _collections, executed by the pp VM (replaces the C module).

Semantics follow Modules/_collectionsmodule.c (deque, defaultdict,
_count_elements, _tuplegetter, the deque iterators) and Objects/odictobject.c
(OrderedDict and its odict_* views).

The deque stores its items in fixed-size blocks like CPython's (BLOCKLEN 64,
left/right indices), held in a Python list of blocks, so both ends and
indexing are O(1) amortized. Limitation: ``type(x).__name__`` of the classes
here is the short name, so messages formatted by the VM from a type name say
"deque" where CPython's static type says "collections.deque".
"""

import copyreg as _copyreg
import sys as _sys

__all__ = ["deque", "defaultdict", "OrderedDict", "_count_elements", "_tuplegetter",
           "_deque_iterator", "_deque_reverse_iterator"]

_GenericAlias = type(list[int])
_NOARG = object()
_MAXSIZE = _sys.maxsize
_dict_get = dict.get
_dict_setitem = dict.__setitem__
_repr_running = set()
try:
    _ANY_DICT = (dict, frozendict)
except NameError:
    _ANY_DICT = (dict,)
_INTERNAL_SLOTS = frozenset({
    "_deque__blocks", "_deque__lb", "_deque__rb", "_deque__n",
    "_deque__maxlen", "_deque__state", "__weakref__"})
_BLOCKLEN = 64
_CENTER = 31


def _index(value):
    try:
        return value.__index__()
    except AttributeError:
        raise TypeError(f"'{type(value).__name__}' object cannot be "
                        "interpreted as an integer") from None


def _slice_index(value):
    if value is None or not hasattr(type(value), "__index__"):
        raise TypeError("slice indices must be integers or have an "
                        "__index__ method")
    return value.__index__()


class deque:
    """A list-like sequence optimized for data accesses near its endpoints."""

    # Private state is name-mangled so subclass attributes cannot collide.
    __slots__ = ("__blocks", "__lb", "__rb", "__n", "__maxlen", "__state",
                 "__weakref__")
    __module__ = "collections"

    def __new__(cls, *args, **kwargs):
        self = object.__new__(cls)
        self.__maxlen = -1
        self.__state = 0
        self.__empty()
        return self

    def __init__(self, iterable=_NOARG, maxlen=None):
        ml = -1
        if maxlen is not None:
            if not isinstance(maxlen, int):
                raise TypeError("an integer is required")
            ml = maxlen
            if ml < 0:
                raise ValueError("maxlen must be non-negative")
        self.__maxlen = ml
        if self.__n:
            self.clear()
        if iterable is not _NOARG:
            self.extend(iterable)

    @property
    def maxlen(self):
        """maximum size of a deque or None if unbounded"""
        return None if self.__maxlen < 0 else self.__maxlen

    # -- block storage ----------------------------------------------------

    def __empty(self):
        self.__blocks = [[None] * _BLOCKLEN]
        self.__lb = _CENTER + 1
        self.__rb = _CENTER
        self.__n = 0

    def __items(self):
        blocks = self.__blocks
        lb = self.__lb
        rb = self.__rb
        if len(blocks) == 1:
            return blocks[0][lb:rb + 1]
        out = blocks[0][lb:]
        for blk in blocks[1:-1]:
            out += blk
        out += blocks[-1][:rb + 1]
        return out

    def __reset(self, items):
        n = len(items)
        if n == 0:
            self.__empty()
            return
        blocks = []
        for i in range(0, n, _BLOCKLEN):
            blk = items[i:i + _BLOCKLEN]
            if len(blk) < _BLOCKLEN:
                blk += [None] * (_BLOCKLEN - len(blk))
            blocks.append(blk)
        self.__blocks = blocks
        self.__lb = 0
        self.__rb = (n - 1) % _BLOCKLEN
        self.__n = n

    def __item(self, i):
        pos = self.__lb + i
        return self.__blocks[pos >> 6][pos & 63]

    def __popleft(self):
        blocks = self.__blocks
        lb = self.__lb
        item = blocks[0][lb]
        blocks[0][lb] = None
        self.__n -= 1
        self.__state += 1
        if self.__n == 0:
            self.__empty()
        elif lb == _BLOCKLEN - 1:
            del blocks[0]
            self.__lb = 0
        else:
            self.__lb = lb + 1
        return item

    # -- mutation ---------------------------------------------------------

    def append(self, x, /):
        """Add an element to the right side of the deque."""
        if self.__rb == _BLOCKLEN - 1:
            self.__blocks.append([None] * _BLOCKLEN)
            self.__rb = -1
        self.__rb += 1
        self.__blocks[-1][self.__rb] = x
        self.__n += 1
        self.__state += 1
        if 0 <= self.__maxlen < self.__n:
            self.__popleft()

    def appendleft(self, x, /):
        """Add an element to the left side of the deque."""
        if self.__lb == 0:
            self.__blocks.insert(0, [None] * _BLOCKLEN)
            self.__lb = _BLOCKLEN
        self.__lb -= 1
        self.__blocks[0][self.__lb] = x
        self.__n += 1
        self.__state += 1
        if 0 <= self.__maxlen < self.__n:
            self.pop()

    def pop(self):
        """Remove and return the rightmost element."""
        if not self.__n:
            raise IndexError("pop from an empty deque")
        blocks = self.__blocks
        rb = self.__rb
        item = blocks[-1][rb]
        blocks[-1][rb] = None
        self.__n -= 1
        self.__state += 1
        if self.__n == 0:
            self.__empty()
        elif rb == 0:
            blocks.pop()
            self.__rb = _BLOCKLEN - 1
        else:
            self.__rb = rb - 1
        return item

    def popleft(self):
        """Remove and return the leftmost element."""
        n = self.__n
        if not n:
            raise IndexError("pop from an empty deque")
        blocks = self.__blocks
        lb = self.__lb
        blk = blocks[0]
        item = blk[lb]
        blk[lb] = None
        self.__n = n - 1
        self.__state += 1
        if n == 1:
            self.__empty()
        elif lb == _BLOCKLEN - 1:
            del blocks[0]
            self.__lb = 0
        else:
            self.__lb = lb + 1
        return item

    def extend(self, iterable, /):
        """Extend the right side of the deque with elements from the iterable."""
        if iterable is self:
            iterable = self.__items()
        it = iter(iterable)
        if self.__maxlen == 0:
            for _ in it:
                pass
            return
        for item in it:
            self.append(item)

    def extendleft(self, iterable, /):
        """Extend the left side of the deque with elements from the iterable."""
        if iterable is self:
            iterable = self.__items()
        it = iter(iterable)
        if self.__maxlen == 0:
            for _ in it:
                pass
            return
        for item in it:
            self.appendleft(item)

    def clear(self):
        """Remove all elements from the deque."""
        self.__state += 1
        self.__empty()

    def rotate(self, n=1, /):
        """Rotate the deque n steps to the right.  If n is negative, rotate to the left."""
        n = _index(n)
        size = self.__n
        if size <= 1:
            return
        n %= size
        self.__state += 1
        if n:
            items = self.__items()
            self.__reset(items[-n:] + items[:-n])

    def reverse(self):
        """Reverse *IN PLACE*."""
        items = self.__items()
        items.reverse()
        self.__reset(items)

    def insert(self, index, value, /):
        """Insert value before index."""
        index = _index(index)
        if self.__maxlen == self.__n:
            raise IndexError("deque already at its maximum size")
        items = self.__items()
        items.insert(index, value)
        self.__state += 1
        self.__reset(items)

    def remove(self, value, /):
        """Remove first occurrence of value."""
        state = self.__state
        for i in range(self.__n):
            item = self.__item(i)
            cmp = bool(item is value or item == value)
            if self.__state != state:
                raise IndexError("deque mutated during iteration")
            if cmp:
                del self[i]
                return
        raise ValueError("deque.remove(x): x not in deque")

    # -- queries ----------------------------------------------------------

    def count(self, value, /):
        """Return number of occurrences of value."""
        state = self.__state
        count = 0
        for i in range(self.__n):
            item = self.__item(i)
            if item is value or item == value:
                count += 1
            if self.__state != state:
                raise RuntimeError("deque mutated during iteration")
        return count

    def index(self, value, start=0, stop=_MAXSIZE, /):
        """Return first index of value.

        Raises ValueError if the value is not present.
        """
        state = self.__state
        size = self.__n
        start = _slice_index(start)
        stop = _slice_index(stop)
        if start < 0:
            start = max(start + size, 0)
        if stop < 0:
            stop = max(stop + size, 0)
        if stop > size:
            stop = size
        if start > stop:
            start = stop
        for i in range(start, stop):
            item = self.__item(i)
            if item is value or item == value:
                return i
            if self.__state != state:
                raise RuntimeError("deque mutated during iteration")
        raise ValueError("deque.index(x): x not in deque")

    def __contains__(self, value):
        state = self.__state
        for i in range(self.__n):
            item = self.__item(i)
            if item is value or item == value:
                return True
            if self.__state != state:
                raise RuntimeError("deque mutated during iteration")
        return False

    def __len__(self):
        return self.__n

    # -- item access ------------------------------------------------------

    def __norm(self, i):
        if not hasattr(type(i), "__index__"):
            raise TypeError("sequence index must be integer, not "
                            f"'{type(i).__name__}'")
        i = i.__index__()
        if i < 0:
            i += self.__n
        if not 0 <= i < self.__n:
            raise IndexError("deque index out of range")
        return i

    def __getitem__(self, i):
        return self.__item(self.__norm(i))

    def __setitem__(self, i, value):
        pos = self.__lb + self.__norm(i)
        self.__blocks[pos >> 6][pos & 63] = value

    def __delitem__(self, i):
        i = self.__norm(i)
        items = self.__items()
        del items[i]
        self.__state += 1
        self.__reset(items)

    # -- copying / arithmetic --------------------------------------------

    def copy(self):
        """Return a shallow copy of a deque."""
        cls = type(self)
        if cls is deque:
            new = deque.__new__(deque)
            new.__maxlen = self.__maxlen
            new.__reset(self.__items())
            return new
        if self.__maxlen < 0:
            result = cls(self)
        else:
            result = cls(self, self.__maxlen)
        if not isinstance(result, deque):
            raise TypeError(f"{cls.__name__}() must return a deque, not "
                            f"{type(result).__name__}")
        return result

    __copy__ = copy

    def __add__(self, other):
        if not isinstance(other, deque):
            raise TypeError("can only concatenate deque (not "
                            f'"{_tp_name(type(other))}") to deque')
        new = self.copy()
        new.extend(other)
        return new

    def __iadd__(self, other):
        self.extend(other)
        return self

    def __mul__(self, n):
        if not hasattr(type(n), "__index__"):
            raise TypeError("can't multiply sequence by non-int of type "
                            f"'{_tp_name(type(n))}'")
        new = self.copy()
        new.__inplace_repeat(n.__index__())
        return new

    def __rmul__(self, n):
        # CPython's deque has sq_repeat only, so `x * deque` reports the
        # deque as the bad count.
        if not hasattr(type(n), "__index__"):
            raise TypeError("can't multiply sequence by non-int of type "
                            f"'{_tp_name(type(self))}'")
        return self.__mul__(n)

    def __imul__(self, n):
        self.__inplace_repeat(_index(n))
        return self

    def __inplace_repeat(self, n):
        size = self.__n
        if size == 0 or n == 1:
            return
        if n <= 0:
            self.clear()
            return
        if size > _MAXSIZE // n:
            raise MemoryError
        items = self.__items()
        if size == 1 and self.__maxlen >= 0 and n > self.__maxlen:
            n = self.__maxlen
        items = items * n
        if 0 <= self.__maxlen < len(items):
            items = items[len(items) - self.__maxlen:]
        self.__state += 1
        self.__reset(items)

    # -- comparison -------------------------------------------------------

    def __compare(self, other, op):
        if not isinstance(other, deque):
            return NotImplemented
        vs = self.__n
        ws = other.__n
        if op == "==":
            if self is other:
                return True
            if vs != ws:
                return False
        elif op == "!=":
            if self is other:
                return False
            if vs != ws:
                return True
        it1 = iter(self)
        it2 = iter(other)
        end = _NOARG
        while True:
            x = next(it1, end)
            y = next(it2, end)
            if x is end or y is end:
                break
            if not (x is y or x == y):
                if op == "==":
                    return False
                if op == "!=":
                    return True
                if op == "<":
                    return x < y
                if op == "<=":
                    return x <= y
                if op == ">":
                    return x > y
                return x >= y
        if op == "<":
            return y is not end
        if op == "<=":
            return x is end
        if op == "==":
            return x is y
        if op == "!=":
            return x is not y
        if op == ">":
            return x is not end
        return y is end

    def __eq__(self, other):
        return self.__compare(other, "==")

    def __ne__(self, other):
        return self.__compare(other, "!=")

    def __lt__(self, other):
        return self.__compare(other, "<")

    def __le__(self, other):
        return self.__compare(other, "<=")

    def __gt__(self, other):
        return self.__compare(other, ">")

    def __ge__(self, other):
        return self.__compare(other, ">=")

    __hash__ = None

    # -- iteration / protocol --------------------------------------------

    def __iter__(self):
        return _deque_iterator(self)

    def __reversed__(self):
        return _deque_reverse_iterator(self)

    def __reduce__(self):
        """Return state information for pickling."""
        try:
            state = self.__dict__ or None
        except AttributeError:
            state = None
        slots = {}
        for name in _copyreg._slotnames(type(self)):
            if name in _INTERNAL_SLOTS:
                continue
            try:
                slots[name] = getattr(self, name)
            except AttributeError:
                pass
        if slots:
            state = (state, slots)
        it = iter(self)
        if self.__maxlen < 0:
            return (type(self), (), state, it)
        return (type(self), ((), self.__maxlen), state, it)

    def __repr__(self):
        key = id(self)
        if key in _repr_running:
            return "[...]"
        _repr_running.add(key)
        try:
            aslist = list(self)
            name = type(self).__name__
            if self.__maxlen >= 0:
                return f"{name}({aslist!r}, maxlen={self.__maxlen})"
            return f"{name}({aslist!r})"
        finally:
            _repr_running.discard(key)

    def __dir__(self):
        return [n for n in object.__dir__(self) if not n.startswith("_deque__")]

    def __sizeof__(self):
        return object.__sizeof__(self) + 8 * _BLOCKLEN * len(self.__blocks)

    __class_getitem__ = classmethod(_GenericAlias)


_deque_item = deque._deque__item
_deque_len = deque.__len__
_deque_state = deque._deque__state


class _deque_iterator:
    __slots__ = ("_deque", "_state", "_counter", "_index")
    __module__ = "collections"

    def __new__(cls, deque_, index=0, /):
        if not isinstance(deque_, deque):
            raise TypeError("_deque_iterator() argument 1 must be "
                            f"collections.deque, not {type(deque_).__name__}")
        self = object.__new__(cls)
        self._deque = deque_
        self._state = _deque_state.__get__(deque_)
        self._counter = len(deque_)
        self._index = 0
        for _ in range(_index(index)):
            try:
                next(self)
            except StopIteration:
                break
        return self

    def __iter__(self):
        return self

    def __next__(self):
        dq = self._deque
        if _deque_state.__get__(dq) != self._state:
            self._counter = 0
            raise RuntimeError("deque mutated during iteration")
        if self._counter == 0:
            raise StopIteration
        item = _deque_item(dq, self._index)
        self._index += 1
        self._counter -= 1
        return item

    def __length_hint__(self):
        return self._counter

    def __reduce__(self):
        return (type(self), (self._deque, len(self._deque) - self._counter))


class _deque_reverse_iterator:
    __slots__ = ("_deque", "_state", "_counter", "_index")
    __module__ = "collections"

    def __new__(cls, deque_, index=0, /):
        if not isinstance(deque_, deque):
            raise TypeError("_deque_reverse_iterator() argument 1 must be "
                            f"collections.deque, not {type(deque_).__name__}")
        self = object.__new__(cls)
        self._deque = deque_
        self._state = _deque_state.__get__(deque_)
        self._counter = len(deque_)
        self._index = self._counter - 1
        for _ in range(_index(index)):
            try:
                next(self)
            except StopIteration:
                break
        return self

    def __iter__(self):
        return self

    def __next__(self):
        dq = self._deque
        if _deque_state.__get__(dq) != self._state:
            self._counter = 0
            raise RuntimeError("deque mutated during iteration")
        if self._counter == 0:
            raise StopIteration
        item = _deque_item(dq, self._index)
        self._index -= 1
        self._counter -= 1
        return item

    def __length_hint__(self):
        return self._counter

    def __reduce__(self):
        return (type(self), (self._deque, len(self._deque) - self._counter))


class defaultdict(dict):
    """defaultdict(default_factory=None, /, [...]) --> dict with default factory

    The default factory is called without arguments to produce
    a new value when a key is not present, in __getitem__ only.
    A defaultdict compares equal to a dict with the same items.
    All remaining arguments are treated the same as if they were
    passed to the dict constructor, including keyword arguments.
    """

    __slots__ = ("__factory",)
    __module__ = "collections"

    @property
    def default_factory(self):
        """Factory for default value called by __missing__()."""
        try:
            return self.__factory
        except AttributeError:
            return None

    @default_factory.setter
    def default_factory(self, value):
        self.__factory = value

    @default_factory.deleter
    def default_factory(self):
        try:
            del self.__factory
        except AttributeError:
            pass

    def __init__(self, /, *args, **kwargs):
        newdefault = None
        if args:
            newdefault = args[0]
            if newdefault is not None and not callable(newdefault):
                raise TypeError("first argument must be callable or None")
            args = args[1:]
        self.default_factory = newdefault
        dict.__init__(self, *args, **kwargs)

    def __missing__(self, key, /):
        """__missing__(key) # Called by __getitem__ for missing key; pseudo-code:
        if self.default_factory is None: raise KeyError((key,))
        self[key] = value = self.default_factory()
        return value
        """
        factory = self.default_factory
        if factory is None:
            raise KeyError(key)
        value = factory()
        return dict.setdefault(self, key, value)

    def _new(self, arg):
        return type(self)(self.default_factory, arg)

    def copy(self):
        """D.copy() -> a shallow copy of D."""
        return self._new(self)

    __copy__ = copy

    def __reduce__(self):
        args = () if self.default_factory is None else (self.default_factory,)
        return (type(self), args, None, None, iter(self.items()))

    def __repr__(self):
        baserepr = dict.__repr__(self)
        factory = self.default_factory
        if factory is None:
            defrepr = "None"
        else:
            key = id(factory)
            if key in _repr_running:
                defrepr = "..."
            else:
                _repr_running.add(key)
                try:
                    defrepr = repr(factory)
                finally:
                    _repr_running.discard(key)
        return f"{type(self).__name__}({defrepr}, {baserepr})"

    def __or__(self, other):
        if not isinstance(other, _ANY_DICT):
            return NotImplemented
        new = self._new(self)
        dict.update(new, other)
        return new

    def __ror__(self, other):
        if not isinstance(other, _ANY_DICT):
            return NotImplemented
        new = self._new(other)
        dict.update(new, self)
        return new

    __class_getitem__ = classmethod(_GenericAlias)


def _count_elements(mapping, iterable, /):
    """Count elements in the iterable, updating the mapping."""
    it = iter(iterable)
    cls = type(mapping)
    if (isinstance(mapping, dict)
            and getattr(cls, "get", None) is dict.get
            and getattr(cls, "__setitem__", None) is dict.__setitem__):
        missing = _NOARG
        for key in it:
            old = _dict_get(mapping, key, missing)
            if old is missing:
                _dict_setitem(mapping, key, 1)
            else:
                _dict_setitem(mapping, key, old + 1)
        return None
    bound_get = mapping.get
    zero = 0
    for key in it:
        old = bound_get(key, zero)
        if old is zero:
            new = 1
        else:
            new = old + 1
        mapping[key] = new
    return None


class _tuplegetter:
    """Descriptor returning item `index` of a tuple (used by namedtuple)."""

    __module__ = "collections"

    def __new__(cls, index, doc, /):
        self = object.__new__(cls)
        self._index = _index(index)
        self.__doc__ = doc
        return self

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if not isinstance(obj, tuple):
            raise TypeError(f"descriptor for index '{self._index}' for tuple "
                            f"subclasses doesn't apply to "
                            f"'{type(obj).__name__}' object")
        if not 0 <= self._index < len(obj):
            raise IndexError("tuple index out of range")
        return obj[self._index]

    def __set__(self, obj, value):
        raise AttributeError("can't set attribute")

    def __delete__(self, obj):
        raise AttributeError("can't delete attribute")

    def __reduce__(self):
        return (type(self), (self._index, self.__doc__))

    def __repr__(self):
        return f"{type(self).__name__}({self._index}, {self.__doc__!r})"


def _tp_name(cls):
    """tp_name of the static CPython types defined here."""
    if cls in (deque, defaultdict, OrderedDict):
        return "collections." + cls.__name__
    return cls.__name__



# ---------------------------------------------------------------------------
# OrderedDict (Objects/odictobject.c)
# ---------------------------------------------------------------------------

import _collections_abc
from _weakref import proxy as _proxy
from reprlib import recursive_repr as _recursive_repr

# The views are registered as KeysView & co. rather than subclassing them, so
# they carry no `_mapping` slot (pprint treats views that have one as abc views).
_Set = _collections_abc.Set
_Collection = _collections_abc.Collection
_dict_view_types = {
    "keys": type({}.keys()),
    "values": type({}.values()),
    "items": type({}.items()),
}


class _odict_view_repr:
    """Class-level __repr__ is the dict view's, as C's odict views inherit it.

    pprint dispatches on ``type(view).__repr__``; instances still get the
    odict_* repr.
    """

    def __init__(self, kind):
        self.kind = kind

    def __get__(self, obj, owner=None):
        if obj is None:
            return _dict_view_types[self.kind].__repr__
        return lambda: f"{type(obj).__name__}({list(obj)!r})"


class odict_keys(_Set):
    __slots__ = ("_od",)
    __module__ = "builtins"
    __repr__ = _odict_view_repr("keys")

    def __init__(self, od):
        self._od = od

    @classmethod
    def _from_iterable(cls, it):
        return set(it)

    @property
    def mapping(self):
        return type(type.__dict__)(self._od)

    def __len__(self):
        return len(self._od)

    def __iter__(self):
        return _odict_iterator(self._od, 1)

    def __reversed__(self):
        return _odict_iterator(self._od, 5)

    def __contains__(self, key):
        return key in self._od


class odict_values(_Collection):
    __slots__ = ("_od",)
    __module__ = "builtins"
    __repr__ = _odict_view_repr("values")

    def __init__(self, od):
        self._od = od

    @classmethod
    def _from_iterable(cls, it):
        return set(it)

    @property
    def mapping(self):
        return type(type.__dict__)(self._od)

    def __len__(self):
        return len(self._od)

    def __iter__(self):
        return _odict_iterator(self._od, 2)

    def __reversed__(self):
        return _odict_iterator(self._od, 6)

    def __contains__(self, value):
        for v in _odict_iterator(self._od, 2):
            if v is value or v == value:
                return True
        return False


class odict_items(_Set):
    __slots__ = ("_od",)
    __module__ = "builtins"
    __repr__ = _odict_view_repr("items")

    def __init__(self, od):
        self._od = od

    @classmethod
    def _from_iterable(cls, it):
        return set(it)

    @property
    def mapping(self):
        return type(type.__dict__)(self._od)

    def __len__(self):
        return len(self._od)

    def __iter__(self):
        return _odict_iterator(self._od, 3)

    def __reversed__(self):
        return _odict_iterator(self._od, 7)

    def __contains__(self, item):
        key, value = item
        try:
            v = self._od[key]
        except KeyError:
            return False
        return v is value or v == value


_collections_abc.KeysView.register(odict_keys)
_collections_abc.ValuesView.register(odict_values)
_collections_abc.ItemsView.register(odict_items)


class _odict_iterator:
    """odict_iterator: state is recorded when the iterator is created.

    kind bits as in odictobject.c: 1 keys, 2 values, 3 items (0 means keys),
    4 reversed.
    """

    __slots__ = ("_od", "_state", "_size", "_curr", "_kind")
    __module__ = "builtins"
    __name__ = "odict_iterator"

    def __init__(self, od, kind):
        self._od = od
        self._state = _odict_state.__get__(od)
        self._size = len(od)
        self._kind = kind
        root = _od_root.__get__(od)
        self._curr = root.prev if kind & 4 else root.next

    def __iter__(self):
        return self

    def __next__(self):
        od = self._od
        if od is None:
            raise StopIteration
        curr = self._curr
        if curr is _od_root.__get__(od):
            self._od = None
            raise StopIteration
        if _odict_state.__get__(od) != self._state:
            self._od = None
            raise RuntimeError("OrderedDict mutated during iteration")
        if len(od) != self._size:
            self._size = -1
            raise RuntimeError("OrderedDict changed size during iteration")
        key = curr.key
        self._curr = curr.prev if self._kind & 4 else curr.next
        what = self._kind & 3
        if what == 2:
            return dict.__getitem__(od, key)
        if what == 3:
            return (key, dict.__getitem__(od, key))
        return key

    def __length_hint__(self):
        od = self._od
        return 0 if od is None else self._size

    def __reduce__(self):
        od = self._od
        items = list(self) if od is not None else []
        return iter, (items,)


class _Link:
    __slots__ = ("prev", "next", "key", "__weakref__")


class OrderedDict(dict):
    "Dictionary that remembers insertion order"

    __module__ = "collections"
    # Internal state lives in slots so that vars(od) stays empty; subclasses
    # still get an instance __dict__ through the explicit "__dict__" slot.
    __slots__ = ("__hardroot", "__root", "__map", "__state", "__dict__",
                 "__weakref__")

    def __new__(cls, /, *args, **kwds):
        "Create the ordered dict object and set up the underlying structures."
        self = dict.__new__(cls)
        self.__hardroot = _Link()
        self.__root = root = _proxy(self.__hardroot)
        root.prev = root.next = root
        self.__map = {}
        self.__state = 0
        return self

    def __init__(self, other=(), /, **kwds):
        """Initialize an ordered dictionary.  The signature is the same as
        regular dictionaries.  Keyword argument order is preserved.
        """
        self.__update(other, **kwds)

    def __setitem__(self, key, value,
                    dict_setitem=dict.__setitem__, proxy=_proxy, Link=_Link):
        "od.__setitem__(i, y) <==> od[i]=y"
        if key not in self:
            self.__map[key] = link = Link()
            root = self.__root
            last = root.prev
            link.prev, link.next, link.key = last, root, key
            last.next = link
            root.prev = proxy(link)
            self.__state += 1
        dict_setitem(self, key, value)

    def __delitem__(self, key, dict_delitem=dict.__delitem__):
        "od.__delitem__(y) <==> del od[y]"
        dict_delitem(self, key)
        link = self.__map.pop(key)
        link_prev = link.prev
        link_next = link.next
        link_prev.next = link_next
        link_next.prev = link_prev
        link.prev = None
        link.next = None
        self.__state += 1

    def __iter__(self):
        "od.__iter__() <==> iter(od)"
        return _odict_iterator(self, 0)

    def __reversed__(self):
        "od.__reversed__() <==> reversed(od)"
        return _odict_iterator(self, 4)

    def clear(self):
        "od.clear() -> None.  Remove all items from od."
        root = self.__root
        root.prev = root.next = root
        self.__map.clear()
        self.__state += 1
        dict.clear(self)

    def popitem(self, last=True):
        """Remove and return a (key, value) pair from the dictionary.

        Pairs are returned in LIFO order if last is true or FIFO order if false.
        """
        if not self:
            raise KeyError("dictionary is empty")
        root = self.__root
        if last:
            link = root.prev
            link_prev = link.prev
            link_prev.next = root
            root.prev = link_prev
        else:
            link = root.next
            link_next = link.next
            root.next = link_next
            link_next.prev = root
        key = link.key
        del self.__map[key]
        self.__state += 1
        value = dict.pop(self, key)
        return key, value

    def move_to_end(self, key, last=True):
        """Move an existing element to the end (or beginning if last is false).

        Raise KeyError if the element does not exist.
        """
        link = self.__map[key]
        link_prev = link.prev
        link_next = link.next
        soft_link = link_next.prev
        link_prev.next = link_next
        link_next.prev = link_prev
        root = self.__root
        if last:
            last = root.prev
            link.prev = last
            link.next = root
            root.prev = soft_link
            last.next = link
        else:
            first = root.next
            link.prev = root
            link.next = first
            first.prev = soft_link
            root.next = link
        self.__state += 1

    def __dir__(self):
        return [n for n in object.__dir__(self)
                if not n.startswith("_OrderedDict__")]

    def __sizeof__(self):
        # Fixed base plus the dict's own growth, od_fast_nodes (8 bytes per
        # hash slot) and one 32-byte node per entry, as in odictobject.c.
        n = len(self)
        size = 112 + dict.__sizeof__(dict(self)) - dict.__sizeof__({})
        if n:
            slots = 8
            while 2 * slots // 3 < n:
                slots *= 2
            size += 8 * slots + 32 * n
        return size

    update = __update = _collections_abc.MutableMapping.update

    def keys(self):
        "D.keys() -> a set-like object providing a view on D's keys"
        return odict_keys(self)

    def items(self):
        "D.items() -> a set-like object providing a view on D's items"
        return odict_items(self)

    def values(self):
        "D.values() -> an object providing a view on D's values"
        return odict_values(self)

    __ne__ = _collections_abc.MutableMapping.__ne__

    __marker = object()

    def pop(self, key, default=__marker):
        """od.pop(k[,d]) -> v, remove specified key and return the corresponding
        value.  If key is not found, d is returned if given, otherwise KeyError
        is raised.
        """
        marker = self.__marker
        result = dict.pop(self, key, marker)
        if result is not marker:
            link = self.__map.pop(key)
            link_prev = link.prev
            link_next = link.next
            link_prev.next = link_next
            link_next.prev = link_prev
            link.prev = None
            link.next = None
            self.__state += 1
            return result
        if default is marker:
            raise KeyError(key)
        return default

    def setdefault(self, key, default=None):
        """Insert key with a value of default if key is not in the dictionary.

        Return the value for key if key is in the dictionary, else default.
        """
        if key in self:
            return self[key]
        self[key] = default
        return default

    @_recursive_repr()
    def __repr__(self):
        "od.__repr__() <==> repr(od)"
        if not self:
            return "%s()" % (self.__class__.__name__,)
        return "%s(%r)" % (self.__class__.__name__, dict(self.items()))

    def __reduce__(self):
        "Return state information for pickling"
        state = self.__dict__.copy() or None
        slots = {}
        for name in _copyreg._slotnames(type(self)):
            if name.startswith("_OrderedDict__"):
                continue
            try:
                slots[name] = getattr(self, name)
            except AttributeError:
                pass
        if slots:
            state = (state, slots)
        return self.__class__, (), state, None, iter(self.items())

    def copy(self):
        "od.copy() -> a shallow copy of od"
        return self.__class__(self)

    @classmethod
    def fromkeys(cls, iterable, value=None):
        """Create a new ordered dictionary with keys from iterable and values set to value."""
        self = cls()
        for key in iterable:
            self[key] = value
        return self

    def __eq__(self, other):
        """od.__eq__(y) <==> od==y.  Comparison to another OD is order-sensitive
        while comparison to a regular mapping is order-insensitive.
        """
        if isinstance(other, OrderedDict):
            return dict.__eq__(self, other) and all(
                a is b or a == b for a, b in zip(self, other))
        return dict.__eq__(self, other)

    __hash__ = None

    def __ior__(self, other):
        self.update(other)
        return self

    def __or__(self, other):
        if not isinstance(other, _ANY_DICT):
            return NotImplemented
        new = self.__class__(self)
        new.update(other)
        return new

    def __ror__(self, other):
        if not isinstance(other, _ANY_DICT):
            return NotImplemented
        new = self.__class__(other)
        new.update(self)
        return new


_od_root = OrderedDict._OrderedDict__root
_odict_state = OrderedDict._OrderedDict__state
