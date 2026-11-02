x = 1
def f():
    global x, newg
    x += 1
    newg = "g"
f(); print(x, newg)
def g():
    y = 1
    del y
    try:
        print(y)
    except UnboundLocalError as e:
        print(type(e).__name__)
g()
def h():
    print(x)
    x = 2
try:
    h()
except UnboundLocalError:
    print("unbound")
class C:
    z = 5
    w = [z for _ in range(1)] if False else None
    def m(self):
        return z if "z" in globals() else "no z"
print(C().m(), C.w)
print(sorted(k for k in locals() if not k.startswith("__"))[:4])
def loc(a, b=2):
    c = 3
    return sorted(locals().items())
print(loc(1))
print(eval("x + 1"), eval("a * 2", {"a": 21}))
exec("q = 7")
print(q)
