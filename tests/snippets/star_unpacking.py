a, *b = [1, 2, 3, 4]
print(a, b)
*a, b = range(5)
print(a, b)
a, *b, c = "hello"
print(a, b, c)
first, *rest = [1]
print(first, rest)
(a, *b), c = [1, 2, 3], 4
print(a, b, c)
for x, *ys in [(1, 2, 3), (4,)]:
    print(x, ys)
