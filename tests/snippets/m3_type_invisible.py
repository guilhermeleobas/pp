class C:
    def f(self): pass
C().f()
print('__pp_view__' in C.__dict__, hasattr(C, '__pp_view__'), [n for n in dir(C) if 'pp' in n])
print(sorted(k for k in C.__dict__ if not k.startswith('__')), C.__qualname__)
E = type('E', (), {'x': 1})
print(len([E().x for k in E.__dict__]))
for k in E.__dict__:
    E().x
class D(C): pass
D().f()
print(sorted(vars(D)) == sorted(vars(D)), len(vars(D)))
C.__qualname__ = "Renamed"
C().f(); print(C.__qualname__, repr(C))
