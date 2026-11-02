import pickle
class C:
    def __init__(self): self.a = 1
C()
for proto in range(2, 6):
    data = pickle.dumps(C(), proto)
    print(proto, data.hex(), pickle.loads(data).a)
    print(pickle.dumps(C, proto).hex())
print(type(getattr(C, "__qualname__")), type(getattr(C, "__qualname__", None)), type(C.__qualname__))
print(getattr(C, "nope", 5), getattr(C, "__name__"))
try: getattr(C, "nope")
except AttributeError as e: print(e)
