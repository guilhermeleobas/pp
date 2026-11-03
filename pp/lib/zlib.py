"""Pure-Python ``zlib`` (replaces Modules/zlibmodule.c and libz).

Mirrors the 3.15 C module: ``compress``, ``decompress`` (zlib, raw, gzip and
auto-detect ``wbits``, ``bufsize``), ``compressobj`` / ``decompressobj`` (with
``zdict``, ``unused_data``, ``unconsumed_tail``, ``eof``, ``max_length``,
``flush`` and ``copy``), the ``_ZlibDecompressor`` type that ``gzip`` uses,
``crc32`` / ``adler32`` and their ``*_combine`` functions, the ``Z_*``
constants, and ``error`` with the C message format ("Error -3 while
decompressing data: incorrect header check").

Inflate is a complete resumable decoder (stored, fixed and dynamic Huffman
blocks, table-driven, bytearray output): it takes input in any chunking, honours
an output limit, and reports the same data errors as libz.

Deflate is a real compressor (LZ77 with hash chains, lazy matching at levels 4
and up, stored / fixed / dynamic blocks chosen by size, all strategies and
flush modes) but it is NOT libz's: the compressed bytes are valid and
round-trip through any inflater, yet they differ from libz's bytes and
ratios differ slightly. Do not compare compressed output to libz's.

Limitations: much slower than C (everything is interpreted; ``crc32`` runs one
table lookup per byte); input is not released between calls, memory is
O(window + one 256 KiB segment) per compressor; ``ZLIB_VERSION`` is a fixed
string; ``Compress``/``Decompress`` are plain classes whose instantiation is
blocked by ``__new__`` (not immutable static types); a ``compress`` call may
return less output than libz would at the same point (data is buffered until a
256 KiB segment is full or ``flush`` is called). After an output-limit stop
(``max_length``) ``Decompress.unconsumed_tail`` can be one byte longer than libz's:
libz has already pulled the next symbol's code bits into its state, this decoder
returns every unread whole byte.
"""

import operator as _operator

_MAXSIZE = (1 << 63) - 1

MAX_WBITS = 15
DEFLATED = 8
DEF_MEM_LEVEL = 8
DEF_BUF_SIZE = 16384
Z_NO_COMPRESSION = 0
Z_BEST_SPEED = 1
Z_BEST_COMPRESSION = 9
Z_DEFAULT_COMPRESSION = -1
Z_FILTERED = 1
Z_HUFFMAN_ONLY = 2
Z_RLE = 3
Z_FIXED = 4
Z_DEFAULT_STRATEGY = 0
Z_NO_FLUSH = 0
Z_PARTIAL_FLUSH = 1
Z_SYNC_FLUSH = 2
Z_FULL_FLUSH = 3
Z_FINISH = 4
Z_BLOCK = 5
Z_TREES = 6
ZLIB_VERSION = '1.3.1'
ZLIB_RUNTIME_VERSION = '1.3.1'


class error(Exception):
    pass


error.__module__ = 'zlib'

_NULL = object()        # "argument not given" (C: NULL default)


class _ZError(Exception):
    """Internal: a zlib return code (and message) to turn into ``error``."""

    def __init__(self, code, msg=None):
        self.code = code
        self.msg = msg


class _Need(Exception):
    """Internal: the input ran out in the middle of a header."""


def _zerr(code, msg, where):
    # zlib_error()
    if msg is None:
        msg = {-5: 'incomplete or truncated stream',
               -2: 'inconsistent stream state',
               -3: 'invalid input data'}.get(code)
    if msg is None:
        return error(f"Error {code} {where}")
    return error(f"Error {code} {where}: {msg}")


# --- argument conversion ------------------------------------------------

def _buf(data):
    # Py_buffer argument (PyBUF_SIMPLE): bytes of any bytes-like object.
    if type(data) is bytes:
        return data
    try:
        mv = memoryview(data)
    except TypeError:
        raise TypeError("a bytes-like object is required, not "
                        f"'{type(data).__name__}'") from None
    if not mv.c_contiguous:
        raise BufferError("memoryview: underlying buffer is not C-contiguous")
    return mv.tobytes()


def _index(v):
    m = getattr(type(v), '__index__', None)
    if m is None:
        raise TypeError(f"'{type(v).__name__}' object cannot be interpreted "
                        "as an integer")
    return m(v)


def _ssize(v):
    v = _index(v)
    if not -(1 << 63) <= v < (1 << 63):
        raise OverflowError("Python int too large to convert to C ssize_t")
    return v


def _cint(v):
    v = _index(v)
    if not -(1 << 31) <= v < (1 << 31):
        raise OverflowError("Python int too large to convert to C int")
    return v


def _uint(v):
    # unsigned_int(bitwise=True): any int, masked to 32 bits; a value outside
    # [-2**31, 2**32) warns.
    v = _index(v)
    if not -(1 << 31) <= v < (1 << 32):
        import warnings
        warnings.warn("integer value out of range", DeprecationWarning, 3)
    return v & 0xffffffff


# --- checksums ----------------------------------------------------------

def _make_crc32_table():
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xedb88320 if c & 1 else c >> 1
        tab.append(c)
    return tuple(tab)


_CRC_TAB = _make_crc32_table()


def _crc32_raw(data, crc):
    crc ^= 0xffffffff
    tab = _CRC_TAB
    for b in data:
        crc = tab[(crc ^ b) & 0xff] ^ (crc >> 8)
    return crc ^ 0xffffffff


_mul = int.__mul__


def _adler32_raw(data, value):
    a = value & 0xffff
    b = (value >> 16) & 0xffff
    n = len(data)
    i = 0
    while i < n:
        chunk = data[i:i + 5552]
        m = len(chunk)
        b += m * a + sum(map(_mul, chunk, range(m, 0, -1)))
        a += sum(chunk)
        a %= 65521
        b %= 65521
        i += m
    return ((b % 65521) << 16) | (a % 65521)


def crc32(data=_NULL, value=0, /):
    """Compute a CRC-32 checksum of data.

    value
      Starting value of the checksum.

    The returned checksum is an integer.
    """
    if data is _NULL:
        raise TypeError("crc32 expected at least 1 argument, got 0")
    return _crc32_raw(_buf(data), _uint(value))


def adler32(data=_NULL, value=1, /):
    """Compute an Adler-32 checksum of data.

    value
      Starting value of the checksum.

    The returned checksum is an integer.
    """
    if data is _NULL:
        raise TypeError("adler32 expected at least 1 argument, got 0")
    return _adler32_raw(_buf(data), _uint(value))


def _nargs(name, *args):
    got = sum(1 for a in args if a is not _NULL)
    if got != 3:
        raise TypeError(f"{name} expected 3 arguments, got {got}")


def _len2(len2):
    if not isinstance(len2, int):
        raise TypeError("crc32_combine() argument 'len2' must be int, not "
                        f"{type(len2).__name__}")
    if not -(1 << 63) <= len2 < (1 << 63):
        raise OverflowError("Python int too large to convert to C ssize_t")
    if len2 < 0:
        raise ValueError("len2 must be non-negative")
    return len2


def _gf2_times(mat, vec):
    s = 0
    i = 0
    while vec:
        if vec & 1:
            s ^= mat[i]
        vec >>= 1
        i += 1
    return s


