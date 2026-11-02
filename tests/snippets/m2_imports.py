import operator, keyword, heapq
from collections import namedtuple, OrderedDict, deque, Counter, defaultdict
from itertools import chain, product, accumulate
P = namedtuple("P", "x y")
p = P(1, 2)
print(p, p._replace(y=5), p.x + p[1])
print(operator.itemgetter(1)([5, 6]), keyword.iskeyword("for"))
h = [5, 1, 4]; heapq.heapify(h); heapq.heappush(h, 0)
print([heapq.heappop(h) for _ in range(4)], heapq.nlargest(2, [3, 9, 1]))
print(list(chain([1], (2,))), list(product("ab", repeat=2))[:3], list(accumulate([1, 2, 3])))
d = deque([1, 2]); d.appendleft(0); print(d, Counter("abca").most_common(1))
dd = defaultdict(list); dd["a"].append(1); print(dict(dd), list(OrderedDict(b=1, a=2)))
