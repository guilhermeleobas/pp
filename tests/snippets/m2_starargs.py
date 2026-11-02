def f(*args, **kwargs):
    return args, kwargs
print(f(*range(3), *"ab", k=1, **{"j": 2}))
a, *b, c = range(6)
print(a, b, c)
print([*range(2), *{3: 0}], {**{"a": 1}, "b": 2, **dict(c=3)})
def kw_only(*, a, b=2): return a + b
print(kw_only(**{"a": 1}))
args = (1, 2)
print(max(*args), print is print, int("ff", base=16))
