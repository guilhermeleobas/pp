"""Generators, coroutines and async generators, modeled on Objects/genobject.c.

`PyGenObject` carries CPython's fields (`gi_frame_state`, `gi_exc_state`,
`gi_name`, `gi_qualname`, `gi_iframe`). Where C returns NULL with an exception
set, functions here raise; `PYGEN_NEXT` / `PYGEN_RETURN` results are returned as
`(kind, value)`.
"""

import types

from pp.errors import (PyErr_GivenExceptionMatches, PyExceptionClass_Check,
                       _PyErr_ChainStackItem, _PyErr_Clear, _PyErr_SetRaisedException,
                       _PyErr_StackItem, _PyExceptionInstance_Check, _PyThreadState_GET)
from pp.frame import (FRAME_OWNED_BY_GENERATOR, NULL, _PyFrame_GetFrameObject)
from pp.typeobject import register_static_slots

# PyFrameState (Include/internal/pycore_frame.h)
FRAME_CREATED = 0
FRAME_SUSPENDED = 1
FRAME_SUSPENDED_YIELD_FROM = 2
FRAME_SUSPENDED_YIELD_FROM_LOCKED = 3
FRAME_EXECUTING = 4
FRAME_CLEARED = 5

PYGEN_RETURN = 0
PYGEN_NEXT = 1

_tb_get = BaseException.__dict__["__traceback__"].__get__

NON_INIT_CORO_MSG = "can't send non-None value to a just-started coroutine"


def FRAME_STATE_SUSPENDED(state: int) -> bool:
    return FRAME_SUSPENDED <= state <= FRAME_SUSPENDED_YIELD_FROM_LOCKED


def FRAME_STATE_FINISHED(state: int) -> bool:
    return state == FRAME_CLEARED


class PyGenObject:
    _kind = "generator"

    # `__name__`/`__qualname__` are slots (as on the old Generator): gi_name and
    # gi_qualname are views of them.
    __slots__ = ("gi_frame_state", "gi_exc_state", "__name__", "__qualname__", "gi_iframe",
                 "gi_tstate", "gi_code", "__weakref__")

    def __init__(self, frame, func, tstate):
        self.gi_iframe = frame
        self.gi_code = frame.f_executable
        frame.owner = FRAME_OWNED_BY_GENERATOR
        self.__name__ = func.__name__ if func is not None else frame.code.co_name
        self.__qualname__ = func.__qualname__ if func is not None else frame.code.co_qualname
        self.gi_exc_state = _PyErr_StackItem()
        self.gi_frame_state = FRAME_CREATED
        self.gi_tstate = tstate

    # --- introspection (genobject.c getset/member tables) ---

    @property
    def gi_frame(self):
        if self.gi_frame_state == FRAME_CLEARED:
            return None
        return _PyFrame_GetFrameObject(self.gi_iframe)

    @property
    def gi_running(self):
        return self.gi_frame_state == FRAME_EXECUTING

    @property
    def gi_suspended(self):
        return FRAME_STATE_SUSPENDED(self.gi_frame_state)

    @property
    def gi_yieldfrom(self):
        if self.gi_frame_state == FRAME_SUSPENDED_YIELD_FROM:
            return self.gi_iframe.stack[-2]
        return None

    @property
    def gi_state(self):
        return gen_get_state(self)

    gi_name = property(lambda self: self.__name__)
    gi_qualname = property(lambda self: self.__qualname__)

    def __repr__(self):
        return f"<{self._kind} object {self.gi_qualname} at {id(self):#x}>"

    # --- protocol: methods the host (and VM code via the type slots) can call ---

    def __iter__(self):
        return self

    def __next__(self):
        return gen_iternext(self)

    def send(self, arg, /):
        return gen_send(self, arg)

    def throw(self, typ, val=None, tb=None, /):
        return gen_throw(self, typ, val, tb)

    def close(self):
        return gen_close(self)

    def __del__(self):
        if FRAME_STATE_SUSPENDED(self.gi_frame_state):
            err = None
            try:
                self.close()
            except BaseException as e:
                err = e


