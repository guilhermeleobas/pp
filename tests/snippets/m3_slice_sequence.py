s = slice(1)
for op in (lambda: [1] * s, lambda: s * [1], lambda: s + s, lambda: (1, 2) * s):
    try: op()
    except TypeError as e: print(e)
try:
    s *= [1]
except TypeError as e: print(e)
l = [1]
l *= 2; print(l)
try: l *= s
except TypeError as e: print(e)
