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
