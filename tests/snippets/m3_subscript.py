class S:
    def __getitem__(self, k): print("get", k); return k
    def __setitem__(self, k, v): print("set", k, v)
    def __delitem__(self, k): print("del", k)
s = S()
s[1:2]; s[::3]; s[1:2, 3]; s[...]; s[1, 2]; s[:]
s[1:2] = 0
s[::2] = 1
del s[1:]
s[1] += 1
sl = slice(1, None); s[sl]
class I:
    def __index__(self): return 1
l = [10, 20, 30]
print(l[I()], l[I():], "abc"[I()], (1, 2)[I()])
l[I()] = 5; print(l)
try: l["a"]
except TypeError as e: print(e)
try: l[1.0]
except TypeError as e: print(e)
class BI:
    def __index__(self): return "x"
try: l[BI()]
except TypeError as e: print(e)
print(l[True], bin(I()) if False else hex(I()), range(5)[I()])
class Both(list):
    def __getitem__(self, k): print("Both", k); return list.__getitem__(self, k)
x = Both([1, 2, 3]); print(x[1], x[1:])
try: 1[0]
except TypeError as e: print(e)
try: s2 = object(); s2[0] = 1
except TypeError as e: print(e)
try: del (1,)[0]
except TypeError as e: print(e)
class Sl:
    def __getslice__(self, a, b): return "old"
    def __getitem__(self, k): return type(k).__name__
print(Sl()[1:2])
