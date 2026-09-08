# hashi — plan

**Created:** 2026-09-08
**Status:** draft — not confirmed by the owner
**Source:** the first real deployment. Every item below was found by *running* the
product on a rented host, not by reading the tree. None of them is caught by
`make test`, and none of them was visible from inside the repository.

Charter: `docs/product/charter.md`. Frozen acceptance criteria:
`docs/research/product-owner-ohno-4/research.md` §3. Provider research:
`docs/research/research-vps-provider-shape-a/research.md`.

---

## Where things stand

One host, rented and live: **Amsterdam, NL — 45.151.69.107**, AS216139 Iron
Hosting Centre, Ubuntu 22.04, 1 vCPU, 957 Mi RAM. Runbook **Shape A**: control
plane, panel, delivery endpoint and one node on the same box.

**Works, verified over the public internet:** `panel-bootstrap.sh` → Let's Encrypt
certificate → panel login → register node → enable transport → `apply` → friend →
subscription → a real client connects and carries traffic. Operator auth fails
closed (401 unauthenticated). The API returns public keys and withholds private
and preshared ones.

**The charter's hardest invariant holds on real hardware.** A live subscription
token appears **zero** times in container logs and **zero** times in Docker's
on-disk JSON logs; `/sub/` is never recorded; uvicorn's access log is empty and
Caddy emitted four lines across the whole deployment. No unit test could have
established this.

**Does not work:** everything in M1–M3 below. The pattern is worth stating once,
because it is the lesson of the whole exercise:

> Everything checkable by **rendering** works. Everything checkable only by
> **running** does not.

**Standing recommendation: do not rent the Russian host yet.** It would cost money
and buy nothing until M2 and M3 are done — you would get two working nodes and no
working hop between them.

---

## M1 — `apply` must actually take effect

**Blocking prerequisite for everything else.** Until this is fixed, no other fix
can be verified on a live node: a correct change and an incorrect one both look
broken.

**The bug.** `node_stack.restart()` runs `docker compose up -d --remove-orphans`.
Compose is declarative — it compares the desired *service definition* against the
running container and does nothing when they match. A bind-mounted config file's
**contents are not part of that definition**, so the container is never recreated,
and Xray parses its config only at process start. Measured on the live node:
container started `12:57:53`, config last written `17:01:39`, with three applies
and one revocation in between — **none reached the process**.

The comment at `node_stack.py:249` asserts the opposite in as many words: *"`up -d`
rather than `restart`: it is the same command whether the stack was never started,
is partly running, or **needs a changed config picked up**."* That last clause is
the defect.

**Why it stayed invisible:** `running_services()` asks which services are up, and
the container genuinely *is* up — just stale. So `apply` returns 200 and writes
`applied_digest` to the database, which then records a state the node is not in.

**Consequences:** a new friend cannot connect, and — worse — **a revoked friend is
not cut off.** The config file loses the credential, the subscription 404s, and
the running daemon keeps accepting the revoked key until something unrelated
restarts it. That is criterion 6 failing silently while the panel reports success.

### Steps
1. Make the config part of the service definition — put `digest_of(config)` into
   the rendered compose as a label or env var on the service. A changed config
   then *is* a changed definition, and Compose recreates the container by itself.
   `up -d` stays the single verb, and `digest_of()` already computes the value.
2. Replace the `running_services()` check with one that proves the daemon loaded
   **this** config, not that a process exists.
3. Correct the comment at `node_stack.py:249`.

*Rejected: simply swapping `up -d` for `restart`. That breaks the cases `up -d`
exists for — container never created, definition genuinely changed, stack partly
running.*

### Done when
- [ ] Changing a config and applying restarts the daemon, proven by a start
      timestamp later than the config's mtime.
- [ ] `apply` fails loudly if the running daemon's config does not match the
      digest it just pushed.
- [ ] Revoking a friend stops that friend **at the node**, verified by a client
      that could connect before and cannot after — not by reading the file.

**Acceptance required: yes.** This is the item whose whole failure mode was
"the file looks right".

---

## M2 — The WireGuard family must start at all

**The bug.** `node_stack.py:116,126` sets `command=("up", "{config}")` for
`amneziawg` and `wireguard`. Both images have an **empty ENTRYPOINT**
(`amneziavpn/amneziawg-go:3.0.3` → `Cmd=[/bin/sh]`;
`masipcat/wireguard-go:0.0.20230223` → `Cmd=[/entrypoint.sh]`), so `command`
becomes the entire argv and Docker tries to exec a binary named `up`:

```
exec: "up": executable file not found in $PATH   → exit 127, container stuck "Created"
```

