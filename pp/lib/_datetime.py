"""``_datetime`` for pp: re-exports the pure-Python ``_pydatetime``.

CPython's ``datetime.py`` does ``from _datetime import *`` and falls back to
``_pydatetime``; here the "accelerator" is the same implementation, so tests
that ``import _datetime`` directly (``test_types``, ``test_sys``, ``test_gc``)
get a working module. ``datetime`` keeps working when only ``_datetime`` is
reachable, and fails with ``ImportError`` when ``_pydatetime`` is blocked (so
``test_datetime`` does not run its ``_Fast`` variant as a duplicate).

Limitation: ``datetime_CAPI`` (a C capsule) does not exist, so tests that
need it (``types.test_capsule_type``, ``sys.getsizeof`` and ``gc`` checks)
stay failing.
"""

from _pydatetime import *
from _pydatetime import __all__
