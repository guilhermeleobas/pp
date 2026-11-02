try:
    raise ExceptionGroup("eg", [ValueError(1), TypeError(2), ValueError(3)])
except* ValueError as g:
    print("V", [str(e) for e in g.exceptions])
except* TypeError as g:
    print("T", [str(e) for e in g.exceptions])
try:
    try:
        raise ExceptionGroup("eg", [KeyError("k"), OSError("o")])
    except* KeyError:
        print("got key")
except ExceptionGroup as rest:
    print("rest", [type(e).__name__ for e in rest.exceptions])
try:
    raise ValueError("naked")
except* ValueError as g:
    print(type(g).__name__, g.exceptions)
