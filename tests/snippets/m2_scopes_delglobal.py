g1 = 1
def drop():
    global g1
    del g1
drop()
print("g1" in globals())
try:
    drop()
except NameError as e:
    print(type(e).__name__, e)
