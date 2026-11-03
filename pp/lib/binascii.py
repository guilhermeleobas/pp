"""Pure-Python ``binascii`` (replaces Modules/binascii.c): conversion between
binary data and ASCII.

Mirrors the 3.15 C module: ``a2b_uu``/``b2a_uu``, ``a2b_base64``/``b2a_base64``
(``strict_mode``, ``padded``, ``alphabet``, ``ignorechars``, ``canonical``,
``wrapcol``, ``newline``), ``a2b_ascii85``/``b2a_ascii85``,
``a2b_base85``/``b2a_base85``, ``a2b_base32``/``b2a_base32``,
``a2b_hex``/``b2a_hex`` (and the ``unhexlify``/``hexlify`` aliases),
``a2b_qp``/``b2a_qp``, ``crc32``, ``crc_hqx``, the ``*_ALPHABET`` constants and
the ``Error`` (a ``ValueError``) and ``Incomplete`` exceptions. Decoders follow
the C state machines step by step so error messages match
``Modules/binascii.c``; ``b2a_hex`` goes through ``bytes.hex`` (the same
``_Py_strhex_with_sep`` the C code uses).

Limitations: much slower than C (every byte goes through the interpreter; the
C fast paths are not reproduced, only their results); argument-count errors
carry Python's wording rather than Argument Clinic's; a non-contiguous buffer raises memoryview's ``BufferError`` wording.
"""

import sys as _sys

_SSIZE_MAX = _sys.maxsize
_NULL = object()        # "argument not given" (C: NULL default)


class Error(ValueError):
    pass


class Incomplete(Exception):
    pass


Error.__module__ = Incomplete.__module__ = 'binascii'

