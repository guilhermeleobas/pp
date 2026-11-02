class D:
    def __get__(self, o, t=None): return "data-get"
    def __set__(self, o, v): print("set", v)
class N:
    def __get__(self, o, t=None): return "nondata-get"
class C:
    d = D()
    n = N()
    x = 1
c = C()
c.__dict__["d"] = "inst-d"
c.__dict__["n"] = "inst-n"
c.__dict__["x"] = "inst-x"
print(c.d, c.n, c.x)
c.d = 5
c.n = "new"
print(c.d, c.n, c.__dict__["n"])
del c.n
print(c.n, C.n, C.x)
C.x = 2
print(c.x)
del c.x
print(c.x)
class RO:
    @property
    def p(self): return 1
try:
    RO().p = 2
except AttributeError as e:
    print("AE", e)
try:
    del RO().p
except AttributeError as e:
    print("AE", e)
