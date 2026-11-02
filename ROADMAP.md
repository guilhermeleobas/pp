# Roadmap

Where pp stands and what comes next. Per-module numbers are in
[STATUS.md](STATUS.md); blockers and the ranked to-do list are in
[BLOCKERS.md](BLOCKERS.md); the process is in [WORKFLOW.md](WORKFLOW.md).

Branches below are pushed to GitHub.

## Done (on `main`)

- Milestone 1: bytecode decoding, frames, eval loop for module-level code.
- Milestone 2: functions, classes, exceptions, generators, importer, `pp/lib`,
  `match`.
- Milestone 3: CPython-mirrored type slots and abstract layer
  (`typeobject`, `abstract`, `call`, `ceval`, `genobject`, `funcobject`).
- Host-boundary import guard test (`tests/test_host_boundary.py`).
- Pure-Python `_collections` (deque, defaultdict, OrderedDict), `array`,
  `_weakref` and `gc` in `pp/lib` (weak refs never die; `gc.collect()` frees
  nothing; see BLOCKERS.md).
- Stdlib tracking: tiers 1–4 (49 modules) validated by CPython's Lib/test at
  tag v3.15.2, dashboard in `docs/dashboard.html`.
- Design rule: C modules are reimplemented in Python, limitations accepted
  (DESIGN.md, "C modules: reimplement, don't borrow").

## In review (not merged)

| Branch | What | Review | Gate | Next step |
|---|---|---|---|---|
| `impl/m3-fixes` | Milestone 3 regression fixes; CPython-style version-tag type cache; no new host imports; warnings go through the guest `warnings` | round 3: merge (storage hack aside) | round 3: no drops except `difflib` timeout (perf) | round 4: slot data in a VM-side weak table; then judge |
| `impl/sre` | Pure-Python `_sre` regex engine (`re` fully in Python) | merge, with a limit: `RecursionError` on group repeats over ~600 chars | clean vs `main` | rebase after `impl/m3-fixes` (conflicts); explicit-stack matcher on `impl/sre-stack` (9bf8304, test_re 160/168) |

Merge order: `impl/m3-fixes` → `impl/sre` (rebased) → `impl/sre-stack`;
regenerate the dashboard after each.

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

## Missing modules

What pp does not yet provide in pure Python, against Python 3.15's
`sys.stdlib_module_names`. The importer is in `pp/importer.py`; pure-Python
replacements live in `pp/lib/`. Already reimplemented: `_collections`,
`array`, `_weakref`, `gc`, `itertools`.

### C modules still borrowed from the host (to reimplement)

`HOST_MODULES_TEMPORARY`, each one tracked debt:

| Module | Used by | Status |
|---|---|---|
| `_sre` | `re` and everything using regexes | in review (`impl/sre-stack`) |
| `math` | `fractions`, `statistics`, `random`, `decimal`, ... | |
| `_struct` | `struct`, `pickle`, `zipfile`, `base64`, ... | |
| `_string` | `string.Formatter` | |
| `_contextvars` | `contextvars`, `asyncio`, `decimal` | |
| `_random` | `random` | |
| `binascii` | `base64`, `zipfile`, `email` | |
| `zlib` | `gzip`, `zipfile` | |
| `unicodedata` | `unicodedata`, normalization in `str` helpers | |
| `_locale` | `locale` | |
| `select`, `fcntl`, `_posixsubprocess`, `_socket`, `resource`, `faulthandler` | `subprocess`, `socket`, `test.support` | OS access; may move to the permanent boundary |

### Host boundary (stays on the host)

`HOST_MODULES_PERMANENT`: the compiler (`_ast`, `_tokenize`, `_opcode`,
`marshal`), OS and runtime access (`posix`, `_io`, `time`, `errno`, `_signal`,
`_thread`, `atexit`, `_imp`), `_codecs`, `_typing` and `_warnings` (moving to
pure Python), plus `sys` and `builtins`, which the VM serves itself.

### C-only modules with no pp version (import fails under pp)

