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
- Milestone 3 regression fixes: per-type slot data in a VM-side weak table,
  CPython-style method cache, warnings through the guest `warnings` module.
- Pure-Python `_sre` (explicit-stack matcher, `re` entirely in Python) and
  accelerator stand-ins `_bisect`, `_datetime`, `_json`, `_csv`.
- Pure-Python `_struct` and `binascii`, and `tools/host_test.py`: runs
  CPython's Lib/test on host CPython with C modules swapped for their
  `pp/lib` versions (the fast loop for C-module work).
- Host-boundary import guard test (`tests/test_host_boundary.py`).
- Pure-Python `_collections` (deque, defaultdict, OrderedDict), `array`,
  `_weakref` and `gc` in `pp/lib` (weak refs never die; `gc.collect()` frees
  nothing; see BLOCKERS.md).
- Stdlib tracking: tiers 1–4 (54 modules) validated by CPython's Lib/test at
  tag v3.15.2, dashboard in `docs/dashboard.html`.
- Design rule: C modules are reimplemented in Python, limitations accepted
  (DESIGN.md, "C modules: reimplement, don't borrow").

## In progress

| Branch | What | Status |
|---|---|---|
| `impl/math` | Pure-Python `math` and `cmath` | in progress |
| `impl/random-string` | Pure-Python `_random` and `_string` | in progress |
| `impl/zlib` | Pure-Python `zlib` | in progress |

## Next

1. **Performance** of the interpreter loop (first attempt not merged):
   the milestone 3 ~2× slowdown and the `difflib`, `itertools`, `datetime`,
   `statistics` timeouts.
2. **Async opcodes** (parked; `impl/async` is pushed, last judge round FIX): unblocks `unittest`, `collections`, `contextlib`, `types` and everything
   that imports `asyncio` through `test.support`.
3. **Layout**: split `pp/` into `pp/vm/` (host code) and `pp/lib/` (guest
   code) once in-flight branches have merged.
4. **Remaining C modules → `pp/lib`** (one branch each): `math`,
   `_string`, `_contextvars`, `_random`, `zlib`, `unicodedata`,
   `_locale`, `_typing`, `_codecs`, plus accelerator stand-ins `_pickle` and
   `_hashlib`. Iterate with `tools/host_test.py --swap <mod>`. Then a pp-native t-string
   `Template`/`Interpolation`.
5. The ranked to-do list in [BLOCKERS.md](BLOCKERS.md#to-do) (doctest
   `displayhook`, PEP 695 TypeVars, `FunctionType(closure=)`, `__index__`,
   mock context managers, guest-only tracebacks, recursion accounting, `dis`
   parity).

Later milestones: a pure-Python compiler (replacing host `compile()`), and a
pp-owned object model (needed for real weak references and `gc`).

## Missing modules

What pp does not yet provide in pure Python, against Python 3.15's
`sys.stdlib_module_names`. The importer is in `pp/importer.py`; pure-Python
replacements live in `pp/lib/`. Already reimplemented: `_collections`,
`array`, `_weakref`, `gc`, `itertools`, `_sre`, `_bisect`, `_datetime`,
`_json`, `_csv`, `_struct`, `binascii`.

### C modules still borrowed from the host (to reimplement)

`HOST_MODULES_TEMPORARY`, each one tracked debt:

| Module | Used by | Status |
|---|---|---|
| `math` | `fractions`, `statistics`, `random`, `decimal`, ... | |
| `_string` | `string.Formatter` | |
| `_contextvars` | `contextvars`, `asyncio`, `decimal` | |
| `_random` | `random` | |
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

Tracked today: 54 modules (see [STATUS.md](STATUS.md)). Untracked public
modules, roughly in the order they are worth adding:

- **Core**: `io`, `os`, `pathlib`, `struct`, `pickle`, `codecs`,
  `numbers`, `contextvars`, `importlib`, `linecache`, `tokenize`, `token`,
  `opcode`, `stat`, `genericpath`, `annotationlib`, `logging`, `doctest`,
  `timeit`, `locale`, `gettext`, `signal`, `threading`, `asyncio`.
- **Text and data**: `email`, `mimetypes`, `quopri`, `stringprep`,
  `pickletools`, `plistlib`, `xml`,
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
