"""Binary ops, comparisons and subscripts on builtins and user types."""


class V:
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v

    def __add__(self, o):
        return V(self.v + o.v)

    def __lt__(self, o):
        return self.v < o.v


def main():
    a = 0
    f = 1.5
    s = ""
    d = {}
    lst = [0] * 100
    for i in range(60000):
        a = (a + i * 3 - (i >> 1)) % 1000003
        f = f * 1.0000001 + 0.5
        if i < a and a != 5:
            lst[i % 100] += 1
        d[i & 255] = i
        if i % 1000 == 0:
            s += str(i)
    v = V(0)
    one = V(1)
    for i in range(20000):
        v = v + one
        if v < one:
            break
    print(a, int(f), len(s), sum(lst), len(d), v.v)


main()
