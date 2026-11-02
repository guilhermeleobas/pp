"""Pure-Python itertools, executed by the pp VM (replaces the C module).

Semantics follow Modules/itertoolsmodule.c and the "roughly equivalent"
recipes in the itertools documentation.
"""

import sys as _sys

__all__ = [
    "accumulate", "batched", "chain", "combinations", "combinations_with_replacement",
    "compress", "count", "cycle", "dropwhile", "filterfalse", "groupby", "islice",
    "pairwise", "permutations", "product", "repeat", "starmap", "takewhile", "tee",
    "zip_longest",
]

_GenericAlias = type(list[int])
_marker = object()


def _index(value, what):
    try:
        return value.__index__()
    except AttributeError:
        raise TypeError(f"'{type(value).__name__}' object cannot be interpreted "
                        "as an integer") from None


class _Iter:
    """Base: wraps a VM generator holding the iteration state."""
    __slots__ = ("_it",)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def __reduce__(self):
        raise TypeError(f"cannot pickle '{type(self).__name__}' object")


def _new(cls, gen):
    self = object.__new__(cls)
    self._it = gen
    return self


def _no_kwargs(name, kwargs):
    if kwargs:
        raise TypeError(f"{name}() takes no keyword arguments")


# --- infinite iterators ---

class count(_Iter):
    __slots__ = ("_n", "_step")

    def __new__(cls, start=0, step=1):
        for v, what in ((start, "start"), (step, "step")):
            if not isinstance(v, (int, float, complex)) and not hasattr(type(v), "__add__"):
                raise TypeError("a number is required")
        self = object.__new__(cls)
        self._n = start
        self._step = step
        return self

    def __next__(self):
        n = self._n
        self._n = n + self._step
        return n

    def __repr__(self):
        name = type(self).__name__
        if isinstance(self._step, int) and self._step == 1:
            return f"{name}({self._n!r})"
        return f"{name}({self._n!r}, {self._step!r})"


def _cycle_gen(iterable):
    saved = []
    for element in iterable:
        yield element
        saved.append(element)
    if not saved:
        return
    while True:
        for element in saved:
            yield element


class cycle(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, /):
        return _new(cls, _cycle_gen(iter(iterable)))


class repeat(_Iter):
    __slots__ = ("_obj", "_times")

    def __new__(cls, object, times=None):
        self = _new(cls, None)
        self._obj = object
        if times is not None:
            times = _index(times, "times")
            if times < 0:
                times = 0
        self._times = times
        return self

    def __next__(self):
        if self._times is None:
            return self._obj
        if self._times > 0:
            self._times -= 1
            return self._obj
        raise StopIteration

    def __length_hint__(self):
        if self._times is None:
            raise TypeError("len() of unsized object")
        return self._times

    def __repr__(self):
        if self._times is None:
            return f"{type(self).__name__}({self._obj!r})"
        return f"{type(self).__name__}({self._obj!r}, {self._times})"


# --- iterators terminating on the shortest input sequence ---

def _accumulate_gen(it, func, initial):
    total = initial
    if initial is None:
        try:
            total = next(it)
        except StopIteration:
            return
    yield total
    if func is None:
        for element in it:
            total = total + element
            yield total
    else:
        for element in it:
            total = func(total, element)
            yield total


class accumulate(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, func=None, *, initial=None):
        return _new(cls, _accumulate_gen(iter(iterable), func, initial))


def _batched_gen(it, n, strict):
    while True:
        batch = []
        for _ in range(n):
            try:
                batch.append(next(it))
            except StopIteration:
                break
        if not batch:
            return
        if strict and len(batch) != n:
            raise ValueError("batched(): incomplete batch")
        yield tuple(batch)


class batched(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, n, *, strict=False):
        n = _index(n, "n")
        if n < 1:
            raise ValueError("n must be at least one")
        return _new(cls, _batched_gen(iter(iterable), n, strict))


def _chain_gen(iterables):
    for it in iterables:
        yield from it


class chain(_Iter):
    __slots__ = ()

    def __new__(cls, *iterables, **kwargs):
        _no_kwargs("chain", kwargs)
        return _new(cls, _chain_gen(iterables))

    @classmethod
    def from_iterable(cls, iterable, /):
        return _new(cls, _chain_gen(iter(iterable)))

    __class_getitem__ = classmethod(_GenericAlias)


def _compress_gen(data, selectors):
    for d, s in zip(data, selectors):
        if s:
            yield d


