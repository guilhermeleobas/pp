"""Pure-Python ``_struct`` (replaces Modules/_struct.c).

Functions to convert between Python values and C structs.
Python bytes objects are used to hold the data representing the C struct.
The format string (explained below) describes the layout of data
in the C struct.

The optional first format char indicates byte order, size and alignment:
  @: native order, size & alignment (default)
  =: native order, std. size & alignment
  <: little-endian, std. size & alignment
  >: big-endian, std. size & alignment
  !: same as >

The remaining characters indicate types of args and must match exactly;
these can be preceded by a decimal repeat count:
  x: pad byte (no data); c: char; b: signed byte; B: unsigned byte;
  ?: _Bool; h: short; H: unsigned short; i: int; I: unsigned int;
  l: long; L: unsigned long; q: long long; Q: unsigned long long;
  f: float; d: double; e: half-float;
  F: float complex; D: double complex.
Special cases (preceding decimal count indicates length):
  s: byte string (array of char); p: Pascal string (with count byte).
Special cases (only available in native format):
  n: ssize_t; N: size_t;
  P: an integer type that is wide enough to hold a pointer.
Whitespace between formats is ignored.

The variable struct.error is an exception raised on errors.

Mirrors the C module: the format table (native sizes and alignment for an
LP64 or ILP32 little-/big-endian host taken from ``sys``), the error messages,
the 3.15 ``Struct.__new__``/``__init__`` compatibility dance, ``unpack_iterator``
and the module-level format cache.

Floats are packed with integer bit manipulation (``as_integer_ratio``, round
half to even), not the host ``struct``.

Limitations: NaN payloads are not preserved (a NaN packs as the quiet NaN with
its sign); argument-count errors for the module functions are Python's wording
("pack() missing 1 required positional-only argument: 'format'") instead of the
Argument Clinic wording; ``Struct`` is a plain Python class (instances have
``__slots__`` and the format/size attributes are read-only properties) rather
than an immutable static type; the buffer protocol is reached through
``memoryview`` so a non-contiguous buffer raises memoryview's ``BufferError``
wording; native sizes are those of a Linux LP64 or ILP32 host (``long`` and
``size_t`` are 8 bytes when ``sys.maxsize`` is 2**63-1, else 4; ``short`` 2,
``int`` 4, ``_Bool`` 1).
"""

import math as _math
import operator as _operator
import sys as _sys

_SSIZE_MAX = (1 << 63) - 1
_LITTLE = _sys.byteorder == 'little'
_NATIVE_ORDER = _sys.byteorder
_LONG = 8 if _sys.maxsize > 2**32 else 4
_SIZE_T = 8 if _sys.maxsize > 2**32 else 4
_WS = ' \t\n\r\x0b\x0c'


class error(Exception):
    pass


error.__module__ = 'struct'
error.__qualname__ = 'error'


# ---- integer helpers -------------------------------------------------------

def _index(v):
    if isinstance(v, int):
        return v
    if hasattr(type(v), '__index__'):
        return _operator.index(v)
    raise error("required argument is not an integer")


def _ssize(v):
    # Py_ssize_t argument conversion: an index, range-checked.
    m = getattr(type(v), '__index__', None)
    if m is None:
        raise TypeError(f"'{type(v).__name__}' object cannot be interpreted "
                        "as an integer")
    v = m(v)
    if not -(1 << 63) <= v < (1 << 63):
        raise OverflowError("Python int too large to convert to C ssize_t")
    return v


def _int_entry(fmt, size, align, signed, order):
    nbits = 8 * size
    if signed:
        lo, hi = -(1 << (nbits - 1)), (1 << (nbits - 1)) - 1
        msg = f"'{fmt}' format requires {lo} <= number <= {hi}"
    else:
        lo, hi = 0, (1 << nbits) - 1
        msg = f"'{fmt}' format requires 0 <= number <= {hi}"

    def pack(v):
        x = _index(v)
        if x < lo or x > hi:
            raise error(msg)
        return x.to_bytes(size, order, signed=signed)

    def unpack(b):
        return int.from_bytes(b, order, signed=signed)

    return (fmt, size, align, pack, unpack)


