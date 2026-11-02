def noisy(n):
    for i in range(n):
        print("produce", i)
        yield i
g = (x * 2 for x in noisy(3))
print("created")
print(next(g))
print(list(g))
print(any(x > 0 for x in noisy(5)))
def gen_close():
    try:
        yield 1
        yield 2
    except GeneratorExit:
        print("GeneratorExit")
        raise
c = gen_close(); next(c); c.close(); c.close()
print(list(c))
def bad_close():
    try:
        yield 1
    except GeneratorExit:
        yield 2
bc = bad_close(); next(bc)
try:
    bc.close()
except RuntimeError as e:
    print("RuntimeError", e)