The images **do** ship `awg-quick`, `awg`, `amneziawg-go`, `wg-quick` — so this is
a command bug, not an image swap.

The runbook's "Known-unproven" section named only the plain-WireGuard image. Both
are broken, and `amneziawg` is the transport the same runbook recommends for
Shape A and **mandates** for the entry→leaf hop.

### Steps
1. Give each WireGuard-family transport a command its image actually accepts.
   Note `awg-quick` derives the interface name from the config **filename**, so
   the config path is part of the fix, not incidental to it.
2. Check the same assumption for every transport in the registry, including any
   added later — the Xray family happens to be correct, which is luck, not design.

### Done when
- [ ] `amneziawg` and `wireguard` containers reach `Up`, not `Created`, on a real
      node.
- [ ] A client on a WireGuard-family transport carries traffic.
- [ ] A test asserts the container command against the image's real entrypoint
      (see M5).

**Acceptance required: yes.**

---

## M3 — The entry node must route friend traffic into the hop

**This is the charter's core claim, and it is not implemented.**

`vless_reality/server.j2:58` (and `vless_ws_tls` identically) hardcodes a single
outbound:

```json
"outbounds": [{"tag": "direct", "protocol": "freedom"}]
```

No routing rules, nothing conditional on the node having a hop. `edge/relay.py:174`
defines `exit_address()` — *"the in-tunnel address the entry forwards friend
traffic to… what an entry node's data plane uses as its outbound target"* — and it
is called from **exactly one place in the tree: its own unit test**
(`tests/edge/test_relay.py:135`).

So on an entry node with a friend-facing transport and a hop to a leaf, friend
traffic arrives at Xray and leaves **straight out of the entry node's own
interface, in Russia.** The hop is genuinely built — keys minted, both ends
rendered, entry-dials-leaf asymmetry handled, `AllowedIPs` deliberately narrow so
the control plane's own SSH is not swallowed, rotation and drift detection working.
Every piece except the one that makes it a relay.

**Why this is the worst of the three: the failure is invisible.** The friend
connects, pages load, the panel shows two `active` nodes and a live hop — and the
exit is in Russia. The protection the topology exists to provide is absent while
everything looks healthy.

### Steps
1. Render an outbound on the entry node that targets `exit_address(leaf)`, and the
   routing rule that sends friend inbound traffic to it.
2. Keep it data-driven — the entry must not learn protocol names. A node with no
   hop keeps today's `freedom` outbound unchanged.
3. Decide and document what happens when the hop is down: fail closed (no exit) is
   almost certainly right, because failing open means exiting in Russia without
   anyone being told.

### Done when
- [ ] A client connected to the entry node shows the **leaf's** public address as
      its exit IP.
- [ ] A node with no hop still exits directly, unchanged.
- [ ] Tearing the hop down does not silently fall back to a Russian exit.

**Acceptance required: yes.** Nothing short of observing the exit IP proves this.

---

## M4 — Failures must report themselves honestly

Two defects, both about a wrong message at the worst moment.

**A node's first apply cannot record its own failure.** `apply_node` marks a node
`degraded` on failure (`apply.py:257,265`), but the state machine forbids
`draft → degraded` — and `draft` is exactly where a first apply starts. The
operator gets `409: a node cannot go from draft to degraded` instead of "amneziawg
did not come up", and the real reason reaches no log either. This is how M2 hid
itself on the first run.

**Revoking a friend returns 500.** `MissingGreenlet` at `apply.py:276` —
`node.transports` is lazy-loaded after `friends.revoke` committed the session.
`apply_many` (`apply.py:303`) catches only `NodeOperationFailed`, so the SQLAlchemy
error escapes. The operator never receives the `RevocationOutcome` naming which
nodes still carry the credential — which is the reporting criterion 6 exists for.

### Steps
1. Allow `draft → degraded`, or give the first apply its own path. A node that has
   been written to and failed is not still a draft.
2. Eager-load what `apply_node` needs, or refresh explicitly, so no lazy I/O
   happens outside the greenlet context.
3. Widen `apply_many`'s except clause so an unexpected error becomes a reported
   per-node failure rather than a 500 for the whole fan-out.

### Done when
- [ ] A first apply that fails leaves the node `degraded` with the real reason in
      `state_detail`.
- [ ] Revocation returns `RevocationOutcome`, listing any node that still carries
      the credential.
- [ ] No operator-facing 500 on either path.

**Acceptance required: no.** Provable by test once M1 is in.

---

## M5 — Tests that catch "renders but does not run"

Nothing in `tests/e2e/` or `tests/edge/` asserts the data-plane container command,
and nothing asserts that traffic transits a hop.
`test_every_image_pin_resolves.py` proves a tag exists and says nothing about
whether the image starts. That gap is why M1, M2 and M3 all survived to a rented
host.

