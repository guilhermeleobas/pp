import sys
try:
    raise OSError("os")
except OSError:
    print(type(sys.exception()).__name__, sys.exc_info()[0].__name__)
print(sys.exception())
def f():
    try:
        raise KeyError(1)
    except KeyError:
        return sys.exc_info()[1].args
print(f(), sys.exc_info())
