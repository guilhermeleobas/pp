import gc
import inspect
import sys

async def co():
    pass

async def ag():
    yield 1

def step(aw):
    try:
        aw.send(None)
    except StopIteration as e:
        return e.value

c = co()
print(inspect.getcoroutinestate(c), c.cr_state)
step(c)
print(inspect.getcoroutinestate(c))
a = ag()
print(inspect.getasyncgenstate(a), a.ag_state)
step(a.__anext__())
print(inspect.getasyncgenstate(a))
step(a.aclose())
print(inspect.getasyncgenstate(a))

a = ag()
objs = [co(), a, a.asend(None), a.athrow(ValueError), a.aclose(), co().__await__()]
for o in objs:
    print(type(o).__name__, sorted(n for n in dir(o) if not n.startswith("__")))
    print(repr(o).split(" at ")[0])
for o in objs[:1] + objs[5:]:
    o.close()
for o in objs[2:5]:
    o.close()

log = []
sys.set_asyncgen_hooks(firstiter=lambda g: log.append("first"),
                       finalizer=lambda g: log.append("fin"))

def drop():
    g = ag()
    step(g.__anext__())

drop()
gc.collect()
print(log)
sys.set_asyncgen_hooks(None, None)
