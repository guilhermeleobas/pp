# Contributing to pp

All contributions to pp come from AI agents. A human sets the direction and an
orchestrator agent hands out tasks. Other agents implement, test, review and
decide. This file is the contract every agent follows. The roles and the
review flow are in [WORKFLOW.md](WORKFLOW.md).

## Before you start

Read these, in this order:

1. [DESIGN.md](DESIGN.md): architecture, the host boundary, and the rules for
   code under `pp/`.
2. [WORKFLOW.md](WORKFLOW.md): roles, the review flow, the gate, and budget.
3. [ROADMAP.md](ROADMAP.md): what is done, in review, next, and missing.
4. [BLOCKERS.md](BLOCKERS.md): known blockers. Check here before
   rediscovering one.

Your brief names your role, branch and scope. Stay inside that scope. If the
brief and these documents disagree, follow the brief and say so in your
report.

## Setup

```bash
git fetch origin
git worktree add ../pp-<task> -b <role>/<task> origin/main
cd ../pp-<task>
bash tools/setup_worktree.sh     # links vendor/ and the pixi env
pixi run test                    # must be green before you change anything
```

In a fresh clone (not a worktree), run `pixi run fetch-cpython` once. It
downloads CPython's `Lib/` at tag v3.15.2 into `vendor/`. Always use that tag.

## Ground rules

- **CPython 3.15.2 is the ruler.** Read sources at the `v3.15.2` tag
  (`git show v3.15.2:<path>` in a CPython checkout), not a working tree on
  another version. Behavior, error messages and structure follow CPython (`Python/ceval.c`, `Objects/typeobject.c`,
  `Objects/abstract.c`, `Modules/*.c`, ...). Mirror CPython's names and
  structures, but add a slot or a field only when something reads it.
- **Host boundary.** The VM (`pp/*.py`) is host code. It may import only the
  allow-list in DESIGN.md. Never import `dis`, `ctypes` or C test modules.
  `tests/test_host_boundary.py` enforces this.
- **No borrowed C modules.** When guest code needs a C module, write a
  pure-Python replacement in `pp/lib/` under the C module's name. Limitations
  are fine if you document them in the module docstring and in BLOCKERS.md.
- **`pp/lib/` is guest code.** It may import other `pp/lib` modules,
  pure-Python stdlib modules and the `HOST_MODULES` list, all through the VM
  importer. It never imports `pp.*`.
- **Don't stall on blockers.** Record the blocker in your report under
  "Blockers", park that part, and finish the rest.

## Testing

- **Differential snippets** (`tests/snippets/*.py`): each one runs under host
  Python and under pp, and the outputs must match. Add one for every
  behavior you fix or add.
- **Host-side tests** (`tests/test_*.py`): use them for checks a snippet
  can't express, such as object lifetime seen through the host's
  `gc`/`weakref`, or decoder output compared with `dis`.
- **CPython's own tests**: `pixi run cpython-tests` runs Lib/test for every
  tracked module. No module's passed count may drop below `main`'s
  `tools/test_results.json`. If a drop is expected, list the test names and
  the reason.
- To run one module: `pixi run python -m pp run tools/run_unittest.py
  test.test_X`, with `PYTHONPATH=<worktree>:<worktree>/vendor/cpython-3.15.2/Lib`.
- Performance work needs before/after timings for every change.

## Commits and branches

- Branch name: `impl/<task>`, `test/<task>`, `perf/<task>` or
  `scout/<task>`.
- Make small, focused commits. End each commit message with your model's
  attribution line, for example
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Never commit generated files: `STATUS.md`, `docs/dashboard.html` and
  `tools/test_results.json`. Only the orchestrator regenerates them, on
  `main`.
- Never push to `main`. After a rebase, push with `--force-with-lease`.
- External contributors: fork the repository and open a pull request
  against `main`. The pull request goes through the same review, gate and
  judge steps.
- Agents working inside the project's own orchestration push their branch
  to this repository instead, and the orchestrator merges it.
- Rebase onto `origin/main` before asking for review.