def _ptr_entry(fmt, size, align, order):
    hi = (1 << (8 * size)) - 1
    lo = -(1 << (8 * size - 1))

    def pack(v):
        x = _index(v)
        if x < lo or x > hi:
            raise error("int too large to convert")
        return (x & hi).to_bytes(size, order)

    def unpack(b):
        return int.from_bytes(b, order)

    return (fmt, size, align, pack, unpack)


# ---- floating point --------------------------------------------------------

def _as_double(v):
    # PyFloat_AsDouble; every failure becomes struct.error.
    if isinstance(v, float):
        return v
    t = type(v)
    if hasattr(t, '__float__') or hasattr(t, '__index__'):
        try:
            return float(v)
        except Exception:
            pass
    raise error("required argument is not a float")


def _as_complex(v):
    if isinstance(v, complex):
        return v
    t = type(v)
    if hasattr(t, '__complex__') or hasattr(t, '__float__') or hasattr(t, '__index__'):
        try:
            return complex(v)
        except Exception:
            pass
    raise error("required argument is not a complex")


def _pack_bits(x, ebits, mbits, name):
    """IEEE-754 bits of the double ``x`` rounded to (ebits, mbits)."""
    sign = 1 << (ebits + mbits) if _math.copysign(1.0, x) < 0 else 0
    emax_field = (1 << ebits) - 1
    if x != x:
        return sign | (emax_field << mbits) | (1 << (mbits - 1))
    if x in (_math.inf, -_math.inf):
        return sign | (emax_field << mbits)
    if x == 0.0:
        return sign
    n, d = abs(x).as_integer_ratio()
    bias = (1 << (ebits - 1)) - 1
    e = n.bit_length() - d.bit_length()
    if e >= 0:
        if n < (d << e):
            e -= 1
    elif (n << -e) < d:
        e -= 1
    if e < 1 - bias:
        e = 1 - bias
    shift = mbits - e
    if shift >= 0:
        num, den = n << shift, d
    else:
        num, den = n, d << -shift
    q, r = divmod(num, den)
    if 2 * r > den or (2 * r == den and q & 1):
        q += 1
    if q >= 1 << (mbits + 1):       # rounding carried into the next binade
        q >>= 1
        e += 1
    bits = ((e + bias - 1) << mbits) + q
    if bits >> mbits >= emax_field:
        raise OverflowError(f"float too large to pack with {name} format")
    return sign | bits


def _unpack_bits(bits, ebits, mbits):
    sign = bits >> (ebits + mbits)
    exp = (bits >> mbits) & ((1 << ebits) - 1)
    mant = bits & ((1 << mbits) - 1)
    if exp == (1 << ebits) - 1:
        if mant:
            return _math.copysign(_math.nan, -1.0 if sign else 1.0)
        return -_math.inf if sign else _math.inf
    bias = (1 << (ebits - 1)) - 1
    if exp == 0:
        v = _math.ldexp(float(mant), 1 - bias - mbits)
    else:
        v = _math.ldexp(float(mant | (1 << mbits)), exp - bias - mbits)
    return -v if sign else v


def _float_entry(fmt, size, align, order, ebits, mbits, name):
    def pack(v):
        return _pack_bits(_as_double(v), ebits, mbits, name).to_bytes(size, order)

    def unpack(b):
        return _unpack_bits(int.from_bytes(b, order), ebits, mbits)

    return (fmt, size, align, pack, unpack)


def _saturating_bits(x, ebits, mbits, name):
    # C's (float) cast: out-of-range values become +-inf instead of an error.
    try:
        return _pack_bits(x, ebits, mbits, name)
    except OverflowError:
        return ((1 << ebits) - 1) << mbits | (
            1 << (ebits + mbits) if x < 0 else 0)


