"""Compatibility shim: VM functions live in pp.funcobject."""

from pp.funcobject import (Function, PyFunctionObject, bind_arguments,  # noqa: F401
                           builtins_from_globals)
