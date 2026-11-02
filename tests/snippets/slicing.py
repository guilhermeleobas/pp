s = list(range(10))
print(s[2:5], s[:3], s[7:], s[::2], s[::-1], s[-3:], s[:-7], s[1:8:3])
t = "abcdefgh"
print(t[1:4], t[::-2], t[-1:-4:-1], t[100:], t[:])
i = 2
j = 6
print(s[i:j], s[i:], s[:j], s[i:j:2], s[slice(1, 3)])
s[1:3] = ["a", "b", "c"]
print(s)
s[::3] = [0] * len(s[::3])
print(s)
del s[2:4]
print(s)
del s[::2]
print(s)
s[i:j] = []
print(s)
