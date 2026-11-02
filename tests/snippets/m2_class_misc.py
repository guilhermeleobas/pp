class Base:
    def __repr__(self):
        return f"<{type(self).__name__} {self.__dict__}>"
    def __getattr__(self, name):
        return f"missing:{name}"
    def __setattr__(self, k, v):
        object.__setattr__(self, k, v * 2 if isinstance(v, int) else v)
b = Base(); b.n = 4
print(b, b.nope)
class Num(int):
    def __new__(cls, v):
        return super().__new__(cls, v + 1)
    def double(self): return self * 2
print(Num(3), Num(3).double(), type(Num(1) + 1).__name__)
class L(list):
    def append(self, x):
        super().append(x * 10)
l = L(); l.append(1); l.extend([2]); print(l)
class Outer:
    class Inner:
        pass
    def method(self):
        return __class__.__name__
print(Outer.Inner.__qualname__, Outer().method())
class E(Exception):
    def __str__(self): return "custom E"
try:
    raise E()
except Exception as e:
    print(e, isinstance(e, E))
print(type("Dyn", (Base,), {"k": 1})().k)