def _complex_entry(fmt, size, align, order, ebits, mbits, name):
    half = size // 2
    # Tables in native byte order share the native (memcpy of a C float cast)
    # packer, which saturates; the other byte order goes through PyFloat_Pack4.
    bits = _saturating_bits if order == _NATIVE_ORDER else _pack_bits

    def pack(v):
        c = _as_complex(v)
        return (bits(c.real, ebits, mbits, name).to_bytes(half, order)
                + bits(c.imag, ebits, mbits, name).to_bytes(half, order))

    def unpack(b):
        return complex(_unpack_bits(int.from_bytes(b[:half], order), ebits, mbits),
                       _unpack_bits(int.from_bytes(b[half:], order), ebits, mbits))

    return (fmt, size, align, pack, unpack)


# ---- the format tables -----------------------------------------------------

def _char_pack(v):
    if not isinstance(v, bytes) or len(v) != 1:
        raise error("char format requires a bytes object of length 1")
    return bytes(v)


def _bool_pack(v):
    return b'\x01' if v else b'\x00'


def _bool_unpack(b):
    return b != b'\x00'


def _make_table(native, order):
    t = {}
    t['x'] = ('x', 1, 0, None, None)
    t['b'] = _int_entry('b', 1, 0, True, order)
    t['B'] = _int_entry('B', 1, 0, False, order)
    t['c'] = ('c', 1, 0, _char_pack, bytes)
    t['s'] = ('s', 1, 0, None, None)
    t['p'] = ('p', 1, 0, None, None)

    def a(size):
        return size if native else 0

    if native:
        sizes = dict(h=2, i=4, l=_LONG, q=8)
    else:
        sizes = dict(h=2, i=4, l=4, q=8)
    for c, size in sizes.items():
        t[c] = _int_entry(c, size, a(size), True, order)
        t[c.upper()] = _int_entry(c.upper(), size, a(size), False, order)
    if native:
        t['n'] = _int_entry('n', _SIZE_T, _SIZE_T, True, order)
        t['N'] = _int_entry('N', _SIZE_T, _SIZE_T, False, order)
    t['?'] = ('?', 1, 1 if native else 0, _bool_pack, _bool_unpack)
    t['e'] = _float_entry('e', 2, a(2), order, 5, 10, 'e')
    t['f'] = _float_entry('f', 4, a(4), order, 8, 23, 'f')
    t['d'] = _float_entry('d', 8, a(8), order, 11, 52, 'd')
    t['F'] = _complex_entry('F', 8, a(4), order, 8, 23, 'f')
    t['D'] = _complex_entry('D', 16, a(8), order, 11, 52, 'd')
    t['Zf'] = _complex_entry('Zf', 8, a(4), order, 8, 23, 'f')
    t['Zd'] = _complex_entry('Zd', 16, a(8), order, 11, 52, 'd')
    if native:
        t['P'] = _ptr_entry('P', _SIZE_T, _SIZE_T, order)
    return t


_NATIVE = _make_table(True, _NATIVE_ORDER)
_LE = _make_table(False, 'little')
_BE = _make_table(False, 'big')
_HOST = _LE if _LITTLE else _BE


def _whichtable(fmt):
    c = fmt[:1]
    if c == '<':
        return _LE, 1
    if c in ('>', '!'):
        return _BE, 1
    if c == '=':
        return _HOST, 1
    if c == '@':
        return _NATIVE, 1
    return _NATIVE, 0


def _getentry(s, i, table):
    c = s[i]
    if c == 'Z':
        e = table.get(s[i:i + 2])
    else:
        e = table.get(c)
    if e is None:
        raise error("bad char in struct format")
    return e


def _overflow():
    return error("total struct size too long")


