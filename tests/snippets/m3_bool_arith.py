a = [True, False, True]
x, y = a[0], a[1]
print(x + y, x * 3, 3 * x, x + x, x - y, x * y, -x, x / True)
t = 0
for v in a: t = t + v
print(t)
import itertools
print(list(itertools.accumulate(a)), list(itertools.accumulate(a, lambda p, q: p * q)))
z = x
z += y; print(z, type(z))
print(sum(a), [True] * 2, True * [1], "ab" * True)
