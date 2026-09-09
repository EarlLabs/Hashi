# M1 — outcome

**Steps:** M1.1, M1.2, M1.3 — built together as one coherent change to
`node_stack`'s restart-and-verify path, committed one per zone. **One review
round, `0 critical, 0 high`**, two Mediums and a Low, all recorded in
`carry-over.md`.

**Acceptance: yes, and discharged in the field.** The plan is explicit that this
milestone's scenario needs a real node and that reading the config file does not
count — *"this is the milestone whose whole failure mode was 'the file looks
right'"*. It was walked on live hardware with a real client built from the
friend's own subscription document; evidence in `field-proof.md`. Verified by the
run's orchestrator rather than an independent acceptance agent, which is weaker
than a stand-walked milestone and is stated plainly for that reason.

**Gate at close:** `make test` green — 177 control, 155 edge (3 skipped), 96
infra.

## The two things worth carrying forward

**The health probe was lying in a way nobody had asked about.** The plan
described the apply path. On real hardware the *health* path told the same lie:
`healthy: true, drifted: []` about a daemon running an eight-minute-old config.
Drift compares the file against the pushed digest and those genuinely matched —
the check was answering a question that does not establish what an operator
believes it establishes. That is the same defect one layer over, and it is now
its own field, `stale`.

**The fakes cannot prove the thing this milestone is about.** Both new test files
say so in their headers, and the reviewer confirmed the claim is accurate: the
control fake models exactly one rule of Compose and does **not** prove that real
Docker recreates a container on a label change. M5.3 is where that gets proven on
a stand. Everything that makes this milestone *true* rather than plausible is in
`field-proof.md`, measured on a host.
