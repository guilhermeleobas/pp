class B:
    def f(self): return "B.f"
class K(B): pass
class L(K): pass
l = L()
print(l.f(), l.f(), getattr(l, "g", None))
B.f = lambda self: "B.f2"
print(l.f())
B.g = lambda self: "B.g"
print(l.g())
K.f = lambda self: "K.f"
print(l.f())
del K.f
print(l.f())
L.__bases__ = (B,)
print(l.f())
class M(B): pass
M.__bases__ = (object,)
try: M().f()
except AttributeError as e: print(e)
class Meta(type):
    order = 0
    def mro(cls):
        m = super().mro()
        return m if Meta.order == 0 else [m[0], *reversed(m[1:-1]), m[-1]]
class P1:
    def who(self): return "P1"
class P2:
    def who(self): return "P2"
class Both(P1, P2, metaclass=Meta): pass
print(Both().who(), [c.__name__ for c in Both.__mro__])
Meta.order = 1
class Both2(P1, P2, metaclass=Meta): pass
print(Both2().who(), [c.__name__ for c in Both2.__mro__])
Both.__bases__ = (P2, P1)
print(Both().who())
