# M28 — closed 2026-09-26

**24 steps written, 22 landed, one withdrawn.** Thirteen were planned; the rest came from
findings — two from acceptance rounds, nine from reviews. Acceptance: **good**, round 3 of 3,
six `clumsy` findings and none blocking. Review rounds: 2 per step at most, two steps
(M28.21, M28.22) stopped at their cap with prose findings open and recorded as debt.

## What landed

Daily offsite backups, encrypted whole with an `age` keypair so the control host holds only
the public recipient and cannot read a backup back. One command restores onto a machine that
has never run the project. The record is read by exactly one thing, and every verb reads
through it.

## What the acceptance walk actually did

Built a fleet, destroyed the box with `down -v` and deleted the checkout, and rebuilt from one
bucket object plus the two carried secrets. The existing user's existing token returned a
byte-identical body. `file`: *age encrypted file, X25519 recipient*. Grepping the artifact for
the node address, node name, country, username, transport and SQL keywords: zero hits each.
9 PUT, 0 DELETE.

## The defect this milestone was really about

**A check that can be satisfied by the absence of the thing it checks will be, eventually.**
Eight surfaces of it were found. A schedule line printed whether or not a schedule existed. An
audit swept a file after the code had moved out of it. A guard never ran because its case was
never generated. An existence check recorded what a helper offered rather than what a loop
exercised. `tick` read the record leniently while `status` and `due` read it strictly, so the
channel that takes backups concluded the day's was already taken.

## The second defect, and the convention it produced

**Fifteen findings of "prose asserts behaviour the code does not have"**, and the last five
were written by the steps fixing the earlier ones — one by the orchestrator, in the plan, in
the step whose subject was that class. Every late instance reached across a boundary: the
shell claiming what the panel reads, the panel claiming what the command line prints, a
comment claiming what a neighbouring branch does.

`CLAUDE.md` and all three rulebooks gained the rule that follows: **a comment describes the
code it sits on and records why — never what another module, another channel or a
neighbouring branch does.** The defence is scope, because verification is not available: *no
test can tell a true sentence from a false one; it can only tell you which states a sentence
appears in.*

The prose work was stopped deliberately at fifteen, with the remainder in `carry-over.md` and
a standing recommendation to **delete rather than refine** — those sentences explain gates
already pinned by biconditionals, and the explanations are pinned by nothing.

## Open, and where

`carry-over.md` holds the accepted prose debt and the unfixed seams. Round 3's six `clumsy`
findings are in `acceptance-verdict.md`; the first of them — `make backup-status` not
consulting the crontab on a host with **no record yet**, which is exactly a freshly restored
host — is the one to fix first and is proposed as its own milestone.
