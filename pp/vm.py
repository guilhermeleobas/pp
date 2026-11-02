"""The eval loop and opcode handlers. Spec: CPython 3.15 Python/bytecodes.c."""

import builtins as _builtins
import types

import opcode as _opcode

from pp.bytecode import Instruction, compile_source
from pp.errors import UnimplementedOpcode
from pp.frame import Frame


class _Null:
    __slots__ = ()

    def __repr__(self):
        return "NULL"


NULL = _Null()
_EXIT = object()  # returned by a handler to leave the eval loop

CO_OPTIMIZED = 0x1


# --- BINARY_OP table (index = oparg, order from opcode._nb_ops) ---

def _iadd(a, b): a += b; return a
def _iand(a, b): a &= b; return a
def _ifloordiv(a, b): a //= b; return a
def _ilshift(a, b): a <<= b; return a
def _imatmul(a, b): a @= b; return a
def _imul(a, b): a *= b; return a
def _imod(a, b): a %= b; return a
def _ior(a, b): a |= b; return a
def _ipow(a, b): a **= b; return a
def _irshift(a, b): a >>= b; return a
def _isub(a, b): a -= b; return a
def _itruediv(a, b): a /= b; return a
def _ixor(a, b): a ^= b; return a


_NB_FUNCS = {
    "NB_ADD": lambda a, b: a + b,
    "NB_AND": lambda a, b: a & b,
    "NB_FLOOR_DIVIDE": lambda a, b: a // b,
    "NB_LSHIFT": lambda a, b: a << b,
    "NB_MATRIX_MULTIPLY": lambda a, b: a @ b,
    "NB_MULTIPLY": lambda a, b: a * b,
    "NB_REMAINDER": lambda a, b: a % b,
    "NB_OR": lambda a, b: a | b,
    "NB_POWER": lambda a, b: a ** b,
    "NB_RSHIFT": lambda a, b: a >> b,
    "NB_SUBTRACT": lambda a, b: a - b,
    "NB_TRUE_DIVIDE": lambda a, b: a / b,
    "NB_XOR": lambda a, b: a ^ b,
    "NB_INPLACE_ADD": _iadd,
    "NB_INPLACE_AND": _iand,
    "NB_INPLACE_FLOOR_DIVIDE": _ifloordiv,
    "NB_INPLACE_LSHIFT": _ilshift,
    "NB_INPLACE_MATRIX_MULTIPLY": _imatmul,
    "NB_INPLACE_MULTIPLY": _imul,
    "NB_INPLACE_REMAINDER": _imod,
    "NB_INPLACE_OR": _ior,
    "NB_INPLACE_POWER": _ipow,
    "NB_INPLACE_RSHIFT": _irshift,
    "NB_INPLACE_SUBTRACT": _isub,
    "NB_INPLACE_TRUE_DIVIDE": _itruediv,
    "NB_INPLACE_XOR": _ixor,
    "NB_SUBSCR": lambda a, b: a[b],
}
BINARY_OPS = tuple(_NB_FUNCS[name] for name, _ in _opcode._nb_ops)

# COMPARE_OP: op = oparg >> 5, indexes opcode.cmp_op ('<', '<=', '==', '!=', '>', '>=')
COMPARE_OPS = (
    lambda a, b: a < b,
    lambda a, b: a <= b,
    lambda a, b: a == b,
    lambda a, b: a != b,
    lambda a, b: a > b,
    lambda a, b: a >= b,
)

# CONVERT_VALUE: FVC_STR=1, FVC_REPR=2, FVC_ASCII=3
CONVERSIONS = (None, str, repr, ascii)

COMMON_CONSTANTS = tuple(_opcode._common_constants)


def _builtins_dict(globals: dict) -> dict:
    b = globals.get("__builtins__", _builtins)
    if isinstance(b, types.ModuleType):
        b = b.__dict__
    return b


