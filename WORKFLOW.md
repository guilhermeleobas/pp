# How work gets done in pp

The orchestrator (main Claude session) writes briefs, routes work and merges.
It does not write code, review code, run gates or make accept/reject calls.
Those belong to subagents, each in its own git worktree.

## Roles

| Role | Model | Works in | Output |
|---|---|---|---|
| Implementer | Sonnet (Opus if Sonnet's work is rejected twice) | own worktree, branch `impl/<task>` | commits on its branch |
| Tester | Sonnet | own worktree, branch `test/<task>` | blind tests on its branch; never reads `pp/` changes of the task |
| Reviewer | Opus | read-only, against the implementer's branch | findings with reproducers |
| Gate | Sonnet | own worktree, merges `impl/<task>` + `test/<task>` | test + CPython-test numbers vs baseline |
| Judge | Opus | read-only | `MERGE` / `FIX` / `REJECT` with reasons, given reviewer + gate reports |

Flow for a task: implementer ∥ tester → reviewer ∥ gate → judge →
`MERGE`: orchestrator merges both branches into `main`, regenerates the
dashboard, commits · `FIX`: judge's list goes back to an implementer on the
same branch · `REJECT`: branch dropped, task re-briefed (possibly on Opus).

## Rules for every agent in a worktree

1. First run `bash tools/setup_worktree.sh` (links `vendor/` and the main pixi
   environment). Run Python as `pixi run ...`.
2. Commit small, focused commits on your branch, ending with the attribution
   line. Never push, never touch `main`.
3. Never commit generated files: `STATUS.md`, `docs/dashboard.html`,
   `tools/test_results.json`. Only the orchestrator regenerates them on `main`.
4. Final report states the branch name and the last commit hash.

## Gate

- `pixi run test` green.
- `pixi run cpython-tests` in the gate's worktree: no module's passed count
  below the baseline in `main`'s `STATUS.md`.
- Gate reports the per-module table (baseline → branch) and any drop with the
  regressed test names.

## Remote and machines

- GitHub: `guilhermeleobas/pp` (private). Development is local; no pull
  requests. The orchestrator pushes `main` from time to time (after merges).
  Agent branches stay local unless a remote session needs them.
- Extra capacity: the `build machine` SSH host runs separate Claude sessions with a
  clone at `~/git/pp`. Use it for CPU-heavy gate runs and independent tasks.
  Remote sessions push their branch (`impl/<task>`, `test/<task>`) to GitHub;
  the orchestrator fetches and merges it like a local branch.

## Budget

The user's Claude quota is shared with other work, so keep usage modest:

- At most two agents running at once; Sonnet by default. Opus only for the
  reviewer and judge, with compact briefs and capped finding counts.
- Prefer one combined reviewer+judge pass for small changes.
- Check usage between tasks; above ~50% of the session limit, pause new work
  and ask the user.
