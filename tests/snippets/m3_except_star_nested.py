import sys
try:
    raise KeyError("outer")
except KeyError:
    try:
        raise ExceptionGroup("eg", [ValueError(1), TypeError(2)])
    except* ValueError as e:
        print("V", repr(e), repr(e.exceptions[0].__context__))
    except* TypeError as e:
        print("T", repr(e))
    print(repr(sys.exception()))
print(sys.exception())
try:
    try:
        raise ExceptionGroup("eg", [ValueError(1), OSError(2)])
    except* ValueError:
        pass
except ExceptionGroup as e:
    print(repr(e), repr(e.exceptions[0]), e.__context__)
try:
    try:
        raise ExceptionGroup("eg", [ValueError(1)])
    except* ValueError as e:
        raise RuntimeError("in star")
except BaseException as e:
    print(type(e).__name__, repr(e.__context__), type(e.__context__))
try:
    raise ExceptionGroup("a", [ValueError(1), ExceptionGroup("b", [TypeError(2), KeyError(3)])])
except* (TypeError, KeyError) as e:
    print(repr(e))
except* ValueError as e:
    print("val", repr(e))
try:
    try: raise ValueError("p")
    except ValueError:
        try: raise ExceptionGroup("g", [KeyError("k")])
        except* KeyError as e:
            raise
except ExceptionGroup as e:
    print(repr(e), repr(e.exceptions[0].__context__))
