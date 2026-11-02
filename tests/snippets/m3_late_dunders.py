class C: pass
c = C()
def add(self, o): return "added"
C.__add__ = add
print(c + 1)
C.__len__ = lambda self: 3
print(len(c), bool(c))
C.__getitem__ = lambda self, k: k
print(c[5])
c.__sub__ = lambda o: "inst"
try: c - 1
except TypeError as e: print(e)
c.__len__ = lambda: 99
print(len(c))
c.__getitem__ = lambda k: "inst"
print(c[1])
del C.__add__
try: c + 1
except TypeError as e: print(e)
C.__eq__ = lambda s, o: "eq!"
print(c == 1, c != 1)
C.__call__ = lambda s: "called"
print(c())
C.__str__ = lambda s: "STR"
print(str(c), f"{c}")
C.__iter__ = lambda s: iter([1, 2])
print(list(c))
C.__contains__ = lambda s, x: "ctn"
print(5 in c)
C.__getattr__ = lambda s, n: "ga-" + n
print(c.zzz)
C.__bool__ = lambda s: False
print(bool(c))
class D(C): pass
print(len(D()), D() + 1 if hasattr(D, "__add__") else "noadd")
C.__hash__ = None
try: hash(c)
except TypeError as e: print(e)