class compress(_Iter):
    __slots__ = ()

    def __new__(cls, data, selectors):
        return _new(cls, _compress_gen(iter(data), iter(selectors)))


def _dropwhile_gen(predicate, it):
    for x in it:
        if not predicate(x):
            yield x
            break
    yield from it


class dropwhile(_Iter):
    __slots__ = ()

    def __new__(cls, predicate, iterable, /):
        return _new(cls, _dropwhile_gen(predicate, iter(iterable)))


def _takewhile_gen(predicate, it):
    for x in it:
        if predicate(x):
            yield x
        else:
            break


class takewhile(_Iter):
    __slots__ = ()

    def __new__(cls, predicate, iterable, /):
        return _new(cls, _takewhile_gen(predicate, iter(iterable)))


def _filterfalse_gen(predicate, it):
    if predicate is None:
        predicate = bool
    for x in it:
        if not predicate(x):
            yield x


class filterfalse(_Iter):
    __slots__ = ()

    def __new__(cls, function, iterable, /):
        return _new(cls, _filterfalse_gen(function, iter(iterable)))


class groupby(_Iter):
    __slots__ = ("_keyfunc", "_iter", "_tgtkey", "_currkey", "_currvalue", "_id")

    def __new__(cls, iterable, key=None):
        self = _new(cls, None)
        self._keyfunc = key
        self._iter = iter(iterable)
        self._tgtkey = self._currkey = self._currvalue = _marker
        self._id = object()
        return self

    def _step(self):
        self._currvalue = next(self._iter)
        v = self._currvalue
        self._currkey = v if self._keyfunc is None else self._keyfunc(v)

    def __next__(self):
        self._id = object()
        if self._currvalue is not _marker:
            while self._currkey == self._tgtkey:
                self._step()
        else:
            self._step()
        self._tgtkey = self._currkey
        return (self._currkey, _grouper(self, self._tgtkey))


class _grouper:
    __slots__ = ("_parent", "_tgtkey", "_id")

    def __init__(self, parent, tgtkey):
        self._parent = parent
        self._tgtkey = tgtkey
        self._id = parent._id

    def __iter__(self):
        return self

    def __next__(self):
        parent = self._parent
        if parent._id is not self._id:
            raise StopIteration
        if parent._currvalue is _marker:
            parent._step()
        if not (self._tgtkey == parent._currkey):
            raise StopIteration
        r = parent._currvalue
        parent._currvalue = _marker
        return r


def _islice_arg(value, name):
    if value is None:
        return None
    try:
        v = value.__index__()
    except AttributeError:
        v = -1
    if v < 0 or v > _sys.maxsize:
        if name == "start":
            raise ValueError("Indices for islice() must be None or an integer: "
                             "0 <= x <= sys.maxsize.")
        raise ValueError("Stop argument for islice() must be None or an integer: "
                         "0 <= x <= sys.maxsize.")
    return v


def _islice_gen(it, start, stop, step):
    indices = count() if stop is None else range(max(start, stop))
    next_i = start
    for i, element in zip(indices, it):
        if i == next_i:
            yield element
            next_i += step


class islice(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, *args):
        if not 1 <= len(args) <= 3:
            if not args:
                raise TypeError("islice expected at least 2 arguments, got 1")
            raise TypeError(f"islice expected at most 4 arguments, got {len(args) + 1}")
        if len(args) == 1:
            start, stop, step = None, args[0], None
        else:
            start, stop = args[0], args[1]
            step = args[2] if len(args) == 3 else None
        stop = _islice_arg(stop, "stop")
        start = _islice_arg(start, "start")
        if start is None:
            start = 0
        if step is None:
            step = 1
        else:
            try:
                step = step.__index__()
            except AttributeError:
                step = 0
            if step <= 0:
                raise ValueError("Step for islice() must be a positive integer or None.")
        return _new(cls, _islice_gen(iter(iterable), start, stop, step))


def _pairwise_gen(it):
    try:
        a = next(it)
    except StopIteration:
        return
    for b in it:
        yield a, b
        a = b


class pairwise(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, /):
        return _new(cls, _pairwise_gen(iter(iterable)))


def _starmap_gen(function, it):
    for args in it:
        yield function(*args)


class starmap(_Iter):
    __slots__ = ()

    def __new__(cls, function, iterable, /):
        return _new(cls, _starmap_gen(function, iter(iterable)))


def _zip_longest_gen(iterators, fillvalue):
    num_active = len(iterators)
    if not num_active:
        return
    iterators = list(iterators)
    while True:
        values = []
        for i, it in enumerate(iterators):
            try:
                value = next(it)
            except StopIteration:
                num_active -= 1
                if not num_active:
                    return
                iterators[i] = repeat(fillvalue)
                value = fillvalue
            values.append(value)
        yield tuple(values)


