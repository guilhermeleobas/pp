from collections import OrderedDict, deque

print(vars(OrderedDict(a=1)))
class S(OrderedDict): pass
s = S(a=1); s.x = 2
print(vars(s), s.__reduce__()[2], s.copy().x if hasattr(s.copy(), "x") else None)
o = OrderedDict(a=1, b=2)
try:
    for k in o: o.move_to_end('a')
except RuntimeError as e: print(e)
o = OrderedDict(a=1, b=2)
try:
    for k in o: o['c']=1
except RuntimeError as e: print(e)
try:
    for k in reversed(o): o.move_to_end(k, False)
except RuntimeError as e: print(e)
o = OrderedDict(a=1, b=2, c=3)
try:
    for k in o: del o['c']
except RuntimeError as e: print(e)
o = OrderedDict(a=1)
for k in o: o.move_to_end('a')
print(list(o), [n for n in dir(deque()) if n.startswith('_deque')])
