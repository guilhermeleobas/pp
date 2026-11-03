"""Classify stdlib modules, run their CPython tests under pp, and write STATUS.md.

    python tools/stdlib_status.py            # classify only, keep previous results
    python tools/stdlib_status.py --run      # also run each module's CPython test under pp
    python tools/stdlib_status.py --run json heapq   # run only these modules
"""

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "3.15.2"
LIB = os.path.join(ROOT, "vendor", f"cpython-{VERSION}", "Lib")
RESULTS = os.path.join(ROOT, "tools", "test_results.json")
STATUS = os.path.join(ROOT, "STATUS.md")
TEMPLATE = os.path.join(ROOT, "tools", "dashboard_template.html")
DASHBOARD = os.path.join(ROOT, "docs", "dashboard.html")
TIMEOUT = 600

# Modules tracked by STATUS.md and the dashboard, mapped to their tier (the order we
# plan to support them in). Tiers follow what `unittest` needs to run under pp.
TIERS = {
    1: ["operator", "keyword", "types", "functools", "collections", "heapq", "reprlib", "copyreg", "itertools"],
    2: ["enum", "contextlib", "warnings", "weakref", "abc", "string", "textwrap", "fnmatch", "re"],
    3: ["traceback", "difflib", "pprint", "argparse", "unittest"],
    4: ["bisect", "colorsys", "copy", "dataclasses", "graphlib", "json", "fractions", "statistics", "shlex",
        "glob", "posixpath", "tomllib", "base64", "html", "csv", "ipaddress", "random", "typing", "decimal",
        "datetime", "inspect", "dis", "ast", "queue", "calendar", "optparse", "configparser", "array", "gc",
        "struct", "binascii", "zlib", "gzip"],
}
TRACKED = {m: t for t, mods in TIERS.items() for m in mods}

# Modules we do not plan to support fully: what is out of scope and why. Shown next to
# the module's test counts, so "partial" there is expected rather than a regression.
# Example: SCOPE_NOTES = {"weakref": "GC-timing tests depend on host refcounting"}
SCOPE_NOTES = {
    "weakref": "weak references never die and callbacks never fire (host objects; see pp/lib/_weakref.py)",
    "gc": "collect() frees nothing; object enumeration is empty (see pp/lib/gc.py)",
}

# Modules whose pure-Python twin lives under a different name.
PY_TWINS = {"decimal": "_pydecimal", "io": "_pyio", "datetime": "_pydatetime"}


def c_modules():
    names = set(sys.builtin_module_names)
    dynload = os.path.join(sys.base_prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "lib-dynload")
    if os.path.isdir(dynload):
        names.update(f.split(".")[0] for f in os.listdir(dynload) if f.endswith(".so"))
    return names


def source_path(name):
    for p in (os.path.join(LIB, name + ".py"), os.path.join(LIB, name, "__init__.py")):
        if os.path.exists(p):
            return p
    return None


def test_path(name):
    for p in (os.path.join(LIB, "test", f"test_{name}.py"), os.path.join(LIB, "test", f"test_{name}")):
        if os.path.exists(p):
            return p
    return None


def classify():
    cmods = c_modules()
    rows = []
    for name in sorted(sys.stdlib_module_names):
        if name.startswith("_") or name in ("test", "idlelib", "turtledemo", "this", "antigravity"):
            continue
        src = source_path(name)
        accel = f"_{name}"
        if src is None:
            kind = "C only"
        elif name in PY_TWINS or (accel in cmods and accel in open(src, encoding="utf-8", errors="replace").read()):
            kind = "Python + C helper"
        else:
            kind = "Python"
        tp = test_path(name)
        rows.append({"module": name, "kind": kind, "test": os.path.relpath(tp, LIB) if tp else None})
    return rows


def run_test(row):
    module = "test." + os.path.basename(row["test"]).removesuffix(".py")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([ROOT, LIB]))
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pp", "run", os.path.join(ROOT, "tools", "run_unittest.py"), module],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=ROOT, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"result": "timeout", "detail": f">{TIMEOUT}s"}
    out = proc.stdout + proc.stderr
    counts = unittest_counts(out)
    passed, total = counts["passed"], counts["total"]
    last = next((l for l in reversed(out.strip().splitlines()) if l.strip()), "")
    if total:
        if passed == total and proc.returncode == 0:
            return {"result": "pass", "detail": "", **counts}
        return {"result": "partial" if passed else "fail", "detail": last[:120], **counts}
    if "UnimplementedOpcode" in last:
        return {"result": "blocked", "detail": last.split(":", 1)[-1].strip(), **counts}
    return {"result": "fail", "detail": last[:120], **counts}


def unittest_counts(out):
    """Counts from unittest's "Ran N tests" / "FAILED (failures=a, errors=b, skipped=c)" summary.

    Returns passed/total plus failures/errors/skipped (unexpected successes count as failures).
    """
    m = re.search(r"^Ran (\d+) tests?", out, re.M)
    if not m:
        return {"passed": 0, "total": 0, "failures": 0, "errors": 0, "skipped": 0}
    total = int(m.group(1))
    found = {}
    for k, n in re.findall(r"\b(failures|errors|skipped|unexpected successes)=(\d+)", out):
        found[k] = found.get(k, 0) + int(n)
    failures = found.get("failures", 0) + found.get("unexpected successes", 0)
    errors, skipped = found.get("errors", 0), found.get("skipped", 0)
    return {"passed": max(total - failures - errors - skipped, 0), "total": total,
            "failures": failures, "errors": errors, "skipped": skipped}


