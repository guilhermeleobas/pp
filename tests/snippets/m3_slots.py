class S:
    __slots__ = ("a", "b")
s = S()
try: s.a
except AttributeError as e: print("AE", e)
s.a = 1
print(s.a, type(S.a).__name__)
try: s.c = 1
except AttributeError as e: print("AE", e)
del s.a
try: del s.a
except AttributeError as e: print("AE", e)
class T(S):
    pass
t = T(); t.z = 3; t.a = 2
print(t.z, t.a, sorted(t.__dict__))
class U:
    __slots__ = ("x", "__dict__")
    x2 = 5
u = U(); u.x = 1; u.q = 2
print(u.x, u.q, u.x2)
class V:
    __slots__ = ("v",)
    v2 = 1
try:
    V().__dict__
except AttributeError as e: print("AE")
