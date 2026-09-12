# M16 — carry-over

## Counts

| source | Blocking | Medium | Low |
|---|---|---|---|
| M16.1 review (2 rounds) | 1 (fixed in round 2) | 3 | 2 |
| M16.2 review (1 round) | 0 | 2 | 1 |
| acceptance (partial) | 0 | 7 "works, but awkward" | 0 |

**Nothing blocking is open.** The one Critical was closed inside the milestone.

## The Critical that was closed, recorded because the shape recurs

Migration `0005` leaves existing nodes with **no resolver**, so a hop-dialling
node **refuses to render** — which meant every revocation's re-push would fail
behind a banner reading "until they are reachable", with **no edit path to fix
it**. A revoked friend would have kept working indefinitely while the panel
showed a plausible, wrong reason.

Fixed inside M16.1 by shipping a resolver edit path, plus a banner that states
the real per-node reason **by exception type, never by message text**. The
"never by message text" half is the part worth remembering: a banner that
switches on a string is a banner that lies the first time the string changes.

## The seven from acceptance — scheduled, not dropped

All seven are dispositioned **fix** in `docs/tracker/M16/acceptance.md`, and go
to a single fresh step-loop, **M16.3**, per autopilot §3.

**Sequencing decision (orchestrator, not in the owner's prompt).** M16.3 does
**not** run now, and the reason is mechanical rather than a judgement about the
findings: M17's review is currently the sole gate-runner, and `make e2e-verify`
builds the control image from the **working tree, not `HEAD`**. An implementer
editing `control/**` right now would make that gate measure half-built code —
the exact failure that already cost this run 18 phantom failures
(`docs/tracker/M16/branch-recovery.md`). Running M16.3 would also mean switching
branches under a checkout an agent is reading, which is the other failure this
run has already paid for.

So M16.3 runs **after M17's steps land and before M18**. None of the seven is
blocking, so nothing is at risk in waiting.

The one that is more than awkward and should not be quietly downgraded:
**`ResolverMissing:` reaching the operator's banner with a 502 and a traceback
behind it.** A Python class name in front of the operator is a copy defect; a
traceback is an error-handling defect. It is the same shape as the redaction
finding M9 closed — the exception escapes to where nobody is shaping it.

## Still open from earlier milestones, untouched by M16

M8's second acceptance finding — a **stale row on a second session** — remains
open and unassigned, as the owner directed. It is not M16's and was not folded in.
