class Desc:
    def __set_name__(self, owner, name):
        print("set_name", owner.__name__, name)
    def __get__(self, o, t=None): return 1
class Base:
    def __init_subclass__(cls, flag=None, **kw):
        print("init_subclass", cls.__name__, flag, kw)
        super().__init_subclass__(**kw)
class K(Base, flag=3):
    a = Desc()
    b = Desc()
class K2(K): pass
class G:
    def __class_getitem__(cls, item):
        return (cls.__name__, item)
print(G[int], G[1, 2])
class H(G): pass
print(H["x"])
try: int[3]
except TypeError as e: print("TE")
print(list[int], type(list[int]).__name__)
try:
    class Bad(Base, nokw=1): pass
except TypeError as e: print("TE", e)
K.late = Desc()
print("late")
class W:
    def __set_name__(self, o, n): raise RuntimeError("sn")
try:
    class Z:
        w = W()
except Exception as e:
    print(type(e).__name__, type(e.__cause__))
