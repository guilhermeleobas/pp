class A:
    def __add__(self, o): print("add"); return "add"
    def __radd__(self, o): print("radd"); return "radd"
a = A(); a += 1; print(a)
b = 1; b += A(); print(b)
class I:
    def __iadd__(self, o): print("iadd"); return NotImplemented
    def __add__(self, o): print("add"); return "I.add"
i = I(); i += 1; print(i)
class J:
    def __iadd__(self, o): print("iadd"); return self
j = J(); k = j; j += 1; print(j is k)
class K:
    def __iadd__(self, o): return NotImplemented
k = K()
try: k += 1
except TypeError as e: print(e)
l = [1]; m = l; l += [2]; print(m, l is m)
t = (1,); u = t; t += (2,); print(u, t)
s = {1}; s |= {2}; print(s)
class R:
    def __radd__(self, o): print("R.radd"); return "R"
x = 5; x += R(); print(x)
x = [1]
x *= 2; print(x)
class M:
    def __imul__(self, o): print("imul"); return 99
m = M(); m *= 3; print(m)
class L(list):
    def __iadd__(self, o): print("L.iadd"); return list.__iadd__(self, o)
q = L(); q += [1]; print(q)
