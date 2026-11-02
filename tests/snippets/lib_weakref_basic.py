# weakref behaviour that holds on the host and under pp's never-dying references
import re
import weakref


def show(f):
    try:
        r = f()
    except Exception as e:
        print(type(e).__name__, re.sub(r"0x[0-9a-f]+", "0x", str(e)))
    else:
        print("ok", re.sub(r"0x[0-9a-f]+", "0x", repr(r)))


class C:
    def __del__(self):
        print("del")


weakref.ref(C())          # the ref is dropped at once: nothing pins the object
print("after")


class D:
    pass


class Slots:
    __slots__ = ()


d = D()
r = weakref.ref(d, print)
print(weakref.getweakrefcount(d))
weakref.ref(d)
weakref.proxy(d)
print(weakref.getweakrefcount(d))
del r
print(weakref.getweakrefcount(d))
print(weakref.getweakrefcount(1), weakref.getweakrefcount(Slots()))

show(lambda: weakref.ref(d))
show(lambda: weakref.proxy(d))
show(lambda: weakref.ref(1))
show(lambda: weakref.ref(Slots()))
show(lambda: weakref.proxy([]))
show(lambda: weakref.ref(len))
show(lambda: weakref.ref(D))
show(lambda: weakref.proxy(weakref.ref))
show(lambda: weakref.ProxyType(d))
show(lambda: weakref.ref())
show(lambda: weakref.ref(d, None, 3))

# equality, hash, callbacks
a, b = D(), D()
print(weakref.ref(a) == weakref.ref(a), weakref.ref(a) == weakref.ref(b), hash(weakref.ref(a)) == hash(a))
print(weakref.ref(a, print).__callback__ is print, weakref.ref(a).__callback__)


class NoHash:
    __hash__ = None


nh = NoHash()
show(lambda: hash(weakref.ref(nh)))
show(lambda: hash(weakref.proxy(a)))


class L:
    def __init__(self):
        self.v = [1, 2]

    def __iadd__(self, o):
        return o

    def __ifloordiv__(self, o):
        return 21

    def __len__(self):
        return 5


l = L()
p = weakref.proxy(l)
print(len(p), p.v, bool(p))
p += 3
print(p)
p = weakref.proxy(l)
p //= 5
print(p)
