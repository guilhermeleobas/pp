"""Pure-Python array module, executed by the pp VM (replaces the C module).

Semantics follow Modules/arraymodule.c (3.15): all typecodes (b B u w h H i I
l L q Q e f d Zf Zd), slicing, comparisons, ``+ * += *=``, pickling through
``__reduce_ex__`` and ``_array_reconstructor``, and the buffer protocol.

Storage is a ``bytearray`` in native byte order. Items are packed and unpacked
with ``int.to_bytes`` / ``int.from_bytes`` and a pure-Python IEEE 754 codec
(no ``struct``). ``__buffer__`` hands out a ``memoryview`` of that bytearray,
cast to the item format when ``memoryview`` supports one, so exports block
resizing (BufferError) as in CPython.

Limitations:
  * ``buffer_info()[0]`` is ``id()`` of the backing bytearray, not a machine
    address; it is only stable while the array is not resized.
  * ``memoryview(a).format`` is ``'B'`` (itemsize 1) for the typecodes
    ``memoryview.cast`` has no format for (``u``, ``w``, ``Zf``, ``Zd``).
  * NaN payloads and the sign of a NaN are not preserved when packing.
  * Item access is interpreted bytecode per element, so it is much slower than
    the C module.
  * Layout assumes LP64 (``l``/``L`` are 8 bytes) unless ``sys.platform`` is
    ``win32``; ``u`` and ``w`` are both 4-byte UCS4.
"""

import sys as _sys

_BO = _sys.byteorder
_LITTLE = _BO == "little"
_INF = float("inf")
_GenericAlias = type(list[int])

typecodes = ("b", "B", "u", "w", "h", "H", "i", "I", "l", "L", "q", "Q",
             "e", "f", "d", "Zf", "Zd")

_MISSING = object()
_BLOCKSIZE = 64 * 1024


# ---------------------------------------------------------------------------
# IEEE 754 codec

def _pack_bits(x, ebits, mbits, raise_overflow=False):
    """Round the float *x* to an IEEE binary format; return the bit pattern."""
    emax = (1 << ebits) - 1
    bias = (1 << (ebits - 1)) - 1
    if x != x:
        return (emax << mbits) | (1 << (mbits - 1))
    sign = 1 if x.hex()[0] == "-" else 0
    shift = ebits + mbits
    ax = -x if sign else x
    if ax == _INF:
        return (sign << shift) | (emax << mbits)
    if ax == 0:
        return sign << shift
    n, d = ax.as_integer_ratio()
    e = n.bit_length() - d.bit_length()
    if e >= 0:
        ge = n >= (d << e)
    else:
        ge = (n << -e) >= d
    if not ge:
        e -= 1
    E = e + bias
    s = mbits - e if E >= 1 else mbits + bias - 1
    if s >= 0:
        num = n << s
        den = d
    else:
        num = n
        den = d << -s
    q, r = divmod(num, den)
    r2 = r * 2
    if r2 > den or (r2 == den and q & 1):
        q += 1
    bits = ((E - 1) << mbits) + q if E >= 1 else q
    if bits >= (emax << mbits):
        if raise_overflow:
            raise OverflowError("float too large to pack with e format")
        bits = emax << mbits
    return (sign << shift) | bits


def _unpack_bits(bits, ebits, mbits):
    emax = (1 << ebits) - 1
    bias = (1 << (ebits - 1)) - 1
    sign = bits >> (ebits + mbits)
    exp = (bits >> mbits) & emax
    frac = bits & ((1 << mbits) - 1)
    if exp == emax:
        return float("nan") if frac else (-_INF if sign else _INF)
    if exp == 0:
        v = frac * 2.0 ** (1 - bias - mbits)
    else:
        v = (frac | (1 << mbits)) * 2.0 ** (exp - bias - mbits)
    return -v if sign else v


def _as_double(v):
    if type(v) is float:
        return v
    if type(v) is int:
        return float(v)
    t = type(v)
    f = getattr(t, "__float__", None)
    if f is not None:
        r = f(v)
        if not isinstance(r, float):
            raise TypeError(f"{t.__name__}.__float__ returned non-float "
                            f"(type {type(r).__name__})")
        return float(r)
    f = getattr(t, "__index__", None)
    if f is not None:
        return float(f(v))
    raise TypeError(f"must be real number, not {t.__name__}")


def _as_complex(v):
    if isinstance(v, complex):
        return v.real, v.imag
    t = type(v)
    f = getattr(t, "__complex__", None)
    if f is not None:
        r = f(v)
        if not isinstance(r, complex):
            raise TypeError(f"{t.__name__}.__complex__ returned non-complex "
                            f"(type {type(r).__name__})")
        return r.real, r.imag
    return _as_double(v), 0.0


