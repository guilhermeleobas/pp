"""VM functions, modeled on PyFunctionObject (Objects/funcobject.c)."""

import builtins as _host_builtins
import types

from pp.frame import NULL

CO_OPTIMIZED = 0x1
CO_VARARGS = 0x4
CO_VARKEYWORDS = 0x8
CO_HAS_DOCSTRING = 0x4000000


class Function:
    # Dunder names are real slots so that `vars(f)` / `f.__dict__` only holds
    # user attributes (functools.update_wrapper copies __dict__).
    __slots__ = ("__code__", "__globals__", "__builtins__", "__name__",
                 "__qualname__", "__doc__", "__defaults__", "__kwdefaults__",
                 "__closure__", "__annotate__", "__type_params__", "_module",
                 "_annotations", "_vm", "__dict__", "__weakref__")

    def __init__(self, code: types.CodeType, globals: dict, vm, builtins: dict | None = None):
        self.__code__ = code
        self.__globals__ = globals
        self.__builtins__ = builtins if builtins is not None else vm.builtins_for(globals)
        self.__name__ = code.co_name
        self.__qualname__ = code.co_qualname
        if code.co_flags & CO_HAS_DOCSTRING and code.co_consts:
            self.__doc__ = code.co_consts[0]
        else:
            self.__doc__ = None
        self.__defaults__ = None
        self.__kwdefaults__ = None
        self.__closure__ = None
        self.__annotate__ = None
        self.__type_params__ = ()
        self._module = globals.get("__name__")
        self._annotations = None
        self._vm = vm

    # --- descriptor / call protocol ---

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return types.MethodType(self, obj)

    def __call__(self, *args, **kwargs):
        return self._vm.call_function(self, args, kwargs)

    def __repr__(self):
        return f"<function {self.__qualname__} at {id(self):#x}>"

    # --- lazily computed attributes ---

    @property
    def __annotations__(self):
        if self._annotations is None:
            if self.__annotate__ is not None:
                ann = self.__annotate__(1)
                if not isinstance(ann, dict):
                    raise TypeError(
                        f"__annotate__ returned non-dict of type '{type(ann).__name__}'")
                self._annotations = ann
            else:
                self._annotations = {}
        return self._annotations

    @__annotations__.setter
    def __annotations__(self, value):
        if value is not None and not isinstance(value, dict):
            raise TypeError("__annotations__ must be set to a dict object")
        self._annotations = value

    @__annotations__.deleter
    def __annotations__(self):
        self._annotations = None


def _get_module(self):
    return self._module


def _set_module(self, value):
    self._module = value


# Installed after class creation: a `__module__` slot would conflict with the
# class's own `__module__` entry.
Function.__module__ = property(_get_module, _set_module)


# --- argument binding: initialize_locals() in Python/ceval.c ---

def _format_missing(kind: str, qualname: str, names: list) -> TypeError:
    n = len(names)
    if n == 1:
        s = names[0]
    elif n == 2:
        s = f"{names[0]} and {names[1]}"
    else:
        s = ", ".join(names[:-2]) + f", {names[-2]}, and {names[-1]}"
    return TypeError(
        f"{qualname}() missing {n} required {kind} argument{'' if n == 1 else 's'}: {s}")


def _missing_arguments(co, defcount, localsplus, names, qualname):
    positional = defcount != -1
    if positional:
        start, end = 0, co.co_argcount - defcount
    else:
        start, end = co.co_argcount, co.co_argcount + co.co_kwonlyargcount
    missing = [repr(names[i]) for i in range(start, end) if localsplus[i] is NULL]
    return _format_missing("positional" if positional else "keyword-only", qualname, missing)


def _too_many_positional(co, given, defaults, localsplus, qualname):
    argcount = co.co_argcount
    kwonly_given = sum(1 for i in range(argcount, argcount + co.co_kwonlyargcount)
                       if localsplus[i] is not NULL)
    defcount = len(defaults) if defaults else 0
    if defcount:
        plural = True
        sig = f"from {argcount - defcount} to {argcount}"
    else:
        plural = argcount != 1
        sig = str(argcount)
    if kwonly_given:
        kwonly_sig = (f" positional argument{'s' if given != 1 else ''} "
                      f"(and {kwonly_given} keyword-only argument{'s' if kwonly_given != 1 else ''})")
    else:
        kwonly_sig = ""
    was = "was" if given == 1 and not kwonly_given else "were"
    return TypeError(
        f"{qualname}() takes {sig} positional argument{'s' if plural else ''} "
        f"but {given}{kwonly_sig} {was} given")


def bind_arguments(func: Function, localsplus: list, names: tuple, args, kwargs) -> None:
    co = func.__code__
    qualname = func.__qualname__
    argcount = co.co_argcount
    total_args = argcount + co.co_kwonlyargcount
    flags = co.co_flags
    nargs = len(args)

    kwdict = None
    if flags & CO_VARKEYWORDS:
        kwdict = {}
        i = total_args + (1 if flags & CO_VARARGS else 0)
        localsplus[i] = kwdict

    n = min(nargs, argcount)
    for j in range(n):
        localsplus[j] = args[j]

    if flags & CO_VARARGS:
        localsplus[total_args] = tuple(args[n:])

    if kwargs:
        posonly = co.co_posonlyargcount
        for keyword, value in kwargs.items():
            if type(keyword) is not str and not isinstance(keyword, str):
                raise TypeError(f"{qualname}() keywords must be strings")
            for j in range(posonly, total_args):
                if names[j] == keyword:
                    break
            else:
                if kwdict is None:
                    if posonly:
                        conflicts = [k for k in kwargs if k in names[:posonly]]
                        if conflicts:
                            raise TypeError(
                                f"{qualname}() got some positional-only arguments passed"
                                f" as keyword arguments: '{', '.join(conflicts)}'")
                    raise TypeError(
                        f"{qualname}() got an unexpected keyword argument '{keyword}'")
                kwdict[keyword] = value
                continue
            if localsplus[j] is not NULL:
                raise TypeError(f"{qualname}() got multiple values for argument '{keyword}'")
            localsplus[j] = value

    if nargs > argcount and not flags & CO_VARARGS:
        raise _too_many_positional(co, nargs, func.__defaults__, localsplus, qualname)

    if nargs < argcount:
        defaults = func.__defaults__ or ()
        defcount = len(defaults)
        m = argcount - defcount
        if any(localsplus[i] is NULL for i in range(nargs, m)):
            raise _missing_arguments(co, defcount, localsplus, names, qualname)
        for i in range(max(n - m, 0), defcount):
            if localsplus[m + i] is NULL:
                localsplus[m + i] = defaults[i]

    if co.co_kwonlyargcount:
        kwdefs = func.__kwdefaults__
        missing = False
        for i in range(argcount, total_args):
            if localsplus[i] is not NULL:
                continue
            if kwdefs is not None and names[i] in kwdefs:
                localsplus[i] = kwdefs[names[i]]
                continue
            missing = True
        if missing:
            raise _missing_arguments(co, -1, localsplus, names, qualname)


def builtins_from_globals(globals: dict, default: dict) -> dict:
    b = globals.get("__builtins__")
    if b is None:
        return default
    if isinstance(b, types.ModuleType):
        b = b.__dict__
    if b is _host_builtins.__dict__:
        return default
    return b

# Present as the builtin `function` type to VM code (types.FunctionType is
# computed as type(lambda: None) by Lib/types.py's fallback).
Function.__name__ = Function.__qualname__ = "function"
