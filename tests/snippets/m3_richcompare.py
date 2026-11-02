class A:
    def __eq__(self, o): print("A.eq"); return NotImplemented
class B:
    def __eq__(self, o): print("B.eq"); return NotImplemented
a, b = A(), B()
print(a == b, a != b, a == a, a != a)
class L:
    def __lt__(self, o): print("L.lt"); return NotImplemented
    def __gt__(self, o): print("L.gt"); return True
print(L() < L(), L() > L())
try: L() <= L()
except TypeError as e: print(e)
class P:
    def __lt__(self, o): print("P.lt"); return True
class Q(P):
    def __gt__(self, o): print("Q.gt"); return "q"
print(P() < Q(), Q() > P(), P() > Q())
class E:
    def __eq__(self, o): print("eq"); return True
print(E() != 1, E() == 1, 1 == E(), 1 != E())
class S:
    def __ne__(self, o): return "ne"
print(S() == S(), S() != S())
class N:
    def __eq__(self, o): return NotImplemented
print(N() == 1, N() != 1)
try: N() < 1
except TypeError as e: print(e)
class W:
    def __eq__(self, o): return [1]
print(W() == 1, W() != 1)
print((W() == 1) is not None, bool(W() == 1))
class X(int):
    def __eq__(self, o): print("X.eq"); return False
print(1 == X(1), X(1) == 1)
print([E()] == [1], (E(),) == (1,))
