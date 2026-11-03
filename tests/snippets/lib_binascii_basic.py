import binascii as b

def t(f, *a, **k):
    try:
        print(f(*a, **k))
    except Exception as e:
        print(type(e).__name__, e)

data = bytes(range(256)) * 2
for n in (0, 1, 2, 3, 4, 5, 6, 7, 8, 45, 100):
    d = data[:n]
    print(n, b.hexlify(d)[:20], b.b2a_base64(d), b.b2a_base64(d, newline=False, padded=False),
          b.b2a_base32(d), b.b2a_base32(d, padded=False), b.b2a_base85(d), b.b2a_base85(d, pad=True),
          b.b2a_ascii85(d), b.b2a_ascii85(d, adobe=True, pad=True, foldspaces=True))
    assert b.a2b_base64(b.b2a_base64(d)) == d
    assert b.a2b_base32(b.b2a_base32(d)) == d
    assert b.a2b_base85(b.b2a_base85(d)) == d
    assert b.a2b_ascii85(b.b2a_ascii85(d)) == d
    assert b.a2b_ascii85(b.b2a_ascii85(d, adobe=True), adobe=True) == d
    assert b.unhexlify(b.hexlify(d)) == d
    if n <= 45:
        assert b.a2b_uu(b.b2a_uu(d)) == d
        print(b.b2a_uu(d), b.b2a_uu(d, backtick=True))
    assert b.a2b_qp(b.b2a_qp(d)) == d
    print(b.b2a_qp(d)[:40], b.b2a_qp(d, quotetabs=True, istext=False, header=True)[:40])
print(b.b2a_base64(data[:100], wrapcol=20), b.b2a_base32(data[:20], wrapcol=10), b.b2a_ascii85(data[:30], wrapcol=7, adobe=True))
print(b.hexlify(b"\x01\x02\x03", ":"), b.hexlify(b"\x01\x02\x03", b"-", 2), b.b2a_hex(b"\x01\x02\x03", "-", -2))
print(b.a2b_hex("0a 0B", ignorechars=b" "), b.a2b_base64("YQ==\n"), b.a2b_base64(b"Y Q = =", ignorechars=b" "))
print(b.crc32(b"hello world"), b.crc32(b"world", b.crc32(b"hello ")), b.crc32(b"", -1), b.crc_hqx(b"hello", 0), b.crc_hqx(b"x", 0x12345))
print(b.a2b_qp(b"a=3Db=\nc=zz_d", header=True), b.b2a_qp(b"a=b \nc\t\r\nd.\n.\n", quotetabs=True))
print(b.BASE64_ALPHABET[:5], b.BASE32HEX_ALPHABET[-3:], len(b.Z85_ALPHABET), len(b.BINHEX_ALPHABET), b.UU_ALPHABET[:3])
print(b.b2a_base64(b"\xff\xfe", alphabet=b.URLSAFE_BASE64_ALPHABET), b.a2b_base64(b"__4=", alphabet=b.URLSAFE_BASE64_ALPHABET))
print(b.Error.__module__, issubclass(b.Error, ValueError), issubclass(b.Incomplete, Exception), b.Error.__mro__[1].__name__)
for f, a, k in ((b.a2b_base64, (b"abc",), {}), (b.a2b_base64, (b"a",), {}), (b.a2b_base64, (b"YQ=",), {}),
                (b.a2b_base64, (b"=YQ=",), {"strict_mode": True}), (b.a2b_base64, (b"YQ==Y",), {"strict_mode": True}),
                (b.a2b_base64, (b"Y!Q=",), {"strict_mode": True}), (b.a2b_base64, (b"YR==",), {"canonical": True}),
                (b.a2b_base64, (b"YQ==\xe9",), {}), (b.a2b_base64, ("\xe9",), {}), (b.a2b_base64, (5,), {}),
                (b.a2b_base64, (b"YQ==",), {"alphabet": b"abc"}), (b.a2b_base64, (b"YQ==",), {"alphabet": "x" * 64}),
                (b.b2a_base64, (b"x",), {"alphabet": b"abc"}), (b.b2a_base64, ("x",), {}),
                (b.b2a_base64, (b"x",), {"wrapcol": -1}), (b.b2a_base64, (b"x",), {"wrapcol": 2**64}),
                (b.a2b_hex, (b"abc",), {}), (b.a2b_hex, (b"zz",), {}), (b.hexlify, (b"ab", "ab"), {}), (b.hexlify, (b"ab", 5), {}),
                (b.hexlify, (b"ab", "\xe9"), {}), (b.a2b_uu, (b"",), {}), (b.a2b_uu, (b"#\x01",), {}), (b.a2b_uu, (b"!  xx",), {}),
                (b.b2a_uu, (b"x" * 46,), {}), (b.a2b_base32, (b"MZ",), {}), (b.a2b_base32, (b"M",), {}), (b.a2b_base32, (b"MZXQ====M",), {}),
                (b.a2b_base32, (b"=MZXQ",), {}), (b.a2b_base32, (b"MZ!",), {}), (b.a2b_base85, (b"abc!",), {}),
                (b.a2b_base85, (b"\x00",), {}), (b.a2b_base85, (b"~~~~~~",), {}), (b.a2b_base85, (b"a",), {}),
                (b.a2b_ascii85, (b"abc",), {"adobe": True}), (b.a2b_ascii85, (b"ab<z",), {}), (b.a2b_ascii85, (b"s8W-!",), {}),
                (b.a2b_ascii85, (b"s8W-\"",), {}), (b.a2b_ascii85, (b"!!!!!",), {"canonical": True}), (b.a2b_ascii85, (b"y",), {"foldspaces": True}),
                (b.a2b_ascii85, (b"!z",), {}), (b.crc32, ("x",), {}), (b.crc32, (b"x", 1.5), {})):
    t(f, *a, **k)
print(b.hexlify(bytes(range(10)), "-", 3), b.hexlify(bytes(range(10)), b"-", -3), b.hexlify(bytes(range(4)), ":", 9), b.hexlify(b"ab", ":", 0))
