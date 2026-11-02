"""Pure-Python ``_bisect`` (replaces Modules/_bisectmodule.c).

Mirrors the C module: ``bisect_left``/``bisect_right`` and ``insort_left``/
``insort_right`` with ``lo``, ``hi`` and ``key=``. Arguments are validated
the way Argument Clinic does (``lo`` must be a non-negative index, ``hi`` an
index or ``None``; an explicit ``hi=-1`` also means ``len(a)``), a container
without ``__getitem__`` or a plain mapping raises the same ``TypeError`` as
``get_sq_item``, and ``insort`` calls ``a.insert`` (``list.insert`` for exact
lists). Comparisons always use ``item < x`` / ``x < item`` like the C code.

Limitations: none known beyond speed (the search loop is interpreted) and the
sequence check, which cannot see ``sq_item`` and approximates it with
``type(a).__getitem__`` being present and not ``dict.__getitem__``.
"""

import operator as _operator


def _check_sequence(a):
    tp = type(a)
    getitem = getattr(tp, '__getitem__', None)
    if getitem is None:
        raise TypeError(f"'{tp.__name__}' object does not support indexing")
    if getitem is dict.__getitem__:
        raise TypeError(f"{tp.__name__} is not a sequence")


def _args(a, lo, hi):
    lo = _operator.index(lo)
    if lo < 0:
        raise ValueError('lo must be non-negative')
    if hi is None:
        hi = -1
    else:
        hi = _operator.index(hi)
    if hi == -1:
        hi = len(a)
    _check_sequence(a)
    return lo, hi


def bisect_right(a, x, lo=0, hi=None, *, key=None):
    """Return the index where to insert item x in list a, assuming a is sorted.

    The return value i is such that all e in a[:i] have e <= x, and all e in
    a[i:] have e > x.  So if x already appears in the list, a.insert(i, x) will
    insert just after the rightmost x already there.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """
    lo, hi = _args(a, lo, hi)
    return _bisect_right(a, x, lo, hi, key)


def _bisect_right(a, x, lo, hi, key):
    if key is None:
        while lo < hi:
            mid = (lo + hi) // 2
            if x < a[mid]:
                hi = mid
            else:
                lo = mid + 1
    else:
        while lo < hi:
            mid = (lo + hi) // 2
            if x < key(a[mid]):
                hi = mid
            else:
                lo = mid + 1
    return lo


def bisect_left(a, x, lo=0, hi=None, *, key=None):
    """Return the index where to insert item x in list a, assuming a is sorted.

    The return value i is such that all e in a[:i] have e < x, and all e in
    a[i:] have e >= x.  So if x already appears in the list, a.insert(i, x) will
    insert just before the leftmost x already there.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """
    lo, hi = _args(a, lo, hi)
    return _bisect_left(a, x, lo, hi, key)


def _bisect_left(a, x, lo, hi, key):
    if key is None:
        while lo < hi:
            mid = (lo + hi) // 2
            if a[mid] < x:
                lo = mid + 1
            else:
                hi = mid
    else:
        while lo < hi:
            mid = (lo + hi) // 2
            if key(a[mid]) < x:
                lo = mid + 1
            else:
                hi = mid
    return lo


def insort_right(a, x, lo=0, hi=None, *, key=None):
    """Insert item x in list a, and keep it sorted assuming a is sorted.

    If x is already in a, insert it to the right of the rightmost x.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """
    lo, hi = _args(a, lo, hi)
    key_x = x if key is None else key(x)
    a.insert(_bisect_right(a, key_x, lo, hi, key), x)


def insort_left(a, x, lo=0, hi=None, *, key=None):
    """Insert item x in list a, and keep it sorted assuming a is sorted.

    If x is already in a, insert it to the left of the leftmost x.

    Optional args lo (default 0) and hi (default len(a)) bound the
    slice of a to be searched.

    A custom key function can be supplied to customize the sort order.
    """
    lo, hi = _args(a, lo, hi)
    key_x = x if key is None else key(x)
    a.insert(_bisect_left(a, key_x, lo, hi, key), x)
