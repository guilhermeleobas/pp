def gen(n):
    for i in range(n):
        got = yield i
        if got:
            print("got", got)
    return "done"
g = gen(3)
print(next(g), g.send("x"), next(g))
try:
    next(g)
except StopIteration as e:
    print("stop", e.value)
def echo():
    try:
        while True:
            try:
                v = yield
                print("echo", v)
            except ValueError as e:
                print("caught", e)
                yield "recovered"
    finally:
        print("closing")
e = echo(); next(e); e.send(1)
print(e.throw(ValueError("bad")))
e.close()
print(type(g).__name__, g.gi_running, g.gi_code.co_name)
def fib():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b
import itertools
print(list(itertools.islice(fib(), 10)))
print(list(zip(gen(3), "ab")), sum(gen(5)), sorted(gen(4), reverse=True))
