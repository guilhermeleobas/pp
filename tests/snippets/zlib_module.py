import zlib

def t(f, *a, **k):
    try:
        print(f(*a, **k))
    except Exception as e:
        print(type(e).__name__, e)

text = b"The quick brown fox jumps over the lazy dog. " * 50 + bytes(range(256))
print(zlib.crc32(b"penguin"), zlib.adler32(b"penguin"), zlib.crc32(text), zlib.adler32(text))
print(zlib.crc32_combine(zlib.crc32(b"ab"), zlib.crc32(b"cd"), 2) == zlib.crc32(b"abcd"))
print(zlib.adler32_combine(zlib.adler32(b"ab"), zlib.adler32(b"cd"), 2) == zlib.adler32(b"abcd"))
for level in (0, 1, 6, 9, -1):
    for wbits in (15, -15, 31, 9):
        c = zlib.compress(text, level, wbits)
        assert zlib.decompress(c, wbits) == text, (level, wbits)
print(zlib.decompress(zlib.compress(text), 47) == text)

# fixed data produced by libz, so the inflater is checked independently
print(zlib.decompress(b'x\x9cK\xcb\xcf\x07\x00\x02\x82\x01E'))
t(zlib.decompress, b'x\x9cK\xcb\xcf\x07\x00\x02\x82\x01E'[:-1])
t(zlib.decompress, b'not zlib data')
t(zlib.decompress, b'x\x9cK\xcb\xcf\x07\x00\x02\x82\x01F')
t(zlib.decompress, b'x\x9cK\xcb\xcf\x07\x00\x02\x82\x01E', 14)
t(zlib.compress, b'x', 10)
t(zlib.decompress, b'', 15, -1)

# streaming
c = zlib.compressobj(6, zlib.DEFLATED, -15)
raw = c.compress(text[:300]) + c.flush(zlib.Z_SYNC_FLUSH) + c.compress(text[300:]) + c.flush()
d = zlib.decompressobj(-15)
out = b""
data = raw + b"tail"
while data:
    out += d.decompress(data[:7], 100)
    data = d.unconsumed_tail + data[7:]
    if d.eof:
        break
print(out == text, d.eof, d.unused_data[-4:] or data[-4:])
t(c.flush)
t(c.compress, b"x")
t(zlib.decompressobj().decompress, b"", -1)
t(zlib.decompressobj, -1)
t(zlib.compressobj, 1, zlib.DEFLATED, 0)

# dictionary
zd = b"quick brown fox lazy dog"
co = zlib.compressobj(zdict=zd)
cd = co.compress(text) + co.flush()
print(zlib.decompressobj(zdict=zd).decompress(cd) == text)
t(zlib.decompress, cd)
t(zlib.decompressobj().decompress, cd)

# _ZlibDecompressor (used by gzip)
zd = zlib._ZlibDecompressor()
out = b""
comp = zlib.compress(text)
for i in range(0, len(comp), 10):
    out += zd.decompress(comp[i:i + 10])
print(out == text, zd.eof, zd.needs_input)
t(zd.decompress, b"more")

# a bad gzip CRC is reported as soon as its 4 bytes arrive
good = zlib.compress(b"hello gzip", 6, 31)
bad = good[:-8] + good[-7:]
t(zlib.decompress, bad, 31)
t(zlib.decompressobj(31).decompress, bad)
t(zlib.decompressobj(31).decompress, good[:-4])

# compressed bytes differ from libz: keep them out of the compared globals
del c, cd, comp, raw, co, good, bad
