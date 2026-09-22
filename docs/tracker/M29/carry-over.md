# M29 — carry-over
Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## From M29.1, review round 1 — Medium

**`docs/product/backlog.md` is classified monolithically as living, and it is
half a record.** `docs/records-and-living-documents.md:59` and
`docs/tracker/M29/step-notes.md:80` both say `living | reword` for the whole
file. But the file carries its own `## Журнал решений` section (from line 533),
a dated decision journal in the same `| Date | Decision | Reason |` shape as
`docs/decisions.md` — which that very document treats as append-only. The row
`2026-08-01 (ohno-6)` records a transport decision whose text contains
"friend-facing вариант".

The same "half record, half living" lens was applied correctly to
`docs/PLAN.md` (its dated sections carved out) and even to migration comments,
but not to this file — which M29.1 added to scope on its own initiative rather
than from the owner's enumerated list, and that is exactly where the miss is
costliest.

**Left open because** M29.1 renamed nothing, so nothing is wrong in the tree
today. **It must be closed before M29.7 executes**, which is the step that
rewords the living documents and would otherwise follow the table literally and
falsify a record. M29.7's brief carries this finding as a required input.

**Shape of the fix:** a carve-out row saying `## Журнал решений` is a record and
stays untouched, while the mutable backlog above it (roadmap items, statuses,
IDs, the "Как читать этот файл" prose) is living; then extend the record check
to cover that slice before M29.7 runs.

## From M29.1, accepted residuals (not defects)

- **`docs/tracker/field-checklist.md`** holds 56 occurrences in a file that is a
  live instrument rather than a record, but it sits inside the owner's
  path-drawn never-touched set. Path wins. The residual — a checklist saying
  *friend* in front of a panel saying *user* — is accepted. Closing it means
  promoting the file out of `docs/tracker/`, which is the owner's call, not a
  step's.
- **No pointer in `CLAUDE.md`** to `docs/records-and-living-documents.md`, which
  is where an agent would actually look. M29.7 owns that file with the owner's
  sanction and should add the one line. Until then discoverability rests on the
  `docs/decisions.md` row and the step notes.

## From M29.2b, review round 1 — Low, and it is not M29's

**`tests/e2e/` is linted by no Makefile target.** `make test-edge` runs
`ruff check edge tests/edge` and `pytest tests/edge` (Makefile:93); `tests/e2e/`
appears in neither half, and the same is true of the other zones' targets. So the
e2e scenarios — which are real Python and are the only tests that prove the
product works end to end — have been unlinted since they were written.

Measured consequence today: **7 ruff errors** (4×`E501`, 3×`F541`) in
`tests/e2e/edge/test_a_crash_looping_container_is_not_reported_as_running.py` and
`tests/e2e/edge/test_the_serving_check_meets_the_real_daemon.py`. Both files are
untouched by M29 and both errors pre-date its baseline — confirmed independently
by the reviewer.

**Left open because** widening a lint target changes what the gate means for every
future change, which is an owner/architect call and not something a rename
milestone gets to decide. **Not a blocker for anything in M29.**

## From M29.3 — a flake nobody could reproduce, Low

`tests/control/test_a_daemon_that_did_not_come_back_on_this_config_fails_loudly`
failed **once**, during the builder's first full run, on `node.state == DEGRADED`
while the captured log showed the service had already set `degraded` — the shape of
a stale identity-map read. It then passed alone, passed with every alphabetically
preceding file, passed in the final full run, and passed five more times in
isolation for the reviewer.

**Left open because** neither agent could reproduce it and a test that cannot be
made to fail cannot be fixed with confidence. Recorded rather than dropped because
the tree has **no `pytest-randomly`**, so ordering is stable — which means a
failure that appears once and then vanishes is not explained by shuffling, and that
is the unsettling part. If it returns, the first place to look is session identity
rather than the assertion.

## From M29.3b — the port table does not mention a third block, Low

`tests/e2e/infra/test_restore_proves_the_backup.py` stands up two disposable
compose projects on **54300 / 54301 / 54305**, which is outside the 54100–54299
block `CLAUDE.md` documents as this project's own. Confirmed **pre-existing** —
the constants are unchanged from before M29's baseline — so it is neither this
step's doing nor its to fix.

