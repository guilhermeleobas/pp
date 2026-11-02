a = 1
b = 5
c = 10
print(a < b < c, a < c < b, a <= a < b <= b)
print(1 < 2 > 0 != 4, 0 < a == 1 < 3)
print(a < b < c < 100 < 1000)
if 0 <= b < 10:
    print("in range")
if not (0 <= c < 10):
    print("out of range")