| Area | Modules | Blocks |
|---|---|---|
| Accelerators imported directly by tests | `_bisect`, `_json`, `_csv`, `_datetime` | `bisect`, `json`, `csv`, `types` tests (in progress: `impl/accel`) |
| Hashing | `_hashlib`, `_md5`, `_sha1`, `_sha2`, `_sha3`, `_blake2`, `_hmac` | `hashlib`, `hmac`, `secrets`, `random` seeding by bytes |
| Compression | `_bz2`, `_lzma`, `_zstd` (and borrowed `zlib`) | `bz2`, `lzma`, `compression.zstd`, `tarfile`, `zipfile` |
| XML | `pyexpat`, `_elementtree` (Python fallback exists) | `xml.parsers.expat`, `xml.dom.minidom`, `plistlib` |
| Numbers | `cmath`, `_math_integer`, `_decimal` (Python fallback `_pydecimal` exists), `_statistics` (fallback exists) | `cmath` |
| CJK codecs | `_multibytecodec`, `_codecs_cn`, `_codecs_hk`, `_codecs_iso2022`, `_codecs_jp`, `_codecs_kr`, `_codecs_tw` | those encodings |
| Async and concurrency | `_asyncio` (fallback exists), `_queue` (fallback exists), `_multiprocessing`, `_posixshmem`, `_interpreters`, `_interpchannels`, `_interpqueues` | `multiprocessing`, `concurrent.interpreters` (also blocked on async opcodes) |
| Introspection and tooling | `_lsprof`, `_tracemalloc`, `_symtable`, `_suggestions`, `_remote_debugging`, `_sysconfig` | `cProfile`, `tracemalloc`, `symtable`, error-name suggestions |
| Databases and storage | `_sqlite3`, `_dbm`, `_gdbm`, `mmap` | `sqlite3`, `dbm`, `mmap` |
| Networking and crypto | `_ssl` | `ssl`, HTTPS in `urllib`/`http` |
| OS and terminal | `grp`, `pwd`, `termios`, `syslog`, `readline`, `_curses`, `_curses_panel` | `getpass`, `tty`, `curses`, interactive input |
| GUI and FFI | `_tkinter`, `_ctypes` | `tkinter`, `turtle`, `ctypes` (likely out of scope) |
| Platform-specific | `nt`, `msvcrt`, `winreg`, `winsound`, `_winapi`, `_wmi`, `_overlapped` (Windows), `_scproxy` (macOS) | out of scope for now |

Accelerators that pp blocks on purpose, so the pure-Python fallback runs
(not missing, listed for completeness): `_abc`, `_functools`, `_heapq`,
`_operator`, `_pickle`, `_stat`, `_types`, `_uuid`, `_zoneinfo`,
`_frozen_importlib`, `_frozen_importlib_external`.

### Pure-Python stdlib modules not yet tracked on the dashboard

Tracked today: 51 modules (see [STATUS.md](STATUS.md)). Untracked public
modules, roughly in the order they are worth adding:

- **Core**: `re`, `io`, `os`, `pathlib`, `struct`, `pickle`, `codecs`,
  `numbers`, `contextvars`, `importlib`, `linecache`, `tokenize`, `token`,
  `opcode`, `stat`, `genericpath`, `annotationlib`, `logging`, `doctest`,
  `timeit`, `locale`, `gettext`, `signal`, `threading`, `asyncio`.
- **Text and data**: `email`, `mimetypes`, `quopri`, `stringprep`,
  `pickletools`, `plistlib`, `xml`, `csv` (tracked; blocked on `_csv`),
  `uuid`, `zoneinfo`, `secrets`, `hashlib`, `hmac`.
- **Files and archives**: `shutil`, `tempfile`, `filecmp`, `fileinput`,
  `glob` (tracked), `zipfile`, `tarfile`, `gzip`, `bz2`, `lzma`,
  `compression`, `zipimport`, `zipapp`, `shelve`, `dbm`, `mailbox`, `netrc`.
- **Tools**: `cmd`, `code`, `codeop`, `getopt`, `pdb`, `bdb`, `trace`,
  `profile`, `cProfile`, `pstats`, `pyclbr`, `pydoc`, `tabnanny`,
  `py_compile`, `compileall`, `modulefinder`, `pkgutil`, `runpy`, `sched`,
  `symtable`, `tracemalloc`, `rlcompleter`, `site`, `sysconfig`, `platform`.
- **Processes and networking**: `subprocess`, `selectors`, `socket`,
  `socketserver`, `ssl`, `http`, `urllib`, `ftplib`, `poplib`, `imaplib`,
  `smtplib`, `xmlrpc`, `wsgiref`, `webbrowser`, `multiprocessing`,
  `concurrent`, `pty`, `tty`, `getpass`.
- **Probably out of scope**: `tkinter`, `turtle`, `turtledemo`, `idlelib`,
  `curses`, `ctypes`, `sqlite3`, `venv`, `ensurepip`, `ntpath`,
  `nturl2path`, `wave`, `antigravity`, `this`.
