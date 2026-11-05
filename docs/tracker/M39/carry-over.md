# M39 — carry-over
Non-blocking findings left open, as background. Do not fix them as part of another step.

## M39.1 (round 1 clean + 2 Medium & 1 Low fixed in round-1 fixes; round 2 clean)

- Resolved in round-1 fixes: botmain.py had no tests (now 3) and the heartbeat path could drift (now pinned by an ast test); the crash-vs-clean-exit path was misleading (now logged honestly, comment corrected); the "byte-identical through the cache" comment softened.
- Note (reviewer, round 2): the blank-token test asserts no box/poller bound but does not also assert the `bound_settings`/`db_url` recorders stay unset — a strictness gap, not a defect.
- **Process note:** `make verify` (e2e) is red from M39.1 until the stand re-point lands. Keep all M39 steps on one branch and gate the milestone close on a green e2e AFTER the re-point, so nothing merges red.

## Stand re-point step (review round 1: clean; 1 Medium = a pre-existing flake)

- Medium, judged a pre-existing flake, not this diff's: `tests/e2e/control/test_a_backup_that_did_not_land_is_on_the_screen_the_owner_opens.py::test_six_weeks_of_failure_is_on_the_overview_the_panel_opens_on` failed once in a full `make e2e-verify` ("The last one that succeeded was 43 days ago" — six weeks is 42, an off-by-one day-boundary), and passed on a fresh rerun. The diff touches nothing near backups/overview/clock. Treated as a flake per the retry-once rule; recorded for the owner as a relative-date test fragility worth a small fix someday. Watch for it in the M39 close gate.
