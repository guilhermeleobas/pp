i = 0
total = 0
while i < 10:
    i += 1
    if i % 2 == 0:
        continue
    if i > 7:
        break
    total += i
print(i, total)
n = 0
while n < 3:
    n += 1
else:
    print("while else ran", n)
n = 0
while True:
    n += 1
    if n == 4:
        break
else:
    print("never")
print("done", n)
