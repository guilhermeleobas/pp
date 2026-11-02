def f(a, b, *, c): pass
def g(x, /): pass
def h(): pass
class K:
    def m(self, a): pass
calls = [
    lambda: f(1), lambda: f(1, 2), lambda: f(1, 2, 3, c=1), lambda: f(1, 2, c=3, d=4),
    lambda: f(1, a=1, b=2, c=3), lambda: g(x=1), lambda: h(1), lambda: f(),
    lambda: K().m(), lambda: K().m(1, 2), lambda: f(1, 2, **{"c": 1}, **{"c": 2}),
    lambda: f(*1),
]
for c in calls:
    try:
        c()
    except TypeError as e:
        print(type(e).__name__, e)
