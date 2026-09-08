# M11 — outcome

**Steps:** M11.1, M11.2, M11.3, M11.4 — all built, all reviewed, **one review
round each, no Critical or High at any point**. M11.3 drew one Medium (the
runbook's headline command used angle-bracket placeholders inside a runnable
fence, so pasting it produced a shell redirection error naming neither the
command nor the unfilled field). It was fixed rather than filed, because this
milestone's whole premise is that command working under time pressure; the
implementer recorded no disagreement, and a new test pins it.

**Gate at close:** `make test` green — 153 control, 132 edge (3 skipped), 90
infra. The control zone runs against a real Postgres here, so 85 tests that CI
never runs are included in that number.

**Acceptance: half-discharged, and the milestone stays open.** The script half is
proven on two hosts of deliberately different shape. The `register it in the
panel and apply` half is blocked on M4's `draft → degraded` bug and is not
outstanding work on this milestone. Detail in `field-inventory.md` and in the
plan's own status note.

**What the hosts taught us that a test run could not:** see
`field-inventory.md` (both hosts, before and after) and `step-notes.md` §M11.4.
The one worth repeating here is the `AuthorizedKeysCommand` condition — a host
can be reachable with no `authorized_keys` file at all, and this script verifies
its own work by reading back the file it just wrote. That verification is true
on a host where sshd never consults that file. It is in `carry-over.md`.
