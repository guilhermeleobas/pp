class CM:
    def __init__(self, name, suppress=False):
        self.name, self.suppress = name, suppress
    def __enter__(self):
        print("enter", self.name)
        return self.name.upper()
    def __exit__(self, t, v, tb):
        print("exit", self.name, t.__name__ if t else None, v)
        return self.suppress
with CM("a") as x, CM("b") as y:
    print(x, y)
with CM("s", True):
    raise ValueError("swallowed")
print("after")
try:
    with CM("n"):
        raise KeyError("k")
except KeyError as e:
    print("propagated", e)
def f():
    with CM("r"):
        return "ret"
print(f())
import contextlib
@contextlib.contextmanager
def ctx(v):
    print("setup")
    try:
        yield v
    except ZeroDivisionError:
        print("handled in gen")
    finally:
        print("teardown")
with ctx(5) as v:
    print(v)
    1 / 0
with contextlib.suppress(IndexError):
    [][1]
print("done")
