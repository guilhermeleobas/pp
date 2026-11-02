import gc, weakref
def mk():
    class B:
        def f(self): return 1
    class K(B):
        def f(self): return super().f()
    k = K()
    print(k.f(), k.f(), len(k.__class__.__mro__))
    return weakref.ref(K), weakref.ref(B)
k, b = mk()
gc.collect()
print(k() is None, b() is None)
# a class the VM never saw instantiated is collected too
def mk2():
    class C:
        __slots__ = ()
        def __len__(self): return 3
    return weakref.ref(C), len(C())
r, n = mk2(); gc.collect(); print(r() is None, n)
# Protocol subclasses and classes defined with type() are collected as well
import typing
def mk3(base):
    class K(base):
        def f(self): return super().f()
    class B(base):
        def f(self): return 1
    K().f
    T = type("T", (), {"f": lambda self: 2})
    T().f()
    return weakref.ref(K), weakref.ref(T)
class Proto(typing.Protocol):
    def f(self): ...
a, t = mk3(Proto); gc.collect(); print(a() is None, t() is None)
