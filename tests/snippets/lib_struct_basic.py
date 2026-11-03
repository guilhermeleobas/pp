import struct

def t(f, *a, **k):
    try:
        print(f(*a, **k))
    except Exception as e:
        print(type(e).__name__, e)

# native vs standard size and alignment
for fmt in ("@bhiqx", "=bhiq", "@bq", "=bq", "<hl", "@hl", "@lL", "<lL", "@nNP", "@ci?", "=ci?", "@e", "@d",
            "!f", ">F", "<D", "@Zf", "<Zd", "3s2p", "x", "", "5x", "@3h0q", " < h h "):
    t(struct.calcsize, fmt)

# round trips
vals = [("<bBhHiIlLqQ", (-5, 200, -300, 60000, -70000, 4000000000, -1, 2**31, -2**63, 2**64 - 1)),
        (">hl?", (-2, 7, True)),
        ("=3s5pc", (b"abcdef", b"hi", b"z")),
        ("<f d e", (1.5, -2.25, 0.5)),
        ("<e", (65504.0,)), ("<e", (6e-8,)), ("<f", (1e-45,)), ("<f", (3.4028234663852886e38,)),
        ("<d", (5e-324,)), (">d", (float("inf"),)), ("<f", (-float("inf"),)), ("<e", (-0.0,)),
        ("<F D", (1 + 2j, -3.5 - 4j)),
        ("@nNP", (-3, 3, 12345)), ("@ci", (b"x", 9)), ("?", ("yes",)), ("?", ("",))]
for fmt, v in vals:
    p = struct.pack(fmt, *v)
    print(fmt, p.hex(), struct.unpack(fmt, p))

# half and single rounding
for x in (65519.9, 65520.0, 1e-8, 2.9802322387695312e-08, 6.103515625e-05, 1.0009765625, 1.00048828125):
    t(struct.pack, "<e", x)
for x in (3.4028235677973366e38, 3.5e38, 1e-46, 7e-46):
    t(struct.pack, "<f", x)
t(struct.pack, "<f", 10**39)
t(struct.pack, "<e", 10**400)

# Pascal strings, strings
print(struct.pack("4p", b"abcdefg"), struct.pack("0p", b"abc"), struct.pack("300p", b"x" * 300)[:3])
print(struct.unpack("4p", b"\x09abc"), struct.unpack("3s", b"abc"))
print(struct.pack("3s", bytearray(b"ab")))

# unpack_from, iter_unpack, pack_into
buf = bytearray(10)
struct.pack_into("<hh", buf, 2, 1, 2)
struct.pack_into("<h", buf, -2, 9)
print(buf, struct.unpack_from("<hh", buf, 2), struct.unpack_from("<h", buf, offset=-2))
print(list(struct.iter_unpack("<h", b"\x01\x00\x02\x00")))
it = struct.iter_unpack("<h", b"\x01\x00\x02\x00")
print(it.__length_hint__(), next(it), it.__length_hint__())
s = struct.Struct("<ih")
print(s.format, s.size, repr(s), s.unpack(s.pack(1, 2)))
print(struct.Struct(b"<i").format)
print(memoryview(s.pack(7, 8)).tobytes(), struct.unpack("<i", memoryview(b"\x01\x00\x00\x00")))
