# M16's commits are on `task/M17` — RESOLVED 2026-09-12

**RESOLVED.** All four commits were cherry-picked onto `task/M16` in an isolated
worktree on 2026-09-12 — `8515b90`, `a21eb8f`, `fac0d2f`, `672cc5c`. Every pick
applied cleanly. Verified afterwards: M16's own files are present
(`tests/edge/test_a_friends_lookup_leaves_through_the_hop.py`,
`control/migrations/versions/0005_a_nodes_resolver.py`), M17's are **absent**
(`edge/addressing.py`, `control/app/services/addresses.py`), no M17 step commit is
on the branch, and `make test-edge` there is **250 passed, 10 skipped, EXIT 0** —
the skips being M17.1a's tests correctly not present.

**A worktree was used deliberately**: the M17.1b review was reading the main
checkout at the time, and switching branches under it would have made it review
code that was not there. `git worktree add` left that checkout untouched.

The original record is kept below because the reasoning is the point.

## What happened

`task/M17` was branched off `task/M16` **while M16 was still in flight**, and both
milestones' agents then worked in the same checkout. So three commits that belong
to M16 landed on `task/M17`:

| commit | what it is |
|---|---|
| `5e98c65` | M16.1 round-2 fixes (control) — the resolver dialog's corrected hint |
| `e28a57c` | M16.1 round-2 fixes (docs) — the runbook's corrected sentence |
| `ff132e2` | **M16.2 complete** — the lasting DNS scenario |

`task/M16`'s tip is `1d3c1d5`, which is a **strict ancestor** of all three.

## How to put them back

**Do this only when no agent is working in the tree** — check `git status` is clean
and no `pytest`, `make`, or docker build is running.

```
git checkout task/M16
git cherry-pick 5e98c65 e28a57c ff132e2
```

Each touches only its own zone's files, so the picks should apply cleanly. Then
`make verify` on `task/M16` before closing the milestone.

## Why this was NOT done at the time — the reasoning matters

The M16.2 implementer was told to stash its work, switch to `task/M16` and pop.
**It refused, and it was right.** It checked first and found:

- Another agent (M17.1b) was writing to the same tree, with **16 modified
  `control/**` files and 3 untracked ones** at that moment.
- Those files were **byte-identical between the two branches**, so
  `git checkout task/M16` would **not** have refused or conflicted. It would have
  silently carried that agent's in-progress work onto `task/M16` and redirected
  its next commit there — **invisible from its side.**

A commit on the wrong branch is recoverable with one command. Another agent's work
silently relocated mid-edit is not. It chose the recoverable failure and handed
back the exact command.

## The lesson for the orchestrator

**Do not branch the next milestone until the current one's last commit has
landed**, and do not leave two milestones' agents sharing one checkout. If they
must overlap, they need separate worktrees (`git worktree add`), not a shared
tree on a shared branch.

## A second, related finding from the same agent

**`make e2e-verify` cannot give a trustworthy answer while another agent has
uncommitted `control/**` work in the tree** — the e2e stand builds the control
image from the **working tree**, not from `HEAD`. That run measured M17.1b's
half-built code and reported 18 failures that belonged to nobody's finished work.

It is related to `docs/tracker/M9/gate-hazard.md` but distinct: that one is about
two runs sharing one Postgres; this one is about a run measuring a tree that is
mid-edit.

**And the guard I gave agents was too narrow.** `pgrep -af "make (verify|e2e-verify|test-)"`
does not catch an agent invoking `pytest` directly — which is exactly what
happened. The pattern must include bare `pytest` and `docker build`.
