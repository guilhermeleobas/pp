class A:
    cls_attr = 1
    def __init__(self, x):
        self.x = x
    def get(self):
        return self.x
    def __repr__(self):
        return f"A({self.x!r})"
class B(A):
    def __init__(self, x, y):
        super().__init__(x)
        self.y = y
    def get(self):
        return super().get() + self.y
b = B(1, 2)
print(b, b.get(), B.cls_attr, isinstance(b, A), B.__mro__[1].__name__)
print(B.__qualname__, B.__module__, sorted(k for k in vars(b)))
print(A.get(b), type(b).__name__)
class C(B):
    def get(self):
        return [super().get(), super(B, self).get()]
print(C(5, 6).get())
