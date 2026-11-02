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
