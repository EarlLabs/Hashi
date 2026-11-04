# M39 — carry-over
Non-blocking findings left open, as background. Do not fix them as part of another step.

## M39.1 (round 1 clean + 2 Medium & 1 Low fixed in round-1 fixes; round 2 clean)

- Resolved in round-1 fixes: botmain.py had no tests (now 3) and the heartbeat path could drift (now pinned by an ast test); the crash-vs-clean-exit path was misleading (now logged honestly, comment corrected); the "byte-identical through the cache" comment softened.
- Note (reviewer, round 2): the blank-token test asserts no box/poller bound but does not also assert the `bound_settings`/`db_url` recorders stay unset — a strictness gap, not a defect.
- **Process note:** `make verify` (e2e) is red from M39.1 until the stand re-point lands. Keep all M39 steps on one branch and gate the milestone close on a green e2e AFTER the re-point, so nothing merges red.
