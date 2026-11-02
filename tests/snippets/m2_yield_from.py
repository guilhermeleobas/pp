def inner():
    x = yield 1
    print("inner got", x)
    yield 2
    return "inner-ret"
def outer():
    r = yield from inner()
    print("r =", r)
    yield from [10, 20]
    yield from (c for c in "ab")
    return r
g = outer()
print(next(g), g.send("hi"), list(g))
def deleg():
    try:
        yield from inner()
    except KeyError as e:
        yield ("caught", e.args)
d = deleg(); next(d)
print(d.throw(KeyError("kk")))
def stopper():
    yield 1
    raise StopIteration
try:
    list(stopper())
except RuntimeError as e:
    print("RuntimeError", e)
