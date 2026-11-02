# The body of this `if` is long enough that the jump needs EXTENDED_ARG.
flag = len("abc") == 3
total = 0
if flag:
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
    total += 1; total += 2; total += 3; total += 4; total += 5; total += 6; total += 7; total += 8
print(total)
i = 0
while i < 3:
    i += 1
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
    total -= 1; total -= 2; total -= 3; total -= 4; total -= 5; total -= 6; total -= 7; total -= 8
print(total, i)
