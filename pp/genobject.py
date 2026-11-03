"""Generators, coroutines and async generators, modeled on Objects/genobject.c.

`PyGenObject` carries CPython's fields (`gi_frame_state`, `gi_exc_state`,
`gi_name`, `gi_qualname`, `gi_iframe`). Where C returns NULL with an exception
set, functions here raise; `PYGEN_NEXT` / `PYGEN_RETURN` results are returned as
`(kind, value)`.
"""

import sys
import types

from pp.errors import (PyErr_GivenExceptionMatches, PyErr_WarnEx, PyExceptionClass_Check,
                       _PyErr_ChainStackItem, _PyErr_Clear, _PyErr_SetRaisedException,
                       _PyErr_StackItem, _PyExceptionInstance_Check, _PyThreadState_GET)
from pp.frame import (FRAME_OWNED_BY_GENERATOR, NULL, _PyFrame_GetFrameObject)
from pp.typeobject import Py_TYPE, register_static_slots

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

CO_COROUTINE = 0x80
CO_ITERABLE_COROUTINE = 0x100

NON_INIT_CORO_MSG = "can't send non-None value to a just-started coroutine"


def FRAME_STATE_SUSPENDED(state: int) -> bool:
    return FRAME_SUSPENDED <= state <= FRAME_SUSPENDED_YIELD_FROM_LOCKED


def FRAME_STATE_FINISHED(state: int) -> bool:
    return state == FRAME_CLEARED


# Names of VM state that dir() does not list (CPython keeps them in the C struct).
_HIDDEN = frozenset((
    "_kind", "gi_frame_state", "gi_exc_state", "gi_iframe", "gi_tstate", "ag_closed",
    "ag_hooks_inited", "ag_running_async", "ag_origin_or_finalizer", "ags_gen", "ags_sendval",
    "ags_state", "agt_gen", "agt_typ", "agt_tb", "agt_val", "agt_state", "cw_coroutine"))


def _public_dir(self):
    names = [n for n in object.__dir__(self) if n not in _HIDDEN]
    if type(self) is not PyGenObject:
        # gi_code is the slot holding every kind's code; only generators have it.
        names = [n for n in names if n != "gi_code"]
    return sorted(names)


class _PyGenBase:
    """The fields and finalizer shared by generators, coroutines and async generators
    (PyGenObject's common header)."""
    _kind = "generator"

    # `__name__`/`__qualname__` are slots (as on the old Generator).
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

    def __repr__(self):
        return f"<{self._kind} object {self.__qualname__} at {id(self):#x}>"

    def __del__(self):
        gen_finalize(self)

    __dir__ = _public_dir


def _gen_frame(gen):
    if gen.gi_frame_state == FRAME_CLEARED:
        return None
    return _PyFrame_GetFrameObject(gen.gi_iframe)


def _gen_yf(gen):
    if gen.gi_frame_state == FRAME_SUSPENDED_YIELD_FROM:
        return gen.gi_iframe.stack[-2]
    return None


class _SendMixin:
    """send/throw/close of generators and coroutines."""
    __slots__ = ()

    def send(self, arg, /):
        return gen_send(self, arg)

    def throw(self, *args):
        return gen_throw(self, args)

    def close(self):
        return gen_close(self)


class PyGenObject(_SendMixin, _PyGenBase):
    __slots__ = ()

    # --- introspection (genobject.c getset/member tables) ---

    gi_frame = property(_gen_frame)
    gi_running = property(lambda self: self.gi_frame_state == FRAME_EXECUTING)
    gi_suspended = property(lambda self: FRAME_STATE_SUSPENDED(self.gi_frame_state))
    gi_yieldfrom = property(_gen_yf)

    @property
    def gi_state(self):
        return gen_get_state(self)

    # --- protocol: methods the host (and VM code via the type slots) can call ---

    def __iter__(self):
        return self

    def __next__(self):
        return gen_iternext(self)


