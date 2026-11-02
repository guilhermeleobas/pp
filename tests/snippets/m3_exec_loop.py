total = 0
for i in range(6000):
    ns = {}
    exec("def f(n): return n + %d" % i, ns)
    total += ns["f"](1)
del ns
print(total)
