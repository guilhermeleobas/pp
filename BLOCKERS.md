# Blockers

Things that stopped or would stop a piece of work. When something blocks a task,
it is added here and the task moves on (skipping or parking the blocked part).
Blocked work is retried once its blocker is resolved.

| Blocker | Blocks | Found | Status |
|---|---|---|---|
| `async` opcodes (GET_AWAITABLE, GET_AITER, GET_ANEXT, END_ASYNC_FOR) not implemented | `collections` and `unittest` CPython tests (test.support imports asyncio), any async code | 2026-11-01 | open |
| Milestone 3 made pp ~2x slower (slot dispatch overhead); `difflib` now times out. Perf work on Fable/Opus, after `impl/m3-fixes` merges | `difflib`, `itertools`, gate run time | 2026-11-02 | open |
| `itertools` CPython test exceeds the 600s timeout under pp | `itertools` row on the dashboard | 2026-11-01 | open |
| `types` test imports the blocked accelerator `_datetime` directly. Fix (S): `pp/lib/_datetime.py` re-exporting `_pydatetime`; `test_capsule_type` needs the C capsule and stays failing. Then blocked on async | `types` CPython test | 2026-11-01 | diagnosed |
| `string` test: all 54 errors are `test_pickle_template` (9 templates × 6 protocols): host C `Template.__reduce__` returns a host function pp's pickle can't handle. Fix (M): pp-native `Template`/`Interpolation`, built in `ceval.py` (after milestone 3) | `string` CPython test | 2026-11-01 | diagnosed |
| `contextlib`: `await` in `contextmanager` decorating a coroutine hits GET_AWAITABLE; `UnimplementedOpcode` deliberately bypasses guest `except` (`ceval.py:517`) and kills the run. Async generators lack `asend` | `contextlib` CPython test | 2026-11-01 | diagnosed (= async) |
| Guest tracebacks include VM frames (`run_frame`, `binary_op1`, ...) instead of only guest frames | `contextlib.test_contextmanager_traceback`, anything inspecting `__traceback__` | 2026-11-02 | open |
| `UnimplementedOpcode` aborts the whole process, so one unsupported test kills a module's run with no summary | accurate per-module counts | 2026-11-02 | open |
| t-strings use the host's C `string.templatelib.Template` type (see `string` row) | "no C in the runtime" goal | 2026-11-02 | diagnosed |
| Lazy evaluation of type-parameter bounds/defaults (PEP 695/696) | `type X = ...` with forward refs, `def f[T=int]` defaults | 2026-11-01 | open |
| `compile(..., "single")` / interactive expression results not written via `sys.displayhook`, so doctests see "Got nothing" | `decimal` (432 of 587 are doctest "Got nothing"), any doctest-based test | 2026-11-02 | open |
| `warnings` do not fire from guest code: `assertWarns` / `warnings_helper.check_warnings` report "DeprecationWarning/FutureWarning/RuntimeWarning not triggered" | `ast`, `base64`, `calendar`, `optparse`, `posixpath`, `tomllib`, `decimal` (1–2 tests each) | 2026-11-02 | open |
| `types.FunctionType(..., closure=...)` keyword rejected (`Function.__init__() got an unexpected keyword argument 'closure'`) | `copy` (1), `dataclasses` (8) | 2026-11-02 | open |
| pp functions cannot be pickled (`cannot pickle 'function' object`) | `dataclasses` (28), `inspect` partly | 2026-11-02 | open |
| C accelerators with no pp stand-in: `_csv`, `_pickle`, `_bisect`, `_json` (`import_fresh_module` yields `None` and tests then fail on `None.<attr>`), `_hashlib`/sha2 (`unsupported hash algorithm sha512`) | `csv` (import error, 0 tests), `inspect` (import error), `json` (setUp crash, 0 tests), `bisect` (23 errors), `random` (3) | 2026-11-02 | open |
| PEP 695 `class C[T]` hits `typing.Generic[...]`: "Parameters to Generic[...] must all be type variables" (`_intrinsic_subscript_generic`, `ceval.py`); type params created by pp are probably not recognised as `typing.TypeVar` | `typing` (import-time crash, 0 tests), PEP 695 code in other tests | 2026-11-02 | open |
| Missing `__index__` on instances/`float` raises `AttributeError` instead of `TypeError`/falling back (`'IPv6Address' object has no attribute '__index__'`) | `ipaddress` (6), `random` (4) | 2026-11-02 | open |
| `unittest.mock.patch` result "does not support the context manager protocol" (`__enter__`/`__exit__` special-method lookup on `_patch`) | `random` (7), mock users | 2026-11-02 | open |
| `sys.setrecursionlimit` rejects low limits at current depth (VM frames count toward depth); `RecursionError` on deep-but-legal guest recursion | `tomllib` (2), `ast` (1) | 2026-11-02 | open |
| `dis` output differs: `COPY_FREE_VARS` shown and line/`RESUME` offsets differ from CPython's bytecode | `dis` (7) | 2026-11-02 | open |
| Performance: whole-module runs exceed the 600s timeout (`datetime` via `_pydatetime`, `statistics`; tests pass up to the cutoff, only a few errors) | `datetime`, `statistics`, `itertools` | 2026-11-02 | open |
| `_weakref` (pure Python): host values' death is invisible to pp, so a weak reference is a strong reference for as long as the ref itself lives (dropping the last ref frees the object), never dies by itself, and callbacks never fire. No per-object ref list is kept: `getweakrefs()` returns `[]` and `ref(o) is ref(o)` is False (CPython shares the basic ref); `getweakrefcount` counts live refs. Fix needs pp-owned object lifetimes (refcounts) or a host hook | `weakref`/`weakset` CPython tests that rely on collection or on shared refs, `WeakValueDictionary`/`WeakSet` auto-removal, `weakref.finalize` firing | 2026-11-02 | accepted limitation (pp/lib/_weakref.py) |
| `gc` (pure Python): `collect()` frees nothing and returns 0; `get_objects`/`get_referrers`/`get_referents` are empty, `is_tracked`/`is_finalized` are False, callbacks never run. `test.support.gc_collect()` / `gc_collect` users (assertions that an object or weakref died after `del x; gc_collect()`) therefore fail | `gc` CPython test, `weakref`, `functools`/`operator` tests that wait for collection | 2026-11-02 | accepted limitation (pp/lib/gc.py) |
| `array` (pure Python): bulk operations run as host builtins and `f`/`d`/`Zf`/`Zd` are packed by `memoryview.cast` (no `struct`); arrays over 1 KiB are iterated through a snapshot list iterator (mutation during iteration is not seen); `buffer_info()` address is `id()` of the backing bytearray; `memoryview(a).format` is `'B'` for `u`, `w`, `Zf`, `Zd`; NaN payload/sign not preserved; per-item access is interpreted (slow) | `array` CPython test (weakref death tests) | 2026-11-02 | accepted limitation (pp/lib/array.py) |
| Guest `warnings.catch_warnings`/`assertWarns` do not see warnings raised by the host `_warnings.warn` (the C `warn` uses the host `warnings` module state). Needs a pure-Python `_warnings` | `array` `test_typecode_u_deprecation` (2 tests), any `assertWarns` test | 2026-11-02 | open |

