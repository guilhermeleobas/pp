"""Attribute access and method calls on instances and classes."""


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def norm1(self):
        return abs(self.x) + abs(self.y)

    @property
    def sum(self):
        return self.x + self.y


class P3(Point):
    __slots__ = ()
    z = 7

    def norm1(self):
        return super().norm1() + self.z


def main():
    total = 0
    p = Point(1, 2)
    q = P3(3, 4)
    for i in range(40000):
        p.x = i
        total += p.x + p.y + p.norm1() + p.sum
        total += q.norm1() + q.z
    lst = []
    for i in range(20000):
        lst.append(i)
    print(total, len(lst))


main()
