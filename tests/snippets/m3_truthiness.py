class A:
    def __len__(self): print("len"); return 0
class B(A):
    def __bool__(self): print("bool"); return True
class C:
    def __bool__(self): return 1
class D:
    def __len__(self): return -1
class E:
    def __len__(self): return 2**70
class F:
    def __bool__(self): return False
    def __len__(self): return 5
print(bool(A()), bool(B()), not A(), 1 if B() else 2)
for k in (C, D, E):
    try: print(bool(k()))
    except Exception as e: print(type(e).__name__, e)
print(bool(F()), F() or "x", F() and "y")
class G:
    def __len__(self): return True
print(bool(G()), len(G()))
class H:
    __bool__ = None
try: bool(H())
except TypeError as e: print(e)
class I:
    def __bool__(self): raise ValueError("vb")
try:
    if I(): pass
except ValueError as e: print(e)
x = A()
while x: break
print("done")
