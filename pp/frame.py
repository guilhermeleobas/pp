"""Execution frames, modeled on CPython's _PyInterpreterFrame."""

import types

from pp.bytecode import DecodedCode, decode


def _nlocalsplus(code: types.CodeType) -> int:
    varnames = code.co_varnames
    cells = [c for c in code.co_cellvars if c not in varnames]
    return len(varnames) + len(cells) + len(code.co_freevars)


class Frame:
    def __init__(self, code: types.CodeType, globals: dict, builtins: dict,
                 locals: dict | None, previous: "Frame | None" = None):
        self.code = code
        self.decoded: DecodedCode = decode(code)
        self.globals = globals
        self.builtins = builtins
        self.locals = locals
        self.localsplus = [None] * _nlocalsplus(code)
        self.stack: list = []
        self.instr_offset = 0
        self.previous = previous
        self.return_value = None

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