def _prepare(format):
    """Parse a str format; returns (codes, size, len)."""
    if not format.isascii():
        raise ValueError("non-ASCII character in struct format")
    if '\0' in format:
        raise error("embedded null character")
    table, i = _whichtable(format)
    n = len(format)
    codes = []
    size = 0
    count = 0
    while i < n:
        c = format[i]
        i += 1
        if c in _WS:
            continue
        if '0' <= c <= '9':
            num = ord(c) - 48
            while i < n and '0' <= format[i] <= '9':
                num = num * 10 + ord(format[i]) - 48
                if num > _SSIZE_MAX:
                    raise _overflow()
                i += 1
            if i >= n:
                raise error("repeat count given without format specifier")
            c = format[i]
            i += 1
        else:
            num = 1
        e = _getentry(format, i - 1, table)
        fmt, itemsize, alignment, _p, _u = e
        if c == 's' or c == 'p':
            count += 1
        elif c != 'x':
            if num > _SSIZE_MAX - count:
                raise _overflow()
            count += num
        if alignment and size > 0:
            extra = (alignment - 1) - (size - 1) % alignment
            if extra > _SSIZE_MAX - size:
                raise _overflow()
            size += extra
        i += len(fmt) - 1
        if num > (_SSIZE_MAX - size) // itemsize:
            raise _overflow()
        if c == 's' or c == 'p':
            codes.append((size, num, e, 1))
            size += num
        elif c == 'x':
            size += num
        elif num:
            codes.append((size, itemsize, e, num))
            size += itemsize * num
    return codes, size, count


# ---- Struct ----------------------------------------------------------------

def _bad_buffer(name, argno, what, v):
    return TypeError(f"{name}() argument {argno} must be {what}, "
                     f"not {type(v).__name__}")


def _readbuf(buffer):
    try:
        mv = memoryview(buffer)
    except TypeError:
        raise TypeError("a bytes-like object is required, not "
                        f"'{type(buffer).__name__}'") from None
    if not mv.c_contiguous:
        raise BufferError("memoryview: underlying buffer is not C-contiguous")
    if mv.format != 'B' or mv.ndim != 1:
        mv = mv.cast('B')
    return mv


def _writebuf(buffer, argno):
    try:
        mv = memoryview(buffer)
    except TypeError:
        raise _bad_buffer('pack_into', argno, 'read-write bytes-like object',
                          buffer) from None
    if mv.readonly:
        raise _bad_buffer('pack_into', argno, 'read-write bytes-like object',
                          buffer)
    if not mv.c_contiguous:
        raise _bad_buffer('pack_into', argno, 'read-write bytes-like object',
                          buffer)
    if mv.format != 'B' or mv.ndim != 1:
        mv = mv.cast('B')
    return mv


def _parse_format_arg(args, kwds):
    # Argument Clinic's parsing of Struct(format).
    nargs = len(args) + len(kwds)
    if kwds:
        extra = [k for k in kwds if k != 'format']
        if extra:
            raise TypeError(f"Struct() got an unexpected keyword argument "
                            f"'{extra[0]}'")
        if args:
            raise TypeError("argument for Struct() given by name ('format') "
                            "and position (1)")
    if nargs > 1:
        raise TypeError(f"Struct() takes at most 1 argument ({nargs} given)")
    if nargs < 1:
        raise TypeError("Struct() missing required argument 'format' (pos 1)")
    return args[0] if args else kwds['format']


def _format_str(format):
    if isinstance(format, str):
        return str(format)
    if isinstance(format, bytes):
        return format.decode('ascii', 'surrogateescape')
    raise TypeError("Struct() argument 1 must be a str or bytes object, "
                    f"not {type(format).__name__}")


_frozen = set()


class _ImmutableType(type):
    # Py_TPFLAGS_IMMUTABLETYPE on the two static types; subclasses stay mutable.
    def __setattr__(cls, name, value):
        if cls in _frozen:
            raise TypeError(f"cannot set {name!r} attribute of immutable type "
                            f"'_struct.{cls.__name__}'")
        type.__setattr__(cls, name, value)

    def __delattr__(cls, name):
        if cls in _frozen:
            raise TypeError(f"cannot set {name!r} attribute of immutable type "
                            f"'_struct.{cls.__name__}'")
        type.__delattr__(cls, name)


