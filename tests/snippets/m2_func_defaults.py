def f(a, b=2, *args, c, d=4, **kw):
    return (a, b, args, c, d, sorted(kw.items()))
print(f(1, c=3))
print(f(1, 5, 6, 7, c=3, d=8, x=9, y=10))
print(f(*[1, 2, 3], **{"c": 0, "z": 1}))
def g(x, /, y, *, z=1):
    return x + y + z
print(g(1, 2), g(1, y=2, z=3))
print(f.__defaults__, f.__kwdefaults__, f.__name__, f.__qualname__)
def mut(x, acc=[]):
    acc.append(x)
    return acc
mut(1); print(mut(2))
