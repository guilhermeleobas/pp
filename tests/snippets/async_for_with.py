def drive(aw):
    try:
        while True:
            aw.send(None)
    except StopIteration as e:
        return e.value

class AIter:
    def __init__(self, n):
        self.n = n
    def __aiter__(self):
        return self
    async def __anext__(self):
        if self.n == 0:
            raise StopAsyncIteration
        self.n -= 1
        return self.n

async def f():
    out = []
    async for x in AIter(3):
        out.append(x)
    else:
        out.append("else")
    return out

print(drive(f()))

async def brk():
    async for x in AIter(5):
        if x == 3:
            break
    return x

print(drive(brk()))

class CM:
    async def __aenter__(self):
        print("enter")
        return "val"
    async def __aexit__(self, t, v, tb):
        print("exit", t.__name__ if t else None)
        return t is ValueError

async def w():
    async with CM() as v:
        print(v)
    async with CM():
        raise ValueError("x")
    async with CM():
        pass
    try:
        async with CM():
            raise KeyError("k")
    except KeyError:
        print("propagated")
    return "ok"

print(drive(w()))

async def bad_with():
    async with object():
        pass

try:
    drive(bad_with())
except TypeError as e:
    print(e)

async def bad_for():
    async for x in 5:
        pass

try:
    drive(bad_for())
except TypeError as e:
    print(e)

class BadIter:
    def __aiter__(self):
        return 1

async def bad_for2():
    async for x in BadIter():
        pass

try:
    drive(bad_for2())
except TypeError as e:
    print(e)

class BadEnter:
    def __aenter__(self):
        return 1
    async def __aexit__(self, *a):
        pass

async def bad_with2():
    async with BadEnter():
        pass

try:
    drive(bad_with2())
except TypeError as e:
    print(e)

async def comp():
    return [x async for x in AIter(3)], {x: x async for x in AIter(2)}

print(drive(comp()))
