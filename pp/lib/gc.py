"""Pure-Python gc, executed by the pp VM (replaces the C module).

Guest values are host objects whose lifetime pp does not manage, so this
module cannot collect, enumerate or inspect anything. Every function keeps
CPython's signature, argument validation and return types and gives an honest
no-op or empty answer:

  * ``collect()`` frees nothing and returns 0; ``gc.callbacks`` are never
    invoked and ``garbage`` stays empty;
  * ``get_objects()``, ``get_referrers()`` and ``get_referents()`` return
    empty lists; ``is_tracked()`` is False and ``is_finalized()`` is False;
  * ``get_count()`` is ``(0, 0, 0)`` and ``get_stats()`` reports zeroed
    generations;
  * enable/disable, thresholds, debug flags and the freeze count are stored
    and reported back but change nothing.
"""

DEBUG_STATS = 1
DEBUG_COLLECTABLE = 2
DEBUG_UNCOLLECTABLE = 4
DEBUG_SAVEALL = 32
DEBUG_LEAK = DEBUG_COLLECTABLE | DEBUG_UNCOLLECTABLE | DEBUG_SAVEALL

garbage = []
callbacks = []

_enabled = True
_debug = 0
_threshold = (2000, 10, 10)
_freeze_count = 0


def _int(value, name):
    if type(value) is int:
        return value
    f = getattr(type(value), "__index__", None)
    if f is None:
        raise TypeError(f"'{type(value).__name__}' object cannot be interpreted "
                        "as an integer")
    return f(value)


def enable():
    """Enable automatic garbage collection."""
    global _enabled
    _enabled = True


def disable():
    """Disable automatic garbage collection."""
    global _enabled
    _enabled = False


def isenabled():
    """Returns true if automatic garbage collection is enabled."""
    return _enabled


def collect(generation=2):
    """Run the garbage collector. Always returns 0: nothing is collected."""
    generation = _int(generation, "generation")
    if not 0 <= generation <= 2:
        raise ValueError("invalid generation")
    return 0


def set_debug(flags, /):
    """Set the garbage collection debugging flags."""
    global _debug
    _debug = _int(flags, "flags")


def get_debug():
    """Get the garbage collection debugging flags."""
    return _debug


def get_count():
    """Return a three-tuple of the current collection counts."""
    return (0, 0, 0)


def set_threshold(threshold0, threshold1=None, threshold2=None, /):
    """Set the collection thresholds (the collection frequency)."""
    global _threshold
    t0 = _int(threshold0, "threshold0")
    t1 = _threshold[1] if threshold1 is None else _int(threshold1, "threshold1")
    t2 = _threshold[2] if threshold2 is None else _int(threshold2, "threshold2")
    _threshold = (t0, t1, t2)


def get_threshold():
    """Return the current collection thresholds."""
    return _threshold


def get_objects(generation=None):
    """Return a list of objects tracked by the collector (always empty)."""
    if generation is not None:
        generation = _int(generation, "generation")
        if not 0 <= generation <= 2:
            raise ValueError("generation parameter must be less than the number of "
                             "available generations (3)")
    return []


def get_stats():
    """Return a list of dictionaries containing per-generation statistics."""
    return [{"collections": 0, "collected": 0, "uncollectable": 0}
            for _ in range(3)]


def is_tracked(obj, /):
    """Returns true if the object is tracked by the garbage collector (never)."""
    return False


def is_finalized(obj, /):
    """Returns true if the object has been already finalized by the GC (never)."""
    return False


def get_referrers(*objs):
    """Return the list of objects that directly refer to any of the arguments
(always empty)."""
    return []


def get_referents(*objs):
    """Return the list of objects that are directly referred to by the arguments
(always empty)."""
    return []


def freeze():
    """Freeze all current tracked objects and ignore them for future collections."""


def unfreeze():
    """Unfreeze all objects in the permanent generation."""


def get_freeze_count():
    """Return the number of objects in the permanent generation."""
    return _freeze_count
