import math

vals = [0.0, -0.0, 0.5, 1.0, 2.0, -3.5, 1e-300, 1e300, 123.456]
for name in ["sin", "cos", "tan", "atan", "exp", "expm1", "sqrt", "log", "log2",
             "log10", "log1p", "sinh", "cosh", "tanh", "asinh", "erf", "erfc",
             "gamma", "lgamma", "cbrt", "acos", "asin", "atanh", "acosh"]:
    for v in vals:
        try:
            print(name, v, f"{getattr(math, name)(v):.13g}")
        except (ValueError, OverflowError) as e:
            print(name, v, type(e).__name__, e)
print(math.atan2(1.0, -2.0), math.atan2(-0.0, -0.0), math.hypot(3, 4, 12))
print(math.fsum([1e100, 1.0, -1e100, 1e-100]), math.sumprod([1, 2.5], [3, 4]))
print(math.fma(0.1, 10, -1), math.nextafter(1.0, 0.0, steps=3), math.ulp(1e300))
print(math.factorial(30), math.comb(100, 37), math.perm(10, 3), math.isqrt(10**40 + 1))
print(math.gcd(12, 18, 27), math.lcm(4, 6, 10), math.log(10**500), math.log2(2**1000))
print(math.frexp(-12.5), math.ldexp(0.75, -1074), math.modf(-2.25), math.fmod(-7.0, 3.0))
print(math.remainder(5.0, 2.0), math.remainder(7.0, 2.0), math.pow(-2.0, 3.0), math.copysign(1, -0.0))
print(math.floor(-2.5), math.ceil(2.1), math.trunc(-2.9), math.dist((1, 2), (4, 6)))
for f, a in [(math.sqrt, (-1,)), (math.log, (0,)), (math.fsum, ([math.inf, -math.inf],))]:
    try:
        f(*a)
    except ValueError as e:
        print(e)
import math.integer
print(math.integer.__name__, math.integer.factorial(5))
try:
    math.fsum([1e308, 1e308, -1e308])
except OverflowError as e:
    print(type(e).__name__, e)
print(math.log(2**2000, 3))
try:
    math.log(5, 1)
except ZeroDivisionError as e:
    print(type(e).__name__, e)
print([n for n in dir(math.integer) if n.startswith("_") and n not in ("__doc__", "__loader__", "__name__", "__package__", "__spec__", "__file__")])
