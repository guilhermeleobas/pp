z = 3 + 4j
print(z.real, z.imag, z.conjugate(), abs(z))
print((255).bit_length(), (10).to_bytes(2, "big"), int.from_bytes(b"\x01\x00", "big"))
print("abc".__class__.__name__, [].__class__, (1).__add__(2))
ModuleType = type(__builtins__)
m = ModuleType("mymod")
m.x = 5
m.y = [1]
m.y.append(2)
print(m.x, m.y, m.__name__)
m.x += 1
print(m.x)
del m.x
print(hasattr(m, "x"), hasattr(m, "y"))
