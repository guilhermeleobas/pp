"""Pure-Python math, executed by the pp VM (replaces the C module).

Semantics follow Modules/mathmodule.c of CPython 3.15.  No libm is used:
transcendental functions are evaluated in binary fixed point on host ints
(with an adaptive number of guard bits) from the exact rational value of the
float argument, then rounded once to a float by int true division.  Results
are therefore usually correctly rounded, and in any case within an ulp or so.

Limitations:
- Speed: every transcendental call does big-int series work in the VM; much
  slower than libm.
- Results may differ from the platform libm in the last bit (pp tends to be
  closer to the correctly rounded value).
- The sign/payload of NaN results is not tracked the way libm does it.
- ``math.integer`` is the pure-Python ``_math_integer`` module, registered as
  ``sys.modules['math.integer']``.
"""

import sys as _sys
import _math_integer as integer

from _math_integer import comb, factorial, gcd, isqrt, lcm, perm, _index

_sys.modules.setdefault("math.integer", integer)

inf = float("inf")
nan = float("nan")
pi = 3.141592653589793
e = 2.718281828459045
tau = 6.283185307179586

_MAXF = 1.7976931348623157e308
_BASE_W = 128


# ---------------------------------------------------------------- conversions

def _f(x):
    """PyFloat_AsDouble."""
    if type(x) is float:
        return x
    if isinstance(x, (float, int)):
        return float(x)
    tp = type(x)
    if hasattr(tp, "__float__"):
        return float(x)
    if hasattr(tp, "__index__"):
        return float(_index(x))
    raise TypeError(f"must be real number, not {tp.__name__}")


def _isnan(x):
    return x != x


def _isinf(x):
    return x == inf or x == -inf


def _isfinite(x):
    return x == x and x != inf and x != -inf


def _bits(x):
    m = memoryview(bytearray(8)).cast("d")
    m[0] = x
    return m.cast("B").cast("Q")[0]


def _from_bits(b):
    m = memoryview(bytearray(8)).cast("Q")
    m[0] = b
    return m.cast("B").cast("d")[0]


def _signbit(x):
    return _bits(x) >> 63 == 1


def _copysign(x, y):
    neg = _signbit(y)
    x = abs(x)
    return -x if neg else x


def _ratio(x):
    """x (finite, nonzero) -> (n, d) with x = n/d, d a power of 2."""
    return x.as_integer_ratio()


def _log2approx(n, d):
    """floor-ish of log2(|n/d|)."""
    return abs(n).bit_length() - d.bit_length()


def _range_err():
    return OverflowError("math range error")


def _dom_err(msg="math domain error"):
    return ValueError(msg)


def _to_float(num, den):
    """Correctly rounded num/den for ints; OverflowError -> math range error."""
    try:
        return num / den
    except OverflowError:
        raise _range_err() from None


def _scaled(num, shift):
    """num * 2**shift as a float."""
    if shift >= 0:
        return _to_float(num << shift, 1)
    return _to_float(num, 1 << -shift)


def _mulw(a, b, W):
    """a * b / 2**W truncated toward zero."""
    p = a * b
    return p >> W if p >= 0 else -((-p) >> W)


def _divt(a, k):
    return a // k if a >= 0 else -((-a) // k)


def _fixed(n, d, W):
    """floor(n/d * 2**W) for a rational with d a power of two."""
    return (n << W) // d


# ---------------------------------------------------------------- constants

_cache = {}


def _const(name, W, compute):
    c = _cache.get(name)
    if c is not None and c[0] >= W:
        return c[1] >> (c[0] - W)
    Wc = max(W + 32, 256 if c is None else 2 * c[0])
    v = compute(Wc)
    _cache[name] = (Wc, v)
    return v >> (Wc - W)


