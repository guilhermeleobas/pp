import functools
@functools.total_ordering
class V:
    def __init__(self, n): self.n = n
    def __eq__(self, o): return isinstance(o, V) and self.n == o.n
    def __hash__(self): return hash(self.n)
    def __lt__(self, o): return self.n < o.n
    def __repr__(self): return f"V{self.n}"
    def __add__(self, o): return V(self.n + o.n)
    def __len__(self): return self.n
    def __iter__(self): return iter(range(self.n))
    def __getitem__(self, i): return i * 10
    def __contains__(self, x): return x == 42
    def __bool__(self): return self.n != 0
    def __call__(self, k): return k + self.n
vs = [V(3), V(1), V(2)]
print(sorted(vs), max(vs), V(1) + V(2), len(V(4)), list(V(3)))
print({V(1), V(1), V(2)} == {V(1), V(2)}, V(2) >= V(1), V(1)[5], 42 in V(0), bool(V(0)))
print(sorted(vs, key=lambda v: -v.n), list(map(V(10), [1, 2])), str(V(7)))
print(V(1) == 1, V(1) != V(2), sum([1, 2], 0), [*V(2)], dict.fromkeys(V(2)))
