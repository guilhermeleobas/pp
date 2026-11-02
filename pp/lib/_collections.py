"""Pure-Python _collections, executed by the pp VM (replaces the C module).

Semantics follow Modules/_collectionsmodule.c: deque, defaultdict,
_count_elements, _tuplegetter and the deque iterators. OrderedDict is left
to the Python implementation in collections/__init__.py.
"""

import copyreg as _copyreg
import sys as _sys

__all__ = ["deque", "defaultdict", "_count_elements", "_tuplegetter",
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
_INTERNAL_SLOTS = frozenset({"_d", "_maxlen", "_state", "__weakref__"})


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

    __slots__ = ("_d", "_maxlen", "_state", "__weakref__")
    __module__ = "collections"

    def __new__(cls, *args, **kwargs):
        self = object.__new__(cls)
        self._d = []
        self._maxlen = -1
        self._state = 0
        return self

    def __init__(self, iterable=_NOARG, maxlen=None):
        ml = -1
        if maxlen is not None:
            if not isinstance(maxlen, int):
                raise TypeError("an integer is required")
            ml = maxlen
            if ml < 0:
                raise ValueError("maxlen must be non-negative")
        self._maxlen = ml
        if self._d:
            self.clear()
        if iterable is not _NOARG:
            self.extend(iterable)

    @property
    def maxlen(self):
        """maximum size of a deque or None if unbounded"""
        return None if self._maxlen < 0 else self._maxlen

    # -- mutation ---------------------------------------------------------

    def append(self, x, /):
        """Add an element to the right side of the deque."""
        d = self._d
        d.append(x)
        self._state += 1
        if 0 <= self._maxlen < len(d):
            del d[0]

    def appendleft(self, x, /):
        """Add an element to the left side of the deque."""
        d = self._d
        d.insert(0, x)
        self._state += 1
        if 0 <= self._maxlen < len(d):
            d.pop()

    def pop(self):
        """Remove and return the rightmost element."""
        if not self._d:
            raise IndexError("pop from an empty deque")
        self._state += 1
        return self._d.pop()

    def popleft(self):
        """Remove and return the leftmost element."""
        if not self._d:
            raise IndexError("pop from an empty deque")
        self._state += 1
        return self._d.pop(0)

    def extend(self, iterable, /):
        """Extend the right side of the deque with elements from the iterable."""
        if iterable is self:
            iterable = list(self._d)
        it = iter(iterable)
        if self._maxlen == 0:
            for _ in it:
                pass
            return
        for item in it:
            self.append(item)

    def extendleft(self, iterable, /):
        """Extend the left side of the deque with elements from the iterable."""
        if iterable is self:
            iterable = list(self._d)
        it = iter(iterable)
        if self._maxlen == 0:
            for _ in it:
                pass
            return
        for item in it:
            self.appendleft(item)

    def clear(self):
        """Remove all elements from the deque."""
        self._state += 1
        self._d.clear()

    def rotate(self, n=1, /):
        """Rotate the deque n steps to the right.  If n is negative, rotate to the left."""
        n = _index(n)
        d = self._d
        size = len(d)
        if size <= 1:
            return
        n %= size
        self._state += 1
        if n:
            d[:] = d[-n:] + d[:-n]

    def reverse(self):
        """Reverse *IN PLACE*."""
        self._d.reverse()

    def insert(self, index, value, /):
        """Insert value before index."""
        index = _index(index)
        d = self._d
        if self._maxlen == len(d):
            raise IndexError("deque already at its maximum size")
        d.insert(index, value)
        self._state += 1

    def remove(self, value, /):
        """Remove first occurrence of value."""
        d = self._d
        state = self._state
        n = len(d)
        for i in range(n):
            cmp = d[i] == value
            if cmp:
                cmp = bool(cmp)
            if self._state != state:
                raise IndexError("deque mutated during iteration")
            if cmp:
                del self[i]
                return
        raise ValueError("deque.remove(x): x not in deque")

    # -- queries ----------------------------------------------------------

    def count(self, value, /):
        """Return number of occurrences of value."""
        d = self._d
        state = self._state
        count = 0
        for i in range(len(d)):
            item = d[i]
            if item is value or item == value:
                count += 1
            if self._state != state:
                raise RuntimeError("deque mutated during iteration")
        return count

    def index(self, value, start=0, stop=_MAXSIZE, /):
        """Return first index of value.

        Raises ValueError if the value is not present.
        """
        d = self._d
        state = self._state
        size = len(d)
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
            item = d[i]
            if item is value or item == value:
                return i
            if self._state != state:
                raise RuntimeError("deque mutated during iteration")
        raise ValueError("deque.index(x): x not in deque")

    def __contains__(self, value):
        d = self._d
        state = self._state
        for i in range(len(d)):
            item = d[i]
            if item is value or item == value:
                return True
            if self._state != state:
                raise RuntimeError("deque mutated during iteration")
        return False

    def __len__(self):
        return len(self._d)

    # -- item access ------------------------------------------------------

    def _norm(self, i):
        if not hasattr(type(i), "__index__"):
            raise TypeError("sequence index must be integer, not "
                            f"'{type(i).__name__}'")
        i = i.__index__()
        size = len(self._d)
        if i < 0:
            i += size
        if not 0 <= i < size:
            raise IndexError("deque index out of range")
        return i

    def __getitem__(self, i):
        return self._d[self._norm(i)]

    def __setitem__(self, i, value):
        self._d[self._norm(i)] = value

    def __delitem__(self, i):
        i = self._norm(i)
        self._state += 1
        del self._d[i]

    # -- copying / arithmetic --------------------------------------------

    def copy(self):
        """Return a shallow copy of a deque."""
        cls = type(self)
        if cls is deque:
            new = deque.__new__(deque)
            new._d = list(self._d)
            new._maxlen = self._maxlen
            return new
        if self._maxlen < 0:
            result = cls(self)
        else:
            result = cls(self, self._maxlen)
        if not isinstance(result, deque):
            raise TypeError(f"{cls.__name__}() must return a deque, not "
                            f"{type(result).__name__}")
        return result

    __copy__ = copy

    def __add__(self, other):
        if not isinstance(other, deque):
            raise TypeError("can only concatenate deque (not "
                            f'"{type(other).__name__}") to deque')
        new = self.copy()
        new.extend(other)
        return new

    def __iadd__(self, other):
        self.extend(other)
        return self

    def __mul__(self, n):
        n = _index(n)
        new = self.copy()
        new._inplace_repeat(n)
        return new

    __rmul__ = __mul__

    def __imul__(self, n):
        n = _index(n)
        self._inplace_repeat(n)
        return self

    def _inplace_repeat(self, n):
        d = self._d
        size = len(d)
        if size == 0 or n == 1:
            return
        if n <= 0:
            self.clear()
            return
        if size == 1:
            if 0 <= self._maxlen < n:
                n = self._maxlen
            self._state += 1
            d.extend(d * (n - 1))
            return
        if size > _MAXSIZE // n:
            raise MemoryError
        seq = list(d)
        if self._maxlen >= 0 and n * size > self._maxlen:
            n = (self._maxlen + size - 1) // size
        for _ in range(n - 1):
            self.extend(seq)

    # -- comparison -------------------------------------------------------

    def _compare(self, other, op):
        if not isinstance(other, deque):
            return NotImplemented
        vs = len(self._d)
        ws = len(other._d)
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
        _end = _NOARG
        while True:
            x = next(it1, _end)
            y = next(it2, _end)
            if x is _end or y is _end:
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
            return y is not _end
        if op == "<=":
            return x is _end
        if op == "==":
            return x is y
        if op == "!=":
            return x is not y
        if op == ">":
            return x is not _end
        return y is _end

    def __eq__(self, other):
        return self._compare(other, "==")

    def __ne__(self, other):
        return self._compare(other, "!=")

    def __lt__(self, other):
        return self._compare(other, "<")

    def __le__(self, other):
        return self._compare(other, "<=")

    def __gt__(self, other):
        return self._compare(other, ">")

    def __ge__(self, other):
        return self._compare(other, ">=")

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
        if self._maxlen < 0:
            return (type(self), (), state, it)
        return (type(self), ((), self._maxlen), state, it)

    def __repr__(self):
        key = id(self)
        if key in _repr_running:
            return "[...]"
        _repr_running.add(key)
        try:
            aslist = list(self)
            name = type(self).__name__
            if self._maxlen >= 0:
                return f"{name}({aslist!r}, maxlen={self._maxlen})"
            return f"{name}({aslist!r})"
        finally:
            _repr_running.discard(key)

    def __sizeof__(self):
        return object.__sizeof__(self) + 8 * len(self._d)

    __class_getitem__ = classmethod(_GenericAlias)


class _deque_iterator:
    __slots__ = ("_deque", "_state", "_counter", "_index")
    __module__ = "collections"

    def __new__(cls, deque_, index=0, /):
        if not isinstance(deque_, deque):
            raise TypeError("_deque_iterator() argument 1 must be "
                            f"collections.deque, not {type(deque_).__name__}")
        self = object.__new__(cls)
        self._deque = deque_
        self._state = deque_._state
        self._counter = len(deque_._d)
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
        if dq._state != self._state:
            self._counter = 0
            raise RuntimeError("deque mutated during iteration")
        if self._counter == 0:
            raise StopIteration
        item = dq._d[self._index]
        self._index += 1
        self._counter -= 1
        return item

    def __length_hint__(self):
        return self._counter

    def __reduce__(self):
        return (type(self), (self._deque, len(self._deque._d) - self._counter))


class _deque_reverse_iterator:
    __slots__ = ("_deque", "_state", "_counter", "_index")
    __module__ = "collections"

    def __new__(cls, deque_, index=0, /):
        if not isinstance(deque_, deque):
            raise TypeError("_deque_reverse_iterator() argument 1 must be "
                            f"collections.deque, not {type(deque_).__name__}")
        self = object.__new__(cls)
        self._deque = deque_
        self._state = deque_._state
        self._counter = len(deque_._d)
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
        if dq._state != self._state:
            self._counter = 0
            raise RuntimeError("deque mutated during iteration")
        if self._counter == 0:
            raise StopIteration
        item = dq._d[self._index]
        self._index -= 1
        self._counter -= 1
        return item

    def __length_hint__(self):
        return self._counter

    def __reduce__(self):
        return (type(self), (self._deque, len(self._deque._d) - self._counter))


class defaultdict(dict):
    """defaultdict(default_factory=None, /, [...]) --> dict with default factory

    The default factory is called without arguments to produce
    a new value when a key is not present, in __getitem__ only.
    A defaultdict compares equal to a dict with the same items.
    All remaining arguments are treated the same as if they were
    passed to the dict constructor, including keyword arguments.
    """

    __slots__ = ("_factory",)
    __module__ = "collections"

    @property
    def default_factory(self):
        """Factory for default value called by __missing__()."""
        try:
            return self._factory
        except AttributeError:
            return None

    @default_factory.setter
    def default_factory(self, value):
        self._factory = value

    @default_factory.deleter
    def default_factory(self):
        try:
            del self._factory
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
