# pp — a Python 3.15 bytecode interpreter written in Python

## Goal

Run Python programs with an interpreter (eval loop) and, over time, a standard
library written entirely in Python. The structure mirrors CPython so that
`Python/bytecodes.c` (3.15 branch) is the spec for every opcode.

## Environment

- Managed by pixi (`pixi.toml`). Host interpreter: CPython 3.15 from conda-forge.
- `pixi run test` runs the test suite; `pixi run pp <args>` runs the CLI.
- The VM targets 3.15 bytecode only. Other host versions are unsupported.

## References

**CPython is the ruler.** When pp, Dynamo, or anything else disagrees with
CPython 3.15's behavior or source, CPython wins. Dynamo is secondary prior art
only, consulted for ideas and edge cases, never as the authority.

- **CPython 3.15** (`<cpython checkout>`, branch
  `upstream/3.15`; read with `git show upstream/3.15:<path>`): `Python/bytecodes.c`
  (opcode semantics), `Python/ceval.c` (dispatch, exception unwinding, argument
  binding), `Python/intrinsics.c`, `Objects/genobject.c`, `Objects/funcobject.c`,
  `Objects/typeobject.c`, `Python/bltinmodule.c` (`__build_class__`, `super`),
  `Lib/importlib/_bootstrap.py` and `_bootstrap_external.py` (import system).
- **Dynamo** (`torch/_dynamo`): a Python
  implementation of a CPython bytecode interpreter loop. Useful prior art for
  `symbolic_convert.py` (`InstructionTranslator`: per-opcode handlers, CALL /
  LOAD_ATTR / LOAD_SUPER_ATTR forms, exception table handling, generator and
  `with` handling, version differences), `bytecode_transformation.py` and
  `bytecode_analysis.py` (decoding, exception table, jump targets),
  `variables/` (how CPython object protocols are modeled in Python, e.g.
  `tp_*` slot behavior). Dynamo traces symbolically; pp executes concretely, so
  take its opcode semantics and edge cases, not its tracing machinery.

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
  `dataclasses`, `enum`, `typing`, `io`, `argparse`, `os`, `_imp` (importer only). Ask before adding to
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

## Clarifications (from milestone 1)

- `run_source(globals=g)` executes in `g` itself and returns that same dict. If
  `g` has no `__builtins__`, pp inserts it, as `exec` does.
- `DecodedCode.at(offset)` / `index_of(offset)` raise `KeyError` for an offset
  that is not the start of an instruction.
- `next_offset` is always `offset + 2 + 2 * cache_entries`.
- CLI: when the program raises, `python -m pp run` prints the traceback to
  stderr and exits 1 (like `python`).

## Milestone 2: functions, classes, exceptions, generators, imports

Goal: `python -m pp run` executes a script that imports and uses the tier-1
stdlib modules (`operator`, `keyword`, `types`, `functools`, `collections`,
`heapq`, `reprlib`, `copyreg`, `itertools`), with those modules' source
executed by the VM, not the host.

New modules in `pp/` (names are the contract; internals are free):

- `pp/function.py` — `Function`, modeled on `PyFunctionObject`: `__code__`,
  `__globals__`, `__builtins__`, `__name__`, `__qualname__`, `__module__`,
  `__doc__`, `__defaults__`, `__kwdefaults__`, `__closure__` (tuple of host
  `types.CellType`), `__annotate__`, `__type_params__`, `__dict__`. It is a
  descriptor (`__get__` returns a bound method) and is callable from host code
  (`__call__` re-enters the VM), so `sorted(key=f)`, `map(f, ...)` and dunder
  methods defined in VM code work. Argument binding follows
  `_PyEval_MakeFrameVector` / `initialize_locals` in `ceval.c`, including the
  CPython error messages for missing/extra/duplicate arguments.
- `pp/generator.py` — `Generator` (`send`, `throw`, `close`, `__iter__`,
  `__next__`, `gi_frame`, `gi_running`, `gi_code`), built on suspendable VM
  frames. `async def` / `await` are out of scope for milestone 2.
- `pp/builtins.py` — the VM's builtins: a dict starting as a copy of the host
  `builtins` namespace, overriding the frame-aware ones: `__build_class__`,
  `__import__`, `globals`, `locals`, `vars`, `exec`, `eval`, `super`
  (zero-argument form via the calling VM frame's `__class__` cell and first
  argument). Frames run by pp use this dict as their builtins.
