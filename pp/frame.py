"""Execution frames, modeled on CPython's _PyInterpreterFrame (and the PyFrameObject view)."""

import types

from pp.bytecode import DecodedCode, decode


class _Null:
    __slots__ = ()

    def __repr__(self):
        return "NULL"


NULL = _Null()  # re-exported as pp.vm.NULL (and pp.ceval.NULL)

# enum _frameowner (Include/internal/pycore_interpframe_structs.h)
FRAME_OWNED_BY_THREAD = 0
FRAME_OWNED_BY_GENERATOR = 1
FRAME_OWNED_BY_FRAME_OBJECT = 2
FRAME_OWNED_BY_INTERPRETER = 3

_names_cache: dict = {}  # id(code) -> (code, localsplusnames, first_free)
_CACHE_LIMIT = 4096      # both code caches hold their code strongly: bound them


def _trim(cache: dict) -> None:
    if len(cache) > _CACHE_LIMIT:
        del cache[next(iter(cache))]       # the oldest entry


def localsplus_names(code: types.CodeType) -> tuple:
    """Return (co_localsplusnames, index of the first free variable)."""
    entry = _names_cache.get(id(code))
    if entry is not None and entry[0] is code:
        return entry[1], entry[2]
    varnames = code.co_varnames
    cells = tuple(c for c in code.co_cellvars if c not in varnames)
    names = varnames + cells + code.co_freevars
    first_free = len(varnames) + len(cells)
    _names_cache[id(code)] = (code, names, first_free)
    _trim(_names_cache)
    return names, first_free


_code_info: dict = {}  # id(code) -> (code, DecodedCode, localsplusnames, first_free)


def _make_code_info(code: types.CodeType) -> tuple:
    names, first_free = localsplus_names(code)
    info = (code, decode(code), names, first_free)
    _code_info[id(code)] = info
    _trim(_code_info)
    return info


def _alias(name: str) -> property:
    """A CPython field name for a pp field (fields may be added, not renamed)."""
    def get(self):
        return getattr(self, name)

    def set(self, value):
        setattr(self, name, value)
    return property(get, set)


class Frame:
    """_PyInterpreterFrame. The CPython field names (`f_executable`, `f_funcobj`,
    `f_globals`, `f_builtins`, `f_locals`, `localsplus`, `stackpointer`,
    `instr_ptr`, `previous`, `owner`) are available next to pp's original ones."""

    f_executable = _alias("code")
    f_funcobj = _alias("func")
    f_globals = _alias("globals")
    f_builtins = _alias("builtins")
    f_locals = _alias("locals")
    instr_ptr = _alias("lasti")     # instruction currently executing (a byte offset)

    @property
    def stackpointer(self) -> int:
        return len(self.stack)

    __slots__ = ("code", "decoded", "globals", "builtins", "locals", "localsplusnames",
                 "first_free", "localsplus", "stack", "instr_offset", "lasti", "previous",
                 "func", "owner", "frame_obj", "return_value", "yielded", "yield_oparg",
                 "__weakref__")

    def __init__(self, code: types.CodeType, globals: dict, builtins: dict,
                 locals, previous: "Frame | None" = None, func=None):
        info = _code_info.get(id(code))
        if info is None or info[0] is not code:
            info = _make_code_info(code)
        self.code = code
        self.decoded = info[1]
        self.globals = globals
        self.builtins = builtins
        self.locals = locals
        names = self.localsplusnames = info[2]
        self.first_free = info[3]
        self.localsplus = [NULL] * len(names)
        self.stack: list = []
        self.instr_offset = 0
        self.lasti = 0          # offset of the instruction being executed (frame->instr_ptr)
        self.previous = previous
        self.func = func        # the Function being executed (f_funcobj), if any
        self.owner = FRAME_OWNED_BY_THREAD
        self.frame_obj = None   # the PyFrameObject view, once created
        self.return_value = None
        self.yielded = False    # set by YIELD_VALUE, cleared by RETURN_VALUE
        self.yield_oparg = 0

    def push(self, v):
        self.stack.append(v)

    def pop(self):
        return self.stack.pop()

    def popn(self, n: int) -> list:
        if n == 0:
            return []
        vals = self.stack[-n:]
        del self.stack[-n:]
        return vals

    def peek(self, n: int = 1):
        return self.stack[-n]

    def lineno(self) -> int | None:
        for start, end, line in self.code.co_lines():
            if start <= self.lasti < end:
                return line
        return self.code.co_firstlineno

    def fast_locals_dict(self) -> dict:
        """Snapshot of the fast locals (what locals() returns in a function)."""
        d = {}
        cellvars = self.code.co_cellvars
        for k, name in enumerate(self.localsplusnames):
            v = self.localsplus[k]
            if v is NULL:
                continue
            if k >= self.first_free or (name in cellvars and isinstance(v, types.CellType)):
                try:
                    v = v.cell_contents
                except ValueError:
                    continue
            d[name] = v
        return d


class PyFrameObject:
    """The Python-visible frame object: a view over an `_PyInterpreterFrame`."""
    __slots__ = ("f_frame", "__weakref__")

    def __init__(self, frame: Frame):
        self.f_frame = frame

    @property
    def f_back(self):
        prev = self.f_frame.previous
        return None if prev is None else _PyFrame_GetFrameObject(prev)

    @property
    def f_code(self):
        return self.f_frame.f_executable

    @property
    def f_globals(self):
        return self.f_frame.f_globals

    @property
    def f_builtins(self):
        return self.f_frame.f_builtins

    @property
    def f_locals(self):
        frame = self.f_frame
        return frame.f_locals if frame.f_locals is not None else frame.fast_locals_dict()

    @property
    def f_lineno(self):
        return self.f_frame.lineno()

    @property
    def f_lasti(self):
        return self.f_frame.instr_ptr

    f_trace = None

    def __getattr__(self, name):
        # pp-specific fields of the underlying _PyInterpreterFrame
        return getattr(self.f_frame, name)

    def __repr__(self):
        code = self.f_frame.f_executable
        return (f"<frame at {id(self):#x}, file {code.co_filename!r}, "
                f"line {self.f_lineno}, code {code.co_name}>")


def _PyFrame_GetFrameObject(frame: Frame) -> PyFrameObject:
    if frame.frame_obj is None:
        frame.frame_obj = PyFrameObject(frame)
    return frame.frame_obj


PyFrameObject.__name__ = PyFrameObject.__qualname__ = "frame"
PyFrameObject.__module__ = "builtins"
