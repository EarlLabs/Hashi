# hashi — plan

**Created:** 2026-09-08
**Status:** approved by the owner 2026-09-08 — M1–M11. **M12 was appended
during the overnight field run of 2026-09-08**, under the owner's standing rule
that a field bug no milestone covers becomes a new milestone: it concerns
something the plan already aimed at (walking M8–M10 on the stand) and it lands
in `infra`, so implementing it in the same run is pre-approved.
**Source:** the first real deployment. Every item below was found by *running* the
product on a rented host, not by reading the tree. None of them is caught by
`make test`, and none of them was visible from inside the repository.

Charter: `docs/product/charter.md`. Frozen acceptance criteria:
`docs/research/product-owner-ohno-4/research.md` §3. Provider research:
`docs/research/research-vps-provider-shape-a/research.md`.

---

## General rules for every milestone below

- **M1 gates the verification of everything else.** Until `apply` takes effect, a
  correct change and an incorrect one both look broken on a live node. Order the
  work accordingly.
- **M4 now runs BEFORE M1 — changed during the field run of 2026-09-08, with
  evidence.** The first apply against a real host prepared by M11's script
  returned `409: a node cannot go from draft to degraded`, and the control
  plane's log recorded exactly one line about it: `domain error: conflict`. The
  real reason — whatever actually failed on the node — was destroyed before it
  could be raised, because `set_node_state(DEGRADED)` throws on the forbidden
  transition while it is handling the original failure. M1 and M2 are diagnosed
  by applying to a live node and reading what comes back, so M4.1 is not a
  follow-up to them; it is the instrument they are diagnosed with. This plan
  already said as much — *"this is how M2 hid itself on the first run"* — it
  simply sequenced it as a consequence rather than a prerequisite.
- **The lesson that produced this plan:** everything checkable by *rendering*
  works; everything checkable only by *running* does not. A milestone is not done
  because its output looks right.
- **Do not rent the Russian host yet.** It would cost money and buy nothing until
  M2 and M3 are done — you would get two working nodes and no working hop between
  them.
- **Where a milestone says `acceptance: yes`, its scenario needs a real node.**
  The disposable stand in `scripts/acceptance/stand.sh` brings up a control plane,
  a database and a delivery endpoint — it has no data plane, no tunnel and no
  second host. M1, M2, M3 and M7 are therefore field observations on rented
  hardware, and the stand cannot discharge them. Say so in the verdict rather
  than passing them on a panel that looked right.
- **M8, M9 and M10 are the exception to that rule.** They are panel work, and the
  stand is exactly the right instrument for them: a control plane, a database and
  a delivery endpoint is all their scenarios need. Walk them on the stand — and
  walk them, rather than passing them because the screenshot matched the design.
- **`make test` never proves a tunnel carries traffic**, and it cannot prove the
  charter's first success criterion. See "What this plan does not cover".

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

**Two hosts as of 2026-09-08, roles set by the owner.** The Amsterdam box is the
**leaf** and exits traffic. A second host — 3.9 Gi RAM, in Russia — is the
**entry**, and carries the control plane and the panel as well. That moves the
control plane off the 957 Mi box, which had 463 Mi free while running control,
Postgres, Caddy and a node together. It also puts every node key and every friend
credential on a Russian host: deliberate, and the reason M7 stops being optional.

**Does not work:** everything in M1–M3 below. The pattern is worth stating once,
because it is the lesson of the whole exercise:

> Everything checkable by **rendering** works. Everything checkable only by
> **running** does not.

---

## ✅ M1 — `apply` must actually take effect · planned 2026-09-08 · done 2026-09-09

> **Closed in the field run, and verified on real hardware rather than by test.**
> One review round, `0 critical, 0 high`. Gate green — 177 control, 155 edge
> (3 skipped), 96 infra.
>
> **All three "done when" bullets discharged on a live node** — see
> `docs/tracker/M1/field-proof.md`, and `field-measurement.md` for the same node
> before the fix:
>
> | | before | after |
> |---|---|---|
> | config vs the process serving it | config written **8m25s after** the container started | container starts **0.5s after** the config |
> | container label vs `sha256sum` of the config | no label | identical |
> | health of a stale daemon | `healthy: true, drifted: []` | `healthy: false, drifted: [], stale: [...]` |
> | a revoked friend's client | (never tested — the file "looked right") | **refused, while a live friend connected through the same node at the same moment** |
>
> That last row is criterion 6 holding, and the control is what makes it
> conclusive: the node was still serving, only the revoked credential was dead.
>
> **`drifted` stayed `[]` and was correct** — the file genuinely matched what was
> pushed. Nothing compared either against what the *process* loaded. That gap is
> not in this milestone's original description and was the more dangerous half;
> `stale` is a separate fact for that reason.

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

*Rejected: simply swapping `up -d` for `restart`. That breaks the cases `up -d`
exists for — container never created, definition genuinely changed, stack partly
running.*

### M1.1 — Make the config part of the service definition

Put `digest_of(config)` into the rendered compose as a label or env var on the
service. A changed config then *is* a changed definition, and Compose recreates
the container by itself. `up -d` stays the single verb, and `digest_of()` already
computes the value.

### M1.2 — Prove the daemon loaded this config, not merely that a process exists

Replace the `running_services()` check with one that establishes the running
daemon is on the digest `apply` just pushed.

### M1.3 — Correct the comment at `node_stack.py:249`

It currently states the defect as the reason for the design.

**E2E:** none yet — the scenario that would catch this is M5.3, sequenced after
the fix so it can be written red against a node known to be broken.

**Done when**
- [ ] Changing a config and applying restarts the daemon, proven by a start
      timestamp later than the config's mtime.
- [ ] `apply` fails loudly if the running daemon's config does not match the
      digest it just pushed.
- [ ] Revoking a friend stops that friend **at the node**, verified by a client
      that could connect before and cannot after — not by reading the file.

acceptance: yes
On a live node with a transport enabled, add a friend and connect a real client as
that friend. Note when the data-plane container started. Now revoke the friend in
the panel and apply. Check that the container restarted *after* the config was
written, then try that same client again: it must no longer connect. Reading the
config file does not count — this is the milestone whose whole failure mode was
"the file looks right".

---

## ✅ M2 — The WireGuard family must start at all · planned 2026-09-08 · done 2026-09-09

> **Field run 2026-09-09 — steps complete and reviewed clean; the milestone stays
> open on its second "done when", for a reason that is not its own.** One review
> round, `0 critical, 0 high`; the Medium it raised was fixed rather than filed.
> Gate green — 177 control, 187 edge (3 skipped), 96 infra.
>
> **First "done when": discharged on real hardware.** On the entry node both
> containers reach **`Up`**, not `Created` — they were `Created` with exit 127
> before — and both interfaces exist in the *node's* network namespace with the
> transport's own name. `awg show` reports the interface with its obfuscation
> values live (`jc`, `jmin`, `jmax`, `h1`–`h4`), and a real client built from the
> friend's own subscription **completed a handshake in both directions**.
>
> **Second "done when" — "a client carries traffic" — discharged once M14 landed.**
> When this milestone's work was done the handshake succeeded and nothing moved,
> because the node had no forwarding or NAT for the tunnel subnet. That was M14,
> not M2, and with M14 in place a real client on the `amneziawg` transport loads
> pages through this node and exits at its address. Nothing about the command,
> the image or the interface was ever outstanding. The plain-WireGuard member
> carries M14's recorded image-backend limitation.

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

### M2.1 — Give each WireGuard-family transport a command its image accepts

Note `awg-quick` derives the interface name from the config **filename**, so the
config path is part of the fix, not incidental to it.

### M2.2 — Check the same assumption for every transport in the registry

Including any added later. The Xray family happens to be correct, which is luck,
not design.

**E2E:** none yet — M5.1 and M5.2 are the scenarios that pin this.

**Done when**
- [ ] `amneziawg` and `wireguard` containers reach `Up`, not `Created`, on a real
      node.
- [ ] A client on a WireGuard-family transport carries traffic.
- [ ] A test asserts the container command against the image's real entrypoint
      (see M5).

acceptance: yes
On a live node, enable `amneziawg`, apply, and look at the container: it must be
`Up`, not `Created`. Then take a client onto that transport and load a page
through it. Repeat for `wireguard`.

---

## ✅ M3 — The entry node must route friend traffic into the hop · planned 2026-09-08 · done 2026-09-09

> **The charter's core claim, working on real hardware.** One review round,
> `0 critical, 0 high`. Gate green — 188 control, 230 edge (3 skipped), 96 infra.
> All three "done when" bullets discharged on two live hosts; see
> `docs/tracker/M3/field-proof.md`, and `field-observations.md` for the same fleet
> before the fix.
>
> | | before | after |
> |---|---|---|
> | what the internet sees when a friend dials the Russian entry | **the entry's own address** | **the leaf's, in Amsterdam** |
> | a real page through the relay | — | `HTTP 200`, 119 573 bytes |
> | with the hop torn down | (never reached — it exited locally anyway) | **two timeouts, and never a Russian address** |
> | the control plane's SSH across the apply | — | unaffected; main routing table untouched |
>
> **Two corrections this milestone made to its own instructions**, both recorded
> in `docs/decisions.md` and beside the original wording above: a leaf's
> in-tunnel address is a **route, not a destination**, so the entry binds its own
> end (`sendThrough`) rather than dialling the far one; and the entry's hop-peer
> `AllowedIPs` had to **widen** to `0.0.0.0/0`, because `AllowedIPs` is
> WireGuard's crypto-routing table rather than a firewall list.
>
> **Found immediately after, and not covered by this milestone's criterion:** the
> exit is Amsterdam and the **DNS lookup is still Russia** — now M16.

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

