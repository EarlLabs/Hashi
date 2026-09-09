# M14 — outcome

**Steps:** M14.1, M14.2, M14.3 — built together, committed one per zone, **one
review round**. Verdict `0 critical, 1 high`. (The reviewer's verdict line said
"1 critical, 1 high"; its own issues table listed no Critical, and the table was
taken as authoritative.)

**The High was about a missing record, not a defect.** The implementer had found
and disclosed that the two data-plane images ship different netfilter backends,
and the reviewer confirmed it by pulling both — but nothing in the code, the plan
or a tracker file said so, and a reader of the shipped tree would have had no
signal that "the WireGuard family" is fixed for one member only. Recorded in
`carry-over.md` and in `docs/decisions.md`.

**Acceptance: yes, discharged in the field.** Evidence in `field-proof.md`. As
with the other field milestones tonight, it was walked by the run's orchestrator
rather than by an independent acceptance agent — weaker than a stand-walked
milestone, and stated rather than glossed.

**Gate at close:** `make test` green — 183 control, 210 edge (3 skipped), 96
infra.

## What made this milestone worth its cost

It exists because the previous one's second question was asked. M2 made both
containers start, and the obvious next step — *does a page load?* — turned out to
have a different answer from *does it handshake?*. A handshake completing in both
directions while nothing moves is precisely the shape of failure this project
fears most: a true signal covering a dead path, with no log line anywhere,
because logging is off by charter and must stay off.

The debugging recorded in `field-proof.md` is the same lesson inverted: two
plausible diagnoses (path MTU, then ICMP filtering) were wrong, and the real
cause was the operator's own harness resolving IPv6 addresses into an IPv4-only
tunnel. Neither the milestone nor the debugging could have been settled by
reading anything.
