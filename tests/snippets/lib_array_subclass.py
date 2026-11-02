import array
class S(array.array): pass
a=S('i',[1,2]);b=S('i',[3])
print(type(a+b).__name__,type(a*2).__name__,type(a[:1]).__name__,type(a[::-1]).__name__,type(a.__copy__()).__name__)
import copy
print(type(copy.copy(a)).__name__,type(copy.deepcopy(a)).__name__)
for o in (array.array('i'),a):
    try: hash(o)
    except TypeError as e: print(e)
    try: o.append('x')
    except TypeError as e: print(e)
    try: o+1
    except TypeError as e: print(e)
    try: o.extend(array.array('d'))
    except TypeError as e: print(e)
    try: o.frombytes(1)
    except TypeError as e: print(e)
