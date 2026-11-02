from collections import deque


def err(f):
    try:
        return f()
    except Exception as e:
        return type(e).__name__, str(e)


# remove() compares by identity first
n = float('nan')
d = deque([n])
d.remove(n)
print(len(d))
print(err(lambda: deque([float('nan')]).remove(float('nan'))))
print(deque([n]).count(n), deque([n]).index(n), n in deque([n]))


# subclass attributes cannot collide with private state
class D(deque):
    pass


d = D('abc')
d._d = 1
d._state = 2
d._maxlen = 3
d._blocks = 4
d.__n = 5
print(len(d), list(d), d.maxlen, d.pop(), d.popleft(), d)

# multiplication / concatenation errors
print(err(lambda: deque([1]) * 'a'))
print(err(lambda: [1] * deque()))
print(err(lambda: 'a' * deque()))
print(err(lambda: deque([1]) * deque()))
print(err(lambda: deque([1]).__imul__('a')))
print(err(lambda: deque([1]) + [1]))

# both ends are cheap and ordered across many blocks
d = deque()
for i in range(300):
    d.append(i)
    d.appendleft(-i)
print(len(d), d[0], d[-1], d[300], d.index(150), d.rotate(7), d[0])
out = [d.popleft() if i % 3 else d.pop() for i in range(500)]
print(sum(out), len(d), list(d)[:3])
e = deque(range(1000), maxlen=100)
print(len(e), e[0], e[-1], e.popleft(), e.pop(), len(e))
d = deque(range(100000))
while d:
    d.popleft()
print(len(d))
