for i in range(5):
    print(i, end=" ")
print()
for c in "hey":
    print(c)
for i in range(10):
    if i == 3:
        continue
    if i == 6:
        break
    print("i", i)
else:
    print("never")
for i in []:
    print("never")
else:
    print("empty else")
for i in range(2):
    pass
else:
    print("else after", i)
