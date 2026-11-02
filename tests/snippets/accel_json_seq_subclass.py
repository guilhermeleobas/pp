import json


class L(list):
    def __iter__(self):
        return iter([9])

    def __getitem__(self, i):
        return 7


class T(tuple):
    def __iter__(self):
        return iter([9])

    def __getitem__(self, i):
        return 7


class Sized(list):
    def __len__(self):
        return 5


print(json.dumps(L([1, 2])))
print(json.dumps(T((1, 2))))
print(json.dumps(Sized([1, 2])))
print(json.dumps({"a": L([1, 2, 3])}, indent=1))
