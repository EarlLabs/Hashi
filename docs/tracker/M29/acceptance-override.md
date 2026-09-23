# M29 — acceptance override

Round 1 of stand acceptance returned BLOCKED. Not on a product defect: the gate
found no finding of class `broken` and none of class `lies`, the working tree was
unmodified across the run, and four of the six checklist lines passed with evidence
the agent produced itself. It blocked on two lines a disposable stand cannot observe.

Both were put to the owner with the evidence that discharges them. The owner lifted
the block on 2026-09-23, instructing that the milestone be marked done and the run
continue.

- lifted by owner: checklist item "The migration has been run forward and back against a copy of real data." — discharged by M29.5 against a dump of the live control plane, independently re-verified by that step's reviewer, and again by the real-host walk of 2026-09-22 which migrated a live deployment forward and back and confirmed the reversal exact. A disposable stand cannot be restored from owner data, and the acceptance agent was right to refuse to claim it.
- lifted by owner: checklist item "The project's records are untouched." — proven by diff against baseline `1b60280` at both ends of M29.7, M29.8 and M29.9, and re-verified independently by four reviewers. It is not observable through the product on an empty seed, because there is no prior record on such a stand whose survival could be confirmed.

## What the stand walk did establish, on its own evidence

All eight panel screens, every HTMX fragment they call, both stylesheets, the
delivered config file, the routes, the database schema and the stored audit actions:
**zero occurrences of the old word.** The old paths answer 404 with no `Location`
header — no alias, no redirect, as the owner chose. A revoked token and a
never-issued one returned byte-identical responses across three request shapes.

## What no run of ours can discharge, recorded so a green verdict does not imply it

The owner's scenario says *"still works on a device that already had it"*. On the
owner's **own** rows that is not provable by anyone without `HASHI_SECRET_KEY`, which
no agent may read: a stand restored from their dump cannot decrypt their tokens. The
real-host walk proves the claim on a deployment it built itself, and M29.6 proves it
mechanically in a test that fails five different ways. That is the ceiling, and it is
not raised by this override.

Neither walk says anything about whether a tunnel survives a Russian mobile whitelist
shutdown. That is a field observation on a real mobile network and remains uncovered.
