"""Comprehensions, generators, try/except."""


def gen(n):
    for i in range(n):
        yield i * 2


def main():
    total = 0
    for _ in range(30):
        total += sum([x for x in range(2000) if x & 1])
        total += len({x: x for x in range(1000)})
        total += sum(gen(2000))
        total += sum(x for x in range(1000))
    caught = 0
    for i in range(30000):
        try:
            if i % 3 == 0:
                raise ValueError(i)
            caught += 1
        except ValueError:
            caught += 2
        finally:
            caught += 1
    d = {}
    for i in range(20000):
        try:
            d[i] += 1
        except KeyError:
            d[i] = 1
    print(total, caught, len(d))


main()