> **The `AllowedIPs` half of that sentence stopped being true on 2026-09-09, on
> purpose. Do not re-narrow it on the strength of the paragraph above.** The
> entry's hop peer is now `0.0.0.0/0`, because WireGuard only encrypts a packet
> to a peer whose `AllowedIPs` covers the **destination**, and only accepts a
> reply whose **source** it covers — a `/32` entry can send nothing but pings,
> and a relay's return traffic arrives sourced from the internet host the friend
> asked for, not from the leaf. The SSH protection is a **different switch**:
> `Table = off` plus source-based policy routing, so only traffic already sourced
> from the tunnel's own address enters the hop and the main routing table is
> untouched. Verified on real hardware — `docs/decisions.md`, and
> `docs/tracker/M3/field-proof.md`.

**Why this is the worst of the three: the failure is invisible.** The friend
connects, pages load, the panel shows two `active` nodes and a live hop — and the
exit is in Russia. The protection the topology exists to provide is absent while
everything looks healthy.

### M3.1 — Render the entry node's outbound and routing rule

Target `exit_address(leaf)`, and send friend inbound traffic to it.

> **Corrected while implementing, 2026-09-09 — this instruction was wrong.**
> `exit_address(leaf)` cannot be an outbound *destination*, because **nothing
> listens there**: a leaf runs one hop end and no proxy, so its in-tunnel address
> accepts no connection. What a leaf offers is a **route**, not a service.
>
> What shipped: the entry opens ordinary connections **bound to its own end of
> the tunnel** — `sendThrough: <the entry's in-tunnel address>` on a single
> `freedom` outbound, plus a routing rule binding the friend inbound to it — and
> the kernel carries them over the hop. Same function, other argument:
> `exit_via(entry)`.
>
> Kept because the original wording would have rendered a config that looked
> correct, passed review and connected to nothing — the same failure mode as the
> milestone it was written to fix.

### M3.2 — Keep it data-driven

The entry must not learn protocol names. A node with no hop keeps today's
`freedom` outbound unchanged.

### M3.3 — Decide and document what happens when the hop is down

Fail closed (no exit) is almost certainly right, because failing open means
exiting in Russia without anyone being told. This is decision 3 below.

**E2E:** none yet — M5.4 is the hop scenario that asserts the exit address.

**Done when**
- [ ] A client connected to the entry node shows the **leaf's** public address as
      its exit IP.
- [ ] A node with no hop still exits directly, unchanged.
- [ ] Tearing the hop down does not silently fall back to a Russian exit.

acceptance: yes
With an entry node and a leaf node joined by a live hop, connect a friend's client
to the entry and ask the internet what address it sees — it must be the leaf's,
not the entry's. Then take the hop down and check again: the friend must not
quietly end up exiting in Russia. Nothing short of observing the exit IP proves
this.

---

## ✅ M4 — Failures must report themselves honestly · planned 2026-09-08 · done 2026-09-09

> **Closed in the field run.** Six steps, every one converging clean; only M4.4
> needed a second round, for mixing two zones in one diff rather than for
> anything it did. Gate at close: `make test` green — 169 control, 134 edge
> (3 skipped), 90 infra.
>
> **M4.1 is proven on real hardware, not only by test.** The same apply that
> returned `409: a node cannot go from draft to degraded` and logged one line —
> `domain error: conflict` — now returns
> `mkdir: cannot create directory '/opt/hashi': Permission denied`, in the
> response body, in `state_detail`, and in an `ERROR` log line carrying the node
> id and no address. The fault that took a health probe, a host inspection and a
> hand-run command to identify is now a sentence. That is the milestone
> justifying the reordering it was given.
>
> **The milestone grew from three steps to six**, each addition traceable: M4.4
> from a 7m39s baseline gate, M4.5 from a reviewer disproving an
> implementer's "harmless", M4.6 from two guards that could not fail.

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

### M4.1 — Let a first apply record its own failure

Allow `draft → degraded`, or give the first apply its own path. A node that has
been written to and failed is not still a draft.

### M4.2 — Remove the lazy load from `apply_node`

Eager-load what it needs, or refresh explicitly, so no lazy I/O happens outside
the greenlet context.

### M4.3 — Widen `apply_many`'s except clause

### M4.4 — A node operation must not block forever · found 2026-09-08

Not a message problem like the three above, but the same failure to report
honestly: a node that accepts no packets makes the control plane wait, rather
than telling anyone.

Found while establishing a baseline for the field run.
`tests/control/test_revocation.py::test_an_unreachable_node_makes_the_revocation_report_incomplete`
points its fixture at `192.0.2.10` — TEST-NET-1, deliberately unroutable — and
the whole control suite takes **7 minutes 39 seconds**, essentially all of it
waiting on addresses that will never answer.

**Corrected while implementing, and the correction matters.** The first
diagnosis above — *"there is no connect timeout anywhere"* — was wrong. There was
one; it simply shared the 20-second budget used for *commands*, and the suite
paid it in full **23 times** (measured with `--durations`: every node dial cost
20.2–20.4 s). So the fix is splitting one ceiling into two, not inventing one
from nothing.

What genuinely had **no ceiling at all** was not the connect: it was the **SFTP
transfers and the session close**. A node that completes the handshake and then
goes quiet mid-transfer hung forever — which is a better description of a node
being blocked than a refused connection is, and it is the failure the module
docstring already claimed to handle.

**Why this matters in the field and not only in CI.** A blackholed address is
not a contrived test condition for this project — it is what a *blocked* node
looks like from outside, which is the exact scenario the product exists for.
The operator opens the panel during a block, presses apply or revoke, and the
request hangs for minutes with no indication whether anything is happening.
Worse, revocation is the operation whose whole point is being fast.

**Done when**
- [ ] Reaching a node has a bounded timeout, and exceeding it is a reported
      per-node failure with a plain reason, not a hang.
- [ ] The control suite no longer spends minutes waiting on an address that will
      never answer.

An unexpected error becomes a reported per-node failure rather than a 500 for the
whole fan-out.

### M4.5 — A second failure must replace the first one's reason · found in review 2026-09-09

Found by the reviewer of M4.2, which had recorded this as harmless. It is not,
and it defeats this milestone's own "done when".

`control/app/services/nodes.py` guards `set_node_state` with
`state is not node.state` — an **identity** comparison. `Node.state` is
`Mapped[NodeState]` over a plain `String(16)` column with no enum coercion, so a
node loaded by `session.get` or a `select` carries a plain `str`, never the
`NodeState` singleton. The comparison is therefore **always true**, and the
"setting a state to what it already is, is allowed" branch never short-circuits.

**What that costs.** Marking an already-`degraded` node `degraded` again — which
is exactly what a second failed apply does — raises
`Conflict: a node cannot go from degraded to degraded`. M4.1's `_record_failure`
swallows a `Conflict` by design, so the write is silently skipped and
**`state_detail` keeps the *first* failure's reason after a second, different
failure.** The operator retries an apply, gets a new error, and the panel shows
them the old one. Reproduced directly by the reviewer.

This milestone's own criterion says *"a first apply that fails leaves the node
`degraded` with the real reason in `state_detail`"*. The second one does not, so
this is finishing M4 rather than widening it.

### M4.6 — Two tests that currently cannot fail

**Pin the node-stack doubles to the real signatures.**

`tests/control/test_revocation_push.py` is the first test in this zone to fake
the SSH boundary, which was the right call — there is no honest way to reach the
apply *success* path without one. The gap is that a stale double goes **silently
green** rather than red if a real signature changes, and this double guards a
charter criterion. `create_autospec`, or an `inspect.signature` parity assertion,
turns that drift into a hard failure for a few lines.

**And give the address-leak guard something to catch.** M4.3 deliberately puts
only `type(exc).__name__` into the operator-facing string, never `str(exc)`,
because a raw connection error carries the node's address — the reviewer
confirmed it empirically (`[Errno 111] Connect call failed ('127.0.0.1', 1)`) and
that such an exception can reach the broad catch unsanitised. The test guarding
that asserts the address is absent from the response, but the exception it
injects is a `MissingGreenlet`, which never carried an address in the first
place. **A future step "harmonising" those messages by putting `{exc}` back would
reintroduce the leak and this suite would stay green.** The guard needs an
exception that actually carries an address forced through the broad catch, with
the assertion made against both the API response and the stored `state_detail`.

Both are the same defect in miniature and the reason this step exists: *a test
that cannot fail is worse than no test.*

**E2E:** none from `tests/e2e/` — this is control-zone territory and the gate that
applies is `make test-control`.

**Done when**
- [ ] A first apply that fails leaves the node `degraded` with the real reason in
      `state_detail`.
- [ ] Revocation returns `RevocationOutcome`, listing any node that still carries
      the credential.
- [ ] No operator-facing 500 on either path.

acceptance: no
Provable by test once M1 is in.

---

## ✅ M5 — Tests that catch "renders but does not run" · planned 2026-09-08 · done 2026-09-09

> **Closed in the field run.** One review round, CLEAN. Four scenarios under
> `tests/e2e/edge/`, all against a real Docker engine. Gate green — 188 control,
> 230 edge (3 skipped), 96 infra.
>
> **The "done when" is a demonstration and it was demonstrated**, then reproduced
> independently by the reviewer: reverting M1 turns **only** M5.3 red (14
> assertions), reverting M2 turns M5.1 red with `exec: "up": executable file not
> found`, and reverting M3 turns **only** M5.4 red. See
> `docs/tracker/M5/outcome.md`.
>
> M5.4 is a real relay — two containers, two networks, minted keys, a real
> handshake — with the control that makes it discriminating: through the hop the
> destination sees the leaf; by the entry's own route it sees the entry.

Nothing in `tests/e2e/` or `tests/edge/` asserts the data-plane container command,
and nothing asserts that traffic transits a hop.
`test_every_image_pin_resolves.py` proves a tag exists and says nothing about
whether the image starts. That gap is why M1, M2 and M3 all survived to a rented
host.

