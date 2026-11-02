import pickle, sys, types
for f in (getattr, setattr, delattr, len):
    print(pickle.loads(pickle.dumps(f)) is f, pickle.dumps(f, 0))
mod = types.ModuleType("m3_pickle_mod2")
sys.modules["m3_pickle_mod2"] = mod
exec("class T:\n    def m(self): pass\n", mod.__dict__)
print(pickle.dumps(mod.T.m, 0))
del sys.modules["m3_pickle_mod2"]