- `pp/importer.py` — the VM's import system, modeled on
  `importlib._bootstrap`'s `_find_and_load`/`_handle_fromlist`:
  - Module table: `vm.modules`, separate from the host `sys.modules`.
  - Search path: the pure-Python stdlib at `vendor/cpython-3.15.2/Lib`, then the
    script's directory, then extra paths given to the VM.
  - `.py` modules and packages are loaded from source, compiled with
    `pp.bytecode.compile_source`, and executed by the VM into a host
    `types.ModuleType` (`__name__`, `__file__`, `__package__`, `__spec__`
    (a `ModuleSpec` is fine), `__path__` for packages). Relative imports work.
  - C modules (builtin or extension) are importable only if listed in
    `HOST_MODULES` in `pp/importer.py`; otherwise importing them raises
    `ImportError`, so the pure-Python fallbacks run. `HOST_MODULES` starts with
    what the VM cannot do without (`sys`, `builtins`, `_imp`, `_thread`,
    `_weakref`, `_io`, `posix`, `errno`, `time`, `marshal`, `_warnings`, `gc`,
    `_abc` is NOT included: `abc` falls back to `_py_abc`) and is split into two clearly commented
    groups: **permanent** (the host boundary) and **temporary** (C modules we
    intend to replace with Python, e.g. `_collections`, `itertools`, `_sre`,
    `math`). Every temporary entry is a tracked piece of debt.
  - Accelerator modules (`_heapq`, `_bisect`, `_functools`, `_operator`,
    `_json`, `_pickle`, `_datetime`, `_decimal`, `_collections_abc`'s friends,
    ...) are never in `HOST_MODULES`.
- `pp/lib/` — pure-Python replacements for C-only modules, importable under the
  C module's name (`pp/lib/itertools.py`, `pp/lib/_collections.py`, ...). The
  importer searches `pp/lib` before the stdlib. Milestone 2 needs at least
  `itertools`; for others, put them in the temporary `HOST_MODULES` group.

Opcodes added in milestone 2: all of the fast-locals and cell/closure
family (LOAD_FAST*, STORE_FAST*, DELETE_FAST, LOAD_FAST_AND_CLEAR,
LOAD_FAST_CHECK, MAKE_CELL, LOAD_DEREF, STORE_DEREF, DELETE_DEREF,
COPY_FREE_VARS, LOAD_FROM_DICT_OR_DEREF, LOAD_FROM_DICT_OR_GLOBALS,
LOAD_LOCALS), MAKE_FUNCTION, SET_FUNCTION_ATTRIBUTE, RETURN_GENERATOR,
YIELD_VALUE, SEND, END_SEND, CLEANUP_THROW, CALL_FUNCTION_EX, CALL_INTRINSIC_1,
CALL_INTRINSIC_2, LOAD_BUILD_CLASS, LOAD_SUPER_ATTR, SETUP_ANNOTATIONS,
RAISE_VARARGS, RERAISE, PUSH_EXC_INFO, POP_EXCEPT, CHECK_EXC_MATCH,
CHECK_EG_MATCH, WITH_EXCEPT_START, LOAD_SPECIAL, IMPORT_NAME, IMPORT_FROM,
GET_LEN, MATCH_CLASS, MATCH_MAPPING, MATCH_SEQUENCE, MATCH_KEYS, DICT_MERGE,
LOAD_ATTR method form (unbound function + self, per 3.15).

Exceptions use the code object's exception table (`get_exception_handler` /
the `exception_unwind` label in `ceval.c`): on a raise, find the handler for
the instruction's offset, pop the stack to `depth`, push `lasti` if set, push
the exception, jump to `target`; if none, pop the frame and re-raise in the
caller. Tracebacks are not required to include VM frames yet. The VM tracks its
own handled-exception stack (`exc_info`), used by bare `raise`, implicit
`__context__` chaining, and `sys.exc_info()`/`sys.exception()` called from VM
code (provide them via a VM-side `sys` override or document the gap).

Known milestone 2 gaps that are acceptable: `async`, template strings
(`BUILD_TEMPLATE`, `BUILD_INTERPOLATION`), VM frames in host tracebacks and
`sys._getframe`, `locals()` write-back.

### Milestone 2 clarifications

- `VirtualMachine(path: list[str] | None = None)`: `path` is extra import
  search directories (searched after `pp/lib` and the stdlib). The VM's module
  table is `vm.modules`. `run_source(..., vm=None)` and `run_file(path, vm=None)`
  accept an existing VM; by default each call creates a fresh one. `run_file`
  adds the script's directory to the VM's path.
