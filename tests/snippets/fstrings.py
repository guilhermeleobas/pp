x = 3.14159
n = 42
s = "hi"
w = 10
print(f"{x}", f"{n}", f"{s}", f"plain")
print(f"{s!r} {s!s} {'é'!a} {n!r}")
print(f"{x:.2f}|{n:>6}|{n:<6}|{n:^6}|{n:06d}|{n:x}|{n:#b}")
print(f"{x:{w}.{3}}|{s:>{w}}|{n:,}")
print(f"{s!r:>8}|{n + 1}|{[1, 2]}|{ {'a': 1} }")
print(f"{n=}", f"{x = :.1f}")
print(f"a{n}b{s}c{x:.0f}d")