class Struct(metaclass=_ImmutableType):
    """Create a compiled struct object.

    Return a new Struct object which writes and reads binary data according
    to the format string.  See help(struct) for more on format strings.
    """

    __slots__ = ('_format', '_codes', '_size', '_len', '_init_called',
                 '__weakref__')

    def __new__(cls, *args, **kwds):
        if cls.__new__ is not Struct.__new__:
            # Struct.__new__() called explicitly from a subclass' __new__().
            format = _parse_format_arg(args, kwds)
            self = object.__new__(cls)
            self._reset()
            self._set_format(format)
            return self
        format = None
        have = False
        if len(args) == 1 and not kwds:
            format, have = args[0], True
        elif not args and len(kwds) == 1 and 'format' in kwds:
            format, have = kwds['format'], True
        custom_init = cls.__init__ is not Struct.__init__
        if not have and custom_init:
            import warnings
            nargs = len(args) + len(kwds)
            if nargs > 1:
                warnings.warn(f"Struct() takes at most 1 argument ({nargs} given)",
                              DeprecationWarning, 2)
            else:
                warnings.warn("Struct() missing required argument 'format' (pos 1)",
                              DeprecationWarning, 2)
        self = object.__new__(cls)
        self._reset()
        if have:
            try:
                self._set_format(format)
            except Exception as exc:
                if not custom_init:
                    raise
                self._format = None
                import warnings
                warnings.warn("Invalid 'format' argument for Struct.__new__(): "
                              f"{exc}", DeprecationWarning, 2)
        return self

    def _reset(self):
        self._format = None
        self._codes = None
        self._size = -1
        self._len = -1
        self._init_called = False

    def _set_format(self, format):
        fmt = _format_str(format)
        codes, size, count = _prepare(fmt)
        self._codes = codes
        self._size = size
        self._len = count
        self._format = fmt

    def __init__(self, *args, **kwds):
        if (not self._init_called and type(self).__init__ is Struct.__init__
                and self._format is not None):
            # Called implicitly: __new__() already did all the work.
            self._init_called = True
            return
        format = _parse_format_arg(args, kwds)
        if self._format is None:
            self._set_format(format)
        elif not self._same_format(format):
            import warnings
            msg = ("Re-initialization of Struct by calling the __init__() method "
                   "will not work in future Python versions"
                   if self._init_called else
                   "Different format arguments for __new__() and __init__() "
                   "methods of Struct")
            warnings.warn(msg, FutureWarning, 2)
            self._set_format(format)
        self._init_called = True

    def _same_format(self, format):
        if isinstance(format, str) and format.isascii():
            return format == self._format
        if isinstance(format, bytes):
            return format.decode('ascii', 'surrogateescape') == self._format
        return False

    @property
    def format(self):
        """struct format string"""
        if self._format is None:
            raise AttributeError('format')
        return self._format

    @property
    def size(self):
        """struct size in bytes"""
        return self._size

    def __reduce__(self):
        raise TypeError("cannot pickle '_struct.Struct' object")

    def __sizeof__(self):
        self._ready()
        return 48 + 32 * (len(self._codes) + 1)

    def __repr__(self):
        self._ready()
        return f"{type(self).__name__}({self._format!r})"

    def _ready(self):
        if self._codes is None:
            raise RuntimeError("Struct object is not initialized")

    def _unpack_internal(self, data, start):
        result = []
        for off, csize, e, repeat in self._codes:
            c = e[0]
            pos = start + off
            for _ in range(repeat):
                if c == 's':
                    v = bytes(data[pos:pos + csize])
                elif c == 'p':
                    if csize == 0:
                        n = 0
                    else:
                        n = data[pos]
                        if n >= csize:
                            n = csize - 1
                    v = bytes(data[pos + 1:pos + 1 + n])
                else:
                    v = e[4](bytes(data[pos:pos + csize]))
                result.append(v)
                pos += csize
        return tuple(result)

    def unpack(self, buffer, /):
        """Return a tuple containing unpacked values.

        Unpack according to the struct format string.  The buffer's
        size in bytes must be the struct size.  See help(struct) for more on
        format strings.
        """
        self._ready()
        mv = _readbuf(buffer)
        if mv.nbytes != self._size:
            raise error(f"unpack requires a buffer of {self._size} bytes")
        return self._unpack_internal(mv, 0)

    def unpack_from(self, /, buffer, offset=0):
        """Return a tuple containing unpacked values.

        Values are unpacked according to the struct format string.  The
        buffer's size in bytes, starting at position offset, must be at
        least the struct size.  A negative offset counts from the end of
        the buffer.  See help(struct) for more on format strings.
        """
        mv = _readbuf(buffer)
        offset = _ssize(offset)
        self._ready()
        size = self._size
        blen = mv.nbytes
        if offset < 0:
            if offset + size > 0:
                raise error(f"not enough data to unpack {size} bytes at "
                            f"offset {offset}")
            if offset + blen < 0:
                raise error(f"offset {offset} out of range for "
                            f"{blen}-byte buffer")
            offset += blen
        if blen - offset < size:
            raise error(f"unpack_from requires a buffer of at least "
                        f"{size + offset} bytes for unpacking {size} bytes "
                        f"at offset {offset} (actual buffer size is {blen})")
        return self._unpack_internal(mv, offset)

    def iter_unpack(self, buffer, /):
        """Return an iterator yielding tuples.

        Tuples are unpacked from the given bytes source, like a repeated
        invocation of unpack_from().  Requires that the bytes length be
        a multiple of the struct size.
        """
        self._ready()
        if self._size == 0:
            raise error("cannot iteratively unpack with a struct of length 0")
        mv = _readbuf(buffer)
        if mv.nbytes % self._size != 0:
            raise error("iterative unpacking requires a buffer of "
                        f"a multiple of {self._size} bytes")
        return _unpack_iterator._make(self, mv)

    def _pack_internal(self, args, out):
        i = 0
        for off, csize, e, repeat in self._codes:
            c = e[0]
            pos = off
            for _ in range(repeat):
                v = args[i]
                i += 1
                if c == 's':
                    if not isinstance(v, (bytes, bytearray)):
                        raise error("argument for 's' must be a bytes object")
                    n = min(len(v), csize)
                    out[pos:pos + n] = v[:n]
                elif c == 'p':
                    if not isinstance(v, (bytes, bytearray)):
                        raise error("argument for 'p' must be a bytes object")
                    n = len(v)
                    if csize == 0:
                        n = 0
                    elif n > csize - 1:
                        n = csize - 1
                    if n > 0:
                        out[pos + 1:pos + 1 + n] = v[:n]
                        out[pos] = min(n, 255)
                else:
                    try:
                        out[pos:pos + csize] = e[3](v)
                    except OverflowError:
                        if isinstance(v, int):
                            raise error("int too large to convert") from None
                        raise
                pos += csize

    def pack(self, *values):
        """Pack values and return the packed bytes.

        Return a bytes object containing the provided values packed
        according to the struct format string.  See help(struct) for more on
        format strings.
        """
        self._ready()
        if len(values) != self._len:
            raise error(f"pack expected {self._len} items for packing "
                        f"(got {len(values)})")
        out = bytearray(self._size)
        self._pack_internal(values, out)
        return bytes(out)

    def pack_into(self, buffer, offset, /, *values):
        """Pack values and write the packed bytes into the buffer.

        Pack the provided values according to the struct format string
        and write the packed bytes into the writable buffer starting at
        offset.  Note that the offset is a required argument.  A negative
        offset counts from the end of the buffer.  See help(struct) for
        more on format strings.
        """
        return self._pack_into_mv(_writebuf(buffer, 1), offset, values)

    def _pack_into_mv(self, mv, offset, values):
        offset = _ssize(offset)
        self._ready()
        size = self._size
        if len(values) != self._len:
            raise error(f"pack_into expected {self._len} items for packing "
                        f"(got {len(values)})")
        blen = mv.nbytes
        if offset < 0:
            if offset + size > 0:
                raise error(f"no space to pack {size} bytes at offset {offset}")
            if offset + blen < 0:
                raise error(f"offset {offset} out of range for "
                            f"{blen}-byte buffer")
            offset += blen
        if blen - offset < size:
            raise error(f"pack_into requires a buffer of at least "
                        f"{size + offset} bytes for packing {size} bytes at "
                        f"offset {offset} (actual buffer size is {blen})")
        out = bytearray(size)
        self._pack_internal(values, out)
        mv[offset:offset + size] = out


