import types
@types.coroutine
def step():
    yield "tick"
async def coro():
    await step()
    async with Ctx() as v:
        return v
class Ctx:
    async def __aenter__(self): return 42
    async def __aexit__(self, *a): return False
c = coro()
print(c.send(None))
try:
    c.send(None)
except StopIteration as e:
    print(e.value)
