def fact(n):
    return 1 if n <= 1 else n * fact(n - 1)
def ack(m, n):
    if m == 0: return n + 1
    if n == 0: return ack(m - 1, 1)
    return ack(m - 1, ack(m, n - 1))
def is_even(n): return True if n == 0 else is_odd(n - 1)
def is_odd(n): return False if n == 0 else is_even(n - 1)
print(fact(20), ack(2, 3), is_even(50))
def flatten(x):
    if isinstance(x, list):
        for y in x:
            yield from flatten(y)
    else:
        yield x
print(list(flatten([1, [2, [3, [4]], 5]])))
