import asyncio

async def worker(name, n):
    total = 0
    for i in range(n):
        await asyncio.sleep(0)
        total += i
    print("worker", name, total)
    return name, total

async def main():
    r = await asyncio.gather(worker("a", 3), worker("b", 5))
    print(r)
    t = asyncio.create_task(worker("c", 2))
    print(await t)
    async def agen():
        for i in range(3):
            await asyncio.sleep(0)
            yield i
    print([x async for x in agen()])
    try:
        await asyncio.wait_for(asyncio.sleep(5), 0.01)
    except asyncio.TimeoutError:
        print("timeout")
    return "done"

print(asyncio.run(main()))
