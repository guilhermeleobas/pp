import inspect, pickle, sys, types
mod = types.ModuleType("m3_pickle_mod")
sys.modules["m3_pickle_mod"] = mod
exec("class C:\n    def __init__(self): self.a = 1\n", mod.__dict__)
C = mod.C
C()
for proto in range(2, 6):
    data = pickle.dumps(C(), proto)
    print(proto, data.hex(), pickle.loads(data).a)
    print(pickle.dumps(C, proto).hex())
print(type(getattr(C, "__qualname__")), type(getattr(C, "__qualname__", None)), type(C.__qualname__))
print(getattr(C, "nope", 5), getattr(C, "__name__"))
try: getattr(C, "nope")
except AttributeError as e: print(e)
print(getattr(C, "__qualname__") is getattr(C, "__qualname__"), C.__qualname__ is C.__qualname__)
print(sorted(a.name for a in inspect.classify_class_attrs(C) if a.name.startswith("__q")))
del sys.modules["m3_pickle_mod"]
