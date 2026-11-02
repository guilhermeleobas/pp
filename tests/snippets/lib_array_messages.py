# array error messages and edge semantics must match CPython 3.15
import array


def show(f):
    try:
        r = f()
    except Exception as e:
        print(type(e).__name__, e)
    else:
        print("ok", r)


vals = [-2**70, -2**63 - 1, -2**63, -2**31 - 1, -2**15 - 1, -129, -1, 0, 255, 256,
        2**15, 2**16, 2**31, 2**32, 2**63, 2**64, 2**70]
for c in "bBhHiIlLqQ":
    for v in vals:
        show(lambda: array.array(c, [v]).tolist())
    show(lambda: array.array(c, [1.0]))
    show(lambda: array.array(c, ["a"]))
    show(lambda: array.array(c, [None]))
for c in ["e", "f", "d", "Zf", "Zd"]:
    show(lambda: array.array(c, ["a"]))
    show(lambda: array.array(c, [None]))
show(lambda: array.array("e", [1e5]))
show(lambda: array.array("e", [1e300]))
show(lambda: array.array("f", [1e300]))
show(lambda: array.array("d", [2**2000]))
show(lambda: array.array("w", ["ab"]))
show(lambda: array.array("w", [1]))

# resizing an array with an exported buffer
a = array.array("i", [1, 2, 3])
m = memoryview(a)
for f in (lambda: a.append(1), lambda: a.extend([1]), lambda: a.pop(), lambda: a.remove(1),
          lambda: a.insert(0, 1), lambda: a.clear(), lambda: a.fromlist([1]),
          lambda: a.frombytes(b"abcd"), lambda: a.__delitem__(0), lambda: a.__delitem__(slice(0, 2)),
          lambda: a.__setitem__(slice(0, 1), array.array("i")), lambda: a.__iadd__(a),
          lambda: a.__imul__(2)):
    show(f)
a[0] = 7
a[::2] = array.array("i", [8, 9])
a.reverse()
print(a.tolist(), m.tolist())
m.release()
a.append(4)
print(a)

# bulk paths and their fallbacks
print(array.array("b", [True, 3, -128]), array.array("B", range(256)).tobytes()[250:])
print(array.array("d", [1, 2.5, True]), array.array("f", (0.1, 2)), array.array("Zd", [1, 2j]))
a = array.array("i", [1, 2])
show(lambda: a.extend([3, 4.5, 5]))   # items before the bad one are kept
print(a)
show(lambda: a.fromlist([1, "x"]))    # fromlist is atomic
print(a)
big = array.array("i", range(1000))
print(sum(big), big[::7][:5], big[998:0:-300], len(list(iter(big))), big.index(999), big.count(5))
big[::100] = array.array("i", range(10))
del big[1::2]
print(big[:6], len(big))
big.reverse()
print(big[:3], big[-3:], 998 in big, 999 in big)
t = array.array("d", [1.5] * 300)
it = iter(t)
print(next(it), sum(t), t == array.array("d", [1.5] * 300))
