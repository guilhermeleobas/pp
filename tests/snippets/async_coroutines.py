import types

async def leaf(x):
    return x * 2

async def mid(x):
    a = await leaf(x)
    b = await leaf(a)
    return a + b

c = mid(3)
print(type(c).__name__, c.cr_running, c.cr_suspended, c.cr_await)
try:
    c.send(None)
except StopIteration as e:
    print("result", e.value)
try:
    c.send(None)
except RuntimeError as e:
    print(e)

@types.coroutine
def bare():
    got = yield "ping"
    return got

async def uses_bare():
    r = await bare()
    return ("bare", r)

c = uses_bare()
print(c.send(None), c.cr_await is not None)
try:
    c.send("pong")
except StopIteration as e:
    print(e.value)

class Aw:
    def __await__(self):
        v = yield 1
        return v + 1

async def uses_aw():
    return await Aw()

c = uses_aw()
print(c.send(None))
try:
    c.send(10)
except StopIteration as e:
    print(e.value)

async def raises():
    raise KeyError("k")

try:
    raises().send(None)
except KeyError as e:
    print("KeyError", e)

async def catches():
    try:
        await Aw()
    except ValueError as e:
        return "caught " + str(e)

c = catches()
c.send(None)
try:
    c.throw(ValueError("boom"))
except StopIteration as e:
    print(e.value)

async def closable():
    try:
        await Aw()
    finally:
        print("cleanup")

c = closable()
c.send(None)
c.close()
print(c.cr_frame)

async def bad():
    await 42

try:
    bad().send(None)
except TypeError as e:
    print(e)

class BadAw:
    def __await__(self):
        return 5

async def bad2():
    await BadAw()

try:
    bad2().send(None)
except TypeError as e:
    print(e)

async def twice():
    co = leaf(1)
    print(await co)
    try:
        await co
    except RuntimeError as e:
        print(e)

try:
    twice().send(None)
except StopIteration:
    pass

async def stopit():
    raise StopIteration

try:
    stopit().send(None)
except RuntimeError as e:
    print(e)

w = leaf(1).__await__()
print(type(w).__name__)
try:
    next(w)
except StopIteration as e:
    print(e.value)

c = leaf(1)
try:
    c.send(1)
except TypeError as e:
    print(e)
c.close()
