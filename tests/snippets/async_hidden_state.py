import types

def plain():
    yield 1

async def co():
    pass

async def ag():
    yield 1

a = ag()
c = co()
objs = {
    "generator": plain(),
    "coroutine": c,
    "async_generator": a,
    "asend": a.asend(None),
    "athrow": a.athrow(ValueError),
    "coroutine_wrapper": co().__await__(),
}
hidden = ("gi_tstate", "gi_iframe", "gi_exc_state", "gi_frame_state", "_kind", "_s",
          "ag_origin_or_finalizer", "ag_closed", "ag_hooks_inited", "ag_running_async",
          "cw_coroutine", "ags_gen", "ags_sendval", "ags_state", "agt_gen", "agt_typ",
          "agt_val", "agt_tb", "agt_state")
for kind, o in objs.items():
    t = type(o)
    leaked = []
    for name in hidden:
        for get in (getattr, object.__getattribute__):
            try:
                get(o, name)
            except AttributeError:
                pass
            else:
                leaked.append(name)
        if name in vars(t):
            leaked.append("vars:" + name)
    print(kind, t.__name__, t.__mro__ == (t, object), leaked)
    keys = sorted(k for k in vars(t) if k not in ("__module__", "__slots__", "__weakref__"))
    print("  ", keys)

import warnings
warnings.simplefilter("ignore")
for o in objs.values():
    if hasattr(o, "close"):
        o.close()
