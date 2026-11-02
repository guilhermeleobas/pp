class A:
    def __setattr__(self, n, v):
        print("set", n, v)
        object.__setattr__(self, n, v * 2)
    def __delattr__(self, n):
        print("del", n)
        object.__delattr__(self, n)
a = A()
a.x = 2
print(a.x)
del a.x
try: del a.x
except AttributeError as e: print("AE", e)
a.__dict__["y"] = 1
print(a.y)
class B:
    def __setattr__(self, n, v): print("B set", n)
b = B(); b.q = 1
print(b.__dict__)
object.__setattr__(b, "q", 7)
print(b.q)
try: object.__setattr__(1, "x", 1)
except (AttributeError, TypeError) as e: print(type(e).__name__)
class P:
    @property
    def v(self): return 1
    @v.setter
    def v(self, x): print("psetter", x)
class Q(P):
    def __setattr__(self, n, v):
        print("Q", n); super().__setattr__(n, v)
Q().v = 3
try: object.__setattr__(Q(), "v", 4)
except Exception as e: print(type(e).__name__)