class zip_longest(_Iter):
    __slots__ = ()

    def __new__(cls, *iterables, fillvalue=None):
        return _new(cls, _zip_longest_gen([iter(it) for it in iterables], fillvalue))


# --- combinatoric iterators ---

def _product_gen(pools):
    result = [[]]
    for pool in pools:
        result = [x + [y] for x in result for y in pool]
    for prod in result:
        yield tuple(prod)


class product(_Iter):
    __slots__ = ()

    def __new__(cls, *iterables, repeat=1):
        repeat = _index(repeat, "repeat")
        if repeat < 0:
            raise ValueError("repeat argument cannot be negative")
        pools = [tuple(pool) for pool in iterables] * repeat
        return _new(cls, _product_gen(pools))


def _permutations_gen(pool, r):
    n = len(pool)
    if r > n:
        return
    indices = list(range(n))
    cycles = list(range(n, n - r, -1))
    yield tuple(pool[i] for i in indices[:r])
    while n:
        for i in reversed(range(r)):
            cycles[i] -= 1
            if cycles[i] == 0:
                indices[i:] = indices[i + 1:] + indices[i:i + 1]
                cycles[i] = n - i
            else:
                j = cycles[i]
                indices[i], indices[-j] = indices[-j], indices[i]
                yield tuple(pool[i] for i in indices[:r])
                break
        else:
            return


class permutations(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, r=None):
        pool = tuple(iterable)
        if r is None:
            r = len(pool)
        else:
            r = _index(r, "r")
            if r < 0:
                raise ValueError("r must be non-negative")
        return _new(cls, _permutations_gen(pool, r))


def _combinations_gen(pool, r):
    n = len(pool)
    if r > n:
        return
    indices = list(range(r))
    yield tuple(pool[i] for i in indices)
    while True:
        for i in reversed(range(r)):
            if indices[i] != i + n - r:
                break
        else:
            return
        indices[i] += 1
        for j in range(i + 1, r):
            indices[j] = indices[j - 1] + 1
        yield tuple(pool[i] for i in indices)


class combinations(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, r):
        r = _index(r, "r")
        if r < 0:
            raise ValueError("r must be non-negative")
        return _new(cls, _combinations_gen(tuple(iterable), r))


def _cwr_gen(pool, r):
    n = len(pool)
    if not n and r:
        return
    indices = [0] * r
    yield tuple(pool[i] for i in indices)
    while True:
        for i in reversed(range(r)):
            if indices[i] != n - 1:
                break
        else:
            return
        indices[i:] = [indices[i] + 1] * (r - i)
        yield tuple(pool[i] for i in indices)


class combinations_with_replacement(_Iter):
    __slots__ = ()

    def __new__(cls, iterable, r):
        r = _index(r, "r")
        if r < 0:
            raise ValueError("r must be non-negative")
        return _new(cls, _cwr_gen(tuple(iterable), r))


# --- tee ---

class _tee_link:
    __slots__ = ("value", "next")

    def __init__(self):
        self.value = _marker
        self.next = None


class _tee:
    __slots__ = ("_source", "_link", "__weakref__")

    def __init__(self, source, link):
        self._source = source
        self._link = link

    def __iter__(self):
        return self

    def __next__(self):
        link = self._link
        if link.next is None:
            value = next(self._source)
            link.value = value
            link.next = _tee_link()
        self._link = link.next
        return link.value

    def __copy__(self):
        return _tee(self._source, self._link)


_tee.__name__ = "_tee"


def tee(iterable, n=2, /):
    n = _index(n, "n")
    if n < 0:
        raise ValueError("n must be >= 0")
    if n == 0:
        return ()
    it = iter(iterable)
    if isinstance(it, _tee):
        first = it.__copy__()
    elif hasattr(type(it), "__copy__"):
        first = it.__copy__()
        if not isinstance(first, _tee):
            first = _tee(it, _tee_link())
    else:
        first = _tee(it, _tee_link())
    result = [first]
    for _ in range(n - 1):
        result.append(first.__copy__())
    return tuple(result)


for _cls in (count, cycle, repeat, accumulate, batched, chain, compress, dropwhile,
             takewhile, filterfalse, groupby, islice, pairwise, starmap, zip_longest,
             product, permutations, combinations, combinations_with_replacement):
    _cls.__module__ = "itertools"
del _cls
