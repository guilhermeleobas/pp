"""Bytecode decoding: instructions, jump targets, exception table."""

import types
from dataclasses import dataclass, field

import opcode as _opcode

_HASARG = frozenset(_opcode.hasarg)
_HASJUMP = frozenset(_opcode.hasjump)
_BACKWARD = frozenset(
    _opcode.opmap[n]
    for n in ("JUMP_BACKWARD", "JUMP_BACKWARD_NO_INTERRUPT", "END_ASYNC_FOR")
)
_EXTENDED_ARG = _opcode.opmap["EXTENDED_ARG"]
_INT_OVERFLOW = 2 ** 31


def compile_source(source: str, filename: str = "<string>", mode: str = "exec") -> types.CodeType:
    return compile(source, filename, mode, dont_inherit=True)


@dataclass(frozen=True, slots=True)
class Instruction:
    offset: int
    opcode: int
    opname: str
    arg: int | None
    cache_entries: int
    next_offset: int
    jump_target: int | None


@dataclass(frozen=True, slots=True)
class ExceptionTableEntry:
    start: int
    end: int
    target: int
    depth: int
    lasti: bool


@dataclass(frozen=True)
class DecodedCode:
    code: types.CodeType
    instructions: tuple
    exception_table: tuple
    _index: dict = field(default_factory=dict, repr=False, compare=False)
    # offset -> (opcode, instruction, offset, next_offset): what the eval loop
    # needs per instruction, in one lookup.
    ops: dict = field(default_factory=dict, repr=False, compare=False)

    def at(self, offset: int) -> Instruction:
        return self.instructions[self._index[offset]]

    def index_of(self, offset: int) -> int:
        return self._index[offset]


def _cache_size(opname: str) -> int:
    return _opcode._inline_cache_entries.get(opname, 0)


def _jump_target(op: int, arg: int, offset: int, caches: int) -> int | None:
    if op not in _HASJUMP:
        return None
    if op in _BACKWARD:
        arg = -arg
    return offset + 2 + arg * 2 + caches * 2


def _decode_instructions(raw: bytes) -> tuple:
    out = []
    extended_arg = 0
    i = 0
    n = len(raw)
    while i < n:
        op = raw[i]
        name = _opcode.opname[op]
        caches = _cache_size(name)
        if op in _HASARG:
            arg = raw[i + 1] | extended_arg
            extended_arg = (arg << 8) if op == _EXTENDED_ARG else 0
            if extended_arg >= _INT_OVERFLOW:
                extended_arg -= 2 * _INT_OVERFLOW
        else:
            arg = None
            extended_arg = 0
        next_offset = i + 2 + 2 * caches
        target = _jump_target(op, arg, i, caches) if arg is not None else None
        out.append(Instruction(i, op, name, arg, caches, next_offset, target))
        i = next_offset
    return tuple(out)


def _parse_varint(it) -> int:
    b = next(it)
    val = b & 63
    while b & 64:
        val <<= 6
        b = next(it)
        val |= b & 63
    return val


def parse_exception_table(code: types.CodeType) -> tuple:
    it = iter(code.co_exceptiontable)
    entries = []
    try:
        while True:
            start = _parse_varint(it) * 2
            length = _parse_varint(it) * 2
            target = _parse_varint(it) * 2
            dl = _parse_varint(it)
            entries.append(ExceptionTableEntry(start, start + length, target, dl >> 1, bool(dl & 1)))
    except StopIteration:
        return tuple(entries)


# Instructions that do nothing when executed: the eval loop steps over them
# (an instruction's successor is the next one that does something). Jumps may
# still land on one, which then runs as a no-op.
_NOOPS = frozenset(_opcode.opmap[n] for n in ("NOP", "NOT_TAKEN", "EXTENDED_ARG"))


def _eval_ops(instrs: tuple) -> dict:
    """offset -> (opcode, instruction, offset, offset of the next instruction to run)."""
    ops = {}
    nxt = None
    for ins in reversed(instrs):
        if nxt is None:
            nxt = ins.next_offset
        ops[ins.offset] = (ins.opcode, ins, ins.offset, nxt)
        nxt = nxt if ins.opcode in _NOOPS else ins.offset
    return ops


_cache: dict = {}  # id(code) -> DecodedCode (holds a strong ref, so ids are not reused)


def decode(code: types.CodeType) -> DecodedCode:
    d = _cache.get(id(code))
    if d is not None and d.code is code:
        return d
    instrs = _decode_instructions(code.co_code)
    index = {ins.offset: k for k, ins in enumerate(instrs)}
    ops = _eval_ops(instrs)
    d = DecodedCode(code, instrs, parse_exception_table(code), index, ops)
    _cache[id(code)] = d
    return d