def gen_get_state(gen, prefix="GEN") -> str:
    state = gen.gi_frame_state
    if state == FRAME_CREATED:
        return prefix + "_CREATED"
    if FRAME_STATE_SUSPENDED(state):
        return prefix + "_SUSPENDED"
    if state == FRAME_EXECUTING:
        return prefix + "_RUNNING"
    return prefix + "_CLOSED"


def gen_finalize(gen) -> None:
    """gen_finalize (the tp_finalize of generators, coroutines, async generators)."""
    state = gen.gi_frame_state
    if FRAME_STATE_FINISHED(state):
        return
    try:
        if PyAsyncGen_CheckExact(gen):
            finalizer = gen.ag_origin_or_finalizer
            if finalizer is not None and not gen.ag_closed:
                _call_finalizer(finalizer, gen)
                return
        if gen.gi_code.co_flags & CO_COROUTINE and state == FRAME_CREATED:
            _warn_unawaited_coroutine(gen)
        else:
            gen_close(gen)
    except BaseException:
        # Raised from __del__: C prints "Exception ignored" and goes on.
        pass


def _call_finalizer(finalizer, gen) -> None:
    from pp.call import PyObject_CallOneArg
    PyObject_CallOneArg(finalizer, gen)


def _warn_unawaited_coroutine(coro) -> None:
    tstate = _PyThreadState_GET()
    vm = tstate.vm if tstate is not None else None
    if vm is None:
        return
    warnings = vm.importer.import_module("warnings")
    fn = getattr(warnings, "_warn_unawaited_coroutine", None)
    if fn is not None:
        fn(coro)
    else:
        PyErr_WarnEx(RuntimeWarning, f"coroutine '{coro.__qualname__}' was never awaited", 1)


class PyCoroWrapper:
    """coroutine_wrapper: what `coro.__await__()` returns."""
    __slots__ = ("cw_coroutine",)

    __dir__ = _public_dir

    def __init__(self, coro):
        self.cw_coroutine = coro

    def __iter__(self):
        return self

    def __next__(self):
        return gen_iternext(self.cw_coroutine)

    def send(self, arg, /):
        return gen_send(self.cw_coroutine, arg)

    def throw(self, *args):
        return gen_throw(self.cw_coroutine, args)

    def close(self):
        return gen_close(self.cw_coroutine)


class PyCoroObject(_SendMixin, _PyGenBase):
    _kind = "coroutine"
    __slots__ = ()

    cr_frame = property(_gen_frame)
    cr_code = property(lambda self: self.gi_code)
    cr_running = property(lambda self: self.gi_frame_state == FRAME_EXECUTING)
    cr_suspended = property(lambda self: FRAME_STATE_SUSPENDED(self.gi_frame_state))
    cr_await = property(_gen_yf)
    # Coroutine origin tracking (sys.set_coroutine_origin_tracking_depth) is not modeled.
    cr_origin = property(lambda self: None)
    cr_state = property(lambda self: gen_get_state(self, "CORO"))

    def __await__(self):
        return PyCoroWrapper(self)


AWAITABLE_STATE_INIT = 0
AWAITABLE_STATE_ITER = 1
AWAITABLE_STATE_CLOSED = 2

ASYNC_GEN_IGNORED_EXIT_MSG = "async generator ignored GeneratorExit"


