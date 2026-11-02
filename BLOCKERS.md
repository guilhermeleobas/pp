# Blockers

Things that stopped or would stop a piece of work. When something blocks a task,
it is added here and the task moves on (skipping or parking the blocked part).
Blocked work is retried once its blocker is resolved.

| Blocker | Blocks | Found | Status |
|---|---|---|---|
| `async` opcodes (GET_AWAITABLE, GET_AITER, GET_ANEXT, END_ASYNC_FOR) not implemented | `collections` and `unittest` CPython tests (test.support imports asyncio), any async code | 2026-11-01 | open |
| `itertools` CPython test exceeds the 600s timeout under pp | `itertools` row on the dashboard | 2026-11-01 | open |
| `types` test imports the blocked accelerator `_datetime` directly. Fix (S): `pp/lib/_datetime.py` re-exporting `_pydatetime`; `test_capsule_type` needs the C capsule and stays failing. Then blocked on async | `types` CPython test | 2026-11-01 | diagnosed |
| `string` test: all 54 errors are `test_pickle_template` (9 templates × 6 protocols): host C `Template.__reduce__` returns a host function pp's pickle can't handle. Fix (M): pp-native `Template`/`Interpolation`, built in `ceval.py` (after milestone 3) | `string` CPython test | 2026-11-01 | diagnosed |
| `contextlib`: `await` in `contextmanager` decorating a coroutine hits GET_AWAITABLE; `UnimplementedOpcode` deliberately bypasses guest `except` (`ceval.py:517`) and kills the run. Async generators lack `asend` | `contextlib` CPython test | 2026-11-01 | diagnosed (= async) |
| Guest tracebacks include VM frames (`run_frame`, `binary_op1`, ...) instead of only guest frames | `contextlib.test_contextmanager_traceback`, anything inspecting `__traceback__` | 2026-11-02 | open |
| `UnimplementedOpcode` aborts the whole process, so one unsupported test kills a module's run with no summary | accurate per-module counts | 2026-11-02 | open |
| t-strings use the host's C `string.templatelib.Template` type (see `string` row) | "no C in the runtime" goal | 2026-11-02 | diagnosed |
| Lazy evaluation of type-parameter bounds/defaults (PEP 695/696) | `type X = ...` with forward refs, `def f[T=int]` defaults | 2026-11-01 | open |
