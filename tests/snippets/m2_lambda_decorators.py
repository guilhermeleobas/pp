import functools
def trace(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        print("call", fn.__name__, a, k)
        return fn(*a, **k)
    return wrapper
def repeat(n):
    def deco(fn):
        def w(*a):
            return [fn(*a) for _ in range(n)]
        return w
    return deco
@trace
@repeat(2)
def sq(x):
    "doc"
    return x * x
print(sq(3), sq.__name__)
add = lambda a, b=1: a + b
print(add(2), add(2, 3), (lambda *a: a)(1, 2), add.__name__)