def _index(v):
    if type(v) is int:
        return v
    f = getattr(type(v), "__index__", None)
    if f is None:
        raise TypeError(f"'{type(v).__name__}' object cannot be interpreted "
                        "as an integer")
    r = f(v)
    if type(r) is not int:
        if not isinstance(r, int):
            raise TypeError(f"__index__ returned non-int (type {type(r).__name__})")
        r = int(r)
    return r


# ---------------------------------------------------------------------------
# Item codecs.
#   enc(value) -> bytes (raises on bad values)        dec(buf, offset) -> value
#   enc_many(list) -> bytes (all or nothing)          dec_many(buf) -> list
# The *_many forms run as host builtins over whole lists (map/join/tolist), so
# bulk operations do not execute bytecode per item; any value the fast path
# does not accept goes through enc() for the exact CPython error.
#
# memoryview.cast gives the native-format pack/unpack of the host. It is used
# for 'f', 'd', 'Zf', 'Zd' (and for decoding every format in bulk); the
# pure-Python IEEE codec above handles 'e', the float32 overflow case and
# _array_reconstructor.

_INT_ONLY = {int}
_FLOAT_OK = {float, int}


def _tolist_fmt(buf, fmt):
    if not buf:
        return []
    m1 = memoryview(buf)
    m2 = m1.cast(fmt)
    try:
        return m2.tolist()
    finally:
        m2.release()
        m1.release()


def _get_fmt(buf, off, size, fmt):
    m1 = memoryview(buf)
    m2 = m1[off:off + size]
    m3 = m2.cast(fmt)
    try:
        return m3.tolist()
    finally:
        m3.release()
        m2.release()
        m1.release()


def _pack_fmt(values, size, fmt):
    ba = bytearray(size * len(values))
    m1 = memoryview(ba)
    m2 = m1.cast(fmt)
    try:
        list(map(m2.__setitem__, range(len(values)), values))
    finally:
        m2.release()
        m1.release()
    return bytes(ba)


_LONGMSG = "Python int too large to convert to C long"
_LONG_RANGE = (-(1 << 63), (1 << 63) - 1, _LONGMSG, _LONGMSG)
_ULONG_RANGE = (0, (1 << 64) - 1, "can't convert negative value to unsigned int",
                "Python int too large to convert to C unsigned long")


def _range(lo, hi, what):
    return (lo, hi, f"{what} is less than minimum", f"{what} is greater than maximum")


def _int_codec(size, signed, stages, fmt):
    lo = -(1 << (8 * size - 1)) if signed else 0
    hi = (1 << (8 * size - 1)) - 1 if signed else (1 << (8 * size)) - 1
    mask = (1 << (8 * size)) - 1
    bo = _BO
    from_bytes = int.from_bytes
    to_bytes = int.to_bytes
    andmask = mask.__and__
    stages = tuple(stages)

    def enc(v):
        v = _index(v)
        for slo, shi, lmsg, hmsg in stages:
            if v < slo:
                raise OverflowError(lmsg)
            if v > shi:
                raise OverflowError(hmsg)
        return (v & mask).to_bytes(size, bo)

    def dec(buf, off):
        return from_bytes(buf[off:off + size], bo, signed=signed)

    def enc_many(vals):
        n = len(vals)
        if n == 0:
            return b""
        if set(map(type, vals)) <= _INT_ONLY and min(vals) >= lo and max(vals) <= hi:
            if signed:
                vals = list(map(andmask, vals))
            if size == 1:
                return bytes(vals)
            return b"".join(map(to_bytes, vals, [size] * n, [bo] * n))
        return b"".join(map(enc, vals))

    def dec_many(buf):
        return _tolist_fmt(buf, fmt)
    return enc, dec, enc_many, dec_many


def _slow_float_codec(size, ebits, mbits, fmt, via_float32=False):
    """'e': pure-Python IEEE binary16 pack (memoryview 'e' rounds differently
    from CPython's float-then-half path), memoryview decode."""
    bo = _BO

    def enc(v):
        x = _unpack_bits(_pack_bits(_as_double(v), 8, 23), 8, 23)
        return _pack_bits(x, ebits, mbits, True).to_bytes(size, bo)

    def dec(buf, off):
        return _get_fmt(buf, off, size, fmt)[0]

    def enc_many(vals):
        return b"".join(map(enc, vals))

    def dec_many(buf):
        return _tolist_fmt(buf, fmt)
    return enc, dec, enc_many, dec_many


def _float_codec(size, ebits, mbits, fmt):
    """'f' and 'd' packed by memoryview.cast (native layout)."""
    bo = _BO
    f32 = size == 4

    def enc(v):
        x = _as_double(v)
        try:
            return _pack_fmt((x,), size, fmt)
        except OverflowError:
            if not f32:
                raise
            return _pack_bits(x, ebits, mbits).to_bytes(size, bo)

    def dec(buf, off):
        return _get_fmt(buf, off, size, fmt)[0]

    def enc_many(vals):
        if len(vals) == 0:
            return b""
        if set(map(type, vals)) <= _FLOAT_OK:
            try:
                return _pack_fmt(vals, size, fmt)
            except (OverflowError, ValueError):
                pass
        return b"".join(map(enc, vals))

    def dec_many(buf):
        return _tolist_fmt(buf, fmt)
    return enc, dec, enc_many, dec_many


