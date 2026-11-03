"""Pure-Python math.integer (replaces the C module _math_integer).

Integer-only functions: comb, factorial, gcd, isqrt, lcm, perm.  All work on
exact ints (operands are converted with __index__ and then to exact int, so
int subclasses with overridden operators do not affect the results).
"""

__name__ = "math.integer"

_LLONG_MAX = (1 << 63) - 1


def _index(value):
    if type(value) is int:
        return value
    try:
        meth = type(value).__index__
    except AttributeError:
        raise TypeError(f"'{type(value).__name__}' object cannot be interpreted "
                        "as an integer") from None
    result = meth(value)
    if not isinstance(result, int):
        raise TypeError(f"__index__ returned non-int (type {type(result).__name__})")
    return int.__index__(result) if type(result) is not int else result


def _gcd2(a, b):
    a = -a if a < 0 else a
    b = -b if b < 0 else b
    while b:
        a, b = b, a % b
    return a


def gcd(*integers):
    """Greatest Common Divisor."""
    result = 0
    for x in integers:
        x = _index(x)
        if result != 1:
            result = _gcd2(result, x)
    return result


def lcm(*integers):
    """Least Common Multiple."""
    result = 1
    vals = [_index(x) for x in integers]
    for x in vals:
        if result == 0:
            continue
        if x == 0:
            result = 0
            continue
        g = _gcd2(result, x)
        result = abs(result // g * x)
    return result


def isqrt(n, /):
    """Return the integer part of the square root of the input."""
    n = _index(n)
    if n < 0:
        raise ValueError("isqrt() argument must be nonnegative")
    if n == 0:
        return 0
    c = (n.bit_length() - 1) // 2
    a = 1
    d = 0
    for s in reversed(range(c.bit_length())):
        e = d
        d = c >> s
        a = (a << d - e - 1) + (n >> 2 * c - e - d + 1) // a
    return a - (a * a > n)


def _prod_range(lo, hi):
    """Product of range(lo, hi) by binary splitting."""
    n = hi - lo
    if n <= 0:
        return 1
    if n < 16:
        r = 1
        for i in range(lo, hi):
            r *= i
        return r
    mid = (lo + hi) >> 1
    return _prod_range(lo, mid) * _prod_range(mid, hi)


def _odd_prod(start, stop):
    """Product of odd numbers in range(start, stop, 2), start and stop odd."""
    n = (stop - start) >> 1
    if n <= 0:
        return 1
    if n < 16:
        r = 1
        for i in range(start, stop, 2):
            r *= i
        return r
    mid = (start + n) | 1
    return _odd_prod(start, mid) * _odd_prod(mid, stop)


def factorial(n, /):
    """Find n!."""
    n = _index(n)
    if n < 0:
        raise ValueError("factorial() not defined for negative values")
    if n > _LLONG_MAX:
        raise OverflowError("factorial() argument should not exceed %d" % _LLONG_MAX)
    inner = outer = 1
    for i in reversed(range(n.bit_length())):
        inner *= _odd_prod(((n >> (i + 1)) + 1) | 1, ((n >> i) + 1) | 1)
        outer *= inner
    return outer << (n - bin(n).count("1"))


def perm(n, k=None, /):
    """Number of ways to choose k items from n items without repetition and with order."""
    n = _index(n)
    if k is None:
        if n < 0:
            raise ValueError("n must be a non-negative integer")
        return factorial(n)
    k = _index(k)
    if n < 0:
        raise ValueError("n must be a non-negative integer")
    if k < 0:
        raise ValueError("k must be a non-negative integer")
    if k > n:
        return 0
    if k > _LLONG_MAX:
        raise OverflowError("k must not exceed %d" % _LLONG_MAX)
    return _prod_range(n - k + 1, n + 1)


def comb(n, k, /):
    """Number of ways to choose k items from n items without repetition and without order."""
    n = _index(n)
    k = _index(k)
    if n < 0:
        raise ValueError("n must be a non-negative integer")
    if k < 0:
        raise ValueError("k must be a non-negative integer")
    if k > n:
        return 0
    k = min(k, n - k)
    if k > _LLONG_MAX:
        raise OverflowError("min(n - k, k) must not exceed %d" % _LLONG_MAX)
    return _comb(n, k)


def _comb(n, k):
    if k < 32:
        r = 1
        for i in range(k):
            r = r * (n - i) // (i + 1)
        return r
    j = k >> 1
    return _comb(n, j) * _comb(n - j, k - j) // _comb(k, j)


for _f in (comb, factorial, gcd, isqrt, lcm, perm):
    _f.__module__ = "math.integer"
del _f


def __dir__():
    return ["__doc__", "__loader__", "__name__", "__package__", "__spec__",
            "comb", "factorial", "gcd", "isqrt", "lcm", "perm"]
