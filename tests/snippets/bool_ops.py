print(1 and 2, 0 and 2, 1 or 2, 0 or 2, None or "x", "" and "y")
print([] or {} or 0 or "last")
print(1 and 2 and 3, 1 and 0 and 3)
a = 5
print(a > 3 and a < 10, a > 3 or undefined_never_evaluated)
print(not (a > 3 and a < 4))
r = a if a > 3 else -a
print(r, "yes" if [] else "no", "deep" if a == 1 else "mid" if a == 5 else "none")