def _complex_codec(half, ebits, mbits, fmt):
    bo = _BO
    f32 = half == 4

    def enc(v):
        re, im = _as_complex(v)
        try:
            return _pack_fmt((re, im), half, fmt)
        except OverflowError:
            if not f32:
                raise
            return (_pack_bits(re, ebits, mbits).to_bytes(half, bo)
                    + _pack_bits(im, ebits, mbits).to_bytes(half, bo))

    def dec(buf, off):
        re, im = _get_fmt(buf, off, 2 * half, fmt)
        return complex(re, im)

    def enc_many(vals):
        return b"".join(map(enc, vals))

    def dec_many(buf):
        flat = _tolist_fmt(buf, fmt)
        return list(map(complex, flat[0::2], flat[1::2]))
    return enc, dec, enc_many, dec_many


def _unicode_codec():
    bo = _BO
    from_bytes = int.from_bytes
    to_bytes = int.to_bytes

    def enc(v):
        if not isinstance(v, str):
            raise TypeError("array item must be a unicode character, "
                            f"not {type(v).__name__}")
        if len(v) != 1:
            raise TypeError("array item must be a unicode character, "
                            f"not a string of length {len(v)}")
        return ord(v).to_bytes(4, bo)

    def dec(buf, off):
        return chr(from_bytes(buf[off:off + 4], bo))

    def enc_many(vals):
        return b"".join(map(enc, vals))

    def dec_many(buf):
        return list(map(chr, _tolist_fmt(buf, "I")))

    def enc_str(s):
        n = len(s)
        return b"".join(map(to_bytes, map(ord, s), [4] * n, [bo] * n))
    return enc, dec, enc_many, dec_many, enc_str


class _Desc:
    __slots__ = ("typecode", "itemsize", "enc", "dec", "enc_many", "dec_many",
                 "enc_str", "integer", "signed", "mformat")

    def __init__(self, typecode, itemsize, codec, integer=False, signed=False,
                 mformat=-1):
        self.typecode = typecode
        self.itemsize = itemsize
        self.enc, self.dec, self.enc_many, self.dec_many = codec[:4]
        self.enc_str = codec[4] if len(codec) > 4 else None
        self.integer = integer
        self.signed = signed
        self.mformat = mformat


_LONG = 4 if _sys.platform == "win32" else 8
_BE = 0 if _LITTLE else 1


def _int_mformat(size, signed):
    if size == 1:
        return 1 if signed else 0
    base = {2: 2, 4: 6, 8: 10}[size]
    return base + _BE + (2 if signed else 0)


def _int_desc(code, size, signed, stages, fmt):
    return _Desc(code, size, _int_codec(size, signed, stages, fmt),
                 True, signed, _int_mformat(size, signed))


_SHORT = _range(-(1 << 15), (1 << 15) - 1, "signed short integer")
_INTR = _range(-(1 << 31), (1 << 31) - 1, "signed integer")
_LONGR = _LONG_RANGE if _LONG == 8 else (-(1 << 31), (1 << 31) - 1, _LONGMSG, _LONGMSG)
_ULONGR = _ULONG_RANGE if _LONG == 8 else (0, (1 << 32) - 1, _ULONG_RANGE[2], _ULONG_RANGE[3])
_LFMT = "l" if _LONG == 8 else "i"

_DESCRIPTORS = (
    _int_desc("b", 1, True, [_LONG_RANGE, _SHORT,
                             _range(-128, 127, "signed char")], "b"),
    _int_desc("B", 1, False, [_LONG_RANGE,
                              _range(0, 255, "unsigned byte integer")], "B"),
    _Desc("u", 4, _unicode_codec(), mformat=20 + _BE),
    _Desc("w", 4, _unicode_codec(), mformat=20 + _BE),
    _int_desc("h", 2, True, [_LONG_RANGE, _SHORT], "h"),
    _int_desc("H", 2, False, [_LONG_RANGE, _INTR,
                              _range(0, 65535, "unsigned short")], "H"),
    _int_desc("i", 4, True, [_LONG_RANGE, _INTR], "i"),
    _int_desc("I", 4, False, [_ULONG_RANGE,
                              _range(0, (1 << 32) - 1, "unsigned int")], "I"),
    _int_desc("l", _LONG, True, [_LONGR], _LFMT),
    _int_desc("L", _LONG, False, [_ULONGR], _LFMT.upper()),
    _int_desc("q", 8, True, [(-(1 << 63), (1 << 63) - 1, "int too big to convert",
                              "int too big to convert")], "q"),
    _int_desc("Q", 8, False, [(0, (1 << 64) - 1,
                               "can't convert negative int to unsigned",
                               "int too big to convert")], "Q"),
    _Desc("e", 2, _slow_float_codec(2, 5, 10, "e"), mformat=26 + _BE),
    _Desc("f", 4, _float_codec(4, 8, 23, "f"), mformat=14 + _BE),
    _Desc("d", 8, _float_codec(8, 11, 52, "d"), mformat=16 + _BE),
    _Desc("Zf", 8, _complex_codec(4, 8, 23, "f"), mformat=22 + _BE),
    _Desc("Zd", 16, _complex_codec(8, 11, 52, "d"), mformat=24 + _BE),
)
_BY_CODE = {d.typecode: d for d in _DESCRIPTORS}
_UNICODE = ("u", "w")

