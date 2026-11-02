class Meta(type):
    def __getattribute__(cls, n):
        if n.startswith("x"): print("meta ga", n)
        return super().__getattribute__(n)
    def __getattr__(cls, n): return "meta-fb-" + n
    def __instancecheck__(cls, o): print("ic", o); return o == 1
    def __subclasscheck__(cls, s): print("sc", s); return True
    def __call__(cls, *a): print("call"); return 42
    def __len__(cls): return 7
    def __getitem__(cls, k): return ("mg", k)
    def __iter__(cls): return iter("ab")
    def __contains__(cls, x): return x == "in"
    def __repr__(cls): return "<M>"
    def __or__(cls, o): return "or"
class C(metaclass=Meta):
    xa = 1
print(C.xa, C.yb, C.__name__)
print(isinstance(1, C), isinstance(2, C), issubclass(int, C))
print(C(), len(C), C[3], list(C), "in" in C, repr(C), C | 1)
class P:
    def __getattr__(self, n): return "inst-fb"
print(P().xa, C.xa)
class N(type):
    def __new__(m, name, bases, ns):
        print("new", name); return super().__new__(m, name, bases, ns)
    def __init__(c, *a): print("init"); super().__init__(*a)
    @classmethod
    def __prepare__(m, name, bases): print("prep"); return {"pre": 1}
class Z(metaclass=N): pass
print(Z.pre)
print(isinstance(C, Meta), type(C) is Meta, C.__class__.__name__)
try: isinstance(1, 2)
except TypeError as e: print(e)
