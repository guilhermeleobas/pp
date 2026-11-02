# pp

A Python 3.15 bytecode interpreter written in Python.

pp runs Python programs with an eval loop, frames, generators, an import
system and an object protocol written in Python. It mirrors CPython's own
structures (`_PyInterpreterFrame`, `PyGenObject`, type slots, `binary_op1`,
`_PyObject_GenericGetAttrWithDict`, ...), with CPython 3.15 as the reference
for behavior. Pure-Python stdlib modules run inside the VM with their C
accelerators blocked, so the Python fallbacks are what execute.

It is an experiment, not a production interpreter: it is slow, and for now it
still borrows from the host CPython the compiler, the value types (`int`,
`str`, `dict`, ...) and a list of C modules (see `pp/importer.py`).

## Quick start

Requires [pixi](https://pixi.sh).

```bash
pixi run pp run script.py        # run a script under pp
pixi run pp dis script.py        # pp's own disassembly
pixi run test                    # unit and differential tests
pixi run cpython-tests           # CPython's Lib/test for tracked modules
```

## Status

[STATUS.md](STATUS.md) (also rendered as `docs/dashboard.html`) tracks, per
stdlib module, how many of CPython's own tests pass under pp, plus what is in
progress. Known blockers are in [BLOCKERS.md](BLOCKERS.md).

## Docs

- [DESIGN.md](DESIGN.md) — architecture, host boundary, milestones.
- [WORKFLOW.md](WORKFLOW.md) — how the work is organized.