Every scenario red-first: break it, watch the right assertion fail, restore.

### M5.1 — Assert each transport's command against its image's real entrypoint
### M5.2 — Assert a container reaches `Up` and stays up, not merely that it was created
### M5.3 — Assert that a config change reaches the running daemon

Pairs with M1.

### M5.4 — A hop scenario that asserts the exit address, not the rendered config

**E2E:** this milestone *is* the e2e work — its four steps are the scenarios, and
they land under `tests/e2e/<zone>/`. The existing suite stays green.

**Done when**
- [ ] Reverting any of M1–M3 turns a specific scenario red.

acceptance: no

---

## → M6 — Deployment hygiene · planned 2026-09-08

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

### M6.1 — Make bootstrap's final message match what is actually reachable
### M6.2 — Add `ufw logging off` to the runbook, and a check to bootstrap
### M6.3 — Decide what to do with the existing `/var/log/ufw.log` on the live host

This is decision 5 below.

### M6.4 — The operator's password hash cannot survive `--env-file` · found in the field 2026-09-08

**Found while standing up the control plane on the entry host.** The panel
returned 401 to a password that was correct. The cause is not in the panel.

`hash_password()` produces `scrypt$<n>$<r>$<p>$<salt-b64>$<hash-b64>` — `$` is
the field separator, and `control/cli.py` prints the value ready to paste into
`.env`, which is what the runbook tells the operator to do. Every compose
invocation in this project goes through `--env-file` (CLAUDE.md requires it),
and compose interpolates `$name` inside those values. Observed on the host:

```
The "SNiOje2G3DLUkAfHbJpPC8FeuMSEoMwDkuujDaBc6Hw" variable is not set.
  Defaulting to a blank string.
HASHI_OPERATOR_PASSWORD_HASH: scrypt$$32768$$8$$1$$469D1j8LwOnyngdRZyAHYA===
```

An 86-character hash reached the container as 42 characters. The final field —
the hash itself — was deleted.

**Why this is worse than an ordinary bug: it is a coin flip, and it is silent.**
The salt field survived because base64 happened to give it a leading digit
(`469D…`), and `$4` is not a variable name. The hash field began with a letter,
so it was one. A deployment therefore breaks whenever the random salt or the
random hash happens to start with a letter or an underscore — roughly five times
in six, independently per deployment. Nothing fails at deploy time. `compose
config` emits one warning naming a base64 string, and `panel-bootstrap.sh`'s
health check passes, because the control plane is perfectly healthy — it simply
holds a truncated hash that no password matches. The operator is locked out of
the panel that holds every node key, and the runbook's next line congratulates
them.

It also explains why the existing deployment worked: it got the lucky sixth.

**The fix is not "tell the operator to escape it".** A person copying a hash out
of a terminal at three in the morning will not double five dollar signs, and the
failure they get is a 401 with nothing to grep for. The value must be carried in
a form that cannot be interpolated, or emitted pre-escaped by the command that
prints it, or verified after boot by something that would notice — the control
plane knows both the hash it loaded and the shape it should have.

**E2E:** this is exactly the assertion `tests/e2e/infra/` exists for — bring a
stack up from an env file containing a freshly generated hash and log in. A unit
test cannot catch it: the mangling happens in compose, outside Python. Note a
test that hashes one fixed password will pass or fail *at random* unless it
forces a hash whose last field starts with a letter.

**Done when**
- [ ] A hash generated by `control.cli hash-password` and pasted into `.env`
      verbatim produces a control plane its operator can log into.
- [ ] Something fails loudly at boot if the loaded hash is not a well-formed
      scrypt string, rather than answering 401 forever.
- [ ] A scenario covers it, and is not itself a coin flip.

### M6.5 — `panel-bootstrap.sh` is not idempotent, and its own header says it is · found 2026-09-09

`scripts/panel-bootstrap.sh`'s header enumerates four properties it holds itself
to. The first is:

> **1. IDEMPOTENT. A second run changes nothing.** Nothing below deletes,
> recreates or re-initialises; `compose up -d` converges and leaves running
> containers alone.

It does not hold. `tests/e2e/infra/test_panel_bootstrap.py::test_running_it_again_changes_nothing`
— a scenario that already exists, and which asserts the property on **container
identity** rather than on an exit code — fails: a second run replaces a
container. Observed twice, replacing a *different* container each time, so which
service is recreated is not even stable.

**This is pre-existing, and that is the point.** Verified by running the same
scenario at `b155a5f`, the commit before the field run began: it fails there
identically. Nothing in this run caused it.

**Why nobody knew.** `make test` deliberately excludes e2e — a gate that silently
needs Docker is one agents skip — and CI runs the same three zone targets. So
`tests/e2e/` is not run by anything automatic, and this scenario has been failing
for as long as it has existed while every green signal the project has stayed
green. It is the same shape as every other defect this run found: the check
existed, and nothing ran it.

**Why it matters more than a flaky test.** The scenario's own docstring says it:
recreating the database container is a restart of *the one service whose loss
cannot be repaired by rebuilding a node*, and an operator re-running the script
after fixing an unrelated typo must not risk it. The runbook tells operators to
re-run this script.

### M6.6 — Something must run the e2e suite

A scenario nothing executes is documentation. Whatever the answer is — a CI job,
a Make target the runbook names, a scheduled run — the property to establish is
that `tests/e2e/` failing becomes visible to somebody without a person choosing
to look. Note the honest constraint: these scenarios need a Docker engine, which
is exactly why `make test` excludes them, so this is a decision about where that
engine lives rather than a line of code.

**E2E:** none from `tests/e2e/` — the real check is a fresh host following the
runbook, and no suite rents one. `make test-infra` covers what can be asserted
about the script itself.

**Done when**
- [ ] Bootstrap's success line is reachable from outside, or it does not print one.
- [ ] A fresh host following the runbook produces no connection log.

acceptance: no

---

## → M7 — Panel off the public internet · planned 2026-09-08 · reshaped 2026-09-09

> **Decision 2 was reversed on 2026-09-09 and this milestone changed shape with
> it.** The panel is reached over a **dedicated WireGuard management tunnel**, not
> Tailscale. `docs/decisions.md` carries all three lines — the original choice,
> its reaffirmation on measurement, and the reversal — because the sequence is
> the record. Everything below about *splitting the Caddy site* stands unchanged;
> only the private network it binds to is different.
>
> **What prompted it.** Measured from the entry host:
> `tailscale.com` fails its TLS handshake while `controlplane.tailscale.com`
> answers in 150 ms — so Tailscale worked, and the filtering of that company is
> nonetheless real, present and per-hostname. Today's reachability is an
> observation, not a guarantee, and an emergency rotation is exactly when it
> would matter. Detail in `docs/tracker/M7/field-notes.md`.
>
> **Three things the implementation must get right, none of them obvious:**
>
> 1. **The bootstrap prints the owner's config once.** The panel cannot hand you
>    the config you need to reach the panel. This is a real chicken-and-egg and
>    it belongs in `scripts/panel-bootstrap.sh`, which is the control plane's own
>    bootstrap — **not** `node-bootstrap.sh`, which M11.1 fixed at docker, the key
>    and the firewall and nothing else.
> 2. **It must not be a `node_transports` row.** That shape carries one
>    `peer_tunnel_address` and therefore serves exactly one device — **M17** — and
>    an owner with a laptop and a phone needs at least two peers. The management
>    tunnel takes N peers by construction.
> 3. **Use the obfuscated transport, not plain WireGuard.** A plain handshake is
>    fingerprintable, and this is the one tunnel that has to work when everything
>    else is being blocked. (Plain WireGuard is also unusable here for unrelated
>    reasons — **M20**.) Note the management tunnel needs no forwarding or NAT: it
>    carries traffic *to the host*, not *through* it, so M14's rules do not apply
>    and must not be rendered for it.
>
> **Still true and still the hard part:** `/sub/{token}` must stay public, because
> a friend refreshes their config from inside Russia at exactly the moment a node
> was blocked. The site splits in two either way.

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

**Blocked on two owner decisions — 1 and 2 below.** This is a charter amendment,
and the project's own rule is consent first, then the charter, then the plan — in
that order, never the reverse. *Both are answered: 1 yes, 2 reversed on
2026-09-09 to a WireGuard management tunnel — see the note at the top of this
milestone.*

### M7.1 — Split the Caddy site in two
### M7.2 — Bind the panel and API to the private interface, with its own certificate
### M7.3 — Document the way back in when the private network is unavailable — and TEST it

SSH remains the fallback either way.

> **Raised to "tested" on 2026-09-09**, after the owner pointed out that ТСПУ
> detects plain WireGuard. The obfuscated transport is the answer to that and it
> is what this milestone uses — but the honest position is that nothing in this
> fleet can prove how the owner's *home or mobile* network behaves, because the
> operator's machine and the entry host share a cloud region and their traffic
> may never traverse ТСПУ at all. A fallback that has only been written down is
> worth nothing on the day it is needed, and the day it is needed is an emergency
> rotation. **Leave SSH access verified working, not merely described.**

**E2E:** none — the check is reachability from two different networks, which no
suite running on one machine can stage.

**Done when**
- [ ] The panel is unreachable from a public address.
- [ ] `/sub/{token}` still resolves from an ordinary network, unchanged.
- [ ] A documented way back in when the private network is unavailable.

acceptance: yes
From an ordinary public network, try to open the panel — it must not be there.
From the tailnet, open it and sign in normally. Then, from the ordinary network
again, fetch a friend's `/sub/{token}` and confirm the subscription still
resolves. Last, with the private network unavailable, follow the documented route
back in and confirm it works.

---

## → M8 — The console the owner actually lives in · planned 2026-09-08

