def a():
    return b()
def b():
    print("in b")
    return {}["missing"]
try:
    a()
finally:
    print("finally ran")
