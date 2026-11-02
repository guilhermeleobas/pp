class Point:
    __match_args__ = ("x", "y")
    def __init__(self, x, y): self.x, self.y = x, y
def describe(v):
    match v:
        case 0 | 1:
            return "small"
        case int(n) if n < 0:
            return f"neg {n}"
        case [x, y, *rest]:
            return f"seq {x} {y} {rest}"
        case {"k": k, **others}:
            return f"map {k} {others}"
        case Point(0, y=yy):
            return f"on y axis {yy}"
        case Point(x, y):
            return f"pt {x},{y}"
        case str() as s:
            return "str " + s
        case None:
            return "none"
        case _:
            return "other"
for v in [0, -5, [1, 2, 3, 4], (7, 8), {"k": 1, "z": 2}, Point(0, 3), Point(1, 2), "s", None, 3.5, "ab"[0:0]]:
    print(describe(v))
