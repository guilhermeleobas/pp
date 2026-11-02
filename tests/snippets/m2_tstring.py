name = "x"
t = t"hello {name}"
print(type(t).__name__, t.strings, [i.value for i in t.interpolations])