### Steps
1. Assert each transport's command against its image's real entrypoint.
2. Assert a container reaches `Up` and stays up, not merely that it was created.
3. Assert that a config change reaches the running daemon (pairs with M1).
4. A hop scenario that asserts the **exit address**, not the rendered config.

Every scenario red-first: break it, watch the right assertion fail, restore.

### Done when
- [ ] Reverting any of M1–M3 turns a specific scenario red.

**Acceptance required: no.**

---

## M6 — Deployment hygiene

**`panel-bootstrap.sh` reports a URL nothing serves.** Confirmed on the live host:
it verified the stack from inside the compose network and printed
`The panel is at https://…/panel/` while ports 80 and 443 were closed, because the
base compose publishes nothing. The runbook documents this and tells you to write
`deploy/docker-compose.public.yml` by hand. Either publish, or do not print an
address that has not been proven reachable.

**`ufw enable` turns on connection logging.** The runbook's own line produces
`/var/log/ufw.log` full of source addresses — the record the charter forbids *at
any level*. It had collected 5,840 bytes within minutes on the live host. I ran
`ufw logging off`; the runbook still lacks the line and `panel-bootstrap.sh` has
no check.

### Steps
1. Make bootstrap's final message match what is actually reachable.
2. Add `ufw logging off` to the runbook, and a check to bootstrap.
3. Decide what to do with the existing `/var/log/ufw.log` on the live host.

### Done when
- [ ] Bootstrap's success line is reachable from outside, or it does not print one.
- [ ] A fresh host following the runbook produces no connection log.

**Acceptance required: no.**

---

## M7 — Panel off the public internet

**Owner request:** reach the admin console over Tailscale rather than from a public
address. The reasoning is sound: the panel holds every node key and every friend
credential, and there is deliberately **no lockout on failed logins**
(`control/app/auth.py`), so password length is the entire defence.

**What makes it more than a one-line change:** the panel and the delivery endpoint
are the same Caddy site today —
`{$HASHI_PUBLIC_HOST} { reverse_proxy control:8000 }`. And `/sub/{token}` **must
stay public**: a friend refreshes their config from inside Russia at exactly the
moment a node was blocked. So the site has to split in two:

- **public** — serves only `/sub/*`, everything else 404;
- **tailnet** — `/panel/*` and `/api/*`, bound to the Tailscale interface, cert
  from `tailscale cert`.

### Blocked on two owner decisions
1. **This is a charter amendment.** The Deployment line *"Public URL required for
   the panel (behind auth)"* stops being true. The project's own rule is consent
   first, then the charter, then the plan — in that order, never the reverse.
2. **Tailscale vs Headscale.** Tailscale's coordination is a US service that may
   be unreachable from Russia. If it is down exactly when an emergency rotation is
   needed, you are locked out of your own panel — the failure lands precisely on
   the scenario the panel exists for. **Headscale** (self-hosted coordination)
   avoids that. SSH remains the fallback either way.

### Done when
- [ ] The panel is unreachable from a public address.
- [ ] `/sub/{token}` still resolves from an ordinary network, unchanged.
- [ ] A documented way back in when the private network is unavailable.

**Acceptance required: yes.**

---

## Decisions needed from you

| # | Decision | Blocks |
|---|---|---|
| 1 | Charter amendment: panel leaves the public URL | M7 |
| 2 | Tailscale or Headscale | M7 |
| 3 | Behaviour when a hop is down — fail closed, or exit locally and say so | M3 |
| 4 | Whether to bump `xray-core` from the pinned `1.8.24` (roughly two years behind the ≥ `25.12.8` that 2026 field guidance names as the detection threshold). A data-plane pin bump has a security argument on both sides — new upstream means new defaults and new detectability | — |
| 5 | What to do with `/var/log/ufw.log` on the live host | M6 |

Still open from before: **C** and **E** in `docs/product/backlog.md`, both awaiting
you, E wanted by M4.

---

## What this plan does not cover

- **Criterion 1 — "survives a mobile whitelist shutdown".** Not reachable by any
  foreign box from any provider at any price: whitelist mode leaves roughly 57
  *Russian* services reachable. No item here moves it, and none pretends to.
- **Throughput and DPI survival.** The live client proves a tunnel carries traffic;
  it proves nothing about speed, or about how long this IP stays unblocked.
- **The second host.** Nothing here requires it, and M2 and M3 should land before
  it is rented.
- **A leaf node's console.** There is none, deliberately — a node runs only its
  data-plane container, exposes nothing for management, and never dials the control
  plane. Nothing to build.
