"""VM generators, modeled on Objects/genobject.c (gen_send_ex2, _gen_throw, gen_close)."""

import types

CREATED, SUSPENDED, SUSPENDED_YIELD_FROM, EXECUTING, CLEARED = range(5)


_THROW_HERE = object()


class ExcInfo:
    """_PyErr_StackItem: one entry of the handled-exception stack."""
    __slots__ = ("exc_value", "previous")

    def __init__(self, exc_value=None, previous=None):
        self.exc_value = exc_value
        self.previous = previous


def _normalize_throw(typ, val, tb):
    """gen_set_exception(): build the exception instance for throw()."""
    if isinstance(typ, type) and issubclass(typ, BaseException):
        if isinstance(val, typ):
            exc = val
        elif val is None:
            exc = typ()
        elif isinstance(val, tuple):
            exc = typ(*val)
        else:
            exc = typ(val)
    elif isinstance(typ, BaseException):
        if val is not None:
            raise TypeError("instance exception may not have a separate value")
        exc = typ
    else:
        raise TypeError("exceptions must be classes or instances deriving from "
                        f"BaseException, not {type(typ).__name__}")
    if tb is not None:
        if not isinstance(tb, types.TracebackType):
            raise TypeError("throw() third argument must be a traceback object")
        exc = exc.with_traceback(tb)
    return exc


class Generator:
    _kind = "generator"

    __slots__ = ("gi_frame", "gi_code", "__name__", "__qualname__", "_state",
                 "_exc_state", "_vm", "__weakref__")

    def __init__(self, frame, func, vm):
        self.gi_frame = frame
        self.gi_code = frame.code
        self.__name__ = func.__name__ if func is not None else frame.code.co_name
        self.__qualname__ = func.__qualname__ if func is not None else frame.code.co_qualname
        self._state = CREATED
        self._exc_state = ExcInfo()
        self._vm = vm

    # --- introspection ---

    @property
    def gi_running(self):
        return self._state == EXECUTING

    @property
    def gi_state(self):
        return ("GEN_CREATED", "GEN_SUSPENDED", "GEN_SUSPENDED", "GEN_RUNNING",
                "GEN_CLOSED")[self._state]

    @property
    def gi_suspended(self):
        return self._state in (SUSPENDED, SUSPENDED_YIELD_FROM)

    @property
    def gi_yieldfrom(self):
        if self._state == SUSPENDED_YIELD_FROM:
            return self.gi_frame.stack[-2]
        return None

    def __repr__(self):
        return f"<{self._kind} object {self.__qualname__} at {id(self):#x}>"

    # --- core resume: gen_send_ex2 ---

    def _resume(self, value, exc=None):
        """Run the frame; return (is_return, value). Exceptions propagate."""
        state = self._state
        if state == EXECUTING:
            raise ValueError(f"{self._kind} already executing")
        if state == CLEARED:
            if exc is not None:
                self._vm._raised = exc  # gen_set_exception: restored, not chained
                raise exc
            return True, None
        if state == CREATED and value is not None and exc is None:
            raise TypeError(f"can't send non-None value to a just-started {self._kind}")
        vm = self._vm
        frame = self.gi_frame
        frame.push(value)
        self._exc_state.previous = vm.exc_info
        vm.exc_info = self._exc_state
        self._state = EXECUTING
        if exc is not None and self._exc_state.exc_value is not None:
            vm._chain(exc)  # _PyErr_ChainStackItem: only against our own exc state
        try:
            result = vm.run_frame(frame, exc)
        except BaseException:
            self._state = CLEARED
            self.gi_frame = None
            raise
        finally:
            vm.exc_info = self._exc_state.previous
            self._exc_state.previous = None
        if frame.yielded:
            self._state = SUSPENDED_YIELD_FROM if frame.yield_oparg == 1 else SUSPENDED
            return False, result
        self._state = CLEARED
        self.gi_frame = None
        return True, result

    def _send_ex(self, value):
        return self._resume(value)

    # --- public protocol ---

    def __iter__(self):
        return self

    def __next__(self):
        return self._finish(*self._resume(None))

    def send(self, value):
        return self._finish(*self._resume(value))

    def _finish(self, is_return, v):
        if is_return:
            if v is None:
                raise StopIteration
            raise StopIteration(v)
        return v

    def throw(self, typ, val=None, tb=None):
        return self._throw(True, typ, val, tb)

    def _throw(self, close_on_genexit, typ, val, tb):
        state = self._state
        if state == EXECUTING:
            raise ValueError(f"{self._kind} already executing")
        if state == CLEARED:
            exc = _normalize_throw(typ, val, tb)
            self._vm._raised = exc  # gen_set_exception: restored, not chained
            raise exc
        if state == SUSPENDED_YIELD_FROM:
            yf = self.gi_frame.stack[-2]
            is_genexit = (isinstance(typ, type) and issubclass(typ, GeneratorExit)) or \
                isinstance(typ, GeneratorExit)
            # Never resume the frame from inside a host `except` block: the
            # host would chain its handled exception onto everything raised.
            err = None
            self._state = EXECUTING  # the delegating generator is running meanwhile
            try:
                ret = self._delegate_throw(yf, is_genexit and close_on_genexit,
                                           close_on_genexit, typ, val, tb)
            except BaseException as e:
                err = e
            self._state = state
            if err is not None:
                return self._throw_into(err)
            if ret is not _THROW_HERE:
                return ret
        return self._throw_into(_normalize_throw(typ, val, tb))

    def _delegate_throw(self, yf, close_first, close_on_genexit, typ, val, tb):
        if close_first:
            _close_iter(yf)
            return _THROW_HERE
        if isinstance(yf, Generator):
            return yf._throw(close_on_genexit, typ, val, tb)
        meth = getattr(yf, "throw", None)
        if meth is None:
            return _THROW_HERE
        args = [typ]
        if val is not None:
            args.append(val)
            if tb is not None:
                args.append(tb)
        return meth(*args)

    def _throw_into(self, exc):
        return self._finish(*self._resume(None, exc))

    def close(self):
        state = self._state
        if state == CREATED:
            self._state = CLEARED
            self.gi_frame = None
            return None
        if state == CLEARED:
            return None
        if state == EXECUTING:
            raise ValueError(f"{self._kind} already executing")
        exc = None
        if state == SUSPENDED_YIELD_FROM:
            self._state = EXECUTING
            try:
                _close_iter(self.gi_frame.stack[-2])
            except BaseException as e:
                exc = e
            self._state = state
        if exc is None:
            exc = GeneratorExit()
        try:
            is_return, v = self._resume(None, exc)
        except GeneratorExit:
            return None
        if is_return:
            return v
        raise RuntimeError(f"{self._kind} ignored GeneratorExit")

    def __del__(self):
        if self._state in (SUSPENDED, SUSPENDED_YIELD_FROM):
            try:
                self.close()
            except BaseException:
                pass


def _close_iter(yf):
    if isinstance(yf, Generator):
        yf.close()
        return
    meth = getattr(yf, "close", None)
    if meth is not None:
        meth()


class Coroutine(Generator):
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


class AsyncGenerator(Generator):
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

for _cls, _name in ((Generator, "generator"), (Coroutine, "coroutine"),
                    (AsyncGenerator, "async_generator")):
    _cls.__name__ = _cls.__qualname__ = _name
    _cls.__module__ = "builtins"
del _cls, _name
