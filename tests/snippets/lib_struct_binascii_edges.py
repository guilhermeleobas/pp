import struct, binascii, warnings
def t(f,*a,**k):
    try: print(f(*a,**k))
    except Exception as e: print(type(e).__name__, e)
for f in ('@F','<F','>F','=D','@D'):
    for v in (3.5e38, 2**200, -3.5e38, complex(3.5e38,1)): t(struct.pack,f,v)
t(binascii.unhexlify,b'ab',b' '); t(binascii.a2b_hex,b'ab',b' '); t(binascii.unhexlify,b'a b',ignorechars=b' ')
t(struct.unpack,'i',memoryview(b'abcdabcd')[::2])
t(struct.unpack_from,'i',memoryview(b'abcdabcd')[::2])
warnings.simplefilter('error')
for v in (2**40,-2**31,-2**31-1,2**32): t(binascii.crc32,b'x',v); t(binascii.crc_hqx,b'x',v)
print([n for n in dir(binascii) if n.startswith('_') and n not in ('__file__', '__loader__', '__spec__', '__package__', '__cached__')])
print('unpack_iterator' in dir(struct), type(struct.iter_unpack('b', b'x')).__name__)