The panel today is one scrolling page plus a node detail page, dressed in twenty
lines of inline CSS. `design/` holds a finished, high-fidelity redesign of it:
nine screens behind a persistent sidebar, every creation flow in a dialog, and the
24-field hop form collapsed behind a disclosure. The job it optimises for —
*"add a user, hand them their subscription link, and see at a glance whether the
mesh is healthy"* — is criteria 2 and 3 word for word, so this is not decoration.

**The source of truth is the three written documents**, not the prototype:
`design/README.md` (the handoff), `design/UI-PATTERNS.md` (how to add a screen
without the panel drifting) and `design/design-system/styles.css` (the tokens).
`design/VPN Admin.dc.html` is a reference drawing — it links a `_ds/` bundle and a
`support.js` the handoff does not ship, so it does not even render standalone.
Recreate the design in the stack the panel already has; do not copy its markup.

**No framework arrives with this.** "Sidebar navigation swaps the main region; no
page reload" is HTMX against a `#main` target, which is what the project already
serves from its own `/static`. The stack rule stands: Jinja2 + HTMX, no bundler.

**Three things in the design cannot be built as drawn, and one of them matters.**

- *The stylesheet fetches fonts from Google.* `styles.css:2` is
  `@import url('https://fonts.googleapis.com/…')`. The panel must not fetch
  anything from a third party — `base.html` already refuses a CDN for HTMX,
  because "the panel must work on a network where the CDN is blocked, which is the
  same network the operator uses to fix a blocked node," and M7 puts the panel on
  an interface where that request may have no route at all. It also tells a US
  company every time the owner opens their VPN console. The `@import` goes;
  decision 7 says what replaces it.
- *Four cells measure people.* "throughput now" (Overview), "last seen" (Users),
  node "load" (Nodes) and the whole **Traffic screen** — per-user down, up,
  sessions and busiest node. The charter's non-goals name all of it: *"No traffic
  logging, no DNS logs, no per-user analytics. Not 'off by default' — absent, so
  there is nothing to seize or subpoena."*
  `tests/control/test_zone_invariants.py::test_no_model_records_anything_about_a_connection`
  turns red the moment a model grows a field for any of them. The design is right
  about the layout and wrong about those four cells, because it was drawn without
  the charter in hand. Decision 6 chooses what stands in their place; the layout
  survives either way.
- *The design renames friends to users.* Its own note says the prototype "is still
  named `friends` internally — rename on implementation," which points the wrong
  way for us: `friend` is the word in the models, the services, the API, the tests
  and the charter. The recommendation is to keep `friend` in the code and decide
  only the visible label — decision 9.

This milestone lands the foundation and the two screens that carry the primary
job. The fleet screens follow in M9, and the two that need records the project
does not keep are M10. Until M9 lands, the sidebar keeps one entry pointing at
today's page for everything not yet ported — a dead nav link is worse than an
honest one.

### M8.1 — Vendor the design system, minus its third-party font fetch

Serve `styles.css` from `/static`. Every colour, space, radius and shadow comes
from its variables; nothing gets hard-coded past them.

### M8.2 — The shell: sidebar, header, panel body, and the 900px collapse

One breakpoint, per UI-PATTERNS §12. Grids are `repeat(N, minmax(0, 1fr))` so they
collapse under the rule that already exists rather than a new one.

### M8.3 — The toast and the dialog primitive

Every mutation emits a toast naming its object (`<nick> revoked — link is dead`),
one at a time. `.dialog` needs an opaque background — the design system's is
transparent, and the handoff says so twice.

### M8.4 — Overview

Four stat cards and the preview tables, carrying only facts the control plane
already holds.

### M8.5 — Users, with the add-user and subscription-link dialogs

Submitting the nickname creates the user, closes, and opens the link dialog by
itself. The link is a bearer credential: it may not reach a query string, a log
line or an error message.

### M8.6 — The states the design did not draw

Empty, loading, request failure, and field-level validation — for these two
screens. A first-time operator meets the empty state before anything else, which
is exactly the seed the acceptance stand uses.

**E2E:** the existing `tests/e2e/control/` scenarios stay green —
`test_the_owner_issues_and_revokes_access.py` and
`test_request_paths_are_never_logged.py` above all. Where one asserts a fact on
the old single page, it moves to the screen that now owns that fact; relaxing the
assertion instead is how this kind of rewrite loses its cover. One new scenario:
**the panel fetches nothing from a third party** — no font, script or stylesheet
from an origin that is not this host. It pins decision 7 permanently, and it is
the only part of this milestone a test can hold. `make test-control` is the gate.

**Done when**
- [ ] The panel opens on the new console — sidebar, header, framed panel — at the
      design's colours, type and spacing.
- [ ] The owner adds a user in a dialog and the link dialog follows on its own,
      with a copy button that works.
- [ ] No screen shows a per-user or per-connection number anywhere, and no model
      grew a field that could produce one.
- [ ] Every page loads from this host alone, proven with the machine's outbound
      network cut.
- [ ] Empty, loading and failure states are drawn for both screens: a fresh
      install shows an empty state that says what to do next, not a broken table.
- [ ] At 900px the sidebar becomes a top scroller and nothing runs off the side of
      the page.

acceptance: yes
On the stand, with nothing in it but the operator account, sign in. First judge it
empty: the console has to tell a first-time owner what to do next, not show blank
boxes. Add a user called `dima` from the header button — the link dialog should
appear by itself; copy the link and open it in another tab. It must resolve (the
empty stand has no node to offer yet, so an empty subscription is the correct
answer — a 404 or an error is not). Then go looking for anything the panel claims
to know about who connected, how long ago, or how much they used: it must not be
there, on any screen. Last, narrow the window below 900px and check the console is
still operable rather than merely still rendering.

---

## → M9 — The fleet screens, and the old page retires · planned 2026-09-08

Nodes, Hops, Transports and Keys & configs, with the add-node and establish-hop
dialogs. Same design, same rules as M8 — read its prose first, it carries the
constraints for all three of these milestones.

**The hop dialog is the biggest usability claim in the handoff.** Establishing a
hop asks 27 parameters today, all at once, in one flat form. The design asks three
— entry node, leaf node, transport — and puts the other 24 behind
`<details> advanced tuning — 12 parameters per end`, every field carrying its
transport default as a placeholder so an empty box visibly means "use the
default". This is the form the runbook has you open during a rotation, which is
the worst possible moment to read 27 labels.

**The old pages are deleted at the end of this milestone, not at its start.**
Until every action they carry has a new home, removing them removes the only way
to do the job.

### M9.1 — Nodes, with the add-node dialog

### M9.2 — Hops, with the establish-hop dialog and its advanced-tuning disclosure

### M9.3 — Transports — the read-only capability table

Including the "on a filtering network" column, and the row that says a protocol is
identified and blocked and must never be offered as an exit. That sentence is
transport metadata, not a case statement in a template: no template may name a
transport, which is the same hard rule the code lives under.

### M9.4 — Keys & configs

Fingerprints truncated, rotation in place. UI-PATTERNS §9: where key material
could appear, the panel prints the rule instead. Nothing displays a private or
preshared key — the API already withholds both, and the panel must not become the
place they surface.

### M9.5 — Retire `pages/index.html` and `pages/node.html`

**E2E:** none new — the behaviour is unchanged and only the markup moves. The
scenarios that already cover it must stay green against the new screens:
`test_a_replacement_node_and_a_protocol_from_the_panel.py`,
`test_the_panel_never_offers_a_blocked_protocol_as_working.py`,
`test_a_hop_never_reaches_a_friend.py` and
`test_rotation_does_not_move_the_link.py`. `make test-control` is the gate.

**Done when**
- [ ] Every action the old pages offered has a home on a new screen: add node,
      enable and disable a transport, apply, probe, set state, establish and tear
      down a hop, rotate keys, replace params.
- [ ] Establishing a hop asks three questions; the other 24 parameters are behind
      the disclosure, each showing its own transport's default as a placeholder.
- [ ] No template names a transport, a country, an address or a port.
- [ ] No key material appears anywhere in the panel; fingerprints are truncated.
- [ ] `pages/index.html` and `pages/node.html` are gone and nothing links to them.

acceptance: yes
On the stand, register a node, enable a transport on it and apply — every step
from the new screens, with no URL typed by hand. Then establish a hop between two
nodes and check the dialog lets you answer three questions and leave the tuning
alone. Open the transports screen: it must name a protocol the panel refuses to
offer as an exit and say why, in words. Then hunt for a private key anywhere in
the console — you must not find one. Applying will fail on the stand, because
there is no real host behind the node; that is expected, and what is being judged
is that the failure arrives on the screen in plain words instead of a blank page
or a raw error. If the failure is the wrong message about a draft node, that is
M4's known bug and not a finding here.

---

## → M10 — The two screens that need records this project does not keep · planned 2026-09-08

Audit log and Settings. Both ask for something that does not exist, and one of
them may be something the charter should refuse outright — which is why they are
last and not folded into M9.

**Audit log.** There is no audit trail anywhere in the tree; `grep -ri audit
control edge docs` returns nothing. Building one means a new table written on
every mutation. It is *not* a connection log — it records what the operator did,
never who dialed what — but it is still a new durable record naming friends and
times, sitting on the one machine most worth seizing, and the charter's whole
argument is that such records are *absent, so there is nothing to subpoena*.
Whether it exists at all, what it may record, and whether it keeps the operator's
own source address, is decision 8.

**Settings.** The design draws an Admins table (user / role / last login) and a
form for mesh name, subscription base URL and log retention days. There is one
operator, configured from the environment (`HASHI_OPERATOR_USERNAME`,
`HASHI_OPERATOR_PASSWORD_HASH`); more than one is a charter non-goal — *"One
operator, one fleet"* — and there is no log to retain, by construction. A form
that saves a value the process only reads from the environment at boot is a lie
told in a text field. The proposal is a Settings screen that shows what this
control plane is configured with and says where each value is actually changed,
with a single-row Admins table. Also decision 8.

