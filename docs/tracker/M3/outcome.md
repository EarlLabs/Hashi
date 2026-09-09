# M3 — outcome

**Steps:** M3.1, M3.2, M3.3 — built together, committed one per zone, **one
review round, `0 critical, 0 high`**. Two Mediums (the plan's own prose being
left stale) and three Lows, all addressed or recorded.

**Acceptance: yes, discharged in the field on two hosts.** The plan is explicit
that nothing short of observing the exit address settles this. Evidence in
`field-proof.md`; the pre-fix state, with every panel signal green and the exit in
Russia, is in `field-observations.md`. Walked by the run's orchestrator rather
than an independent acceptance agent — weaker than a stand-walked milestone, and
said plainly rather than glossed.

**Gate at close:** `make test` green — 188 control, 230 edge (3 skipped), 96
infra.

## What this milestone actually cost, and why it was worth it

The hop had been fully built for weeks — keys, both ends, the dial asymmetry,
rotation, drift detection. Everything except the line that made it a relay. The
product reported two `active` nodes, both `healthy`, no drift, no staleness, and
a hop with a nine-second-old handshake, while every friend exited in Russia. **The
one number that mattered was the one number the product does not display.**

## The two things worth carrying forward

**The plan's own mechanism was wrong, in the plan's own failure mode.** It said
to dial `exit_address(leaf)`. Nothing listens there — a leaf runs a hop end and
no proxy — so building it as written would have produced a rendered config that
looked correct, passed review, and connected to nothing. Caught by an implementer
reading what a leaf actually *is* rather than what the instruction said.

**An instruction I gave was also wrong, and was correctly overridden.** I said not
to widen `AllowedIPs`. `AllowedIPs` is not a firewall list; it is WireGuard's
crypto-routing table, and a `/32` entry cannot relay at all. The protection I was
guarding — the control plane's own SSH — is a different switch entirely
(`Table = off` plus source routing), and the implementer verified that on real
hardware before shipping it. The right response to a wrong instruction is to say
so with evidence, which is what happened.
