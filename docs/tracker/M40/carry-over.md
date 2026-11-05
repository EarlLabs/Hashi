# M40 — carry-over
Non-blocking findings / deferrals, as background. Do not fix as part of another step.

## Egress step (round 1: 1 High + 3 Medium fixed; round 2: clean)
- Fixed in round-1 fixes: the endpoint-pin (the real-host showstopper — PostUp now pins the
  leaf endpoint via the original gateway before swapping the default); the DNS leak (sidecar
  `dns:` through the tunnel, field-confirmed); the stale `Egress.LOCAL` comment → RELAY; the
  restart gap (documented — restart the bot after the sidecar).
- FIELD-ONLY, no stand can prove (the owner's walk): the endpoint-pin working against a real
  public leaf; DNS actually egressing via the tunnel (tcpdump); the traffic carrying from a
  real Russian network through a real leaf to real Telegram ("polling as @…" appearing).
- Known flake (not this diff): `test_a_container_in_that_state_is_not_reported_as_loaded[amneziawg]`
  (edge M22 crash-loop timing race, worse under two emulated amneziawg containers on arm64);
  did not recur in the clean gate runs; fast/native on x86_64 CI.

## Deferred to a future milestone (owner, "just make it work")
- Mint the bot's egress peer through the control plane (rotation/revocation), with the
  production leaf rendered `Egress.LOCAL` and the container-client render variant. Until then
  the operator supplies `deploy/egress/awg0.conf` by hand (see `deploy/egress/README.md`),
  like the management tunnel.

## M40 acceptance (round 1: GOOD — may merge; 1 clumsy, non-blocking)
- Clumsy — when the egress sidecar is stopped at runtime, the BOT container's own healthcheck stays `healthy` for the whole outage even though the bot is fully cut off (the egress container correctly shows exited, and the runbook tells the operator to watch the egress container). Security property intact (no clear-path leak); a monitoring-clarity nit. A future tweak could tie the bot's health to the egress handshake.
- Could-not-observe (owner's field checks, by design): a real leaf carrying from inside a real Russian network to real Telegram; DNS for api.telegram.org leaving through the tunnel on the real host; a populated /nodes + happy-path /apply against a serving node (the stand had no serving node).