### M10.1 — Settle what Settings can honestly show, and what it may change

### M10.2 — Settings, read-only wherever the value comes from the environment

### M10.3 — The audit trail, if decision 8 says there is one

### M10.4 — The audit log screen

**E2E:** none new if decision 8 says no. If it says yes, one scenario asserting
the audit trail contains no token, no subscription URL and nothing about a
connection — a record that grows those is the failure mode worth a test.
`make test-control` is the gate either way, and
`test_no_model_records_anything_about_a_connection` already stands over any new
model without being asked.

**Done when**
- [ ] Settings shows the owner what this control plane is actually configured
      with, and names where a value is changed when the panel cannot change it.
- [ ] Nothing on Settings claims to save a value the running process would not
      then use.
- [ ] Decision 8 is written down in `docs/decisions.md`, whichever way it went.
- [ ] If an audit trail exists, it holds no token, no subscription URL and nothing
      about who connected.

acceptance: yes
On the stand, open Settings and check that every value it shows is true of the
control plane you are signed into, and that anything it will not let you change
says where it is changed instead. If the audit log shipped, change two things
about the fleet, then open it: both must be named in plain words, with no token
and no subscription link anywhere in sight.

---

## ✅ M11 — One script prepares a host to be a node · planned 2026-09-08 · done 2026-09-09

> **Closed 2026-09-09.** Acceptance completed once apply worked — see the
> "Acceptance completed" section of `docs/tracker/M11/outcome.md`. Both field
> hosts were prepared by this script alone and both became working nodes carrying
> real traffic, with nothing else typed on either box. **Not proven:** the
> script's Docker *install* path, since both hosts already had Docker — only its
> "already present" path was exercised.
>
> **Field run 2026-09-08 — steps complete and reviewed clean.** M11.1–M11.3 each converged in
> one review round. M11.4 is **proven on two real hosts**: on a non-root host
> with docker present and `ufw` inactive, and on a root host with `ufw` already
> active carrying its own rules and hashi already applied to it. The second run
> on the first host was **byte-identical** — `authorized_keys`, `/etc/ufw/ufw.conf`,
> `/etc/default/ufw`, `/etc/ufw/user.rules` and the rule set, mtimes included.
> The other host kept its own firewall rules and its four running containers.
>
> **What is left, and why it is not this milestone's fault.** The acceptance
> scenario ends *"register it in the panel and apply — it must become a working
> node"*. The node was registered and a transport enabled; the apply returned
> `409: a node cannot go from draft to degraded`, which is **M4's known bug**, and
> the underlying reason was destroyed with it. So the milestone closes when apply
> works — after M4, M1 and M2 — not because anything about the script is
> outstanding. See the reordering note in the general rules above.

`edge/bootstrap/node_stack.py:212` refuses a node that has no docker, and says
why in as many words: *"hashi configures upstream data-plane containers and does
not install a container runtime for you."* That is the right boundary for the
library and it leaves a hole in the product. `scripts/panel-bootstrap.sh` brings
a control plane up in one command; a leaf has no equivalent, so every leaf host so
far was prepared by hand.

**A hand-prepared host is a host you cannot rebuild at three in the morning** —
which is precisely when you rebuild one. The charter's "destroy and replace in ten
minutes" is a claim about a *script*, and there isn't one.

**Owner's requirement, 2026-09-08:** every host configuration is reproducible from
this repository, and a new leaf comes up with one script. Nothing the fleet does
to a host by hand may stay by hand. **Sequenced first in the field run**, ahead of
M1: the two hosts it prepares are what M1, M2 and M3 are then verified on, and
writing the script while doing the work is the only way it ends up true.

### M11.1 — `scripts/node-bootstrap.sh` — docker, the key, the firewall, nothing else

No hashi code and no state. A node holds nothing that cannot be regenerated from
the control database, and this script must not invent the first exception.

### M11.2 — Make it idempotent, and say what it does not do

The cloud-level firewall — a provider's security groups — sits outside the host
and outside the script's reach. It gets named in the runbook, not silently
assumed, because a closed security group looks exactly like a broken transport.

### M11.3 — The runbook grows a leaf section

### M11.4 — Prove it on a host that has never run hashi

**E2E:** `tests/e2e/infra/`, following `test_panel_bootstrap.py`. The real proof is
an untouched host, which no suite rents; the scenario asserts what can be asserted
about the script itself. `make test-infra` is the gate.

**Done when**
- [ ] A fresh host becomes a usable node with one command, plus the provider's
      firewall.
- [ ] No step in the sequence survives only in someone's shell history.
- [ ] Running the script twice on the same host changes nothing and breaks
      nothing.
- [ ] `ufw logging off` is part of it — a node must never start collecting the one
      record the charter forbids.

acceptance: yes
Take a host that has never run hashi. Run the one script, then register it in the
panel and apply — it must become a working node without a second command typed on
the box itself. Then run the script again on that same host and check nothing
breaks and nothing changes. If a step still has to be done by hand, this milestone
is not done, however well the node works afterwards.

---

## → M12 — The acceptance hands must actually hold a browser · found in the field 2026-09-08

**Appended during the overnight field run, not planned.** Found by running
`scripts/acceptance/drive.py` for the first time against a stand that had just
come up cleanly. It is the same lesson as M1, M2 and M3, one layer further out:
everything checkable by *rendering* works, everything checkable only by *running*
does not — and this time the thing that did not run was the instrument the plan
intends to judge M8, M9 and M10 with.

**The bug.** `deploy/docker-compose.e2e.yml:70` pins the browser service to
`mcr.microsoft.com/playwright/python:v1.55.0-noble`. That image ships the browser
binaries under `/ms-playwright` and it ships `pip` — it does **not** ship the
`playwright` Python package. `drive.py` imports it at `serve()`:

```
ModuleNotFoundError: No module named 'playwright'
```

so every verb fails, and the stand around it is perfectly healthy while it does.

**Why it stayed invisible, and this is the part worth keeping.** `begin` starts
the in-container server with `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`
(`drive.py:469`), then waits for a socket that never appears and reports the one
thing it can still see:

```
[drive] action failed: the browser did not come up inside the stand
```

That message names the *symptom* and hides the *cause*, and it points at the
stand — which was fine. An agent reading it would go and debug compose, the
profile, the network and the health checks, all of them working, for as long as
its patience lasted. The traceback existed the whole time and had been thrown
away on the line above.

**Confirmed, not guessed:** installing `playwright==1.55.0` inside the running
container made `begin` and `open` succeed immediately, returning the panel's
accessibility tree and writing its screenshot. Nothing else was wrong.

### M12.1 — The browser image carries the package it is imported for

Build the browser service from a small Dockerfile rather than pulling the bare
upstream image, exactly as `deploy/docker/caddy.Dockerfile` already does and for
the recorded reason — *config must travel with the image*. The `playwright`
package version and the image tag are the same version and must not be able to
drift: derive one from the other with a build argument rather than writing
`1.55.0` twice.

Installing at container start instead is the wrong shape: it puts a package
index on the critical path of every acceptance run, and an acceptance stand that
cannot come up without the network is one more thing to debug at three in the
morning.

### M12.2 — A failed verb must report the cause, not only the symptom

`begin` discards the in-container server's stderr. Keep the diagnosis: capture it
and print it when the socket does not appear. "The browser did not come up inside
the stand" sent the reader to the one layer that was working.

### M12.3 — A check that the hands work, before a milestone leans on them

`stand.sh up` reports ready on a stand whose driver cannot take a single action.
Prove the instrument, not just the subject: the cheapest honest check is one real
verb through the real driver.

### M12.4 — `down` must take away everything `up` started

`stand.sh up` starts the browser through `E2E_PROFILES=browser`; `make e2e-down`
runs `docker compose down -v` with **no profile**, so compose does not know the
browser service exists and leaves it running. Observed: after a clean
`stand.sh down`, `hashi-e2e-browser-1` was still up, holding its 1 GB of shared
memory. Every acceptance run leaks one, on a host the plan already describes as
short of memory.

It also defeats `up`'s own safety check. `up` tears down first and then refuses
to continue if anything still answers `/healthz` — a leaked browser answers
nothing, so it passes that check and accumulates instead.

**E2E:** `tests/infra/`, beside `test_drive.py`, which already exists and did not
catch this — it tests the driver's argument handling on the host and never asks
whether the container can import what the driver imports. The assertion worth
adding is the one that would have gone red: the browser image the compose file
names can import `playwright`. `make test-infra` is the gate.

**Done when**
- [ ] `drive.py begin` succeeds against a freshly built stand with no package
      installed by hand.
- [ ] The playwright package version and the browser image tag cannot drift
      apart.
- [ ] A `begin` that fails prints why, not only that it did.
- [ ] Bringing the stand up and taking one real action is a single documented
      step, and something runs it.
- [ ] `stand.sh down` leaves no container behind, browser included.

acceptance: no
Its own proof is a verb that works, and every acceptance run from M8 onward
exercises it. A milestone whose subject is the acceptance instrument cannot be
judged by that instrument.

---
## ✅ M13 — A node the control plane logs into as anything but root · found in the field 2026-09-08 · done 2026-09-09

> **Closed in the field run.** Shape one: the bootstrap script creates
> `/opt/hashi` empty, `0700`, owned by the account it tells the operator to
> register; `edge` acquires no notion of privilege. One review round, clean, no
> findings at any severity. Gate green — 169 control, 139 edge, 96 infra.
>
> **Acceptance discharged by field observation**, not on the stand, which has no
> real node — the same rule this plan already applies to M1, M2, M3 and M7. On
> the non-root entry host the apply now returns
> `200 {"transports_applied":["vless-reality"]}`, the node is `active` and
> `healthy`, the data-plane container is `Up` and its config is on disk owned by
> the non-root account. Verified by the run's orchestrator rather than an
> independent acceptance agent; see `docs/tracker/M13/outcome.md`.
>
> **The apply succeeded while that host's control plane was still running the
> pre-M13 library.** The script alone made a non-root node work, which is shape
> one's central claim demonstrated rather than argued. See
> `docs/tracker/M13/field-proof.md`.

