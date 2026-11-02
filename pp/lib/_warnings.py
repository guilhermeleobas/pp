"""Pure-Python `_warnings` for the guest.

CPython's `_warnings` is the C accelerator of `warnings.py`; importlib's
bootstrap also needs the module to exist (`_warnings.warn` raises ImportWarning).
This one only forwards to the pure-Python `warnings` module and deliberately has
no `filters`/`_defaultaction`/... so that `warnings` falls back to its own
implementation, whose state is the one `catch_warnings` swaps.
"""


def warn(message, category=None, stacklevel=1, source=None, *, skip_file_prefixes=()):
    import warnings
    warnings.warn(message, category, stacklevel + 1, source,
                  skip_file_prefixes=skip_file_prefixes)


def warn_explicit(message, category, filename, lineno, module=None, registry=None,
                  module_globals=None, source=None):
    import warnings
    warnings.warn_explicit(message, category, filename, lineno, module, registry,
                           module_globals, source)