BASE64_ALPHABET = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
URLSAFE_BASE64_ALPHABET = (b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                           b"0123456789-_")
CRYPT_ALPHABET = (b"./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  b"abcdefghijklmnopqrstuvwxyz")
UU_ALPHABET = b" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"
BINHEX_ALPHABET = (b"!\"#$%&'()*+,-012345689@ABCDEFGHIJKLMNPQRSTUVXYZ[`"
                   b"abcdefhijklmpqr")
BASE85_ALPHABET = (b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                   b"abcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~")
ASCII85_ALPHABET = (b"!\"#$%&'()*+,-./0123456789:;<=>?@"
                    b"ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstu")
Z85_ALPHABET = (b"0123456789abcdefghijklmnopqrstuvwxyz"
                b"ABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#")
BASE32_ALPHABET = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
BASE32HEX_ALPHABET = b"0123456789ABCDEFGHIJKLMNOPQRSTUV"

_PAD = 0x3d     # '='
_U32 = 0xffffffff
_POW85 = (1, 85, 7225, 614125, 52200625)


# ---- argument conversion ---------------------------------------------------

def _tobytes(data):
    mv = memoryview(data)
    if not mv.c_contiguous:
        raise BufferError("memoryview: underlying buffer is not C-contiguous")
    return mv.tobytes()


def _buf(data):
    # Py_buffer (PyBUF_SIMPLE).
    try:
        return _tobytes(data)
    except TypeError:
        raise TypeError("a bytes-like object is required, not "
                        f"'{type(data).__name__}'") from None


def _ascii_buf(data):
    # ascii_buffer converter: an ASCII str or a bytes-like object.
    if isinstance(data, str):
        if not data.isascii():
            raise ValueError("string argument should contain only ASCII "
                             "characters")
        return data.encode('ascii')
    try:
        return _tobytes(data)
    except TypeError:
        raise TypeError("argument should be bytes, buffer or ASCII string, "
                        f"not '{type(data).__name__}'") from None


def _size_t(v):
    m = getattr(type(v), '__index__', None)
    if m is None:
        raise TypeError(f"'{type(v).__name__}' object cannot be interpreted "
                        "as an integer")
    v = m(v)
    if v < 0:
        raise ValueError("Cannot convert negative int")
    if v >= 1 << 64:
        raise OverflowError("Python int too large for C size_t")
    return v


def _bytes_arg(func, name, v):
    if not isinstance(v, bytes):
        raise TypeError(f"{func}() argument '{name}' must be bytes, "
                        f"not {type(v).__name__}")
    return v


_reverse_cache = {}


def _reverse_table(alphabet, size, padchar):
    if len(alphabet) != size:
        raise ValueError(f"alphabet must have length {size}")
    table = _reverse_cache.get(alphabet)
    if table is None:
        out = [255] * 256
        for i, c in enumerate(alphabet):
            out[c] = i
        if padchar >= 0:
            out[padchar] = size
        table = tuple(out)
        _reverse_cache[alphabet] = table
    return table


def _reverse(alphabet, size, padchar):
    out = [255] * 256
    for i, c in enumerate(alphabet):
        out[c] = i
    if padchar >= 0:
        out[padchar] = size
    return tuple(out)


_A2B_BASE64 = _reverse(BASE64_ALPHABET, 64, _PAD)
_A2B_BASE85 = _reverse(BASE85_ALPHABET, 85, -1)
_A2B_ASCII85 = _reverse(ASCII85_ALPHABET, 85, -1)
_A2B_BASE32 = _reverse(BASE32_ALPHABET, 32, _PAD)


def _ignorer(ignorechars):
    # ignorechar(): ignorechars is None (nothing ignored) or a set of byte values.
    if ignorechars is None or len(ignorechars) == 0:
        return frozenset()
    return frozenset(ignorechars)


def _wraplines(data, width):
    if len(data) <= width:
        return data
    return bytearray(b'\n').join(
        [data[i:i + width] for i in range(0, len(data), width)])


# ---- uuencode --------------------------------------------------------------

def a2b_uu(data, /):
    """Decode a line of uuencoded data."""
    d = _ascii_buf(data)
    n = len(d)
    if n == 0:
        raise Error("Missing length byte")
    bin_len = (d[0] - 32) & 0o77
    pos = 1
    ascii_len = n - 1
    leftbits = 0
    leftchar = 0
    out = bytearray()
    while bin_len > 0:
        ch = d[pos] if ascii_len > 0 else 0
        if ch == 10 or ch == 13 or ascii_len <= 0:
            ch = 0
        else:
            if ch < 32 or ch > 32 + 64:
                raise Error("Illegal char")
            ch = (ch - 32) & 0o77
        leftchar = (leftchar << 6) | ch
        leftbits += 6
        if leftbits >= 8:
            leftbits -= 8
            out.append((leftchar >> leftbits) & 0xff)
            leftchar &= (1 << leftbits) - 1
            bin_len -= 1
        ascii_len -= 1
        pos += 1
    while ascii_len > 0:
        ch = d[pos]
        pos += 1
        ascii_len -= 1
        if ch != 32 and ch != 32 + 64 and ch != 10 and ch != 13:
            raise Error("Trailing garbage")
    return bytes(out)


def b2a_uu(data, /, *, backtick=False):
    """Uuencode line of data."""
    d = _buf(data)
    n = len(d)
    if n > 45:
        raise Error("At most 45 bytes at once")
    backtick = bool(backtick)
    out = bytearray()
    out.append(96 if backtick and not n else 32 + n)
    leftbits = 0
    leftchar = 0
    i = 0
    while n > 0 or leftbits != 0:
        if n > 0:
            leftchar = (leftchar << 8) | d[i]
        else:
            leftchar <<= 8
        leftbits += 8
        while leftbits >= 6:
            ch = (leftchar >> (leftbits - 6)) & 0x3f
            leftbits -= 6
            out.append(96 if backtick and not ch else ch + 32)
        n -= 1
        i += 1
        leftchar &= 0xffffff
    out.append(10)
    return bytes(out)


# ---- base64 ----------------------------------------------------------------

def a2b_base64(data, /, *, strict_mode=_NULL, padded=True, alphabet=_NULL,
               ignorechars=_NULL, canonical=False):
    """Decode a line of base64 data.

      strict_mode
        When set to true, bytes that are not part of the base64 standard are
        not allowed.  The same applies to excess data after padding (= / ==).
        Set to True by default if ignorechars is specified, False otherwise.
      padded
        When set to false, padding in input is not required.
      ignorechars
        A byte string containing characters to ignore from the input when
        strict_mode is true.
      canonical
        When set to true, reject non-zero padding bits per RFC 4648 section 3.5.
    """
    d = _ascii_buf(data)
    if strict_mode is _NULL:
        strict = ignorechars is not _NULL
    else:
        strict = bool(strict_mode)
    padded = bool(padded)
    if ignorechars is not _NULL:
        ignorechars = _buf(ignorechars)
    canonical = bool(canonical)
    if alphabet is _NULL:
        table = _A2B_BASE64
    else:
        table = _reverse_table(_bytes_arg('a2b_base64', 'alphabet', alphabet),
                               64, _PAD)
    ign = _ignorer(None if not strict or ignorechars is _NULL else ignorechars)
    out = bytearray()
    quad_pos = 0
    leftchar = 0
    pads = 0
    for ch in d:
        if padded and ch == _PAD:
            pads += 1
            if quad_pos >= 2 and quad_pos + pads <= 4:
                continue
            if not strict or _PAD in ign:
                continue
            if quad_pos == 1:
                break
            raise Error("Leading padding not allowed"
                        if quad_pos == 0 and not out
                        else "Excess padding not allowed")
        v = table[ch]
        if v >= 64:
            if strict and ch not in ign:
                raise Error("Padding not allowed" if ch == _PAD
                            else "Only base64 data is allowed")
            continue
        if pads and strict and _PAD not in ign:
            raise Error("Excess data after padding" if quad_pos + pads == 4
                        else "Discontinuous padding not allowed")
        pads = 0
        if quad_pos == 0:
            quad_pos = 1
            leftchar = v
        elif quad_pos == 1:
            quad_pos = 2
            out.append(((leftchar << 2) | (v >> 4)) & 0xff)
            leftchar = v & 0x0f
        elif quad_pos == 2:
            quad_pos = 3
            out.append(((leftchar << 4) | (v >> 2)) & 0xff)
            leftchar = v & 0x03
        else:
            quad_pos = 0
            out.append(((leftchar << 6) | v) & 0xff)
            leftchar = 0
    if quad_pos == 1:
        raise Error("Invalid base64-encoded string: number of data "
                    f"characters ({len(out) // 3 * 4 + 1}) cannot be 1 more "
                    "than a multiple of 4")
    if padded and quad_pos != 0 and quad_pos + pads < 4:
        raise Error("Incorrect padding")
    if canonical and leftchar != 0:
        raise Error("Non-zero padding bits")
    return bytes(out)


def b2a_base64(data, /, *, padded=True, wrapcol=0, newline=True,
               alphabet=_NULL):
    """Base64-code line of data.

      padded
        When set to false, omit padding in the output.
    """
    d = _buf(data)
    padded = bool(padded)
    wrapcol = _size_t(wrapcol)
    newline = bool(newline)
    if alphabet is _NULL:
        tbl = BASE64_ALPHABET
    else:
        tbl = _buf(alphabet)
        if len(tbl) != 64:
            raise ValueError("alphabet must have length 64")
    n = len(d)
    out = bytearray()
    full = n - n % 3
    for i in range(0, full, 3):
        c = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2]
        out += bytes((tbl[c >> 18], tbl[(c >> 12) & 0x3f],
                      tbl[(c >> 6) & 0x3f], tbl[c & 0x3f]))
    rest = n - full
    pads = 0
    if rest == 1:
        v = d[full]
        out += bytes((tbl[(v >> 2) & 0x3f], tbl[(v << 4) & 0x3f]))
        pads = 2
    elif rest == 2:
        v = (d[full] << 8) | d[full + 1]
        out += bytes((tbl[(v >> 10) & 0x3f], tbl[(v >> 4) & 0x3f],
                      tbl[(v << 2) & 0x3f]))
        pads = 1
    if padded:
        out += b'=' * pads
    if wrapcol and out:
        wrapcol = 4 if wrapcol < 4 else wrapcol // 4 * 4
        out = _wraplines(out, wrapcol)
    if newline:
        out.append(10)
    return bytes(out)