**Left open because** the fix is either a documentation change to `CLAUDE.md`'s
port section (it belongs to no zone and is the owner's file) or moving a working
scenario's ports, and neither is a rename milestone's business. Worth someone's
decision: the published-port block is written down precisely so a third stack
cannot collide with the host, and a scenario quietly living outside it is the
case that rule exists to prevent.

---

## CLOSED by M29.4 — the flake from M29.3

The entry above ("a flake nobody could reproduce") is **resolved**, not still open.
`test_a_daemon_that_did_not_come_back_on_this_config_fails_loudly` was a stale
identity-map read in the test harness — `expire_on_commit=False` plus a setup helper
writing through the test's own session while the apply wrote through the request's.
Fixed with one `session.expire_all()` before the re-read, in commit `708441e`.

**Not reachable in production**, and that was established rather than assumed: every
route gets a fresh session per request with an empty identity map, so a `GET` after a
`POST` always issues a real query. The reviewer also patched the service to write the
wrong state and confirmed the fixed test still fails loudly.

Causation stays unsettled: HEAD failed 5/5, baseline failed 2/3 — the builder
reproduced it at baseline and the reviewer did not. Timing- or environment-sensitive.
Recorded because the next person to see a once-in-three failure in this suite should
know this shape exists and where to look.

## From M29.5 — the deployed control plane is seven revisions behind, Medium

**Measured on the owner's live box, 2026-09-22, and confirmed by the reviewer: its
`alembic_version` is `0002`.** Its control image predates `0003` — there is no
`audit_entries` table — and it has been running since 2026-09-09.

`deploy/docker/entrypoint.sh:45` runs `alembic upgrade head` **unconditionally on
every boot**. So **the next time that image is updated, one container start will apply
`0003` through `0009` — seven migrations, including this milestone's two.** That is
not M29's doing and nothing was changed about it.

Two consequences worth the owner's attention:

- The rehearsal validated `0007`→`0008`→`0009` and back. The jump that will actually
  happen on that box is larger, and no run of ours has exercised `0003`–`0007` against
  its data. They are this repository's own migrations and were green in every suite,
  but "rehearsed" and "will run" are not the same set here.
- **A schema rollback does not survive a restart.** Downgrading to `0007` without also
  rolling the image back is undone by the next boot, because the entrypoint's upgrade
  is unconditional. M29.7's runbook sentence says so.

**Left open because** updating that deployment is not this milestone's work and is the
owner's call about their own fleet.

## From M29.5 — the test hosts' addresses are already in tracked records, Low

The reviewer noticed while checking this step leaked nothing: **the authorised host's
address already appears in tracked files** — `docs/tracker/M3/`,
`docs/tracker/field-checklist.md`, `docs/PLAN.md:3497`, `docs/tracker/M26/walk-*.md`
and `docs/tracker/M16/acceptance.md`. All pre-date M29 by months, and M29.5 added
nothing.

`CLAUDE.md`'s rule is about hardcoding an address **in code**, and these are field
records of what was walked and when, which the record/living-document line says must
not be rewritten. So this is not a violation to fix by editing. **It is the owner's
call** whether a record naming a real host is a record they want to keep in a
repository, and it is recorded here rather than acted on.

## From M29.6, review round 1 — the round trip is never re-checked for schema drift, Low

`test_migrations.py` runs `compare_metadata` on a plain `empty → head` chain, and
M29.6 runs `head → 0007 → head` **with data** but never re-checks the metadata
afterwards. So a regression specific to the down-then-up sequence — the reviewer's
example is `_rename_constraint_if_present`'s guard silently no-opping because the
prior name no longer matches after a downgrade, leaving a constraint under the wrong
name — would move no byte, no token and no census value, and nothing in the tree
would catch it.

**Left open because** it is a schema-integrity question orthogonal to M29's promise
("nothing on anybody's device changed"), which M29.6 proves from three independent
angles. The fix is small and belongs to whoever next touches the migration tests:
add `compare_metadata` after the final `upgrade head`, either in M29.6's file or in
`test_migrations.py`'s own round-trip test.
