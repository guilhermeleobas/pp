import _random

for seed in (0, 1, -1, 2**32, -2**70, 1.5, (1, 2), 2**64):
    r = _random.Random(seed)
    print(seed if not isinstance(seed, tuple) else 't', [r.random() for _ in range(3)],
          [r.getrandbits(k) for k in (0, 1, 31, 32, 33, 100, 700)])
r = _random.Random(7)
st = r.getstate()
a = [r.random() for _ in range(700)]
r.setstate(st)
print(a == [r.random() for _ in range(700)], len(st), st[-1], st[:2])
for bad in ([], (), (1,) * 625, (1,) * 624 + (625,), (-1,) * 624 + (0,), (1.5,) * 624 + (0,)):
    try:
        r.setstate(bad)
    except Exception as e:
        print(type(e).__name__, e)
for f in (lambda: r.getrandbits(-1), lambda: r.getrandbits(1.5), lambda: r.seed(1, 2), lambda: r.seed([])):
    try:
        f()
    except Exception as e:
        print(type(e).__name__, e)
import pickle, random
rr = random.Random(5)
rr.random()
c = pickle.loads(pickle.dumps(rr))
print(c.random() == rr.random())
for proto in (0, 2):
    try:
        pickle.dumps(_random.Random(1), proto)
    except TypeError as e:
        print('TypeError')