- `DELETE_GLOBAL` is in milestone 2 scope.
- `sys.exception()` / `sys.exc_info()` called from VM code must reflect the VM's
  handled exception (not a documented gap).
- `__file__` is an absolute, resolved path.

## Milestone 3: CPython's object protocol, mirrored

Goal: opcode handlers and pp's runtime dispatch exactly as CPython does, through
the same structures and functions, instead of relying on host operators. Values
stay host objects; what becomes ours is the *dispatch*: type slots,
descriptors, attribute lookup, the abstract object layer, frames, generators
and exception state.

### Type slots (`pp/typeobject.py`)

- `PyTypeObject`-shaped slot table per type, with CPython's field names
  (`tp_getattro`, `tp_setattro`, `tp_descr_get`, `tp_descr_set`, `tp_call`,
  `tp_richcompare`, `tp_iter`, `tp_iternext`, `tp_hash`, `tp_new`, `tp_init`,
  `nb_add`, `nb_inplace_add`, ..., `nb_bool`, `mp_subscript`,
  `mp_ass_subscript`, `sq_contains`, ...).
- **Only add a slot when an opcode or abstract function needs it.** No
  `tp_flags` bits, `tp_basicsize`, buffer slots, GC slots, etc., unless
  something actually reads them. The slot list grows with use.
- Slots are filled like `typeobject.c`'s `slotdefs` / `update_one_slot` /
  `fixup_slot_dispatchers`: from the type's MRO, a dunder defined in Python
  (VM `Function`, `staticmethod`, `classmethod`, ...) gets the matching
  `slot_*` function (`slot_tp_getattr_hook`, `slot_nb_add` via the
  `SLOT1BINFULL` logic, `slot_tp_richcompare`, ...); a dunder provided by a host
  C type calls that host method directly (it is the "C slot").
- `_PyType_Lookup(type, name)`: MRO walk over `type.__dict__`s.
- Caching is optional; if added it must be invalidated when a type's dict or
  `__bases__` change. Correctness first.

### Abstract layer (`pp/object.py`, `pp/abstract.py`)

CPython's functions, same names and algorithms, built on the slots:
`PyObject_GetAttr`, `PyObject_SetAttr`, `PyObject_GenericGetAttr` /
`_PyObject_GenericGetAttrWithDict` / `PyObject_GenericSetAttr` (data vs
non-data descriptor precedence, instance `__dict__`), `_PyObject_GetMethod`
(LOAD_ATTR method form), `PyObject_RichCompare` / `do_richcompare` (reflected
order, `NotImplemented`), `PyObject_IsTrue`, `PyObject_Hash`,
`PyNumber_*` / `PyNumber_InPlace*` via `binary_op1` / `binary_iop1`
(subclass-first rule), `PyObject_GetItem` / `SetItem` / `DelItem`,
`PySequence_Contains`, `PyObject_GetIter`, `PyIter_Next`, `PyObject_Call` /
vectorcall. Only the functions the VM actually calls.

### Descriptors and functions (`pp/funcobject.py`, `pp/descrobject.py`)

`PyFunctionObject` (`func_descr_get` → `PyMethodObject`), and the descriptor
types pp needs to own (`classmethod`, `staticmethod`, `property` only if host
versions can't be driven correctly through the slots).

### Frames, generators, exceptions

- `pp/frame.py`: `_PyInterpreterFrame` field names (`f_executable`, `f_globals`,
  `f_builtins`, `f_locals`, `f_funcobj`, `localsplus`, `stackpointer`,
  `instr_ptr`, `previous`, `owner`) plus the `PyFrameObject` view.
- `pp/genobject.py`: `PyGenObject` with `gi_frame_state`
  (`FRAME_CREATED`, `FRAME_SUSPENDED`, `FRAME_EXECUTING`, `FRAME_COMPLETED`,
  ...), `gen_send_ex2`, `gen_throw`, `gen_close`, `gi_exc_state`.
- `pp/errors.py` (name kept; `UnimplementedOpcode` stays): the thread state's
  `exc_info` chain of `_PyErr_StackItem`, `_PyErr_SetObject` (implicit
  chaining happens here and only here), `_PyErr_ChainStackItem`,
  `_PyErr_GetTopmostException`.
- `pp/ceval.py`: dispatch and `exception_unwind`; opcode handlers call the
  abstract layer, never Python operators on values (no `a + b`, `a[b]`,
  `getattr`, `==` on user values inside handlers).

Out of scope: our own object representations (`PyLongObject`, `PyDictObject`,
...). Values remain host objects.
