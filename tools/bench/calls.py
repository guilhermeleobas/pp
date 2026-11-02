"""Function calls: positional, keyword, defaults, closures."""


def add(a, b):
    return a + b


def kw(a, b=2, *, c=3):
    return a + b + c


def outer():
    x = 1

    def inner(y):
        return x + y
    return inner


inner = outer()
def main():
    total = 0
    for i in range(60000):
        total = add(total, i)
        total = kw(total, c=1)
        total = inner(total)
    print(total)


main()
