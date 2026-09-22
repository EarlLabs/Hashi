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

## M29.2 — `edge` renamed (the zone is done except its e2e scenarios)

**The vocabulary is proven.** `edge/**` and `tests/edge/**` carry no *friend*
except two deliberate keeps. `make test-edge` is green on it (911 passed, 3
skipped — `awg-quick` absent, the baseline skip).

1. **The public name is now `TransportMeta.serves_users_through_a_hop`**
   (`edge/registry.py`). `control` has NOT been updated and is red until it is.
   The complete list M29.3/M29.4 must change, measured and independently
   confirmed: `control/app/services/nodes.py:732` and
   `control/app/services/relay.py:425` (calls), `control/app/errors.py:250` and
   `control/app/services/transports.py:280` (prose), and
   `tests/control/test_both_doors_refuse_a_friend_with_no_way_out.py` (lines 48,
   53, 205, 457, 468 — and the file name itself). `grep -rn` over `control/`,
   `tests/control/` and `tests/e2e/` returns exactly those sites and no others.

2. **HOW RED THE TREE IS BETWEEN HERE AND M29.4 — measured, not estimated.**
   M29.2's own hand-off first said "one collection error and one runbook
   mismatch", and review round 1 disproved it. The true state after M29.2:

   - static: `tests/control` has **1 collection error** (the file above) and is
     otherwise green (216 passed, 670 skipped for want of Postgres — the
     baseline shape); `tests/infra` has **1 failure** (item 3 below), 240 passed;
     `make test-edge` is fully green.
   - e2e: **28 failed and 5 errors** across `tests/e2e/control/` and
     `tests/e2e/infra/`. Every one of them is the SAME root cause as the
     collection error — `control` calling the renamed property unconditionally
     on every "enable a transport" and "establish a hop" path. The container log
     carries the identical `AttributeError: 'TransportMeta' object has no
     attribute 'serves_friends_through_a_hop'` traceback on all 31
     `internal_error` 500s; the remaining 2 are `Server disconnected` cascading
     from the same crash, not a distinct defect.

   **So essentially all of `tests/e2e/control/` and `tests/e2e/infra/` is
   blocked until M29.3/M29.4 migrate the callers** — it is not "mostly green
   with two known failures", and nothing downstream should rely on it being so.
   Do not read a green-ish `make verify` summary as progress before M29.4.

3. **A seam nobody predicted: `docs/deploy/runbook.md` quotes `edge`'s error
   strings verbatim and `tests/infra/` pins the quotation.**
   `tests/infra/test_deploy_runbook.py` imports `edge.egress.NO_RESOLVER` and
   asserts the runbook contains it word for word. `NO_RESOLVER` now says "the
   destinations its **users** ask for"; the runbook still says *friends*, so
   `make test-infra` fails one test and **`make verify` cannot be green until
   the runbook sentence moves, which is M29.7's**. Any step between M29.2 and
   M29.7 that gates on `make verify` is gating on something already red for a
   reason it did not cause. Gate on the zone's own verify instead.

4. **`tests/e2e/edge/**` is in the old vocabulary — 94 occurrences.**
   `CLAUDE.md` puts it in the `edge` zone, but M29.2's fence was `edge/**` +
   `tests/edge/**` and M29.7's E2E note named only `tests/e2e/control/`. It
   holds a file name (`test_a_friend_exits_at_the_leaf_and_not_at_the_entry.py`)
   and four identifiers (`NO_FRIEND_HERE`, `FRIEND_TRANSPORTS`, `FRIEND_PORT`,
   `FRIEND_ATTEMPTS`), so the milestone's "no identifier in `control` or `edge`
   still carries the old one" was not reachable by the seven steps as written.
   **M29.2b was added to the plan to take it**, rather than leaving a Done-when
   the milestone cannot satisfy.

5. **Two occurrences are KEPT and must not be "finished" by a later step.**
   `edge/health/listening.py:36` says "``/proc/net/tcp`` and friends" — English
   for "and similar files", not a person. And
   `tests/edge/test_a_tunnel_carries_traffic_off_the_node.py:583` cites the path
   `tests/e2e/edge/test_a_friend_exits_at_the_leaf_and_not_at_the_entry.py`,
   which must keep naming the file that actually exists — so it moves only when
   M29.2b renames that file, and then it moves with it.

6. **`docs/decisions.md:104,110` name `edge.egress._friend_rules`**, now
   `_user_rules`. Those rows are record and stay as written; the symbol they
   point at has moved. Accepted, not fixed.

### How to test what M29.2 built

`make test-edge` — ruff plus `pytest tests/edge`, no Docker, ~8s. Nothing was
fixtured or scaffolded: the existing `tests/edge/conftest.py` fixtures
(`clients`, `credentials`, the per-transport `node` fixtures) are unchanged in
shape and only their prose moved. The three golden files under
`tests/edge/golden/` are rendered from the `.j2` templates, so **a comment
reworded in `server.j2` or `client.j2` must be reworded identically in the
golden `.conf`** — `test_golden_configs.py` compares byte for byte and will say
so. A later step reworking edge prose changes the template and re-checks the
golden, never the other way round.

### Wording a person will see

Operator-facing strings in `edge` now say *user*. The ones that matter, because
they are quoted or asserted elsewhere:

- `edge.egress.NO_RESOLVER` — "…names no resolver for the destinations its
  **users** ask for…". **`docs/deploy/runbook.md` must be changed to match this
  exact sentence** (`tests/infra/test_deploy_runbook.py` enforces it).
- `edge.egress` hop refusal — "Give this node's **users** a transport that…".
- `edge.registry` — "no **user**-facing format at all"; "so no **user** can be
  given access to it individually — and therefore no **user** could be revoked
  from it without affecting the others."
- The WireGuard/AmneziaWG `Params` field descriptions (panel- and API-visible):
  "the resolver a **USER**'s device is told to use inside the tunnel", "the
  first address given out when this transport is offered to **users**".
