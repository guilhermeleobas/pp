"""Execution frames, modeled on CPython's _PyInterpreterFrame."""

import types

from pp.bytecode import DecodedCode, decode


class _Null:
    __slots__ = ()

    def __repr__(self):
        return "NULL"


NULL = _Null()  # re-exported as pp.vm.NULL

_names_cache: dict = {}  # id(code) -> (code, localsplusnames, first_free)


def localsplus_names(code: types.CodeType) -> tuple:
    """Return (co_localsplusnames, index of the first free variable)."""
    entry = _names_cache.get(id(code))
    if entry is not None and entry[0] is code:
        return entry[1], entry[2]
    varnames = code.co_varnames
    cells = tuple(c for c in code.co_cellvars if c not in varnames)
    names = varnames + cells + code.co_freevars
    first_free = len(varnames) + len(cells)
    _names_cache[id(code)] = (code, names, first_free)
    return names, first_free


class Frame:
    def __init__(self, code: types.CodeType, globals: dict, builtins: dict,
                 locals, previous: "Frame | None" = None, func=None):
        self.code = code
        self.decoded: DecodedCode = decode(code)
        self.globals = globals
        self.builtins = builtins
        self.locals = locals
        names, first_free = localsplus_names(code)
        self.localsplusnames = names
        self.first_free = first_free
        self.localsplus = [NULL] * len(names)
        self.stack: list = []
        self.instr_offset = 0
        self.lasti = 0          # offset of the instruction being executed (frame->instr_ptr)
        self.previous = previous
        self.func = func        # the Function being executed (f_funcobj), if any
        self.return_value = None
        self.yielded = False    # set by YIELD_VALUE, cleared by RETURN_VALUE
        self.yield_oparg = 0

    def push(self, v):
        self.stack.append(v)

    def pop(self):
        return self.stack.pop()

    def popn(self, n: int) -> list:
        if n == 0:
            return []
        vals = self.stack[-n:]
        del self.stack[-n:]
        return vals

    def peek(self, n: int = 1):
        return self.stack[-n]

    def lineno(self) -> int | None:
        for start, end, line in self.code.co_lines():
            if start <= self.lasti < end:
                return line
        return self.code.co_firstlineno

    def fast_locals_dict(self) -> dict:
        """Snapshot of the fast locals (what locals() returns in a function)."""
        d = {}
        cellvars = self.code.co_cellvars
        for k, name in enumerate(self.localsplusnames):
            v = self.localsplus[k]
            if v is NULL:
                continue
            if k >= self.first_free or (name in cellvars and isinstance(v, types.CellType)):
                try:
                    v = v.cell_contents
                except ValueError:
                    continue
            d[name] = v
        return d