def gen_get_state(gen) -> str:
    state = gen.gi_frame_state
    if state == FRAME_CREATED:
        return "GEN_CREATED"
    if FRAME_STATE_SUSPENDED(state):
        return "GEN_SUSPENDED"
    if state == FRAME_EXECUTING:
        return "GEN_RUNNING"
    return "GEN_CLOSED"


class PyCoroObject(PyGenObject):
    """Minimal coroutine object (async/await execution is out of scope)."""
    _kind = "coroutine"
    __slots__ = ()

    @property
    def cr_frame(self):
        return self.gi_frame

    @property
    def cr_code(self):
        return self.gi_code

    @property
    def cr_running(self):
        return self.gi_running

    def __await__(self):
        return self

    def __iter__(self):
        raise TypeError("'coroutine' object is not iterable")

    def __next__(self):
        raise TypeError("'coroutine' object is not an iterator")

    def __del__(self):
        pass


class PyAsyncGenObject(PyGenObject):
    """Minimal async generator object (async iteration is out of scope)."""
    _kind = "async_generator"
    __slots__ = ()

    @property
    def ag_frame(self):
        return self.gi_frame

    @property
    def ag_code(self):
        return self.gi_code

    def __iter__(self):
        raise TypeError("'async_generator' object is not iterable")

    def __next__(self):
        raise TypeError("'async_generator' object is not an iterator")

    def __del__(self):
        pass


for _cls, _name in ((PyGenObject, "generator"), (PyCoroObject, "coroutine"),
                    (PyAsyncGenObject, "async_generator")):
    _cls.__name__ = _cls.__qualname__ = _name
    _cls.__module__ = "builtins"
del _cls, _name


def PyGen_CheckExact(o) -> bool:
    return type(o) is PyGenObject


def PyCoro_CheckExact(o) -> bool:
    return type(o) is PyCoroObject


def PyAsyncGen_CheckExact(o) -> bool:
    return type(o) is PyAsyncGenObject


def _gen_raise_already_executing_error(gen):
    if PyCoro_CheckExact(gen):
        return ValueError("coroutine already executing")
    if PyAsyncGen_CheckExact(gen):
        return ValueError("async generator already executing")
    return ValueError("generator already executing")


def _clear_gen_frame(gen) -> None:
    gen.gi_iframe = None


def gen_send_ex2(gen, arg, exc=None):
    """Resume the (EXECUTING) generator with `arg`, or by throwing `exc` into it.
    -> (PYGEN_NEXT, yielded value) or (PYGEN_RETURN, return value)."""
    tstate = gen.gi_tstate
    frame = gen.gi_iframe

    # Push arg onto the frame's value stack
    frame.stack.append(arg)

    prev_exc_info = tstate.exc_info
    gen.gi_exc_state.previous_item = prev_exc_info
    tstate.exc_info = gen.gi_exc_state

    if exc is not None:
        _PyErr_ChainStackItem(tstate, exc)

    err = None
    result = NULL
    try:
        result = tstate.eval_frame(frame, exc)
    except BaseException as e:
        err = e
    tstate.exc_info = prev_exc_info
    gen.gi_exc_state.previous_item = None
    if err is not None:
        # The generator frame is cleared when an exception propagates out of it.
        gen.gi_frame_state = FRAME_CLEARED
        _clear_gen_frame(gen)
        raise err

    if frame.yielded:
        # YIELD_VALUE: suspended (oparg 1 means a `yield from` / await in progress).
        gen.gi_frame_state = FRAME_SUSPENDED_YIELD_FROM if frame.yield_oparg == 1 \
            else FRAME_SUSPENDED
        return PYGEN_NEXT, result

    # The generator just returned (as opposed to yielding).
    gen.gi_frame_state = FRAME_CLEARED
    _clear_gen_frame(gen)
    return PYGEN_RETURN, result


