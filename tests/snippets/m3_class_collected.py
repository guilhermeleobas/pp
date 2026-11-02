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
