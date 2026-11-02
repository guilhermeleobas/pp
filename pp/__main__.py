"""CLI: python -m pp run FILE | python -m pp dis FILE"""

import argparse
import sys
import types

from pp.bytecode import compile_source, decode
from pp.vm import run_file


def _dis_code(code: types.CodeType, out) -> None:
    print(f"Disassembly of {code.co_qualname} ({code.co_filename}, line {code.co_firstlineno}):", file=out)
    d = decode(code)
    for ins in d.instructions:
        arg = "" if ins.arg is None else str(ins.arg)
        tgt = "" if ins.jump_target is None else f"(to {ins.jump_target})"
        print(f"  {ins.offset:>6} {ins.opname:<28} {arg:>6} {tgt}".rstrip(), file=out)
    if d.exception_table:
        print("ExceptionTable:", file=out)
        for e in d.exception_table:
            lasti = " lasti" if e.lasti else ""
            print(f"  {e.start} to {e.end} -> {e.target} [{e.depth}]{lasti}", file=out)
    print(file=out)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            _dis_code(const, out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pp")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="execute FILE under the VM")
    p_run.add_argument("file")
    p_run.add_argument("args", nargs=argparse.REMAINDER)
    p_dis = sub.add_parser("dis", help="print pp's decoding of FILE")
    p_dis.add_argument("file")
    ns = parser.parse_args(argv)

    if ns.command == "run":
        sys.argv = [ns.file] + ns.args
        try:
            run_file(ns.file)
        except SystemExit:
            raise
        except BaseException as e:
            sys.excepthook(type(e), e, e.__traceback__)
            return 1
    else:
        with open(ns.file, encoding="utf-8") as fh:
            code = compile_source(fh.read(), ns.file)
        _dis_code(code, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
