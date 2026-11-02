words = ["pear", "Apple", "fig", "banana"]
print(sorted(words, key=str.lower), sorted(words, key=lambda w: (len(w), w)))
print(list(map(lambda a, b: a * b, [1, 2, 3], [4, 5, 6])))
print(list(filter(lambda x: x % 3 == 0, range(10))))
import functools
print(functools.reduce(lambda a, b: a + b, range(5)), max(words, key=len))
def cmp(a, b):
    return (a > b) - (a < b)
print(sorted([3, 1, 2], key=functools.cmp_to_key(cmp)))
class Acc:
    def __init__(self): self.seen = []
    def __call__(self, x):
        self.seen.append(x)
        return -x
a = Acc()
print(sorted([2, 3, 1], key=a), a.seen)
def boom(x):
    raise ValueError(x)
try:
    list(map(boom, [1]))
except ValueError as e:
    print("from host", e)
