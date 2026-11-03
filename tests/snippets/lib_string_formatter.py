import _string
import string


def show(call):
    try:
        print(call())
    except Exception as e:
        print(type(e).__name__, e)


def consume(it):
    out = []
    for _ in range(12):
        try:
            out.append(next(it))
        except StopIteration:
            out.append("stop")
            break
        except Exception as e:
            out.append((type(e).__name__, str(e)))
    return out


for c in ["", "{{", "}}", "a{{b}}c", "{!r:}", "{0:{1}}", "{0[x}y]}", "{0[}", "{", "}",
          "x}", "{0", "{0!", "{0!r", "{0!rx}", "{0!}", "{0:", "{a[{]}", "{0!r:>{w}}",
          "{:}", "{}", "{!}", "{0[]}", "{0:{{}}}", "{x{y}", "{x!\0}", "{x:{y}",
          "\u0661{\u0662}", "{00}{012}"]:
    print(repr(c), consume(_string.formatter_parser(c)))

for c in ["", "0", "00", "012", "a.b[0]", "a[", "a]", "a.", "a..b", "0[01]",
          "\u0661\u0662", "9" * 30, "a[x].y[\u0663]", "x]y", ".a", "[0]",
          "a[" + "9" * 30 + "]"]:
    try:
        first, rest = _string.formatter_field_name_split(c)
        print(repr(c), repr(first), consume(rest))
    except Exception as e:
        print(repr(c), type(e).__name__, e)


class S(str):
    def __str__(self):
        return "zz"


print(list(_string.formatter_parser(S("a{0}"))))
first, rest = _string.formatter_field_name_split(S("q.a"))
print(repr(first), list(rest))

for name in ("formatter_parser", "formatter_field_name_split"):
    f = getattr(_string, name)
    for args, kwargs in [((1,), {}), ((), {}), (("a", "b"), {}), ((), {"x": "a"})]:
        show(lambda: f(*args, **kwargs))

p = _string.formatter_parser("ab")
n = _string.formatter_field_name_split("a.b")[1]
for it in (p, n):
    t = type(it)
    print(t.__name__, t.__qualname__, t.__module__, iter(it) is it)
    show(t)
    show(lambda: __import__("pickle").dumps(it))
    show(lambda: type("X", (t,), {}))
print(repr(p).split(" object at")[0])

p = _string.formatter_parser("}a{0}")
print(consume(p))

fmt = string.Formatter()
print(fmt.format("{0[1]}{x.real:>{w}}{{}}{!r}", [1, 2], 5, x=3, w=4) if False else
      fmt.format("{0[1]}{x.real:>{w}}{{}}{y!r}", [1, 2], x=3, w=4, y="s"))
show(lambda: fmt.format("{0!z}", 1))
show(lambda: fmt.format("{", 1))
show(lambda: fmt.format("{0.}", 1))
