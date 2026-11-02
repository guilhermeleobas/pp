"""Errors raised by the pp VM itself (not by user code)."""


class UnimplementedOpcode(NotImplementedError):
    def __init__(self, opname: str):
        super().__init__(f"opcode {opname} is not implemented")
        self.opname = opname