**Appended during the overnight field run.** Found on the first apply to a host
prepared by M11's own script, which is the point: the two halves of the product
disagree, and the disagreement is invisible from either side alone.

**The bug.** `edge/bootstrap/node_stack.py` prepares a node with

```
mkdir -p /opt/hashi/conf && chmod 700 /opt/hashi /opt/hashi/conf
```

over the SSH connection, with no privilege escalation. `NODE_ROOT` is `/opt/hashi`
and `/opt` is root-owned, so on a node registered with any non-root `ssh_user`
this is:

```
mkdir: cannot create directory '/opt/hashi': Permission denied
```

Reproduced by hand as the registered user. The node is reachable, the key works,
docker works — and nothing of hashi's can ever be written to it.

**Why it went unnoticed, and why it will not stay unnoticed.** Every host in the
project's history was reached as `root`, and the runbook's Shape A says so. But
`scripts/node-bootstrap.sh` — landed hours ago in M11 — deliberately supports a
non-root account with passwordless sudo, puts that account in the `docker` group,
and ends by printing `register it in the panel with ssh_user <user>`. It tells
the operator to do the one thing the control plane cannot do. A cloud host whose
default account is not root is the normal case, not the exotic one.

**What made it expensive to find, and this is the part worth keeping.** The apply
returned `409: a node cannot go from draft to degraded` — M4's bug — and the
control plane logged one line, `domain error: conflict`. The real reason was
destroyed while being handled. It took a node health probe, an inspection of the
host, and reproducing the command by hand to recover a one-line permission error.
That is the whole argument for M4 being sequenced first, made concrete.

### M13.1 — Decide where the privilege boundary belongs, and write it down

Three shapes, and this is a decision rather than a detail:

- **The script creates the directory it will own.** `node-bootstrap.sh` already
  runs privileged on the host and already grants the account docker access; a
  root-owned `/opt/hashi` handed to the node's user is the same category of host
  preparation, and it keeps `edge` free of any notion of privilege. Recommended.
  Note the tension to resolve honestly: M11.1 says the script leaves *"no hashi
  code and no state"*, and this is an empty directory, not state — say so where
  it is created, or the next reader will think the rule was broken.
- **`node_stack` escalates when the user is not root**, declared per node rather
  than sniffed. Keeps the script minimal; puts `sudo` into the edge library.
- **Refuse a non-root `ssh_user` at registration**, and make the script stop
  advertising one. Honest, and the smallest change, but it gives up hosts whose
  provider does not offer root.

### M13.2 — Whichever shape wins, the two halves must agree in a test

The failure was possible because the script's advertised contract and the
library's assumption were never checked against each other. A test that pins
them together is worth more than either fix.

### M13.3 — The runbook says which accounts work

**E2E:** `tests/e2e/` cannot rent a non-root host, but the assertion that the
node root is creatable by the registered user — or that a non-root registration
is refused — is unit-testable in whichever zone the fix lands. `make test-edge`
or `make test-control` is the gate depending on M13.1's answer.

**Done when**
- [ ] A node registered with a non-root `ssh_user` either applies successfully,
      or is refused at registration with a reason that names the problem.
- [ ] `node-bootstrap.sh` and the control plane agree about which accounts work,
      and a test fails if they stop agreeing.
- [ ] The runbook says which accounts work.

acceptance: yes
On the entry host, which is reached as a non-root account with passwordless sudo,
register it and apply. It must become a working node — or, if the decision was to
refuse non-root, the refusal must arrive at registration and say why, and the
bootstrap script must no longer tell the operator to register that account.

---

## ✅ M14 — A WireGuard-family node accepts a friend and carries nothing · found in the field 2026-09-09 · done 2026-09-09

> **Closed in the field run.** One review round, `0 critical, 1 high` — the High
> was that a real limitation had been left with no written trace, not a defect in
> the code; it is now `docs/tracker/M14/carry-over.md` and a decision entry. Gate
> green — 183 control, 210 edge (3 skipped), 96 infra.
>
> **Both testable "done when" bullets discharged on real hardware** — see
> `docs/tracker/M14/field-proof.md`. A real client from the friend's own
> subscription loaded four sites through the tunnel including a **119 KB** page,
> exiting at the node's address, where before M14 the same client completed a
> handshake and every request timed out. Disabling the transport removed every
> rule, the interface and the container; re-enabling restored **exactly one**
> masquerade rule, not two.
>
> **Known limitation, recorded not fixed:** proven for `amneziawg`. The plain
> WireGuard image ships `iptables` on the legacy backend, which on a ufw host
> cannot front-run ufw's nft `DROP`, so a friend-facing `wireguard` row is
> unproven and likely to fail in exactly this milestone's shape. Owner's decision
> of 2026-09-09: the pin stays, the limitation is written down.

**Found while discharging M2's second "done when".** M2 made both WireGuard-family
containers start; this is what the next question revealed.

**Measured on the entry node with a real AmneziaWG client**, built from the
friend's own `client-config-file` subscription:

| | |
|---|---|
| container | `Up` |
| interface in the node's netns | present, `UP,LOWER_UP` |
| handshake | **completes, both ends** — `latest handshake: 17 seconds ago` |
| bytes | client sent 2.02 KiB, received 252 B |
| an address echo through the tunnel | **times out** |

So the tunnel is genuinely established and the friend carries **nothing**.

**The cause, confirmed on the host.** `net.ipv4.ip_forward = 1`, but:

- `iptables -t nat -S POSTROUTING` masquerades only the docker bridges. **There is
  no rule for the tunnel subnet.**