class PyAsyncGenObject(_PyGenBase):
    _kind = "async_generator"
    __slots__ = ("ag_origin_or_finalizer", "ag_closed", "ag_hooks_inited", "ag_running_async")

    def __init__(self, frame, func, tstate):
        _PyGenBase.__init__(self, frame, func, tstate)
        self.ag_origin_or_finalizer = None
        self.ag_closed = False
        self.ag_hooks_inited = False
        self.ag_running_async = False

    ag_frame = property(_gen_frame)
    ag_code = property(lambda self: self.gi_code)
    ag_running = property(lambda self: self.ag_running_async)
    ag_suspended = property(lambda self: FRAME_STATE_SUSPENDED(self.gi_frame_state))
    ag_await = property(_gen_yf)
    ag_state = property(lambda self: gen_get_state(self, "AGEN"))

    def __aiter__(self):
        return self

    def __anext__(self):
        async_gen_init_hooks(self)
        return PyAsyncGenASend(self, None)

    def asend(self, arg, /):
        async_gen_init_hooks(self)
        return PyAsyncGenASend(self, arg)

    def aclose(self):
        async_gen_init_hooks(self)
        return PyAsyncGenAThrow(self, ())

    def athrow(self, *args):
        if not args:
            raise TypeError("athrow expected at least 1 argument, got 0")
        if len(args) > 1:
            PyErr_WarnEx(DeprecationWarning,
                         "the (type, exc, tb) signature of athrow() is deprecated, "
                         "use the single-arg signature instead.", 1)
        async_gen_init_hooks(self)
        return PyAsyncGenAThrow(self, args)




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
    # A suspended or finished generator frame has no caller (gen_send_ex2 sets
    # `previous = NULL`); keeping it would tie the generator to its last resumer.
    frame.previous = None
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
        caught = True    # not the exception itself: cycle with its traceback
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
    """Build the exception instance to throw (the PyErr_NormalizeException part).
    `val` / `tb` are NULL when not given."""
    if tb is None:
        tb = NULL
    elif tb is not NULL and not isinstance(tb, types.TracebackType):
        raise TypeError("throw() third argument must be a traceback object")
    if val is NULL:
        val = None
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
    if tb is not NULL:
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
        meth = NULL
        if PyErr_GivenExceptionMatches(typ, GeneratorExit) and close_on_genexit:
            # Asynchronous generators *should not* be closed right away; hence
            # the `close_on_genexit` parameter.
            try:
                gen_close_iter(yf)
            except BaseException as e:
                err = e
            throw_here = err is None
        elif PyGen_CheckExact(yf) or PyCoro_CheckExact(yf):
            # `yf` is a generator or a coroutine.
            try:
                ret = _gen_throw(yf, close_on_genexit, typ, val, tb)
            except BaseException as e:
                err = e
        else:
            # `yf` is an iterator or a coroutine-like object.
            from pp.object import PyObject_GetOptionalAttr
            lookup_err = None
            try:
                meth = PyObject_GetOptionalAttr(yf, "throw")
            except BaseException as e:
                lookup_err = e
            if lookup_err is not None:
                # genobject.c: restore the frame state and propagate.
                gen.gi_frame_state = frame_state
                raise lookup_err
            if meth is NULL:
                throw_here = True
            else:
                from pp.call import PyObject_Vectorcall
                args = [typ]
                if val is not NULL:
                    args.append(val)
                    if tb is not NULL:
                        args.append(tb)
                try:
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


def gen_throw(gen, args):
    nargs = len(args)
    if nargs < 1:
        raise TypeError(f"throw expected at least 1 argument, got {nargs}")
    if nargs > 3:
        raise TypeError(f"throw expected at most 3 arguments, got {nargs}")
    if nargs > 1:
        PyErr_WarnEx(DeprecationWarning,
                     "the (type, exc, tb) signature of throw() is deprecated, "
                     "use the single-arg signature instead.", 1)
    typ = args[0]
    val = args[1] if nargs > 1 else NULL
    tb = args[2] if nargs > 2 else NULL
    return _gen_throw(gen, True, typ, val, tb)


register_static_slots(PyGenObject, tp_iter=lambda gen: gen, tp_iternext=gen_iternext,
                      am_send=gen_am_send)
register_static_slots(PyCoroObject, am_send=gen_am_send)


# --- awaitables ---------------------------------------------------------------

def gen_is_coroutine(o) -> bool:
    return PyGen_CheckExact(o) and bool(o.gi_code.co_flags & CO_ITERABLE_COROUTINE)