# memoryview.cast formats for the typecodes it can express (for __buffer__)
_MV_FORMATS = {"b": "b", "B": "B", "h": "h", "H": "H", "i": "i", "I": "I",
               "l": _LFMT, "L": _LFMT.upper(), "q": "q", "Q": "Q", "e": "e",
               "f": "f", "d": "d"}

_MFORMAT_DESCR = (
    (1, 0, 0), (1, 1, 0), (2, 0, 0), (2, 0, 1), (2, 1, 0), (2, 1, 1),
    (4, 0, 0), (4, 0, 1), (4, 1, 0), (4, 1, 1), (8, 0, 0), (8, 0, 1),
    (8, 1, 0), (8, 1, 1), (4, 0, 0), (4, 0, 1), (8, 0, 0), (8, 0, 1),
    (4, 0, 0), (4, 0, 1), (8, 0, 0), (8, 0, 1), (8, 0, 0), (8, 0, 1),
    (16, 0, 0), (16, 0, 1), (2, 0, 0), (2, 0, 1),
)


def _tp_name(obj):
    return type(obj).__name__


_RESIZE_MSG = "cannot resize an array that is exporting buffers"


def _mutator(f):
    """Re-word the bytearray's resize-while-exported BufferError as CPython's."""
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except BufferError as e:
            if "Existing exports" in str(e):
                raise BufferError(_RESIZE_MSG) from None
            raise
    wrapper.__name__ = f.__name__
    wrapper.__qualname__ = f.__qualname__
    wrapper.__doc__ = f.__doc__
    return wrapper


def _slices(r, isz):
    """Byte slices of the items in the range of item indices *r*."""
    starts = range(r.start * isz, r.stop * isz, r.step * isz)
    return map(slice, starts, map(isz.__add__, starts))


class _ImmutableMeta(type):
    """array.array is an immutable type in CPython (its subclasses are not)."""

    def __setattr__(cls, name, value):
        if cls.__dict__.get("_immutable"):
            raise TypeError(f"cannot set '{name}' attribute of immutable type "
                            f"'{cls.__module__}.{cls.__qualname__}'")
        type.__setattr__(cls, name, value)

    def __delattr__(cls, name):
        if cls.__dict__.get("_immutable"):
            raise TypeError(f"cannot delete '{name}' attribute of immutable type "
                            f"'{cls.__module__}.{cls.__qualname__}'")
        type.__delattr__(cls, name)


# Arrays above this many bytes are iterated by a host list iterator over a
# snapshot (no bytecode per item); smaller ones by arrayiterator (live).
_SNAPSHOT_ITER_BYTES = 1024