def _gf2_square(mat):
    return [_gf2_times(mat, mat[n]) for n in range(32)]


def crc32_combine(a=_NULL, b=_NULL, len2=_NULL, /):
    """Combine two CRC-32 checksums into one.

    crc1
      CRC-32 checksum for sequence A
    crc2
      CRC-32 checksum for sequence B
    len2
      Length of sequence B

    Given the CRC-32 checksum 'crc1' of a sequence A and the
    CRC-32 checksum 'crc2' of a sequence B of length 'len2',
    return the CRC-32 checksum of A and B concatenated.
    """
    _nargs('crc32_combine', a, b, len2)
    crc1 = _uint(a)
    crc2 = _uint(b)
    len2 = _len2(len2)
    if len2 == 0:
        return crc1
    odd = [0xedb88320] + [1 << n for n in range(31)]
    even = _gf2_square(odd)
    odd = _gf2_square(even)
    while True:
        even = _gf2_square(odd)
        if len2 & 1:
            crc1 = _gf2_times(even, crc1)
        len2 >>= 1
        if not len2:
            break
        odd = _gf2_square(even)
        if len2 & 1:
            crc1 = _gf2_times(odd, crc1)
        len2 >>= 1
        if not len2:
            break
    return crc1 ^ crc2


def adler32_combine(a=_NULL, b=_NULL, len2=_NULL, /):
    """Combine two Adler-32 checksums into one.

    adler1
      Adler-32 checksum for sequence A
    adler2
      Adler-32 checksum for sequence B
    len2
      Length of sequence B

    Given the Adler-32 checksum 'adler1' of a sequence A and the
    Adler-32 checksum 'adler2' of a sequence B of length 'len2',
    return the Adler-32 checksum of A and B concatenated.
    """
    _nargs('adler32_combine', a, b, len2)
    adler1 = _uint(a)
    adler2 = _uint(b)
    len2 = _len2(len2)
    base = 65521
    rem = len2 % base
    sum1 = adler1 & 0xffff
    sum2 = (rem * sum1) % base
    sum1 += (adler2 & 0xffff) + base - 1
    sum2 += ((adler1 >> 16) & 0xffff) + ((adler2 >> 16) & 0xffff) + base - rem
    if sum1 >= base:
        sum1 -= base
    if sum1 >= base:
        sum1 -= base
    if sum2 >= (base << 1):
        sum2 -= base << 1
    if sum2 >= base:
        sum2 -= base
    return sum1 | (sum2 << 16)


# --- deflate format tables ----------------------------------------------

_LBASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43,
          51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
_LEXT = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4,
         4, 5, 5, 5, 5, 0)
_DBASE = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385,
          513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385,
          24577)
_DEXT = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10,
         10, 11, 11, 12, 12, 13, 13)
_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)

_REV8 = [int(bin(i)[2:].zfill(8)[::-1], 2) for i in range(256)]


def _build(lens, kind):
    """Decode table for the code lengths ``lens``: ``(table, bits)`` or None.

    ``table[next bits]`` is ``(symbol << 6) | length``; an unused code is 63.
    ``kind`` 0 is the code-length code (must be complete), 1 a literal/length
    or distance code (an incomplete code is fine only if it is one code of
    length 1), as in inftrees.c.
    """
    count = [0] * 16
    for l in lens:
        count[l] += 1
    count[0] = 0
    maxl = 15
    while maxl > 0 and count[maxl] == 0:
        maxl -= 1
    if maxl == 0:
        return [63, 63], 1
    left = 1
    for l in range(1, 16):
        left = (left << 1) - count[l]
        if left < 0:
            return None
    if left > 0 and (kind == 0 or maxl != 1):
        return None
    nxt = [0] * 16
    code = 0
    for b in range(1, 16):
        code = (code + count[b - 1]) << 1
        nxt[b] = code
    table = [63] * (1 << maxl)
    rev8 = _REV8
    for sym, l in enumerate(lens):
        if l:
            c = nxt[l]
            nxt[l] = c + 1
            r = ((rev8[c & 255] << 8) | rev8[c >> 8]) >> (16 - l)
            table[r::1 << l] = [(sym << 6) | l] * (1 << (maxl - l))
    return table, maxl


def _codes(lens):
    """Canonical codes for ``lens``, bit-reversed for LSB-first output."""
    count = [0] * 16
    for l in lens:
        count[l] += 1
    count[0] = 0
    nxt = [0] * 16
    code = 0
    for b in range(1, 16):
        code = (code + count[b - 1]) << 1
        nxt[b] = code
    out = [0] * len(lens)
    rev8 = _REV8
    for s, l in enumerate(lens):
        if l:
            c = nxt[l]
            nxt[l] = c + 1
            out[s] = ((rev8[c & 255] << 8) | rev8[c >> 8]) >> (16 - l)
    return out


_FIXED_LIT_LENS = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
_FIXED_DIST_LENS = [5] * 32
_FIXED_DECODE = None


def _fixed_decode():
    global _FIXED_DECODE
    if _FIXED_DECODE is None:
        lt, lb = _build(_FIXED_LIT_LENS, 1)
        dt, db = _build(_FIXED_DIST_LENS, 1)
        _FIXED_DECODE = (lt, lb, dt, db)
    return _FIXED_DECODE


def _fill(d, pos, bb, bc, k):
    while bc < k:
        if pos >= len(d):
            raise _Need
        bb |= d[pos] << bc
        bc += 8
        pos += 1
    return pos, bb, bc


# --- inflate ------------------------------------------------------------

(_HEAD, _DICT, _BLOCK, _STORED, _CODES, _TRAILER, _DONE, _BAD) = range(8)
_MAXOUT = 1 << 62


