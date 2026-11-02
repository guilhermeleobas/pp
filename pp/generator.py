"""Compatibility shim: generators live in pp.genobject."""

from pp.genobject import (PyAsyncGenObject as AsyncGenerator, PyCoroObject as Coroutine,
                          PyGenObject as Generator)

__all__ = ["Generator", "Coroutine", "AsyncGenerator"]
