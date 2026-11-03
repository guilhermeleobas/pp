"""Pure-Python ``_random`` (replaces Modules/_randommodule.c).

Module implements the Mersenne Twister random number generator.

Mirrors the C module: MT19937 with ``init_by_array`` seeding (ints by absolute
value in 32-bit little-endian chunks, anything else by ``hash()`` cast to
unsigned 64 bits), ``random()`` with 53-bit resolution, ``getrandbits``,
and ``getstate``/``setstate`` with the same ``(624 words..., index)`` tuple.
``seed(None)`` reads ``os.urandom`` and falls back to time and pid. Output is
bit-identical to CPython for the same seed and call sequence.

Limitations: the type is a plain Python class (not immutable, a heap type
whose methods are Python functions, so signatures and error text for bad
call shapes are emulated by hand), and generation is interpreted, so it is
far slower than C. ``getrandbits(k)`` raises ``MemoryError`` for k above
2**25 bits (C fails only when malloc does), so ``test_getrandbits_2G_bits``
fails. Messages for a wrong-type ``self`` and the type name in attribute
errors differ cosmetically. ``Random.__init__`` seeds directly rather than
calling ``self.seed``, as C does. ``random.Random(str/bytes)`` needs sha512
(``_sha2``/``_hashlib``), which pp does not provide yet.
"""

import os as _os
import time as _time

_N = 624
_M = 397
_MATRIX_A = 0x9908b0df
_UPPER_MASK = 0x80000000
_LOWER_MASK = 0x7fffffff
_M32 = 0xffffffff
_MAG01 = (0, _MATRIX_A)

_int_abs = int.__abs__
# C raises MemoryError only when malloc fails; interpreted, bigger requests
# would run for hours (test_getrandbits_2G_bits needs 2**26 words).
_MAX_WORDS = 1 << 20


def _noargs(name, args, kwargs):
    if kwargs:
        raise TypeError(f"{name}() takes no keyword arguments")
    if args:
        raise TypeError(f"{name}() takes no arguments ({len(args)} given)")


def _as_index(v):
    # PyNumber_Index
    if type(v) is int:
        return v
    m = getattr(type(v), '__index__', None)
    if m is None:
        raise TypeError(f"'{type(v).__name__}' object cannot be interpreted "
                        "as an integer")
    r = m(v)
    if not isinstance(r, int):
        raise TypeError(f"__index__ returned non-int (type {type(r).__name__})")
    return r