class array(metaclass=_ImmutableMeta):
    """array(typecode [, initializer]) -> array

Return a new array whose items are restricted by typecode, and
initialized from the optional initializer value, which must be a list,
string or iterable over elements of the appropriate type.

Arrays represent basic values and behave very much like lists, except
the type of objects stored in them is constrained.  The type is specified
at object creation time by using a type code, which is a single character.
The following type codes are defined:

    Type code   C Type             Minimum size in bytes
    'b'         signed integer     1
    'B'         unsigned integer   1
    'u'         Unicode character  2 (see note)
    'w'         Unicode character  4
    'h'         signed integer     2
    'H'         unsigned integer   2
    'i'         signed integer     2
    'I'         unsigned integer   2
    'l'         signed integer     4
    'L'         unsigned integer   4
    'q'         signed integer     8 (see note)
    'Q'         unsigned integer   8 (see note)
    'e'         floating-point     2
    'f'         floating-point     4
    'd'         floating-point     8
    'Zf'        complex            8
    'Zd'        complex            16
"""

    __slots__ = ("_b", "_d", "__weakref__")
    _immutable = True

    def __new__(cls, typecode, initializer=_MISSING, /, **kwds):
        if kwds and cls.__init__ is array.__init__:
            raise TypeError("array.array() takes no keyword arguments")
        if not isinstance(typecode, str):
            raise TypeError("array() argument 1 must be str, "
                            f"not {_tp_name(typecode)}")
        _audit = getattr(_sys, "audit", None)
        if _audit is not None:
            _audit("array.__new__", typecode,
                   None if initializer is _MISSING else initializer)
        if typecode == "u":
            import warnings
            warnings.warn("The 'u' type code is deprecated and will be "
                          "removed in Python 3.16", DeprecationWarning, 1)
        desc = _BY_CODE.get(typecode)
        if desc is None:
            raise ValueError("bad typecode (must be b, B, u, w, h, H, i, I, "
                             "l, L, q, Q, e, f, d, Zf or Zd)")
        initial = None if initializer is _MISSING else initializer
        has_initial = initializer is not _MISSING
        is_unicode = typecode in _UNICODE
        if has_initial and not is_unicode:
            if isinstance(initial, str):
                raise TypeError("cannot use a str to initialize an array "
                                f"with typecode '{typecode}'")
            if isinstance(initial, array) and initial._d.typecode in _UNICODE:
                raise TypeError("cannot use a unicode array to initialize an "
                                f"array with typecode '{typecode}'")
        self = object.__new__(cls)
        self._b = bytearray()
        self._d = desc
        if not has_initial:
            return self
        if isinstance(initial, (list, tuple)):
            self._b += desc.enc_many(list(initial))
        elif isinstance(initial, (bytes, bytearray)):
            self.frombytes(initial)
        elif is_unicode and isinstance(initial, str):
            self.fromunicode(initial)
        elif isinstance(initial, array) and initial._d is desc:
            self._b += initial._b
        else:
            self._b += desc.enc_many(list(initial))
        return self

    @classmethod
    def _make(cls, desc, data):
        self = object.__new__(cls)
        self._b = data if type(data) is bytearray else bytearray(data)
        self._d = desc
        return self

    # --- attributes --------------------------------------------------------

    @property
    def typecode(self):
        """the typecode character used to create the array"""
        return self._d.typecode

    @property
    def itemsize(self):
        """the size, in bytes, of one array item"""
        return self._d.itemsize

    # --- sequence protocol -------------------------------------------------

    def __len__(self):
        return len(self._b) // self._d.itemsize

    def _get(self, i):
        d = self._d
        return d.dec(self._b, i * d.itemsize)

    def __getitem__(self, i):
        if type(i) is not int:
            if isinstance(i, slice):
                return self._getslice(i)
            if getattr(type(i), "__index__", None) is None:
                raise TypeError("array indices must be integers")
            i = _index(i)
        d = self._d
        n = len(self._b) // d.itemsize
        if i < 0:
            i += n
        if i < 0 or i >= n:
            raise IndexError("array index out of range")
        return d.dec(self._b, i * d.itemsize)

    def _getslice(self, s):
        d = self._d
        isz = d.itemsize
        start, stop, step = s.indices(len(self._b) // isz)
        buf = self._b
        if step == 1:
            data = buf[start * isz:max(start, stop) * isz]
        else:
            data = b"".join(map(buf.__getitem__,
                                _slices(range(start, stop, step), isz)))
        return type(self)._make(d, data)

    @_mutator
    def __setitem__(self, i, v):
        if type(i) is not int:
            if isinstance(i, slice):
                return self._setslice(i, v)
            if getattr(type(i), "__index__", None) is None:
                raise TypeError("array indices must be integers")
            i = _index(i)
        d = self._d
        isz = d.itemsize
        n = len(self._b) // isz
        if i < 0:
            i += n
        if i < 0 or i >= n:
            raise IndexError("array assignment index out of range")
        data = d.enc(v)
        # the value's __index__/__float__ may have shrunk the array
        if i >= len(self._b) // isz:
            raise IndexError("array assignment index out of range")
        self._b[i * isz:(i + 1) * isz] = data

    def _setslice(self, s, value):
        d = self._d
        isz = d.itemsize
        n = len(self._b) // isz
        start, stop, step = s.indices(n)
        r = range(start, stop, step)
        if not isinstance(value, array):
            raise TypeError("can only assign array (not "
                            f"\"{_tp_name(value)}\") to array slice")
        if value._d is not d:
            raise TypeError("bad argument type for built-in operation")
        other = bytes(value._b)
        needed = len(other) // isz
        if step == 1:
            if stop < start:
                stop = start
            self._b[start * isz:stop * isz] = other
            return
        if needed != len(r):
            raise ValueError(f"attempt to assign array of size {needed} to "
                             f"extended slice of size {len(r)}")
        chunks = map(other.__getitem__, _slices(range(needed), isz))
        list(map(self._b.__setitem__, _slices(r, isz), chunks))

    @_mutator
    def __delitem__(self, i):
        d = self._d
        isz = d.itemsize
        n = len(self._b) // isz
        if type(i) is not int:
            if isinstance(i, slice):
                start, stop, step = i.indices(n)
                if step == 1:
                    if stop < start:
                        stop = start
                    del self._b[start * isz:stop * isz]
                    return
                r = range(start, stop, step)
                if len(r) == 0:
                    return
                if step > 0:
                    r = r[::-1]
                # delete back to front so earlier offsets stay valid
                list(map(self._b.__delitem__, _slices(r, isz)))
                return
            if getattr(type(i), "__index__", None) is None:
                raise TypeError("array indices must be integers")
            i = _index(i)
        if i < 0:
            i += n
        if i < 0 or i >= n:
            raise IndexError("array assignment index out of range")
        del self._b[i * isz:(i + 1) * isz]

    def __iter__(self):
        if len(self._b) > _SNAPSHOT_ITER_BYTES:
            return iter(self.tolist())
        return _make_iter(self, 0)

    def __contains__(self, v):
        return v in self.tolist()

    def __add__(self, other):
        if not isinstance(other, array):
            raise TypeError("can only append array (not "
                            f"\"{_tp_name(other)}\") to array")
        if other._d is not self._d:
            raise TypeError("bad argument type for built-in operation")
        return type(self)._make(self._d, self._b + other._b)

    @_mutator
    def __iadd__(self, other):
        if not isinstance(other, array):
            raise TypeError("can only extend array with array (not "
                            f"\"{_tp_name(other)}\")")
        self._extend_array(other)
        return self

    def _repeat_count(self, n):
        if type(n) is not int:
            if getattr(type(n), "__index__", None) is None:
                raise TypeError("can't multiply sequence by non-int of type "
                                f"'{_tp_name(n)}'")
            n = _index(n)
        return n

    def __mul__(self, n):
        n = self._repeat_count(n)
        if n < 0:
            n = 0
        if len(self._b) * n > _sys.maxsize:
            raise MemoryError
        return type(self)._make(self._d, self._b * n)

    __rmul__ = __mul__

    @_mutator
    def __imul__(self, n):
        n = self._repeat_count(n)
        if n < 0:
            n = 0
        if len(self._b) * n > _sys.maxsize:
            raise MemoryError
        self._b *= n
        return self

    # --- comparison --------------------------------------------------------

    def _cmp(self, other, op):
        if not isinstance(other, array):
            return NotImplemented
        if op == "__eq__" or op == "__ne__":
            if len(self._b) // self._d.itemsize != len(other._b) // other._d.itemsize:
                return op == "__ne__"
        return getattr(list, op)(self.tolist(), other.tolist())

    def __eq__(self, other):
        return self._cmp(other, "__eq__")

    def __ne__(self, other):
        return self._cmp(other, "__ne__")

    def __lt__(self, other):
        return self._cmp(other, "__lt__")

    def __le__(self, other):
        return self._cmp(other, "__le__")

    def __gt__(self, other):
        return self._cmp(other, "__gt__")

    def __ge__(self, other):
        return self._cmp(other, "__ge__")

    __hash__ = None

    def __repr__(self):
        name = type(self).__name__
        d = self._d
        if len(self._b) == 0:
            return f"{name}('{d.typecode}')"
        if d.typecode in _UNICODE:
            v = self.tounicode()
        else:
            v = self.tolist()
        return f"{name}('{d.typecode}', {v!r})"

    # --- methods -----------------------------------------------------------

    @_mutator
    def append(self, v, /):
        """Append new value v to the end of the array."""
        self._b += self._d.enc(v)

    def buffer_info(self):
        """Return a tuple (address, length) giving the current memory address
and the length in items of the buffer used to hold array's contents."""
        return (id(self._b), len(self._b) // self._d.itemsize)

    def byteswap(self):
        """Byteswap all items of the array.

Note, that for complex types the order of components (the real part,
followed by imaginary part) is preserved."""
        d = self._d
        c = d.itemsize // 2 if d.typecode[0] == "Z" else d.itemsize
        if c == 1:
            return
        buf = self._b
        orig = bytes(buf)
        for k in range(c):
            buf[k::c] = orig[c - 1 - k::c]

    @_mutator
    def clear(self):
        """Remove all items from the array."""
        del self._b[:]

    def count(self, v, /):
        """Return number of occurrences of v in the array."""
        return self.tolist().count(v)

    @_mutator
    def extend(self, iterable, /):
        """Append items to the end of the array."""
        if isinstance(iterable, array):
            self._extend_array(iterable)
            return
        vals = list(iterable)
        try:
            data = self._d.enc_many(vals)
        except (TypeError, OverflowError, ValueError):
            # keep the items before the bad one, as CPython does
            for v in vals:
                self.append(v)
            return
        if data:
            self._b += data

    def _extend_array(self, other):
        if other._d is not self._d:
            raise TypeError("can only extend with array of same kind")
        self._b += bytes(other._b)

    @_mutator
    def frombytes(self, buffer, /):
        """Appends items from the string, interpreting it as an array of machine
values, as if it had been read from a file using the fromfile() method)."""
        mv = memoryview(buffer)
        try:
            if mv.itemsize != 1:
                raise TypeError("a bytes-like object is required")
            if mv.nbytes % self._d.itemsize != 0:
                raise ValueError("bytes length not a multiple of item size")
            data = mv.tobytes()
            if data:
                self._b += data
        finally:
            mv.release()

    @_mutator
    def fromfile(self, f, n, /):
        """Read n objects from the file object f and append them to the end of the
array."""
        n = _index(n)
        if n < 0:
            raise ValueError("negative count")
        nbytes = n * self._d.itemsize
        b = f.read(nbytes)
        if not isinstance(b, bytes):
            raise TypeError("read() didn't return bytes")
        not_enough = len(b) != nbytes
        self.frombytes(b)
        if not_enough:
            raise EOFError("read() didn't return enough bytes")

    @_mutator
    def fromlist(self, lst, /):
        """Append items to array from list."""
        if not isinstance(lst, list):
            raise TypeError("arg must be list")
        data = self._d.enc_many(lst)
        if data:
            self._b += data

    @_mutator
    def fromunicode(self, ustr, /):
        """Extends this array with data from the unicode string ustr.

The array must be a unicode type array; otherwise a ValueError is raised.
Use array.frombytes(ustr.encode(...)) to append Unicode data to an array of
some other type."""
        if not isinstance(ustr, str):
            raise TypeError("fromunicode() argument must be str, not "
                            f"{_tp_name(ustr)}")
        if self._d.typecode not in _UNICODE:
            raise ValueError("fromunicode() may only be called on unicode "
                             "type arrays ('u' or 'w')")
        data = self._d.enc_str(ustr)
        if data:
            self._b += data

    def index(self, v, start=0, stop=_sys.maxsize, /):
        """Return index of first occurrence of v in the array.

Raise ValueError if the value is not present."""
        n = len(self._b) // self._d.itemsize
        start = _index(start)
        stop = _index(stop)
        if start < 0:
            start = max(start + n, 0)
        if stop < 0:
            stop += n
        stop = min(max(stop, 0), n)
        if start < stop:
            try:
                return self.tolist().index(v, start, stop)
            except ValueError:
                pass
        raise ValueError("array.index(x): x not in array")

    @_mutator
    def insert(self, i, v, /):
        """Insert a new item v into the array before position i."""
        d = self._d
        isz = d.itemsize
        n = len(self._b) // isz
        i = _index(i)
        data = d.enc(v)
        if i < 0:
            i += n
            if i < 0:
                i = 0
        if i > n:
            i = n
        self._b[i * isz:i * isz] = data

    @_mutator
    def pop(self, i=-1, /):
        """Return the i-th element and delete it from the array.

i defaults to -1."""
        d = self._d
        isz = d.itemsize
        n = len(self._b) // isz
        i = _index(i)
        if n == 0:
            raise IndexError("pop from empty array")
        if i < 0:
            i += n
        if i < 0 or i >= n:
            raise IndexError("pop index out of range")
        v = d.dec(self._b, i * isz)
        del self._b[i * isz:(i + 1) * isz]
        return v

    @_mutator
    def remove(self, v, /):
        """Remove the first occurrence of v in the array."""
        try:
            i = self.tolist().index(v)
        except ValueError:
            raise ValueError("array.remove(x): x not in array") from None
        isz = self._d.itemsize
        del self._b[i * isz:(i + 1) * isz]

    def reverse(self):
        """Reverse the order of the items in the array."""
        isz = self._d.itemsize
        if isz == 1:
            self._b[:] = self._b[::-1]
            return
        orig = bytes(self._b)
        n = len(orig) // isz
        self._b[:] = b"".join(map(orig.__getitem__,
                                  _slices(range(n - 1, -1, -1), isz)))

    def tobytes(self):
        """Convert the array to an array of machine values and return the bytes
representation."""
        return bytes(self._b)

    def tofile(self, f, /):
        """Write all items (as machine values) to the file object f."""
        data = bytes(self._b)
        for pos in range(0, len(data), _BLOCKSIZE):
            f.write(data[pos:pos + _BLOCKSIZE])

    def tolist(self):
        """Convert array to an ordinary list with the same items."""
        return self._d.dec_many(self._b)

    def tounicode(self):
        """Extends this array with data from the unicode string ustr.

Convert the array to a unicode string.  The array must be a unicode type
array; otherwise a ValueError is raised.  Use array.tobytes().decode() to
obtain a unicode string from an array of some other type."""
        if self._d.typecode not in _UNICODE:
            raise ValueError("tounicode() may only be called on unicode type "
                             "arrays ('u' or 'w')")
        return "".join(self.tolist())

    def __copy__(self):
        return self._getslice(slice(None))

    def __deepcopy__(self, unused, /):
        return self._getslice(slice(None))

    def __sizeof__(self):
        return object.__sizeof__(self) + len(self._b)

    def __reduce_ex__(self, protocol, /):
        if not isinstance(protocol, int):
            raise TypeError("__reduce_ex__ argument should be an integer")
        dct = getattr(self, "__dict__", None)
        d = self._d
        if d.mformat == -1 or protocol < 3:
            return (type(self), (d.typecode, self.tolist()), dct)
        return (_array_reconstructor,
                (type(self), d.typecode, d.mformat, self.tobytes()), dct)

    __class_getitem__ = classmethod(_GenericAlias)

    def __buffer__(self, flags, /):
        mv = memoryview(self._b)
        fmt = _MV_FORMATS.get(self._d.typecode)
        if fmt is None or fmt == "B":
            return mv
        try:
            return mv.cast("B").cast(fmt)
        except (TypeError, ValueError):
            return mv

    def __release_buffer__(self, view, /):
        view.release()


ArrayType = array


class arrayiterator:
    __slots__ = ("_a", "_i")

    def __new__(cls, *args, **kwargs):
        raise TypeError("cannot create 'array.arrayiterator' instances")

    def __iter__(self):
        return self

    def __next__(self):
        a = self._a
        if a is not None:
            i = self._i
            if i < len(a):
                self._i = i + 1
                return a._get(i)
            self._a = None
        raise StopIteration

    def __reduce__(self):
        if self._a is None:
            return (iter, ((),))
        return (iter, (self._a,), self._i)

    def __setstate__(self, state):
        if self._a is None:
            return
        i = _index(state)
        if i < 0:
            i = 0
        elif i > len(self._a):
            i = len(self._a)
        self._i = i

    def __length_hint__(self):
        a = self._a
        return 0 if a is None else max(len(a) - self._i, 0)


def _make_iter(a, index):
    it = object.__new__(arrayiterator)
    it._a = a
    it._i = index
    return it


arrayiterator.__module__ = "array"


def _array_reconstructor(arraytype, typecode, mformat_code, items, /):
    """Internal. Used for pickling support."""
    if not isinstance(arraytype, type):
        raise TypeError("first argument must be a type object, not "
                        f"{_tp_name(arraytype)}")
    if not issubclass(arraytype, array):
        raise TypeError(f"{arraytype.__name__} is not a subtype of array")
    if not isinstance(typecode, str) or typecode not in _BY_CODE:
        raise ValueError("second argument must be a valid type code")
    if mformat_code < 0 or mformat_code > 27:
        raise ValueError("third argument must be a valid machine format code.")
    if not isinstance(items, bytes):
        raise TypeError("fourth argument should be bytes, not "
                        f"{_tp_name(items)}")
    if mformat_code == _BY_CODE[typecode].mformat:
        return arraytype(typecode, items)
    size = _MFORMAT_DESCR[mformat_code][0]
    if len(items) % size != 0:
        raise ValueError("string length not a multiple of item size")
    le = mformat_code % 2 == 0
    order = "little" if le else "big"
    if mformat_code in (26, 27):
        conv = [_unpack_bits(int.from_bytes(items[i:i + 2], order), 5, 10)
                for i in range(0, len(items), 2)]
    elif mformat_code in (14, 15):
        conv = [_unpack_bits(int.from_bytes(items[i:i + 4], order), 8, 23)
                for i in range(0, len(items), 4)]
    elif mformat_code in (16, 17):
        conv = [_unpack_bits(int.from_bytes(items[i:i + 8], order), 11, 52)
                for i in range(0, len(items), 8)]
    elif mformat_code in (22, 23):
        conv = [complex(
            _unpack_bits(int.from_bytes(items[i:i + 4], order), 8, 23),
            _unpack_bits(int.from_bytes(items[i + 4:i + 8], order), 8, 23))
            for i in range(0, len(items), 8)]
    elif mformat_code in (24, 25):
        conv = [complex(
            _unpack_bits(int.from_bytes(items[i:i + 8], order), 11, 52),
            _unpack_bits(int.from_bytes(items[i + 8:i + 16], order), 11, 52))
            for i in range(0, len(items), 16)]
    elif mformat_code in (18, 19):
        conv = items.decode("utf-16-le" if le else "utf-16-be")
    elif mformat_code in (20, 21):
        conv = items.decode("utf-32-le" if le else "utf-32-be")
    else:
        _, signed, big = _MFORMAT_DESCR[mformat_code]
        for d in _DESCRIPTORS:
            if d.integer and d.itemsize == size and d.signed == bool(signed):
                typecode = d.typecode
        order = "big" if big else "little"
        conv = [int.from_bytes(items[i:i + size], order, signed=bool(signed))
                for i in range(0, len(items), size)]
    return arraytype(typecode, conv)


def _register():
    import collections.abc
    collections.abc.MutableSequence.register(array)


_register()
del _register
