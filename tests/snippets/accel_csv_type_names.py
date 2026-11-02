import csv
import io

r = csv.reader(io.StringIO("a,b\n"))
w = csv.writer(io.StringIO())
print(type(r).__name__, type(r).__qualname__, type(r).__module__)
print(type(w).__name__, type(w).__qualname__, type(w).__module__)
print(repr(r).split(" object at")[0])
print(repr(w).split(" object at")[0])
print(next(r))
for cls in (type(r), type(w)):
    try:
        cls()
    except TypeError as e:
        print(e)
