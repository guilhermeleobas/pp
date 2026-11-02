class C:
    def __call__(self, *a, **k): return ("call", a, k)
c = C()
print(c(1, x=2), c())
c.__call__ = lambda: "inst"
print(c(1))
class D:
    f = C()
    g = len
    h = lambda self: "h"
d = D()
print(d.f(1), d.g([1, 2]) if False else "skip", d.h())
try: d.g([1])
except TypeError as e: print("TE")
class E:
    s = staticmethod(C())
    k = classmethod(C())
    t = staticmethod(len)
print(E.s(1), E().s(2), E.t("ab"))
r = E.k(5)
print(r[0], len(r[1]))
class Meta(type):
    def __call__(cls, *a): print("meta call", a); return super().__call__(*a)
class M(metaclass=Meta):
    def __init__(self, x): print("init", x)
M(3)
try: 5()
except TypeError as e: print(e)
class NC: pass
try: NC()()
except TypeError as e: print(e)
class SC:
    __call__ = staticmethod(lambda: "static")
print(SC()())
class Dd:
    class _D:
        def __get__(self, o, t=None): return lambda *a: "via-get"
    __call__ = _D()
print(Dd()(1))
