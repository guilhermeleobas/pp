"""Calling objects, modeled on Objects/call.c.

pp's "vectorcall" is `func(callable, args, kwargs)` for the types that have a
`Py_TPFLAGS_HAVE_VECTORCALL` analogue (VM functions and bound methods); every
other callable goes through its `tp_call` slot.
"""

import types

from pp.typeobject import Py_TYPE

_method_func = types.MethodType.__dict__["__func__"].__get__
_method_self = types.MethodType.__dict__["__self__"].__get__


def _function_type():
    from pp.funcobject import Function
    return Function


_Function = None      # pp.funcobject.Function, set when that module loads


def _func_vectorcall(func, args, kwargs):
    return func._vm.call_function(func, args, kwargs)


def _method_vectorcall(method, args, kwargs):
    return _PyObject_Call(_method_func(method), (_method_self(method),) + tuple(args), kwargs)


def _PyVectorcall_Function(callable):
    global _Function
    if _Function is None:
        _Function = _function_type()
    tp = type(callable)
    if tp is _Function:
        return _func_vectorcall
    if tp is types.MethodType:
        return _method_vectorcall
    return None


def _PyObject_Call(callable, args, kwargs):
    if type(callable) is _Function:
        return callable._vm.call_function(callable, args, kwargs)    # _PyFunction_Vectorcall
    vector_func = _PyVectorcall_Function(callable)
    if vector_func is not None:
        return vector_func(callable, args, kwargs)
    call = Py_TYPE(callable).tp_call
    if call is None:
        raise TypeError(f"'{Py_TYPE(callable).tp_name}' object is not callable")
    return call(callable, args, kwargs)


def _PyObject_Call_Prepend(callable, obj, args, kwargs):
    return _PyObject_Call(callable, (obj,) + tuple(args), kwargs)


def PyObject_Vectorcall(callable, args, kwnames=None):
    """`args` holds the positional arguments followed by the values of the
    keyword arguments named by the tuple `kwnames`."""
    if kwnames:
        npos = len(args) - len(kwnames)
        kwargs = dict(zip(kwnames, args[npos:]))
        return _PyObject_Call(callable, tuple(args[:npos]), kwargs)
    if type(callable) is _Function:
        return callable._vm.call_function(callable, args, None)      # _PyFunction_Vectorcall
    return _PyObject_Call(callable, args if type(args) is tuple else tuple(args), None)


def PyObject_CallOneArg(callable, arg):
    return _PyObject_Call(callable, (arg,), None)


def PyObject_CallNoArgs(callable):
    return _PyObject_Call(callable, (), None)
