def f(n):
    out = []
    try:
        try:
            out.append("try")
            if n == 1:
                raise ValueError("v")
            if n == 2:
                return out + ["ret"]
        except ValueError as e:
            out.append(("exc", str(e)))
        else:
            out.append("else")
        finally:
            out.append("finally")
    finally:
        out.append("outer")
    return out
for n in range(3):
    print(f(n))
def g():
    for i in range(3):
        try:
            if i == 1:
                continue
            if i == 2:
                break
        finally:
            print("fin", i)
    try:
        return 1
    finally:
        print("returning")
print(g())
try:
    e = 1
    raise KeyError("k")
except (TypeError, KeyError) as e:
    print(repr(e))
print("e" in dir())