class _Inflate:
    """Resumable inflate of a raw, zlib or gzip stream (inflate.c)."""

    def __init__(self, wbits):
        if wbits < 0:
            wrap = 0
            wb = -wbits
        else:
            wrap = (wbits >> 4) + 5
            wb = wbits & 15 if wbits < 48 else wbits
        if wb and (wb < 8 or wb > 15):
            raise _ZError(-2)
        self.wrap = wrap            # 0 raw, bit 0 zlib allowed, bit 1 gzip allowed
        self.wbits = wb             # 0: take the window size from the header
        self.wsize = 1 << wb if wb else 0
        self.mode = _HEAD if wrap else _BLOCK
        self.gz = False
        self.bitbuf = 0
        self.bitcnt = 0
        self.win = bytearray()
        self.pend = b''             # input zlib would have consumed into its state
        self.last = False
        self.check = 1
        self.total = 0
        self.dictid = 0
        self.ltab = self.dtab = None
        self.lbits = self.dbits = 0
        self.stored_left = 0
        self.mlen = 0
        self.mdist = 0
        self.errmsg = None

    def clone(self):
        new = object.__new__(_Inflate)
        new.__dict__.update(self.__dict__)
        new.win = bytearray(self.win)
        return new

    # -- headers ---------------------------------------------------------

    def _head(self, d, p):
        n = len(d)
        if n - p < 2:
            raise _Need
        b0 = d[p]
        b1 = d[p + 1]
        if self.wrap & 2 and b0 == 0x1f and b1 == 0x8b:
            if n - p < 10:
                raise _Need
            if d[p + 2] != 8:
                raise _ZError(-3, 'unknown compression method')
            flg = d[p + 3]
            if flg & 0xe0:
                raise _ZError(-3, 'unknown header flags set')
            q = p + 10
            if flg & 4:
                if n - q < 2:
                    raise _Need
                q += 2 + d[q] + (d[q + 1] << 8)
                if n < q:
                    raise _Need
            for bit in (8, 16):
                if flg & bit:
                    i = d.find(b'\0', q)
                    if i < 0:
                        raise _Need
                    q = i + 1
            if flg & 2:
                if n - q < 2:
                    raise _Need
                if _crc32_raw(d[p:q], 0) & 0xffff != d[q] | (d[q + 1] << 8):
                    raise _ZError(-3, 'header crc mismatch')
                q += 2
            if not self.wbits:
                self.wbits = 15
                self.wsize = 1 << 15
            self.gz = True
            self.check = 0
            self.mode = _BLOCK
            return q
        if not self.wrap & 1 or ((b0 << 8) + b1) % 31:
            raise _ZError(-3, 'incorrect header check')
        if b0 & 15 != 8:
            raise _ZError(-3, 'unknown compression method')
        ln = (b0 >> 4) + 8
        if not self.wbits:
            self.wbits = ln
            self.wsize = 1 << ln
        if ln > 15 or ln > self.wbits:
            raise _ZError(-3, 'invalid window size')
        self.gz = False
        self.check = 1
        q = p + 2
        if b1 & 0x20:
            if n - q < 4:
                raise _Need
            self.dictid = int.from_bytes(d[q:q + 4], 'big')
            q += 4
            self.mode = _DICT
        else:
            self.mode = _BLOCK
        return q

    def set_dict(self, zdict):
        """inflateSetDictionary()."""
        if self.wrap and self.mode != _DICT:
            raise _ZError(-2)
        if self.mode == _DICT:
            if _adler32_raw(zdict, 1) != self.dictid:
                raise _ZError(-3)
            self.mode = _BLOCK
        self.win = bytearray(zdict[-self.wsize:] if self.wsize else b'')

    def _block_header(self, d, pos, bb, bc):
        pos, bb, bc = _fill(d, pos, bb, bc, 3)
        last = bb & 1
        typ = (bb >> 1) & 3
        bb >>= 3
        bc -= 3
        if typ == 0:
            r = bc & 7
            bb >>= r
            bc -= r
            pos, bb, bc = _fill(d, pos, bb, bc, 32)
            ln = bb & 0xffff
            if ln != ((bb >> 16) & 0xffff) ^ 0xffff:
                raise _ZError(-3, 'invalid stored block lengths')
            bc -= 32
            # whole bytes still in the bit buffer go back to the input
            pos -= bc >> 3
            return last, 0, ln, pos, 0, 0
        if typ == 1:
            return last, 1, _fixed_decode(), pos, bb, bc
        if typ == 3:
            raise _ZError(-3, 'invalid block type')
        pos, bb, bc = _fill(d, pos, bb, bc, 14)
        nlen = (bb & 31) + 257
        ndist = ((bb >> 5) & 31) + 1
        ncode = ((bb >> 10) & 15) + 4
        bb >>= 14
        bc -= 14
        if nlen > 286 or ndist > 30:
            raise _ZError(-3, 'too many length or distance symbols')
        cl = [0] * 19
        for i in range(ncode):
            pos, bb, bc = _fill(d, pos, bb, bc, 3)
            cl[_ORDER[i]] = bb & 7
            bb >>= 3
            bc -= 3
        built = _build(cl, 0)
        if built is None:
            raise _ZError(-3, 'invalid code lengths set')
        ctab, cbits = built
        cmask = (1 << cbits) - 1
        total = nlen + ndist
        lens = [0] * total
        have = 0
        n = len(d)
        while have < total:
            while bc < 14 and pos < n:
                bb |= d[pos] << bc
                bc += 8
                pos += 1
            e = ctab[bb & cmask]
            l = e & 63
            if l > bc:
                raise _Need
            sym = e >> 6
            bb >>= l
            bc -= l
            if sym < 16:
                lens[have] = sym
                have += 1
                continue
            if sym == 16:
                if have == 0:
                    raise _ZError(-3, 'invalid bit length repeat')
                prev = lens[have - 1]
                k = 2
                add = 3
            elif sym == 17:
                prev = 0
                k = 3
                add = 3
            else:
                prev = 0
                k = 7
                add = 11
            if bc < k:
                raise _Need
            rep = add + (bb & ((1 << k) - 1))
            bb >>= k
            bc -= k
            if have + rep > total:
                raise _ZError(-3, 'invalid bit length repeat')
            lens[have:have + rep] = [prev] * rep
            have += rep
        if lens[256] == 0:
            raise _ZError(-3, 'invalid code -- missing end-of-block')
        lt = _build(lens[:nlen], 1)
        if lt is None:
            raise _ZError(-3, 'invalid literal/lengths set')
        dt = _build(lens[nlen:], 1)
        if dt is None:
            raise _ZError(-3, 'invalid distances set')
        return last, 2, (lt[0], lt[1], dt[0], dt[1]), pos, bb, bc

    # -- checksum --------------------------------------------------------

    def _upd(self, win, start):
        if start >= len(win) or not self.wrap:
            return
        chunk = win[start:]
        if self.gz:
            self.check = _crc32_raw(chunk, self.check)
        else:
            self.check = _adler32_raw(chunk, self.check)
        self.total += len(chunk)

    # -- the decoder -----------------------------------------------------

    def run(self, data, maxout):
        """Inflate ``data``; return ``(output, status, leftover)``.

        ``maxout`` limits the output (None: unlimited). Status is 'ok' (all
        input consumed, more needed), 'limit' (output limit reached; ``leftover``
        is the unconsumed input), 'dict' (a preset dictionary is needed;
        ``leftover`` is the unconsumed input) or 'end' (end of stream;
        ``leftover`` is what follows it).
        """
        mode = self.mode
        if mode == _BAD:
            raise _ZError(-3, self.errmsg)
        if mode == _DONE:
            return b'', 'end', data
        if self.pend:
            data = self.pend + data
            self.pend = b''
        win = self.win
        base = len(win)
        limit = _MAXOUT if maxout is None else base + maxout
        wsize = self.wsize
        pos = 0
        dlen = len(data)
        bitbuf = self.bitbuf
        bitcnt = self.bitcnt
        mlen = self.mlen
        mdist = self.mdist
        status = None
        checked = base
        lextra = _LEXT
        lbase = _LBASE
        dextra = _DEXT
        dbase = _DBASE
        frombytes = int.from_bytes
        try:
            while True:
                if mode == _CODES:
                    ltab = self.ltab
                    lbits = self.lbits
                    lmask = (1 << lbits) - 1
                    dtab = self.dtab
                    dbits = self.dbits
                    dmask = (1 << dbits) - 1
                    n = len(win)
                    if mlen:
                        room = limit - n
                        if room <= 0:
                            status = 'limit'
                            break
                        take = mlen if mlen <= room else room
                        s = n - mdist
                        if mdist >= take:
                            win += win[s:s + take]
                        else:
                            win += (win[s:] * (take // mdist + 1))[:take]
                        n += take
                        mlen -= take
                        if mlen:
                            status = 'limit'
                            break
                    while True:
                        tail = False
                        if bitcnt < 48:
                            if pos < dlen:
                                chunk = data[pos:pos + 6]
                                bitbuf |= frombytes(chunk, 'little') << bitcnt
                                k = len(chunk)
                                bitcnt += k << 3
                                pos += k
                            tail = bitcnt < 48
                        e = ltab[bitbuf & lmask]
                        l = e & 63
                        if l > bitcnt:
                            if tail and (l != 63 or bitcnt < lbits):
                                status = 'ok'
                                break
                            raise _ZError(-3, 'invalid literal/length code')
                        sym = e >> 6
                        if sym < 256:
                            if n >= limit:
                                status = 'limit'
                                break
                            bitbuf >>= l
                            bitcnt -= l
                            win.append(sym)
                            n += 1
                            continue
                        if sym == 256:
                            bitbuf >>= l
                            bitcnt -= l
                            mode = _BLOCK
                            break
                        sym -= 257
                        if sym > 28:
                            raise _ZError(-3, 'invalid literal/length code')
                        if n >= limit:
                            status = 'limit'
                            break
                        bb = bitbuf >> l
                        bc = bitcnt - l
                        eb = lextra[sym]
                        if tail and bc < eb:
                            status = 'ok'
                            break
                        ln = lbase[sym] + (bb & ((1 << eb) - 1))
                        bb >>= eb
                        bc -= eb
                        e = dtab[bb & dmask]
                        l = e & 63
                        if l > bc:
                            if tail and (l != 63 or bc < dbits):
                                status = 'ok'
                                break
                            raise _ZError(-3, 'invalid distance code')
                        sym = e >> 6
                        if sym > 29:
                            raise _ZError(-3, 'invalid distance code')
                        bb >>= l
                        bc -= l
                        eb = dextra[sym]
                        if tail and bc < eb:
                            status = 'ok'
                            break
                        dist = dbase[sym] + (bb & ((1 << eb) - 1))
                        bb >>= eb
                        bc -= eb
                        if dist > n or dist > wsize:
                            raise _ZError(-3, 'invalid distance too far back')
                        bitbuf = bb
                        bitcnt = bc
                        room = limit - n
                        if ln > room:
                            mlen = ln - room
                            mdist = dist
                            ln = room
                        s = n - dist
                        if dist >= ln:
                            win += win[s:s + ln]
                        else:
                            win += (win[s:] * (ln // dist + 1))[:ln]
                        n += ln
                        if mlen:
                            status = 'limit'
                            break
                    if status is not None:
                        break
                    continue
                if mode == _BLOCK:
                    if self.last:
                        mode = _TRAILER
                        continue
                    try:
                        last, typ, info, p2, bb, bc = self._block_header(
                            data, pos, bitbuf, bitcnt)
                    except _Need:
                        status = 'ok'
                        break
                    self.last = bool(last)
                    pos = p2
                    bitbuf = bb
                    bitcnt = bc
                    if typ == 0:
                        self.stored_left = info
                        mode = _STORED
                    else:
                        self.ltab, self.lbits, self.dtab, self.dbits = info
                        mode = _CODES
                    continue
                if mode == _STORED:
                    left = self.stored_left
                    avail = dlen - pos
                    room = limit - len(win)
                    take = min(left, avail, room)
                    if take:
                        win += data[pos:pos + take]
                        pos += take
                        left -= take
                        self.stored_left = left
                    if left == 0:
                        mode = _BLOCK
                        continue
                    status = 'ok' if pos >= dlen else 'limit'
                    break
                if mode == _HEAD:
                    try:
                        pos = self._head(data, pos)
                    except _Need:
                        status = 'ok'
                        break
                    mode = self.mode
                    wsize = self.wsize
                    continue
                if mode == _DICT:
                    status = 'dict'
                    break
                if mode == _TRAILER:
                    pos -= bitcnt >> 3
                    bitbuf = 0
                    bitcnt = 0
                    need = 0
                    if self.wrap:
                        need = 8 if self.gz else 4
                    if self.gz and dlen - pos >= 4:
                        # libz checks the CRC as soon as its 4 bytes are in
                        self._upd(win, checked)
                        checked = len(win)
                        if frombytes(data[pos:pos + 4], 'little') != self.check:
                            raise _ZError(-3, 'incorrect data check')
                    if dlen - pos < need:
                        status = 'ok'
                        break
                    if need:
                        self._upd(win, checked)
                        checked = len(win)
                        if self.gz:
                            crc = frombytes(data[pos:pos + 4], 'little')
                            isize = frombytes(data[pos + 4:pos + 8], 'little')
                            if crc != self.check:
                                raise _ZError(-3, 'incorrect data check')
                            if isize != self.total & 0xffffffff:
                                raise _ZError(-3, 'incorrect length check')
                        elif frombytes(data[pos:pos + 4], 'big') != self.check:
                            raise _ZError(-3, 'incorrect data check')
                        pos += need
                    mode = _DONE
                    status = 'end'
                    break
        except _ZError as e:
            self.mode = _BAD
            self.errmsg = e.msg
            raise
        r = bitcnt & 7
        pos -= bitcnt >> 3
        bitbuf &= (1 << r) - 1
        bitcnt = r
        self._upd(win, checked)
        out = bytes(win[base:])
        if len(win) > 98304:
            del win[:len(win) - 32768]
        self.mode = mode
        self.bitbuf = bitbuf
        self.bitcnt = bitcnt
        self.mlen = mlen
        self.mdist = mdist
        left = data[pos:]
        if status == 'ok':
            self.pend = left
            left = b''
        return out, status, left


# --- deflate ------------------------------------------------------------

_SEG = 1 << 18

_LSYM = [0] * 259       # length -> literal/length symbol
_LEXTV = [0] * 259      # length -> extra bits value
_LEXTB = [0] * 259      # length -> number of extra bits
_idx = 0
for _ln in range(3, 258):
    while _idx < 27 and _LBASE[_idx + 1] <= _ln:
        _idx += 1
    _LSYM[_ln] = 257 + _idx
    _LEXTV[_ln] = _ln - _LBASE[_idx]
    _LEXTB[_ln] = _LEXT[_idx]
_LSYM[258] = 285
_DC1 = [0] * 256        # distance 1..256 -> distance symbol
_DC2 = [0] * 256        # (distance - 1) >> 7 -> distance symbol
_idx = 0
for _d in range(1, 257):
    while _idx < 29 and _DBASE[_idx + 1] <= _d:
        _idx += 1
    _DC1[_d - 1] = _idx
_idx = 0
for _k in range(256):
    while _idx < 29 and _DBASE[_idx + 1] <= 128 * _k + 1:
        _idx += 1
    _DC2[_k] = _idx
del _idx, _ln, _d, _k

_FIXED_LCODE = _codes(_FIXED_LIT_LENS)
_FIXED_DCODE = _codes([5] * 30)
_FIXED_DLEN = [5] * 30

# per level: (max chain, nice length, lazy matching, only from level 7); chains are much shorter
# than libz's because every candidate costs interpreted bytecode
_CONFIG = (None, (2, 8, False), (3, 16, False), (4, 32, False),
           (4, 16, False), (6, 32, False), (8, 64, False), (16, 128, True),
           (32, 258, True), (64, 258, True))


def _huff_lens(freq, limit):
    """Length-limited Huffman code lengths for ``freq`` (a complete code)."""
    n = len(freq)
    lens = [0] * n
    syms = [s for s in range(n) if freq[s]]
    if len(syms) < 2:
        a = syms[0] if syms else 0
        lens[a] = 1
        lens[1 if a == 0 else 0] = 1
        return lens
    syms.sort(key=lambda s: (freq[s], s))
    m = len(syms)
    w = [freq[s] for s in syms]
    iw = []
    lc = []
    rc = []
    a = 0
    b = 0
    for _ in range(m - 1):
        if a < m and (b >= len(iw) or w[a] <= iw[b]):
            x = a
            xw = w[a]
            a += 1
        else:
            x = m + b
            xw = iw[b]
            b += 1
        if a < m and (b >= len(iw) or w[a] <= iw[b]):
            y = a
            yw = w[a]
            a += 1
        else:
            y = m + b
            yw = iw[b]
            b += 1
        iw.append(xw + yw)
        lc.append(x)
        rc.append(y)
    depth = [0] * (2 * m - 1)
    for j in range(m - 2, -1, -1):
        dd = depth[m + j] + 1
        depth[lc[j]] = dd
        depth[rc[j]] = dd
    maxd = max(depth[:m])
    if maxd <= limit:
        for i in range(m):
            lens[syms[i]] = depth[i]
        return lens
    bl = [0] * (limit + 1)
    units = 0
    for i in range(m):
        l = min(depth[i], limit)
        bl[l] += 1
        units += 1 << (limit - l)
    excess = units - (1 << limit)
    while excess > 0:
        bits = limit - 1
        while bl[bits] == 0:
            bits -= 1
        bl[bits] -= 1
        bl[bits + 1] += 2
        bl[limit] -= 1
        excess -= 1
    i = 0
    for l in range(limit, 0, -1):
        for _ in range(bl[l]):
            lens[syms[i]] = l
            i += 1
    return lens


def _rle(seq):
    """Run-length code the code lengths: ``(symbol, extra value, extra bits)``."""
    out = []
    i = 0
    n = len(seq)
    while i < n:
        v = seq[i]
        j = i + 1
        while j < n and seq[j] == v:
            j += 1
        run = j - i
        if v == 0:
            while run >= 11:
                k = min(run, 138)
                out.append((18, k - 11, 7))
                run -= k
            if run >= 3:
                out.append((17, run - 3, 3))
                run = 0
            out.extend([(0, 0, 0)] * run)
        else:
            out.append((v, 0, 0))
            run -= 1
            while run >= 3:
                k = min(run, 6)
                out.append((16, k - 3, 2))
                run -= k
            out.extend([(v, 0, 0)] * run)
        i = j
    return out


class _Deflate:
    """Streaming deflate with a zlib, gzip or raw wrapper."""

    def __init__(self, level, wrap, wbits, memlevel, strategy):
        self.level = 6 if level == -1 else level
        self.wrap = wrap            # 0 raw, 1 zlib, 2 gzip
        self.wbits = wbits
        self.strategy = strategy
        self.maxdist = (1 << wbits) - 262
        self.tokmax = (1 << (memlevel + 6)) - 1
        self.cfg = _CONFIG[self.level] if self.level else None
        self.pending = bytearray()
        self.hist = b''
        self.acc = 0
        self.nb = 0
        self.started = False
        self.finished = False
        self.check = 1 if wrap == 1 else 0
        self.total = 0
        self.dictid = None

    def clone(self):
        new = object.__new__(_Deflate)
        new.__dict__.update(self.__dict__)
        new.pending = bytearray(self.pending)
        return new

    def set_dict(self, zdict):
        if self.wrap == 2 or self.started:
            raise _ZError(-2)
        if self.wrap == 1:
            self.dictid = _adler32_raw(zdict, 1)
        if self.level:
            self.hist = zdict[-self.maxdist:] if zdict else b''
        if self.wrap == 1 and not zdict:
            self.dictid = None

    # -- bit output ------------------------------------------------------

    def _flush_bits(self, out):
        n = self.nb >> 3
        if n:
            out += (self.acc & ((1 << (n << 3)) - 1)).to_bytes(n, 'little')
            self.acc >>= n << 3
            self.nb &= 7

    def _align(self, out):
        n = (self.nb + 7) >> 3
        if n:
            out += self.acc.to_bytes(n, 'little')
        self.acc = 0
        self.nb = 0

    def _start(self, out):
        if self.started:
            return
        self.started = True
        level = self.level
        if self.wrap == 1:
            cmf = 8 | ((self.wbits - 8) << 4)
            if self.strategy >= 2 or level < 2:
                lf = 0
            elif level < 6:
                lf = 1
            elif level == 6:
                lf = 2
            else:
                lf = 3
            hdr = (cmf << 8) | (lf << 6)
            if self.dictid is not None:
                hdr |= 0x20
            hdr += 31 - hdr % 31
            out += hdr.to_bytes(2, 'big')
            if self.dictid is not None:
                out += self.dictid.to_bytes(4, 'big')
        elif self.wrap == 2:
            xfl = 2 if level == 9 else (4 if self.strategy >= 2 or level < 2
                                        else 0)
            out += b'\x1f\x8b\x08\x00\x00\x00\x00\x00' + bytes((xfl, 3))

    # -- blocks ----------------------------------------------------------

    def _stored(self, buf, s, e, final, out):
        if s == e and not final:
            return
        first = True
        while first or s < e:
            first = False
            n = min(e - s, 65535)
            last = final and s + n >= e
            self.acc |= (1 if last else 0) << self.nb
            self.nb += 3
            self._align(out)
            out += n.to_bytes(2, 'little') + (n ^ 0xffff).to_bytes(2, 'little')
            out += buf[s:s + n]
            s += n

    def _block(self, tokens, buf, bs, be, final, out):
        lf = [0] * 286
        df = [0] * 30
        lsym = _LSYM
        dc1 = _DC1
        dc2 = _DC2
        for t in tokens:
            if t < 256:
                lf[t] += 1
            else:
                lf[lsym[t & 511]] += 1
                d = t >> 9
                df[dc1[d - 1] if d <= 256 else dc2[(d - 1) >> 7]] += 1
        lf[256] = 1
        xbits = 0
        for k in range(29):
            xbits += lf[257 + k] * _LEXT[k]
        for k in range(30):
            xbits += df[k] * _DEXT[k]
        fixed = 3 + xbits + 5 * sum(df)
        for s in range(286):
            if lf[s]:
                fixed += lf[s] * _FIXED_LIT_LENS[s]
        if self.strategy == Z_FIXED:
            use = 1
        else:
            ll = _huff_lens(lf, 15)
            dl = _huff_lens(df, 15)
            nl = 286
            while nl > 257 and ll[nl - 1] == 0:
                nl -= 1
            nd = 30
            while nd > 1 and dl[nd - 1] == 0:
                nd -= 1
            rle = _rle(ll[:nl] + dl[:nd])
            cf = [0] * 19
            for sym, _xv, _xb in rle:
                cf[sym] += 1
            cl = _huff_lens(cf, 7)
            nc = 19
            while nc > 4 and cl[_ORDER[nc - 1]] == 0:
                nc -= 1
            dyn = 3 + 14 + 3 * nc + xbits
            for sym, _xv, xb in rle:
                dyn += cl[sym] + xb
            for s in range(286):
                if lf[s]:
                    dyn += lf[s] * ll[s]
            for s in range(30):
                if df[s]:
                    dyn += df[s] * dl[s]
            use = 2 if dyn < fixed else 1
        size = be - bs
        stored = 8 * size + 42 * (size // 65535 + 1)
        best = fixed if use == 1 else dyn
        if self.strategy != Z_FIXED and stored < best:
            self._stored(buf, bs, be, final, out)
            return
        acc = self.acc
        nb = self.nb
        fin = 1 if final else 0
        if use == 1:
            acc |= (fin | 2) << nb
            nb += 3
            lcode = _FIXED_LCODE
            llen = _FIXED_LIT_LENS
            dcode = _FIXED_DCODE
            dlen = _FIXED_DLEN
        else:
            acc |= (fin | 4) << nb
            nb += 3
            acc |= ((nl - 257) | ((nd - 1) << 5) | ((nc - 4) << 10)) << nb
            nb += 14
            for i in range(nc):
                acc |= cl[_ORDER[i]] << nb
                nb += 3
            ccode = _codes(cl)
            for sym, xv, xb in rle:
                acc |= ccode[sym] << nb
                nb += cl[sym]
                if xb:
                    acc |= xv << nb
                    nb += xb
                if nb >= 48:
                    k = nb >> 3
                    out += (acc & ((1 << (k << 3)) - 1)).to_bytes(k, 'little')
                    acc >>= k << 3
                    nb &= 7
            lcode = _codes(ll)
            llen = ll
            dcode = _codes(dl)
            dlen = dl
        lextv = _LEXTV
        lextb = _LEXTB
        dbase = _DBASE
        dext = _DEXT
        for t in tokens:
            if t < 256:
                acc |= lcode[t] << nb
                nb += llen[t]
            else:
                ln = t & 511
                d = t >> 9
                s = lsym[ln]
                acc |= lcode[s] << nb
                nb += llen[s]
                eb = lextb[ln]
                if eb:
                    acc |= lextv[ln] << nb
                    nb += eb
                s = dc1[d - 1] if d <= 256 else dc2[(d - 1) >> 7]
                acc |= dcode[s] << nb
                nb += dlen[s]
                eb = dext[s]
                if eb:
                    acc |= (d - dbase[s]) << nb
                    nb += eb
            if nb >= 48:
                k = nb >> 3
                out += (acc & ((1 << (k << 3)) - 1)).to_bytes(k, 'little')
                acc >>= k << 3
                nb &= 7
        acc |= lcode[256] << nb
        nb += llen[256]
        self.acc = acc
        self.nb = nb
        self._flush_bits(out)

    def _run(self, data, final, out):
        """Compress ``data`` (the next input) into blocks appended to ``out``."""
        if not self.level:
            self._stored(data, 0, len(data), final, out)
            return
        hist = self.hist
        hl = len(hist)
        buf = hist + data
        end = len(buf)
        strat = self.strategy
        chain, nice, lazy = self.cfg
        maxdist = self.maxdist
        tokmax = self.tokmax
        head = {}
        if strat != Z_HUFFMAN_ONLY and strat != Z_RLE:
            for j in range(min(hl, end - 2)):
                key = buf[j:j + 3]
                lst = head.get(key)
                if lst is None:
                    head[key] = [j]
                else:
                    lst.append(j)
        cap = 2 * chain + 8
        tokens = []
        append = tokens.append
        bs = i = hl
        pl = 0          # pending (lazy) match: length and distance
        pd = 0
        while i < end:
            ln = 0
            dist = 0
            if i + 2 < end and strat != Z_HUFFMAN_ONLY:
                maxlen = end - i
                if maxlen > 258:
                    maxlen = 258
                if strat == Z_RLE:
                    if i and buf[i] == buf[i - 1]:
                        k = 1
                        while k < maxlen and buf[i + k] == buf[i - 1 + k]:
                            k += 1
                        if k >= 3:
                            ln = k
                            dist = 1
                else:
                    key = buf[i:i + 3]
                    lst = head.get(key)
                    if lst is None:
                        head[key] = [i]
                    else:
                        if not (pl >= nice):
                            tries = 0
                            for c in range(len(lst) - 1, -1, -1):
                                j = lst[c]
                                d = i - j
                                if d > maxdist:
                                    break
                                if ln and buf[j + ln] != buf[i + ln]:
                                    tries += 1
                                    if tries >= chain:
                                        break
                                    continue
                                k = 3
                                step = 8
                                while k < maxlen:
                                    e2 = k + step
                                    if e2 > maxlen:
                                        e2 = maxlen
                                    if buf[j + k:j + e2] == buf[i + k:i + e2]:
                                        k = e2
                                        step <<= 1
                                    else:
                                        while buf[j + k] == buf[i + k]:
                                            k += 1
                                        break
                                if k > ln:
                                    ln = k
                                    dist = d
                                    if k >= nice or k >= maxlen:
                                        break
                                tries += 1
                                if tries >= chain:
                                    break
                        lst.append(i)
                        if len(lst) > cap:
                            del lst[:cap >> 1]
            if lazy:
                if pl and ln <= pl:
                    # emit the match found at i - 1
                    append((pd << 9) | pl)
                    stop = i - 1 + pl
                    if strat != Z_HUFFMAN_ONLY and strat != Z_RLE:
                        for j in range(i + 1, min(stop, end - 2)):
                            key = buf[j:j + 3]
                            lst = head.get(key)
                            if lst is None:
                                head[key] = [j]
                            else:
                                lst.append(j)
                    i = stop
                    pl = 0
                elif ln >= 3:
                    if pl:
                        append(buf[i - 1])
                    pl = ln
                    pd = dist
                    i += 1
                else:
                    if pl:
                        append(buf[i - 1])
                        pl = 0
                    append(buf[i])
                    i += 1
            elif ln >= 3:
                append((dist << 9) | ln)
                if chain > 4 or ln < 16:
                    for j in range(i + 1, min(i + ln, end - 2)):
                        key = buf[j:j + 3]
                        lst = head.get(key)
                        if lst is None:
                            head[key] = [j]
                        else:
                            lst.append(j)
                i += ln
            else:
                append(buf[i])
                i += 1
            if len(tokens) >= tokmax:
                if pl:
                    # flush the deferred match first so the block ends at i
                    pass
                else:
                    self._block(tokens, buf, bs, i, False, out)
                    del tokens[:]
                    bs = i
        if pl:
            append((pd << 9) | pl)
            i = i - 1 + pl
        if tokens or final:
            self._block(tokens, buf, bs, end, final, out)
        self.hist = buf[-maxdist:] if end > maxdist else buf

    # -- public ----------------------------------------------------------

    def feed(self, data):
        out = bytearray()
        self._start(out)
        if self.wrap == 1:
            self.check = _adler32_raw(data, self.check)
        elif self.wrap == 2:
            self.check = _crc32_raw(data, self.check)
        self.total += len(data)
        pend = self.pending
        pend += data
        while len(pend) >= _SEG:
            chunk = bytes(pend[:_SEG])
            del pend[:_SEG]
            self._run(chunk, False, out)
        return bytes(out)

    def flush(self, mode):
        out = bytearray()
        self._start(out)
        final = mode == Z_FINISH
        pend = self.pending
        while len(pend) > _SEG:
            chunk = bytes(pend[:_SEG])
            del pend[:_SEG]
            self._run(chunk, False, out)
        if pend or final:
            chunk = bytes(pend)
            del pend[:]
            self._run(chunk, final, out)
        if final:
            self._align(out)
            if self.wrap == 1:
                out += self.check.to_bytes(4, 'big')
            elif self.wrap == 2:
                out += self.check.to_bytes(4, 'little')
                out += (self.total & 0xffffffff).to_bytes(4, 'little')
            self.finished = True
        elif mode == Z_PARTIAL_FLUSH:
            self.acc |= 2 << self.nb
            self.nb += 10
            self._flush_bits(out)
        elif mode == Z_SYNC_FLUSH or mode == Z_FULL_FLUSH:
            self.nb += 3
            self._align(out)
            out += b'\x00\x00\xff\xff'
            if mode == Z_FULL_FLUSH:
                self.hist = b''
        return bytes(out)


def _deflate_params(level, method, wbits, memlevel, strategy):
    """deflateInit2() parameter check: ``(level, wrap, wbits)`` or None."""
    if level == -1:
        level = 6
    wrap = 1
    if wbits < 0:
        wrap = 0
        wbits = -wbits
    elif wbits > 15:
        wrap = 2
        wbits -= 16
    if (memlevel < 1 or memlevel > 9 or method != DEFLATED or wbits < 8
            or wbits > 15 or level < 0 or level > 9 or strategy < 0
            or strategy > Z_FIXED or (wbits == 8 and wrap != 1)):
        return None
    if wbits == 8:
        wbits = 9
    return level, wrap, wbits


# --- module functions ---------------------------------------------------

def compress(data=_NULL, /, level=Z_DEFAULT_COMPRESSION, wbits=MAX_WBITS):
    """Returns a bytes object containing compressed data.

    data
      Binary data to be compressed.
    level
      Compression level, in 0-9 or -1.
    wbits
      The window buffer size and container format.
    """
    if data is _NULL:
        raise TypeError("compress() takes at least 1 positional argument (0 given)")
    data = _buf(data)
    level = _cint(level)
    wbits = _cint(wbits)
    params = _deflate_params(level, DEFLATED, wbits, DEF_MEM_LEVEL,
                             Z_DEFAULT_STRATEGY)
    if params is None:
        raise error("Bad compression level")
    level, wrap, wb = params
    d = _Deflate(level, wrap, wb, DEF_MEM_LEVEL, Z_DEFAULT_STRATEGY)
    return d.feed(data) + d.flush(Z_FINISH)


def decompress(data=_NULL, /, wbits=MAX_WBITS, bufsize=DEF_BUF_SIZE):
    """Returns a bytes object containing the uncompressed data.

    data
      Compressed data.
    wbits
      The window buffer size and container format.
    bufsize
      The initial output buffer size.
    """
    if data is _NULL:
        raise TypeError("decompress() takes at least 1 positional argument (0 given)")
    data = _buf(data)
    wbits = _cint(wbits)
    bufsize = _ssize(bufsize)
    if bufsize < 0:
        raise ValueError("bufsize cannot be negative")
    try:
        inf = _Inflate(wbits)
    except _ZError as e:
        raise _zerr(e.code, e.msg, "while preparing to decompress data") \
            from None
    try:
        out, status, _left = inf.run(data, None)
    except _ZError as e:
        raise _zerr(e.code, e.msg, "while decompressing data") from None
    if status == 'dict':
        raise _zerr(2, None, "while decompressing data")
    if status != 'end':
        raise _zerr(-5, None, "while decompressing data")
    return out


class _Compress:
    """Compression object (returned by ``compressobj``)."""

    def __new__(cls, *args, **kwargs):
        raise TypeError("cannot create 'zlib.Compress' instances")

    def compress(self, data, /):
        """Returns a bytes object containing compressed data.

        data
          Binary data to be compressed.

        After calling this function, some of the input data may still
        be stored in internal buffers for later processing.
        Call the flush() method to clear these buffers.
        """
        data = _buf(data)
        if self._d.finished:
            raise _zerr(-2, None, "while compressing data")
        return self._d.feed(data)

    def flush(self, mode=Z_FINISH, /):
        """Return a bytes object containing any remaining compressed data.

        mode
          One of the constants Z_SYNC_FLUSH, Z_FULL_FLUSH, Z_FINISH.
          If mode == Z_FINISH, the compressor object can no longer be
          used after calling the flush() method.  Otherwise, more data
          can still be compressed.
        """
        mode = _cint(mode)
        if mode == Z_NO_FLUSH:
            return b''
        if self._d.finished or mode < 0 or mode > Z_BLOCK:
            raise _zerr(-2, None, "while flushing")
        return self._d.flush(mode)

    def copy(self):
        """Return a copy of the compression object."""
        if self._d.finished:
            raise ValueError("Inconsistent stream state")
        new = object.__new__(_Compress)
        new._d = self._d.clone()
        return new

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo, /):
        return self.copy()

    def __reduce_ex__(self, protocol):
        raise TypeError("cannot pickle 'zlib.Compress' object")


class _Decompress:
    """Decompression object (returned by ``decompressobj``)."""

    def __new__(cls, *args, **kwargs):
        raise TypeError("cannot create 'zlib.Decompress' instances")

    @property
    def unused_data(self):
        return self._unused_data

    @property
    def unconsumed_tail(self):
        return self._unconsumed_tail

    @property
    def eof(self):
        return self._eof

    def decompress(self, data, /, max_length=0):
        """Return a bytes object containing the decompressed version of the data.

        data
          The binary data to decompress.
        max_length
          The maximum allowable length of the decompressed data.
          Unconsumed input data will be stored in
          the unconsumed_tail attribute.

        After calling this function, some of the input data may still be
        stored in internal buffers for later processing.
        Call the flush() method to clear these buffers.
        """
        data = _buf(data)
        max_length = _ssize(max_length)
        if max_length < 0:
            raise ValueError("max_length cannot be negative")
        if not self._init:
            raise _zerr(-2, None, "while decompressing data")
        limit = None if max_length == 0 else max_length
        while True:
            try:
                out, status, left = self._inf.run(data, limit)
            except _ZError as e:
                raise _zerr(e.code, e.msg, "while decompressing data") \
                    from None
            if status == 'dict' and self._zdict is not None:
                self._set_dict()
                data = left
                continue
            break
        if status == 'dict':
            raise _zerr(2, None, "while decompressing data")
        if status == 'end':
            self._eof = True
            if left:
                self._unused_data += left
            self._unconsumed_tail = b''
        elif status == 'limit':
            self._unconsumed_tail = left
        else:
            self._unconsumed_tail = b''
        return out

    def _set_dict(self):
        try:
            self._inf.set_dict(_buf(self._zdict))
        except _ZError as e:
            raise _zerr(e.code, e.msg, "while setting zdict") from None

    def flush(self, length=DEF_BUF_SIZE, /):
        """Return a bytes object containing any remaining decompressed data.

        length
          the initial size of the output buffer.
        """
        length = _ssize(length)
        if length <= 0:
            raise ValueError("length must be greater than zero")
        if not self._init:
            return b''
        try:
            out, status, left = self._inf.run(self._unconsumed_tail, None)
        except _ZError as e:
            raise _zerr(e.code, e.msg, "while decompressing data") from None
        if status == 'dict':
            raise _zerr(2, None, "while decompressing data")
        if status == 'end':
            self._eof = True
            self._init = False
            if left:
                self._unused_data += left
        self._unconsumed_tail = b''
        return out

    def copy(self):
        """Return a copy of the decompression object."""
        if not self._init:
            raise ValueError("Inconsistent stream state")
        new = object.__new__(_Decompress)
        new.__dict__.update(self.__dict__)
        new._inf = self._inf.clone()
        return new

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo, /):
        return self.copy()

    def __reduce_ex__(self, protocol):
        raise TypeError("cannot pickle 'zlib.Decompress' object")


_Compress.__module__ = _Decompress.__module__ = 'zlib'
_Compress.__name__ = _Compress.__qualname__ = 'Compress'
_Decompress.__name__ = _Decompress.__qualname__ = 'Decompress'


def compressobj(level=Z_DEFAULT_COMPRESSION, method=DEFLATED, wbits=MAX_WBITS,
                memLevel=DEF_MEM_LEVEL, strategy=Z_DEFAULT_STRATEGY,
                zdict=None):
    """Return a compressor object.

    level
      The compression level (an integer in the range 0-9 or -1; default is
      currently equivalent to 6).  Higher compression levels are slower,
      but produce smaller results.
    method
      The compression algorithm.  If given, this must be DEFLATED.
    wbits
      +9 to +15: The base-two logarithm of the window size.  Include a zlib
          container.
      -9 to -15: Generate a raw stream.
      +25 to +31: Include a gzip container.
    memLevel
      Controls the amount of memory used for internal compression state.
      Valid values range from 1 to 9.  Higher values result in higher memory
      usage, faster compression, and smaller output.
    strategy
      Used to tune the compression algorithm.  Possible values are
      Z_DEFAULT_STRATEGY, Z_FILTERED, and Z_HUFFMAN_ONLY.
    zdict
      The predefined compression dictionary - a sequence of bytes
      containing subsequences that are likely to occur in the input data.
    """
    level = _cint(level)
    method = _cint(method)
    wbits = _cint(wbits)
    memLevel = _cint(memLevel)
    strategy = _cint(strategy)
    if zdict is not None:
        zdict = _buf(zdict)
    params = _deflate_params(level, method, wbits, memLevel, strategy)
    if params is None:
        raise ValueError("Invalid initialization option")
    level, wrap, wb = params
    self = object.__new__(_Compress)
    self._d = _Deflate(level, wrap, wb, memLevel, strategy)
    if zdict is not None:
        try:
            self._d.set_dict(zdict)
        except _ZError:
            raise ValueError("Invalid dictionary") from None
    return self


def decompressobj(wbits=MAX_WBITS, zdict=_NULL):
    """Return a decompressor object.

    wbits
      The window buffer size and container format.
    zdict
      The predefined compression dictionary.  This must be the same
      dictionary as used by the compressor that produced the input data.
    """
    wbits = _cint(wbits)
    if zdict is not _NULL:
        try:
            memoryview(zdict)
        except TypeError:
            raise TypeError("zdict argument must support the buffer protocol") \
                from None
    else:
        zdict = None
    self = object.__new__(_Decompress)
    self._zdict = zdict
    self._unused_data = b''
    self._unconsumed_tail = b''
    self._eof = False
    self._init = True
    try:
        self._inf = _Inflate(wbits)
    except _ZError:
        raise ValueError("Invalid initialization option") from None
    if zdict is not None and wbits < 0:
        self._set_dict()
    return self


class _ZlibDecompressor:
    """Create a decompressor object for decompressing data incrementally.

      wbits
        The window buffer size and container format.
      zdict
        The predefined compression dictionary. This is a sequence of bytes
        (such as a bytes object) containing subsequences that are expected
        to occur frequently in the data that is to be compressed. Those
        subsequences that are expected to be most common should come at the
        end of the dictionary. This must be the same dictionary as used by the
        compressor that produced the input data.
    """

    def __init__(self, wbits=MAX_WBITS, zdict=_NULL):
        wbits = _cint(wbits)
        self._zdict = None if zdict is _NULL else zdict
        self._unused_data = b''
        self._input = b''
        self._eof = False
        self._needs_input = True
        try:
            self._inf = _Inflate(wbits)
        except _ZError:
            raise ValueError("Invalid initialization option") from None
        if self._zdict is not None and wbits < 0:
            self._set_dict()

    def _set_dict(self):
        try:
            self._inf.set_dict(_buf(self._zdict))
        except _ZError as e:
            raise _zerr(e.code, e.msg, "while setting zdict") from None

    @property
    def unused_data(self):
        """Data found after the end of the compressed stream."""
        return self._unused_data

    @property
    def eof(self):
        """True if the end-of-stream marker has been reached."""
        return self._eof

    @property
    def needs_input(self):
        """True if more input is needed before more decompressed data can be produced."""
        return self._needs_input

    def decompress(self, data, max_length=-1):
        """Decompress *data*, returning uncompressed data as bytes.

        If *max_length* is nonnegative, returns at most *max_length* bytes
        of decompressed data.  If this limit is reached and further output
        can be produced, *self.needs_input* will be set to ``False``.  In
        this case, the next call to *decompress()* may provide *data* as b''
        to obtain more of the output.

        If all of the input data was decompressed and returned (either
        because this was less than *max_length* bytes, or because
        *max_length* was negative), *self.needs_input* will be set to True.

        Attempting to decompress data after the end of stream is reached
        raises an EOFError.  Any data found after the end of the stream is
        ignored and saved in the unused_data attribute.
        """
        data = _buf(data)
        max_length = _ssize(max_length)
        if self._eof:
            raise EOFError("End of stream already reached")
        data = self._input + data if self._input else data
        limit = None if max_length < 0 or max_length == _MAXSIZE \
            else max_length
        while True:
            try:
                out, status, left = self._inf.run(data, limit)
            except _ZError as e:
                self._input = b''
                raise _zerr(e.code, e.msg, "while decompressing data") \
                    from None
            if status == 'dict' and self._zdict is not None:
                self._set_dict()
                data = left
                continue
            break
        if status == 'dict':
            self._input = b''
            raise _zerr(2, None, "while decompressing data")
        if status == 'end':
            self._eof = True
            self._needs_input = False
            self._input = b''
            if left:
                self._unused_data = left
        elif status == 'limit':
            self._input = left
            self._needs_input = not left
        else:
            self._input = b''
            self._needs_input = True
        return out

    def __reduce_ex__(self, protocol):
        raise TypeError("cannot pickle 'zlib._ZlibDecompressor' object")


_ZlibDecompressor.__module__ = 'zlib'
_ZlibDecompressor.__name__ = _ZlibDecompressor.__qualname__ = '_ZlibDecompressor'


def __getattr__(name):
    if name == '__version__':
        import warnings
        warnings.warn("'__version__' is deprecated and slated for removal in "
                      "Python 3.20", DeprecationWarning, stacklevel=2)
        return '1.0'
    raise AttributeError(f"module 'zlib' has no attribute {name!r}")


def __dir__():
    # Hide the private helpers: dir(zlib) lists what the C module has.
    return sorted(n for n in globals()
                  if not n.startswith('_') or n == '_ZlibDecompressor'
                  or (n.startswith('__') and n not in ('__builtins__', '__dir__')))