def gen_send_ex(gen, arg, called_from_iternext=False):
    """-> (kind, value). `arg` is None for next(). Errors raise."""
    frame_state = gen.gi_frame_state
    if frame_state == FRAME_CREATED and arg is not None:
        if PyCoro_CheckExact(gen):
            raise TypeError(NON_INIT_CORO_MSG)
        if PyAsyncGen_CheckExact(gen):
            raise TypeError("can't send non-None value to a just-started async generator")
        raise TypeError("can't send non-None value to a just-started generator")
    if frame_state == FRAME_EXECUTING:
        raise _gen_raise_already_executing_error(gen)
    if FRAME_STATE_FINISHED(frame_state):
        if PyCoro_CheckExact(gen):
            # `gen` is an exhausted coroutine: raise an error
            raise RuntimeError("cannot reuse already awaited coroutine")
        if not called_from_iternext:
            # `gen` is an exhausted generator: only return a value if called from send().
            return PYGEN_RETURN, None
        raise StopIteration
    gen.gi_frame_state = FRAME_EXECUTING
    return gen_send_ex2(gen, arg, None)


def _gen_set_stop_iteration(gen, result):
    if PyAsyncGen_CheckExact(gen):
        raise StopAsyncIteration if result is None else StopAsyncIteration(result)
    if result is None:
        raise StopIteration
    raise StopIteration(result)


def gen_iternext(gen):
    kind, result = gen_send_ex(gen, None, True)
    if kind == PYGEN_RETURN:
        if result is not None:
            raise StopIteration(result)
        raise StopIteration
    return result


def gen_send(gen, arg):
    kind, result = gen_send_ex(gen, arg)
    if kind == PYGEN_RETURN:
        _gen_set_stop_iteration(gen, result)
    return result


def gen_am_send(gen, arg):
    """am_send: `PyIter_Send` of a generator or coroutine (called by SEND)."""
    return gen_send_ex(gen, arg)


def gen_close_iter(yf) -> None:
    if PyGen_CheckExact(yf) or PyCoro_CheckExact(yf):
        gen_close(yf)
        return
    from pp.object import PyObject_GetOptionalAttr
    from pp.call import PyObject_CallNoArgs
    meth = PyObject_GetOptionalAttr(yf, "close")
    if meth is not NULL:
        PyObject_CallNoArgs(meth)


def gen_close(gen):
    frame_state = gen.gi_frame_state
    if frame_state == FRAME_CREATED:
        gen.gi_frame_state = FRAME_CLEARED
        _clear_gen_frame(gen)
        return None
    if FRAME_STATE_FINISHED(frame_state):
        return None
    if frame_state == FRAME_EXECUTING:
        raise _gen_raise_already_executing_error(gen)

    gen.gi_frame_state = FRAME_EXECUTING
    frame = gen.gi_iframe
    err = None
    if frame_state == FRAME_SUSPENDED_YIELD_FROM:
        yf = frame.stack[-2]
        try:
            gen_close_iter(yf)
        except BaseException as e:
            err = e
        if err is not None:
            _PyErr_Clear(_PyThreadState_GET())
    if err is not None:
        # gen_close_iter failed: throw that error into the generator instead.
        exc = err
    else:
        exc = GeneratorExit()

    caught = None
    kind = result = None
    try:
        kind, result = gen_send_ex2(gen, None, exc)
    except GeneratorExit as e:
        caught = e
    if caught is not None:
        _PyErr_Clear(_PyThreadState_GET())      # ignore this error
        return None
    if kind == PYGEN_RETURN:
        # the generator returned a value while closing
        return result
    if PyCoro_CheckExact(gen):
        raise RuntimeError("coroutine ignored GeneratorExit")
    if PyAsyncGen_CheckExact(gen):
        raise RuntimeError("async generator ignored GeneratorExit")
    raise RuntimeError("generator ignored GeneratorExit")