def PyCoro_GetAwaitableIter(o):
    """_PyCoro_GetAwaitableIter: `o` itself if a coroutine, else `o.__await__()`."""
    from pp.abstract import PyIter_Check
    from pp.object import _type_fullname
    if PyCoro_CheckExact(o) or gen_is_coroutine(o):
        return o
    tp = Py_TYPE(o)
    getter = tp.am_await
    if getter is None:
        raise TypeError(f"'{tp.tp_name[:100]}' object can't be awaited")
    res = getter(o)
    if PyCoro_CheckExact(res) or gen_is_coroutine(res):
        # __await__ must return an *iterator*, not a coroutine (see PEP 492)
        raise TypeError(f"{_type_fullname(type(o))}.__await__() must return an iterator, "
                        "not coroutine")
    if not PyIter_Check(res):
        raise TypeError(f"{_type_fullname(type(o))}.__await__() must return an iterator, "
                        f"not {_type_fullname(type(res))}")
    return res


# --- async generators ---------------------------------------------------------

class PyAsyncGenWrappedValue:
    """_PyAsyncGenWrappedValue: marks a value yielded by an async generator (as
    opposed to one yielded by an await inside it)."""
    __slots__ = ("agw_val",)

    def __init__(self, val):
        self.agw_val = val


def _wrapped(o) -> bool:
    return type(o) is PyAsyncGenWrappedValue


def async_gen_init_hooks(o) -> None:
    if o.ag_hooks_inited:
        return
    o.ag_hooks_inited = True
    firstiter, finalizer = sys.get_asyncgen_hooks()
    if finalizer is not None:
        o.ag_origin_or_finalizer = finalizer
    if firstiter is not None:
        _call_finalizer(firstiter, o)


def async_gen_unwrap_value(gen, step):
    """Run `step()` (a send/throw of the generator) and unwrap what it yields: an async
    yield ends the awaitable with StopIteration(value)."""
    err = None
    result = NULL
    try:
        result = step()
    except BaseException as e:
        err = e
    if err is not None:
        if isinstance(err, (StopAsyncIteration, GeneratorExit)):
            gen.ag_closed = True
        gen.ag_running_async = False
        try:
            raise err
        finally:
            err = None
    if _wrapped(result):
        gen.ag_running_async = False
        raise StopIteration(result.agw_val)
    return result


def _warn_unawaited_agen_method(agen, method) -> None:
    try:
        PyErr_WarnEx(RuntimeWarning,
                     f"coroutine method {method!r} of {agen.__qualname__!r} was never awaited", 1)
    except BaseException:
        pass


