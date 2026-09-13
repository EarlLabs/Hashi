# M18 — carry-over

## Counts

| source | Blocking | Medium | Low |
|---|---|---|---|
| M18 review (4 lenses) | 0 | 6 | 7 |
| acceptance round 1 | 1 (fixed) | — | 6 awkward |
| acceptance round 2 | 2 (1 fixed, **1 referred to the owner**) | — | 6 awkward |

Every Medium and Low from the review was fixed in the review round. The
acceptance findings are dispositioned below.

## Referred to the owner — not fixed, not downgraded

**The probe reports a crash-looping transport as serving.** See
`docs/tracker/M18/acceptance.md` for the evidence and the four reasons this run
declined to fix it inside M18. Recorded in `docs/decisions.md` as
measured-and-not-closed.

**It needs a milestone of its own, and the milestone's real work is a decision,
not code:** what does "serving" mean? That the container exists; that it is
running; that something is listening on the port; or that a peer has handshaked.
Each answer costs differently and fails differently. `Restarting` counting as
serving is the symptom; the absence of a definition is the defect.

## Open, recorded in `docs/decisions.md`, deliberately not built

**Nothing in this product stops a node serving what it was last given.** Withdraw
and remove are *delivery* operations — they change what the panel hands out, not
what the host runs. The closest thing to a teardown is "enable some other
transport and apply", which stops the old one only as a side effect of
`--remove-orphans`, and on the **last** row it forces the operator to serve
something they did not want to serve.

**A product whose stated purpose is cutting a person off in minutes has no verb
for "stop this host."** The missing action is small; the decision that goes with
it is not — what it does to a node the operator only meant to take out of
rotation, and whether it is reachable from the Nodes row or only from a retire.

**A removed transport's rendered config stays on the host, key material and
all.** `/opt/hashi/conf/wireguard.conf`, `PrivateKey` line included, was still
there after the container was gone — on a path the panel itself calls "no undo".
**This is field-checklist item 1 (orphaned key material), now confirmed on real
hardware**, and it belongs with the teardown gap above: the same missing action
would remove it.

*Worth recording how this one arrived:* the orchestrator earlier wrote a **false**
"Confirmed" against item 1, on the strength of a `grep -Ei "wg|awg"` that could
never match the string `wireguard`. That was retracted. Acceptance has now
confirmed it properly, by a different route, on a real host.

## Fixed in the round-2 tightening

- **`node-bootstrap.sh --user <account that does not exist>` exited 2 with zero
  bytes on stdout *and* stderr.** Total silence, on the most natural first-run
  order — name the account you intend to use, before creating it. **M18's own
  theme in its purest form:** the script knew exactly what was wrong and said
  nothing.
- The never-applied node described as though something had been pushed to it, on
  both confirmation dialogs and the remove path's apply refusal.
- An unrecognised docker error dumped raw and cut off mid-word with no ellipsis.
- The API handed panel directions (*"from the Nodes screen"*) in a JSON error body.

## Left open, judged not worth the change

- **A successful probe answer never became visible on screen** in four attempts
  (waits of 2/3/4/8 s), while every *failing* probe's banner appeared at the same
  waits. Related to the probe finding above; it moves with that milestone.
- **Refusal and failure wear the same banner hue**, with only the REFUSED/FAILED
  word differing. Decided deliberately: the word carries severity, and `app.css`
  licenses the hue for both. A reviewer re-examined it and found nothing wrong.
- **The toasts and row-standing sentences** still overstate on a never-applied
  node. The authoritative surface — the apply refusal — is now correct and no
  longer contradicts them; a never-applied node has no users to mislead; and
  sweeping three sentences across three branches for a 2.2-second toast is a
  bigger milestone than the one written.

## The finding worth remembering beyond this milestone

The probe defect is **the same shape as M14's "handshake completes, nothing
moves"**: every signal green, nothing carried. The charter treats that shape as
the one that hurts most, because it is the one where the operator stops looking.

This run has now met it three times — M14 in the field, the retracted
"container Up 3 days serving nothing", and the probe. The first was real, the
second was the orchestrator's own measurement error, and the third is real and
proven. **Two out of three were real, and the false one was caught only because
somebody re-measured.**
