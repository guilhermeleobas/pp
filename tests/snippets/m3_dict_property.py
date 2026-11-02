class P:
    @property
    def __dict__(self): return {}
p = P()
p.q2 = 1
print(p.q2, hasattr(p, "q2"), p.__dict__)
del p.q2
print(hasattr(p, "q2"))
class Q(P):
    __slots__ = ()
q = Q(); q.z = 3; print(q.z)
