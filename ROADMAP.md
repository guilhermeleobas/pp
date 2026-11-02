# Roadmap

Where pp stands and what comes next. Per-module numbers are in
[STATUS.md](STATUS.md); blockers and the ranked to-do list are in
[BLOCKERS.md](BLOCKERS.md); the process is in [WORKFLOW.md](WORKFLOW.md).

Work is paused as of 2026-11-02. Branches below are pushed to GitHub.

## Done (on `main`)

- Milestone 1: bytecode decoding, frames, eval loop for module-level code.
- Milestone 2: functions, classes, exceptions, generators, importer, `pp/lib`,
  `match`.
- Milestone 3: CPython-mirrored type slots and abstract layer
  (`typeobject`, `abstract`, `call`, `ceval`, `genobject`, `funcobject`).
- Host-boundary import guard test (`tests/test_host_boundary.py`).
- Stdlib tracking: tiers 1–4 (49 modules) validated by CPython's Lib/test at
  tag v3.15.2, dashboard in `docs/dashboard.html`.
- Design rule: C modules are reimplemented in Python, limitations accepted
  (DESIGN.md, "C modules: reimplement, don't borrow").

## In review (not merged)

| Branch | What | Review | Gate | Next step |
|---|---|---|---|---|
| `impl/m3-fixes` | Milestone 3 regression fixes; CPython-style version-tag type cache; no new host imports; warnings go through the guest `warnings` | round 1: fix (all items addressed in round 2) | round 2: no drops except `difflib` timeout (perf) | re-review round 2, judge, merge |
| `impl/collections` | Pure-Python `_collections` (deque, defaultdict, OrderedDict, views) | round 1: fix (all items addressed) | round 2: `pprint` back to 77/77 | re-review, judge, merge |
| `impl/sre` | Pure-Python `_sre` regex engine (`re` fully in Python) | merge, with a limit: `RecursionError` on group repeats over ~600 chars | clean vs `main` | judge; then explicit-stack matcher (see below) |
| `impl/array-weakref` | Pure-Python `array`, `_weakref`, `gc` | round 1: fix (registry, array speed, error messages; addressed in round 2) | weakref/object-death drops (accepted) | re-review round 2, judge, merge |

Merge order: `impl/m3-fixes` → `impl/collections` → `impl/sre` →
`impl/array-weakref`; regenerate the dashboard after each.

## Next

1. **Finish the review queue above** (judge on Opus, then merge).
2. **Performance** of the interpreter loop (Opus/Fable, `perf/` branch): the
   milestone 3 ~2× slowdown, `difflib`/`itertools`/`datetime`/`statistics`
   timeouts.
3. **`_sre` explicit-stack matcher**, as in `sre_lib.h`, to remove the
   recursion limit.
4. **Async opcodes** (GET_AWAITABLE, GET_AITER, GET_ANEXT, END_ASYNC_FOR):
   unblocks `unittest`, `collections`, `contextlib` and everything that imports
   `asyncio` through `test.support`.
5. **Remaining C modules → `pp/lib`** (one branch each): `math`, `_struct`,
   `_string`, `_contextvars`, `_random`, `binascii`, `zlib`, `unicodedata`,
   `_locale`, `_typing`, `_codecs`, plus accelerator stand-ins `_csv`, `_json`,
   `_bisect`, `_pickle`, `_datetime`, `_hashlib`. Then a pp-native t-string
   `Template`/`Interpolation`.
6. The ranked to-do list in [BLOCKERS.md](BLOCKERS.md#to-do) (doctest
   `displayhook`, PEP 695 TypeVars, `FunctionType(closure=)`, `__index__`,
   mock context managers, guest-only tracebacks, recursion accounting, `dis`
   parity).

Later milestones: a pure-Python compiler (replacing host `compile()`), and a
pp-owned object model (needed for real weak references and `gc`).
