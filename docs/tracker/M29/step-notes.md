# M29 — step notes
Conventions established here. They bind later steps, and later milestones in
this codebase, until something supersedes them. Follow them; do not relitigate.

## M29.1 — the line, and the decisions (renamed nothing)

**The record/living-document line lives in `docs/records-and-living-documents.md`.**
Read it before you touch anything in bulk. It is not a summary of this milestone;
it is the durable home, deliberately outside `docs/PLAN.md` because M29.1's own
plan text becomes a record the day M29 is marked `✅`, and a future bulk edit will
not look it up there.

The short of it, so you cannot miss it:

- **Never reworded:** `docs/tracker/**` (including this file once it is written),
  the existing rows of `docs/decisions.md`, the already-applied Alembic
  migrations, git history, and **three parts of `docs/PLAN.md`**: every `## ✅`
  milestone, `## Decisions needed from you`, and `## Where the field run left the
  plan, 2026-09-09`. The middle one is the easy miss — its decision 9, answered
  by the owner on 2026-09-08 with *"`friend` stays the word in the models, the
  services, the API and the tests"*, is the decision M29 reverses, and rewording
  it erases the fact that it was ever decided the other way.
- **Reworded:** the charter, `docs/deploy/runbook.md`, `docs/product/backlog.md`,
  `docs/security/threat-model.md`, `README.md`, `CLAUDE.md`, `.claude/**`, the
  plan's `## →` (open) milestones and its `## What this plan does not cover`, and
  all other code, templates and tests.
- **"Never touched" forbids rewording, not adding.** This milestone may add new
  files under `docs/tracker/M29/`; the check looks for *removed and changed
  lines*, never for a changed directory. `docs/decisions.md` shows as modified in
  every such diff because rows were appended — that is correct.

**M29.7 must verify the records by diff, not by intention.** Run this from the
repository root; M29's baseline is `1b60280`. Both must print nothing:

```sh
git diff 1b60280 -- docs/tracker/ | grep -E '^-[^-]'
git diff 1b60280 -- docs/decisions.md | grep -E '^-[^-]'
SLICE='/^## /{k = /^## ✅|^## Decisions needed from you|^## Where the field run left the plan/} k'
diff <(git show 1b60280:docs/PLAN.md | awk "$SLICE") <(awk "$SLICE" docs/PLAN.md)
```

Run them at the *start* of your step too, so a failure at the end is known to be
yours.

## Conventions every remaining M29 step follows

1. **The word is `user`.** Singular `user`, plural `users`, adjectivally
   `user_id`, `UserRow`, `users_table.html`. Owner-settled 2026-09-22; recorded
   in `docs/decisions.md`.
2. **A bare `user` means the person who uses hashi.** The other two meanings are
   never written bare and must not be "fixed" to look like it: a node's account
   stays `ssh_user`, the panel login stays `operator` / `HASHI_OPERATOR_USERNAME`
   / `--user` in `scripts/node-bootstrap.sh`. The three-way collision was put to
   the owner against `subscriber` and accepted knowingly — do not reopen it, and
   do not invent a fourth spelling to dodge it.
3. **No aliases, no deprecation window.** `/api/friends/*` → `/api/users/*`,
   `/panel/friends/*` → `/panel/users/*`. Do not leave a redirect, a second route
   or a compatibility shim "just for a while". `/sub/{token}` does not change.
4. **Already-applied migrations keep every word**, including their comments and
   docstrings, their file names and their revision ids. Six of the seven mention
   the old word (`0001`, `0002`, `0003`, `0004`, `0006`, `0007`); none of them is
   edited. M29.3's rename is a **new** migration on top of `0007`, reversible
   both ways. Rewording `0001` would make a fresh database disagree with a
   deployed one while both report the same revision.
5. **Prose is renamed with the same care as identifiers.** Most of the ~3650
   occurrences are comments and docstrings; a comment left saying *friend* beside
   a symbol saying `user` is the exact half-finished state this milestone exists
   to end.

## Things M29.7 will otherwise miss

The plan's living-document list is shorter than the corpus. Measured at baseline
`1b60280` with `grep -oi friend <file> | wc -l`:

| file | occurrences | on the plan's list? |
|---|---|---|
| `docs/PLAN.md` | 212, of which **151 are record and stay** (144 in `## ✅` milestones, 7 in the two dated tail sections) — **61 are movable** | yes, open milestones only |
| `docs/deploy/runbook.md` | 67 | yes |
| `docs/product/charter.md` | 15 | yes |
| `docs/product/backlog.md` | 8 | **no** — classified living by the test |
| `docs/security/threat-model.md` | 5 | **no** — classified living by the test |
| `.claude/projects/00-core-invariants.md` | 2 | **no** — classified living by the test |
| `CLAUDE.md` | 2 | yes |
| `README.md` | 1 | yes |

`CLAUDE.md` and `.claude/**` are owner/architect territory. They are on the
living side of the line and the owner put `CLAUDE.md` there explicitly, so M29.7
rewords them — but nothing beyond the vocabulary, and no new rule rides along.

**One accepted residual:** `docs/tracker/field-checklist.md` holds 56
occurrences and is a live instrument the owner carries to the hosts, not a
record of what happened. The owner drew the line by path (`docs/tracker/**`), so
the path wins and the checklist keeps the old word — a checklist saying *friend*
in front of a panel saying *user*. Closing that means promoting the file out of
`docs/tracker/`, which is the owner's call and is not M29's to take on the way
past.

## How to test what M29.1 built

Nothing to fixture: this step added two documents and four journal rows and
changed no code. Its gate was `make verify` (the whole gate, because `docs/**`
belongs to no zone), and nothing in it is specific to this step.

What the *later* steps should reuse is the three-command record check above —
paste it, do not re-derive it. The `awk` idiom turns the accumulator on at a
record heading and off at the next `## ` of any kind, which is what lets one file
be half record and half living document. Do not simplify it back to `## ✅` only:
that was the first version written here and it left 7 occurrences of the old word
exposed in two dated sections that must not move.

## Wording a person will see

M29.1 introduced none. The strings an operator reads are M29.4's (panel and API)
and M29.7's (charter, runbook, README); they must match the vocabulary above and
the runbook must state the API break in the words *"anything scripted against the
old paths stops working"*, per the owner's decision.