class Random:
    """Random() -> create a random number generator with its own internal state."""

    __slots__ = ('_mt', '_index')
    __module__ = '_random'

    def __new__(cls, *args, **kwargs):
        self = object.__new__(cls)
        self._mt = [0] * _N
        self._index = 0
        return self

    def __init__(self, *args, **kwargs):
        if kwargs:
            raise TypeError("Random() takes no keyword arguments")
        if len(args) > 1:
            raise TypeError(
                f"Random expected at most 1 argument, got {len(args)}")
        _seed(self, args[0] if args else None)

    def __reduce__(self):
        # A C type without __getstate__ support: not picklable or copyable.
        raise TypeError(f"cannot pickle '{type(self).__module__}."
                        f"{type(self).__qualname__}' object"
                        if type(self) is Random else
                        f"cannot pickle '{type(self).__qualname__}' object")

    # -- core generator ---------------------------------------------------

    def _refill(self):
        mt = self._mt
        mag01 = _MAG01
        for kk in range(_N - _M):
            y = (mt[kk] & _UPPER_MASK) | (mt[kk + 1] & _LOWER_MASK)
            mt[kk] = mt[kk + _M] ^ (y >> 1) ^ mag01[y & 1]
        for kk in range(_N - _M, _N - 1):
            y = (mt[kk] & _UPPER_MASK) | (mt[kk + 1] & _LOWER_MASK)
            mt[kk] = mt[kk + (_M - _N)] ^ (y >> 1) ^ mag01[y & 1]
        y = (mt[_N - 1] & _UPPER_MASK) | (mt[0] & _LOWER_MASK)
        mt[_N - 1] = mt[_M - 1] ^ (y >> 1) ^ mag01[y & 1]
        self._index = 0

    def _genrand(self):
        if self._index >= _N:
            self._refill()
        y = self._mt[self._index]
        self._index += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9d2c5680
        y ^= (y << 15) & 0xefc60000
        y ^= y >> 18
        return y

    def _words(self, n):
        # n tempered outputs, equivalent to n calls of _genrand(), taken a
        # block at a time.
        out = []
        while n > 0:
            if self._index >= _N:
                self._refill()
            take = min(n, _N - self._index)
            for y in self._mt[self._index:self._index + take]:
                y ^= y >> 11
                y ^= (y << 7) & 0x9d2c5680
                y ^= (y << 15) & 0xefc60000
                out.append(y ^ (y >> 18))
            self._index += take
            n -= take
        return out

    # -- public methods ---------------------------------------------------

    def random(self, /, *args, **kwargs):
        """random() -> x in the interval [0, 1)."""
        _noargs("Random.random", args, kwargs)
        genrand = self._genrand
        a = genrand() >> 5
        b = genrand() >> 6
        return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0)

    def seed(self, *args, **kwargs):
        if kwargs:
            raise TypeError("Random.seed() takes no keyword arguments")
        if len(args) > 1:
            raise TypeError(
                f"seed expected at most 1 argument, got {len(args)}")
        _seed(self, args[0] if args else None)
        return None

    seed.__doc__ = (
        "seed([n]) -> None.\n\nDefaults to use urandom and falls back to a "
        "combination\nof the current time and the process identifier.")
    seed.__text_signature__ = '($self, n=None, /)'

    def getstate(self, /, *args, **kwargs):
        """getstate() -> tuple containing the current state."""
        _noargs("Random.getstate", args, kwargs)
        return tuple(self._mt) + (self._index,)

    def setstate(self, *args, **kwargs):
        """setstate(state) -> None.  Restores generator state."""
        if kwargs:
            raise TypeError("Random.setstate() takes no keyword arguments")
        if len(args) != 1:
            raise TypeError("Random.setstate() takes exactly one argument "
                            f"({len(args)} given)")
        state = args[0]
        if not isinstance(state, tuple):
            raise TypeError("state vector must be a tuple")
        if len(state) != _N + 1:
            raise ValueError("state vector is the wrong size")
        new_state = []
        for i in range(_N):
            e = state[i]
            if not isinstance(e, int):
                raise TypeError("an integer is required")
            if e < 0:
                raise OverflowError(
                    "can't convert negative value to unsigned int")
            if e >> 64:
                raise OverflowError(
                    "Python int too large to convert to C unsigned long")
            new_state.append(e & _M32)
        index = _as_index(state[_N])
        if not -(1 << 63) <= index < (1 << 63):
            raise OverflowError("Python int too large to convert to C long")
        if index < 0 or index > _N:
            raise ValueError("invalid state")
        self._index = index
        self._mt[:] = new_state
        return None

    setstate.__text_signature__ = '($self, state, /)'

    def getrandbits(self, *args, **kwargs):
        """getrandbits(k) -> x.  Generates an int with k random bits."""
        if kwargs:
            raise TypeError("Random.getrandbits() takes no keyword arguments")
        if len(args) != 1:
            raise TypeError("Random.getrandbits() takes exactly one argument "
                            f"({len(args)} given)")
        k = _as_index(args[0])
        if k < 0:
            raise ValueError("Cannot convert negative int")
        if k >> 64:
            raise OverflowError("Python int too large for C uint64_t")
        if k == 0:
            return 0
        genrand = self._genrand
        if k <= 32:
            return genrand() >> (32 - k)
        words = (k - 1) // 32 + 1
        if words > _MAX_WORDS:
            raise MemoryError
        # Words come least significant first; the last one is truncated.
        ws = self._words(words)
        ws[-1] >>= words * 32 - k
        return int.from_bytes(b''.join([w.to_bytes(4, 'little') for w in ws]),
                              'little')

    getrandbits.__text_signature__ = '($self, k, /)'


def _init_genrand(self, s):
    mt = self._mt
    mt[0] = s & _M32
    for mti in range(1, _N):
        p = mt[mti - 1]
        mt[mti] = (1812433253 * (p ^ (p >> 30)) + mti) & _M32
    self._index = _N


def _init_by_array(self, key):
    mt = self._mt
    _init_genrand(self, 19650218)
    key_length = len(key)
    i = 1
    j = 0
    for _ in range(max(_N, key_length)):
        p = mt[i - 1]
        mt[i] = ((mt[i] ^ ((p ^ (p >> 30)) * 1664525)) + key[j] + j) & _M32
        i += 1
        j += 1
        if i >= _N:
            mt[0] = mt[_N - 1]
            i = 1
        if j >= key_length:
            j = 0
    for _ in range(_N - 1):
        p = mt[i - 1]
        mt[i] = ((mt[i] ^ ((p ^ (p >> 30)) * 1566083941)) - i) & _M32
        i += 1
        if i >= _N:
            mt[0] = mt[_N - 1]
            i = 1
    mt[0] = 0x80000000


def _seed_urandom(self):
    data = _os.urandom(_N * 4)
    key = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, _N * 4, 4)]
    _init_by_array(self, key)


def _seed_time_pid(self):
    now = _time.time_ns()
    mono = _time.monotonic_ns()
    key = [now & _M32, (now >> 32) & _M32, _os.getpid() & _M32,
           mono & _M32, (mono >> 32) & _M32]
    _init_by_array(self, key)


def _seed(self, arg):
    if arg is None:
        try:
            _seed_urandom(self)
        except Exception:
            _seed_time_pid(self)
        return
    # The algorithm relies on the number being unsigned: ints by absolute
    # value (int.__abs__ so a subclass cannot interfere), others by hash
    # cast to size_t.
    if isinstance(arg, int):
        n = _int_abs(arg)
    else:
        n = hash(arg) & 0xffffffffffffffff
    bits = n.bit_length()
    keyused = 1 if bits == 0 else (bits - 1) // 32 + 1
    key = [(n >> (32 * i)) & _M32 for i in range(keyused)]
    _init_by_array(self, key)