def _host_modules():
    """Read the HOST_MODULES groups from pp/importer.py without importing pp."""
    import ast
    tree = ast.parse(open(os.path.join(ROOT, "pp", "importer.py"), encoding="utf-8").read())
    groups = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call):
            name = node.targets[0].id
            if name in ("HOST_MODULES_PERMANENT", "HOST_MODULES_TEMPORARY") and node.value.args:
                groups[name] = set(ast.literal_eval(node.value.args[0]))
    return groups.get("HOST_MODULES_PERMANENT", set()), groups.get("HOST_MODULES_TEMPORARY", set())


PERM_HOST, TEMP_HOST = _host_modules()


def text_bar(passed, total, width=10):
    filled = round(width * passed / total) if total else 0
    return f"`{'█' * filled}{'░' * (width - filled)}` {int(100 * passed / total)}%"




def write_status(rows, results):
    counts = {}
    for r in rows:
        res = results.get(r["module"], {}).get("result", "untested" if r["test"] else "no test")
        got = results.get(r["module"], {})
        r["result"], r["detail"] = res, got.get("detail", "")
        r["passed"], r["total"] = got.get("passed", 0), got.get("total", 0)
        # Old result files lack these: None means unknown (bar shows passed/total only).
        for k in ("failures", "errors", "skipped"):
            r[k] = got.get(k)
        r["note"] = SCOPE_NOTES.get(r["module"], "")
        counts[res] = counts.get(res, 0) + 1
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1

    blockers = {}
    for r in rows:
        if r["result"] == "blocked":
            blockers[r["detail"]] = blockers.get(r["detail"], 0) + 1

    if not rows:
        with open(STATUS, "w") as f:
            f.write("# pp stdlib status\n\n" + "No modules tracked yet. Add names to `TRACKED` in `tools/stdlib_status.py`.\n")
        write_dashboard(rows, counts, kinds, blockers)
        return
    lines = [
        "# pp stdlib status",
        "",
        f"Generated by `pixi run status` on {date.today()} against CPython {VERSION} `Lib/test`.",
        "",
        "A module counts as **pass** when its CPython test file runs to completion under `pp`",
        "(`python -m pp run tools/run_unittest.py test.test_<module>`). The test file and every pure-Python module it",
        "imports run in the VM; C modules come from the host only if listed in `pp/importer.py`.",
        "",
        f"Host C modules still borrowed: {len(TEMP_HOST)} temporary (to replace with Python), "
        f"{len(PERM_HOST)} permanent (host boundary).",
        "",
        "Temporary: " + ", ".join(f"`{m}`" for m in sorted(TEMP_HOST)),
        "",
        "## Summary",
        "",
        "| Result | Modules |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])],
        "",
        "| Kind | Modules | What pp needs |",
        "|---|---|---|",
        f"| Python | {kinds.get('Python', 0)} | run the `.py` source through the VM |",
        f"| Python + C helper | {kinds.get('Python + C helper', 0)} | use its Python fallback if it has one, else reimplement the `_<name>` C helper |",
        f"| C only | {kinds.get('C only', 0)} | reimplement in Python under `pp/lib/` |",
        "",
    ]
    if blockers:
        lines += ["## Top blockers", "", "| Missing | Modules blocked |", "|---|---|"]
        lines += [f"| `{k}` | {v} |" for k, v in sorted(blockers.items(), key=lambda kv: -kv[1])[:15]]
        lines.append("")
    lines += ["## Modules", "", "| Tier | Module | Kind | CPython test | Result | Tests passed | Out of scope | Detail |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['tier']} | {r['module']} | {r['kind']} | {r['test'] or '—'} | {r['result']} | {f"{text_bar(r['passed'], r['total'])} {r['passed']}/{r['total']}" if r['total'] else '—'} | {r['note']} | {r['detail'].replace('|', '/')} |")
    with open(STATUS, "w") as f:
        f.write("\n".join(lines) + "\n")
    write_dashboard(rows, counts, kinds, blockers)


def write_dashboard(rows, counts, kinds, blockers):
    data = {
        "generated": str(date.today()),
        "cpython": VERSION,
        "counts": counts,
        "kinds": kinds,
        "blockers": sorted(blockers.items(), key=lambda kv: (-kv[1], kv[0]))[:15],
        "rows": rows,
    }
    # "</" is escaped so the JSON can never close its <script> tag early.
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read().replace("__DATA__", blob)
    os.makedirs(os.path.dirname(DASHBOARD), exist_ok=True)
    with open(DASHBOARD, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("modules", nargs="*")
    args = ap.parse_args()
    if not os.path.isdir(LIB):
        sys.exit("CPython Lib missing: run `pixi run fetch-cpython`")
    rows = sorted((dict(r, tier=TRACKED[r["module"]]) for r in classify() if r["module"] in TRACKED),
                  key=lambda r: (r["tier"], list(TRACKED).index(r["module"])))
    results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {}
    if args.run:
        todo = [r for r in rows if r["test"] and (not args.modules or r["module"] in args.modules)]
        with ThreadPoolExecutor(os.cpu_count()) as ex:
            for row, res in zip(todo, ex.map(run_test, todo)):
                results[row["module"]] = res
        with open(RESULTS, "w") as f:
            json.dump(results, f, indent=1, sort_keys=True)
    write_status(rows, results)
    print(f"wrote {os.path.relpath(STATUS, ROOT)}")


if __name__ == "__main__":
    main()
