"""Bounds that a differential snippet cannot show."""
import gc
import weakref

import pp
from pp import frame


def test_code_caches_are_bounded():
    pp.run_source("for i in range(%d):\n    exec('x = %%d' %% i)\n" % (frame._CACHE_LIMIT + 500), "<t>")
    assert len(frame._code_info) <= frame._CACHE_LIMIT
    assert len(frame._names_cache) <= frame._CACHE_LIMIT


_CLASSES = '''
import typing

class B:
    def f(self): return 1

class K(B):
    def f(self): return super().f()

class Proto(typing.Protocol):
    def m(self): ...

class Impl(Proto):
    def m(self): return super().m()

class Slotted:
    __slots__ = ()
    def __len__(self): return 3

T = type("T", (), {"f": lambda self: 2})

results = [K().f(), Impl().m(), len(Slotted()), T().f()]
'''


def test_classes_are_freed():
    """The VM's per-type tables must not keep classes alive (host weakref and gc:
    the guest's own are pure Python)."""
    g = {"__name__": "m3_freed"}
    pp.run_source(_CLASSES, "<m3_freed>", g)
    assert g["results"] == [1, None, 3, 2]
    refs = [weakref.ref(g[name]) for name in ("B", "K", "Proto", "Impl", "Slotted", "T")]
    g.clear()
    gc.collect()
    assert [r() for r in refs] == [None] * len(refs)
