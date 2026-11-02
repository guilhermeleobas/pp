def f():
    try:
        raise ValueError("a")
    finally:
        try:
            raise KeyError("b")
        except KeyError as e:
            print("inner", repr(e.__context__))
try: f()
except ValueError as e: print("outer", repr(e), e.__context__)
def g():
    try:
        raise ValueError("a")
    finally:
        raise TypeError("b")
try: g()
except TypeError as e: print(repr(e.__context__), e.__context__.__context__)
def h():
    for i in range(2):
        try:
            raise ValueError(i)
        finally:
            continue
    return "h-done"
print(h())
def r():
    try:
        return "try"
    finally:
        print("fin")
print(r())
def over():
    try: return 1
    finally: return 2
print(over())
try:
    try: raise ValueError("1")
    except ValueError as e:
        try: raise e
        except ValueError: raise
except ValueError as e: print(e.__context__)
try:
    try: raise A if False else ValueError("x")
    except ValueError as e:
        raise e from None
except ValueError as e: print(e.__cause__, e.__suppress_context__, e.__context__)
a = ValueError("loop")
try:
    try: raise a
    except ValueError:
        raise KeyError("k")
except KeyError as e:
    try:
        raise a
    except ValueError as e2:
        print(e2.__context__ is None, a.__context__)
