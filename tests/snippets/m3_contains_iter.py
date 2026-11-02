class Both:
    def __contains__(self, x): print("contains"); return "yes"
    def __iter__(self): print("iter"); return iter([1])
    def __getitem__(self, i): print("gi"); return 1
print(1 in Both(), 2 not in Both())
class It:
    def __iter__(self): print("iter"); return iter([1, 2])
    def __getitem__(self, i): print("gi"); return 1
print(2 in It(), 3 in It())
class GI:
    def __getitem__(self, i):
        print("gi", i)
        if i >= 3: raise IndexError
        return i * 10
print(20 in GI(), 5 in GI())
print(list(GI()), tuple(GI()), [*GI()])
a, b, c = GI(); print(a, b, c)
class NoIter:
    __iter__ = None
    def __getitem__(self, i): return 1
try: iter(NoIter())
except TypeError as e: print(e)
try: 1 in NoIter()
except TypeError as e: print(e)
class KE:
    def __getitem__(self, i): raise KeyError(i)
try: list(KE())
except KeyError as e: print("KeyError")
try: 1 in 5
except TypeError as e: print(e)
class BadIter:
    def __iter__(self): return 5
try: iter(BadIter())
except TypeError as e: print(e)
class NoNext:
    def __iter__(self): return self
try: list(NoNext())
except TypeError as e: print(e)
class Cnt:
    def __init__(self): self.i = 0
    def __iter__(self): return self
    def __next__(self):
        self.i += 1
        if self.i > 2: raise StopIteration
        return self.i
print(list(Cnt()), 2 in Cnt())