def gen_set_exception(typ, val, tb):
    """Build the exception instance to throw (the PyErr_NormalizeException part)."""
    if tb is not None and not isinstance(tb, types.TracebackType):
        raise TypeError("throw() third argument must be a traceback object")
    if PyExceptionClass_Check(typ):
        if val is not None and _PyExceptionInstance_Check(val) \
                and PyErr_GivenExceptionMatches(val, typ):
            exc = val
        elif val is None:
            exc = typ()
        elif type(val) is tuple:
            exc = typ(*val)
        else:
            exc = typ(val)
    elif _PyExceptionInstance_Check(typ):
        # Raising an instance. The value should be a dummy.
        if val is not None:
            raise TypeError("instance exception may not have a separate value")
        exc = typ
    else:
        # Not something you can raise. throw() fails.
        raise TypeError("exceptions must be classes or instances deriving from "
                        f"BaseException, not {type(typ).__name__}")
    if tb is not None:
        exc = exc.with_traceback(tb)
    return exc


def _gen_throw(gen, close_on_genexit, typ, val, tb):
    frame_state = gen.gi_frame_state
    if frame_state == FRAME_EXECUTING:
        raise _gen_raise_already_executing_error(gen)
    if FRAME_STATE_FINISHED(frame_state):
        if PyCoro_CheckExact(gen):
            # `gen` is an exhausted coroutine: raise an error
            raise RuntimeError("cannot reuse already awaited coroutine")
        exc = gen_set_exception(typ, val, tb)
        _PyErr_SetRaisedException(gen.gi_tstate, exc)
        raise exc

    gen.gi_frame_state = FRAME_EXECUTING
    if frame_state == FRAME_SUSPENDED_YIELD_FROM:
        frame = gen.gi_iframe
        yf = frame.stack[-2]
        # Never resume the frame from inside a host `except` block: the host would
        # chain its handled exception onto everything raised.
        err = None
        ret = NULL
        throw_here = False
        try:
            if PyErr_GivenExceptionMatches(typ, GeneratorExit) and close_on_genexit:
                # Asynchronous generators *should not* be closed right away; hence
                # the `close_on_genexit` parameter.
                gen_close_iter(yf)
                throw_here = True
            elif PyGen_CheckExact(yf) or PyCoro_CheckExact(yf):
                # `yf` is a generator or a coroutine.
                ret = _gen_throw(yf, close_on_genexit, typ, val, tb)
            else:
                # `yf` is an iterator or a coroutine-like object.
                from pp.object import PyObject_GetOptionalAttr
                from pp.call import PyObject_Vectorcall
                meth = PyObject_GetOptionalAttr(yf, "throw")
                if meth is NULL:
                    throw_here = True
                else:
                    args = [typ]
                    if val is not None:
                        args.append(val)
                        if tb is not None:
                            args.append(tb)
                    ret = PyObject_Vectorcall(meth, tuple(args))
        except BaseException as e:
            err = e
        if err is not None:
            # gen_throw_current_exception: send the error into the generator.
            return _throw_current_exception(gen, err)
        if not throw_here:
            gen.gi_frame_state = frame_state
            return ret
    exc = _gen_set_exception_resetting(gen, frame_state, typ, val, tb)
    return _throw_current_exception(gen, exc)


def _gen_set_exception_resetting(gen, frame_state, typ, val, tb):
    err = None
    exc = None
    try:
        exc = gen_set_exception(typ, val, tb)
    except BaseException as e:
        err = e
    if err is not None:
        gen.gi_frame_state = frame_state
        raise err
    return exc


def _throw_current_exception(gen, exc):
    _PyErr_SetRaisedException(gen.gi_tstate, exc)
    kind, result = gen_send_ex2(gen, None, exc)
    if kind == PYGEN_RETURN:
        _gen_set_stop_iteration(gen, result)
    return result


def gen_throw(gen, typ, val=None, tb=None):
    return _gen_throw(gen, True, typ, val, tb)


register_static_slots(PyGenObject, tp_iter=lambda gen: gen, tp_iternext=gen_iternext,
                      am_send=gen_am_send)
register_static_slots(PyCoroObject, am_send=gen_am_send)