class PyAsyncGenASend:
    """async_generator_asend: the awaitable of `__anext__()` / `asend()`."""
    __slots__ = ("ags_gen", "ags_sendval", "ags_state", "__weakref__")
    __dir__ = _public_dir

    def __init__(self, gen, sendval):
        self.ags_gen = gen
        self.ags_sendval = sendval
        self.ags_state = AWAITABLE_STATE_INIT

    def __await__(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        return async_gen_asend_send(self, None)

    def send(self, arg, /):
        return async_gen_asend_send(self, arg)

    def throw(self, *args):
        return async_gen_asend_throw(self, args)

    def close(self):
        return async_gen_asend_close(self)

    def __del__(self):
        if self.ags_state == AWAITABLE_STATE_INIT:
            _warn_unawaited_agen_method(self.ags_gen, "asend")


def async_gen_asend_send(o, arg):
    if o.ags_state == AWAITABLE_STATE_CLOSED:
        raise RuntimeError("cannot reuse already awaited __anext__()/asend()")
    gen = o.ags_gen
    if o.ags_state == AWAITABLE_STATE_INIT:
        if gen.ag_running_async:
            o.ags_state = AWAITABLE_STATE_CLOSED
            raise RuntimeError("anext(): asynchronous generator is already running")
        if arg is None:
            arg = o.ags_sendval
        o.ags_state = AWAITABLE_STATE_ITER
    gen.ag_running_async = True
    err = None
    result = NULL
    try:
        result = async_gen_unwrap_value(gen, lambda: gen_send(gen, arg))
    except BaseException as e:
        err = e
    if err is not None:
        o.ags_state = AWAITABLE_STATE_CLOSED
        try:
            raise err
        finally:
            err = None
    return result


def async_gen_asend_am_send(o, arg):
    stop = None
    result = NULL
    try:
        result = async_gen_asend_send(o, arg)
    except StopIteration as e:
        stop = e.value
        _PyErr_Clear(_PyThreadState_GET())
        return PYGEN_RETURN, stop
    return PYGEN_NEXT, result


def async_gen_asend_throw(o, args):
    if o.ags_state == AWAITABLE_STATE_CLOSED:
        raise RuntimeError("cannot reuse already awaited __anext__()/asend()")
    gen = o.ags_gen
    if o.ags_state == AWAITABLE_STATE_INIT:
        if gen.ag_running_async:
            o.ags_state = AWAITABLE_STATE_CLOSED
            raise RuntimeError("anext(): asynchronous generator is already running")
        o.ags_state = AWAITABLE_STATE_ITER
        gen.ag_running_async = True
    err = None
    result = NULL
    try:
        result = async_gen_unwrap_value(gen, lambda: gen_throw(gen, args))
    except BaseException as e:
        err = e
    if err is not None:
        gen.ag_running_async = False
        o.ags_state = AWAITABLE_STATE_CLOSED
        try:
            raise err
        finally:
            err = None
    return result


def _close_awaitable(throw, o):
    """asend/athrow `close()`: throw GeneratorExit in and swallow how it ends."""
    caught = None
    result = NULL
    try:
        result = throw(o, (GeneratorExit,))
    except (StopIteration, StopAsyncIteration, GeneratorExit):
        caught = True
    if caught is not None:
        _PyErr_Clear(_PyThreadState_GET())
        return None
    raise RuntimeError("coroutine ignored GeneratorExit")


def async_gen_asend_close(o):
    if o.ags_state == AWAITABLE_STATE_CLOSED:
        return None
    return _close_awaitable(async_gen_asend_throw, o)


class PyAsyncGenAThrow:
    """async_generator_athrow: the awaitable of `aclose()` / `athrow()`."""
    __slots__ = ("agt_gen", "agt_typ", "agt_tb", "agt_val", "agt_state", "__weakref__")
    __dir__ = _public_dir

    def __init__(self, gen, args):
        nargs = len(args)
        if nargs > 3:
            raise TypeError(f"athrow expected at most 3 arguments, got {nargs}")
        self.agt_gen = gen
        self.agt_typ = args[0] if nargs > 0 else None
        self.agt_val = args[1] if nargs > 1 else NULL
        self.agt_tb = args[2] if nargs > 2 else NULL
        self.agt_state = AWAITABLE_STATE_INIT

    def __await__(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        return async_gen_athrow_send(self, None)

    def send(self, arg, /):
        return async_gen_athrow_send(self, arg)

    def throw(self, *args):
        return async_gen_athrow_throw(self, args)

    def close(self):
        if self.agt_state == AWAITABLE_STATE_CLOSED:
            return None
        return _close_awaitable(async_gen_athrow_throw, self)

    def __del__(self):
        if self.agt_state == AWAITABLE_STATE_INIT:
            _warn_unawaited_agen_method(self.agt_gen,
                                        "athrow" if self.agt_typ is not None else "aclose")


def _athrow_running_error(o) -> RuntimeError:
    which = "aclose" if o.agt_typ is None else "athrow"
    return RuntimeError(f"{which}(): asynchronous generator is already running")


def async_gen_athrow_send(o, arg):
    gen = o.agt_gen
    if o.agt_state == AWAITABLE_STATE_CLOSED:
        raise RuntimeError("cannot reuse already awaited aclose()/athrow()")
    if FRAME_STATE_FINISHED(gen.gi_frame_state):
        o.agt_state = AWAITABLE_STATE_CLOSED
        raise StopIteration
    aclose = o.agt_typ is None
    init = o.agt_state == AWAITABLE_STATE_INIT
    if init:
        if gen.ag_running_async:
            o.agt_state = AWAITABLE_STATE_CLOSED
            raise _athrow_running_error(o)
        if gen.ag_closed:
            o.agt_state = AWAITABLE_STATE_CLOSED
            raise StopAsyncIteration
        if arg is not None:
            raise RuntimeError(NON_INIT_CORO_MSG)
        o.agt_state = AWAITABLE_STATE_ITER
        gen.ag_running_async = True
    err = None
    retval = NULL
    try:
        if init and aclose:
            gen.ag_closed = True
            # Do not close the generator when GeneratorExit is passed
            retval = _gen_throw(gen, False, GeneratorExit, NULL, NULL)
        elif init:
            retval = async_gen_unwrap_value(
                gen, lambda: _gen_throw(gen, False, o.agt_typ, o.agt_val, o.agt_tb))
        elif not aclose:
            return async_gen_unwrap_value(gen, lambda: gen_send(gen, arg))
        else:
            retval = gen_send(gen, arg)
    except BaseException as e:
        err = e
        if not init and not aclose:
            raise
    if err is None:
        if aclose and _wrapped(retval):
            gen.ag_running_async = False
            o.agt_state = AWAITABLE_STATE_CLOSED
            raise RuntimeError(ASYNC_GEN_IGNORED_EXIT_MSG)
        return retval
    gen.ag_running_async = False
    o.agt_state = AWAITABLE_STATE_CLOSED
    if aclose and isinstance(err, (StopAsyncIteration, GeneratorExit)):
        # aclose() must not propagate these: StopIteration says the await is done.
        _PyErr_Clear(_PyThreadState_GET())
        raise StopIteration
    try:
        raise err
    finally:
        err = None


def async_gen_athrow_throw(o, args):
    gen = o.agt_gen
    if o.agt_state == AWAITABLE_STATE_CLOSED:
        raise RuntimeError("cannot reuse already awaited aclose()/athrow()")
    if o.agt_state == AWAITABLE_STATE_INIT:
        if gen.ag_running_async:
            o.agt_state = AWAITABLE_STATE_CLOSED
            raise _athrow_running_error(o)
        o.agt_state = AWAITABLE_STATE_ITER
        gen.ag_running_async = True
    err = None
    retval = NULL
    try:
        if o.agt_typ is not None:
            retval = async_gen_unwrap_value(gen, lambda: gen_throw(gen, args))
        else:
            retval = gen_throw(gen, args)
    except BaseException as e:
        err = e
    if o.agt_typ is not None:
        if err is not None:
            gen.ag_running_async = False
            o.agt_state = AWAITABLE_STATE_CLOSED
            try:
                raise err
            finally:
                err = None
        return retval
    # aclose() mode
    if err is None and _wrapped(retval):
        gen.ag_running_async = False
        o.agt_state = AWAITABLE_STATE_CLOSED
        raise RuntimeError(ASYNC_GEN_IGNORED_EXIT_MSG)
    if err is None:
        return retval
    gen.ag_running_async = False
    o.agt_state = AWAITABLE_STATE_CLOSED
    if isinstance(err, (StopAsyncIteration, GeneratorExit)):
        _PyErr_Clear(_PyThreadState_GET())
        raise StopIteration
    try:
        raise err
    finally:
        err = None


register_static_slots(PyAsyncGenASend, am_send=async_gen_asend_am_send)


for _cls, _name in ((PyGenObject, "generator"), (PyCoroObject, "coroutine"),
                    (PyAsyncGenObject, "async_generator"), (PyCoroWrapper, "coroutine_wrapper"),
                    (PyAsyncGenASend, "async_generator_asend"),
                    (PyAsyncGenAThrow, "async_generator_athrow"),
                    (PyAsyncGenWrappedValue, "async_generator_wrapped_value")):
    _cls.__name__ = _cls.__qualname__ = _name
    _cls.__module__ = "builtins"
del _cls, _name
