class A:
    def __eq__(self, o): return True
print(A.__hash__)
try: hash(A())
except TypeError as e: print(e)
try: {A()}
except TypeError as e: print(e)
try: {A(): 1}
except TypeError as e: print(e)
class B(A):
    __hash__ = object.__hash__
print(isinstance(hash(B()), int), len({B(), B()}))
class C:
    def __eq__(self, o): return True
    def __hash__(self): return 7
print(hash(C()), len({C(), C()}))
class D:
    __hash__ = None
try: hash(D())
except TypeError as e: print(e)
class E(C):
    def __eq__(self, o): return False
print(E.__hash__)
class F:
    def __hash__(self): return -1
print(hash(F()))
class G:
    def __hash__(self): return "x"
try: hash(G())
except TypeError as e: print(e)
class H:
    def __hash__(self): return 2**70
print(hash(H()) == hash(2**70))
print(isinstance([], object), hash(1) == hash(1.0))
