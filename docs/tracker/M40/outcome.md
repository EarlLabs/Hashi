# M40 — outcome

**Landed on `task/M40` (2026-11-05), stacked on task/M39.** The containerised add-user bot's
traffic now leaves the country through a leaf: a MANDATORY egress sidecar (`telegram-bot-egress`,
the fleet's AmneziaWG image, `NET_ADMIN`+TUN) in the `telegram-bot` profile, with the bot sharing
its network namespace. Everything internet-bound (Telegram and the bot's SSH to nodes) exits
through the leaf; only the local database stays direct (a connected-route carve-out). The
container-client config is `Table = off` with a PostUp that pins the leaf's endpoint off the
tunnel before swapping the default route (without it the tunnel's own packets route into the
tunnel and no handshake completes on a real public leaf), MTU 1280, per-host obfuscation; the
sidecar's `dns:` sends lookups through the tunnel. Fail-closed by construction: no
`deploy/egress/awg0.conf` or no handshake → the sidecar is unhealthy → the bot never starts, so
it can never poll Telegram in the clear from the box. The stand gained a leaf (forward/NAT) with
the fake Telegram isolated behind it, proving the path.

**Scope the owner set (2026-11-04/05):** egress mandatory in the profile; gRPC and mTLS dropped
(the bot is tied to the panel by the shared database on the local docker network); the
separate-machine deploy and control-plane minting of the egress peer DEFERRED to future
milestones — for now the operator supplies the egress config by hand, like the management tunnel.

**Steps and review.** One main build step (egress sidecar + stand leaf, folded with the stand
restructure): 2 review rounds — round 1 found a genuine High (the production config couldn't reach
a real leaf: `ip route replace default` routed the tunnel's own packets into the tunnel) plus a
DNS-leak Medium and two smaller ones; all fixed and verified in round 2 (endpoint-pin, tunnel
DNS, corrected comments, documented restart gap). A docs step (runbook + journal) done inline.
Two agent interruptions (a sleep drop, a network drop) were resumed with no lost work.

**Acceptance.** One round on the stand, verdict GOOD (partial by design). Confirmed: the bot
works end to end with its traffic going through the leaf (live handshake, Telegram via the tunnel,
DB direct); fail-closed (egress down → the bot has no network, reaches nothing, leaks nothing);
strangers silent; no secrets in any log. One clumsy nit (the bot's own healthcheck stays green
during an egress outage — monitoring clarity, not security).

**Close gate (final tree).** control 1336, edge 1025, infra 658 (edge/infra in a Linux container
with CI's pins), e2e 227 passed with the failing set exactly the host-bound baseline and nothing
new. The real `make verify` is the PR's CI run.

**Not covered, by design — the owner's field checks:** that a real leaf carries the traffic from a
real Russian network to real Telegram, and that DNS leaves through the tunnel on the real host.
The runbook ("Switching it on" / "Known-unproven") says exactly how to confirm both.
