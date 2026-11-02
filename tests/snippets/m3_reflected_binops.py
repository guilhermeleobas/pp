class A:
    def __add__(self, o): print("A.add"); return "A+"
    def __radd__(self, o): print("A.radd"); return "A.r"
class B(A):
    def __radd__(self, o): print("B.radd"); return "B.r"
class C:
    def __radd__(self, o): print("C.radd"); return "C.r"
print(A() + B())
print(A() + C())
print(1 + C())
print(C() + A())
class N:
    def __add__(self, o): return NotImplemented
    def __radd__(self, o): return NotImplemented
try: N() + N()
except TypeError as e: print(e)
try: N() + 1
except TypeError as e: print(e)
try: 1 + N()
except TypeError as e: print(e)
try: [] + N()
except TypeError as e: print(e)
try: N() ** 2
except TypeError as e: print(e)
try: pow
except: pass
class X(int):
    def __radd__(self, o): print("X.radd"); return 0
print(1 + X(2))
print(X(2) + 1)
class Y(int):
    def __add__(self, o): print("Y.add"); return 5
print(Y(1) + 1, 1 + Y(1))
try: -N()
except TypeError as e: print(e)
try: N() < N()
except TypeError as e: print(e)
