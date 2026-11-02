# Blockers

Things that stopped or would stop a piece of work. When something blocks a task,
it is added here and the task moves on (skipping or parking the blocked part).
Blocked work is retried once its blocker is resolved.

| Blocker | Blocks | Found | Status |
|---|---|---|---|
| `async` opcodes (GET_AWAITABLE, GET_AITER, GET_ANEXT, END_ASYNC_FOR) not implemented | `collections` and `unittest` CPython tests (test.support imports asyncio), any async code | 2026-11-01 | open |
| `itertools` CPython test exceeds the 600s timeout under pp | `itertools` row on the dashboard | 2026-11-01 | open |
| `types` test imports the blocked accelerator `_datetime` directly | `types` CPython test | 2026-11-01 | open |
| `string` test: 54 errors, cause not investigated | `string` CPython test | 2026-11-01 | open |
| `contextlib` test crashes with "E" before unittest's summary | `contextlib` CPython test | 2026-11-01 | open |
| t-strings use the host's C `string.templatelib.Template` type | "no C in the runtime" goal | 2026-11-02 | open |
| Lazy evaluation of type-parameter bounds/defaults (PEP 695/696) | `type X = ...` with forward refs, `def f[T=int]` defaults | 2026-11-01 | open |
