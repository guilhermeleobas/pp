class MyErr(Exception):
    def __init__(self, a, b):
        super().__init__(a, b)
        self.a = a
try:
    try:
        {}["x"]
    except KeyError:
        raise ValueError("during")
except ValueError as e:
    print(repr(e.__context__), e.__cause__, e.__suppress_context__)
try:
    try:
        1 / 0
    except ZeroDivisionError as z:
        raise MyErr(1, 2) from z
except MyErr as e:
    print(e.args, e.a, type(e.__cause__).__name__, e.__suppress_context__)
try:
    raise TypeError("t") from None
except TypeError as e:
    print(e.__cause__, e.__suppress_context__, e.__context__)
def reraise():
    try:
        raise IndexError("i")
    except IndexError:
        print("handling")
        raise
try:
    reraise()
except IndexError as e:
    print("bare raise:", e)
try:
    raise ValueError
except ValueError as e:
    print(type(e).__name__, e.args)
