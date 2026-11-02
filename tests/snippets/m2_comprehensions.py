print([x * y for x in range(3) for y in range(x) if y])
print({x % 3 for x in range(10)})
print({k: v for k, v in zip("abc", range(3))})
print(sum(x for x in range(10) if x & 1))
print([[j for j in range(i)] for i in range(4)])
x = "outer"
print([x for x in range(2)], x)
g = (i * 2 for i in range(3))
print(next(g), list(g))
print(sorted({(a, b) for a in range(2) for b in "xy"}))
def f(n):
    return [lambda: k + n for k in range(2)]
print([h() for h in f(10)])
