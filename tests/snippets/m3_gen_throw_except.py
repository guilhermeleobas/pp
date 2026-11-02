def g():
    try:
        yield 1
    except ValueError as e:
        print("g caught", repr(e), repr(e.__context__))
        yield 2
    finally:
        print("g finally")
def run():
    x = g(); next(x)
    try:
        raise KeyError("outer")
    except KeyError:
        print(x.throw(ValueError("thrown")))
        import sys
        print(repr(sys.exception()))
    print(repr(sys.exception()))
    x.close()
run()
def h():
    try:
        yield
    except Exception as e:
        raise RuntimeError("from h") from e
y = h(); next(y)
try:
    y.throw(TypeError("t"))
except RuntimeError as e:
    print(repr(e.__cause__), repr(e.__context__), e.__suppress_context__)
def k():
    yield 1
z = k(); next(z)
try:
    try: raise OSError("ctx")
    except OSError: z.throw(IndexError("ix"))
except IndexError as e:
    print(repr(e.__context__))
def sub():
    try: yield 1
    except ValueError: yield "sub-caught"
def deleg():
    yield from sub()
d = deleg(); next(d)
try:
    raise EOFError
except EOFError:
    print(d.throw(ValueError("v")))
try: d.throw(ZeroDivisionError)
except ZeroDivisionError as e: print("ZDE", e.__context__)
