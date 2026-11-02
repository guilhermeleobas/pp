def counter():
    n = 0
    def inc(step=1):
        nonlocal n
        n += step
        return n
    return inc
c = counter()
c(); c(); print(c(10))
print(c.__closure__[0].cell_contents, type(c.__closure__[0]).__name__)
fs = [lambda i=i: i * i for i in range(4)]
print([f() for f in fs])
late = [lambda: i for i in range(3)]
print([f() for f in late])
def outer():
    x = 1
    def mid():
        def inner():
            return x
        return inner
    x = 2
    return mid()()
print(outer())
def unbound():
    def g():
        return y
    try:
        g()
    except NameError as e:
        print(type(e).__name__, e)
    y = 1
unbound()
