import warnings
def g():
    try:
        yield
    except ValueError:
        yield "caught"
x = g(); next(x)
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    print(x.throw(ValueError, ValueError("a"), None))
print(len(w), w[0].category.__name__, "throw() is deprecated" in str(w[0].message))
y = g(); next(y)
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    print(y.throw(ValueError("b")))
print(len(w))
