class A:
    def __getattr__(self, n):
        print("getattr", n)
        return n.upper()
    @property
    def p(self):
        raise AttributeError("inside p")
    @property
    def q(self):
        return self.missing_inner
    real = 1
a = A()
print(a.real, a.foo, a.p, a.q)
class B:
    def __getattribute__(self, n):
        print("ga", n)
        if n == "boom": raise AttributeError(n)
        return object.__getattribute__(self, n)
    def __getattr__(self, n):
        return "fallback-" + n
b = B()
b.x = 1
print(b.x, b.boom, b.nope)
print(getattr(b, "zzz", "d"), hasattr(b, "boom"))
class E:
    def __getattribute__(self, n):
        raise KeyError(n)
    def __getattr__(self, n): return 1
try: E().x
except KeyError as e: print("KeyError", e)
class F:
    def __getattr__(self, n): raise ValueError(n)
try: F().x
except ValueError as e: print("VE", e)
print(hasattr(A(), "x"))
try: hasattr(F(), "x")
except ValueError: print("hasattr VE")