class _unpack_iterator(metaclass=_ImmutableType):
    __slots__ = ('_so', '_buf', '_index')

    def __new__(cls, *args, **kwds):
        raise TypeError("cannot create '_struct.unpack_iterator' instances")

    @classmethod
    def _make(cls, so, mv):
        self = object.__new__(cls)
        self._so = so
        self._buf = mv
        self._index = 0
        return self

    def __iter__(self):
        return self

    def __length_hint__(self):
        if self._so is None:
            return 0
        return (self._buf.nbytes - self._index) // self._so._size

    def __next__(self):
        so = self._so
        if so is None:
            raise StopIteration
        if self._index >= self._buf.nbytes:
            self._so = None
            self._buf = None
            raise StopIteration
        result = so._unpack_internal(self._buf, self._index)
        self._index += so._size
        return result


_unpack_iterator.__name__ = _unpack_iterator.__qualname__ = 'unpack_iterator'
_frozen.update((Struct, _unpack_iterator))


# ---- module-level functions ------------------------------------------------

_MAXCACHE = 100
_cache = {}


def _cached(fmt):
    if isinstance(fmt, bytes):
        key = fmt.decode('ascii', 'surrogateescape')
    else:
        key = fmt
    s = _cache.get(key)
    if s is not None:
        return s
    s = Struct(key)
    if len(_cache) >= _MAXCACHE:
        _cache.clear()
    try:
        _cache[key] = s
    except Exception:
        pass
    return s