# ---- ascii85 / base85 ------------------------------------------------------

def _check_canonical_partial(left, chunk_len):
    n_pad = 4 - chunk_len
    top = (left >> (n_pad * 8)) << (n_pad * 8)
    if top // _POW85[n_pad] != left // _POW85[n_pad]:
        raise Error("Non-zero padding bits")


def a2b_ascii85(data, /, *, foldspaces=False, adobe=False, ignorechars=b'',
                canonical=False):
    """Decode Ascii85 data.

      foldspaces
        Allow 'y' as a short form encoding four spaces.
      adobe
        Expect data to be terminated with '~>' as in Adobe Ascii85, and
        optionally accept leading '<~'.
      ignorechars
        A byte string containing characters to ignore from the input.
      canonical
        When set to true, reject non-canonical encodings.
    """
    d = _ascii_buf(data)
    foldspaces = bool(foldspaces)
    adobe = bool(adobe)
    ignorechars = _buf(ignorechars)
    canonical = bool(canonical)
    if adobe:
        if len(d) < 2 or d[-2] != 0x7e or d[-1] != 0x3e:
            raise Error("Ascii85 encoded byte sequences must end with b'~>'")
        d = d[:-2]
        if len(d) >= 2 and d[0] == 0x3c and d[1] == 0x7e:
            d = d[2:]
    ign = _ignorer(ignorechars)
    out = bytearray()
    rem = len(d)
    pos = 0
    left = 0
    gp = 0
    from_z = False
    ch = 0
    while rem > 0 or gp != 0:
        if rem > 0:
            ch = d[pos]
            dig = _A2B_ASCII85[ch]
        else:
            dig = 84
        if dig < 85:
            if gp == 4 and (left > _U32 // 85 or left * 85 > _U32 - dig):
                raise Error("Ascii85 overflow")
            left = left * 85 + dig
            gp += 1
        elif (ch == 0x79 and foldspaces) or ch == 0x7a:
            if gp != 0:
                raise Error(f"'{chr(ch)}' inside Ascii85 5-tuple")
            left = 0x20202020 if ch == 0x79 else 0
            from_z = ch == 0x7a
            gp = 5
        elif ch not in ign:
            raise Error(f"Non-Ascii85 digit found: {chr(ch)}")
        if gp == 5:
            chunk_len = 3 + rem if rem < 1 else 4
            if chunk_len == 0:
                raise Error("Incomplete Ascii85 group")
            for i in range(chunk_len):
                out.append((left >> (24 - 8 * i)) & 0xff)
            if canonical:
                if chunk_len == 4 and left == 0 and not from_z:
                    raise Error("Non-canonical encoding, "
                                "use 'z' for all-zero groups")
                if chunk_len < 4:
                    _check_canonical_partial(left, chunk_len)
            from_z = False
            gp = 0
            left = 0
        rem -= 1
        pos += 1
    return bytes(out)


def _b85_digits(v, tbl):
    out = [0] * 5
    for i in range(4, 0, -1):
        out[i] = tbl[v % 85]
        v //= 85
    out[0] = tbl[v]
    return out


def b2a_ascii85(data, /, *, foldspaces=False, wrapcol=0, pad=False,
                adobe=False):
    """Ascii85-encode data.

      foldspaces
        Emit 'y' as a short form encoding four spaces.
      wrapcol
        Split result into lines of provided width.
      pad
        Retain zero-padding bytes at end of output.
      adobe
        Wrap result in '<~' and '~>' as in Adobe Ascii85.
    """
    d = _buf(data)
    foldspaces = bool(foldspaces)
    wrapcol = _size_t(wrapcol)
    pad = bool(pad)
    adobe = bool(adobe)
    if adobe and wrapcol == 1:
        wrapcol = 2
    tbl = ASCII85_ALPHABET
    n = len(d)
    out = bytearray()
    if adobe:
        out += b'<~'
    full = n - n % 4
    for i in range(0, full, 4):
        v = int.from_bytes(d[i:i + 4], 'big')
        if v == 0:
            out.append(0x7a)
        elif foldspaces and v == 0x20202020:
            out.append(0x79)
        else:
            out += bytes(_b85_digits(v, tbl))
    rest = n - full
    if rest:
        v = int.from_bytes(d[full:] + b'\0' * (4 - rest), 'big')
        if pad and v == 0:
            out.append(0x7a)
        else:
            group_len = 5 if pad else rest + 1
            out += bytes(_b85_digits(v, tbl)[:group_len])
    if adobe:
        out += b'~>'
    if wrapcol and out:
        out = _wraplines(out, wrapcol)
        if adobe and out[-2] == 10:
            out[-3] = 10
            out[-2] = 0x7e
    return bytes(out)


def a2b_base85(data, /, *, alphabet=_NULL, ignorechars=b'', canonical=False):
    """Decode a line of Base85 data.

      ignorechars
        A byte string containing characters to ignore from the input.
      canonical
        When set to true, reject non-canonical encodings.
    """
    d = _ascii_buf(data)
    ignorechars = _buf(ignorechars)
    canonical = bool(canonical)
    if alphabet is _NULL:
        table = _A2B_BASE85
    else:
        table = _reverse_table(_bytes_arg('a2b_base85', 'alphabet', alphabet),
                               85, -1)
    ign = _ignorer(ignorechars)
    n = len(d)
    out = bytearray()
    rem = n
    pos = 0
    left = 0
    gp = 0
    ch = 0
    while rem > 0 or gp != 0:
        if rem > 0:
            ch = d[pos]
            dig = table[ch]
        else:
            dig = 84
        if dig < 85:
            if gp == 4 and (left > _U32 // 85 or left * 85 > _U32 - dig):
                raise Error("Base85 overflow in hunk starting at byte "
                            f"{(n - rem) // 5 * 5}")
            left = left * 85 + dig
            gp += 1
        elif ch not in ign:
            raise Error(f"bad Base85 character at position {n - rem}")
        if gp == 5:
            chunk_len = 3 + rem if rem < 1 else 4
            if chunk_len == 0:
                raise Error("Incomplete Base85 group")
            for i in range(chunk_len):
                out.append((left >> (24 - 8 * i)) & 0xff)
            if canonical and chunk_len < 4:
                _check_canonical_partial(left, chunk_len)
            gp = 0
            left = 0
        rem -= 1
        pos += 1
    return bytes(out)


def b2a_base85(data, /, *, pad=False, wrapcol=0, alphabet=_NULL):
    """Base85-code line of data.

      pad
        Retain zero-padding bytes at end of output.
    """
    d = _buf(data)
    pad = bool(pad)
    wrapcol = _size_t(wrapcol)
    if alphabet is _NULL:
        tbl = BASE85_ALPHABET
    else:
        tbl = _buf(alphabet)
        if len(tbl) != 85:
            raise ValueError("alphabet must have length 85")
    n = len(d)
    out = bytearray()
    full = n - n % 4
    for i in range(0, full, 4):
        out += bytes(_b85_digits(int.from_bytes(d[i:i + 4], 'big'), tbl))
    rest = n - full
    if rest:
        v = int.from_bytes(d[full:] + b'\0' * (4 - rest), 'big')
        group_len = 5 if pad else rest + 1
        out += bytes(_b85_digits(v, tbl)[:group_len])
    if wrapcol and out:
        wrapcol = 5 if wrapcol < 5 else wrapcol // 5 * 5
        out = _wraplines(out, wrapcol)
    return bytes(out)


# ---- base32 ----------------------------------------------------------------

def a2b_base32(data, /, *, padded=True, alphabet=_NULL, ignorechars=b'',
               canonical=False):
    """Decode a line of base32 data.

      padded
        When set to false, padding in input is not required.
      ignorechars
        A byte string containing characters to ignore from the input.
      canonical
        When set to true, reject non-zero padding bits per RFC 4648 section 3.5.
    """
    d = _ascii_buf(data)
    padded = bool(padded)
    ignorechars = _buf(ignorechars)
    canonical = bool(canonical)
    if alphabet is _NULL:
        table = _A2B_BASE32
    else:
        table = _reverse_table(_bytes_arg('a2b_base32', 'alphabet', alphabet),
                               32, _PAD)
    ign = _ignorer(ignorechars)
    out = bytearray()
    leftchar = 0
    octa_pos = 0
    pads = 0
    for ch in d:
        if padded and ch == _PAD:
            pads += 1
            if octa_pos in (2, 4, 5, 7) and octa_pos + pads <= 8:
                continue
            if _PAD in ign:
                continue
            if octa_pos in (1, 3, 6):
                break
            raise Error("Leading padding not allowed"
                        if octa_pos == 0 and not out
                        else "Excess padding not allowed")
        v = table[ch]
        if v >= 32:
            if ch not in ign:
                raise Error("Padding not allowed" if ch == _PAD
                            else "Only base32 data is allowed")
            continue
        if pads and _PAD not in ign:
            raise Error("Excess data after padding" if octa_pos + pads == 8
                        else "Discontinuous padding not allowed")
        if octa_pos == 0:
            octa_pos = 1
            leftchar = v
        elif octa_pos == 1:
            octa_pos = 2
            out.append(((leftchar << 3) | (v >> 2)) & 0xff)
            leftchar = v & 0x03
        elif octa_pos == 2:
            octa_pos = 3
            leftchar = ((leftchar << 5) | v) & 0xff
        elif octa_pos == 3:
            octa_pos = 4
            out.append(((leftchar << 1) | (v >> 4)) & 0xff)
            leftchar = v & 0x0f
        elif octa_pos == 4:
            octa_pos = 5
            out.append(((leftchar << 4) | (v >> 1)) & 0xff)
            leftchar = v & 0x01
        elif octa_pos == 5:
            octa_pos = 6
            leftchar = ((leftchar << 5) | v) & 0xff
        elif octa_pos == 6:
            octa_pos = 7
            out.append(((leftchar << 2) | (v >> 3)) & 0xff)
            leftchar = v & 0x07
        else:
            octa_pos = 0
            out.append(((leftchar << 5) | v) & 0xff)
            leftchar = 0
        # C resets nothing here: pads was zero (or ignored) on this path
    if octa_pos in (1, 3, 6):
        raise Error("Invalid base32-encoded string: number of data "
                    f"characters ({len(out) // 5 * 8 + octa_pos}) "
                    "cannot be 1, 3, or 6 more than a multiple of 8")
    if padded and octa_pos != 0 and octa_pos + pads < 8:
        raise Error("Incorrect padding")
    if canonical and leftchar != 0:
        raise Error("Non-zero padding bits")
    return bytes(out)


def b2a_base32(data, /, *, padded=True, wrapcol=0, alphabet=_NULL):
    """Base32-code line of data.

      padded
        When set to false, omit padding in the output.
    """
    d = _buf(data)
    padded = bool(padded)
    wrapcol = _size_t(wrapcol)
    if alphabet is _NULL:
        tbl = BASE32_ALPHABET
    else:
        tbl = _buf(alphabet)
        if len(tbl) != 32:
            raise ValueError("alphabet must have length 32")
    n = len(d)
    out = bytearray()
    full = n - n % 5
    for i in range(0, full, 5):
        c = int.from_bytes(d[i:i + 5], 'big')
        out += bytes([tbl[(c >> s) & 0x1f] for s in (35, 30, 25, 20, 15, 10, 5, 0)])
    rest = n - full
    if rest:
        nchars = {1: 2, 2: 4, 3: 5, 4: 7}[rest]
        c = int.from_bytes(d[full:], 'big')
        # left-align the remaining bits on a 5-bit boundary
        c <<= nchars * 5 - rest * 8
        out += bytes([tbl[(c >> (5 * (nchars - 1 - k))) & 0x1f]
                      for k in range(nchars)])
        if padded:
            out += b'=' * (8 - nchars)
    if wrapcol and out:
        wrapcol = 8 if wrapcol < 8 else wrapcol // 8 * 8
        out = _wraplines(out, wrapcol)
    return bytes(out)


# ---- checksums -------------------------------------------------------------

def _make_crc_hqx_table():
    tab = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) if c & 0x8000 else (c << 1)
        tab.append(c & 0xffff)
    return tuple(tab)


def _make_crc32_table():
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xedb88320 if c & 1 else c >> 1
        tab.append(c)
    return tuple(tab)


_CRCTAB_HQX = _make_crc_hqx_table()
_CRC_32_TAB = _make_crc32_table()


def _uint(v):
    # unsigned_int(bitwise=True): any int, masked to 32 bits; a value outside
    # [-2**31, 2**32) warns.
    m = getattr(type(v), '__index__', None)
    if m is None:
        raise TypeError(f"'{type(v).__name__}' object cannot be interpreted "
                        "as an integer")
    v = m(v)
    if not -(1 << 31) <= v < (1 << 32):
        import warnings
        warnings.warn("integer value out of range", DeprecationWarning, 3)
    return v & _U32


def crc_hqx(data, crc, /):
    """Compute CRC-CCITT incrementally."""
    d = _buf(data)
    crc = _uint(crc) & 0xffff
    tab = _CRCTAB_HQX
    for b in d:
        crc = ((crc << 8) & 0xff00) ^ tab[(crc >> 8) ^ b]
    return crc


def crc32(data, crc=0, /):
    """Compute CRC-32 incrementally."""
    d = _buf(data)
    crc = _uint(crc) ^ _U32
    tab = _CRC_32_TAB
    for b in d:
        crc = tab[(crc ^ b) & 0xff] ^ (crc >> 8)
    return crc ^ _U32


# ---- hex -------------------------------------------------------------------

def b2a_hex(data, /, sep=_NULL, bytes_per_sep=1):
    """Hexadecimal representation of binary data.

      sep
        An optional single character or byte to separate hex bytes.
      bytes_per_sep
        How many bytes between separators.  Positive values count from the
        right, negative values count from the left.

    The return value is a bytes object.  This function is also
    available as "hexlify()".

    Example:
    >>> binascii.b2a_hex(b'\\xb9\\x01\\xef')
    b'b901ef'
    >>> binascii.hexlify(b'\\xb9\\x01\\xef', ':')
    b'b9:01:ef'
    >>> binascii.b2a_hex(b'\\xb9\\x01\\xef', b'_', 2)
    b'b9_01ef'
    """
    d = _buf(data)
    m = getattr(type(bytes_per_sep), '__index__', None)
    if m is None:
        raise TypeError(f"'{type(bytes_per_sep).__name__}' object cannot be "
                        "interpreted as an integer")
    bytes_per_sep = m(bytes_per_sep)
    if not -(1 << 63) <= bytes_per_sep < (1 << 63):
        raise OverflowError("Python int too large to convert to C ssize_t")
    if sep is _NULL:
        return d.hex().encode('ascii')
    # _Py_strhex_bytes_with_sep: the bytes variant accepts a Latin-1 str separator.
    if isinstance(sep, str):
        if len(sep) != 1:
            raise ValueError("sep must be length 1.")
        if ord(sep) > 255:
            raise ValueError("sep must be ASCII.")
        sepbyte = ord(sep)
    elif isinstance(sep, bytes):
        if len(sep) != 1:
            raise ValueError("sep must be length 1.")
        sepbyte = sep[0]
    else:
        len(sep)    # the C code asks for the length first
        raise TypeError("sep must be str or bytes.")
    n = len(d)
    chunk = abs(bytes_per_sep)
    if bytes_per_sep == 0 or chunk >= n:
        return d.hex().encode('ascii')
    if bytes_per_sep > 0:
        first = n % chunk
        cuts = ([0, first] if first else [0]) + list(range(first + chunk, n, chunk))
    else:
        cuts = list(range(0, n, chunk))
    cuts.append(n)
    sepb = bytes((sepbyte,))
    return sepb.join([d[a:b].hex().encode('ascii')
                      for a, b in zip(cuts, cuts[1:])])


hexlify = b2a_hex


def a2b_hex(hexstr, /, *extra, ignorechars=b''):
    """Binary data of hexadecimal representation.

      ignorechars
        A byte string containing characters to ignore from the input.

    hexstr must contain an even number of hex digits (upper or lower case).
    This function is also available as "unhexlify()".
    """
    if extra:
        raise TypeError("a2b_hex() takes exactly 1 positional argument "
                        f"({1 + len(extra)} given)")
    return _a2b_hex(hexstr, ignorechars)


def unhexlify(hexstr, /, *extra, ignorechars=b''):
    """Binary data of hexadecimal representation.

      ignorechars
        A byte string containing characters to ignore from the input.

    hexstr must contain an even number of hex digits (upper or lower case).
    """
    if extra:
        raise TypeError("unhexlify() takes exactly 1 positional argument "
                        f"({1 + len(extra)} given)")
    return _a2b_hex(hexstr, ignorechars)


def _a2b_hex(hexstr, ignorechars):
    d = _ascii_buf(hexstr)
    ign = _ignorer(_buf(ignorechars))
    out = bytearray()
    pair_pos = 0
    leftchar = 0
    for ch in d:
        if 48 <= ch <= 57:
            v = ch - 48
        elif 97 <= ch <= 102:
            v = ch - 87
        elif 65 <= ch <= 70:
            v = ch - 55
        else:
            if ch not in ign:
                raise Error("Non-hexadecimal digit found")
            continue
        if not pair_pos:
            pair_pos = 1
            leftchar = v
        else:
            pair_pos = 0
            out.append((leftchar << 4) | v)
    if pair_pos:
        raise Error("Odd number of hexadecimal digits")
    return bytes(out)



# ---- quoted-printable ------------------------------------------------------

_MAXLINESIZE = 76
_HEXDIGITS = b'0123456789abcdefABCDEF'


def _hexval(c):
    return c - 48 if c <= 57 else (c - 87 if c >= 97 else c - 55)


def a2b_qp(data, header=False):
    """Decode a string of qp-encoded data."""
    d = _ascii_buf(data)
    header = bool(header)
    n = len(d)
    out = bytearray()
    i = 0
    while i < n:
        c = d[i]
        if c == 0x3d:   # '='
            i += 1
            if i >= n:
                break
            c = d[i]
            if c == 10 or c == 13:
                if c != 10:
                    while i < n and d[i] != 10:
                        i += 1
                if i < n:
                    i += 1
            elif c == 0x3d:
                out.append(0x3d)
                i += 1
            elif i + 1 < n and c in _HEXDIGITS and d[i + 1] in _HEXDIGITS:
                out.append((_hexval(c) << 4) | _hexval(d[i + 1]))
                i += 2
            else:
                out.append(0x3d)
        elif header and c == 0x5f:  # '_'
            out.append(0x20)
            i += 1
        else:
            out.append(c)
            i += 1
    return bytes(out)


_HEXUP = b'0123456789ABCDEF'


def b2a_qp(data, quotetabs=False, istext=True, header=False):
    """Encode a string using quoted-printable encoding.

    On encoding, when istext is set, newlines are not encoded, and white
    space at end of lines is.  When istext is not set, \\r and \\n (CR/LF)
    are both encoded.  When quotetabs is set, space and tabs are encoded.
    """
    d = _buf(data)
    quotetabs = bool(quotetabs)
    istext = bool(istext)
    header = bool(header)
    n = len(d)
    p = d.find(b'\n')
    crlf = p > 0 and d[p - 1] == 13
    out = bytearray()
    linelen = 0
    i = 0
    while i < n:
        c = d[i]
        if (c > 126 or c == 0x3d
                or (header and c == 0x5f)
                or (c == 0x2e and linelen == 0
                    and (i + 1 == n or d[i + 1] in (10, 13, 0)))
                or (not istext and (c == 13 or c == 10))
                or ((c == 9 or c == 32) and i + 1 == n)
                or (c < 33 and c != 13 and c != 10
                    and (quotetabs or (c != 9 and c != 32)))):
            if linelen + 3 >= _MAXLINESIZE:
                out.append(0x3d)
                if crlf:
                    out.append(13)
                out.append(10)
                linelen = 0
            out.append(0x3d)
            out.append(_HEXUP[c >> 4])
            out.append(_HEXUP[c & 15])
            i += 1
            linelen += 3
        else:
            if istext and (c == 10 or (i + 1 < n and c == 13 and d[i + 1] == 10)):
                linelen = 0
                if out and (out[-1] == 32 or out[-1] == 9):
                    ch = out[-1]
                    out[-1] = 0x3d
                    out.append(_HEXUP[ch >> 4])
                    out.append(_HEXUP[ch & 15])
                if crlf:
                    out.append(13)
                out.append(10)
                i += 2 if c == 13 else 1
            else:
                if i + 1 != n and d[i + 1] != 10 and linelen + 1 >= _MAXLINESIZE:
                    out.append(0x3d)
                    if crlf:
                        out.append(13)
                    out.append(10)
                    linelen = 0
                linelen += 1
                if header and c == 32:
                    out.append(0x5f)
                else:
                    out.append(c)
                i += 1
    return bytes(out)


def __dir__():
    # Hide the private helpers: dir(binascii) lists what the C module has.
    return sorted(n for n in globals()
                  if not n.startswith('_')
                  or (n.startswith('__') and n not in ('__builtins__', '__dir__')))