def _name_error(name: str) -> NameError:
    return NameError(f"name '{name}' is not defined", name=name)


def _unpack(seq, before: int, after: int | None) -> list:
    """Return the unpacked values in source order (after=None: exact count)."""
    try:
        it = iter(seq)
    except TypeError:
        if not hasattr(type(seq), "__iter__") and not hasattr(type(seq), "__getitem__"):
            raise TypeError(f"cannot unpack non-iterable {type(seq).__name__} object") from None
        raise
    if after is None:
        vals = []
        for v in it:
            if len(vals) == before:
                try:
                    n = len(seq)
                except TypeError:
                    raise ValueError(f"too many values to unpack (expected {before})") from None
                raise ValueError(f"too many values to unpack (expected {before}, got {n})")
            vals.append(v)
        if len(vals) < before:
            raise ValueError(f"not enough values to unpack (expected {before}, got {len(vals)})")
        return vals
    vals = list(it)
    if len(vals) < before + after:
        raise ValueError(
            f"not enough values to unpack (expected at least {before + after}, got {len(vals)})")
    middle = vals[before:len(vals) - after]
    return vals[:before] + [middle] + vals[len(vals) - after:]


class VirtualMachine:
    def __init__(self):
        self.frame: Frame | None = None
        self.dispatch = {}
        for name in _opcode.opmap:
            handler = getattr(self, name, None)
            if handler is not None:
                self.dispatch[name] = handler

    # --- entry points ---

    def run_code(self, code: types.CodeType, globals: dict | None = None) -> object:
        if globals is None:
            globals = {"__name__": "__main__", "__builtins__": _builtins}
        globals.setdefault("__builtins__", _builtins)
        locals = None if code.co_flags & CO_OPTIMIZED else globals
        frame = Frame(code, globals, _builtins_dict(globals), locals, self.frame)
        return self.run_frame(frame)

    def run_frame(self, frame: Frame) -> object:
        self.frame = frame
        try:
            decoded = frame.decoded
            dispatch = self.dispatch
            while True:
                instr = decoded.at(frame.instr_offset)
                frame.instr_offset = instr.next_offset
                handler = dispatch.get(instr.opname)
                if handler is None:
                    raise UnimplementedOpcode(instr.opname)
                if handler(frame, instr) is _EXIT:
                    return frame.return_value
        finally:
            self.frame = frame.previous

    # --- no-ops ---

    def RESUME(self, f, i): pass
    def NOP(self, f, i): pass
    def NOT_TAKEN(self, f, i): pass
    def EXTENDED_ARG(self, f, i): pass  # the decoder already folds it into the next arg

    # --- constants and names ---

    def LOAD_CONST(self, f, i):
        f.push(f.code.co_consts[i.arg])

    def LOAD_SMALL_INT(self, f, i):
        f.push(i.arg)

    def LOAD_COMMON_CONSTANT(self, f, i):
        f.push(COMMON_CONSTANTS[i.arg])

    def LOAD_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        if f.locals is None:
            raise SystemError(f"no locals when loading {name!r}")
        for ns in (f.locals, f.globals, f.builtins):
            try:
                f.push(ns[name])
                return
            except KeyError:
                pass
        raise _name_error(name)

    def STORE_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        if f.locals is None:
            raise SystemError(f"no locals found when storing {name!r}")
        f.locals[name] = f.pop()

    def DELETE_NAME(self, f, i):
        name = f.code.co_names[i.arg]
        if f.locals is None:
            raise SystemError(f"no locals when deleting {name!r}")
        try:
            del f.locals[name]
        except KeyError:
            raise _name_error(name) from None

    def LOAD_GLOBAL(self, f, i):
        name = f.code.co_names[i.arg >> 1]
        if name in f.globals:
            v = f.globals[name]
        elif name in f.builtins:
            v = f.builtins[name]
        else:
            raise _name_error(name)
        f.push(v)
        if i.arg & 1:
            f.push(NULL)

    def STORE_GLOBAL(self, f, i):
        f.globals[f.code.co_names[i.arg]] = f.pop()

    # --- stack manipulation ---

    def PUSH_NULL(self, f, i):
        f.push(NULL)

    def POP_TOP(self, f, i):
        f.pop()

    def COPY(self, f, i):
        f.push(f.stack[-i.arg])

    def SWAP(self, f, i):
        s = f.stack
        s[-1], s[-i.arg] = s[-i.arg], s[-1]

    # --- calls ---

    def _call(self, f, nargs, kwnames):
        args = f.popn(nargs)
        self_or_null = f.pop()
        callable = f.pop()
        if self_or_null is not NULL:
            args.insert(0, self_or_null)
        if kwnames:
            npos = len(args) - len(kwnames)
            kwargs = dict(zip(kwnames, args[npos:]))
            res = callable(*args[:npos], **kwargs)
        else:
            res = callable(*args)
        f.push(res)

    def CALL(self, f, i):
        self._call(f, i.arg, ())

    def CALL_KW(self, f, i):
        kwnames = f.pop()
        self._call(f, i.arg, kwnames)

    # --- operators ---

    def BINARY_OP(self, f, i):
        rhs = f.pop()
        lhs = f.pop()
        f.push(BINARY_OPS[i.arg](lhs, rhs))

    def BINARY_SLICE(self, f, i):
        stop = f.pop()
        start = f.pop()
        container = f.pop()
        f.push(container[start:stop])

    def STORE_SLICE(self, f, i):
        stop = f.pop()
        start = f.pop()
        container = f.pop()
        v = f.pop()
        container[start:stop] = v

    def STORE_SUBSCR(self, f, i):
        sub = f.pop()
        container = f.pop()
        v = f.pop()
        container[sub] = v

    def DELETE_SUBSCR(self, f, i):
        sub = f.pop()
        container = f.pop()
        del container[sub]

    def UNARY_NEGATIVE(self, f, i):
        f.push(-f.pop())

    def UNARY_INVERT(self, f, i):
        f.push(~f.pop())

    def UNARY_NOT(self, f, i):
        f.push(not f.pop())

    def TO_BOOL(self, f, i):
        f.push(bool(f.pop()))

    def COMPARE_OP(self, f, i):
        right = f.pop()
        left = f.pop()
        res = COMPARE_OPS[i.arg >> 5](left, right)
        if i.arg & 16:
            res = bool(res)
        f.push(res)

    def IS_OP(self, f, i):
        right = f.pop()
        left = f.pop()
        f.push((left is right) ^ bool(i.arg))

    def CONTAINS_OP(self, f, i):
        right = f.pop()
        left = f.pop()
        f.push((left in right) ^ bool(i.arg))

    # --- control flow ---

    def POP_JUMP_IF_TRUE(self, f, i):
        if f.pop():
            f.instr_offset = i.jump_target

    def POP_JUMP_IF_FALSE(self, f, i):
        if not f.pop():
            f.instr_offset = i.jump_target

    def POP_JUMP_IF_NONE(self, f, i):
        if f.pop() is None:
            f.instr_offset = i.jump_target

    def POP_JUMP_IF_NOT_NONE(self, f, i):
        if f.pop() is not None:
            f.instr_offset = i.jump_target

    def JUMP_FORWARD(self, f, i):
        f.instr_offset = i.jump_target

    def JUMP_BACKWARD(self, f, i):
        f.instr_offset = i.jump_target

    def JUMP_BACKWARD_NO_INTERRUPT(self, f, i):
        f.instr_offset = i.jump_target

    def RETURN_VALUE(self, f, i):
        f.return_value = f.pop()
        return _EXIT

    # --- iteration ---

    def GET_ITER(self, f, i):
        f.push(iter(f.pop()))
        f.push(NULL)  # index_or_null: always NULL in the prototype

    def FOR_ITER(self, f, i):
        it = f.stack[-2]
        try:
            f.push(next(it))
        except StopIteration:
            # Exhausted: jump past the END_FOR at the target, leaving iter/null for POP_ITER.
            f.instr_offset = i.jump_target + 2

    def END_FOR(self, f, i):
        f.pop()

    def POP_ITER(self, f, i):
        f.pop()
        f.pop()

    # --- building containers ---

    def BUILD_TUPLE(self, f, i):
        f.push(tuple(f.popn(i.arg)))

    def BUILD_LIST(self, f, i):
        f.push(f.popn(i.arg))

    def BUILD_SET(self, f, i):
        f.push(set(f.popn(i.arg)))

    def BUILD_MAP(self, f, i):
        vals = f.popn(2 * i.arg)
        f.push({vals[k]: vals[k + 1] for k in range(0, len(vals), 2)})

    def BUILD_SLICE(self, f, i):
        f.push(slice(*f.popn(i.arg)))

    def BUILD_STRING(self, f, i):
        f.push("".join(f.popn(i.arg)))

    def LIST_APPEND(self, f, i):
        v = f.pop()
        f.stack[-i.arg].append(v)

    def LIST_EXTEND(self, f, i):
        iterable = f.pop()
        try:
            f.stack[-i.arg].extend(iterable)
        except TypeError:
            if not hasattr(type(iterable), "__iter__") and not hasattr(type(iterable), "__getitem__"):
                raise TypeError(
                    f"Value after * must be an iterable, not {type(iterable).__name__}") from None
            raise

    def SET_ADD(self, f, i):
        v = f.pop()
        f.stack[-i.arg].add(v)

    def SET_UPDATE(self, f, i):
        iterable = f.pop()
        f.stack[-i.arg].update(iterable)

    def MAP_ADD(self, f, i):
        value = f.pop()
        key = f.pop()
        f.stack[-i.arg][key] = value

    def DICT_UPDATE(self, f, i):
        update = f.pop()
        if not hasattr(update, "keys"):
            raise TypeError(f"'{type(update).__name__}' object is not a mapping")
        f.stack[-i.arg].update(update)

    def UNPACK_SEQUENCE(self, f, i):
        vals = _unpack(f.pop(), i.arg, None)
        f.stack.extend(reversed(vals))

    def UNPACK_EX(self, f, i):
        vals = _unpack(f.pop(), i.arg & 0xFF, i.arg >> 8)
        f.stack.extend(reversed(vals))

    # --- formatting ---

    def FORMAT_SIMPLE(self, f, i):
        v = f.pop()
        f.push(v if type(v) is str else format(v))

    def FORMAT_WITH_SPEC(self, f, i):
        spec = f.pop()
        v = f.pop()
        f.push(format(v, spec))

    def CONVERT_VALUE(self, f, i):
        f.push(CONVERSIONS[i.arg](f.pop()))

    # --- attributes ---

    def LOAD_ATTR(self, f, i):
        owner = f.pop()
        attr = getattr(owner, f.code.co_names[i.arg >> 1])
        f.push(attr)
        if i.arg & 1:
            # Method form: CPython may push (unbound method, self); pushing the
            # bound attribute plus NULL is equivalent for CALL.
            f.push(NULL)

    def STORE_ATTR(self, f, i):
        owner = f.pop()
        v = f.pop()
        setattr(owner, f.code.co_names[i.arg], v)

    def DELETE_ATTR(self, f, i):
        delattr(f.pop(), f.code.co_names[i.arg])


def run_source(source: str, filename: str = "<string>", globals: dict | None = None) -> dict:
    if globals is None:
        globals = {"__name__": "__main__", "__builtins__": _builtins}
    code = compile_source(source, filename, "exec")
    VirtualMachine().run_code(code, globals)
    return globals


def run_file(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    globals = {"__name__": "__main__", "__builtins__": _builtins, "__file__": path}
    return run_source(source, path, globals)