def _clearcache():
    """Clear the internal cache."""
    _cache.clear()


def calcsize(format, /):
    """Return size in bytes of the struct described by the format string."""
    return _cached(format)._size


def pack(format, /, *values):
    """Pack values and return the packed bytes.

    Return a bytes object containing the provided values packed according
    to the format string.  See help(struct) for more on format strings.
    """
    return _cached(format).pack(*values)


def pack_into(format, buffer, offset, /, *values):
    """Pack values and write the packed bytes into the buffer.

    Pack the provided values according to the format string and write the
    packed bytes into the writable buffer starting at offset.  Note that the
    offset is a required argument.  A negative offset counts from the end of
    the buffer.  See help(struct) for more on format strings.
    """
    s = _cached(format)
    mv = _writebuf(buffer, 2)
    return s._pack_into_mv(mv, offset, values)


def unpack(format, buffer, /):
    """Return a tuple containing values unpacked according to the format string.

    The buffer's size in bytes must be calcsize(format).  See help(struct)
    for more on format strings.
    """
    return _cached(format).unpack(buffer)


def unpack_from(format, /, buffer, offset=0):
    """Return a tuple containing values unpacked according to the format string.

    The buffer must contain at least calcsize(format) bytes starting at
    offset.  A negative offset counts from the end of the buffer.  See
    help(struct) for more on format strings.
    """
    return _cached(format).unpack_from(buffer, offset)


def iter_unpack(format, buffer, /):
    """Return an iterator yielding tuples unpacked from the given bytes.

    The bytes are unpacked according to the format string, like a repeated
    invocation of unpack_from().  Requires that the bytes length be
    a multiple of calcsize(format).
    """
    return _cached(format).iter_unpack(buffer)
