class Registry:
    items = []
    def __init_subclass__(cls, tag=None, **kw):
        super().__init_subclass__(**kw)
        Registry.items.append((cls.__name__, tag))
class P(Registry, tag="p"): pass
class Q(P): pass
print(Registry.items)
class Meta(type):
    def __new__(mcls, name, bases, ns, **kw):
        ns["made_by"] = mcls.__name__
        return super().__new__(mcls, name, bases, ns)
    def __call__(cls, *a):
        print("Meta.__call__", a)
        return super().__call__(*a)
class M(metaclass=Meta):
    def __init__(self, v):
        self.v = v
m = M(3)
print(m.v, M.made_by, type(M).__name__)
class D:
    x: int = 1
    y: str
print(D.__annotations__ if hasattr(D, "__annotations__") else None)
