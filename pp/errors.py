"""Errors raised by the pp VM itself, and the thread's exception state.

The second half mirrors Python/errors.c: the `_PyErr_StackItem` chain hanging
off the thread state (`tstate->exc_info`), `_PyErr_SetObject` (the only place
implicit `__context__` chaining happens), `_PyErr_ChainStackItem` and
`_PyErr_GetTopmostException`.

Convention for translating C's "NULL + exception set": functions raise host
exceptions instead. `tstate.current_exception` is `tstate->current_exception`
for exceptions that were already *set* (and so already chained): an exception
caught at an eval-loop boundary that is not the current one was raised by host
code, i.e. it is a fresh `PyErr_SetObject` that must be chained now.
"""


class UnimplementedOpcode(NotImplementedError):
    def __init__(self, opname: str):
        super().__init__(f"opcode {opname} is not implemented")
        self.opname = opname


# Field accessors that cannot be shadowed by user subclasses (PyException_GetContext & co).
_context = BaseException.__dict__["__context__"]
_get_context = _context.__get__
_set_context = _context.__set__
_tp_mro = type.__dict__["__mro__"].__get__


def _PyExceptionInstance_Check(v) -> bool:
    for base in _tp_mro(type(v)):
        if base is BaseException:
            return True
    return False


def PyException_GetContext(exc):
    return _get_context(exc)


def PyException_SetContext(exc, context) -> None:
    _set_context(exc, context)


class _PyErr_StackItem:
    """One entry of the handled-exception stack (`exc_info`)."""
    __slots__ = ("exc_value", "previous_item")

    def __init__(self, exc_value=None, previous_item=None):
        self.exc_value = exc_value
        self.previous_item = previous_item


class PyThreadState:
    def __init__(self):
        self.exc_state = _PyErr_StackItem()   # tstate->exc_state: the base item
        self.exc_info = self.exc_state        # tstate->exc_info: top of the chain
        self.current_exception = None         # tstate->current_exception
        self.eval_frame = None                # _PyEval_EvalFrame: set by the interpreter


_current_tstate = None


def _PyThreadState_GET():
    return _current_tstate


def _PyThreadState_Swap(tstate):
    """Install `tstate` as the current thread state and return the previous one."""
    global _current_tstate
    prev = _current_tstate
    _current_tstate = tstate
    return prev


def _PyErr_GetTopmostException(tstate) -> _PyErr_StackItem:
    exc_info = tstate.exc_info
    while exc_info.exc_value is None and exc_info.previous_item is not None:
        exc_info = exc_info.previous_item
    return exc_info


def _PyErr_SetObject(tstate, value) -> None:
    """Set `value` (an exception instance) as the current exception, chaining
    it to the handled exception (`__context__`)."""
    exc_value = _PyErr_GetTopmostException(tstate).exc_value
    if exc_value is not None:
        # Implicit exception chaining. Avoid creating new reference cycles
        # through the context chain, while taking care not to hang on
        # pre-existing ones (Floyd's cycle detection).
        if exc_value is not value:
            o = exc_value
            slow_o = o
            slow_update_toggle = False
            while True:
                context = PyException_GetContext(o)
                if context is None:
                    break
                if context is value:
                    PyException_SetContext(o, None)
                    break
                o = context
                if o is slow_o:
                    break  # pre-existing cycle: every exception on the path was checked
                if slow_update_toggle:
                    slow_o = PyException_GetContext(slow_o)
                slow_update_toggle = not slow_update_toggle
            PyException_SetContext(value, exc_value)
    tstate.current_exception = value


def _PyErr_SetRaisedException(tstate, exc) -> None:
    """PyErr_SetRaisedException: re-raise `exc` without chaining."""
    tstate.current_exception = exc


def _PyErr_Clear(tstate) -> None:
    tstate.current_exception = None


def _PyErr_ChainStackItem(tstate, exc) -> None:
    """Chain `exc` (being thrown into a generator whose exc state is the top
    item) to that item's handled exception."""
    exc_info = tstate.exc_info
    if exc_info.exc_value is None:
        return
    _PyErr_SetObject(tstate, exc)


def PyExceptionClass_Check(o) -> bool:
    """A class deriving from BaseException."""
    from pp.typeobject import PyType_Check, PyType_IsSubtype, PyType_View
    return PyType_Check(o) and PyType_IsSubtype(PyType_View(o), PyType_View(BaseException))


def PyErr_GivenExceptionMatches(err, exc) -> bool:
    """Does the exception (instance or class) `err` match `exc` (a class or a tuple)?"""
    from pp.typeobject import PyType_IsSubtype, PyType_View
    if err is None or exc is None:
        return False
    if type(exc) is tuple:
        for item in exc:
            if PyErr_GivenExceptionMatches(err, item):
                return True
        return False
    if _PyExceptionInstance_Check(err):
        err = type(err)
    if PyExceptionClass_Check(err) and PyExceptionClass_Check(exc):
        return PyType_IsSubtype(PyType_View(err), PyType_View(exc))
    return err is exc
