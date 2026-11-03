import warnings
warnings.simplefilter("ignore")

log = []

async def agen(n):
    try:
        for i in range(n):
            got = yield i
            if got:
                print("got", got)
    finally:
        log.append("agen finally")

def drive(aw):
    try:
        while True:
            aw.send(None)
    except StopIteration as e:
        return e.value

async def collect():
    out = []
    async for x in agen(3):
        out.append(x)
    return out

print(drive(collect()), log)

ag = agen(5)
print(type(ag).__name__, ag.ag_running, ag.ag_suspended, ag.ag_await)
print(drive(ag.__anext__()))
print(drive(ag.asend("hello")))
print(ag.ag_suspended)
print(drive(ag.aclose()), log)
try:
    drive(ag.__anext__())
except StopAsyncIteration:
    print("stopped")

async def thrower():
    try:
        yield 1
    except ValueError as e:
        print("caught", e)
        yield 2
    yield 3

ag = thrower()
print(drive(ag.__anext__()))
print(drive(ag.athrow(ValueError("x"))))
print(drive(ag.__anext__()))
try:
    drive(ag.__anext__())
except StopAsyncIteration:
    print("done")

async def stubborn():
    try:
        yield 1
    finally:
        yield 2

ag = stubborn()
drive(ag.__anext__())
try:
    drive(ag.aclose())
except RuntimeError as e:
    print(e)

ag = thrower()
try:
    drive(ag.athrow(KeyError("k")))
except KeyError as e:
    print("KeyError", e)

async def awaiting():
    await_result = yield 1
    yield 2

class Aw:
    def __await__(self):
        yield "suspend"
        return "val"

async def mixed():
    v = await Aw()
    yield v
    yield (await Aw())

ag = mixed()
aw = ag.__anext__()
print(aw.send(None))
try:
    aw.send(None)
except StopIteration as e:
    print(e.value)

async def stopasync():
    yield 1
    raise StopAsyncIteration

async def run():
    try:
        async for _ in stopasync():
            pass
    except RuntimeError as e:
        print(e)

drive(run())

class Suspend:
    def __await__(self):
        yield "suspended"

async def slow():
    await Suspend()
    yield 1

ag = slow()
a1 = ag.__anext__()
print(a1.send(None), ag.ag_running, ag.ag_await is not None)
for make in (ag.__anext__, ag.aclose, lambda: ag.athrow(ValueError)):
    try:
        make().send(None)
    except RuntimeError as e:
        print(e)
try:
    a1.send(None)
except StopIteration as e:
    print("yielded", e.value)
print(drive(ag.aclose()), ag.ag_state)

try:
    iter(agen(1))
except TypeError as e:
    print(e)

async def ret():
    return
    yield

async def run2():
    async for _ in ret():
        print("never")
    return "empty"

print(drive(run2()))