## To do

Ranked by tests/modules unblocked. Size: S ≤ ½ day, M ≈ 1–2 days, L = more.

1. **Async opcodes** (GET_AWAITABLE, GET_AITER, GET_ANEXT, END_ASYNC_FOR) — unblocks `unittest`, `collections`, `contextlib` runs and everything importing `asyncio` via `test.support`. L
2. **Performance of the interpreter loop** — `datetime`, `statistics`, `itertools` time out at 600s; these are thousands of tests. M–L
3. **Doctest support**: `compile(..., "single")` + `sys.displayhook` for expression statements — recovers ~430 `decimal` tests and other doctest suites. S
4. **Warnings from guest code** (`warnings.warn` stacklevel/`__warningregistry__`, `assertWarns`) — 1–2 tests in 7+ modules; also `warnings` itself (64 failures). M
5. **pp-native accelerator stand-ins** in `pp/lib/`: `_csv`, `_json` (or make `import_fresh_module` return a usable module), `_bisect`, `_pickle`, `_datetime`/`_hashlib` shims — unblocks `csv`, `json`, `inspect` entirely, 23 `bisect` tests. M each; `_datetime` shim is S
6. **PEP 695 type params as real `typing.TypeVar`s** (fix `_intrinsic_subscript_generic`) — unblocks the whole `typing` suite. S–M
7. **`FunctionType(closure=...)` keyword and pickling of pp functions** — 37 `dataclasses` tests, 1 `copy`. S
8. **`__index__` lookup semantics** (`operator.index`, `int()`, `TypeError` instead of `AttributeError`) — ~10 `ipaddress`/`random` tests. S
9. **`unittest.mock` patch context manager lookup** (special-method lookup on type) — 7 `random` tests, many mock users. S
10. **Guest-only tracebacks and `UnimplementedOpcode` as a catchable error** (see rows above) — accurate counts when a test hits a missing opcode. M
11. **Recursion limit accounting** (guest depth, not VM frames) — `tomllib`, `ast`. S
12. **`dis` bytecode parity** (`COPY_FREE_VARS` display, RESUME/line offsets) — 7 `dis` tests. M
