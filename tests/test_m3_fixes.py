"""Bounds that a differential snippet cannot show."""
import pp
from pp import frame


def test_code_caches_are_bounded():
    pp.run_source("for i in range(%d):\n    exec('x = %%d' %% i)\n" % (frame._CACHE_LIMIT + 500), "<t>")
    assert len(frame._code_info) <= frame._CACHE_LIMIT
    assert len(frame._names_cache) <= frame._CACHE_LIMIT
