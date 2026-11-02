class T:
    count = 0
    def __init__(self):
        self._v = 0
    @property
    def v(self):
        return self._v
    @v.setter
    def v(self, val):
        self._v = val * 2
    @classmethod
    def make(cls):
        cls.count += 1
        return cls()
    @staticmethod
    def add(a, b):
        return a + b
t = T.make(); t.v = 5
print(t.v, T.count, T.add(1, 2), t.add(3, 4), type(T.__dict__["make"]).__name__)
try:
    del t.v
except AttributeError as e:
    print("AttributeError")
class Slotted:
    __slots__ = ("a",)
s = Slotted(); s.a = 1
try:
    s.b = 2
except AttributeError:
    print("no b")
