# pp — a Python 3.15 bytecode interpreter written in Python

## Goal

Run Python programs with an interpreter (eval loop) and, over time, a standard
library written entirely in Python. The structure mirrors CPython so that
`Python/bytecodes.c` (3.15 branch) is the spec for every opcode.

## Environment

- Managed by pixi (`pixi.toml`). Host interpreter: CPython 3.15 from conda-forge.
- `pixi run test` runs the test suite; `pixi run pp <args>` runs the CLI.
- The VM targets 3.15 bytecode only. Other host versions are unsupported.

## Host boundary (prototype)

Borrowed from the host CPython, for now:

- **Compilation**: source → code object via the builtin `compile()`. This is
  isolated behind `pp.bytecode.compile_source` so it can be replaced later by a
  pure-Python compiler.
- **Object model**: `int`, `str`, `list`, `dict`, `type`, descriptors, etc. are
  host objects. Operators on them (`a + b`, `a[b]`, `a < b`) use host semantics.
- **Builtins** that do not touch frames (`print`, `len`, `range`, ...).

Ours, in pure Python:

- Bytecode decoding (instructions, jump targets, exception table).
- Frames, the eval loop, and opcode handlers.
- Later: functions, cells, generators, import system, frame-aware builtins,
  pure-Python stdlib modules.

Rules for code under `pp/`:

- Must not import `dis` (it is the test oracle, not a dependency).
- May import only: `sys`, `types`, `builtins`, `opcode` (data tables only),
  `dataclasses`, `enum`, `typing`, `io`, `argparse`, `os`. Ask before adding to
  this list.
- No C extensions, no `ctypes`.

## Package layout and API contract

```
pp/
  __init__.py      # re-exports run_source, run_file
  __main__.py      # CLI
  errors.py        # UnimplementedOpcode
  bytecode.py      # compile_source, decode, Instruction, ExceptionTableEntry, DecodedCode
  frame.py         # Frame
  vm.py            # eval loop and opcode handlers
tests/             # owned by the tester; see "Testing"
```

### `pp.bytecode`

```python
def compile_source(source: str, filename: str = "<string>", mode: str = "exec") -> types.CodeType

@dataclass(frozen=True)
class Instruction:
    offset: int              # byte offset of this code unit in co_code
    opcode: int
    opname: str
    arg: int | None          # full oparg including preceding EXTENDED_ARGs; None if the op has no arg
    cache_entries: int       # number of inline CACHE code units following it
    next_offset: int         # byte offset of the next instruction (after caches)
    jump_target: int | None  # byte offset of the jump target, same value dis reports; None if not a jump

@dataclass(frozen=True)
class ExceptionTableEntry:
    start: int   # byte offset, inclusive
    end: int     # byte offset, exclusive
    target: int  # byte offset of handler
    depth: int   # stack depth to unwind to
    lasti: bool  # whether to push the offset of the raising instruction

@dataclass(frozen=True)
class DecodedCode:
    code: types.CodeType
    instructions: tuple[Instruction, ...]   # in order; CACHE units are skipped, EXTENDED_ARG units are kept
    exception_table: tuple[ExceptionTableEntry, ...]
    def at(self, offset: int) -> Instruction     # instruction starting at byte offset
    def index_of(self, offset: int) -> int       # position in `instructions`

def decode(code: types.CodeType) -> DecodedCode   # cached per code object
```

`decode` must agree with `dis.get_instructions(code)` (offset, opcode, opname,
arg, jump_target, cache count) and with `dis._parse_exception_table(code)`, for
every code object the host can compile. Note: `dis` reports `FOR_ITER`'s target
as the `END_FOR`; the *runtime* skips `END_FOR` (see `bytecodes.c`). That
adjustment belongs to the VM, not the decoder.

### `pp.frame.Frame`

Modeled on `_PyInterpreterFrame`: `code`, `decoded`, `globals`, `builtins`,
`locals` (dict for module/class code, else `None`), `localsplus` (list sized
`co_nlocalsplus`), `stack` (list), `instr_offset`, `previous` (caller frame or
`None`). Fields may be added, not renamed.

### `pp.vm`

```python
class VirtualMachine:
    def run_code(self, code: types.CodeType, globals: dict | None = None) -> object  # returns the frame's return value
def run_source(source: str, filename: str = "<string>", globals: dict | None = None) -> dict  # returns globals
def run_file(path: str) -> dict
```

- `globals` defaults to a fresh dict with `__name__ = "__main__"` and
  `__builtins__` set to the host `builtins` module.
- The stack holds `NULL` as a dedicated sentinel object `pp.vm.NULL`, never `None`.
- Hitting an opcode without a handler raises
  `pp.errors.UnimplementedOpcode(opname)` (a `NotImplementedError` subclass).
- Exceptions raised by user code propagate out of `run_code` as the original
  host exception (no wrapping).

### CLI

```
python -m pp run FILE        # execute FILE under the VM
python -m pp dis FILE        # print pp's own decoding of FILE (all nested code objects)
```

## Milestone 1 scope (opcodes)

Module-level code and loops calling host builtins; no `def`, classes, or
exceptions handling yet:

RESUME, NOP, NOT_TAKEN, EXTENDED_ARG, CACHE (never executed), LOAD_CONST,
LOAD_SMALL_INT, LOAD_COMMON_CONSTANT, LOAD_NAME, STORE_NAME, DELETE_NAME,
LOAD_GLOBAL, STORE_GLOBAL, PUSH_NULL, POP_TOP, COPY, SWAP, CALL, CALL_KW,
BINARY_OP (all NB_* ops including subscript), BINARY_SLICE, STORE_SLICE,
STORE_SUBSCR, DELETE_SUBSCR, UNARY_NEGATIVE, UNARY_INVERT, UNARY_NOT, TO_BOOL,
COMPARE_OP, IS_OP, CONTAINS_OP, POP_JUMP_IF_TRUE/FALSE/NONE/NOT_NONE,
JUMP_FORWARD, JUMP_BACKWARD, JUMP_BACKWARD_NO_INTERRUPT, GET_ITER, FOR_ITER,
END_FOR, POP_ITER, BUILD_TUPLE, BUILD_LIST, BUILD_SET, BUILD_MAP, BUILD_SLICE,
BUILD_STRING, LIST_APPEND, LIST_EXTEND, SET_ADD, SET_UPDATE, MAP_ADD,
DICT_UPDATE, UNPACK_SEQUENCE, UNPACK_EX, FORMAT_SIMPLE, FORMAT_WITH_SPEC,
CONVERT_VALUE, LOAD_ATTR (incl. method form), STORE_ATTR, DELETE_ATTR,
RETURN_VALUE.

## Testing

- `tests/test_bytecode.py`: `pp.bytecode.decode` vs `dis` as oracle, including
  every `.py` file in the host stdlib (recursively over nested code objects).
- `tests/test_vm.py` + `tests/snippets/*.py`: differential tests. Each snippet is
  run under the host (`exec`) and under `pp.run_source`; stdout and the raised
  exception type (if any) must match.
- `tests/test_cli.py`: smoke tests for the CLI.
- Snippets that need features beyond the current milestone are marked
  `xfail(strict=True)` with the missing opcode in the reason, so the suite
  tracks progress.