- `iptables -S FORWARD` has policy **DROP** (ufw's `deny (routed)` default).
- The rendered node config has **no `PostUp`/`PostDown`** — nothing adds either
  rule when the interface comes up, or removes it when it goes down.

A friend's packet is decrypted onto the tunnel interface and then dropped by the
FORWARD chain, having never been NATed. Nothing logs it, because logging is off
by charter — and it should stay off.

**What is NOT wrong, so nobody "fixes" it.** The server-side
`AllowedIPs = 10.77.0.2/32` is correct: on a WireGuard *server* that field means
"the source addresses I accept from this peer", and the config's own comment is
right that a default route there would swallow the node's own SSH session. The
client side's `AllowedIPs = 0.0.0.0/0` is also correct. The two are consistent.
The gap is the node's forwarding policy, not either config's peer list.

**Why this is on M3's critical path and not only M2's.** The entry→leaf hop needs
the *leaf* to forward and masquerade traffic arriving over the hop. That is the
same missing capability, at the other end. M3 cannot show a foreign exit address
without it.

### M14.1 — A friend-facing tunnel's traffic must leave the node

Add the forwarding and NAT the interface needs, tied to the interface's own life
so it is removed when the tunnel goes down. `wg-quick`'s `PostUp`/`PostDown` is
the idiomatic place and keeps it in the node's config rather than in host state,
which suits a project whose nodes hold nothing that cannot be regenerated.

**The egress interface name is the trap.** It is not `eth0` everywhere, and a
hardcoded one is exactly the kind of value `CLAUDE.md` forbids. Derive it, or
write the rule so it does not need one.

### M14.2 — And it must stop when the tunnel does

A `PostUp` without a matching `PostDown` leaves a NAT rule behind on a node whose
transport has been disabled — a quiet, growing residue on a host the project
promises holds nothing.

### M14.3 — Decide what a node forwards, and say so

Not every tunnel should exit locally. A hop's far end must forward into the hop,
not masquerade out of the entry — that is M3's subject and decision 3's fail-closed
rule. This step is about making the *policy* explicit and data-driven rather than
implied by whichever rules happen to exist, so M3 has something to build on
rather than around.

**E2E:** the honest check is a client that carries traffic, which needs a real
node — M5's territory. What a suite can assert here is that a rendered config
that brings an interface up also carries the rule that makes it useful, and that
every `PostUp` has a matching `PostDown`.

**Done when**
- [ ] A friend on a WireGuard-family transport reaches the internet, and the exit
      address is the node's.
- [ ] Disabling the transport removes every rule it added; a node that has been
      applied and un-applied has no residue.
- [ ] No egress interface name, address or port is hardcoded.

acceptance: yes
On a live node, enable a WireGuard-family transport, connect a real client from
its own subscription, and load a page — the handshake alone is not the test, and
this milestone exists because a handshake succeeded while nothing moved. Then
disable the transport and check the node's NAT and FORWARD rules are as they
were before.

---

## → M15 — A transport enabled for friends locks that node out of a hop, permanently · found in the field 2026-09-09

**Found while setting up M3's two-hop on the real fleet.** Establishing a hop
between the two live nodes was refused:

```
409  'amneziawg' is already configured on node 'entry-ru'
```

**The mechanism.** `control/app/services/relay.py`'s `establish_hop` refuses when
a `NodeTransport` row already exists for `(node, transport_name)` — **regardless
of its `purpose`**. A friend-facing `amneziawg` row and a hop's `RELAY_ENTRY`
`amneziawg` row are the same `(node, transport_name)` pair, so the first one
enabled excludes the other forever.

**Why "permanently" is the right word, and this is the part that matters.** There
is no way back:

- there is **no delete for a node transport** — `set_transport_enabled` only flips
  `enabled`, and the uniqueness check does not look at that flag;
- `dissolve_hop` refuses anything that is not already a hop end (*"that transport
  is not part of a hop"*), so it cannot clear a friend-facing row;
- there is **no delete for a node** either, and retiring one does not free the
  pair.

So an operator who enables `amneziawg` for friends on a box has silently decided
that box can never be an entry node over `amneziawg`, and nothing tells them.
The only exit is editing the database by hand.

**The collision is not hypothetical — the runbook creates it.** The same runbook
**mandates** `amneziawg` for the entry→leaf hop and **recommends** it for Shape A,
where friends dial the same box. Following both pieces of advice in the obvious
order produces a node that cannot host the hop the runbook requires.

**Whether the uniqueness rule itself is right is a separate question.** One row
per `(node, transport)` keeps ports and interface names unambiguous, which is a
real argument — two `amneziawg` rows on one node would need two ports, two
interface names and two config files, and M2 derives the interface name from the
config filename. The defect is not necessarily the rule; it is that the rule is
enforced at the *worst* moment, in terms of the wrong concept (`transport_name`
rather than what actually has to be unique), with no way to undo the state that
triggers it and no warning that it is being created.

### M15.1 — Decide what actually has to be unique

If it is the port and the interface name, say so and check those instead — a
node could then run a friend-facing and a hop `amneziawg` on different ports.
If it is genuinely one row per transport per node, then the refusal must arrive
when the friend-facing transport is enabled, naming the consequence, rather than
months later when a hop is attempted.

### M15.2 — A node transport must be removable

Disabling is not removing, and the difference is invisible until it is
load-bearing. Removing a friend-facing transport should take its credentials with
it, exactly as `dissolve_hop` already does for a hop end.

### M15.3 — The runbook must not recommend a combination the product refuses

**E2E:** `tests/e2e/control/` — establish a hop on a node that already offers that
transport to friends, and assert whichever behaviour M15.1 chooses. The scenario
that would have caught this is "follow the runbook's own Shape A advice, then add
the hop it mandates". `make test-control` is the gate.

**Done when**
- [ ] Either a node can host a friend-facing and a hop end of the same transport,
      or it is refused at the moment the *first* one is created, with the
      consequence named.
- [ ] A node transport can be removed, not merely disabled.
- [ ] The runbook's Shape A advice and its hop requirement do not contradict each
      other.

acceptance: yes
On a fleet where a node already offers a transport to friends, try to make that
node the entry end of a hop over the same transport. Whatever the answer is, it
must arrive with a reason an operator can act on — and if the answer is no, it
must have been said earlier, when the friend-facing transport was enabled.

---

## → M16 — The exit is Amsterdam, the DNS lookup is still Russia · found in review 2026-09-09

**Found by M3's reviewer, immediately after M3 was proven in the field.** The
two-hop works: a friend dialling the entry exits at the leaf's address, measured
on real hardware. This is the part that measurement does not cover.

**The gap.** An entry's friend-facing Xray outbound resolves a domain destination
through **the node's own resolver** before it opens the connection. `sendThrough`
binds the *TCP* socket to the hop; nothing rendered binds the *lookup*. There is
no `dns` object and no `domainStrategy` in either proxy template. So for a friend
asking for a domain:

| | where it happens |
|---|---|
| the DNS lookup for the destination | **the entry node — in Russia** |
| the TCP connection carrying the request | the leaf, in Amsterdam |
| the address the internet sees | the leaf's |

M3's "done when" says *"a client connected to the entry node shows the leaf's
public address as its exit IP"* — and it does. The criterion is met exactly as
written. What the criterion does not say is that the friend's **destination
names** are still resolved from Russia, by a resolver the node did not choose,
one lookup per site visited.

**Why this is worth a milestone rather than a footnote.** The charter's whole
argument for the two-node topology is that a Russian box should learn as little
as possible about what a friend does. An exit address in Amsterdam with a
resolver in Russia leaks the one thing that is arguably most descriptive — the
list of names, in order, with timing. It is not a *connection log*: nothing is
stored, and nothing here contradicts the charter's non-goals. It is a live
metadata path, and it is invisible in exactly the way M3's was: every signal
green, the exit address correct, the question simply never asked.

**Not made worse by M3** — before M3 everything was in Russia, lookup and exit
alike. M3 moved the exit and left the lookup behind, which is why it surfaced now.

### M16.1 — Decide where a friend's destination names get resolved

The options are not equal and the choice is the milestone:

- **Resolve through the hop.** An Xray `dns` object with `domainStrategy` set so
  lookups follow the same outbound. Needs a resolver address the entry can reach
  *through* the tunnel — and a resolver address in a rendered config is exactly
  the kind of value `CLAUDE.md` forbids hardcoding, so it becomes node-record or
  transport data.
- **Do not resolve at the entry at all.** Pass the name to the far end and let it
  resolve. This is what a proxy on the leaf would give, and it is the cleanest
  answer — it is also the strongest argument for the leaf eventually running one,
  which shapes B and C currently say it does not.
- **Accept it and say so.** Write it in the runbook and the charter's own
  language, so an operator knows what the topology does and does not hide. Honest,
  and cheaper than either fix, but it narrows the claim the project makes.

### M16.2 — Whatever is chosen, a scenario must be able to see it

The reason this was invisible is that "what address does the internet see" and
"who resolved the name" are different questions and only the first was ever
asked. A test that watches where the lookup goes is the lasting half.

**E2E:** `tests/e2e/edge/` for what a rendered config asks for; the honest check
is a live observation on the two hosts, which no suite rents.

**Done when**
- [ ] It is written down where a friend's destination names are resolved, and why.
- [ ] If the answer is "not in Russia", a friend's lookup provably does not leave
      the entry node's own interface.
- [ ] No resolver address is hardcoded in code or in a template.

acceptance: yes
On the live fleet, connect a friend to the entry and watch where the destination
lookup goes — not where the traffic exits, which M3 already settled. Whatever the
decision was, the observed behaviour must match it.

---

## → M17 — A WireGuard-family transport can serve exactly one friend · found in the field 2026-09-09

**Found while discharging the run's one-hop instruction against the leaf.** With
two active friends on a node, enabling a friend-facing `wireguard` transport and
applying gives:

```
wireguard could not be rendered for this node — AmbiguousPeerRoute: two peers are
configured with the tunnel address '10.66.0.2/32'. AllowedIPs is both the
authorisation list and the routing table, so the second would silently take over
the first's route. Give each peer its own tunnel address.
```

**The refusal itself is excellent and must not be weakened.** It fails closed, it
explains the mechanism, and it is right: on a WireGuard server `AllowedIPs` is
simultaneously "who may send as this source" and "where replies to this address
go", so two peers sharing one tunnel address is not a duplicate — it is a silent
hijack of the first friend's return path by the second. Rendering it anyway would
have been the worst kind of bug this project has.

**The limitation it exposes is the milestone.** `peer_tunnel_address` is a single
operator parameter on the transport, so a WireGuard-family transport has exactly
one peer address to give out. **One friend.** The charter's own scale is *"the
owner and ~30–50 friends"*, and criterion 3 is adding a user without touching
anyone's device. A transport that serves one person can do neither.

**Why this was not seen before tonight.** Every earlier WireGuard-family test in
this run happened to have exactly one active friend at that moment — including
M14's proof that a friend carries traffic. That proof stands for what it
measured; it was one friend, and two would not have rendered at all.

### M17.1 — Decide whether a WireGuard-family transport is friend-facing at all

Three honest answers, and the choice is the milestone:

- **Allocate a tunnel address per credential.** The natural fix and the largest:
  the address becomes per-friend state, minted with the credential, released on
  revocation, and drawn from a pool the operator sizes. It is real IP-address
  management, which this project has deliberately never had.
- **Say WireGuard-family transports are hop-only** and stop offering them to
  friends. `wireguard` is already `hop_capable=False`, which would make it
  configurable and useful for nothing — so this answer probably means removing
  it, and keeping `amneziawg` for hops where one peer per end is exactly right.
- **Say they serve one friend, deliberately** — a personal node for the owner.
  Honest, narrow, and it should then be refused at *enable* time for a node that
  already has more than one friend, rather than at apply.

### M17.2 — Whatever is chosen, the panel must say it before the operator commits

Today an operator enables the transport, adds a second friend, and learns at
apply. See also **M15**: the same shape, where a friend-facing transport
permanently blocks a hop and nothing says so until the hop is attempted. These
two are the same class of defect and may share a fix — a transport's constraints
should be visible where it is chosen.

**E2E:** `tests/e2e/control/` — enable a WireGuard-family transport on a node
with two active friends and assert whichever behaviour M17.1 chooses. Note the
existing suite would not have caught this: it needs *two* friends, and one is the
natural number to test with.

**Done when**
- [ ] Either a WireGuard-family transport serves every friend on its node, or it
      is refused before an operator can commit to it, with the reason named.
- [ ] The charter's scale and the transport registry agree about which transports
      can serve a fleet.

acceptance: yes
On a node with two friends, offer a WireGuard-family transport and take both
friends onto it. Either both work, or the refusal arrived early enough that the
operator never believed it would.

---

## → M18 — A node that cannot work says so before it fails · found in the field 2026-09-09

Three first-run experiences found during the field run, all the same shape: the
product knows something the operator does not, and waits until apply to say it.

**Applying a node with nothing enabled gives a YAML parser error.** Register a
node, press the obvious next button:

```
502  the node could not be configured and has been marked degraded:
     command failed (1): 'cd /opt/hashi && docker compose up -d --remove-orphans':
     services must be a mapping
```

and the node is left `degraded`. M4 is working exactly as designed here — that is
the *real* error, surfaced verbatim, where before this run it would have been
`409: a node cannot go from draft to degraded`. The problem is that the situation
is not a failure at all: a node with nothing enabled has nothing to serve, and
the honest answer is *"this node has no transports enabled"* or a no-op — not a
message about mappings, and not a degraded node.

**The panel offers `ssh_user` defaulting to `root` with no hint**, while
`scripts/node-bootstrap.sh` ends by telling the operator to register a different
account. Correct under M13's shape — root always works — but the panel is where
that choice is made and it offers no help.

**A node applied as `root` and later switched to a non-root account keeps
root-owned files.** The script hands over the directory only; whatever an earlier
apply left inside still belongs to `root`. Recorded in `docs/tracker/M13/carry-over.md`
because "re-run the script" looks like it should be sufficient and is not.

### M18.1 — Applying a node with no enabled transports is not an error
### M18.2 — The panel says which account to register, where the account is chosen
### M18.3 — Changing a node's account either carries its files or says it does not

**E2E:** `tests/e2e/control/` — apply a node with nothing enabled and assert the
answer is not a parser error. `make test-control` is the gate.

**Done when**
- [ ] Applying a node with no transports gives an answer an operator can act on,
      and does not degrade the node.
- [ ] The panel's node form does not silently point at an account the bootstrap
      script did not prepare.

acceptance: yes
Register a node and press apply before enabling anything. Whatever happens, it
must be something a first-time operator can act on. Then look at the node form
and ask whether it tells you which account to name.

---

## → M19 — What a node needs that nothing checks · found in the field 2026-09-09

A node has kernel-level prerequisites that neither `scripts/node-bootstrap.sh`
nor `edge/bootstrap/node_stack.py` asserts, because neither can: `/proc/sys` is
read-only inside the data-plane container, and the script's own header declares
it does not tune the kernel. Every one of them was fine on the two field hosts,
so none of this is a regression — it is a set of silent preconditions.

- **`net.ipv4.ip_forward`** must be 1 for any tunnel to carry traffic off the
  node. Nothing sets or checks it; it is 1 today only because dockerd sets it at
  every start. Recorded in `docs/tracker/M14/carry-over.md`.
- **`net.ipv4.conf.all.rp_filter`** must be `0` or `2` on an **entry** node, or
  replies arriving on the hop interface are dropped by the kernel before anything
  sees them. Both field hosts happen to ship `2`. A host shipping `1` would give
  a two-hop that handshakes and carries nothing — M14's shape again, at a layer
  no rule this project renders can reach. Recorded in `docs/tracker/M3/carry-over.md`.
- **A host whose sshd uses `AuthorizedKeysCommand` alone.** `node-bootstrap.sh`
  writes `~/.ssh/authorized_keys` and then verifies its own work *by reading back
  the file it just wrote* — which is true whether or not sshd consults that file.
  The entry host really does take keys from cloud metadata and works only because
  its sshd *also* sets `AuthorizedKeysFile`. On a metadata-only host the script
  would report `ready` with a key that cannot log in. Recorded in
  `docs/tracker/M11/carry-over.md`. **This is a verification that cannot fail**,
  which is the same defect class as M4.6.
- **`ip` is not declared in `DataPlane.executables`** for the WireGuard family,
  although `PostUp`/`PostDown` now run `ip rule` and `ip route`. M2.2's offline
  command check would not catch a future pinned image without `iproute2`.
  Failure mode is loud, not silent, which is why it was left.

### M19.1 — Decide where a node's kernel preconditions are asserted

The script says it does not tune the kernel, and that is a defensible boundary —
but "does not tune" and "does not check" are different promises. Checking and
refusing costs nothing and turns a silent wrong answer into a sentence.

### M19.2 — A verification must be able to fail

The `authorized_keys` read-back is the example. Ask sshd what it will actually
consult (`sshd -T`), or authenticate with the key rather than reading the file.

### M19.3 — Declare `ip`, and re-record the golden image facts

**E2E:** `tests/infra/` for what the script asserts; `tests/edge/` for the
executables declaration. `make test-infra` and `make test-edge` are the gates.

**Done when**
- [ ] A host missing a kernel precondition is told so by name, before it is
      registered as a working node.
- [ ] `node-bootstrap.sh` cannot report `ready` for a key that will not
      authenticate.

acceptance: yes
On a host whose sshd takes keys only from a command, run the script. It must not
say `ready`. If no such host is available, say so rather than passing it.

---

## → M20 — Plain WireGuard cannot exit on a ufw host · measured 2026-09-09

**The owner has already decided not to fix this** (`docs/decisions.md`,
2026-09-09: the image pin stays, the limitation is recorded). This milestone
exists so the work is written down if that decision is ever revisited — it is
**not** queued.

`masipcat/wireguard-go:0.0.20230223` ships `iptables` on the **legacy** backend;
`amneziavpn/amneziawg-go:3.0.3` ships **nft**. Every node this project
bootstraps runs `ufw`, which populates nft with `FORWARD` policy `DROP`. M14's
rules therefore land in a ruleset that cannot front-run it.

**Measured on the live leaf**, with a real client from the friend's own
subscription and an image that ships `ip6tables` so the client could not be the
cause:

| | |
|---|---|
| handshake | completes — 46 seconds old |
| client sent / received | 1.33 KiB / 188 B |
| address echo through the tunnel | **times out** |

Rule placement on that one host at that one moment:

```
nft     -A FORWARD -o amneziawg -j ACCEPT      ← where ufw's DROP lives
legacy  -A FORWARD -o wireguard -j ACCEPT      ← traversed independently
```

So `amneziawg` is proven end to end and `wireguard` is proven broken as a
friend-facing exit. **Note M17 independently makes it unusable for a fleet
anyway**, for a reason that has nothing to do with netfilter.

### M20.1 — Either pin a plain-WireGuard image on the nft backend, or render backend-aware rules, or retire the transport

The third is worth weighing seriously given M17: a transport that serves one
friend and cannot forward is configurable and useful for nothing.

**Done when**
- [ ] A friend on a plain `wireguard` transport reaches the internet on a `ufw`
      host, or the transport no longer offers itself as a friend-facing exit.

acceptance: yes
The same measurement as above, on a ufw host, with the answer changed.

---

## Decisions needed from you

| # | Decision | Blocks |
|---|---|---|
| 1 | Charter amendment: panel leaves the public URL | M7 |
| 2 | Tailscale or Headscale | M7 |
| 3 | Behaviour when a hop is down — fail closed, or exit locally and say so | M3 |
| 4 | Whether to bump `xray-core` from the pinned `1.8.24` (roughly two years behind the ≥ `25.12.8` that 2026 field guidance names as the detection threshold). A data-plane pin bump has a security argument on both sides — new upstream means new defaults and new detectability | — |
| 5 | What to do with `/var/log/ufw.log` on the live host | M6 |
| 6 | What replaces the design's per-user numbers — "throughput now", "last seen", node "load" — and whether the Traffic screen is dropped outright. All four are charter non-goals; the design was drawn without the charter | M8 |
| 7 | Vendor Barlow and Barlow Condensed as woff2 files in the repository (OFL, a few hundred kilobytes), or drop to a system-font fallback and accept that the console is not quite the drawing. The design system's stylesheet fetches them from Google, which the panel must not do | M8 |
| 8 | Whether an audit log exists at all and what it may record, and what a Settings screen may change when the values come from the environment | M10 |
| 9 | The visible word for a person who uses the mesh: the design says "users", the charter and the whole codebase say "friends". Recommended: keep `friend` in the code, decide only the label | M8 |

**Answered by the owner on 2026-09-08**, ahead of the field run:

- **1 — yes.** The panel leaves the public URL; the charter is amended.
- **2 — Tailscale.** Chosen over Headscale with the lock-out risk below understood.
- **3 — fail closed.** No exit at all beats a silent Russian one.
- **5 — off and gone.** `ufw logging off`, and the existing file deleted. Both
  hosts are test hardware and their data is expendable.
- **6 — the proposal below**, as written.
- **7 — vendor the woff2 files.** The panel fetches nothing from a third party.
- **8 — a simple audit log**, and a Settings screen to match.
- **9 — "users".** The panel says users; `friend` stays the word in the models,
  the services, the API and the tests. The label is a template concern and does
  not travel into the code.
- **Still open: 4** (the `xray-core` pin), which blocks nothing.

---

## Where the field run left the plan, 2026-09-09

The plan grew from 11 milestones to 20. **Nine were appended during the run**, and
every one of them came from running the product rather than reading it:

| | how it was found |
|---|---|
| M12 | ran the acceptance driver once — it cannot hold a browser |
| M13 | first apply to a prepared host — the control plane needs root |
| M14 | asked for a page, not a handshake |
| M15 | tried to build the hop — a friend-facing transport locks the node out, permanently |
| M16 | reviewer, minutes after the two-hop worked — the exit is Amsterdam, the DNS is still Russia |
| M17 | added a second friend — a WireGuard transport serves exactly one |
| M18 | pressed apply on a node with nothing enabled |
| M19 | a host whose sshd takes keys from cloud metadata |
| M20 | asked which netfilter ruleset the rules landed in |

Plus **M4.4–M4.6** and **M6.4–M6.6** appended inside existing milestones.

**Every one of them passed `make test`.** That is this plan's own thesis holding
nine more times: *everything checkable by rendering works; everything checkable
only by running does not.*

**M6.6 is the one that explains the rest.** `make test` excludes e2e by design and
CI runs the same three zone targets, so **nothing runs `tests/e2e/` at all** —
which is why `panel-bootstrap.sh`'s own idempotency scenario has been failing for
as long as it has existed. The check was written. Nothing executed it.

**On decision 2, the trade-off worth restating:** Tailscale's coordination is a US
service that may be unreachable from Russia. If it is down exactly when an
emergency rotation is needed, you are locked out of your own panel — the failure
lands precisely on the scenario the panel exists for. **Headscale** (self-hosted
coordination) avoids that.

**On decision 6, what I would propose if you want a default:** keep all four
positions in the layout and fill them with facts the control plane already holds —
nodes online, active friends, hops established and transports enabled for the stat
cards; `added` instead of `last seen` in the friends table; drift against the
applied digest instead of node `load`. Drop the Traffic screen outright and give
its sidebar slot to nothing: a screen that exists to say "we do not measure this"
is an invitation to add the measurement later.

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