def _atan_inv(n, W):
    """atan(1/n) * 2**W."""
    one = 1 << W
    x = one // n
    n2 = n * n
    total = x
    k = 1
    sign = -1
    while x:
        x //= n2
        k += 2
        total += sign * (x // k)
        sign = -sign
    return total


def _pi_fixed(W):
    return _const("pi", W, lambda w: (16 * _atan_inv(5, w + 16) - 4 * _atan_inv(239, w + 16)) >> 16)


def _atanh_fixed(t, W):
    """atanh(t) for fixed t, |t| small."""
    total = t
    t2 = (t * t) >> W
    p = t
    k = 1
    while p:
        p = _mulw(p, t2, W)
        k += 2
        total += _divt(p, k)
    return total


def _ln2_fixed(W):
    return _const("ln2", W, lambda w: (2 * _atanh_fixed((1 << (w + 16)) // 3, w + 16)) >> 16)


def _ln10_fixed(W):
    return _const("ln10", W, lambda w: _log_fixed(10, 1, w))


# ---------------------------------------------------------------- log / exp cores

def _extra_bits_near_one(p, q):
    diff = p - q
    if diff == 0:
        return 0
    return max(0, q.bit_length() - abs(diff).bit_length())


def _log_fixed(p, q, W):
    """log(p/q) * 2**W for positive ints p, q."""
    e = p.bit_length() - q.bit_length()
    G = W + 16
    if G - e >= 0:
        M = (p << (G - e)) // q
    else:
        M = p // (q << (e - G))
    one = 1 << G
    # sqrt(2) * one, roughly
    if M * M > 2 * one * one:
        M >>= 1
        e += 1
    elif 2 * M * M < one * one:
        M <<= 1
        e -= 1
    t = ((M - one) << G) // (M + one)
    L = e * _ln2_fixed(G) + 2 * _atanh_fixed(t, G)
    return L >> 16


def _log_ratio(p, q, W=_BASE_W):
    """(fixed value, W) of log(p/q), with enough bits for a relative result."""
    W = W + _extra_bits_near_one(p, q)
    return _log_fixed(p, q, W), W


def _exp_small(R, W):
    """exp(R) for fixed |R| <~ 0.5."""
    one = 1 << W
    total = one
    term = one
    k = 1
    while term:
        term = _divt(_mulw(term, R, W), k)
        total += term
        k += 1
    return total


def _exp_parts(X, W):
    """exp(X / 2**W) == E * 2**(k - W); returns (E, k)."""
    G = W + 24
    X <<= 24
    L = _ln2_fixed(G)
    k = (2 * X + L) // (2 * L)
    R = X - k * L
    E = _exp_small(R, G) >> 24
    return E, k


def _exp_fixed_to_float(X, W):
    E, k = _exp_parts(X, W)
    return _scaled(E, k - W)


# ---------------------------------------------------------------- simple functions

def fabs(x, /):
    """Return the absolute value of the float x."""
    return abs(_f(x))


def copysign(x, y, /):
    """Return a float with the magnitude of x but the sign of y."""
    return _copysign(_f(x), _f(y))


def signbit(x, /):
    """Return True if the sign of x is negative and False otherwise."""
    return _signbit(_f(x))


def isfinite(x, /):
    """Return True if x is neither an infinity nor a NaN, and False otherwise."""
    return _isfinite(_f(x))


def isinf(x, /):
    """Return True if x is a positive or negative infinity, and False otherwise."""
    return _isinf(_f(x))


def isnan(x, /):
    """Return True if x is a NaN (not a number), and False otherwise."""
    return _isnan(_f(x))


def isnormal(x, /):
    """Return True if x is normal, and False otherwise."""
    x = _f(x)
    return _isfinite(x) and abs(x) >= 2.2250738585072014e-308


def issubnormal(x, /):
    """Return True if x is subnormal, and False otherwise."""
    x = _f(x)
    return x != 0.0 and abs(x) < 2.2250738585072014e-308


_MISSING = object()


def _special_lookup(x, name):
    try:
        return getattr(type(x), name)
    except AttributeError:
        return _MISSING


def floor(x, /):
    """Return the floor of x as an Integral."""
    if type(x) is float:
        return int(x) - (x < 0 and x != int(x)) if _isfinite(x) else int(x)
    if type(x) is int:
        return x
    meth = _special_lookup(x, "__floor__")
    if meth is not _MISSING:
        return meth(x)
    x = _f(x)
    return floor(x)


def ceil(x, /):
    """Return the ceiling of x as an Integral."""
    if type(x) is float:
        return int(x) + (x > 0 and x != int(x)) if _isfinite(x) else int(x)
    if type(x) is int:
        return x
    meth = _special_lookup(x, "__ceil__")
    if meth is not _MISSING:
        return meth(x)
    x = _f(x)
    return ceil(x)


def trunc(x, /):
    """Truncates the Real x to the nearest Integral toward 0."""
    if type(x) is float:
        return int(x)
    meth = _special_lookup(x, "__trunc__")
    if meth is _MISSING:
        raise TypeError(f"type {type(x).__name__} doesn't define __trunc__ method")
    return meth(x)


def frexp(x, /):
    """Return the mantissa and exponent of x, as pair (m, e)."""
    x = _f(x)
    if x == 0.0 or not _isfinite(x):
        return x, 0
    n, d = _ratio(x)
    ex = abs(n).bit_length() - d.bit_length()
    # |x| in [2**ex, 2**(ex+1)) or [2**(ex-1), 2**ex)
    m = _scaled(n, 0) if False else None
    if ex >= 0:
        m = n / (d << ex)
    else:
        m = (n << -ex) / d
    if abs(m) >= 1.0:
        m /= 2.0
        ex += 1
    elif abs(m) < 0.5:
        m *= 2.0
        ex -= 1
    return m, ex + 0


def ldexp(x, i, /):
    """Return x * (2**i)."""
    x = _f(x)
    if type(i) is not int:
        if isinstance(i, float) or not hasattr(type(i), "__index__"):
            raise TypeError("Expected an int as second argument to ldexp.")
        i = _index(i)
    if x == 0.0 or not _isfinite(x):
        return x
    if i > 3000:
        raise _range_err()
    if i < -3000:
        return _copysign(0.0, x)
    n, d = _ratio(x)
    if i >= 0:
        r = _to_float(n << i, d)
    else:
        r = _to_float(n, d << -i)
    if r == 0.0:
        return _copysign(0.0, x)
    return r


def modf(x, /):
    """Return the fractional and integer parts of x."""
    x = _f(x)
    if _isinf(x):
        return _copysign(0.0, x), x
    if _isnan(x):
        return x, x
    ip = float(int(x))
    ip = _copysign(ip, x)
    return _copysign(x - ip, x), ip


def _fmod_exact(x, y):
    """sign(x) * (|x| mod |y|), exact."""
    xn, xd = _ratio(abs(x))
    yn, yd = _ratio(abs(y))
    D = max(xd, yd)
    a = xn * (D // xd)
    b = yn * (D // yd)
    return a % b, b, D


def fmod(x, y, /):
    """Return fmod(x, y), according to platform C."""
    x = _f(x)
    y = _f(y)
    if _isnan(x) or _isnan(y):
        return nan
    if _isinf(y) and _isfinite(x):
        return x
    if _isinf(x) or y == 0.0:
        raise _dom_err()
    if x == 0.0:
        return x
    r, _, D = _fmod_exact(x, y)
    return _copysign(r / D, x)


def remainder(x, y, /):
    """Difference between x and the closest integer multiple of y."""
    x = _f(x)
    y = _f(y)
    if _isnan(x):
        return x
    if _isnan(y):
        return y
    if _isinf(x) or y == 0.0:
        raise _dom_err()
    if _isinf(y):
        return x
    if x == 0.0:
        return x
    r, b, D = _fmod_exact(x, y)
    # r in [0, b); choose r or r - b, ties to even quotient
    q_odd = None
    c = 2 * r
    if c > b:
        r -= b
    elif c == b:
        xn, xd = _ratio(abs(x))
        a = xn * (D // xd)
        if (a // b) % 2 == 1:
            r -= b
    res = r / D
    if res == 0.0:
        return _copysign(0.0, x)
    return res if x > 0 else -res


def degrees(x, /):
    """Convert angle x from radians to degrees."""
    return _f(x) * (180.0 / pi)


def radians(x, /):
    """Convert angle x from degrees to radians."""
    return _f(x) * (pi / 180.0)


def fmax(x, y, /):
    """Return the larger of two floating-point arguments."""
    x = _f(x)
    y = _f(y)
    if _isnan(x):
        return y
    if _isnan(y):
        return x
    if x == y:
        return y if _signbit(x) else x
    return x if x > y else y


def fmin(x, y, /):
    """Return the smaller of two floating-point arguments."""
    x = _f(x)
    y = _f(y)
    if _isnan(x):
        return y
    if _isnan(y):
        return x
    if x == y:
        return x if _signbit(x) else y
    return x if x < y else y


# ---------------------------------------------------------------- roots

def _iroot(n, k):
    """floor(n ** (1/k)) for int n >= 0."""
    if n < 2:
        return n
    if k == 2:
        return isqrt(n)
    x = 1 << ((n.bit_length() + k - 1) // k)
    while True:
        y = ((k - 1) * x + n // x ** (k - 1)) // k
        if y >= x:
            break
        x = y
    while x ** k > n:
        x -= 1
    while (x + 1) ** k <= n:
        x += 1
    return x


def _root_ratio(num, den, k):
    """Correctly rounded (num/den) ** (1/k) for positive ints (den power of 2 ok)."""
    # want root with >= 64 significant bits
    target = 66 * k
    s = target - (num.bit_length() - den.bit_length())
    s = max(0, s)
    s += (-s) % k
    # value * 2**s = num * 2**s / den
    if s >= 0:
        q, rem = divmod(num << s, den)
    r = _iroot(q, k)
    if rem or r ** k != q:
        r |= 1
    return _scaled(r, -(s // k))


def sqrt(x, /):
    """Return the square root of x."""
    x = _f(x)
    if _isnan(x) or x == inf or x == 0.0:
        return x
    if x < 0:
        raise _dom_err(f"expected a nonnegative input, got {x!r}")
    n, d = _ratio(x)
    return _root_ratio(n, d, 2)


def cbrt(x, /):
    """Return the cube root of x."""
    x = _f(x)
    if _isnan(x) or _isinf(x) or x == 0.0:
        return x
    n, d = _ratio(abs(x))
    r = _root_ratio(n, d, 3)
    return r if x > 0 else -r


# ---------------------------------------------------------------- exp / log

def exp(x, /):
    """Return e raised to the power of x."""
    x = _f(x)
    if _isnan(x):
        return x
    if _isinf(x):
        return x if x > 0 else 0.0
    if x > 710.0:
        raise _range_err()
    if x < -746.0:
        return 0.0
    if x == 0.0:
        return 1.0
    n, d = _ratio(x)
    W = _BASE_W
    return _exp_fixed_to_float(_fixed(n, d, W), W)


def exp2(x, /):
    """Return 2 raised to the power of x."""
    x = _f(x)
    if _isnan(x):
        return x
    if _isinf(x):
        return x if x > 0 else 0.0
    if x > 1025.0:
        raise _range_err()
    if x < -1080.0:
        return 0.0
    k = int(x)
    if k == x:
        return _scaled(1, k)
    n, d = _ratio(x - k)
    W = _BASE_W
    X = (_fixed(n, d, W + 16) * _ln2_fixed(W + 16)) >> (W + 32)
    E, kk = _exp_parts(X, W)
    return _scaled(E, kk + k - W)


def expm1(x, /):
    """Return exp(x)-1."""
    x = _f(x)
    if _isnan(x):
        return x
    if _isinf(x):
        return x if x > 0 else -1.0
    if x == 0.0:
        return x
    if x > 710.0:
        raise _range_err()
    if x < -60.0:
        return -1.0
    n, d = _ratio(x)
    W = _BASE_W + max(0, -_log2approx(n, d))
    E, k = _exp_parts(_fixed(n, d, W), W)
    # E * 2**(k-W) - 1
    if k >= 0:
        num = (E << k) - (1 << W)
        return _to_float(num, 1 << W)
    num = E - (1 << (W - k))
    return _to_float(num, 1 << (W - k))


def _log_arg(x, name="log"):
    """Positive argument as (p, q) ints, or a float special result."""
    tp = type(x)
    if isinstance(x, int) or (tp is not float and not hasattr(tp, "__float__")
                              and hasattr(tp, "__index__")):
        x = _index(x)
        if x <= 0:
            raise _dom_err("expected a positive input")
        return x, 1
    try:
        x = _f(x)
    except OverflowError:
        if not hasattr(tp, "__index__"):
            raise
        return _log_arg(_index(x))
    if _isnan(x) or x == inf:
        return x
    if x <= 0.0:
        raise _dom_err(f"expected a positive input, got {x!r}")
    return _ratio(x)


def _log_core(x, scale_fn=None):
    a = _log_arg(x)
    if isinstance(a, float):
        return a
    p, q = a
    if p == q:
        return 0.0
    L, W = _log_ratio(p, q)
    if scale_fn is None:
        return _to_float(L, 1 << W)
    C = scale_fn(W + 16)
    return _to_float(L << 16, C)


def log(x, base=None, /):
    """Return the logarithm of x to the given base (default e)."""
    num = _log_core(x)
    if base is None:
        return num
    den = _log_core(base)
    return num / den


def log2(x, /):
    """Return the base 2 logarithm of x."""
    return _log_core(x, _ln2_fixed)


def log10(x, /):
    """Return the base 10 logarithm of x."""
    return _log_core(x, _ln10_fixed)


def log1p(x, /):
    """Return the natural logarithm of 1+x (base e)."""
    x = _f(x)
    if _isnan(x) or x == inf or x == 0.0:
        return x
    if x <= -1.0:
        raise _dom_err(f"expected argument value > -1, got {x!r}")
    n, d = _ratio(x)
    L, W = _log_ratio(d + n, d)
    return _to_float(L, 1 << W)


def pow(x, y, /):
    """Return x**y (x to the power of y)."""
    x = _f(x)
    y = _f(y)
    if not _isfinite(x) or not _isfinite(y):
        if _isnan(x):
            return 1.0 if y == 0.0 else x
        if _isnan(y):
            return 1.0 if x == 1.0 else y
        if _isinf(x):
            odd_y = _isfinite(y) and fmod(abs(y), 2.0) == 1.0
            if y > 0.0:
                return x if odd_y else abs(x)
            if y == 0.0:
                return 1.0
            return _copysign(0.0, x) if odd_y else 0.0
        # y infinite
        if abs(x) == 1.0:
            return 1.0
        if (y > 0.0) == (abs(x) > 1.0):
            return abs(y)
        return 0.0
    if x == 0.0:
        if y < 0.0:
            raise _dom_err()
    elif x < 0.0 and y != int(y):
        raise _dom_err()
    try:
        r = x ** y
    except OverflowError:
        raise _range_err() from None
    except ZeroDivisionError:
        raise _dom_err() from None
    if _isinf(r):
        raise _range_err()
    return r


# ---------------------------------------------------------------- trigonometry

def _sincos_small(R, W):
    """(sin, cos) fixed for fixed |R| <= ~pi/4."""
    R2 = (R * R) >> W
    s = R
    term = R
    k = 1
    while term:
        term = -_divt(_mulw(term, R2, W), (k + 1) * (k + 2))
        s += term
        k += 2
    one = 1 << W
    c = one
    term = one
    k = 0
    while term:
        term = -_divt(_mulw(term, R2, W), (k + 1) * (k + 2))
        c += term
        k += 2
    return s, c


def _trig(x):
    """(sin, cos, Wr) fixed of finite x."""
    n, d = _ratio(x)
    ex = _log2approx(n, d)
    W = _BASE_W + max(0, -ex) + 64
    Wp = W + max(0, ex) + 16
    X = _fixed(n, d, Wp)
    H = _pi_fixed(Wp) >> 1
    q = (2 * X + H) // (2 * H)
    R = (X - q * H) >> (Wp - W)
    s, c = _sincos_small(R, W)
    q &= 3
    if q == 1:
        s, c = c, -s
    elif q == 2:
        s, c = -s, -c
    elif q == 3:
        s, c = -c, s
    return s, c, W


def _trig_arg(x):
    x = _f(x)
    if _isinf(x):
        raise _dom_err(f"expected a finite input, got {x!r}")
    return x


def sin(x, /):
    """Return the sine of x (measured in radians)."""
    x = _trig_arg(x)
    if _isnan(x) or x == 0.0:
        return x
    s, c, W = _trig(x)
    return _to_float(s, 1 << W)


def cos(x, /):
    """Return the cosine of x (measured in radians)."""
    x = _trig_arg(x)
    if _isnan(x):
        return x
    if x == 0.0:
        return 1.0
    s, c, W = _trig(x)
    return _to_float(c, 1 << W)


def tan(x, /):
    """Return the tangent of x (measured in radians)."""
    x = _trig_arg(x)
    if _isnan(x) or x == 0.0:
        return x
    s, c, W = _trig(x)
    return _to_float(s, c)


def _atan_fixed(p, q, W):
    """atan(p/q) * 2**W for ints p >= 0, q > 0."""
    if p > q:
        return (_pi_fixed(W) >> 1) - _atan_fixed(q, p, W)
    G = W + 16
    one = 1 << G
    t = (p << G) // q
    # argument halving twice: t -> t / (1 + sqrt(1 + t^2))
    for _ in range(2):
        t = (t << G) // (one + isqrt(one * one + t * t))
    t2 = (t * t) >> G
    total = t
    term = t
    k = 1
    while term:
        term = -_mulw(term, t2, G)
        k += 2
        total += _divt(term, k)
    return (4 * total) >> 16


def _atan2_fixed(Y, X, W):
    """atan2 of ints (Y, X) not both zero, fixed at W."""
    if X == 0:
        h = _pi_fixed(W) >> 1
        return h if Y > 0 else -h
    a = _atan_fixed(abs(Y), abs(X), W)
    if X < 0:
        a = _pi_fixed(W) - a
    return a if Y >= 0 else -a


def _atan_float(p, q):
    """Correctly rounded atan(p/q) for ints p >= 0, q > 0."""
    if p == 0:
        return 0.0
    extra = q.bit_length() - p.bit_length()
    if extra > 600:
        return p / q
    W = _BASE_W + max(0, extra)
    return _to_float(_atan_fixed(p, q, W), 1 << W)


def atan(x, /):
    """Return the arc tangent (measured in radians) of x."""
    x = _f(x)
    if _isnan(x) or x == 0.0:
        return x
    if _isinf(x):
        return _copysign(pi / 2, x)
    n, d = _ratio(abs(x))
    r = _atan_float(n, d)
    return r if x > 0 else -r


def atan2(y, x, /):
    """Return the arc tangent (measured in radians) of y/x."""
    y = _f(y)
    x = _f(x)
    if _isnan(x) or _isnan(y):
        return nan
    if _isinf(y):
        if _isinf(x):
            if _signbit(x):
                return _copysign(0.75 * pi, y)
            return _copysign(0.25 * pi, y)
        return _copysign(pi / 2, y)
    if _isinf(x) or y == 0.0:
        if _signbit(x):
            return _copysign(pi, y)
        return _copysign(0.0, y)
    if x == 0.0:
        return _copysign(pi / 2, y)
    yn, yd = _ratio(abs(y))
    xn, xd = _ratio(abs(x))
    p = yn * xd
    q = xn * yd
    if x > 0:
        r = _atan_float(p, q)
    else:
        extra = q.bit_length() - p.bit_length()
        W = _BASE_W + 16
        if extra > 600:
            r = pi
        else:
            r = _to_float(_pi_fixed(W) - _atan_fixed(p, q, W), 1 << W)
    return r if y > 0 else -r


def asin(x, /):
    """Return the arc sine (measured in radians) of x."""
    x = _f(x)
    if _isnan(x) or x == 0.0:
        return x
    if not -1.0 <= x <= 1.0:
        raise _dom_err(f"expected a number in range from -1 up to 1, got {x!r}")
    n, d = _ratio(abs(x))
    W = _BASE_W + max(0, -_log2approx(n, d)) + 64
    X = _fixed(n, d, W)
    S = isqrt((1 << (2 * W)) - X * X)
    if S == 0:
        r = pi / 2
    else:
        r = _atan_float(X, S)
    return r if x > 0 else -r


def acos(x, /):
    """Return the arc cosine (measured in radians) of x."""
    x = _f(x)
    if _isnan(x):
        return x
    if not -1.0 <= x <= 1.0:
        raise _dom_err(f"expected a number in range from -1 up to 1, got {x!r}")
    if x == 1.0:
        return 0.0
    if x == 0.0:
        return pi / 2
    n, d = _ratio(abs(x))
    W = _BASE_W + 64
    X = _fixed(n, d, W)
    S = isqrt((1 << (2 * W)) - X * X)
    if x > 0:
        return _atan_float(S, X)
    return _to_float(_atan2_fixed(S, -X, W), 1 << W)


# ---------------------------------------------------------------- hyperbolic

def _exp_pm(x):
    """(A, B, s): e**|x| == A * 2**s, e**-|x| == B * 2**s, ints."""
    n, d = _ratio(abs(x))
    W = _BASE_W + max(0, -_log2approx(n, d))
    X = _fixed(n, d, W)
    E1, k1 = _exp_parts(X, W)
    E2, k2 = _exp_parts(-X, W)
    s = min(k1, k2)
    return E1 << (k1 - s), E2 << (k2 - s), s - W


def sinh(x, /):
    """Return the hyperbolic sine of x."""
    x = _f(x)
    if _isnan(x) or _isinf(x) or x == 0.0:
        return x
    if abs(x) > 711.0:
        raise _range_err()
    A, B, s = _exp_pm(x)
    r = _scaled(A - B, s - 1)
    return r if x > 0 else -r


def cosh(x, /):
    """Return the hyperbolic cosine of x."""
    x = _f(x)
    if _isnan(x):
        return x
    if _isinf(x):
        return inf
    if x == 0.0:
        return 1.0
    if abs(x) > 711.0:
        raise _range_err()
    A, B, s = _exp_pm(x)
    return _scaled(A + B, s - 1)


def tanh(x, /):
    """Return the hyperbolic tangent of x."""
    x = _f(x)
    if _isnan(x) or x == 0.0:
        return x
    if _isinf(x) or abs(x) > 40.0:
        return _copysign(1.0, x)
    A, B, s = _exp_pm(x)
    r = (A - B) / (A + B)
    return r if x > 0 else -r


def asinh(x, /):
    """Return the inverse hyperbolic sine of x."""
    x = _f(x)
    if _isnan(x) or _isinf(x) or x == 0.0:
        return x
    n, d = _ratio(abs(x))
    ex = _log2approx(n, d)
    W = _BASE_W + 32 + max(0, -ex)
    X = _fixed(n, d, W)
    S = isqrt(X * X + (1 << (2 * W)))
    L, W2 = _log_ratio(X + S, 1 << W, _BASE_W + 32)
    r = _to_float(L, 1 << W2)
    return r if x > 0 else -r


def acosh(x, /):
    """Return the inverse hyperbolic cosine of x."""
    x = _f(x)
    if _isnan(x):
        return x
    if x < 1.0:
        raise _dom_err(f"expected argument value not less than 1, got {x!r}")
    if x == inf:
        return x
    if x == 1.0:
        return 0.0
    n, d = _ratio(x)
    W = _BASE_W + 64
    X = _fixed(n, d, W)
    S = isqrt(X * X - (1 << (2 * W)))
    L, W2 = _log_ratio(X + S, 1 << W)
    return _to_float(L, 1 << W2)


def atanh(x, /):
    """Return the inverse hyperbolic tangent of x."""
    x = _f(x)
    if _isnan(x) or x == 0.0:
        return x
    if not -1.0 < x < 1.0:
        raise _dom_err(f"expected a number between -1 and 1, got {x!r}")
    n, d = _ratio(x)
    L, W = _log_ratio(d + n, d - n)
    return _to_float(L, 1 << (W + 1))


# ---------------------------------------------------------------- special functions

def _erf_parts(n, d, W):
    """erf(x) fixed for x = n/d > 0, at W bits."""
    G = W + 32
    X = _fixed(n, d, G)
    X2 = (X * X) >> G
    # sum 2^k x^(2k+1) / (1*3*...*(2k+1))
    term = X
    total = X
    k = 0
    while term:
        k += 1
        term = (term * 2 * X2 >> G) // (2 * k + 1)
        total += term
    E, kk = _exp_parts(-X2, G)
    total = (total * E) >> G
    if kk >= 0:
        total <<= kk
    else:
        total >>= -kk
    # times 2/sqrt(pi)
    sp = isqrt(_pi_fixed(G) << G)
    total = (total << (G + 1)) // sp
    return total >> 32


def erf(x, /):
    """Error function at x."""
    x = _f(x)
    if _isnan(x) or x == 0.0:
        return x
    if _isinf(x) or abs(x) >= 6.0:
        return _copysign(1.0, x)
    n, d = _ratio(abs(x))
    W = _BASE_W + max(0, -_log2approx(n, d)) + int(abs(x) * abs(x) * 1.45) + 8
    r = _to_float(_erf_parts(n, d, W), 1 << W)
    return r if x > 0 else -r


def erfc(x, /):
    """Complementary error function at x."""
    x = _f(x)
    if _isnan(x):
        return x
    if x == inf:
        return 0.0
    if x == -inf:
        return 2.0
    if x == 0.0:
        return 1.0
    if x > 27.3:
        return 0.0
    if x < -6.0:
        return 2.0
    n, d = _ratio(abs(x))
    W = _BASE_W + int(x * x * 1.45) + 16
    v = _erf_parts(n, d, W)
    one = 1 << W
    return _to_float(one - v if x > 0 else one + v, one)


_bern = []


def _bernoulli_coeffs(K):
    """[(num, den)] of B_2k / (2k (2k-1)) for k = 1..K."""
    if len(_bern) >= K:
        return _bern
    from fractions import Fraction
    # Akiyama-Tanigawa for B_0..B_2K
    N = 2 * K
    A = [Fraction(0)] * (N + 1)
    B = []
    for m in range(N + 1):
        A[m] = Fraction(1, m + 1)
        for j in range(m, 0, -1):
            A[j - 1] = j * (A[j - 1] - A[j])
        B.append(A[0])
    del _bern[:]
    for k in range(1, K + 1):
        c = B[2 * k] / (2 * k * (2 * k - 1))
        _bern.append((c.numerator, c.denominator))
    return _bern


def _lgamma_pos_fixed(n, d, W):
    """lgamma(n/d) fixed, n/d > 0 rational."""
    G = W + 32
    N = 0
    if n < 40 * d:
        N = 40 - n // d
    # z = x + N ; P = x (x+1) ... (x+N-1)
    zn = n + N * d
    Pn = 1
    for i in range(N):
        Pn *= n + i * d
    Pd = d ** N
    lz = _log_fixed(zn, d, G)
    Z = _fixed(zn, d, G) if d & (d - 1) == 0 else (zn << G) // d
    res = ((Z - (1 << (G - 1))) * lz >> G) - Z
    res += _log_fixed(_pi_fixed(G) * 2, 1 << G, G) >> 1
    zinv = (d << G) // zn
    zinv2 = (zinv * zinv) >> G
    p = zinv
    for bn, bd in _bernoulli_coeffs(30):
        res += p * bn // bd
        p = (p * zinv2) >> G
    if N:
        res -= _log_fixed(Pn, Pd, G)
    return res >> 32


def _sinpi_fixed(n, d, W):
    """sin(pi * n/d) fixed, plus sign."""
    r = n % (2 * d)
    X = (_pi_fixed(W + 8) * r // d) >> 8
    G = W
    H = _pi_fixed(G) >> 1
    q = (2 * X + H) // (2 * H)
    R = X - q * H
    s, c = _sincos_small(R, G)
    q &= 3
    if q == 1:
        s = c
    elif q == 2:
        s = -s
    elif q == 3:
        s = -c
    return s


def _gamma_arg(x):
    if x == int(x) and x <= 0.0:
        raise _dom_err(f"expected a noninteger or positive integer, got {x!r}")


def lgamma(x, /):
    """Natural logarithm of absolute value of Gamma function at x."""
    x = _f(x)
    if _isnan(x):
        return x
    if _isinf(x):
        return inf
    _gamma_arg(x)
    if x == 1.0 or x == 2.0:
        return 0.0
    if abs(x) > 1e306:
        raise _range_err()
    n, d = _ratio(x)
    W = _BASE_W + 64
    if x > 0:
        return _to_float(_lgamma_pos_fixed(n, d, W), 1 << W)
    # reflection: lgamma(x) = log(pi / |sin(pi x)|) - lgamma(1 - x)
    Ws = W + 64 + max(0, -_log2approx(n, d))
    S = abs(_sinpi_fixed(n, d, Ws))
    r = _log_fixed(_pi_fixed(Ws), S, W) - _lgamma_pos_fixed(d - n, d, W)
    return _to_float(r, 1 << W)


def gamma(x, /):
    """Gamma function at x."""
    x = _f(x)
    if _isnan(x) or x == inf:
        return x
    if x == -inf:
        raise _dom_err(f"expected a noninteger or positive integer, got {x!r}")
    _gamma_arg(x)
    if x == int(x) and x <= 30:
        return float(factorial(int(x) - 1))
    if x > 172.0:
        raise _range_err()
    if x < -200.0:
        return -0.0 if floor(x) % 2 else 0.0
    n, d = _ratio(x)
    W = _BASE_W + 64
    if x > 0:
        E, k = _exp_parts(_lgamma_pos_fixed(n, d, W), W)
        return _scaled(E, k - W)
    Ws = W + 64 + max(0, -_log2approx(n, d))
    S = _sinpi_fixed(n, d, Ws)
    L = _log_fixed(_pi_fixed(Ws), abs(S), W) - _lgamma_pos_fixed(d - n, d, W)
    E, k = _exp_parts(L, W)
    r = _scaled(E, k - W)
    return r if S > 0 else -r


# ---------------------------------------------------------------- sums / norms

def fsum(seq, /):
    """Return an accurate floating-point sum of values in the iterable seq."""
    total = 0  # exact sum * 2**1074
    pos_inf = neg_inf = False
    nan_seen = False
    for x in iter(seq):
        if type(x) is not float:
            x = _f(x)
        if x - x != 0.0:
            if x != x:
                nan_seen = True
            elif x > 0:
                pos_inf = True
            else:
                neg_inf = True
            continue
        if x:
            n, d = x.as_integer_ratio()
            total += n << (1075 - d.bit_length())
    if nan_seen:
        return nan
    if pos_inf and neg_inf:
        raise ValueError("-inf + inf in fsum")
    if pos_inf:
        return inf
    if neg_inf:
        return -inf
    try:
        return total / (1 << 1074)
    except OverflowError:
        raise OverflowError("intermediate overflow in fsum") from None


def prod(iterable, /, *, start=1):
    """Calculate the product of all the elements in the input iterable."""
    result = start
    for x in iterable:
        result = result * x
    return result


_LONG_MIN = -(1 << 63)
_LONG_MAX = (1 << 63) - 1
_SP_SHIFT = 2200


def _flt_term(a, b):
    """Exact a*b * 2**_SP_SHIFT for finite floats a, b."""
    if a == 0.0 or b == 0.0:
        return 0
    an, ad = _ratio(a)
    bn, bd = _ratio(b)
    return (an * bn) << (_SP_SHIFT - (ad.bit_length() - 1) - (bd.bit_length() - 1))


def sumprod(p, q, /):
    """Return the sum of products of values from two iterables p and q."""
    p_it = iter(p)
    q_it = iter(q)
    total = 0
    int_on = flt_on = True
    int_total = 0
    int_used = False
    flt_total = 0
    flt_used = False
    while True:
        try:
            a = next(p_it)
            p_stop = False
        except StopIteration:
            p_stop = True
        try:
            b = next(q_it)
            q_stop = False
        except StopIteration:
            q_stop = True
        if p_stop != q_stop:
            raise ValueError("Inputs are not the same length")
        finished = p_stop
        if int_on:
            if not finished and type(a) is int and type(b) is int:
                if (_LONG_MIN <= a <= _LONG_MAX and _LONG_MIN <= b <= _LONG_MAX):
                    prod_ = a * b
                    if _LONG_MIN <= prod_ <= _LONG_MAX and _LONG_MIN <= int_total + prod_ <= _LONG_MAX:
                        int_total += prod_
                        int_used = True
                        continue
            int_on = False
            if int_used:
                total = total + int_total
                int_used = False
        if flt_on:
            if not finished:
                ok = True
                ta, tb = type(a), type(b)
                if ta is float and tb is float:
                    fa, fb = a, b
                elif ta is float and (tb is int or tb is bool):
                    fa = a
                    try:
                        fb = float(b)
                    except OverflowError:
                        ok = False
                elif tb is float and (ta is int or ta is bool):
                    fb = b
                    try:
                        fa = float(a)
                    except OverflowError:
                        ok = False
                else:
                    ok = False
                if ok and _isfinite(fa) and _isfinite(fb):
                    new = flt_total + _flt_term(fa, fb)
                    try:
                        new / (1 << _SP_SHIFT)
                        ok = True
                    except OverflowError:
                        ok = False
                    if ok:
                        flt_total = new
                        flt_used = True
                        continue
            flt_on = False
            if flt_used:
                total = total + flt_total / (1 << _SP_SHIFT)
                flt_used = False
        if finished:
            return total
        total = total + a * b


def _norm(values):
    """Correctly rounded sqrt(sum(v*v)) of floats, CPython special cases."""
    found_nan = False
    max_ = 0.0
    for v in values:
        if _isinf(v):
            return inf
        if _isnan(v):
            found_nan = True
    if found_nan:
        return nan
    total = 0
    for v in values:
        if v == 0.0:
            continue
        n, d = _ratio(abs(v))
        total += (n * n) << (2148 - 2 * (d.bit_length() - 1))
    if total == 0:
        return 0.0
    try:
        return _root_ratio(total, 1 << 2148, 2)
    except OverflowError:
        return inf


def hypot(*coordinates):
    """Multidimensional Euclidean distance from the origin to a point."""
    return _norm([_f(c) for c in coordinates])


def dist(p, q, /):
    """Return the Euclidean distance between two points p and q."""
    if not isinstance(p, tuple):
        p = tuple(p)
    if not isinstance(q, tuple):
        q = tuple(q)
    if len(p) != len(q):
        raise ValueError("both points must have the same number of dimensions")
    diffs = []
    for a, b in zip(p, q):
        a = _f(a)
        b = _f(b)
        if _isfinite(a) and _isfinite(b):
            diffs.append(_exact_diff(a, b))
        else:
            diffs.append(abs(a - b))
    found_nan = False
    for v in diffs:
        if isinstance(v, float):
            if _isinf(v):
                return inf
            if _isnan(v):
                found_nan = True
    if found_nan:
        return nan
    total = 0
    for v in diffs:
        n, sh = v
        total += (n * n) << (4296 - 2 * sh)
    if total == 0:
        return 0.0
    try:
        return _root_ratio(total, 1 << 4296, 2)
    except OverflowError:
        return inf


def _exact_diff(a, b):
    """a - b exactly as (int, shift) meaning int / 2**shift."""
    an, ad = (0, 1) if a == 0.0 else _ratio(a)
    bn, bd = (0, 1) if b == 0.0 else _ratio(b)
    D = max(ad, bd)
    return an * (D // ad) - bn * (D // bd), D.bit_length() - 1


# ---------------------------------------------------------------- ulp / nextafter / fma

def _next_up(x):
    if _isnan(x) or x == inf:
        return x
    if x == 0.0:
        return 5e-324
    b = _bits(x)
    return _from_bits(b + 1 if x > 0 else b - 1)


def _next_down(x):
    return -_next_up(-x)


def nextafter(x, y, /, *, steps=None):
    """Return the floating-point value the given number of steps after x towards y."""
    x = _f(x)
    y = _f(y)
    if steps is None:
        if _isnan(x):
            return x
        if _isnan(y):
            return y
        if x == y:
            return y
        return _next_up(x) if y > x else _next_down(x)
    steps = _index(steps)
    if steps < 0:
        raise ValueError("steps must be a non-negative integer")
    if steps == 0:
        return x
    if _isnan(x):
        return x
    if _isnan(y):
        return y
    # map to ordered integers
    def key(v):
        b = _bits(v)
        return -(b & ((1 << 63) - 1)) if b >> 63 else b
    def unkey(k):
        return _from_bits(k) if k >= 0 else _from_bits((-k) | (1 << 63))
    kx = key(x)
    ky = key(y)
    if kx == ky:
        return y
    if ky > kx:
        return y if ky - kx <= steps else unkey(kx + steps)
    return y if kx - ky <= steps else unkey(kx - steps)


def ulp(x, /):
    """Return the value of the least significant bit of the float x."""
    x = _f(x)
    if _isnan(x):
        return x
    x = abs(x)
    if _isinf(x):
        return x
    x2 = _next_up(x)
    if _isinf(x2):
        x2 = _next_down(x)
        return x - x2
    return x2 - x


def fma(x, y, z, /):
    """Fused multiply-add operation."""
    x = _f(x)
    y = _f(y)
    z = _f(z)
    if not (_isfinite(x) and _isfinite(y) and _isfinite(z)):
        if _isnan(x) or _isnan(y) or _isnan(z):
            return nan
        if (_isinf(x) and y == 0.0) or (_isinf(y) and x == 0.0):
            raise ValueError("invalid operation in fma")
        if _isinf(x) or _isinf(y):
            p = x * y
            if _isinf(z) and (p > 0) != (z > 0):
                raise ValueError("invalid operation in fma")
            return p
        return z
    if x == 0.0 or y == 0.0:
        p = x * y
        if z == 0.0:
            return p + z
        return z
    xn, xd = _ratio(x)
    yn, yd = _ratio(y)
    pn = xn * yn
    pd = xd * yd
    if z == 0.0:
        num, den = pn, pd
    else:
        zn, zd = _ratio(z)
        D = max(pd, zd)
        num = pn * (D // pd) + zn * (D // zd)
        den = D
    if num == 0:
        return 0.0
    try:
        r = num / den
    except OverflowError:
        raise OverflowError("overflow in fma") from None
    if r == 0.0 and num < 0:
        return -0.0
    return r


def _isclose(a, b, *, rel_tol=1e-09, abs_tol=0.0):
    """Determine whether two floating-point numbers are close in value."""
    a = _f(a)
    b = _f(b)
    rel_tol = _f(rel_tol)
    abs_tol = _f(abs_tol)
    if rel_tol < 0.0 or abs_tol < 0.0:
        raise ValueError("tolerances must be non-negative")
    if a == b:
        return True
    if _isinf(a) or _isinf(b):
        return False
    diff = abs(b - a)
    return ((diff <= abs(rel_tol * b)) or (diff <= abs(rel_tol * a))
            or diff <= abs_tol)


class _Builtin:
    """Callable without __get__, so it does not bind as a method (like a C function)."""

    def __init__(self, fn, name):
        self._fn = fn
        self.__name__ = self.__qualname__ = name
        self.__doc__ = fn.__doc__

    def __call__(self, /, *args, **kwargs):
        return self._fn(*args, **kwargs)

    def __repr__(self):
        return f"<built-in function {self.__name__}>"


isclose = _Builtin(_isclose, "isclose")
