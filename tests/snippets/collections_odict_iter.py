from collections import OrderedDict
def chk(mk):
    o = OrderedDict(a=1)
    it = mk(o)
    o['b'] = 2
    try: next(it)
    except RuntimeError as e: print(e)
for mk in (iter, reversed, lambda o: iter(o.keys()), lambda o: iter(o.values()), lambda o: iter(o.items()),
           lambda o: reversed(o.keys()), lambda o: reversed(o.values()), lambda o: reversed(o.items())):
    chk(mk)
o = OrderedDict(a=1, b=2, c=3)
print(list(o), list(reversed(o)), list(o.values()), list(o.items()), list(reversed(o.items())), list(reversed(o.values())))
print(OrderedDict().__sizeof__(), [n for n in dir(o) if "OrderedDict__" in n])
print(len(o.keys() & {'a','z'}), 'b' in o.keys(), 2 in o.values(), ('a',1) in o.items(), repr(o.keys()), repr(o.items()))
