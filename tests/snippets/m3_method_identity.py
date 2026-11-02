class A:
    def f(self): return 1
    @staticmethod
    def s(): return 2
    @classmethod
    def c(cls): return cls
a = A()
print(a.f == a.f, a.f is a.f, A.f is A.f, a.f.__func__ is A.f, a.f.__self__ is a)
print(A.s is A.s, a.s is A.s, a.c == A.c, a.c is A.c)
print(type(A.f).__name__, type(a.f).__name__, type(A.c).__name__)
b = A()
print(a.f == b.f, hash(a.f) == hash(a.f))
print(A.f(a), A.c() is A, a.c() is A)
class B(A): pass
print(B.c() is B, B().c() is B, B.f is A.f)
try: A.f()
except TypeError as e: print(e)
try: a.f(1)
except TypeError as e: print(e)
print(A.__dict__["f"] is A.f, type(A.__dict__["s"]).__name__)
a.g = a.f
print(a.g())
m = A.f.__get__(a)
print(m == a.f)
print(A.s.__get__(1) is A.s)
print(list.append.__get__([], list).__name__)
