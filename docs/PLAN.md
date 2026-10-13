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

**Update 2026-10-03.** The owner closed M24, M26, M31, M32, M33 and M34 after their real-host walks. The owner has not yet checked any of them from a phone. `develop` holds all of it (PRs #5–#8). **Nothing is open.** The owner dropped **M27** and **M30** and deferred **M35** on 2026-10-03. M16.3's resolver findings are still not dispatched. The 2026-10-02 text below is history.

**As of 2026-10-02. 26 of 31 milestones are closed (✅); five are open — M24, M26, M27,
M30, M31.** Everything before that is in the milestone sections below and in git.

**Where the code is.** `develop` holds M27's steps 27.1–27.7 and 27.9 (PR #4). Nothing
since is merged: `task/M26-fix-round-5` → `task/M31` → `task/M24` → `task/M27.8` are
stacked in that order, each on the one before, and none of them is pushed.

### Built and closed in code on 2026-10-02

- **M26 fix round 5, and the owner's decision on an unreachable host.** Walk 4's two
  blockers — *a port held is not a node serving* and *a condemned node empties every
  link* — are fixed, and **both were confirmed on real hosts on 2026-10-02** (below). The
  owner's rule that came with it: *a health verdict may warn the operator; it may never be
  why a user's link comes back empty* (`docs/decisions.md`, 2026-10-02).
- **M31** — the ten defects the 2026-10-02 field walk and restore walk found. Review clean
  in round 1. The real-host re-walk ran the same day and reported two lows, both fixed on
  `task/M27.8` (M31, *Found in the real-host re-walk*); its verdict on the rest is the
  orchestrator's to record.
- **M24** — the panel hands over the config-file link beside the subscription link (the
  owner's *one URL per config shape*). The owner accepted, the same day, that a config-file
  user re-imports after a key rotation or a replaced node; the charter now says its "never
  re-add anything" holds for subscription-link users. Walked on real hosts the same day:
  the config-file flow worked on the leaf in a container client; no real phone or desktop
  app was tried (M24's done-when).
- **M27.8** — the runbook is one installation procedure; see M27.

Closed before this and unchanged: **M28** (restorable on a machine it never ran on, done
2026-09-26) and **M29** (one word for the person who uses this, done 2026-09-23).

### What the real hosts showed on 2026-10-02

Two test hosts: one in Russia carrying the control plane and the entry, one abroad
carrying the leaf — the co-located arrangement **C+E | L** (the notation of M27.4's
table), which is the arrangement the owner runs, there with several leaves abroad.

- **A fresh install of that arrangement, from `task/M26-fix-round-5`.** `vless-reality` on
  the entry with a decoy of its own, an `amneziawg` hop entry → leaf. A stock xray client
  built from the subscription URL alone, run from a throwaway container: its exit address
  was the leaf's; 8 of 8 DNS lookups crossed the hop interface and none left by the entry's
  uplink; stopping the hop stopped the traffic, with no fallback to the entry's address.
- **M26 on real hosts.** Removing the hop's peer live made the probe report `not_serving`
  with the transport's own explanation. Stopping the entry's xray left the node `active`
  and the subscription still carrying its entry.
- **Backups.** The daily schedule installed and the first offsite upload succeeded.
  Restore from the bucket on a machine that had never run this (a privileged dind
  container), with the CA endpoints and port 22 blocked: one command; the restored
  subscription body was sha256-identical to the live one, and the node, user,
  subscription, credential and node-transport counts were equal. That walk is where M31's
  defects came from.

**Not proven by any of it, or by anything else:** surviving a Russian mobile whitelist
shutdown. That is a field observation on a real Russian network.

### What is open

- **M31 and M24's acceptance** — the real-host re-walk ran on 2026-10-02; its two lows are
  fixed, and closing either milestone is the orchestrator's verdict, not yet recorded here.
  What it was to see: `docs/tracker/M31/carry-over.md`, `docs/tracker/M24/carry-over.md`.
- **M26** — its loop ends with a walk that finds nothing blocking. The 2026-10-02 walk
  found M31's defects, so the M31 re-walk (also 2026-10-02) is the next walk of that loop.
  It reported two lows and nothing blocking that this plan has been told of; whether it
  ends the loop is the orchestrator's verdict. The 14 hand-typed numbers per hop stay
  skipped by the owner.
- **M27** — built and merged except 27.8, which lands on `task/M27.8`. **No real host has
  run the arrangement it exists for** (C+L | E, an entry answering its own users'
  refreshes while the control plane is abroad); its acceptance walk has not happened.
- **M30** — wildcard issuance by the control plane. The owner approved the dependency in
  principle (2026-10-02) and has not chosen a provider. Not needed for C+E | L — see M30.
- **M16.3** — seven resolver acceptance findings, recorded as carry-over
  (`docs/tracker/M16/carry-over.md`), never dispatched.

The lesson that opened this plan still holds:

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

## ✅ M6 — Deployment hygiene · planned 2026-09-08 · done 2026-09-09

> **Closed in the field run, and the first milestone to close under the new
> gate.** Six steps — three planned, three appended during the run. Two review
> rounds: round 1 found a **Critical**, round 2 verified both fixes by
> reproduction and returned CLEAN. `acceptance: no` per the plan.
>
> **Gate at close: `make verify` green** — control 218, edge 230 (3 skipped),
> infra 110, and **130 e2e scenarios in 7m30s**, stand torn down.
>
> **The Critical is worth reading in full** (`docs/tracker/M6/outcome.md`): the
> implementer built `OperatorHashMalformed` *specifically* so a malformed hash
> could never reach a log — and left one input shape that defeated it, putting
> the full credential into the boot-failure message. Every test covered the shape
> they had *seen*. The fix brought a second one unprompted: a well-formed hash
> with an enormous cost parameter boots fine and then 500s on the login route,
> which the control rulebook says a prober must not be able to tell from a wrong
> password.
>
> **M6.5's cause was not in this repository.** BuildKit's provenance attestation
> records build time, so a fully-cached rebuild exports a new manifest digest and
> compose recreates the container. Reproduced independently. Correction to the
> first telling, including mine: the database is **pulled by tag, not built**, so
> it was never recreated and no data was ever at risk — the churn is `control`
> and `caddy`.
>
> **M6.6 — the gate exists now.** `make verify` = `make test` + the stand + all of
> `tests/e2e/` + teardown; a missing Docker engine fails with an explanation
> rather than skipping; CI has a plain job, not an advisory one. `aikit.yml`'s
> `verify_all` points at it. Recorded plainly in the outcome: **the orchestrator
> was itself an instance of this finding**, gating eleven milestones on `make
> test` because that is what the config said.

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

## ✅ M7 — Panel off the public internet · planned 2026-09-08 · reshaped and done 2026-09-09

> **Closed in the field run, and the clearest argument in it for field
> acceptance.** Two review rounds; round 1 returned `0 critical, 0 high` and
> **the field then found a blocking defect no review or test could have caught**.
> Gate at close: `make verify` green — 218 control, 230 edge (3 skipped), 147
> infra, **140 e2e**.
>
> **All three "done when" discharged from Amsterdam** (`docs/tracker/M7/field-proof.md`):
> every console path `404` publicly, the console's port unreachable from outside,
> port 80 redirecting to the **public** host rather than handing out the console's
> address, `/sub/{real token}` still `200` with a real body — and M7.3's fallback
> *walked*, not described: login `303` and a friend created over the SSH forward.
>
> **The defect, because it is the lesson:** a TLS client sends **no SNI for an IP
> literal**, and a WireGuard tunnel hands you an address. With several
> certificates and no name, Caddy aborts — so the console was unreachable by every
> route while nothing was misconfigured. The e2e stack had addressed the console
> by **name**, and names send SNI. The **public** site had the same defect
> already, so `/sub/{token}` was dead for any client dialling an address; nobody
> had asked. Fixed with `default_sni` — see `docs/decisions.md` for the trade a
> *global* option forces — and, more durably, **the test stack's console is now an
> address rather than a name**.
>
> **Limits recorded, not glossed:** ACME was never exercised (the host has no DNS
> record, so `HASHI_PUBLIC_HOST` is its IP and a public CA will not issue for a
> bare IP at all — `/sub/{token}` needs a real name before a friend can use it),
> and no phone on a mobile network was tested, which is the ТСПУ question the
> owner raised and the one thing this fleet cannot answer.

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

## ✅ M8 — The console the owner actually lives in · planned 2026-09-08 · done 2026-09-09

> **Closed in the field run, and the first milestone in this plan judged by an
> independent acceptance agent** — one that never saw the diff and drove the
> console like a person. Gate green: 296 control, 230 edge (3 skipped), 161
> infra, 146 e2e.
>
> **That layer justified itself on its first run.** It found a blocker a full
> code review and an 801-test gate both passed: pressing Back after a sidebar
> navigation returned the console as raw unstyled HTML, reached by the console's
> own primary flow — issue a link, open it, come back. Chasing it surfaced
> something worse: **htmx was writing the whole page body to `localStorage`, and
> after the add-user flow that body holds a live subscription URL.** A bearer
> credential in browser storage. See `docs/decisions.md`, 2026-09-09.
>
> **Four rounds, two of them lost to the orchestrator's own errors** — a commit
> made during a walk, and a stand left un-rebuilt so "judge it empty" was
> impossible. Recorded in `docs/tracker/M8/acceptance.md` rather than buried; the
> round cap was deliberately exceeded on the reasoning that the cap protects
> against a failing product, and this product had not failed.
>
> Final verdict **good**, with all eleven earlier findings confirmed fixed and two
> clumsy ones left for the owner in `acceptance-verdict.md`.

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

## ✅ M9 — The fleet screens, and the old page retires · planned 2026-09-08 · done 2026-09-11

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

### M9.5 — Enable, withdraw and set state, from the Nodes screen · step added 2026-09-10

**Not new scope — an unallocated part of this milestone's own "done when".** That
checklist names *"add node, enable and disable a transport, apply, probe, set
state, establish and tear down a hop, rotate keys, replace params"*, and the four
steps above home every one of those except **enable/withdraw a transport** and
**set node state**: M9.1 carries the node's own lifecycle, M9.3 is read-only by
its own description, M9.4 is keys. So these two actions had no named step while
being required before M9.6 may delete the page that currently carries them.
Found by M9.1's implementer and allocated here rather than silently widening
another step.

M9's acceptance walk — *"register a node, enable a transport on it and apply —
every step from the new screens, with no URL typed by hand"* — cannot be
completed without this.

### M9.6 — Retire `pages/index.html` and `pages/node.html`

**E2E:** none new — the behaviour is unchanged and only the markup moves. The
scenarios that already cover it must stay green against the new screens:
`test_a_replacement_node_and_a_protocol_from_the_panel.py`,
`test_the_panel_never_offers_a_blocked_protocol_as_working.py`,
`test_a_hop_never_reaches_a_friend.py` and
`test_rotation_does_not_move_the_link.py`. `make test-control` is the gate.

**Done when**
- [x] Every action the old pages offered has a home on a new screen: add node,
      enable and disable a transport, apply, probe, set state, establish and tear
      down a hop, rotate keys, replace params.
- [x] Establishing a hop asks three questions; the other 24 parameters are behind
      the disclosure, each showing its own transport's default as a placeholder.
      **Correction, 2026-09-10 — the second clause was written on an assumption
      that was never true, and the line is left in place with this beside it.**
      No shipped transport declares a default for any hop parameter, and none may
      be manufactured in `control`. Checked one field at a time: `port` and the
      two tunnel addresses are barred outright by `CLAUDE.md`'s "never hardcode a
      country, provider, IP, domain or port"; `jc`/`jmin`/`jmax` and `h1`–`h4` are
      exactly the case the "never ship a shared default Reality decoy" rule is
      written about, and the transport says so at the field — a fleet-wide junk
      profile *is* the fingerprint; and `mtu`, the one that looks mechanical, is
      the one the transport most explicitly refuses to default (*"this hop is a
      tunnel inside a tunnel, and the default fragments"*), so a control-side
      value would be `control` overruling `edge` about a protocol. The count is
      also wrong: `design/README.md:98` asks for "12 parameters per end" over an
      11-parameter list, and the twelfth is the only one that declares a default.
      **What the disclosure does instead** is state each field's requirement and
      its own transport's constraints, and say *outside* the closed disclosure how
      many boxes are mandatory — derived from the transport, never written down —
      so an empty box means "this will be refused", not "use the default", and the
      operator learns it before they submit rather than after 22 refusals. The
      reasoning is recorded in `docs/decisions.md`.
- [x] The disclosure says, before it is opened, how many of its parameters this
      transport requires. Derived from the transport; a written number goes stale.
      **Added 2026-09-10 with the correction above** — it is what makes the
      acceptance line below answerable at all.
- [x] No template names a transport, a country, an address or a port.
- [x] No key material appears anywhere in the panel; fingerprints are truncated.
- [x] `pages/index.html` and `pages/node.html` are gone and nothing links to them.

acceptance: yes
On the stand, register a node, enable a transport on it and apply — every step
from the new screens, with no URL typed by hand. Then establish a hop between two
nodes and check the dialog lets you answer three questions and leave the tuning
alone. **Corrected 2026-09-10, same reason as the "done when" above: leaving the
tuning alone does not establish a hop, because no shipped transport declares a
default for any of its hop parameters and `control` may not invent one. What is
being judged instead is that the dialog SAYS SO before you commit — the count of
required boxes is visible while the disclosure is still shut — and that each
refusal arrives under its own box in words an operator can act on.** Open the transports screen: it must name a protocol the panel refuses to
offer as an exit and say why, in words. Then hunt for a private key anywhere in
the console — you must not find one. Applying will fail on the stand, because
there is no real host behind the node; that is expected, and what is being judged
is that the failure arrives on the screen in plain words instead of a blank page
or a raw error. If the failure is the wrong message about a draft node, that is
M4's known bug and not a finding here.

---

## ✅ M10 — The two screens that need records this project does not keep · planned 2026-09-08 · done 2026-09-11

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
- [x] Settings shows the owner what this control plane is actually configured
      with, and names where a value is changed when the panel cannot change it.
- [x] Nothing on Settings claims to save a value the running process would not
      then use.
- [x] Decision 8 is written down in `docs/decisions.md`, whichever way it went.
- [x] If an audit trail exists, it holds no token, no subscription URL and nothing
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

## ✅ M12 — The acceptance hands must actually hold a browser · found in the field 2026-09-08 · done 2026-09-09

> **Closed in the field run.** One review round, CLEAN, two Lows fixed by the
> orchestrator. Gate green — 218 control, 230 edge (3 skipped), 161 infra, 140
> e2e. **The gate did not get slower:** the browser stays behind its compose
> profile, so `make e2e-up` neither builds nor starts it; the ~40s build lands
> only on `stand.sh up`, once per machine.
>
> **Why it mattered now:** M8, M9 and M10 are the only milestones judged on the
> stand rather than on rented hardware, they are the next three, and their
> instrument could not take a single action.
>
> **The privacy claim was verified as structural, not incidental.** `begin` now
> prints the in-container server's own output on failure; the reviewer traced
> `serve()` and confirmed the browser launches and a page is created *before* the
> socket binds, and that `begin` reads that log only in the branch where the
> socket never appeared — so no client has connected and no URL or subscription
> token can exist in it. The instrument check opens `/panel/` and never a `/sub/`
> address, which would put a bearer token in a screenshot name.
>
> **Two things found on the way:** `drive.py` was committed `0644` while both its
> siblings were `0755`, so the documented command died on `Permission denied`; and
> `e2e-down`'s target-specific variable could be silently overridden from the
> command line, a latent way to defeat M12.4 itself. Fixed with `override`, and
> the test **tightened to require it**, proven red-first. See
> `docs/tracker/M12/outcome.md`.

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

## ✅ M15 — A transport enabled for friends locks that node out of a hop, permanently · found in the field 2026-09-09 · done 2026-09-11

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
- [x] Either a node can host a friend-facing and a hop end of the same transport,
      or it is refused at the moment the *first* one is created, with the
      consequence named.
- [x] A node transport can be removed, not merely disabled.
- [x] The runbook's Shape A advice and its hop requirement do not contradict each
      other.

acceptance: yes
On a fleet where a node already offers a transport to friends, try to make that
node the entry end of a hop over the same transport. Whatever the answer is, it
must arrive with a reason an operator can act on — and if the answer is no, it
must have been said earlier, when the friend-facing transport was enabled.

---

## ✅ M16 — The exit is Amsterdam, the DNS lookup is still Russia · found in review 2026-09-09 · done 2026-09-12 (acceptance: partial — needs the field)

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

## ✅ M17 — A WireGuard-family transport can serve exactly one friend · found in the field 2026-09-09 · done 2026-09-13 (acceptance: partial — 3 items need the field)

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

### M17.1 — Decided by the owner, 2026-09-11: WireGuard-family transports stay friend-facing, and each user gets a tunnel address of their own

The plan's M17.1 asked whether a WireGuard-family transport is friend-facing at all. The owner has answered, choosing the first option: yes. The tunnel address becomes per-credential state. It is minted with the credential, released on revocation, and drawn from a pool the operator sizes on the node-transport record. It is never a hardcoded range. The refusal (`AmbiguousPeerRoute`) is not weakened.

Carrying out that answer is most of this milestone, and it spans two zones. `CLAUDE.md` keeps cross-zone work in separate diffs, so M17.1 is split into three steps, divided by zone and by what each can prove on its own:
- **M17.1a** — `edge`.
- **M17.1b** — `control`.
- **M17.1c** — `control`.

M17.2 keeps the plan's wording and its meaning, the one the owner named: *"the panel shows how much of the pool is used before I commit."* There is no release between steps. The milestone deploys as a whole.

### M17.1a — edge: a transport declares that each user needs their own address, and edge does the address arithmetic

This is a sixth recorded widening of `edge/registry.py`: `TransportMeta.peer_address: PeerAddress(name, within) | None = None`.
- `name` is the key the renderers already read a consumer's own address from (`secrets.get(name) or params[name]`). In `params` it is also the pool's first address.
- `within` is the field whose network bounds the pool.
- Both WireGuard-family packages declare `PeerAddress("peer_tunnel_address", "tunnel_address")`.

A new pure module, `edge/addressing.py`, sits beside `egress.py`. It is a second argued shared exception, because the arithmetic is protocol-agnostic and the overlap rule is inherently cross-transport. It holds:
- `pool_problem(first, within, size)`: a sentence or `None`, in `resolver_problem`'s shape;
- a lazy enumeration of the pool, with pool[0] written byte-identical to the renderers' fallback;
- `host_of`;
- `networks_overlap`.

The two packages also refuse a `client_dns` address inside the tunnel's own network. With a pool, that address would be another user's device, and every user's lookups would go to them.

No renderer, template or golden file changes. The pool size is **not** a `Params` field, so the establish-hop dialog, stored hop parameters and hop renders are untouched.

### M17.1b — control: every user on a WireGuard-family transport holds their own address, and a pool too small is refused before anything commits

- **Schema.**
  - `node_transports.pool_size` (nullable, ≥1).
  - On `credentials`: an encrypted `tunnel_address`, and a keyed digest over (row, canonical host) under a new HKDF label, unique per row.
  - Migration `0006`: no backfill, with a downgrade that refuses once pools are in use.
- **Allocation.**
  - One allocator (`services/addresses.py`) gives each new credential the lowest free pool address, in `(created_at, id)` order.
  - One projection feeds both the node's config and the user's file, so `AllowedIPs` and `Address =` cannot diverge.
  - A transport enabled before this milestone gives out exactly its one typed address, byte-identical.
- **Sizing and refusals.**
  - The size is asked for at enable, from the API and the panel.
  - Every path that grants now grants inside the transaction it commits in: add user, enable, offer, and a node becoming serving.
  - A pool too small is therefore refused with nothing written. Before this step, four of the five paths committed first and granted afterwards.
  - No lock is taken. The unique constraint turns a race into a clean refusal, never a shared address.
- **The pinned test is inverted.** `test_second_subscription_format.py`'s two-user refusal becomes two users rendering at two addresses.

### M17.1c — control: nothing moves an address a device holds, and two interfaces on one node never share a network

- **Resizing.**
  - Resizing is part of replacing parameters: `replace_params` gains a pool size, audited as `params-replaced`, with no new action and no new endpoint.
  - Before anything changes, every user still without a stored address is pinned to the address their device already uses, then the new pool is checked against every held address.
    - **Corrected 2026-09-13, beside itself rather than rewritten.** "Every" cannot hold: a pre-pool row has **one** fallback address, so every address-less credential on it renders **the same** one and only one can hold it. What ships: **one** credential is pinned — the earliest by `(created_at, id)`, which is `settle`'s own adoption rule — and the rest are given addresses from the new pool. The done-when below is unaffected: no working device's address moves, because only one device was ever actually using that address. See `docs/decisions.md`.
    - "Checked against every held address" means **can this tunnel still carry it**, not *is it inside the new run*. An address outside the run is still routed and is never re-handed out, so the stricter reading would refuse a change that strands nobody.
  - This is how a row enabled before pools gets sized, and how the field's two-user row is repaired without touching the working device.
- **Overlapping networks.**
  - Placement also refuses a tunnel network that overlaps another WireGuard-family row on the same node, hop ends and withdrawn rows included.
  - It is checked on enable, on establishing a hop, and on replacing parameters.
  - The data planes share the host's routing table, so a reply to one interface's user could otherwise reach whoever holds the same address on the other. That is a cross-person hijack no single-file check can see.

### M17.2 — Whatever is chosen, the panel must say it before the operator commits

Before the operator commits:
- **Keys & configs** reads `<holders> of <pool>`.
- **The enable dialog** says how many active users will each take an address.
- **The add-user dialog** names every full pool and offers no submit button.
- **Offer and set-active** are withheld on a node whose pool is short, with the pool named.
- **The Transports screen** says, from the registry's own declaration, which transports give each user an address from a pool sized per node.

No user's address appears anywhere. The runbook stops saying "one friend per node", backlog 33 closes, and the field checklist gains M17's section.

**E2E:** Existing scenarios, updated in M17.1b so the warm shared stand stays green, each give their pool far above any active-user count:
- `tests/e2e/control/test_the_runbook_shape_a_then_the_hop_it_mandates.py`
- `test_a_hop_never_reaches_a_friend.py`
- `test_the_same_token_serves_two_shapes.py`

M17.2 adds `tests/e2e/control/test_a_wireguard_family_transport_serves_every_user.py`:
- two users on one transport, at two addresses;
- a pool smaller than the active users refused under its box;
- a full pool refusing the next user before anything is written, then a resize letting them in (the row is removed in `finally`);
- rotation keeping every address;
- revocation freeing one;
- the hop dialog unchanged.

The stand has no data plane. "Both work" as traffic is a field observation on `amneziawg` on a node with no hop, recorded in `docs/tracker/field-checklist.md`. `make verify` is the gate.

**Done when**
- [ ] Either a WireGuard-family transport serves every friend on its node, or it
      is refused before an operator can commit to it, with the reason named.
- [ ] The charter's scale and the transport registry agree about which transports
      can serve a fleet.
- [ ] Two and three users on one friend-facing `amneziawg` row, and on one `wireguard` row, render with distinct `/32` `AllowedIPs`. Each user's file names the host the node authorises for that user.
- [ ] A row enabled before M17 with one user renders byte-identical after the upgrade. No working device's address ever moves: not by rotation, revocation, resize or a replaced parameter.
- [ ] Enable, add user, offer, set active and replace each refuse a pool that cannot hold every active user before anything commits. Each refusal names the node and the transport.
- [ ] Two WireGuard-family rows on one node cannot share a tunnel network. `AmbiguousPeerRoute` is still tested directly in `edge`, for both packages.
- [ ] Hop ends are unchanged: no address, no pool, the same dialog boxes, byte-identical renders.

acceptance: yes
On a node with two friends, offer a WireGuard-family transport and take both
friends onto it. Either both work, or the refusal arrived early enough that the
operator never believed it would.

---

## ✅ M18 — A node that cannot work says so before it fails · found in the field 2026-09-09 · done 2026-09-13 (acceptance: partial — one finding referred to the owner as M22)

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

## ✅ M19 — What a node needs that nothing checks · found in the field 2026-09-09 · done 2026-09-13 (acceptance: good)

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

## ✅ M20 — Plain WireGuard cannot exit on a ufw host · measured 2026-09-09 · reopened by the owner 2026-09-13 · done 2026-09-14 (acceptance: good, 2 rounds)

**The owner reopened this on 2026-09-13 and chose the third option: retire the
transport from the panel.** The earlier decision (`docs/decisions.md`,
2026-09-09) was to keep the image pin and record the limitation, taken when the
failure was a packaging *inference*. It has since been **measured twice on the
live leaf** — once during the field run, and again on 2026-09-13 while designing
M23 — so it stopped being a prediction.

**What the owner asked for, in their own words (2026-09-13):**

> *"just stop suggest the wireguard for users now"* … *"the admin panel do not
> even should show this protocol, for me in suggestions"*

So the requirement is **stronger than "not granted to friends"**: the operator
must not be **offered** it when choosing a transport to enable. It should not
appear in the suggestions on the enable dialog, nor anywhere the panel proposes
a transport to add.

**What must NOT change, and why each matters:**

- **The package stays in the tree.** It is the second member of the
  WireGuard family, and having two is what proves the charter's rule that
  *transports are data — no `if transport ==`*. `AmbiguousPeerRoute` is tested
  over both packages, and the contract tests iterate all four. Deleting it would
  silently turn those into single-case tests and lose the guard against a
  hardcoded protocol name. **The code is correct; the defect is one pinned
  image.**
- **The management tunnel is untouched.** `scripts/management-tunnel.sh` is
  separate code, already uses the **obfuscated** wire format rather than plain
  WireGuard (decided 2026-09-09, because *"this is the one tunnel that has to
  work when everything else is being blocked"*), and has **no forwarding and no
  NAT** — it carries traffic *to* the host, not *through* it — so this
  milestone's failure mode structurally cannot reach it. The owner's admin
  access is not affected by anything here.
- **A row already enabled on a node keeps rendering.** Retiring it from the
  suggestions must not break an existing row or an existing friend's config —
  the leaf has one such row today. What stops is *offering it anew*.

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

### M20.1 — Retire it from the panel's suggestions, by declaration and not by name

**The owner chose the third option on 2026-09-13.** The first two — pinning an
nft-backend image, or rendering backend-aware rules — remain written down above
if the decision is ever revisited again.

The transport must **declare** that it is not offered, and the panel must read
that declaration. **No `if transport == "wireguard"` anywhere** — that is the
charter's hard rule, and the whole point of the registry. A future transport
found to be unusable should be retired by setting the same field, with no panel
change at all.

The declaration needs a reason attached, because a reader who finds a package in
the tree that the panel never offers deserves to know why without going to
`git log`.

**Done when**
- [ ] Plain `wireguard` **does not appear in the panel's suggestions** when the
      operator chooses a transport to enable, anywhere it could be proposed.
- [ ] It is retired **by a declaration the registry carries**, not by a name
      compared in the panel.
- [ ] A `wireguard` row **already enabled on a node still renders** and an
      existing friend's config is unchanged.
- [ ] `AmbiguousPeerRoute` and the transport-contract tests **still run over both
      WireGuard-family packages** — retiring it must not quietly reduce them to
      one case.
- [ ] `scripts/management-tunnel.sh` is untouched and still works.

acceptance: yes
Open the panel as the operator and go to enable a transport on a node. Plain
WireGuard must not be among the choices. Then confirm the node that already has
a `wireguard` row still renders it, and that nothing about the management tunnel
changed.

---

## ✅ M25 — Prove route A carries: friend → entry → hop → leaf → internet · asked for by the owner 2026-09-16 · done 2026-09-16 (acceptance: good — 2 walks, route A carries)

**Approved by the owner on 2026-09-16.** M23 proved **route B** — a friend dialling
a leaf directly — on real hardware, nine times. **Route A, the charter's actual
design, has never been observed carrying a packet end to end.**

### The two routes, and why only one is proven

`control` picks the policy from one table (`nodes._EGRESS`):

| row | node has a hop? | policy |
|---|---|---|
| friend-facing | **no** | `Egress.LOCAL` — exit out of this node's own route |
| friend-facing | **yes** | `Egress.HOP` — exit through the hop, **never** locally |

So the same transport renders differently depending on the node it sits on.

**Route B (proven, nine walks):** friend → leaf → internet, exit `45.151.69.107`,
25 MB each way, two friends concurrently.

**Route A (unproven):** friend → **entry** → hop → **leaf** → internet. The
charter's whole point: a friend inside Russia reaches a *Russian* address when
foreign ones are blocked, and the hop out is obfuscated.

**What is known about route A today:** the owner's live hop carries real traffic —
its counters moved at every one of M23's nine walks. **What is not known: whether
a friend's traffic actually traverses it**, because the Russian entry refuses this
machine's key and no friend-facing transport has ever been applied to it.

### Why this is testable without the entry

**Build the shape, not the host.** A throwaway "entry" with a friend-facing row
(`Egress.HOP`) and a hop of its own, whose far end is a **second, throwaway** hop
interface on the leaf (its own port, its own network — the live hop's `/30` holds
two addresses and both are taken). A friend container dials the throwaway entry.

That exercises every part of route A that is the product's: the source-routing an
entry renders, a real obfuscated hop over the real internet, and `Egress.RELAY` at
the far end. **What it does not exercise is the real Russian host's own
conditions** — its `rp_filter`, its provider's filtering, and whether a friend in
Russia can reach it at all. Those stay field observations.

### M25.1 — A friend behind an entry reaches the internet at the leaf's address

The measurement that settles route A. From inside the friend's tunnel, the
address the outside world sees must be **the leaf's**, and the packets must have
crossed the hop to get there.

### M25.2 — An entry must never exit on its own route

**The charter's core claim, and the one that hurts if it is wrong.** `Egress.HOP`
exists so that a friend's traffic leaves through the hop *and nowhere else*. If an
entry leaks locally, **a friend's traffic surfaces in Russia** — the exact
outcome the fleet exists to prevent, arrived at silently.

Prove it two ways: the exit address is the leaf's and never the entry's, **and**
the entry's own rules carry no route to the internet for that tunnel.

### M25.3 — The hop's far end treats entry traffic as an entry's, not a friend's

M23's ninth walk closed a hole by making a friend reach **only** the internet
(`NOT_THE_INTERNET` refused). `Egress.RELAY` is a separate value precisely so that
what arrives over a hop is **not** narrowed the same way — an entry's own lookups
go through it. **Confirm the hop still carries what it is meant to** and that the
distinction is real rather than asserted.

**Done when**
- [ ] A friend behind an entry reaches the internet, and the exit address is the
      **leaf's**.
- [ ] The traffic provably crossed the hop — the hop's own counters move for it.
- [ ] An entry **never** exits on its own route, shown by address and by rule.
- [ ] The far end of a hop still carries what a hop is for, unnarrowed.
- [ ] Nothing on either live host is changed, and the owner's hop is untouched.

acceptance: yes
Stand a friend behind an entry that dials a hop. They reach the internet, they
come out at the leaf, and nothing they send leaves by the entry's own route.

**Not in scope, by the owner's instruction (2026-09-16):** DNS. M16's resolver
question and the entry's own lookups are the owner's hosting concern and are not
this milestone's subject.

---

## ✅ M26 — "Everything is deployed by one script" is not what ships · asked for by the owner 2026-09-16 · PARTIAL — the question is answered and the charter narrowed to the measured counts (4 walks, 3 fix rounds landed); fix round 5 (2026-10-02) fixed walk 4's two blockers — the serving check and the empty link — and both were confirmed on real hosts on 2026-10-02; the loop's next walk is M31's re-walk, see "Where things stand" · **CLOSED by the owner 2026-10-03** — the real-host walk passed; the owner's own phone check was not done before closing

**Approved by the owner on 2026-09-16**, who asked whether a leaf and an entry
can be deployed by one command, and — being told the answer was probably no —
asked for a milestone that **tests it by acceptance and loops until it is ready**.

### The gap, as far as it is known before the walk

`docs/product/charter.md` (owner's requirement, 2026-08-02) says:

| script | charter says it brings up |
|---|---|
| node bootstrap | one leaf or one entry node, **from a bare host to serving traffic** |
| panel bootstrap | the control plane, its database and the delivery endpoint |

and that "one script" must mean, among other things:

> **Verifies before reporting success.** It ends by checking the daemon accepts
> its own config and **the node answers a health probe** — a script that reports
> success on a host that is not serving is worse than one that fails.

**What `scripts/node-bootstrap.sh` actually does** is prepare a host — docker, the
control plane's key, the firewall, and since M19 the kernel preconditions and a
real `sshd -T` check. **It ends by telling the operator to register the node**:

```
==> ready: docker <v>, key authorised, firewall up, logging off
==> register it in the panel with ssh_user root and ssh_port 22
```

**The script is honest. The charter overstates it.** A bare host reaches *serving
traffic* only after: run the script → register the node → offer it a transport →
apply. One command and three panel actions. **For an entry→leaf hop, twice that,
plus establishing the hop.**

**And the script's verification is not the one the charter names:** it checks
docker answers, the key is one sshd will consult, and the kernel will forward. It
does **not** check that the node answers a health probe, because at that point
nothing has been pushed to it and there is nothing to probe.

### What this milestone must settle, before it writes code

**Which end moves — SETTLED BY THE OWNER, 2026-09-16.** In their words:

> *"if the scheme is that I run only one script on the leaf and then add its
> output to the panel it's also okay."*

**So the charter narrows to what is true, and the scripts do not change.** One
script **per host**, which ends by printing what the operator types into the
panel; registering, offering a transport and applying stay panel actions.

**The rejected alternative, and why** — so it is not re-proposed: making the
script register and apply the node itself would need it to hold a control-plane
credential and dial the panel's API. **Today the control plane dials nodes and a
node never dials the control plane** (`CLAUDE.md`'s topology rule). Such a script
would put a control-plane credential on every host the fleet has ever prepared,
and be a **second path that can bring a node into existence**. Rejected on that,
not on effort.

**What the narrowing costs, stated rather than hidden:** a node is one command
**and three panel actions**; an entry→leaf hop is twice that plus establishing
the hop. Criterion 2's *"replace a node in ten minutes"* still holds — it is just
not one command.

**M26.1 — walk it and find out what is actually required.** Take a bare host and
follow only what the product tells you. Count the commands, count the screens,
and record where the script's promise and the charter's claim diverge. **Do not
assume the gap is where it looks — the runbook's Shape A/B/C flows may already
close some of it.**

**M26.2 — make the charter tell the truth.** `docs/product/charter.md`'s *"from a
bare host to serving traffic"* and its *"the node answers a health probe"* promise
must say what the script actually delivers — and `docs/deploy/runbook.md` must
describe what an operator actually does, end to end, including the hop.

**The script's own closing lines are the seam** (`ready: …` and `register it in
the panel with ssh_user …`). They are quoted in the runbook and pinned by
`tests/infra/test_deploy_runbook.py`, so the page and the script cannot drift —
**keep that property.**

**M26.3 — the charter's other three "one script" promises, tested not assumed.**
*Idempotent* (running it twice changes nothing the second time — M19's acceptance
proved this for the node script; the panel script is unproven), *no interactive
questions*, and *verifies before reporting success*.

**Done when**
- [ ] What it takes to go from a bare host to a node serving traffic is written
      down accurately, and an operator following it gets there.
- [ ] The charter and the scripts agree about what "one script" delivers.
- [ ] Both scripts are proven idempotent, non-interactive, and honest about
      success — by running them, not by reading them.
- [ ] The hop case is covered: what it takes to go from two bare hosts to a
      working entry→leaf hop.

acceptance: yes
Take a bare host. Using only what the product tells you, get it to the point
where a user's traffic flows through it. Count what you had to do, and say
whether the charter's sentence is true.

**How this milestone runs, by the owner's instruction (2026-09-16):** tested by an
independent acceptance walk, and **fixed in a loop — walk, record every finding,
fix them all, walk again — until a walk comes back with nothing blocking**, the
way M23 was run.

**Fix round 5 — 2026-10-02, asked for by the owner.** Walk 4's blockers, high, medium and
the Users-screen low, closed in code on `task/M26-fix-round-5` (not pushed); the "14
hand-typed numbers per hop" low was skipped by the owner. Record:
`docs/tracker/M26/fix-round-5.md`. The owner's decision that came with it — a serving host
an apply could not reach at all stays in users' links — is the 2026-10-02 row in
`docs/decisions.md` that opens with those words.

**Confirmed on real hosts, 2026-10-02**, on a fresh install of the co-located arrangement
(control plane and entry on one box in Russia, the leaf abroad) from
`task/M26-fix-round-5`: removing the hop's peer live made the probe report `not_serving`
with the transport's own explanation — blocker 1, the check now asks the transport rather
than the port; and stopping the entry's xray left the node `active` and the subscription
still carrying its entry — blocker 2, a verdict no longer empties a link. That walk also
found the ten defects that became M31, so it did not come back with nothing blocking; **the
M31 re-walk, the same day, is the next walk of this loop** — it reported two lows, fixed
(M31), and whether it closes the loop is the orchestrator's verdict.

---

## ✅ M29 — One word for the person who uses this, and the product already picked a different one than the code did · asked for by the owner 2026-09-22 · done 2026-09-23 (acceptance: stand walk good on everything a stand can reach; 2 checklist lines it cannot observe were lifted by the owner 2026-09-23; the real-host walk passed and found 2 runbook defects, fixed in M29.9)

**Done.** Thirteen steps, 37 commits, every step converged clean under an
independent reviewer. `make verify` green.

### The premise is better than "the owner prefers a different word"

The owner asked to stop calling them *friends* and call them *users*. Measured
before planning, that turns out not to be a preference at all:

| surface | says |
|---|---|
| `control/app/templates/panel/keys_table.html:46` | `<th>users on it</th>` |
| eight panel templates, **including `friends_table.html` itself** | `users` |
| `control/migrations/versions/0006_an_address_per_user.py` | `user` |
| the model, the table, the routes, the file names | `friend` |

**The screens already say one thing and the code says another**, and the screen is
the half the operator reads. So this is not a rename of a settled term — it is
finishing a change the product has already half-made, in the direction it already
went.

Footprint, measured: **~3650 occurrences across 239 files** — `control` 871,
`tests` 1767, `docs` 682, `edge` 306, the rest small.

### What is actually load-bearing, and what is only prose

Most of that count is comments and docstrings. The identifiers are few and known:

- **`control`** — `Friend` (`models/friend.py:25`), `FriendCreate` / `FriendResponse`
  (`api/schemas.py:183,189`), `FriendRow` (`services/console.py:370`), the
  `friends` table, `friend_id` columns, `/api/friends/*` and `/panel/friends/*`,
  and the template file names.
- **`edge`** — almost clean. Its public types are `NodeView` and `Credential`,
  neither of which is named for a person. Only `registry.py:718
  serves_friends_through_a_hop` is a public name; `egress.py:468 _friend_rules` is
  private. Everything else in edge's 306 is prose.

**That asymmetry is the plan: `edge`'s change is one method and a read-through of
its comments; `control`'s is a migration.**

### Settled by the owner, 2026-09-22

Three of this milestone's open questions were put to the owner before any work
started, and answered. They are facts below rather than questions, and they are
recorded in `docs/decisions.md` rather than re-argued inside a diff:

- **The word is `user`** — everywhere a person can read it, **including the
  charter's own sentence**, which becomes *"for the owner and ~30–50 users"*.
  The owner accepts knowingly that this leaves **three** meanings of `user` in one
  codebase: the person who uses the product, a node's `ssh_user`, and
  `HASHI_OPERATOR_USERNAME` (plus `--user` in `scripts/node-bootstrap.sh`). The
  collision was put in front of them with `subscriber` as the alternative that has
  none of it; they chose `user`. What `friends` was carrying — no public signup,
  no billing, no advertising — stays the charter's business, stated there as
  non-goals rather than implied by a noun.
- **The API breaks cleanly.** `/api/friends/*` and `/panel/friends/*` become
  `/api/users/*` and `/panel/users/*`, with **no aliases and no deprecation
  window**. Anything scripted against the old paths stops working the day this
  lands, and the runbook says so in those words.
- **It is three tasks, not one** (decision 7 above), so the steps below are
  ordered `edge` → `control` → the documents, each gated on its own
  `make test-<zone>` with `make verify` across the seam. Nothing here lands as a
  single cross-zone diff.

### M29.1 — Draw the line between record and living document, and write the decisions down

Before a single occurrence changes, decide in writing which files may be reworded
and which may not, because the naive `sed -i` over `docs/` crosses that line and
cannot be un-crossed by a second `sed`.

**Records, never touched:** `docs/tracker/**`, `docs/decisions.md`'s existing
entries, and every completed (`✅`) milestone in this file. They say what happened
and what was said at the time; changing the words in a record falsifies it.

**Living documents, which move:** the charter, `docs/deploy/runbook.md`,
`CLAUDE.md`, `README.md`, and this plan's *open* milestones.

The step ends with new entries appended to `docs/decisions.md` recording the word,
the accepted three-way collision, and the clean API break — appended, never
rewriting what is already there.

### M29.2 — `edge`: the one public name, and a read-through of its prose

`edge` is almost clean and that asymmetry is why it goes first — it is the
cheapest half and it proves the vocabulary before `control` commits a migration to
it. Its public surface is `NodeView` and `Credential`, neither named for a person.
The work is `registry.py:718 serves_friends_through_a_hop`, the private
`egress.py:468 _friend_rules`, and reading through the remaining prose of edge's
306 occurrences. No I/O, no schema, nothing that can break a device.

Gate: `make test-edge`.

### M29.2b — `edge`'s own e2e scenarios speak the same vocabulary · added mid-run 2026-09-22, see below

**Not in the original seven steps, and it should have been.** `CLAUDE.md`'s zone
table puts `tests/e2e/edge/**` in the `edge` zone, but M29.2's work was fenced to
`edge/**` and `tests/edge/**`, and M29.7's E2E note named only
`tests/e2e/control/`. So nothing claimed this directory — while the milestone's
own "Done when" says *no identifier … in `control` or `edge` still carries the old
one*. **The checklist the owner approved could not be satisfied by the steps the
decomposition wrote.** This step exists to close that, and it is the same work in
the same zone, not new scope.

Measured: **94 occurrences**, independently counted twice. A file name —
`test_a_friend_exits_at_the_leaf_and_not_at_the_entry.py` — and four identifiers:
`NO_FRIEND_HERE`, `FRIEND_TRANSPORTS`, `FRIEND_PORT`, `FRIEND_ATTEMPTS`.

Two things travel with it. `tests/edge/test_a_tunnel_carries_traffic_off_the_node.py:583`
cites that file by path and must move in the same commit, or it names a file that
no longer exists. And the scenario at `tests/e2e/edge/…:158` holds a stale prose
reference to a `tests/edge/` file M29.2 already renamed — a string in an assertion
message, so nothing is red today, which is exactly why it would otherwise be missed.

Gate: `make test-edge`. The e2e half of this zone cannot be green until M29.4
migrates `control`'s callers — see `docs/tracker/M29/step-notes.md`, item 2, for
how red the tree is between M29.2 and M29.4 and why a green-looking summary before
M29.4 means nothing.

### M29.3 — `control`: the table, the columns and a migration that goes both ways

`friends` → `users`, every `friend_id` column, and the foreign keys, indexes and
constraints that name them, together with the SQLAlchemy model (`models/friend.py:25`
`Friend`) that must match the table it maps. **Reversible is the requirement, not a
nicety**: there is no way to delete a node record in this product today, and this
milestone must not add a second irreversible act to it.

Gate: `make test-control`.

### M29.3b — `infra`: the scenario that counts rows in a table that no longer exists · added mid-run 2026-09-22

`tests/e2e/infra/test_restore_proves_the_backup.py:389` asserts
`rows_in(project, path, "friends") == 1`. M29.3 renamed that table, so the
scenario is broken — confirmed by the reviewer, not merely predicted.

It is one word. It gets its own step because it is the **`infra`** zone and M29.3
is `control`: `CLAUDE.md` says cross-zone work stays in separate tasks and never in
one diff, so the step that broke it was right not to reach over and fix it. That
rule is the reason this exists, and it is worth one step rather than one exception.

Whether the scenario should assert on a table name at all — rather than on what the
restore actually restored — is a fair question, but it is not this milestone's.
Change the word, keep the scenario's shape.

Gate: `make test-infra`. It is red for a second, unrelated reason until M29.7
(the runbook quotes an `edge` string M29.2 reworded), so read which test fails.

### M29.4 — `control`: the API and the panel, broken cleanly

`FriendCreate` / `FriendResponse` (`api/schemas.py:183,189`), `FriendRow`
(`services/console.py:370`), the routes, and the template file names —
`friends_table.html` included, the file whose own contents already say `users`.
`/api/users/*` and `/panel/users/*`, no aliases, per the decision above.

The eight panel templates that already say `users` stop being a lie about the code
underneath them at this step, which is the whole premise of the milestone.

Gate: `make test-control`.

### M29.4a — `infra`: the restore scenario calls the routes that now exist · added mid-run 2026-09-22

M29.4 breaks `/api/friends/*` cleanly, with no aliases — the owner's decision. Five
call sites in `tests/e2e/infra/test_restore_proves_the_backup.py` still post to the
old path, and M29.3b deliberately left them because `control` was still serving
them at the time.

The moment M29.4 lands they are calls to a route that returns 404, and **no static
target will notice**: `make test-infra` runs `pytest tests/infra`, which does not
reach `tests/e2e/infra/`. The scenario has to be run.

**Widened 2026-09-22, measured during M29.4: it is ten call sites, not five.**
`scripts/security/seed.py` has five more — lines 157, 160, 166, 173, 188, plus
`friend_id` locals. `scripts/**` is the `infra` zone too, nothing static runs it
either, and it 404s from `e02fbe5` onward. It seeds the identities the security
audit's hunter attacks, so a broken seed does not fail loudly — it produces an audit
that finds nothing and looks like good news.

Its own step for the same reason M29.3b had one: this is the `infra` zone and M29.4
is `control`, and `CLAUDE.md` does not allow the two in one diff. That is twice now
that a `control` change has landed work in `infra`, which is worth noticing rather
than working around — the zone split is doing exactly what it exists to do.

Gate: run the scenario, `pytest tests/e2e/infra/test_restore_proves_the_backup.py`.
`make test-infra` is not evidence here and cannot be.

### M29.4b — `control`: the transport purpose a person reads is still the old word · added mid-run 2026-09-22

`TransportPurpose.FRIENDS = "friends"` (`control/app/models/node.py:114,134`) is a
persisted column **value**, not a name — the Python default and `server_default` for
`node_transports.purpose`. M29.3 could not take it: a rename there is a **data**
migration touching every existing row, and `0008` is renames-only on purpose.

It is in scope because of the milestone's first "Done when": *one word for the
concept everywhere a person can read it — screens, API, code*. This value is
returned by the API and shown in the panel, so a person reads it. Leaving it means
closing M29 against a checklist it does not meet, which is the same error M29.2b
was added to correct.

**Widened 2026-09-22, found during M29.4: there are TWO of these, not one.**
`AuditAction.FRIEND_ADDED = "friend-added"` and `FRIEND_REVOKED = "friend-revoked"`
(`control/app/models/audit.py:59-60`) are stored in `audit_entries.action`,
`VARCHAR(32)` since migration `0003`, and read back through `EnumText`. Same shape,
same data-migration requirement — and **an operator reads these on the audit
screen**, which is the argument for taking them. Both enums move in this step or
neither does; splitting them leaves the milestone half-closed against the same
Done-when twice.

Two things to get right:

- **The identifier and the value both move**, for both enums —
  `TransportPurpose.FRIENDS` → `USERS` with `"friends"` → `"users"`, and
  `AuditAction.FRIEND_ADDED` / `FRIEND_REVOKED` → `USER_ADDED` / `USER_REVOKED` with
  `"friend-added"` / `"friend-revoked"` → `"user-added"` / `"user-revoked"` — and
  every comparison against them.
- **It is a data migration and therefore reversible in both directions**, on top of
  `0008`. `UPDATE … SET purpose='users' WHERE purpose='friends'` going forward and
  the exact inverse coming back, with the enum's own type updated if Postgres holds
  it as one. M29's plan text is explicit that this milestone must not add a second
  irreversible act to a product that cannot delete a node record.

**This is the one step in M29 that writes to rows rather than renaming names.** It
carries the risk the rest of the milestone deliberately does not, which is why it
is a step of its own and why M29.5 rehearses it against a copy of real data along
with `0008`.

Gate: `make test-control`, with a real database — a green run whose ~670
database-backed tests were skipped proves nothing about a data migration.

### M29.4c — `infra`: the scripts, and the test that reaches into `control` by AST · added mid-run 2026-09-22

Two things `scripts/**` and `tests/infra/**` are owed, found by M29.4a and confirmed
by its reviewer. Both are the `infra` zone, which is why neither could ride along
with the `control` step that caused them.

**1. A test that reaches into `control` by AST, which no grep would find.**
`tests/infra/test_deploy_runbook.py:1107` walks the AST of `relay.establish_hop`
looking for calls to `nodes.friend_facing_on`. M29.4 renamed that to
`user_facing_on`, so the set comes back empty and
`test_the_growth_path_sends_the_box_that_already_serves_friends_to_the_leaf_end`
fails — loudly, which is the only good thing about it. **A symbol a test reaches by
`ast` or `inspect` is invisible to a grep for its call site.** The test's own name
and docstring move with the string.

**2. `scripts/**` prose, which no step owned.** M29.7 is `docs/` only, so as
decomposed this milestone would close with `backup.sh`, `panel-bootstrap.sh`,
`node-bootstrap.sh`, `acceptance/query.py`, `acceptance/stand.sh`,
`security/stand.sh` and `security/role.sh` still saying the old word — against a
"Done when" that says *one word for the concept everywhere a person can read it —
screens, API, **code***. A script an operator runs during an emergency is code they
read.

**The security stand's names are a cross-file contract and move together or not at
all.** `scripts/security/seed.py` deliberately left its `FRIENDS` constant, the role
keys `friend_a` / `friend_b` / `friend_revoked`, the nicknames `audit-friend-*` and
the `roles.json` key `friend_id`, because `role.sh` and `stand.sh` read them by those
names and `aikit.yml`'s `security.roles` block names the roles too. This step takes
all of it in one diff, `aikit.yml` included, or leaves all of it — **a half-renamed
contract is a stand that seeds nothing and an audit that finds nothing**, which is
the failure that looks like good news.

A stale `.acceptance/security/roles.json` from an older stand still carries the old
key, so the step re-seeds rather than reusing one.

Gate: `make test-infra` — and this is the one step in M29 where that gate can
finally go from 2 failures to 1, the last being M29.7's runbook quotation. Then run
what the gate cannot: the security stand up, the seed, the identities read back
through `scripts/acceptance/query.py`, and down.

### M29.5 — Run the migration forward and back against a copy of real data

Not against a fixture. Take a dump of a real control plane, restore it onto a
disposable stand, migrate forward, confirm the panel works, migrate back, confirm
the panel still works. **Testing a migration needs no decryption**, so
`HASHI_SECRET_KEY` is not required and is not used: the encrypted columns travel
as ciphertext and are never opened. The copy is destroyed when the step ends.

### M29.6 — Prove that nothing on anybody's device changed

`/sub/{token}` contains no such word, so no subscription needs reissuing and
nobody has to be told anything — but "should not have changed" and "did not
change" are different claims and only one of them is worth having. A scenario
asserts that a subscription issued **before** the migration still resolves, still
returns the same material, and still carries the same token afterwards.

**If this milestone ends with a single person having to re-import a config, it was
done wrong.**

### M29.7 — The living documents, including the charter's own sentence · widened mid-run 2026-09-22

**Widened to carry the assertions that read those documents, and the last prose
residuals.** `docs/**` belongs to no zone, so a diff may hold the documents and the
`infra`-zone tests that quote them without breaking `CLAUDE.md`'s cross-zone rule —
and it **must**, because they cannot move apart:

- `tests/infra/test_deploy_runbook.py:779` and `:1187` do `if "friend-facing" in step`
  over `docs/deploy/runbook.md`'s own text, and
  `tests/infra/test_the_charter_states_what_the_scripts_deliver.py` quotes the
  charter's *"a friend's packets move…"*. **Reword either side alone and the gate goes
  red against the other.**
- `test_the_runbook_quotes_the_refusal_a_node_without_a_resolver_gets` imports
  `edge.egress.NO_RESOLVER` and asserts the runbook quotes it verbatim. M29.2 reworded
  the string; this is the **last red test in the tree** and closing it is what makes
  `make verify` green.
- Pure docstrings still saying the old word in `tests/infra/test_backup_script.py`,
  `test_panel_bootstrap_script.py`, `test_management_tunnel_script.py`,
  `test_caddyfile.py` and `test_drive.py` — swept here. `test_drive.py:194` says "a
  friendly", which is English and stays.
- `aikit.yml` :191, :194 and :268, and `deploy/docker-compose.e2e.yml:40` (*"no real
  friends in it"*) — the last two prose residuals M29.4c named and could not take.

The runbook also states the API break in the owner's own words — *anything scripted
against the old paths stops working* — naming `/api/users/*` and `/panel/users/*`.

The charter, the runbook, `CLAUDE.md`, `README.md` and this plan's open
milestones. The charter's *"for the owner and ~30–50 friends"* becomes
*"~30–50 users"*, per the decision above — and the three non-goals that the word
`friends` was carrying get stated plainly there, because the noun no longer
carries them.

The records listed in M29.1 are verified untouched at the end of this step, by
diff and not by intention.

### M29.8 — The last places a person reads the old word · added mid-run 2026-09-22

M29.7 closed the gate but not the first "Done when". Six things still say *friend*
where a person reads it, each found and measured by an earlier step and owned by none
of them.

**The charter's own sentence disagrees with itself in three places.** `project.json:3`
and `deploy/warden/warden.py:320` both still carry *"for its owner and ~30-50
friends"*, and **no test compares the three copies**. The owner settled that sentence;
having it say two different things in one repository is the half-finished state this
milestone exists to end.

**Two living documents M29.1 classified and M29.7's fence did not reach:**
`.claude/projects/00-core-invariants.md` (2) and `docs/security/threat-model.md` (5).
The first is a fleet instruction file — leaving it stale reproduces the old noun in
new code, which is the one residual with a way of spreading.

**`docs/product/backlog.md` (8), and its classification must be settled first.** This
is M29.1's open carry-over: the file is living, but its own `## Журнал решений` is a
dated decision journal in the same shape as `docs/decisions.md` and is therefore a
**record**. Row `2026-08-01 (ohno-6)` contains the old word inside a recorded
decision. **Settle the carve-out in `docs/records-and-living-documents.md` before
touching the file**, then move only the mutable backlog above the journal.

**`docs/PLAN.md`'s `## Where things stand` (10)** is in neither the living list nor the
records table. By the document's own test it reads living — it says what is open now,
not what was said then — so classify it there and reword it.

**The infra zone's remaining prose:** `deploy/caddy/Caddyfile` (5), `.env.example` (4),
`deploy/e2e.env` (1), `.gitignore` (1). All comments.

**Deliberately NOT in this step, and each for a stated reason.** `pyproject.toml` (3)
is architect territory — `CLAUDE.md` says a developer who needs it asks. `design/**`
(42) and `docs/research/**` (11) are dated artefacts of what was designed and
researched at a time, which is the record test, and `design/VPN Admin.dc.html` is a
tool export nobody hand-edits. All three are named for the owner to decide rather than
swept.

Gate: `make verify`. It is green as of M29.7 and **must still be green** — this step is
the last thing in the milestone and may not be what breaks it.

### M29.9 — Two things the real-host walk disproved · found in the walk 2026-09-22

The walk on real hosts passed M29's central claim: a subscription issued by the
pre-M29 code into the pre-M29 schema, fetched from a second machine before and after
both migrations, came back with **the same URL, the same token, the same status and
headers, a byte-identical VLESS body, and an AmneziaWG config whose every functional
line is byte-identical**. `0008` and `0009` reversed exactly. The panel worked in all
three states.

It also disproved two sentences M29.7 wrote into the runbook. Both are the milestone's
own text, and both mislead an operator at the worst moment.

**1. The rollback procedure cannot be executed as written, and attempting it takes the
delivery endpoint down.** The runbook says *roll the image back first, then the
schema*. That was inferred from M29.5's finding that the entrypoint's
`alembic upgrade head` is unconditional, and it is **wrong**: the pre-M29 image
contains only `0001`–`0007`, so it holds no downgrade path from `0009`. Measured, the
old image crash-loops on `Can't locate revision identified by '0009'`, `make up-panel`
exits `dependency failed to start: container hashi-control-1 is unhealthy`, **Caddy
never starts at all**, and `/sub/*` is unreachable for every user for the whole of that
state — the one route the charter says must stay up. The runbook's own recovery
commands cannot be run either, because a restarting container cannot be `exec`'d into.

The order that works, and it was walked: **downgrade under the NEW image**, then
`stop` it before anything can restart it, then swap the tree and bring the old image
up — whose `upgrade head` is then `0007`, a no-op. The restart trap M29.5 documented
is real and was reproduced deliberately, but it is a reason to stop the container, not
a reason to roll the image back first.

**2. "Nothing on anybody's device changes" is true of the URL and not of the file.**
The subscription URL and token are byte-identical, and so is the VLESS body. But the
rendered WireGuard-family config differs by one line — a `#` comment `wg-quick`
ignores — because M29 reworded the rendered server text too. The consequence is
visible and unannounced: **every node carrying a WireGuard-family transport reads as
drifted immediately after the upgrade**, the Overview carries *"not running the
configuration this panel would give it"* until each is re-applied, and the same
happens in reverse after a downgrade. Drift is `applied_digest != digest_of(rendered)`,
so a comment is enough to trip it.

That is harmless in itself and it is **indistinguishable on screen from a real
configuration change**, arriving exactly when an operator is watching for trouble.
Either the sentence narrows to the URL and the functional config, or the upgrade
section tells the operator to expect a fleet-wide re-apply. Do both.

Gate: `make verify`. `tests/infra/` reads the runbook and pins some of its sentences,
so a rewrite here is executed by the suite the moment it runs.

**E2E:** `tests/e2e/control/` — every existing scenario stays green with its own
names updated, and M29.6 adds the one that asserts a pre-migration subscription
survives. `make verify` across the seam, because this milestone touches two zones
and the documents between them.

**Done when**
- [ ] One word for the concept everywhere a person can read it — screens, API,
      code, and the living documents.
- [ ] No identifier, table, column, route or template file in `control` or `edge`
      still carries the old one.
- [ ] `docs/tracker/**`, `docs/decisions.md` and the completed milestones are
      **untouched**.
- [ ] The migration has been run forward and back against a copy of real data.
- [ ] Nothing on a device changed: no subscription reissued, nobody told anything.
- [ ] `make verify` green.

acceptance: yes
Not because a rename is hard, but because this one carries a migration against live
data. On a stand restored from a real dump: add a person, issue their subscription,
revoke them, and confirm a subscription issued **before** the migration still fetches
and still works on a device that already had it. Then run the migration backwards and
confirm the panel still works.

---

## ✅ M28 — The control plane must be restorable on a machine it has never run on · asked for by the owner 2026-09-22 · done 2026-09-26 (acceptance: good — 3 rounds, 24 steps, the restore performed rather than described)

**Done.** 22 steps landed, one withdrawn. Acceptance rounds 1 and 2 both blocked on the same
defect in new surfaces — a reader of the backup record asserting what the record did not
license — and round 3 passed with six `clumsy` findings and none blocking. The walk destroyed
a working fleet and rebuilt it from one bucket object plus the two carried secrets: the
existing user's **existing** token returned a byte-identical body on the restored control
plane. `file` reads the artifact as *age encrypted file, X25519 recipient*, decryption without
an identity refuses, and the node address, node name, country, username, transport and SQL
keywords all grep to **zero** in it. The host issued 9 PUT and 0 DELETE.

**What the walk could not prove, recorded rather than implied:** the bare host was a fresh
clone on the same Docker engine, not a second machine; the object store was a minimal
S3-protocol server, so bucket versioning, object lock and the provider-side write-only
credential are documented decisions and not exercised; applying the restored node could not
complete because no leaf host exists on a stand; the daily run was proven by installing the
real cron entry and running the tick as cron runs it, not by waiting out 04:00; and **nothing
here says anything about surviving a Russian mobile whitelist shutdown** — that is a field
observation on a real network.

**The real-host restore walk was NOT performed.** It needs read-only bucket credentials at
`~/.hashi/restore.env`, which do not exist. Reported as not performed rather than described.

### What the owner asked for

1. Everything the control plane generates is backed up **once a day, at 04:00**.
2. The backups live in a **Yandex Object Storage bucket**, off the host.
3. When the control-plane box is blocked, seized or lost, it comes back on **another
   machine by one command**.

Today none of the three exists. `scripts/backup.sh` dumps and restores, by hand,
to a file beside the repository — `make backup`, `make restore FROM=…`. There is no
schedule, nothing leaves the host, and the one machine that holds every user's
access and every node's credentials is also the only machine holding its own backup.

### The finding that shapes this milestone, measured before it was planned

**The dump is not encrypted, and the script says it is.** `scripts/backup.sh:72` is
`pg_dump --format=plain | gzip`: ordinary SQL. What is encrypted is a *subset of
columns* (`EncryptedText`, `control/app/models/base.py:86`) —

| encrypted | in the clear |
|---|---|
| node `ssh_private_key`, node_transport `secrets` | node `address`, `ssh_port`, `ssh_host_key` |
| user `token`, `subject`, `secrets`, `tunnel_address` | `transport_name`, ports, states, every timestamp |

**So a reader of the bucket who never obtains `HASHI_SECRET_KEY` still gets a map of
the fleet**: every node's real address — including the leaf addresses a user is
never shown, which is the one thing the entry/leaf topology exists to hide — plus
how many users there are and when each arrived.

`scripts/backup.sh:82` prints *"this dump is encrypted with HASHI_SECRET_KEY"*. That
sentence is false as written and is how this was nearly planned wrong: an operator
reading it concludes the artifact is safe to put anywhere. **Correcting that line is
in scope, whatever else this milestone decides.**

### Why "one command" is the requirement and not a nicety

The day this is used is the day the box is gone. The operator is not reading a
runbook carefully; they are rebuilding under pressure, possibly from a phone tether,
possibly having just lost the machine to something that was not an accident. Every
step that is not in the command is a step that gets skipped or done wrong. **The
measure of this milestone is not that a restore is possible — it already is — but
that it is possible by someone frightened and in a hurry.**

### Settled by the owner, 2026-09-22

- **Decision 3 is taken: the whole dump is encrypted before it leaves the host**,
  with `age`, and with a **keypair rather than a passphrase**. The control-plane
  host holds only the public recipient (`HASHI_BACKUP_AGE_RECIPIENT`), so it can
  write a backup and cannot read one back. The private identity never touches that
  machine; it is what the operator carries beside `HASHI_SECRET_KEY`. That is the
  answer to the second secret the milestone worried about: there are still two
  things to carry, but neither of them is ever on the box that gets seized.
- **Already landed, so plan around it rather than repeating it:** `.env.example`
  now carries the offsite-backup block — `HASHI_BACKUP_ENABLED`,
  `HASHI_BACKUP_S3_ENDPOINT` / `_REGION` / `_BUCKET` / `_PREFIX`,
  `HASHI_BACKUP_S3_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY`,
  `HASHI_BACKUP_AGE_RECIPIENT`, `HASHI_BACKUP_AT`, `HASHI_BACKUP_TZ` — plus a
  comment recording that the restore-side `HASHI_RESTORE_*` credentials are
  deliberately **not** stored on the control host. `make test-infra` is green with
  it. The names are S3-protocol names, never a provider's, per decision 4.

### M28.1 — Say what the artifact is, and stop the script claiming it is something else

Decide and write down what "everything the control plane generates" means, item by
item: the database, Caddy's ACME state and private keys (`caddy_data`), the
management tunnel config under `~/.hashi/management/`, and `.env` itself — each an
explicit yes or no with its reason. `/opt/hashi` on a node is explicitly **not**
backup material: the database is the source of truth and a node holds nothing that
cannot be regenerated from it.

In the same step, `scripts/backup.sh:82` stops saying *"this dump is encrypted with
HASHI_SECRET_KEY"*. That sentence is false as written — `backup.sh:72` is
`pg_dump --format=plain | gzip`, and what is encrypted is a subset of columns — and
it is how an operator concludes the artifact is safe to put anywhere. **Correcting
it is in scope whatever else this milestone decides**, and it is first because it is
the one thing that is wrong today rather than merely missing.

### M28.2 — The artifact is encrypted on the host that makes it, to a key that host cannot read back

`age`, the recipient from configuration, before anything leaves the machine.
Without this, a reader of the bucket who never obtains `HASHI_SECRET_KEY` still
gets every node's real address — **including the leaf addresses a user is never
shown, which is the one thing the entry/leaf topology exists to hide** — plus how
many users there are and when each arrived.

`age` is a new dependency on the control-plane host and therefore an **architect
decision** (`CLAUDE.md`). Confirm it before adding it; if it is refused, stop and
ask rather than substituting something.

What a reader of the bucket learns after this step is written down in
`docs/decisions.md` — together with decision 4, that the bucket sits in the
jurisdiction the project exists to work around and is tied to the owner's identity
through payment, accepted knowingly.

### M28.3 — The upload uses a credential that cannot delete, and the storage backend is a field

S3-protocol configuration, never a hardcoded provider — `CLAUDE.md`'s rule about
never hardcoding a provider applies here exactly as it does to a node, and for the
same reason: a provider you cannot rotate away from is one you are stuck with on
the day you need to leave it.

The credential written onto the host is **write-only** — `PutObject` and nothing
else. An attacker who holds the control-plane box holds this key, and a key that
can delete turns a seizure into a total loss of the backup history as well as the
machine.

### M28.4 — Retention the host's own credential cannot reach

The write-only key is half of it; the other half is enforced bucket-side, where
that key has no authority. Decide which of versioning, object lock or a lifecycle
rule the storage actually offers, and what the fallback is if it offers none —
then write down which one is in force. A write-only key against a bucket with no
retention still loses the history to anyone who obtains a better credential.

### M28.5 — Something runs it every day, and says which day it missed

Cron, a systemd timer, or a service in the compose stack — pick one, and note that
**adding a scheduler is a dependency and therefore an architect decision**
(`CLAUDE.md`); confirm it before adding it.

Then decide what `04:00` means on a host whose clock is UTC and whose owner is not
— `HASHI_BACKUP_AT` and `HASHI_BACKUP_TZ` exist for exactly that — and what
happens to the day's backup when the box was down at 04:00. **A schedule that
silently skips is the failure mode that is only discovered during a restore.**

### M28.6 — A backup that has been failing for six weeks says so where the owner already looks

The dangerous state is not "the backup failed", it is "the backup has been failing
for six weeks and nothing said so". The panel's Nodes screen already carries
banners and this is the same kind of fact; decide whether it belongs there or
somewhere of its own, and make a run that does not land visible without anyone
going to look for it.

### M28.7 — Nothing in any of this records who connected to what

A backup job is a new thing that writes files and may log, and a restore command is
another. The charter's one absolute prohibition applies to both unchanged — no
connection, traffic or DNS logs, at any level, including debug and including
temporarily while debugging. Checked on every new surface this milestone adds,
rather than assumed because nobody meant to add one.

### M28.8 — One command, two inputs, and an honest list of what it does not do

The restore: given `HASHI_SECRET_KEY`, the `age` identity and read credentials for
the bucket, on a machine that has never run this project, it produces a control
plane serving the same users and driving the same nodes as the one that was lost.
The restore-side credentials are supplied to the command at the moment it runs, on
the new machine, and are never written onto a control-plane host — that is what
`HASHI_RESTORE_*` is for.

Beside it in the runbook, what it does **not** do, said out loud: it does not move
DNS, it does not re-issue the delivery endpoint's certificate, and it does not tell
users anything. A restored control plane on a new address with the old
`HASHI_PUBLIC_HOST` pointed elsewhere serves nobody. Whatever the command cannot
fix is an operator step, written where the operator will be looking.

**The measure of this step is not that a restore is possible — it already is — but
that it is possible by someone frightened and in a hurry.**

### M28.9 — Perform the restore on a bare host

Not describe it. `make verify` cannot rent a machine, so this step is walked: a
host with nothing but the repository, the key, the identity and read credentials,
and the one command. **A restore that was described rather than performed does not
count**, and the step is not done until the panel on the new host is logged into
and the existing nodes are there.

**E2E:** `tests/infra/` for what the backup and restore commands assert, and
`tests/e2e/infra/` beside `test_panel_bootstrap.py` for the job running against a
disposable stack. An object store for the stand to talk to is a dependency
decision of its own — if it is refused, the suite gate narrows to `tests/infra/`
and the real proof is M28.9's walk, which is a field observation and is reported
as one.

### M28.10 — What the bare-host walk found · walked 2026-09-23

**The restore works.** A control plane built on a Russian box and killed without a
graceful stop came back on a machine that had never run this project: one command plus
the three carried inputs, the existing node applied from the rebuilt panel in 3.8s, and
the existing user's subscription returned **byte for byte identical** — same token, same
path, `sha256 14b0d1fb…`, 336 bytes. The age layer holds: a bucket reader gets
`age-encryption.org/v1` and a refusal, while the decrypted dump carries the leaf address
in the clear, which is precisely what that layer exists to cover. The scheduled path fired
unattended at the appointed minute and recorded `outcome: offsite`.

**It fails the milestone's own measure**, which is not "a restore is possible" but *"the
walk fails if the operator had to read anything other than the command to get there"*.
Six things made that untrue, in the order they bite.

1. **`HASHI_OPERATOR_PASSWORD_HASH` cannot be produced on a bare host, and the runbook
   says it can.** The first refusal sends the operator to `.env.example`, which sends them
   to `python -m control.cli hash-password`. Ubuntu 22.04 ships Python 3.10; `make setup`
   wants 3.14 and fails. The runbook's restore block says *"fill in HASHI_SECRET_KEY, the
   hostnames, the operator password hash and the database password. Nothing else is
   needed"* — and one of those four cannot be made on the machine. **This is the gap
   between "the operator reads the command" and "the operator needs a second working
   checkout."** The hash is computable inside the control image, which the command builds
   anyway.

2. **The one command is interactive and says nothing when it cannot be.** Over a
   non-interactive session it prints the confirmation prompt, reads EOF, and exits 2 with
   no sentence — **after** installing the control plane and fetching the artifact. Nothing
   in the runbook's command block says a terminal is needed. And on a bare host the
   prompt's own text is false: *"Every current node, user and credential is overwritten"*
   describes nothing, in exactly the case the command exists for.

3. **The closing screen's first instruction is the one the Makefile warns against.** It
   says *"Restart the control plane so it reconnects: `make down && make up`"*. Followed
   literally that yields a stack publishing **no ports** — `make up` converges to the base
   shape, which the Makefile itself flags. Two paragraphs later the same screen says
   `make up-panel`. Between "restored" and "logged in", the screen contradicts itself.

4. **`make up-panel` needs a non-loopback address a fresh restore does not have.**
   `HASHI_PRIVATE_BIND_ADDR` is refused if it is loopback, and with no management tunnel
   there is no other address on the box. The walker had to invent one. The refusal points
   at the runbook, which is documented — and is one more step the command does not carry.

5. **A restored fleet is an unbacked-up fleet, and nothing says so.** The write-only S3
   key and the age recipient lived only in the lost `.env`, which is deliberately not in
   the backup. On the restored host `make backup` fails outright:
   `required variable HASHI_BACKUP_AGE_RECIPIENT is missing a value`. Neither the closing
   screen nor the runbook's restore section mentions re-establishing the offsite block.
   **The panel is honest about what it records and silent about the fact that nothing will
   be recorded.**

6. **`scripts/backup.sh` calls `age-keygen` in a diagnostic, and a bare host has none.**
   The wrong-identity path prints `age-keygen: command not found` — a raw shell error on
   the operator's screen — and loses the public key the sentence meant to show. It
   degrades on precisely the machine the command is designed for.

**Not in this step, and recorded rather than fixed:** with a wrong `HASHI_SECRET_KEY` the
panel answers every page with **409 and a raw JSON body** rather than a screen (the
message inside it is exactly right), and `/sub/{token}` returns **404 with zero bytes**,
indistinguishable from a revoked token — the same signature as M26's open blocker 2. Both
are `control`'s and neither is M28's to widen into. `HASHI_PUBLIC_HTTPS` is settable in
`settings.py` and the Settings screen but is in neither `.env.example` nor
`deploy/docker-compose.yml`.

Gate: `make verify`. The proof of 1–4 is a second walk, not a suite.

### M28.11 — `control`: the panel must not say a backup left the machine when it did not · found in acceptance 2026-09-23

Three things the panel says that are not true. All four of acceptance's blocking
findings have a panel half and a script half; this step is the panel's, M28.12 is the
script's, and they are separate because `CLAUDE.md` does not allow one diff to cross
zones.

1. **A backup that never left the machine reads exactly like one that reached the
   store.** Two records identical but for `offsite` — `yes` against `no`, both with a
   success today — render **byte-identical** screens: *"Last backup 17 hours ago: the run
   reported "ok"."* `cmp` reports no difference. The caveat below then talks about
   *"whether any of those artifacts is still in the bucket"*, which for a host that sends
   nothing is worse than silence. **This is the shipped default** — `.env.example` carries
   `HASHI_BACKUP_ENABLED=0`, and its own comment states the rule being broken: *a backup
   that never left the machine is not an offsite backup and must not be reported as one.*
   The record carries the field; the panel drops it. **It goes straight at the milestone's
   first "Done when" and at the complaint that started M28.**

2. **"Most recent" missed days prints the oldest ones.** With eight days stored, three in
   August and three this week, the panel printed *"8 — most recent 2026-08-12,
   2026-08-13, 2026-08-14"*. In the long-outage state — the exact case that sentence
   exists to distinguish — it points six weeks back instead of at now. Neither surface
   sorts; both trust the writer's order, so one of the two labels is wrong whatever that
   order is, and nothing enforces it.

3. **A record dated in the future reads as the quiet reassuring state and can never leave
   it.** Clock skew gives *"Last backup less than an hour ago"* for ever. M28.6 clamps a
   future age to zero rather than reporting it; clamping is right for arithmetic and wrong
   for the sentence.

Gate: `make test-control` with a real Postgres — **report the skip count** — plus
`tests/e2e/control`, then `make verify`.

### M28.12 — `infra`: the command line must not be more confident than the panel · found in acceptance 2026-09-23

The other half of the same four findings.

1. **`make backup-status` reads a damaged record as a fresh host.** The panel refuses to
   assume anything from it — *"Nothing has been assumed from it"* — and then sends the
   operator to `make backup-status`, which prints *"last success: never / last attempt:
   never"* plus a confident *"scheduled: 04:00 Etc/UTC (configured)"* and exits **0**,
   indistinguishable from a machine that has never run one. It can clearly do better: with
   the file **absent** it prints a proper "no record" page and exits 1. It validates
   nothing — `schema: 99`, or a 1000-character `outcome` carrying a `<script>` tag, is
   printed verbatim as fact while the panel calls the same file unreadable.

2. **The same `offsite` blindness, in `make backup-status`**, and the same missed-days
   ordering. Whatever M28.11 settles for the panel's wording, this must match it — and the
   **writer** is here too, so if the order of `missed_dates` is the thing to fix, fix it
   at the source and let both readers stop guessing.

3. **`make backup` blames the backup keypair for failures that have nothing to do with
   it, and the remedy would orphan every existing artifact.** With
   `HASHI_BACKUP_AGE_RECIPIENT` set and non-empty, `make backup` still printed the whole
   *"it needs the PUBLIC half of your backup keypair … `age-keygen -o …`"* page; supplying
   the variable it named moved the cause to the next one and printed the same advice
   again. So the guard says "your recipient is missing" for **any** env-interpolation
   failure. An operator who follows it generates a new keypair — after which every
   artifact already in the store is addressed to an identity they have just replaced.
   **`make restore-from-bucket` meets the same class of failure and names the exact keys:
   the good pattern is already next door.**

4. **Smaller, same file:** exit 3 is shown as a number and never as what it means — the
   artifact is still on the machine and `make backup-upload` is the remedy; and the
   crontab block says *"is the **account** that does not depend on mail existing"* where
   it means *channel*.

**Widened by the second bare-host walk, 2026-09-23.** Five of M28.10's six fixes were
confirmed working on real machines — `make hash-password` in 46s on Ubuntu 22.04 with
Python 3.10 and no images; the placeholder refused in 1s instead of 180; the prompt
asked nothing on a bare target and named `FORCE=1` on a populated one; no address had to
be invented; `make restart-control` left the ports published. **The measure now fails on
one sentence rather than six places.**

5. **The runbook's restore block is wrong about what `.env` needs, and it costs a whole
   failed run.** It says *"fill in `.env`: `HASHI_SECRET_KEY`, the hostnames, that hash
   and the database password. **Nothing else is needed** to run the command below."*
   Following it exactly installed the entire control plane and then died at
   `storage.example.net` — because `deploy/backup/fetch.py` falls back to the
   `HASHI_BACKUP_S3_*` block, and on a rebuilt host that block is `.env.example`'s fakes.
   **`HASHI_RESTORE_S3_ENDPOINT` / `_REGION` / `_BUCKET` / `_PREFIX` are named nowhere in
   that block**, and the walker had to read a trailing comment in `.env.example` to learn
   they exist. **This is now the only remaining place an operator must read something
   other than the command.** Good half: the command prints the endpoint it used, so you
   can see it is not yours. Bad half: *"the configuration resolves"* one line above
   `Name or service not known` reads as a contradiction.

6. **"A second run is safe" is true for the data and false for the panel.** Re-running the
   command runs `panel-bootstrap.sh`, which converges to the base compose file — after
   which nothing is published on 80, 443 or the console port, and Caddy is back to
   unpublished. **This is M28.10's finding 3 arriving through a different door**: the
   operator re-runs the command they were told was safe to re-run and loses the console
   and the delivery endpoint. The only warning is in the runbook, under a different
   heading — which is again "something other than the command".

7. **The restore generated a management tunnel from the template and printed two device
   private keys into the rebuild's scrollback.** `.env.example` ships a complete
   `HASHI_MGMT_*` block, so panel-bootstrap wrote `~/.hashi/management/awg-mgmt.conf` and
   printed two full device configs — `PrivateKey = …`, `Endpoint = hashi.example.com:51821`
   — at an operator who asked for none of it. They are fabricated credentials pointing at
   the template's example host, and a private key on a terminal is the class of thing
   M28.7 and M28.8 exist to prevent. It also puts the closing screen at odds with the
   machine: the screen says the old tunnel's keys were lost, while a tunnel config now
   exists here and `make up-panel` fails for a different reason than the screen gives.

8. **Smaller:** `.env.example`'s placeholder *value* still reads
   `run-python--m-control.cli-hash-password-and-paste-the-output` — the route that cannot
   run on a bare host — even though the comment above it and the refusal both name
   `make hash-password`; the closing screen's `ssh -L` line makes the operator go and find
   `HASHI_PRIVATE_PORT` in `.env` although the script already reads `HASHI_PUBLIC_HOST`
   out of the running container; and a successful restore puts ~6.7 KB on **stdout** (the
   build log and ~90 lines of raw `psql` tags) between "restoring…" and the closing
   screen, which is on stderr.

Gate: `make test-infra`, then `make verify`.

### M28.13 — The same weak parser, in the script that writes the tunnel · found in review 2026-09-24

`scripts/management-tunnel.sh::value_of` is the parser M28.12 replaced everywhere else:
**no `\r` strip, and first-assignment-wins where an env file means the last.** Reproduced
rather than inferred:

```
$ printf 'HASHI_MGMT_ENDPOINT=panel.invalid\r\nHASHI_MGMT_PORT=51821\r\n' > env
$ echo "Endpoint = ${ENDPOINT}:${PORT}" | cat -A
Endpoint = panel.invalid^M:51821^M$
```

Its output feeds `Address`, `ListenPort`, `MTU` and `Endpoint` straight into the host's own
`awg-mgmt.conf` **and into every device config the script prints for an operator to paste
onto a phone or a laptop**. `PEER_SPECS=(${MGMT_PEERS})` also leaves a `\r` glued to the
last peer's address, because bash's default `IFS` does not include it.

**It is a different failure class from M28.12's High and that is why it is its own step.**
That one was a credential leak reachable by copying `.env.example` unedited. This is
**config corruption of a genuinely configured tunnel** — it needs an operator who filled in
real values on an editor that writes CRLF, and the symptom is "the tunnel does not come up"
from a file that looks right. Not a lockout: `make up-panel-over-ssh` plus `ssh -L` does not
depend on this generator. But it costs real debugging time, and it lands on **the exact
reachability path M28 exists to protect** — the way an owner reaches the panel after a
restore.

Adopt `env_value_of`'s idiom, or extract it so both scripts share one implementation rather
than a third copy. **Red-first against `tests/infra/test_management_tunnel_script.py`**,
which is 435 lines and is why this did not ride along inside M28.12.

Gate: `make test-infra`, then `make verify`.

### M28.14 — `control`: the panel must not promise a schedule it cannot see · found in acceptance round 2, 2026-09-24

**Round 2 confirmed all four of round 1's blockers fixed.** What blocks now is the same
disease in a fifth surface, in a field the fixes did not touch.

**The panel says "The host takes one a day at 04:00 Etc/UTC." on a host where no schedule
is installed.** On the stand as shipped, `scripts/backup-schedule.sh show` prints *"no
hashi backup schedule is installed for this account"* and exits 1, and the crontab holds no
entry — while the Overview states the daily backup as fact. **The schedule is opt-in, so
this is the state of every fresh install.**

The panel reads one file and that file carries `at` and `zone`, which are what the
scheduler **would** use — not evidence that anything runs. The panel cannot see a crontab
and must not imply it can. Say what the record actually tells you: the time a run would be
due, not that one is taken.

**Also this round, not blocking, and cheap while you are here:**
- The **exit-3 advice** — *"it never left the machine, re-send it"* — also prints under a
  run that **exited 0 and did leave**. It is not conditioned on the exit code.
- **Twelve missed days across seven weeks carries no badge; one failed run does.** A gap
  that large is not a quiet fact.
- **`days with no backup: 12 — most recent:`** with nothing after it, when the record the
  product itself wrote has a count but no dates.
- **A record that is only re-indented is reported as damaged.** The reader requires the
  writer's exact layout; re-indentation changes no value.
- **The Settings screen still lists no backup setting at all** (round 1's leftover,
  unmoved), while the Overview names `HASHI_BACKUP_ENABLED` by hand and sends the owner to
  a markdown file.

Gate: `make test-control` with a real Postgres — **report the skip count** — plus
`tests/e2e/control`, then `make verify`.

### M28.15 — `infra`: the command line must not promise a schedule either, and `due` must stop assuming · found in acceptance round 2, 2026-09-24

The other half, and this side **can** check.

1. **`make backup-status` says *"scheduled: 04:00 Etc/UTC (configured), checked every 15
   minutes"* whether or not a schedule exists.** Proven: the entry was installed, the
   output diffed **byte-identical**; then `make backup-unschedule` answered *"removed.
   Nothing runs a backup on this host now."* and the next `backup-status` printed the
   schedule line again. **Three commands in one family, one of them contradicting another
   the same minute.** Unlike the panel, this runs on the host and `backup-schedule.sh show`
   already answers the question — use it.

2. **`scripts/backup-run.sh due` is the one surface round 1's fix missed.** On a damaged
   record it still says *"no backup has ever been recorded on this host"*, `offsite=no
   missed=none`, **exit 0** — indistinguishable from a fresh host, asserting facts from a
   file it could not parse. `status` was taught to refuse; `due` was not.

3. **A clock that ran ahead stops backups silently.** The panel warns; `make backup-status`
   says *"last success: 2027-03-01 (ok)"* with no mention; and **`due` answers
   `action=wait` for ever at exit 0**. Nothing is taken and nothing says so.

4. **`HASHI_BACKUP_ENABLED=1` in the process environment is honoured by the uploader and
   ignored by the recorder**: the run uploads and says so, then the screen says the upload
   is switched off. The env-file path is correct; the two readers disagree about where the
   answer comes from.

5. **Three items M28.14 could not reach, traced to this zone with line numbers** rather
   than left to be rediscovered. The panel's equivalent is already correct in each case,
   so the shape of the answer exists — the point is that the two channels disagree about
   one record:
   - `scripts/backup-run.sh:766` — the exit-3 advice fires on `[ "${BAD_CODE}" = "3" ]`,
     and `BAD_CODE` survives a later success, so *"it never left the machine, re-send
     it"* prints under a run that exited 0 and did leave.
   - `scripts/backup-run.sh:775` — `days with no backup: 12 — most recent:` with nothing
     after it. The panel guards this (`tail = "." if not recent`); the shell does not.
   - `scripts/backup-run.sh:606-620` — `entry_problem` requires each nested entry on one
     line, so a record that is **only re-indented** is reported damaged. The control
     reader is `json.loads` and accepts any layout, which is why acceptance saw this on
     one channel and not the other. **Tolerate layout and nothing else:** unknown keys,
     changed values and truncation stay damaged, and the closed 15-key set stays closed.

Gate: `make test-infra`, then `make verify`.

### M28.16 — `control`: a gate that is green in the run the fleet reports on · found reviewing M28.14, 2026-09-24

Not a backup defect, and it is here because this milestone is the thing that found it
and the thing it lies to.

`tests/control/test_apply_must_reach_the_daemon.py::test_a_stale_apply_records_no_applied_digest`
**is flaky.** It failed under `make test-control` at both `2b0eb6a` and the baseline
`12f79a5` with the work stashed, and **passed inside `make verify` on the same commit.**
So the milestone has been verified twice by a suite that disagrees with itself about one
test depending on which command ran it.

The cause is one line. At `:325-334` the test reads `first` **without**
`session.expire_all()`, while the second read twelve lines later has one. SQLAlchemy's
identity map holds **weak** references, so whether the stale `applied_digest=None` copy
from `a_node_with_a_transport` is still alive at that `select` depends on garbage
collection — which is exactly "passes alone, fails under the suite, passes sometimes".

**Why it gets a step rather than a carry-over line.** `CLAUDE.md` says gate on
`make verify`, and the whole claim of this pipeline is that nothing passes on the
author's own word. A test that is red two runs in three and green in the one the fleet
reports on is the one shape of red that never gets fixed: every reviewer sees it pass,
and every implementer who hits it correctly concludes it is not theirs. It is also the
cheapest fix in this milestone.

Add `session.expire_all()` before the first `select`, matching the idiom the same test
already uses at `:337`. **Prove it rather than asserting it**: the failure is
GC-dependent, so a single green run is not evidence. Run the full `make test-control`
several times and say how many, and say plainly if you cannot make it fail at the
baseline on demand — an unreproducible fix to an intermittent test is a guess, and
should be reported as one.

Then check whether the shape repeats: any other test reading through a session that a
fixture also populated, without expiring it first, is the same bug waiting for a
different garbage collection.

Gate: `make test-control` with a real Postgres, run repeatedly, then `make verify`.


### M28.17 — `infra`: pin the parity that is currently only promised, and the last two-channel split · found reviewing M28.15, 2026-09-24

Four small things, all the same subject: a claim that the two channels agree, with nothing
holding them to it.

1. **The 64 KiB ceiling is now a behavioural contract and no test pins it.** Both channels
   refuse a file over `MOST_OF_A_RECORD` for its size, and that parity is asserted only in
   prose — a script comment saying *"the same number as `control/app/services/backups.py`'s
   `MOST_OF_A_RECORD`"* and a runbook sentence saying *"the same ceiling and the same answer
   as the panel"*. The number is then written out a third and fourth time in the new
   fixtures. **Move either side and the two channels give different verdicts about one
   file, with nothing going red** — the exact defect class this milestone exists to close,
   reintroduced as a documentation promise.
   `tests/infra/test_the_command_line_says_what_the_panel_says.py` already AST-reads the
   control zone's source for this kind of parity, and that is where this belongs. The
   fixtures should read the number rather than repeat it.

2. **`refuse_damaged_record "size"` names a key that does not exist.** It renders as
   *its "size" is not what scripts/backup-run.sh writes there*, and every other argument to
   that sentence — `schema`, `missed_dates`, `last_success` — is a real JSON key, so an
   operator goes looking for a `size` key and finds nothing. Give the size case its own
   sentence. It can name the file's size without reading any of it.

3. **The runbook says an over-large file is refused whole and never says the next tick
   replaces it.** The terminal refusal does say so; the runbook reader is the one who is
   planning, and is the one not told. One clause: move the file aside first, because the
   next scheduled run rewrites the record.

4. **A directory at the record path splits the two channels** — pre-existing, and the
   seventh surface of this milestone's one defect. The command line's `[ -f ]` reads it as
   *"No backup has ever been recorded on this host"*; the panel classes the same shape as
   presence-with-nothing-legible and answers `UNREADABLE`. Worse, `write_state`'s `mv` then
   deposits `last-run.json.partial` **inside** that directory, so the schedule runs, reports
   success and leaves no record at all — every tick, for ever. Refuse the shape by name,
   matching the panel.

**Why these are worth a step rather than a carry-over line.** Three of the four are one or
two lines of code. The first is the one that matters: this milestone has been blocked twice
for surfaces stating what the record does not license, and the fix for the last one ended by
creating a fresh promise that the two channels agree, held up by a comment. A parity that
only a human re-reading two files can check is the same thing as no parity.

Gate: `make test-infra`, then `make verify`.


### M28.18 — `infra`: one reader of the backup record, and `tick` decides from it · the root of the seven surfaces · settled by the owner 2026-09-24

**This is the defect the other surfaces were symptoms of.** M28 has been blocked by
acceptance twice and reviewed into four more instances of one thing: several independent
readers of one file, each deciding for itself what that file entitles it to say.
`scripts/backup-run.sh` alone holds **two readers** — the lenient `field`/`read_state` path
behind `tick` and `now`, and the strict `record_problem` path behind `status` and `due`.

That is the same shape M28.12 named and M28.13 closed one level down, and the lesson is
recorded in this milestone's own notes: *the defect was never one bad comparison; it was a
second parser that gives the right answer on every file anybody tests with.*

**What it costs today, verified twice:** a record with `"due_date": "2099-01-01"` makes
`tick` exit 0, print nothing, and take no backup **until the calendar catches up** — the
channel that actually takes backups silently stopped — while `due` exits 1 and the panel
draws a banner about the very same file. A damaged `last_attempt` makes `tick` conclude the
day's backup was taken; that one self-heals when the due date rolls over, and the
clock-ahead one does not.

### Settled by the owner, 2026-09-24

**A record `tick` cannot read is no record, and `tick` takes a backup.**

The fail-safe direction, and it follows the discipline the speaking channels already have:
*nothing has been assumed from it.* A reader that cannot parse the file must not conclude
the day's backup was taken, and the only other answer — refusing to run — stops backups on
the strength of a file the product itself cannot understand, which is the failure this
milestone exists to prevent. The cost is accepted knowingly: **a damaged record triggers a
dump rather than suppressing one**, so a host in that state takes at most one extra backup
per due period until the record is rewritten, which the same run does.

Record it in `docs/decisions.md` in that file's existing format, appended and never
rewriting what is there.

**Build `scripts/lib/backup-record.sh`**, sourced the way `scripts/lib/env-value.sh` and
`scripts/lib/env-file-gate.sh` are: the canonicaliser, the strict validator and the field
readers behind **one entry point** that returns either a refusal key or a validated
reading. Every verb — `tick`, `now`, `status`, `due` — reads through it. When it refuses,
`tick` and `now` proceed as if the host had no record; `status` and `due` refuse as they do
today, unchanged.

**What this must not become.** Not a rewrite of what the verbs say — the wording of every
refusal, caveat and headline is acceptance-judged and stays byte-identical. Not a
loosening: changed values, truncation, a schema from the future, the wrong shape at the
path and a file over the ceiling all stay refused by name. Not a new standing, and not a
sixteenth key. The closed key set stays closed **on the writer**, where it is enforced; the
reader keeps ignoring keys it does not know, by the panel's documented design.

**`due` should gain what the collapse makes possible:** it can now state what `tick` *would*
do with an unreadable record instead of only refusing, because both finally read the same
answer.

Gate: `make test-infra`, then `make verify`. Prove the two readers are gone rather than
asserting it — a structural test that fails if a second parser of the record appears in
that file again, in the shape of `test_no_reader_of_the_record_feeds_it_through_a_pipe`.


### M28.19 — `infra`: the schedule stops waiting for a date it does not trust, and the fences stop being wider than they read · 2026-09-24

Five items. The first is a behaviour decision; the rest are the guards this milestone built
turning out to have seams, which is the same lesson one level up.

1. **A record dated ahead of this host's clock must not stop the schedule silently.**
   Today `tick` exits 0, prints nothing and takes no backup until the calendar reaches the
   date. `due` exits 1 and says *"NOTHING IS BACKED UP AT ALL"*; the panel says nothing at
   all (item 2). This is not the two-readers defect — the record is **valid** and both
   readers always agreed about it — it is `decide` answering `wait` where `note_clock`
   answers `ahead`.

   **Decided, and marked as the orchestrator's extension of the owner's rule rather than
   the owner's own:** the owner settled that *a record `tick` cannot read is no record, and
   `tick` takes a backup*. The same reasoning covers a record `tick` cannot **trust**, and
   taking the backup is the answer that **repairs the state**: the new record carries
   timestamps from this host's own clock, so it is no longer dated ahead and the next tick
   behaves normally. One extra dump, once.

   The rejected alternative, and why — **refuse loudly, exit 1, let cron mail the
   operator.** It has a precedent: M28.17 made `tick` exit 1 on the `shape` fault and the
   notes record *"Loud is right."* But `shape` refuses because writing the record is
   **impossible** — there is a directory in its way. Here writing is possible and writing is
   the cure, so refusing would leave the host with no backups until a human reads mail. The
   precedent is about a case with no other move.

   Record it in `docs/decisions.md`, appended, and say in the row that it is an extension of
   the owner's rule and reversible.

2. **Three files claim the panel draws a banner for such a record. It does not.**
   `control/app/services/backups.py::_ahead()` reads only the `last_success`/`last_failure`
   timestamps — by its own documented design — so a record whose `due_date` alone is ahead
   gives `standing=SILENT` and no banner. Verified. It is reachable without a hand edit:
   move `HASHI_BACKUP_TZ` west across the date line and `due` says `clock=ahead` while the
   panel says `FRESH`. **Narrow the sentences in `docs/decisions.md`, `docs/deploy/runbook.md`
   and `scripts/lib/backup-record.sh` to what is true** — the panel goes loud when a *run
   timestamp* is ahead, and is silent when only the `due_date` is. Making the panel notice
   is M28.20 and is not in this zone.

   **This is the third false-prose finding inside one step.** The rewrite that removed a
   claim about a fix that had not happened introduced a different untrue claim in its place.
   Check every sentence you write here against behaviour you have actually run.

3. **The "records nobody" audit is first hop only.** `_sourced_libraries` reads the three
   named scripts and does not recurse into the libraries it finds. Proven by planting
   `scripts/lib/record-notes.sh` with a `tee -a /var/log/…` in it, sourced from
   `backup-record.sh`: **all 14 tests stayed green.** Record handling now lives in a library,
   so the next move is library→library — the exact hop this misses, and the exact scenario
   the test's own docstring describes. Make the discovery transitive: iterate a worklist
   until no new `scripts/lib/*.sh` appears, same regex, same `is_file()` assertion.

4. **Two seams in the fences, both planted and confirmed.**
   - Process substitution under a command word not in the tool list passes the entry-point
     fence: `done < <(sed -n 1p "${STATE_FILE}")`. Treat `<(` like `$(` in `_commands`, or
     add the shape to the written seam list — but do not leave it both unfixed and unlisted.
   - `_whole_pipelines` folds a **comment** line ending in `\` into the code line below it,
     although bash does not continue comments — which hides that code line from the pipe
     guard. Three such doc-comment continuations already exist in the tree. Do not carry a
     continuation from a line whose stripped form starts with `#`.

5. **The restore scenarios do not run on this machine, and the fixture is why.**
   `object_store()` runs `docker pull` unconditionally and returns `None` on failure, so ten
   scenarios — four upload, six bucket-restore — skip with *"could not obtain
   quay.io/minio/minio:…"* while **that exact image is present locally**. quay.io answers
   401 here.

   **Fall back to `docker image inspect` when the pull fails**, and skip only when the image
   is genuinely absent. This is not making the stand match the expectation — the scenarios
   still run a real object store and really upload and restore; what changes is that a
   registry outage stops disqualifying an image the host already has. The loud skip stays
   for the case where it is truly missing.

Gate: `make test-infra`, then `make verify`. **`make verify` must report e2e 224 passed / 0
skipped.** A 214/10 run does not close this milestone: M28 is the offsite-backup-and-restore
milestone, and `CLAUDE.md` records what it cost the last time scenarios were absent from the
gate for eleven milestones.

### M28.20 — `control`: the panel is the last channel that cannot see a stopped schedule · the eighth surface · 2026-09-24

`control/app/services/backups.py::_ahead()` reads the `last_success` and `last_failure`
timestamps and **never reads `due_date`**. That is deliberate and documented. The
consequence is not: a record whose `due_date` is ahead of this host's clock stops the
schedule completely, and the panel answers `standing=SILENT` — no banner, nothing said.

Verified two ways. Hand-seeded, a `"due_date": "2099-01-01"` record gives
`success_ahead=False, failure_ahead=False, standing=SILENT`. Organically, moving
`HASHI_BACKUP_TZ` west across the date line gives `due` `clock=ahead` and *"NOTHING IS
BACKED UP AT ALL"* while the panel reports `FRESH` — a **healthy** standing on a host that
is taking no backups.

**This is the eighth surface of this milestone's one defect and the last one found.** Every
other instance was a channel asserting something the record did not license; this is a
channel failing to assert something the record states plainly, which is the same disease
read from the other side.

The panel must notice. **What it must not do is grow a second copy of the schedule's
reasoning** — that is the trap M28.18 avoided when `due` was taught to name what the next
tick would do, and it avoided it by calling `decide` rather than restating it. The panel
cannot call the shell, so work out what the *record itself* licenses the panel to say about
a date it cannot reconcile with its own clock, and say no more than that.

Constraints inherited and not re-decided: the panel does **no I/O** — no shell, no crontab,
no clock beyond the one it already reads; `CLOCK_AHEAD_GRACE` already exists and is pinned
against the shell's `CLOCK_AHEAD_GRACE_SECONDS`; the six standings and two weights stay, and
`clock ahead` already wins where several apply; no apostrophe may reach a Jinja template.
Whether this is the existing `clock ahead` standing widened or something the existing one
should already have covered is the question the step has to answer — and if widening it is
right, say why the two cases belong under one name.

Gate: `make test-control` with a real Postgres — report the skip count — plus
`tests/e2e/control`, then `make verify`.


### M28.21 — `infra`: the sentences the last three steps falsified, and the guards that read as exhaustive · 2026-09-24

The cleanup step, and it exists because of a pattern rather than a bug. **This milestone has
produced six findings of the form "prose asserts behaviour the code does not have", and five
of them were written by the fix for the one before.** Two more arrived in M28.19's second
round, and M28.20 falsified five sentences in this zone by changing what the panel does.

Every item here is a sentence that is false at this commit, or a guard that describes itself
as narrower than it is.

**A. The sixth instance, in the paragraph written to fix the fifth** — `scripts/backup-run.sh:472-474`.
The DUE paragraph promises *"one extra dump and then a record that reads normally"*. False
when `last_failure` is **also** ahead: the organic shape when a clock jumps forward and the
run under the jumped clock fails, which is what the retry logic exists for. Measured — after
the promised repairing run **succeeds**, the record is `due_date=today, last_success=now,
last_failure=2099`, and that record still answers `clock=ahead`, `due` still exits 1, and
`status` still prints the whole block. Permanently loud, not repaired. Scope the promise to
the half it is about; the code comment at `:530` already states the consequence correctly.

**B. The seventh, in the runbook's panel section** — `docs/deploy/runbook.md:1741-1747`.
*"And a **run** in the record dated ahead … the screen goes loud"* — the panel reads
`last_success` and `last_failure` only, so a record whose `last_attempt` alone is ahead is
`FRESH` with no banner. The paragraph's qualifier corrects the wrong axis, and the true
statement sits 85 lines away where a reader of that section has no reason to go.

**C. Five sentences M28.20 made false by teaching the panel to read `due_date`.** All were
true before it and are wrong now:
- `scripts/backup-run.sh:393-395` — *"`_ahead` never reads `due_date` … these two verbs are
  the ONLY channels that say anything"*;
- `scripts/backup-run.sh:475` — *"The panel does not read the due date at all, so this may be
  the only place this half is said."* **This one is printed to an operator** by `due` and
  `status`;
- `docs/deploy/runbook.md:1831` and `:1836` — the same claim, twice;
- `tests/infra/test_what_the_command_line_may_say_about_a_backup.py:333-334` — *"The second
  shape is the one the panel cannot see at all"*. A comment, so the suite stays green, which
  is exactly why it will not be caught by running anything.

Also check `docs/decisions.md:156`'s closing clause, which states the old behaviour as
current fact.

**Two more, found by the reviewer sweeping rather than by reading the diff**, and in neither
the implementer's list nor this step's first draft:
- `scripts/lib/backup-record.sh:22-25` — *"the panel goes loud only when a RUN TIMESTAMP is
  ahead … so a record whose due date alone is ahead draws no CLOCK banner at all"*. False now
  above the grace, and it needs the same conditional wording §C asks for everywhere else.
- `scripts/lib/backup-record.sh:131-133` — *"THE SCHEDULE'S OWN THREE — `due_date`,
  `attempts`, `retry_not_before` — … The panel does not read them at all"*. The premise is
  now false for `due_date`. **The conclusion still stands but for a different reason** — the
  panel reads it *leniently*, so validating it here would still refuse a file the panel reads
  happily. Write the reason that is true, not the one that was.

And one partial: `docs/deploy/runbook.md:1745-1747` (*"A **run** and not the record's
`due_date`, which this screen does not read at all"*) sits inside the paragraph §B already
claims for a different defect. **It is falsified by M28.20 as well**, so if §B is fixed
without §C's wording in hand, this clause survives the edit. Fix them together.

**The correct new wording has a condition in it, so write it carefully.** The panel now sees
a due date ahead by **more than a day**; `DUE_AHEAD_GRACE` is one whole day because the writer
resolves the due date in the schedule's zone while the panel has only UTC, and inhabited zones
span UTC−12…UTC+14. So the **timezone-moved-west shape is still invisible to the panel** and
the command line really is still the only channel that sees *that* one. The old sentences are
not simply wrong; they are right about the case an operator is most likely to hit and wrong in
general. Say both halves, and name the states.

**D. One more negative assertion over wrapped output without `flowing()`** —
`tests/infra/test_what_the_command_line_may_say_about_a_backup.py:383`. It fires today only
because the phrase happens to fit on one source line; re-added across a line break it would
pass silently. The rest of `tests/infra/` and `tests/e2e/infra/` was swept and this is the
only other one.

**E. The audit's seam list reads as exhaustive and is not.** Three further spellings walk the
whole sweep out, measured: `. "${REPO_ROOT}"/scripts/lib/a.sh` (quote closed after the
variable), `. ${REPO_ROOT}/scripts/"lib/a.sh"`, and two `source` statements on one line (the
pattern is anchored at `^\s*`, so only the first is found). None is written in this tree
today — which is precisely the argument made about the braceless form one round earlier, and
that one turned out to matter. Fix them or name them; the plan's standing rule is that a seam
is never left both unfixed and unlisted.

**The discipline, which is the actual deliverable.** Every sentence written or edited here
**names the state it holds for**. When narrowing one, **sweep the tree for it** rather than
reading the diff — two extra copies and a whole further instance were found that way in
M28.19. Check each against behaviour actually run, not against the code as read.

Gate: `make test-infra`, then `make verify`, and **the e2e half must stay 224 passed / 0
skipped**.


### M28.22 — `control`: the panel's own sentences, and the rule its parser no longer follows · 2026-09-24

The `control` half of M28.21, split because `CLAUDE.md` does not let one diff cross zones.
Five sentences, and **four of them no test in this repository could catch** — which is the
point rather than an excuse.

1. **`console.py:1072-1074`, its docstring `:1034-1036` and its comment `:995-999`** — *"the
   run times … are printed here exactly as the record has them"* and *"agree with
   `make backup-status` to the minute"*. **The panel never prints the record's times.**
   `_ago`/`_how_long` print a coarse age: rendered over a record holding
   `2026-09-23T08:00:00Z`, the screen says *"Last backup 4 hours ago"*. The sentence is true
   of `make backup-status`, which prints the ISO timestamp, and was carried to the channel
   that prints ages. **It was introduced by M28.20's round-1 fix** — a new instance, not a
   reversal. Say what this screen does: the ages beside it are worked out from times this
   panel has no reason to doubt.

2. **`console.py:1085-1086`** — *"A clock that moved on that host **is what** leaves a record
   like this behind"*. Names one cause exclusively where four are possible: the hand-seeded
   shape, a moved clock, a hand edit, a record carried from another machine. **This is not
   M28.20's round-1 finding returning** — that named a cause the grace makes *impossible*;
   this names a *possible* cause as if it were the only one, and sends an operator whose
   record was hand-edited to check a clock that is fine. Narrow the verb and keep the
   contrast: the load-bearing half is *"and a timezone cannot"*, which survives any fix.

3. **`backups.py:145-148`** — *"every host scheduled east of UTC … ten hours out of every
   day"*. Ten hours is right for UTC+14 at 04:00 local; a host at UTC+1 resolving 04:00 local
   writes a due date equal to the UTC date and would never be flagged. **The argument for
   `DUE_AHEAD_GRACE` is untouched** — only the scope of the sentence overstates. Do not
   weaken the constant.

4. **`tests/control/test_a_backup_that_has_been_failing_says_so.py:697-698`** — the module
   rule *"silent about keys it does not read, strict about keys it does"*, falsified by
   M28.20 in the very file that states it. `due_date` is now a key it reads and deliberately
   is **not** strict about, proved 350 lines below by that step's own tests. **The risk is not
   cosmetic:** a later reader "finishing" the parser on the strength of that rule reopens the
   two-channel defect M28.18 closed. State the exception where the rule is stated, and say
   why — the shell does not validate that field either.

5. **`docs/tracker/M28/step-notes.md`, two entries** (this file belongs to no zone and is in
   reach):
   - `:1598-1600` — the M28.20 residue note lists *"a host clock that jumped back by a day or
     more"* among the shapes now caught. Measured against the real `_due_ahead`: back 24 h →
     False, 36 h → False, 47 h → True. The grace is **strictly** more than a day. Overstated
     twice over, since a backward jump also leaves the run timestamps ahead and is already
     loud via the run half. **This is the milestone's own defect class landing in the place
     its close-out reads from**, on the exact boundary the note is about.
   - `:1447-1449` — M28.18's *"`_parse` does not read them at all"*, now false for
     `due_date`. M28.21 §C lists the identical sentence in `scripts/lib/backup-record.sh` and
     missed this copy. The conclusion still holds for a different reason: the panel reads it
     **leniently**, so validating it in the shell would still refuse files the panel reads
     happily. **Write the reason that is true, not the one that was.**

**While you are here, adopt the form the reviewer argued for**, since this file is where it
was demonstrated. The strongest assertion in M28.20 is a **biconditional** —
`assert (PHRASE in detail) is (standing is not NEVER)` — which fails in both directions and
writes the sentence's state down executably. Convert the presence-only pins on the clauses you
touch, and **pin by constant reference** (`console.BACKUP_CLOCK_OPENING`,
`BACKUP_CLOCK_RUN_AHEAD`) rather than by a literal: a literal in a test is a second copy of
the sentence, and two copies never disagree even when both are wrong.

**Two corrections carried from M28.21, and both matter more than the items above.**

**First, a sentence in M28.21's own text was wrong and it was mine.** §C said the moved-west
shape is *"exactly one day ahead"*. Measured organically, the record that shape produces was
**zero** days ahead of the panel's UTC date — the offset depends on the hour. M28.21 therefore
writes **"no more than a day"** / **"more than a day"** everywhere, and so must this step.
**Never write "exactly one day."** The boundary, measured: the panel is loud iff
`due_date > (its own UTC date + 1 day)` — one day ahead is False, two days is True. That this
error was written into the plan by the orchestrator, in the step whose subject is exactly this
class, is the clearest example the milestone has produced: a true observation about one
instance, written as a generalisation.

**Second, two sentences that look like this defect and are NOT — do not touch them.**
M28.21's implementer checked both and they are true; turning a true sentence false is the same
defect in reverse:
- `control/app/services/console.py:1006` — *"the last ATTEMPT is a run too and this panel does
  not read it"*. `_ahead` reads `last_success` and `last_failure` only, so this holds.
- `docs/tracker/M28/step-notes.md:1605` — *"`due` and `status` remain the only two channels
  that see that half"*, where "that half" is the moved-west shape the panel is silent about.

**A third step-notes line, and it is the surviving copy of my error** —
`docs/tracker/M28/step-notes.md:1603`: *"It leaves a due date **exactly ONE day ahead**"*. It
sits **two lines above** `:1605`, which this brief tells you not to touch, so it is the one
most likely to be skipped. Measured at UTC 13:57 with `AT=04:00` it is **zero** days ahead.
Fix it with the rest of item 5.

**And the measurement for item 3, so you do not have to take it on trust.** Counting the UTC
hours per day at which a zero-grace comparison would fire, `AT=04:00`: `Europe/Berlin` (+2)
**0/24**, `Europe/Moscow` (+3) **0/24**, `Asia/Tokyo` **5/24**, `Pacific/Auckland` **8/24**,
`Pacific/Kiritimati` **10/24**. So it is neither *every* host east of UTC nor a *standing*
banner. Write the numbers; the argument for `DUE_AHEAD_GRACE` is untouched by the correction
and **the constant must not move.**

Item 5's two step-notes entries remain wrong and are still yours. Check every sentence you
touch against behaviour you run, including the ones this plan tells you are broken — this
plan has been wrong once already.

**Do not add a pin to any sentence naming a cause, a mechanism or another channel's
behaviour.** Nothing in this repository determines those, so such a pin can never go red — it
converts an unverifiable claim into a green tick, which is how item 1 of M28.20's review came
to be load-bearing.

Gate: `make test-control` with a real Postgres — report the skip count, the real number is
~992/2 — then `make verify`, with the e2e half at **224 passed / 0 skipped**.


### M28.23 — WITHDRAWN 2026-09-26, folded into the accepted prose debt · was: `infra`, what M28.21 left open at its round cap

**Not built, and the reason is the same judgement that closed M28.22's prose work.** Every
item below is a sentence in a comment, a tracker note or a runbook paragraph. None changes
what the product does. Two consecutive cleanup steps hit their round cap by removing several
such sentences and writing two or three new ones, and at fifteen instances the trade has
stopped paying: the risk being bought down is a reader misled by a comment, and the price is
measured at two or three fresh instances per step.

It is recorded in `docs/tracker/M28/carry-over.md` as debt, with the standing recommendation
for whoever takes it: **delete rather than refine.** These sentences explain gates that are
already pinned by biconditionals failing in both directions; the explanations are pinned by
nothing and cannot be.

The items, kept here so the debt is legible:

#### The original text — M28.23 — `infra`: what M28.21 left open at its round cap, and the counts that keep being wrong · 2026-09-25

**M28.21 stopped at its round cap with three Highs open.** Its code is clean and gated — the
seven sentences it was written for are fixed and every behavioural claim was re-derived by
measurement in both rounds — but the fixes themselves wrote new prose, and that prose is what
is open. This step takes it, plus one correction M28.22 found in text this plan repeats.

**A. A claim that the code lacks something it has.** Both
`tests/infra/test_what_the_command_line_may_say_about_a_backup.py:195-196` and
`docs/tracker/M28/carry-over.md:324-326` say the sibling module *"has no `flowing()` at all"*,
and the carry-over builds an action item on it — *"widening it belongs with whichever step next
touches that file"*. But `tests/infra/test_the_command_line_says_what_the_panel_says.py:75-82`
defines **`flat(text)`** — the same whitespace collapse plus a concat-seam strip — and already
uses it at `:325`. Literally true of the *name*, false about the code, and it mis-scopes the
work it hands on: nothing needs widening, the open assertions need only call the helper sitting
160 lines above them.

**B. The count is wrong again, in the entry whose own thesis is that the count keeps being
wrong.** It says *"there are three, not one"*. There are **four**:
`test_the_command_line_says_what_the_panel_says.py:1137` — `assert "No backup has ever been
recorded on this host" not in result.stderr` — is byte-identical in phrase, source and shape to
`:235`, which the entry does list. Both target `scripts/backup-run.sh:1019`. The entry's own
instruction, *"sweep for the SHAPE, not the phrase"*, was not applied to the module it was
written about.

**Use M28.22's reframing here, because it is what makes these counts tractable:** **count
assertions, not occurrences.** A phrase surviving inside the correction that replaced it, or
inside a quotation of the defect, is not an instance. Three published counts in this milestone
have been wrong by counting occurrences.

**C. A fix for a Low that is false in a first-class state.** `docs/deploy/runbook.md:1748-1750`
now says a record's standing is *"answered by the age of its runs: recent ones read as fresh"*.
Measured against `_judge`: it is answered by the age of the last success **and** whether
anything failed after it. A record whose runs are all recent but whose `last_failure.at >
last_success.at` is `FAILING`, `loud=True`. `_judge`'s own docstring says so, and the same
runbook section already lists *"backups are failing"* among the six standings.

**D. A measurement this plan and the carry-over both repeat, which is hour-dependent.** Both
state *"back 24 h → False, 36 h → False, 47 h → True"* for a clock that jumped backwards.
Measured across all 24 hours by M28.22: 24 h → loud at **0** of 24, 36 h → **12**, 47 h →
**23**, 48 h → **24**. **Write the date-boundary rule, not an hours figure** — and note the run
half already carries that shape, since such a record also has `success_ahead=True`.

**E. Two Lows from M28.21's second round.** The `WHAT IS LEFT RAW` enumeration reads as
exhaustive and omits the planted-secret assertion at `:147` — correctly raw, since a
runtime-interpolated value cannot be split by re-wrapping source. And its example for "a phrase
that is a whole heredoc line of its own" names a phrase no assertion in that file targets; the
real instance there is `:618`'s `"DATED AHEAD"`.

**The method, which is the deliverable.** Every sentence names the state it holds for. Where
one carries a number, **state the conditions it was measured under** — the east-host figures
hold at `AT=04:00` and move with the schedule hour, and item D exists because an hours figure
was published without its hour. Sweep the tree for a claim rather than reading the diff. Check
each sentence against behaviour actually run.

**Do not widen `flowing()` into the sibling module.** Item A's point is that the module already
has `flat()`; the three open assertions there are for whichever step next touches that file.

Gate: `make test-infra`, then `make verify`, with **e2e 224 passed / 0 skipped** reported
explicitly.


### M28.24 — `control`: a gate test whose expected side is a false equivalence · 2026-09-26

**The one finding from M28.22's cap that is not prose.** Two items, both about whether a test
means what it says.

1. **`has_a_run = standing is not backups.Standing.NEVER` is false.** `Standing.NEVER` means no
   backup ever **succeeded**, not that no run exists — `backup_standing` has a
   `case Standing.NEVER if reading.failed_since` branch printing *"The last run was 6 hours
   ago…"*. Measured: `last_success: null`, `last_failure` 6 h old, a due date far ahead →
   standing `never`, a real age on screen, and `BACKUP_CLOCK_RUNS_UNDISTURBED` **is** said.

   So `test_the_run_times_clause_is_said_exactly_where_it_is_true` passes only because
   `_every_standing_with_a_record()`'s NEVER body happens to be the run-less shape, and its
   docstring's claim to sweep *"every state it could be said in"* is untrue. **Derive
   `has_a_run` from the body** (`body["last_success"] or body["last_failure"]`), not from the
   standing, and add the NEVER-with-a-failure body to the sweep.

2. **The mixed run-ahead state is unpinned on a ground that is factually wrong.** The reason
   recorded was that `_every_standing_with_a_record()` cannot reach it because no body carries
   both runs. It does: the FAILING body is `record(last_failure=run(1, …))`, which keeps
   `record()`'s default `last_success=run(6)`. Reaching the state needs one more value in the
   existing `runs_ahead` loop, guarded on the body having a failure — not a purpose-built
   record.

   **Pin it.** This milestone's record is prose and pins drifting from behaviour, and the
   gate's own justification was wrong about *precisely this state* one round ago. A state that
   is measured but unpinned is where the next edit reintroduces the defect.

**Do not rewrite the surrounding comments.** The over-general sentences beside this gate are
recorded as accepted debt in `docs/tracker/M28/carry-over.md` and are deliberately out of
scope — this step is about the test, not the prose. If a comment you touch becomes false
because of an edit you make, fix that one and say so; do not widen.

Gate: `make test-control` with a real Postgres — report the skip count, the real number is
~993/2 — then `make verify`, with **e2e 224 passed / 0 skipped** reported explicitly.


**Done when**
- [ ] A backup lands in the bucket every day without anyone touching it, and a run
      that does not land is visible where the owner already looks.
- [ ] On a machine that has never run this project, one command — given the key and
      read credentials for the bucket — produces a control plane serving the same
      users and driving the same nodes as the one that was lost.
- [ ] What a reader of the bucket learns **without** `HASHI_SECRET_KEY` is written
      down, and is either nothing or a recorded decision in `docs/decisions.md`.
- [ ] An attacker holding the control-plane box cannot destroy the backup history.
- [ ] The storage backend is configuration, not a hardcoded provider.
- [ ] `scripts/backup.sh:82` no longer claims the dump is encrypted.
- [ ] The restore has been **performed** on a bare host, not described.

acceptance: yes
Take a fleet with at least one node and one user, both working. Destroy the
control-plane box — do not stop it gracefully, take it away. On a genuinely bare
machine, with nothing but the repository, `HASHI_SECRET_KEY` and read credentials
for the bucket, run the one command. Then: log into the panel, apply the existing
node, and confirm the existing user's subscription still works on the device it
was already on. The walk fails if the operator had to read anything other than the
command to get there.

---

## → M36 — Losing the entry box costs two commands and a DNS change · asked for by the owner 2026-10-13 · built 2026-10-13 on `task/M36` · acceptance: walk on a local container stand (docs/tracker/M36); the real-host walk is the owner's

**Why.** On 2026-10-13 the box carrying the control plane and the entry node died. The
rebuild onto a fresh Ubuntu took a dozen hand-typed steps: docker and make by hand, the
code by `git archive`, the restore with secrets staged by hand, a refused bootstrap
(fresh Ubuntu's ufw logs), a management-tunnel block commented out by hand (the bootstrap
would have printed new device keys for the dead endpoint), an account named after the
dead box re-created on the new one, a raw `UPDATE nodes` (the record's SSH host, account
and host-key pin could not be changed, and the trail never saw it), an apply driven with a
cookie jar, and the backup schedule reinstalled by hand. The owner: one command for the
panel, one for the first hop, a sensible node account, "only two commands and DNS".

**Steps.**
1. *(control)* `services/relocation.py`: `relocate_node` (ssh host/user/port, optional
   address, the pin always replaced, audited `node-relocated` by name; returns the nodes
   to apply — the entries dialling a leaf whose address moved) and `host_plan` (the
   record's public key, the ports an apply will bind). `POST /api/nodes/{id}/relocate`.
   `control.cli node-plan | relocate-node | apply-node`.
2. *(infra)* `make node-plan | node-relocate | node-apply` on the control-plane host;
   `make restore-panel HOST=` and `make restore-node NODE= HOST= [ACCOUNT=hashi] [PANEL=]`
   from the operator's machine (`scripts/restore-panel.sh`, `scripts/restore-node.sh`,
   `scripts/lib/remote.sh`); `restore-from-bucket` skips the management tunnel
   (`PANEL_SKIP_MGMT_TUNNEL=1`). Runbook cheat sheet: switch DNS, two commands; the
   console URL over `ssh -L` is `https://127.0.0.1:PORT/panel/`.

**Done when.**
- [x] `make restore-panel` on a bare Ubuntu 22.04 container stand (systemd, sshd, ufw
      logging low, no docker, no make) restores the newest backup from an S3 bucket,
      shreds the identity, publishes over SSH, takes a backup, installs the schedule and
      prints the `ssh -L` line; the console answers on `https://127.0.0.1:PORT/panel/`.
- [x] `make restore-node` on the same stand creates `hashi`, bootstraps, relocates
      (audited `node-relocated`), pins the host key it read and applies the node to
      `active`, serving.
- [x] A re-run of either changes nothing that matters (no second restore, "nothing to
      move"); a name that does not point at the host stops before publishing.
- [ ] The delivery probe's success path (a public CA's certificate) — the stand uses
      `localhost`, where no CA issues, and reports "not verified" (exit 3) as designed.
- [ ] The owner's own run on a real host, from a real DNS change — not done here: both
      real hosts are serving users and are not touched by this milestone.

**Not covered, and never claimed:** that a tunnel carries traffic from Russia (a field
observation), and a public CA issuing for the real name (the stand uses `localhost`).

## → M35 — Russian destinations bypass the tunnel on the user's device, by rules the subscription delivers · asked for by the owner 2026-10-03 · PROPOSED · **DEFERRED by the owner 2026-10-03** (not now; the owner's phone uses a hand-added V2Box rule meanwhile)

**Found on 2026-10-03, on the owner's phone, right after the fresh install.** With M34 on,
the Ozon, hh and Gosuslugi apps still said "you are using a VPN". The cause is the
**address** the request arrives from:
- M34 (server-side) sends a listed destination out of the entry. Gosuslugi therefore sees
  **a Yandex Cloud data-centre address**, which these services treat as a VPN.
- Ozon and hh are not on the narrow list, so they see **the leaf's Dutch address**.

**Measured on the owner's phone.** The owner added one routing rule by hand in V2Box,
`domain:ru`, `domain:su`, `domain:xn--p1ai` → **Direct**. Those apps then reach the
service from **the phone's own mobile address**, and they work. The owner's earlier
AmneziaWG setup with on-device routing worked for the same reason.

**What this changes in M34's settled shape.** M34 chose server-side routing so that no
client needs a profile. For apps that judge the address, that is the wrong place: only the
device can make a request leave from the user's own address. M34 stays as the path for a
client that cannot take rules. Record the reversal in `docs/decisions.md`. Do not rewrite
M34's rows.

**What to build (shape to settle in the first step)**
- **VLESS clients:** the subscription carries a routing profile that the common iOS and
  Android apps apply without the user touching it. Find out per app (Happ, V2Box,
  Streisand, Hiddify, v2rayNG) what each accepts. Candidates: a full Xray JSON
  subscription with `routing`, Happ's routing header or deeplink (the format
  `hydraponique/roscomvpn-routing` publishes), and the sing-box `route` block. The rule is
  the owner's: **Russian zones (`.ru`, `.su`, `.рф`) plus the M34 lists → direct on the
  device**, everything else → proxy. Prefer domain rules that need no geo database. A
  client that lacked its `geoip`/`geosite` file would not start, and the owner's first
  attempt showed what that costs: no internet at all.
- **AmneziaWG config files:** `AllowedIPs` that leaves out Russian networks, aggregated to
  a size the iOS and Android apps accept. Measure that limit; a list too long is refused
  or slow. Or document AmneziaVPN's split tunnelling as the route, if the file cannot carry
  it.
- **Panel:** one switch per user-facing transport, "Russian destinations bypass the
  tunnel on the device", plus the owner's always-direct and never-direct lists from M34,
  so both places use one source of truth.
- **Charter and privacy.** The bypassed traffic leaves from the user's own address, which
  is exactly what these services demand. It is visible to the user's ISP **without the
  tunnel**, so the switch says so. Nothing is logged, as in M34.

**Done when**
- [ ] A fresh user imports only the subscription link into each supported app. Ozon, hh
      and Gosuslugi open without a VPN warning, and `ifconfig.me` shows the leaf.
- [ ] An app that cannot take rules still works as before, through M34.
- [ ] A client given a profile it cannot parse is never left with no internet. Test the
      failure the owner hit.
- [ ] The AmneziaWG file route is either working or documented as the app's own setting,
      with the measured limit stated.

acceptance: yes — the owner's phone on a Russian mobile network, with each supported app.

---

## ✅ M34 — Sites that only open from Russia leave from the entry, not through the hop · asked for by the owner 2026-10-03 · built 2026-10-03 on `task/M34` · acceptance: yes (a real-host walk, run by the orchestrator, then the owner's phone on a Russian mobile network — not by the implementer), PENDING · **CLOSED by the owner 2026-10-03** — the real-host walk passed; the owner's own phone check was not done before closing

**What the owner wants.** On the VLESS path (phone → entry → hop → leaf), traffic to sites
that refuse foreign addresses (state services, banks, …) leaves directly from the entry's
Russian address. Everything else goes through the hop as today. The lists come from public,
automatically released sources and are refreshed by themselves. The owner adds their own
entries, switches the feature on and off at any time, and can see which entries are in effect.

**Shape, settled with the owner on 2026-10-03.**
- **Server-side, on the entry's Xray, not on the client.** Xray already sees each
  connection's destination (SNI, IP) and picks an outbound by rule, so no phone needs a
  routing profile. That keeps "a user never touches their device" true. Rejected: shipping
  rule files to clients for every engine, which a known operator does — more formats, more
  places to go stale, and the subscription becomes app-specific.
- **NARROW by default (owner's choice):** only destinations that do not open from abroad go
  direct. Rejected as the default: the broad "every Russian site" (`geosite:ru` +
  `geoip:ru`), which puts far more traffic on the entry's own address.
- **Sources are configuration, not code** (CLAUDE.md: no hardcoded domain). The defaults
  offered in the panel are `itdoginfo/allow-domains` (`Russia/outside-raw.lst`, also
  published as `geosite:russia-outside`), `hydraponique/roscomvpn-geosite` and
  `roscomvpn-geoip`, and `runetfreedom` (refreshed every 6 h). Read each source's licence
  and format before relying on it.
- **The control plane fetches, never the node** (control → node, always). If a source is
  unreachable (for example GitHub behind a whitelist), the last good version stays in force.
- **Updates apply by themselves, at night (owner accepted).** Applying restarts Xray, which
  drops connected users for 1–2 s, so it runs in the same quiet hour as the backup. **A
  suspicious change waits for the owner**: a source that grows or shrinks by more than a set
  ratio, fails its format check, or changes past a size bound is held with its diff shown,
  and is not applied.
- **DNS (owner accepted):** names that go direct are resolved by a Russian resolver, so they
  get the answers a Russian client gets. Every other lookup stays on the hop (M16). The
  resolver is node data, never hardcoded.
- **The owner's own lists:** *always direct* adds entries. *never direct* forces entries
  through the hop even when a source lists them, and it wins over everything.

**What the panel shows.** An on/off switch per entry. A "Routing" screen listing each source
with its last fetch, version, entry count and diff since the last fetch, plus the two owner
lists. A lookup ("where would `example.ru` go?" → "direct, from <source>"). **No statistics
of use**: no hit counters, no "top sites", nothing about which user went where. That is the
charter's one hard record, and this feature must not become the first thing that keeps it.
The screen shows the lists, never their use.

**What it does not do.** It changes nothing for config-file (AmneziaWG) users, whose tunnel
goes straight to the leaf. Traffic to a listed site carries the entry's address, not the
leaf's. That is the point of the feature and also its cost, so it is stated on the switch.
**A side effect worth keeping:** while the hop is down, listed sites still open.

**Open before building — answered 2026-10-03 (docs/decisions.md, the eleven M34 rows).**
- *No `if transport ==`*: a transport DECLARES it can split (`TransportMeta.splits_by_destination`);
  `control` hands `direct=` only to one that does. The lists reach `edge` as plain canonical
  values (`edge/direct.py`); rendering stays pure.
- *Where the versions live*: four tables in the control database (migration `0011`), and so in
  every backup — deliberately (the owner's own entries exist nowhere else; a restored control
  plane behind a closed border needs the last good lists).
- *The charter*: no conflict; the one widening (listed sites see the entry's address) is the
  feature and is said on the switch.

**Steps**
- **M34.1 (edge)** — `edge/direct.py`; the declaration; both Xray transports render never →
  direct → hop, direct names looked up at the entry-side resolver. Golden files from `ecd15c5`
  prove "off" byte for byte; a live harness runs the rendered file in the pinned Xray.
- **M34.2 (control)** — models + migration `0011`; `services/routing.py` (parse, fetch, hold,
  approve/reject, owner lists, the switch, render data, lookup, screen);
  `services/routing_refresh.py` (nightly run in the backup's hour, "fetch now"); the Routing
  screen, the Nodes screen's "direct sites" dialog; seven audit actions.
- **M34.3 (infra)** — the backup hour and the routing settings passed into the control
  container; the suggested sources as a compose default; `.env.example`; an e2e scenario.
- **M34.4 (docs)** — decisions, this section, the runbook ("Sites that only open from Russia"),
  `docs/tracker/M34/`.
- **M34.5 (control)** — **two wording defects found in the real-host walk** (2026-10-03).
  The Routing screen's failed-fetch row read "The version in force is less than an hour ago
  old": `routing.age` ("… ago") was pasted into "is … old" by the template. The sentence is
  now composed whole (`routing.in_force_sentence`; "No version of this list is in force yet."
  when there is none). And the Nodes screen said delivery was "not served from any host:
  this control plane holds no delivery certificate" on the co-located box, whose control
  plane was delivering every link at its public name — read as "users cannot fetch links".
  The sentence (M27.6's) and its two siblings (expired, unusable certificate) now say that
  no node runs a refresh listener of its own and that this control plane serves refreshes
  at `<public base URL>/sub/…`. Tests fail on the old text (8 red before).

**Real-host walk (orchestrator, 2026-10-03)** — `docs/tracker/M34/carry-over.md` items 1–9
PASS: "off" byte-identical on the real host; `showip.net` → entry address, `ifconfig.me` →
leaf address, `gosuslugi.ru` 200; never-direct wins; hop down → listed sites still open,
others time out; switch off → digest back to the pre-switch value; a fetch failure keeps the
last good version; nothing recorded in logs, tables or audit. Item 10 (the first nightly run,
due 2026-10-04 04:00 Europe/Moscow) not yet observable. The phone check on a Russian mobile
network is pending the owner.

**Done when** — what this branch proves, and what only the real hosts can
- [ ] With the switch on, a listed site opened from a phone sees the entry's address, and an
      unlisted one sees the leaf's. With it off, both see the leaf's. *Built and measured on
      loopback against the pinned Xray (which address a connection leaves from, and which
      resolver a name is asked at); "off" is byte-identical to the pre-M34 render. The phone
      half is the walk's.*
- [ ] An entry on *never direct* goes through the hop even when a source lists it. *Measured
      on loopback, by name and by address; the walk repeats it on a real listed site.*
- [ ] A nightly refresh that changes a source is applied without the owner. One that trips
      the bounds is held, with its diff shown on the Routing screen. *Built and tested with
      the fetch replaced; the first real night is the walk's.*
- [ ] Every source unreachable → the last good lists stay in force and the screen says how
      old they are. *Tested; the walk can block the list host on the control box to see it.*
- [ ] Nothing records which user reached which destination: the logs, the database and the
      screen are checked for it. *Asserted on the config, the schema, the captured logs and the
      lookup; the walk reads the entry's container log and the control log after use.*
- [ ] Hop down → listed sites still open, everything else stops (no silent fallback).
      *Measured on loopback with the hop's address gone; the walk stops the hop for real.*

acceptance: yes — on the real hosts, from a phone on a Russian mobile network.

---

## ✅ M33 — The owner reaches the panel from any of their devices without `ssh -L` · asked for by the owner 2026-10-03 · code and docs built 2026-10-03 on `task/M33` · acceptance: yes (the real-host walk, run by the orchestrator — not by the implementer), PENDING · **CLOSED by the owner 2026-10-03** — the real-host walk passed; the owner's own phone check was not done before closing

**Why.** Today the console is reachable only through `ssh -L` from a laptop. The tunnel
drops when the laptop sleeps or changes network, and a phone cannot reach the panel at all.
The owner remembered correctly that this was already designed: M7 built a management tunnel
(`scripts/management-tunnel.sh`, decision 2026-09-09) — obfuscated AmneziaWG, one client
config per device listed in `HASHI_MGMT_PEERS`, no forwarding and no NAT.

**What is missing is the switch, not the feature.** The 2026-10-02 install left the
`HASHI_MGMT_*` block at the template's values, so `make panel-bootstrap` deliberately
generated no tunnel and the stack was published with `make up-panel-over-ssh`.

**Also found and not yet understood:** the RU test host still carries an `awg-mgmt`
interface at the private address from the 2026-09-09 deployment. Nothing in the current
install created it. Find out what keeps it up, and either adopt it or remove it — two
tunnels answering on one address is not a state to leave a host in.

**Found switching it on, on the real host (2026-10-03).** Seven findings, each a gap
between the script, the runbook and a host that has to keep working: a re-run kept an old
host file whatever `.env` now said; the runbook's `awg-quick up ~/...` "as root" pointed at
`/root`; nothing survived a reboot, and the missing interface then failed the whole Caddy
container — the public delivery endpoint with it; removing a device from the list removed
nothing; adding one did not say how to load it; configs came out in the SSH stream with an
em dash a QR decoder misread; and an old port's firewall rule was nobody's to remove. The
code-and-docs half (M33.5) answers all seven; the walk below is what proves it.

**Steps**
- M33.1 — Decide the device list with the owner (at least laptop and phone) and fill the
  `HASHI_MGMT_*` block for this deployment; open its UDP port in the host firewall.
  *(done on the real host by the orchestrator, 2026-10-03)*
- M33.2 — Re-run `make panel-bootstrap` and move the stack to `make up-panel`; hand each
  device its config once. *(walked on the real host; the findings above came out of it)*
- M33.3 — Resolve the leftover `awg-mgmt` interface (above). *(orchestrator, on the host)*
- M33.4 — Adding or removing a device later is a re-run with one entry more or less: walk
  it, and make the runbook say so. *(runbook: done in M33.5; the walk: orchestrator)*
- M33.5 — **built on `task/M33`** (code + docs, no host touched).
  `scripts/management-tunnel.sh` converges the host file's peers to `HASHI_MGMT_PEERS`
  (removes unlisted ones and says so, keeps listed keys, refuses a listed device whose
  address changed); refuses a host file whose Address/ListenPort/MTU disagree with `.env`,
  naming both values and the retire sequence; writes device configs to private files with
  `--configs-to` / `HASHI_MGMT_CONFIGS_TO`; prints ASCII-only configs; and prints the root
  commands with the real path — `/etc/amnezia/amneziawg` symlink, `ufw`, `ip_nonlocal_bind`,
  `systemctl enable --now` / `reload awg-quick@awg-mgmt`. Runbook: "Bringing it up, and
  keeping it up across a reboot", "Adding or removing a device", "Starting the tunnel over".
  Three rows in `docs/decisions.md` (2026-10-03, M33). What the walk must check:
  `docs/tracker/M33/carry-over.md`.

  Gate: infra 577 passed; control 1148 passed / 2 skipped (throwaway Postgres; includes
  M32.4); edge 968 passed / 14 skipped / 3 failed (the known environmental cases in
  `test_upstream_validation.py`); `make e2e-verify` 231 passed / 16 skipped. Review:
  `reviewer-strict`, round 1, CLEAN. One low carried: peers are removed before new keys
  are generated, so a key-generation failure mid-run leaves the removals without the
  additions — a valid file, and a re-run completes it.
- M33.4 follow-up — **two real-host walk findings, fixed on `task/M34`** (no host touched).
  D1: re-running `make panel-bootstrap` to add a device — which the runbook said to do —
  converged a serving stack to the base compose file and took user delivery down until
  `make up-panel`. Now `make mgmt-tunnel` runs the generator alone and touches no
  container, and the runbook's device and start-over sections use it. D2: a changed
  `HASHI_MGMT_PORT` was refused with "nothing was changed" after the stack step had
  unpublished Caddy; the generator gained `--check` (every refusal, nothing written) and
  the bootstrap runs it before `compose up`. Decision row 2026-10-03 (M33.4). Tests:
  `tests/infra/test_a_device_change_keeps_delivery_up.py` (stub docker; three of four
  red before the fix) and two `--check` cases in `test_management_tunnel_script.py`.
  Walk to repeat: carry-over items 4–6 with `make mgmt-tunnel`, and `curl /sub/` from
  outside before and after each.
  Gate (with M34.5): infra 585 passed; control 1209 passed / 2 skipped (throwaway
  Postgres); edge unchanged (3 known env failures); `make e2e-verify` 234 passed / 16
  skipped. Review: `reviewer-strict`, round 1, CLEAN (two lows fixed).

**Done when**
- [ ] The owner opens the panel from the laptop and from the phone over the tunnel, with no
      `ssh -L` running. *(field)*
- [ ] Removing a device from `HASHI_MGMT_PEERS` and re-running takes that device's access
      away, and the other devices keep theirs. *(the script half is tested —
      `tests/infra/test_management_tunnel_script.py`; that the device actually loses the
      console after `systemctl reload` is field)*
- [ ] The `ssh -L` fallback still works, so a lost tunnel never locks the owner out. *(field)*
- [ ] Exactly one management interface on the host, and the runbook says which. *(runbook:
      `ip -brief link | grep awg`, one `awg-mgmt`; the host: field)*
- [ ] After a reboot of the panel host the tunnel is back and the delivery endpoint answers;
      with the tunnel deliberately stopped and Caddy restarted, delivery still answers.
      *(field — added by M33.5; the docker half was shown in a disposable dind only)*

acceptance: yes — on the real hosts, from the owner's own devices.

---

## ✅ M32 — Adding a user reaches the nodes by itself · asked for by the owner 2026-10-03 · built 2026-10-03 on `task/M32` · acceptance: yes (a real-host walk, run by the orchestrator after this milestone — not by the implementer), PENDING · **CLOSED by the owner 2026-10-03** — the real-host walk passed; the owner's own phone check was not done before closing

**Found on 2026-10-03, on the owner's own phone.** The owner added a user, imported the
link into a phone client and got a timeout. The user's UUID was not on the entry: adding a
user writes only to the database, and the node learns about it only on an apply. The panel
does say so — "Not yet pushed to …" on the Overview, "A user added here is not on … yet"
on the Users screen and in the link dialog — and the owner did not see it. In the link
dialog it is a grey (`text-muted`) paragraph under the link, which is exactly where the
eye does not go. **A warning the operator does not see is not a warning.**

**The asymmetry this removes.** Revoking a user already applies by itself
(`services/revocation.py` → `apply.apply_many`). Adding one does not, and nothing in
`docs/decisions.md` says why. Record the reversal as a decision.

**How it will work**
1. **Add → apply.** Creating a user applies every node where the user just got a
   credential, through `apply.apply_many`, the same fan-out revocation uses. The dialog
   shows progress per node, then a per-node result: `✓ entry-ru`, or
   `✗ leaf-ams — <reason> [retry]` with what the link does in the meantime. A node that
   could not be reached stays in every other user's link (M26 round 5).
2. **Several users at once.** Each apply restarts the daemon and drops connected users for a
   second or two, so the add dialog takes several nicknames (one per line) and applies once
   for all of them.
3. **Visible warnings, with the press inside them.** Manual apply is still needed after
   other changes (transport parameters, the decoy, the resolver). For those, the
   not-yet-pushed sentences become one short, coloured block — "<node> is still on the old
   configuration: your changes have not reached it" — with an **Apply <node>** button in it
   and the long text behind "details". Same block on Overview, Users, Nodes and the link
   dialog.
4. **Unchanged:** revocation, and the manual Apply button on the Nodes screen.

**Done when**
- [ ] A user added in the panel connects from a phone with no other press. *(Built: the
      add applies every node it granted on. Not proven — a phone connecting is a field
      observation, the orchestrator's real-host walk.)*
- [x] A failed node is named in the add dialog with its reason and a retry, and the user's
      link still works through every node that did take it. *(Tests: the row names the
      node and what to do from the failure's kind, offers a retry for an unreached or
      not-yet-serving node, and the node stays `active` and in every link.)*
- [x] Adding N users in one go applies each affected node once. *(Panel: one nickname per
      line; API: `POST /api/users/batch`. A test counts one session per node for five
      users.)*
- [x] After a transport change, the warning is visible without reading a paragraph, and
      its button applies the node it names. *(The block is drift-driven, so any change
      no apply has followed raises it; tested on the four surfaces with a user nobody
      pushed, which is the same reading. Its look on a real screen is for the walk.)*
- [x] `docs/decisions.md` records that adding a user now applies, and why. *(Four rows,
      2026-10-03.)*

acceptance: yes — on the real hosts: add a user, import the link on a phone, connect.

### What was built (2026-10-03)

- **Add → apply.** `services/onboarding.py`: `users.create_users` (one transaction,
  committed first) then `apply.apply_nodes` — the fan-out revocation uses, now callable
  by node id — over the serving nodes the add granted on. `POST /api/users` answers the
  user plus `complete`, `nodes_updated`, `nodes_failed`, `summary` (the revocation
  response's names); `POST /api/users/batch` `{"nicknames": [...]}` adds a list, all or
  none, each node applied once.
- **The add dialog.** One nickname per line. The answer hands every link over at once
  and lists the nodes; each node is applied by its own request (`POST /panel/reach`), one
  after another: "… entry-ru — applying; this takes up to a minute / then leaf-ams", then
  `✓ entry-ru — took the new configuration` or `✗ leaf-ams — <what to do> [retry]`. Under
  the rows, re-measured after each node: "Their link works through entry-ru now. It does
  not work through leaf-ams yet: …". Why one request per node rather than one long
  request: `docs/decisions.md`, 2026-10-03.
- **The not-applied block.** Overview, Users, Nodes and the link dialog draw one block
  (`panel/not_pushed.html`, from `console.NotPushed`): a steel-accent edge and ground, the
  label NOT APPLIED, the line "<node> is still on the old configuration: your changes have
  not reached it.", an **Apply <node>** button per node (it reads "applying <node>…" while
  in flight), and the long account behind "details". In the link dialog the block sits
  above the link and its button answers in place instead of closing the dialog.
- **A fan-out never degrades a serving node over a record that dialled nothing** (no SSH
  key) — found because the add's fan-out would otherwise have emptied links of such a
  node. Affects revocation too; recorded.
- **Unchanged:** revocation's own flow, and the Nodes screen's Apply button.

Gate: control 1145 passed / 2 skipped (throwaway Postgres); edge 968 passed / 14 skipped /
3 failed (the known environmental cases in `test_upstream_validation.py`); infra 557
passed; `make e2e-verify` 231 passed / 16 skipped. Review: `reviewer-strict`, round 1,
CLEAN; one low carried — no browser-level test pins the htmx include semantics the
per-node chain relies on (correct for the vendored htmx 2.0.4). What the walk must see:
`docs/tracker/M32/carry-over.md`.

### The real-host walk (2026-10-03, orchestrator) — PASSED, except the phone import

Passed: one add with no other press, and a stock client then exits at the leaf; a batch of
three, each node started once; an unreachable leaf gives `✗` with a retry, the leaf stays
`active` and in every link, and the retry turns it `✓`; the NOT APPLIED block on Overview,
Users and Nodes and in the link dialog above the link, both buttons working; the per-node
requests over the management tunnel and over loopback; closing the dialog midway leaves
the rest in the block; the API's single and batch fields; logs clean. **NOT PROVEN:** the
import on the owner's own phone — the owner's field observation, still pending.

Two wording defects **found in the real-host walk, fixed in M32.4** (`task/M33`, which
stacks on `task/M32`), each with a test that failed on the old text
(`tests/control/test_adding_a_user_reaches_the_nodes.py`, end of file):
- With more than one node pending the dialog read "…so a client that picks them gets no
  connection until **them is** applied." The subject now has its own placeholder: "until
  they are applied" / "until it is applied" (`console.LINK_NOT_YET_THROUGH`).
- A failed row read "✗ leaf-ams — 'leaf-ams' was not updated — …", naming the node twice.
  The row now renders the reason without its leading name
  (`onboarding.why_not_reached_after_its_name`): "✗ leaf-ams was not updated — …". The
  API's `summary` keeps the named sentence, where it is the only name.

---

## ✅ M31 — What the real-host field walk and the restore walk found on 2026-10-02 · asked for by the owner 2026-10-02 · built 2026-10-02, review clean in round 1 · acceptance: yes (a real-host re-walk, run by the orchestrator after this milestone — not by the implementer), PENDING · **CLOSED by the owner 2026-10-03** — the real-host walk passed; the owner's own phone check was not done before closing

**Asked for by the owner on 2026-10-02:** fix every defect the real-host field walk and the
restore walk found that day. Branch `task/M31`, stacked on `task/M26-fix-round-5` (not yet
merged to `develop`). Code, tests and a disposable stand only — **no real host is touched by
this milestone**; the re-walk that accepts it is a separate act.

Each step is one defect, in the owner's priority order: the command that was run, what was
observed, and what is expected instead. Each closes with a test that was red before it,
where the defect is testable at all.

### M31.1 — (high, infra) An unpublished stack must not ask a public CA for anything

`make restore-from-bucket` (and `make panel-bootstrap`) bring up the BASE stack, which
publishes no port. On the restore walk `/data/caddy/acme` already held Let's Encrypt and
ZeroSSL accounts, an `issue_cert_<host>.lock` and a ZeroSSL challenge token: Caddy started
public issuance for `HASHI_PUBLIC_HOST` the moment it booted. The runbook promises it asks
a CA only once the name resolves here and 80/443 are published. Every failed validation
counts against the live domain's rate limits — during a disaster restore, of all times.

**Done when**
- [x] The base stack's Caddy serves the public name from its own CA and asks no public CA;
      only the publishing overlay (`deploy/docker-compose.public.yml`, used by
      `make up-panel` and `make up-panel-over-ssh`) switches public issuance on.
- [x] A static test holds the Caddyfile and the overlays to that, and an e2e test asks the
      real Caddy which issuer each of the two shapes configures.
- [x] The runbook (DNS, "does not do" item 2) and the restore's closing screen say what is
      now true.

### M31.2 — (high, infra/control) `HASHI_FINDING_REMEASURE_INTERVAL` never reached the control plane

Set in `.env`, `env | grep` inside `control` showed nothing: the variable is not in
`deploy/docker-compose.yml`'s `control.environment`, which is the whole list of what the
control plane can read. `tests/infra/test_compose.py` has a rule for exactly this and did
not fire.

**Done when**
- [x] It is passed through, and documented in `.env.example` with what `0` means.
- [x] The rule that missed it is fixed so it would have caught it, and the reason it missed
      is written down.
- [x] A control plane restored from a bucket does not start dialling nodes on its own before
      the operator has published the panel — or, at minimum, the runbook says how to set
      the interval to 0.

### M31.3 — (high, control) An apply cannot repair a daemon whose config did not change

Remove the hop peer live on the leaf (`awg set <if> peer <key> remove`), then apply: 502,
"…pushed, but up and not serving … Probe it in a minute: a slow host often comes up just
after this wait ends." The digest had not changed, so `docker compose up -d` left the
container alone, and it went on not serving; only `docker compose restart <transport>` fixed
it, and the message pointed somewhere else.

**Done when**
- [x] An apply that finds a transport running the pushed configuration, refused by its own
      reading, in a container this apply did not restart, restarts that service once and
      measures again; the verdict is the second measurement's.
- [x] When that restart did not help, the message says so and does not send the operator to
      wait for a slow host.
- [x] The choice is a row in `docs/decisions.md`.

### M31.4 — (medium, control) The API cannot show a node's last probe finding

`GET /api/nodes` read `active`, `state_detail: null`, while the apply had just said "the
finding stays on its row" — it does, in `last_probe_finding`, which `NodeResponse` does not
carry.

**Done when**
- [x] `NodeResponse` carries the finding and when it was taken; a test reads it back after
      an apply that kept a node in service.

### M31.5 — (medium, control) `serving_unmeasured: []` for a transport nothing but its port can confirm

`vless-reality` declares no serving question, so it is confirmed by its held port and an
apply returns `serving_unmeasured: []` — while the schema says an empty list is the only
case where 200 means "pushed and measured".

**Done when**
- [x] The response says which configs were confirmed by their port alone, and the schema's
      contract says what an empty `serving_unmeasured` does and does not mean.
- [x] The choice is a row in `docs/decisions.md`.

### M31.6 — (medium, infra) A restore says nothing about what the artifact held

Restoring an artifact with 0 rows printed "The control plane is back, with the users, nodes
and tokens that artifact held." with no counts, so a backup older than the fleet looks the
same as a good one.

**Done when**
- [x] Every restore prints how many nodes and users the restored database holds, and says so
      plainly when that is none.

### M31.7 — (low, infra/docs) No `bash` on the host

`make restore-from-bucket` on a host without bash → `env: can't execute 'bash'`, exit 127,
before any prerequisite check.

**Done when**
- [x] The Makefile checks for bash before any target that runs one of the bash scripts, with
      a sentence naming it; the runbook's "What every box must already have" lists it.

### M31.8 — (low, infra) Two accounts of what to do after a restore

Mid-output: "Restart the control plane so it reconnects: make restart-control" and "the app
will say so loudly on first use"; the closing screen and runbook: one command does the rest
and a wrong key shows only in the panel. On the walk `/sub` served without a restart.

**Done when**
- [x] One account, true in both paths, said once by the script and repeated by the runbook.

### M31.9 — (low, infra) The restore names the wrong compose project

"compose project: <default: the directory name>" — the real project is `hashi` (`name:` in
the compose file).

**Done when**
- [x] The confirmation names the project the running database actually belongs to.

### M31.10 — (low, docs) Shape B: which account to register for an entry on the control-plane host

When the entry shares the host with the control plane and root key login is not wanted, the
runbook does not say which `ssh_user` to register. On the field walk `node-bootstrap --user
<account>` with passwordless sudo worked, and the control container reached the host by its
own public address.

**Done when**
- [x] Shape B says it, with placeholders and no real address or account name.

### What closed (2026-10-02)

All ten in code, each with a test that was red before it except M31.10 (docs). Gate: control
1118 passed / 2 skipped (throwaway Postgres); edge 968 passed / 14 skipped / 3 failed (the
known environmental `wireguard` cases in `test_upstream_validation.py`); infra 553 passed;
`make e2e-verify` 230 passed / 16 skipped. **Among the skips are the bucket-restore
scenarios (S13–S17, the minio image is not available here)** — so the restore-from-bucket
screen (counts, hold, restart) is proven statically and on the file-restore path only, and
the re-walk is the first run of it end to end. Review: `reviewer-strict`, round 1, CLEAN, no
medium or low findings. Details: `docs/tracker/M31/step-notes.md`; what the re-walk must see:
`docs/tracker/M31/carry-over.md`.

### Found in the real-host re-walk of 2026-10-02, and fixed

The orchestrator's re-walk of M31 and M24 on the real hosts found two low defects, fixed on
`task/M27.8` in commits tagged `M31.10 (infra)` and `M31.10 (control)` — the tag the
request named; they are not the M31.10 step above. Each has a test that was red before it.

- **(low, infra) The wrong-key sentence said twice.** `make restore-from-bucket` printed
  *"One thing no restore can check: whether HASHI_SECRET_KEY …"* word for word after
  *"Restarted the control plane…"* and again at the end of the closing screen — M31.8's
  done-when asks for one account said once. The bucket path now tells the restore a
  closing screen follows, and the sentence is said there only; a file restore, which has
  no closing screen, still says it.
- **(low, control) "Serves it once applied" on a row that was.** The Nodes screen's
  transports row for an `amneziawg` row already applied and serving still read *"the node
  serves it once applied"*. A row carrying its own `applied_at` now reads a sentence that
  says where the config-file link is and claims nothing about applying.

### Acceptance

**Yes — a real-host re-walk**, run by the orchestrator after this milestone lands, not by
the implementer. What it must confirm is in `docs/tracker/M31/carry-over.md`. Its item 8
names *Shape B*: since M27.8 that account's text is in the runbook's *Installing hashi*,
under *Prepare every other box* and *Register each box as a node*.

---

## ✖ M30 — The wildcard for delivery is issued by this control plane, not by hand · PROPOSED 2026-09-27 · dependency approved in principle by the owner 2026-10-02, none chosen · still PROPOSED, for the split arrangements only · **DROPPED by the owner 2026-10-03**: the co-located arrangement in use needs no delivery wildcard, and manual issuance stays the documented mode for anyone who splits the roles

**Deferred out of M27.6 on purpose, and the reason is `CLAUDE.md`'s own rule.** The owner chose
a wildcard issued by the control plane over DNS-01 and pushed on apply, because a per-host
certificate publishes every Russian entry's name in Certificate Transparency — public,
permanent, near-real-time. Everything downstream of issuance is built: the control plane reads
the pair from `HASHI_DELIVERY_CERTIFICATE_PATH` / `HASHI_DELIVERY_KEY_PATH`, distributes it on
apply, stands a listener down when it expires and takes the key off the host.

**What is not built is the issuance**, because DNS-01 needs either an ACME client library or a
Caddy rebuilt with a provider module, and **adding a dependency is an architect decision, not
an implementation detail.** The implementer raised it instead of adding it, which is what the
rule is for.

**So the shipped mode is: the operator obtains the wildcard and puts it at those paths.** Zero
new dependencies, works today. The cost is manual renewal roughly every ninety days — and
because a pushed certificate is renewed by an apply, the operator must also apply afterwards
or delivery stands down at expiry with the listener removed.

**Not needed for the arrangement the owner runs — an observation of 2026-10-02, not a
decision.** The owner runs the co-located arrangement, **C+E | L**: control plane and entry
on one box in Russia, several leaves abroad. There the host users refresh from is the
control plane's own `HASHI_PUBLIC_HOST`, served by its own Caddy under the ordinary
certificate Caddy obtains for that name, and by M27.4's predicate no node in that fleet is
a delivery host while no delivery certificate is configured (the shipped default, which
that arrangement never needs to change) — so no wildcard is pushed anywhere, issued by hand or by this milestone.
**It stays PROPOSED for the split arrangements** (C+L | E, C | E | L), where an entry answers
its own users' refreshes under the wildcard. The owner approved adding a dependency for it
in principle (`docs/decisions.md`, 2026-10-02) and has not chosen one, nor a DNS provider;
that choice gets its own row before `pyproject.toml` or an image changes.

**Done when**
- [ ] The control plane obtains and renews the wildcard itself, without the operator touching a
      file.
- [ ] The DNS credential lives only on the control plane — **never on a node**, because it can
      rewrite the fleet's records.
- [ ] The dependency this needs is the owner's decision, recorded in `docs/decisions.md` before
      it is added.
- [ ] Nothing in the issuance path publishes an individual delivery hostname; that is what the
      wildcard is for.

acceptance: yes
On a stand, with a test zone: let the control plane obtain a wildcard from scratch, push it,
and serve a subscription over it. Then let it renew one that is near expiry and confirm a
delivery host picks the new pair up on the next apply without an operator touching anything.

---

## ✖ M27 — The delivery endpoint cannot leave Russia with the control plane · asked for by the owner 2026-09-22 · scope broadened by the owner the same day: every arrangement of the three roles, on one, two or three machines · built 2026-09-26 to 2026-10-02 (27.1–27.7 and 27.9 merged to `develop` in PR #4; 27.8 on `task/M27.8`) · acceptance: yes, NOT WALKED — it needs real hosts in the C+L | E arrangement · **DROPPED by the owner 2026-10-03**: the owner keeps the control plane on the Russian entry. The built steps stay in the code, off unless a delivery certificate is configured. The real-host walk of the split arrangements will not be done

**Status, 2026-10-02.** Every step is built. 27.1–27.7 and 27.9 are on `develop` (PR #4);
27.8 — the runbook — is on `task/M27.8`, stacked on `task/M24`. What each step settled is in
`docs/decisions.md` (the 2026-09-26 and 2026-09-27 rows) and
`docs/tracker/M27/step-notes.md`; what is known to be wrong and was left is
`docs/tracker/M27/carry-over.md`. **The acceptance walk has not happened.** No real host has
run C+L | E or C | E | L, so nothing has shown an entry answering its own users' refreshes
while the control plane is out of reach. The co-located C+E | L was installed fresh on real
hosts on 2026-10-02 for M26, and refreshes there came from the control plane's own name
and certificate — but that walk was not this milestone's acceptance and did not inspect the
entry for delivery material.

The two sections below describe the product as it was when this was planned (2026-09-22).

### The coupling, stated plainly — as planned, 2026-09-22

`deploy/caddy/Caddyfile` serves the public site and the private site as two blocks
in **one** Caddy container, on **one** box. So `/sub/*` — the endpoint a user
refreshes a config from — lives wherever the panel and the database live. The
runbook admits it in one sentence at the end of *Shape C*: *"today you choose one
location for both."*

**That makes the location of the delivery endpoint a consequence of the location of
`HASHI_SECRET_KEY`, and those two want opposite countries.**

| | wants to be | why |
|---|---|---|
| `/sub/{token}` | **inside Russia** | its entire purpose is being reachable at the moment a node was blocked and a user needs a new config. A whitelist shutdown is exactly when it is needed and exactly when a foreign address is unreachable |
| `HASHI_SECRET_KEY` | **outside Russia** | it decrypts every user's credential and every node's private key, and `scripts/panel-bootstrap.sh:94` requires it in the env file on the host it installs |

Today the operator picks one and pays for the other:

- **Shape B** — control plane on the entry, in Russia. Refresh works under a
  shutdown. The master key sits on the most seizable machine in the fleet, beside
  the database it opens, which the runbook records as violating **the charter's own
  condition** for putting the panel inside Russia.
- **Shape C** — control plane abroad on its own box. The key is out of reach and
  the refresh URL is behind the border that just closed.

**The owner is running Shape B as of 2026-09-22, knowingly.** This milestone is what
makes leaving it affordable: without it, moving the control plane out of Russia
trades a seizure risk for a delivery outage, and that is not obviously a trade worth
making.

### The shape that does not work, recorded so it is not proposed again

**A reverse proxy on the entry that forwards `/sub/*` to the control plane abroad.**
It is the first idea everyone has and it fails twice:

1. It inverts the project's one directional invariant — *control plane → node,
   always; a node NEVER dials the control plane* (`CLAUDE.md`). A proxy on E
   dialling C is that, whatever it is called.
2. **It does not solve the problem.** Under a shutdown the proxy cannot reach C
   either, so the refresh fails exactly as before — with one more moving part.

The direction that already exists and already works is **control plane → node over
SSH, on apply**. Anything this milestone builds should ride it.

### Why this is worth building rather than living with

It is the one change that collapses a dilemma the charter cannot resolve and the
operator cannot avoid. Every other answer is a trade: this one gives the fleet a
refresh path that survives a shutdown **and** a master key that survives a seizure,
and it leaves the third box doing nothing but holding secrets — which is the only
job that actually wants to be abroad.

### Settled by the owner, 2026-09-22

**Real-host acceptance walks the two two-machine arrangements** — `C+L | E`, the
case that needs the work, and the co-located `C+E | L`, the case that fails if the
feature was built as a switch. The three-machine arrangement stays on the stand and
is **reported as unproven on real hosts**, not quietly counted as walked.

### M27.1 — Decide what travels, and how narrow the pushed artifact is

Two decisions that cannot be taken apart, because the second is the cost of the
first.

**What travels.** Rendering a subscription needs the database, so the endpoint
cannot move on its own. The candidate is: the control plane pre-renders each
user's subscription and **pushes it to the entry on apply**, where something small
and stateless serves `/sub/{token}`. Decide whether that something is Caddy, the
node stack, or a new thing — and whether it is a transport-like row or a property
of the node.

**And what is in it, which is the sharpest question in this milestone.** A
subscription does not name only the node serving it — it names **every node that
user may use**. Pushing rendered subscriptions to the entry therefore puts the
fleet's leaf addresses on the box most likely to be seized, which the current
design deliberately never does: a user holds the entry's address and the leaf is
invisible to them. Decide whether the pushed artifact is narrowed to the entry's
own material, and if it is not, decide that knowingly and write down in
`docs/decisions.md` what is lost.

**What is not built, recorded so it is not proposed again:** a reverse proxy on the
entry forwarding `/sub/*` to the control plane abroad. It inverts the project's one
directional invariant — *control plane → node, always* — and it does not even work:
under a shutdown the proxy cannot reach the control plane either, so the refresh
fails exactly as before with one more moving part.

### M27.2 — The control plane pushes delivery material to a node on apply

Riding the direction that already exists and already works: control plane → node
over SSH, on apply. Nothing in this milestone makes a node dial the control plane,
at any point, under any name.

Gate: `make test-edge` for what is rendered, `make test-control` for what is
pushed — separate diffs, as `CLAUDE.md` requires.

### M27.3 — Whatever serves `/sub/{token}` on a delivery host records no token

`/sub/{token}` is a bearer credential in a URL path; access logging is off in
uvicorn and discarded in Caddy, and those rules are **inherited here, not
re-decided**. A second listener on a second host is a second place a path can be
recorded — and it is on a host whose logs the owner does not read daily. Every new
surface gets the same treatment, checked rather than assumed, including whatever
the node stack writes by default.

### M27.4 — Co-location makes the feature absent, not inert

*Owner's requirement, 2026-09-22, broadened the same day.* The three roles —
control plane, entry, leaf — are placed on one, two or three machines in any
combination, and **the country each one sits in is not the product's business**.
That is the charter's own rule about nodes applied one level up: nodes are data, so
the arrangement of them is data too.

| machines | arrangement | what delivery does |
|---|---|---|
| 1 | C + E + L together | already served from that box |
| 2 | C + E \| L | already served from that box |
| 2 | C + L \| E | the case that needs the work |
| 3 | C \| E \| L | the case that needs the work |

**This step also owns the removal path for a host whose apply is refused** — added
2026-09-26, from M27.2's review. `apply_node` raises `NothingToApply` above the delivery push,
so the ordinary way a host stops carrying users (disable its last transport, press Apply)
never reaches it and the host keeps its ex-users' rendered subscriptions — including a
WireGuard client `PrivateKey` its own server config never held. **That is not what "absent,
not inert" means** and the decisions rows are at pains to say so: this step is the home for it
because it is the step that introduces the predicate *"is this host a delivery host"*, and the
removal path for a host that is **not** one is the same path a host that **stopped** being one
needs. Both must reach a host whose apply is refused. `tests/control/test_an_apply_hands_a_node_the_subscriptions_it_serves.py`
pins the uncovered state and goes red the day anything reaches that host.

**Where the roles are co-located the feature must be ABSENT, not merely inert.**
No second domain, no second certificate, no second listener, no extra key in
`.env` — and **no flag the operator has to know to leave off**, because a flag like
that is a way to get it wrong. Whatever is built works this out from what the fleet
already knows, and an operator who has never read this milestone cannot arrive at
the wrong shape by following the panel.

### M27.5 — A user refreshing against an entry three applies behind is not lied to

A pushed subscription is a snapshot. The panel already knows how to say *"this node
is not running what this panel would give them"* (M25). Decide whether delivery
inherits that sentence or needs one of its own, and decide what a user actually
gets when they refresh against an entry that is stale — which is a product answer,
not an error path.

### M27.6 — The certificate, on whichever host ends up serving delivery

A public CA will not issue for a bare address, so every host that serves `/sub/*`
needs a real name, a real record and a real certificate — issued and renewed from
wherever that host happens to be, on a machine the control plane drives but does
not live on. Decide who renews it, and **what happens when renewal fails while the
border is shut**, which is the moment the endpoint exists for.

### M27.7 — How delivery moves, and what users must be told, written down rather than implied

Moving the delivery endpoint is the one change that cannot be announced through the
thing being moved. A subscription URL names a host; change which host serves it and
every user is holding a dead address, and the only channel the product has for
telling them is the address that just died. It works if you move *before* a block
and is impossible if you move *because* of one — which is when you will actually
want to.

So one of these is decided deliberately and recorded:

**A requirement this step inherits, not a suggestion — from M27.5, 2026-09-27.** The wording
that travels with a delivery URL must say **add it alongside the link you already have, do not
replace it.** A delivery host serves a *slice* — only its own material — so a client that
replaces its subscription URL with a delivery URL silently loses every node not on that host,
and it looks exactly like a revocation. M27.5 weighed putting that warning *inside* the
artifact and refused: a truthful per-user version writes *"this person has other nodes"* onto
the most seizable box in the fleet, once per person, which yields a seizer more than the leaf
addresses narrowing was built to hide. **So the protection cannot live in the document. This
step is the only place it can live.**

- a subscription carries **more than one** delivery URL from the day it is issued,
  and a client falls back — which doubles the number of places a bearer token can
  be recorded, and puts a Russian-side address into every foreign artifact and the
  reverse;
- or moving delivery is defined as an **out-of-band event**, said so plainly in the
  runbook, and the operator is expected to have a channel that is not this product.
  That is the honest cheap answer and it is not obviously the wrong one.

The milestone is not done while this is implied rather than recorded.

### M27.8 — The runbook collapses its three shapes into one installation with a field in it

**The test of this milestone is the runbook, not the code.** When this was planned,
`docs/deploy/runbook.md` carried three shapes with three procedures and a migration
section between them, and ended *Shape C* with *"today you choose one location for
both."* If this milestone lands and that structure survives unchanged, the point
was missed.

**Built 2026-10-02**, on `task/M27.8`. The runbook now opens with *Where the three roles
go* — the four arrangements of the table in M27.4 and what each costs — and installs by
one procedure, *Installing hashi*, whose steps are the same for every arrangement: the
arrangement is which box you type each step on and which values a node record carries
(its `address` above all), never a setting and never a question the page asks. *Which host
answers a refresh* states the derived predicate; *The delivery certificate* is the first
runbook text for the wildcard pair; *Growing out of one box* replaces *Growing out of
Shape A*. The shape sections and *"today you choose one location for both"* are gone.
Carried in from M27.6: the 443 rule names the shipped default in which no host loses the
port, and the backup table lists `deploy/delivery/`. Carried in from the done-when list
below: what a delivery host holds, when an apply takes it away, and the three states no
apply reaches. `tests/infra/test_deploy_runbook.py` holds the structure.

### M27.9 — `infra`: the gate is red for four hours a day · found building M27.4, 2026-09-27

**Not M27's subject, and it is here because every remaining step of M27 gates on `make verify`.**

Between **00:00 and 04:00 UTC**, three tests in
`tests/infra/test_what_the_command_line_may_say_about_a_backup.py` fail —
`test_the_tick_that_takes_it_leaves_a_record_this_clock_can_read`,
`test_a_run_timestamp_ahead_does_not_make_the_tick_dump`, and
`test_an_ordinary_record_says_none_of_that`. Confirmed at 00:54 UTC; the same three are green at
other hours, and were green three times on the same diff earlier the same evening.

**The product is right and the fixture is wrong.** The module builds
`A_REAL_RUN_HALF_AN_HOUR_AGO` at import with `due_date = today_in("Etc/UTC")`, while
`scripts/backup-run.sh` computes the schedule's due date from the configured `at=04:00` window. So
inside that window the fixture's record is dated a day **ahead** of the schedule's own due date,
and the script correctly answers `clock=ahead` — the behaviour M28.19 built and M28.22 measured
across every offset. The test asserts the answer it gets during the other twenty hours.

**Proven pre-existing**, so this is not M27's doing: the same three fail at `530e61b` in a clean
worktree at the same wall clock, and M27.4 touches no infra file `make test-infra` collects.

**Why it earns a step rather than a carry-over line.** A gate that is green in every run anyone
happens to make is the exact defect this codebase has spent two milestones learning to name — M28
found eight surfaces of *a check that can be satisfied by the absence of the thing it checks*, and
this is the same shape wearing a clock. It has been in `develop` since M28 merged, so **every
`make verify` this project has run in that window reported a failure nobody could act on**, and
every one outside it reported a pass that did not cover this. Four more M27 steps gate on it.

**Fix the fixture, not the product**, and fix the class rather than the three: build the record's
dates from the **schedule's own due-date rule** — the same computation `backup-run.sh` uses — so
the fixture is correct at every hour, rather than adding a window guard or freezing a clock.
`docs/tracker/M28/step-notes.md` records the measured rule (`offset − ceil(at)`, floored at zero,
and the boundary `due_date > (reader's UTC date + 1 day)`), and M28.22's sweep is the reference for
what the schedule actually computes at each hour.

**Then sweep `tests/infra/` for the shape**, not for these three: any fixture whose value is
derived from `today`, `now` or an import-time clock while the code under test derives the same
value from configuration. Report what the sweep finds even where you do not fix it.

**Run the suite at a simulated hour inside the window and outside it, and report both** — a fix
verified only at the hour you happen to be working is the defect again.

Gate: `make test-infra`, then `make verify`, with **e2e 239 passed / 0 skipped**.


**E2E:** `tests/e2e/control/` for what is pushed on apply and `tests/e2e/infra/`
for what a delivery host serves and does not log. The arrangements themselves need
two machines, so they are a real-host walk and are reported as one — the stand can
show the feature is absent when co-located, and cannot show a border.

**Done when**
- [ ] With the control plane's box unreachable from Russia, a user inside Russia
      fetches a refreshed subscription and connects on it. *Not walked: needs real
      hosts in C+L | E.*
- [ ] **All four arrangements in the table above install by one procedure**, and the
      co-located ones need no second domain, no second certificate and no additional
      configuration — an operator who has never read this milestone cannot arrive at
      the wrong shape by following the panel. *Written (M27.8: one procedure) and held on
      the stand (M27.4: a co-located box is never a delivery host). Unticked until a
      real-host walk follows that procedure in both C+L | E and C+E | L.*
- [ ] No new surface records a token, an address, or who fetched what — checked on
      every host that can serve delivery, not only on the control plane's. *Measured on
      a real Caddy engine on the stand (M27.3, M27.6); not yet on a real delivery host.*
- [x] What a seized delivery host yields is written down and is no wider than it is
      today, or the widening is a recorded decision in `docs/decisions.md`. *The
      2026-09-27 seizure inventory, which records the wildcard key as the widening.*
- [x] How the delivery endpoint is moved, and what users have to be told when it
      moves, is decided and written down rather than left implied. *M27.7: out-of-band,
      in `docs/decisions.md` and the runbook.*
- [x] `docs/deploy/runbook.md` loses the sentence *"today you choose one location
      for both"* **and its three-shape structure**, because neither is true any more.
      *M27.8.*
- [x] **A host that STOPS being a delivery host does not keep its material.** There is no
      teardown in this product — recorded twice on 2026-09-13, and measured with a leaf's
      `wireguard.conf` and its `PrivateKey` still on disk after the row was deleted — so
      delivery inherits that gap rather than a cleanup. A node that stops carrying users
      keeps its ex-users' rendered subscriptions, and a WireGuard-family client file carries
      a `PrivateKey` the node's own server config does not. **M27.4's "absent, not inert" does
      not cover this**: that requirement is about a host which never served delivery, not one
      which stops. Either the material goes, or what survives is named in
      `docs/decisions.md` **(done — M27.2's rows name three states, and a test pins the one
      that is not closed)** and in the runbook where an operator will look — **M27.8 owns the
      runbook half**, and nothing in the runbook yet says a node carries pushed material at
      all. The removal path itself is **M27.4's**, per M27.2's rows. *Closed: M27.4
      built the removal, including on a refused apply; the three states no apply
      reaches are named in `docs/decisions.md` and, since M27.8, in the runbook's "When a
      delivery host stops being one".*

acceptance: yes
Walk it on the two arrangements that differ, not only on the one that motivated it.

1. **Three boxes.** Control plane on its own box; block that box at the firewall so
   it is unreachable from the entry's network. Then, as a user: refresh a
   subscription and connect on what comes back.
2. **Control plane on the entry.** Install the same way, from the same procedure.
   Confirm that nothing extra was configured, that no second name or certificate
   exists, and that there was no point in the walk where the operator had to know
   which shape they were building.

A walk that only proves (1) has proved the easy half: (2) is the one that fails if
the feature was built as a switch instead of as a consequence.

---

## ✅ M24 — The panel never shows the URL that delivers a config-file transport · PROPOSED 2026-09-14, premise corrected the same day · decided by the owner 2026-10-02 (one URL per config shape; the config-file re-import accepted as a known limitation) · built 2026-10-02 · acceptance: yes (a real-host walk, run by the orchestrator after this milestone — not by the implementer), PENDING · **CLOSED by the owner 2026-10-03** — the real-host walk passed; the owner's own phone check was not done before closing

**Built 2026-10-02** on branch `task/M24`, stacked on `task/M31`. Code, tests and a
disposable stand only — no real host was touched. What closed, the gate and what the
real-host walk must see: *What closed* at the end of this section, and
`docs/tracker/M24/`.

### Premise corrected again, when the work started (2026-10-02)

Read against the tree on the day it was built, three sentences below were out of date:

- **There were two composers, not one line.** `control/app/api/routes.py` built
  `{public_base_url}/sub/{token}` for the API, and `console.subscription_url` built the
  same string for the panel's link dialog — opened from the Users screen's *show link*,
  the Overview's *link* and the add-user exchange. Both composed the plain shape only.
  M24 makes them one (`console.links_for`).
- **The two sentences in the table below were no longer the ones on screen.** M20's fix
  round had already replaced both — and two more beside them (the enable dialog's footer
  and the re-offer toast) — with *"…gets it from that same link only by asking for that
  shape"*. True, and an instruction to compose a bearer credential by hand, because no
  screen showed the URL. Five further sentences said a user gets **"one subscription
  URL"** (Users screen, its empty state, the add-user dialog, the Overview's empty state,
  the Users subtitle), false for anyone holding a config-file protocol once the owner's
  decision gave them two.
- **Question 1 is the owner's, answered 2026-10-02** (`docs/decisions.md`): *one URL per
  config shape, not one polymorphic link.* Question 2 follows from it — a node serving
  both families puts a person in both links, and each link says which of their
  protocols it carries.

### The correction that defines this milestone

This was first written up — by the orchestrator, on 2026-09-14 — as *"a friend
cannot receive a config-file transport… there is simply no route from it to the
person."* **That was false, and the error is worth keeping visible**, because two
separate false sentences in the product are what produced it.

**`GET /sub/{token}?format=client-config-file` exists and works.** It is
`control/app/api/delivery.py` (backlog item 27, landed). Fetched through the real
app during M20's fix round: **200 `application/zip`, 1286 bytes**, containing a
valid `awg-probe-1.conf` with `[Interface]`, `PrivateKey`, `Address`, `MTU`.

**So the route exists. What is missing is that no screen ever shows it.**
`control/app/api/routes.py:225` composes `{public_base_url}/sub/{token}` — the
plain shape only. An operator following the panel hands a user a link that, for
a node serving only WireGuard-family transports, returns an empty document.

### Both sentences the product shows are wrong, in opposite directions

| surface | says | truth |
|---|---|---|
| every enabled row | *"offered — **in every user's link at their next refresh**"* | false for a config-file transport: it is not in the link's body |
| Transports screen | *"not in a user's link yet — **this panel cannot hand it over**"* | also false: the same link hands it over when asked for that shape |

M20's fix round corrected **both sentences**. It did not build a delivery surface,
and its own note says the wording it wrote — *"only by asking for that shape"* —
**describes today's gap rather than deciding how the link should carry the
parameter. That decision is this milestone's.**

*Recorded because the near-miss is instructive: a fix that corrected only the
first sentence would have replaced one falsehood with another, and the suite
would have been green either way.*

### What the milestone has to decide, before it writes code

1. **What URL does the operator get handed?** The plain one, with the user
   expected to know about `?format=`? One URL per shape? One URL that answers
   correctly based on what the node actually serves? The last sounds obviously
   right and is the one that quietly changes what a token means.
2. **What does "one link, every serving node" mean when a node serves both
   families?** A base64 URI list and a zip archive are not the same kind of
   document, and the subscription promise is currently written as if they were.
3. **What does the user do with a `.conf`?** A URI pastes into a client. A file
   has to be imported. Whatever is shown must match the client the runbook tells
   people to install.
4. **Bearer-token rules are inherited, not re-decided.** `/sub/{token}` is a
   bearer credential in a URL path; access logging is off in uvicorn and discarded
   in Caddy. **A new surface must not become a second place a token can be
   recorded**, and a `?format=` in a link is one more thing that can land in a
   history, a bookmark or a chat log.

**Done when**
- [x] An operator following only what the panel shows can give a user on a
      WireGuard-family-only node something that works. *Built and proven on the stand
      as far as the bytes: the URL the dialog prints under "config-file link", fetched
      exactly as printed, is an archive holding that user's `.conf`
      (`tests/control/test_the_panel_hands_over_the_config_file_link.py`, e2e
      `test_the_panel_hands_over_the_link_that_delivers_a_config_file.py`). **Seen on real
      hosts, 2026-10-02, with one qualification:** the archive's `.conf` for a user-facing
      `amneziawg` on the LEAF, imported by `amneziawg-go` 3.0.3 in a container, handshook
      and carried traffic that exited at the leaf. A real phone or desktop app was not
      tried. It was walked on the leaf because a user-facing `amneziawg` on an entry that
      dials a hop is refused with 409 `no_exit_through_the_hop` — the runbook's documented
      "one combination that will not render", not a defect.*
- [x] Every sentence the panel says about what a link contains is true for every
      combination of enabled transports — link only, file only, both, a withdrawn
      file row, a degraded or retired node; each tested.
- [x] No new surface records a token, an address, or who fetched what — no log record,
      audit row, attribute or cached response carries either URL (tested); the second
      link is text in the same `no-store` dialog and the same API response as the first.

acceptance: yes
Take a user on a node serving only `amneziawg`. Follow exactly what the panel
hands the operator — nothing learned from the source — and get a working
configuration onto a device.

### What was built (M24.1–M24.3)

- **M24.1 (control)** — `console.links_for` composes every URL a user is handed: the
  subscription link always (byte for byte the old one), and the same token asking
  `?format=client-config-file` **when, and only when,** the user holds a credential on
  an *offered* (enabled, user-facing) row, on a node that may serve again (draft, active
  or degraded — not retired), whose transport declares that shape in
  `subscription_formats`. No `if transport ==`: headings and wording are keyed by
  `SubscriptionFormat`, and each link names the transports it carries for that person.
  - **Link dialog**: one block per link — heading (*subscription link* / *config-file
    link*), the URL, which app takes it, what it carries for this person, its own copy
    button. The config-file link says it is not for a subscription app, is an archive to
    unzip and import, and **does not refresh itself** — after a node of theirs changes
    they download it again. A subscription link carrying nothing for this person says so
    (*"opens as an empty document — not an error"*) and is still handed over, because a
    link-shaped protocol offered later arrives in it.
  - **API** `GET /api/users/{id}/subscription`: `url` unchanged, `config_file_url` added
    (`null` unless held), composed by the same function.
  - **Nodes row, enable dialog, re-offer toast, Transports screen**: name the config-file
    link and where it is shown, instead of "only by asking for that shape"; the enable
    dialog and the re-offer toast also say that a person already handed only the
    subscription link must be handed the second.
  - **"One subscription URL"** removed from the five sentences that said it.
- **M24.2 (docs)** — runbook Shape A step 4 and *The two families are delivered
  differently* follow the dialog; this section; `docs/decisions.md`; `docs/tracker/M24/`.

### What closed (2026-10-02)

M24.1–M24.3 in code (M24.3 is review round 1's one medium finding: a link no longer says it
*carries* a transport whose node is draft or degraded). Gate: control 1127 passed / 2
skipped (throwaway Postgres); edge 968 passed / 14 skipped / 3 failed (the known
environmental `[wireguard]` cases in `test_upstream_validation.py`); infra 553 passed;
`make e2e-verify` **231 passed / 16 skipped** on M24.1+M24.2, and on the re-run after M24.3
229 passed / 16 skipped / **2 failed — both Docker Hub pulls timing out** (`caddy` manifest,
`amneziawg-go` pull, in `tests/e2e/edge/`; no M24 file is involved, and every control
scenario, the new one included, passed in both runs). The 16 skips include the bucket-restore
scenarios (minio image unavailable), as in M31. Review: `reviewer-strict`, round 1 — 0
critical, 0 high; 1 medium (fixed, M24.3), 1 low (owner question recorded in the tracker — answered by the owner 2026-10-02, see
*Not done here, deliberately*).
Details: `docs/tracker/M24/step-notes.md`; what the real-host walk must see:
`docs/tracker/M24/carry-over.md`.

### Not done here, deliberately

- **Per-host delivery URLs (M27.7).** The 2026-09-27 row says M24 owns "which URL an
  operator is handed" and that a delivery host's URL is the same question. The owner's
  decision for M24 covers the config-file shape on the control plane's own link only; the
  panel still composes no delivery URL (`test_this_panel_composes_no_delivery_url_anywhere`
  stays green). That stays M27's.
- **A config-file user re-imports after a rotation — decided by the owner 2026-10-02:
  accepted as a known limitation.** Not new — it is what option (b) (2026-08-09) always
  meant — and it qualifies the charter's *"users never re-add anything"* for this family;
  the dialog says so to the operator, and the charter now says it holds for
  subscription-link users only (`docs/decisions.md`, 2026-10-02).

---

## ✅ M23 — Walk the whole platform on the real hosts, and loop until nothing blocks · asked for by the owner 2026-09-13 · done 2026-09-15 (acceptance: good — 9 walks, 14 fix rounds, round 9 clean)

**Approved by the owner in conversation on 2026-09-13**, in these words: *"create
another one milestone that would verify all features of the platform on real
hosts… U also can create a checker container on current machine that will try to
connect via tunnel to the leaf amsterdam node… If the agent would find a bug it
should text it into a separate block on the milestone and after finish testing
immediately fix all findings and do an acceptance review one more time… do it on
a loop while the blocker/high bugs would not be fixed."*

**Why it exists.** Six milestones in this plan closed with acceptance **partial**,
every one of them for the same reason: *the stand has no data plane, no tunnel and
no second host.* `make verify` cannot prove a tunnel carries a packet, and this
project's most expensive defects have all been of one shape — **every signal
green, nothing carried.** M14 found it in the field. The probe (M22) has it now.
The charter names it as the failure that hurts most, because it is the one where
the operator stops looking.

This milestone is the answer: **stop inferring, and go and look.**

### What is reachable, and what is not — settled before any work starts

| | reachable | how |
|---|---|---|
| **Leaf, Amsterdam** | **yes, fully** | root SSH works from this machine |
| **Entry, Russia** | **no** | refuses this machine's key; takes keys from cloud metadata. Observable only *from the leaf* — the hop's handshake age and byte counters |
| **Pushing new configs** | **no** | applying needs the nodes' secrets, which live only in the owner's production control plane. A fresh control plane mints **new** keys; applying that would rewrite `amneziawg.conf` with a key the entry does not know and **cut the live hop out of Russia**, with no second route back |

**So the checker dials what is already deployed.** It does not apply, and it does
not replace a config.

### The one rule that governs every step

**`amneziawg.conf` on the leaf is the live entry→leaf hop and it carries the
owner's real traffic.** Nothing in this milestone touches it. Every check is
either read-only, or confined to the **friend-facing `wireguard` row** — which is
idle (last handshake days old, ~1 KiB moved) and is the safe subject.

A test peer is added with **`wg set` at runtime**, never by editing a file: it is
additive, it disturbs no existing peer, and it is gone on the next restart even if
cleanup fails. **Every step that writes anything must be undone in a `finally`.**

And the charter's hard record still holds, on the hosts as in the tree: **look, do
not keep.** No capture is written to disk on either host, and nothing that names a
destination is recorded anywhere.

### M23.0 — The transport to test is `amneziawg`, and `wireguard` is not a fair subject

**Measured on the leaf, 2026-09-13, before the walk was designed** — and it
changes what M23 can honestly test:

```
ufw:          active
iptables:     v1.8.7 (nf_tables)

legacy table: -P FORWARD ACCEPT
              -A FORWARD -i wireguard -j ACCEPT      <- plain WireGuard's rules
nft table:    -P FORWARD DROP                        <- ufw's policy
              -A FORWARD -i amneziawg -j ACCEPT      <- amneziawg's rules
```

Both backends register hooks at the same kernel point and a packet traverses
**both**. `amneziawg`'s ACCEPT is in the same table as ufw's `DROP` and front-runs
it. **`wireguard`'s ACCEPT is in the legacy table and cannot**, so a friend's
traffic on that row is dropped — handshake completes, nothing moves, nothing
logged.

**This is M20, observed rather than predicted**, and the owner decided on
2026-09-09 to record it rather than fix it. So:

- **A failure to carry traffic on the `wireguard` row is NOT a finding.** It is
  the known limitation, and reporting it as a bug would be noise. The walk records
  it as *confirmed on real hardware* and moves on.
- **`amneziawg` is the subject**, because it is the transport the runbook mandates
  for the hop, recommends for Shape A, and is proven on this host right now.

### M23.1 — Stand up a checker that is a real client, not a simulation

A container on this machine holding a **real AmneziaWG client**, a keypair minted
for the test, and nothing else.

**It does not join the existing hop interface.** That interface is
`10.90.0.2/30` — a `/30` holds two usable addresses and both are taken — and it
carries the owner's real traffic. Instead the walk brings up a **second,
throwaway `amneziawg` interface on the leaf**, on a spare port and its own
network, existing only for the test and torn down in a `finally`.

That also makes the walk prove something no stand could: **two AmneziaWG
instances on one node, binding two ports, side by side** — which is M15's
uniqueness decision, and field-checklist item 3.

It must be a client the way a friend's device is a client: it completes a real
handshake with the real daemon on the real host, over the real internet.

### M23.2 — Walk every feature that only a real tunnel can answer

Each of these is a line some milestone had to record as *"could not — needs the
field"*. They are now answerable:

- **A packet goes through.** Handshake completes, and traffic moves in **both**
  directions — `wg show` transfer counters non-zero each way, not just a handshake.
- **The exit is the leaf.** From inside the tunnel, the public address seen by the
  outside world is the leaf's, not this machine's.
- **Two friends at once, at two addresses** (M17's whole subject, and its
  outstanding field item). Two peers, two distinct `/32`s, **both carrying
  traffic, neither seeing the other's return traffic.**
- **A revoked friend actually stops.** Remove one peer; that tunnel dies and the
  other keeps working.
- **DNS goes where M16 says it goes** — and, on the entry side, that a friend's
  lookup does not leave the entry's own interface. *(Bounded by the entry being
  unreachable: what can be established from the leaf is recorded, and what cannot
  is named.)*
- **The hop is still healthy afterwards.** The entry↔leaf handshake age and byte
  counters must be moving at the end of the walk exactly as they were at the
  start. **This is the safety check, and it runs first and last.**
- **Orphaned key material** (field-checklist item 1) — already confirmed once by
  M18's acceptance; confirm it on the real leaf.
- **The Xray log stays silent about names**, and nothing anywhere records a
  connection, a destination or a friend.

### M23.3 — The loop

**This is the part the owner asked for explicitly.**

1. Walk everything in M23.2 on the real hosts.
2. **Write every finding into the findings block below**, in the milestone itself —
   severity, what was observed, and the exact command that observed it.
3. When the walk is finished, **immediately fix every finding** that is not out of
   scope.
4. **Run the acceptance walk again**, on the real hosts.
5. **Repeat from 1 while any BLOCKING or HIGH finding is open.**

Stop the loop only when a full walk produces **no blocking and no high finding**,
or when a finding cannot be fixed without work this milestone does not name — in
which case it is written up as its own proposed milestone, the way M22 was, and
the loop continues on the rest.

**Done when**
- [ ] A real client completes a real handshake with the real leaf and carries
      traffic both ways.
- [ ] Two friends hold two addresses on one transport and both work, with neither
      seeing the other's return traffic.
- [ ] Revoking one stops that one and leaves the other untouched.
- [ ] The entry↔leaf hop is provably unharmed — handshake and counters moving at
      the end as at the start.
- [ ] Every finding is recorded in the block below, and no BLOCKING or HIGH
      finding is open.
- [ ] Nothing on either host was left changed: no test peer, no file, no capture.

acceptance: yes
On the real hosts, with a real client: a friend connects, carries traffic, exits
at the leaf, and a second friend does the same at their own address. Then one is
revoked and stops while the other does not. The hop that carries all of it is
untouched throughout.

### Findings — round 1, walked on the leaf 2026-09-14

**Verdict: PARTIAL.** The data plane works. The platform around it does not yet
deliver a usable tunnel to a friend: **a friend who imports the product's own
config gets a tunnel that carries packets and resolves no names, from a link that
returns an empty page.** Six HIGH, none of them visible from any stand. Nothing
blocking — nothing crashed, nothing lost data, the hop was never at risk.

**What the walk substituted, disclosed:** the control plane never displays a
node's private key and applying to the leaf was forbidden, so a throwaway server
keypair was minted and **exactly one line** changed in each product-issued client
config (`PublicKey`). Addresses, obfuscation headers, MTU, per-friend
PresharedKeys, `AllowedIPs`, `Endpoint` and keepalive are the product's own
output, unedited. The server-side firewall rules inserted are byte-identical to
the `PostUp` the product renders.

#### 1 · HIGH — a friend's config gives them no DNS at all, and the config tells them the opposite

No `DNS` line, and `AllowedIPs = 0.0.0.0/0, ::/0`. **Every** address routes into
the tunnel — **including the device's own resolver**, which on a home or corporate
network is a private address unreachable from Amsterdam.

```
$ docker exec hashi-m23-friend-a nslookup example.com
;; connection timed out; no servers could be reached

$ docker exec hashi-m23-friend-a ip route get 10.129.0.2   # the device's own resolver
10.129.0.2 dev awg0 table 51820 src 10.99.7.2
```

Both friends, identically. **Handshake green, exit correct, 5 MB downloaded — and
not one name resolves.** This is the charter's named failure shape.

The config states the opposite, as a deliberate reassurance:

> `# No DNS line: this device keeps its own resolver, and its queries do not go`
> `# through the tunnel. Said out loud rather than left as an absence…`

`ip route get` shows the second half is false for **every** destination. And
setting the node's **resolver** does not help — the client config is
byte-identical afterwards. **There is no setting in the panel that gives a friend
working DNS.**

#### 2 · HIGH — every friend on a node shares one PresharedKey

Two friends' configs differ **only** in private key and address. Confirmed in the
product's own rendered node config:

```
$ grep -c '^PresharedKey' /opt/hashi/conf/amneziawg.conf           → 2
$ grep '^PresharedKey' /opt/hashi/conf/amneziawg.conf | sort -u | wc -l → 1
```

**One friend's leaked config exposes the symmetric key protecting every other
friend's handshake on that node, and revoking that friend does not rotate it.**

#### 3 · HIGH — friends can reach each other's devices inside the tunnel

```
$ docker exec hashi-m23-friend-a ping -c 3 10.99.7.3
3 packets transmitted, 3 packets received, 0% packet loss

$ docker exec -d hashi-m23-friend-b nc -l -p 9999 -e /bin/echo HELLO-FROM-B
$ docker exec hashi-m23-friend-a sh -c 'echo probe | nc -w 4 10.99.7.3 9999'
HELLO-FROM-B
```

Cause is the product's own egress policy: `PostUp` renders
`-i %i -j ACCEPT`, which permits `%i → %i`. With `pool_size` putting every friend
on one routed `/24`, **30–50 people who need not know each other get full IP
reachability to each other's laptops and phones.** A `-i %i -o %i -j DROP`
inserted first would close it.

**The crypto half is sound** — a friend cannot forge another's address
(`ping -I 10.99.7.3` → 100% loss).

#### 4 · HIGH — the subscription URL the panel hands the owner returns an empty page

With an **active** node serving **only** amneziawg:

```
$ curl -i ".../sub/$TOKEN_A"                          → 200 OK, content-length: 0
$ curl -w '%{http_code} %{size_download}' "...?format=client-config-file"  → 200 1297
```

200 OK, zero bytes, no message, while the dialog says *"One URL, every serving
node."* **This is M24, now confirmed on real hardware.**

#### 5 · HIGH — pressing "revoke" twice turns an honest failure into a false success

```
press 1 → failed — access withdrawn in the database and on 0 node(s), but 1 node(s)
          could NOT be updated and the credential is still live on each until it is
press 2 → kolya revoked — link is dead
```

Nothing changed on the node between the presses. **The first message is correct
and the second is not.** An operator revoking someone urgently presses again after
a failure — that is the natural gesture — and is told the link is dead.

#### 6 · HIGH — a node registered without an SSH key can never be given one, edited or removed

The add-node dialog invites it (*"Optional now…"*), but every route 404s:
`edit|credentials|ssh|key|access`, `delete|remove|retire`, `DELETE`. **The node is
permanently unappliable and permanently in the list.**

#### 7 · MEDIUM — two failure messages name the wrong cause

- On a node with **no** SSH key, apply and probe both say *"the node refused the
  key this control plane holds for it."* **It holds none.** The operator is sent
  to debug the host's `authorized_keys`.
- Where the push **did** land but the daemon did not come up: *"could not be
  reached — apply it again once it can be."* It was reached; the file was replaced
  (peer count 2 → 1 on disk). **What failed was the restart.**

#### 8 · MEDIUM — three orphans for the retired `wireguard` transport, not one

`wireguard.conf` (live `PrivateKey`, plus material for `# peer-c50c0878`, a friend
issued credentials on a transport the panel no longer offers), **the interface
`wireguard 10.66.0.1/24` up**, `hashi-node-wireguard-1` running 5 days, `51840/udp`
open in ufw, and legacy-backend FORWARD/NAT rules. *(Read-only; nothing deleted —
it is the owner's.)*

#### 9 · MEDIUM — the live hop's obfuscation headers are the upstream project's published example values

```
h1: 1431655765  h2: 1717986918  h3: 2004318071  h4: 2290649224
```

`0x55555555`, `0x66666666`, `0x77777777`, `0x88888888` — AmneziaWG's documented
example set, **directly beneath the config's own comment**: *"Per-node values:
shared ones would themselves be the fingerprint that identifies the fleet."*

The product does **not** default them — the panel requires all four with no
default — so these were typed. But nothing warns, while `vless-reality`'s
`decoy_host` **does** carry *"per-node decoy site; never a project default"*.
**Same hazard as the charter's Reality rule, one layer down.** Two actions: the
owner rotates the live values; the product puts the same warning on these fields.

#### 10 · LOW
- `ufw` allows `51820/udp` with nothing bound to it.
- A row shows `config: never applied` and `why: pushed, but still running an older
  configuration` simultaneously.
- The config zip names files from an 11-character truncation of the node name, so
  two nodes sharing a prefix would collide inside one friend's zip. *(Observed,
  not tested.)*

### What passed, with the evidence

| item | result |
|---|---|
| **1 · handshake + traffic both ways** | **PASS** — handshake 32 s; **5 MB downloaded by each friend simultaneously**; node-side `672 KiB in / 5.95 MiB out` (A), `188 KiB / 5.49 MiB` (B) |
| **2 · the exit is the leaf** | **PASS** — in-tunnel trace `ip=45.151.69.107, loc=NL`; this machine outside the tunnel is `178.208.65.94` |
| **3 · two friends, two addresses, both carrying** | **PASS** — `10.99.7.2/32` and `10.99.7.3/32`, independent counters, concurrent. **Source-spoofing refused.** *(But see finding 3.)* |
| **4 · revoking one stops that one** | **PASS on the data plane** — A: 100% loss, B: unaffected; re-adding restored A in ~6 s. *(But see finding 5 for the panel path.)* |
| **5 · the probe tells the truth** | **PASS, all four.** Crash-looping → *"is not serving — crash-looping"*. Nothing listening → *"nothing listening on the port for"*. Working → *"is listening for… not proof that anyone can connect."* Success and failure render into the same slot. **M22's fix holds on a real engine.** |
| **7 · nothing logs a connection, destination or friend** | **PASS** — Xray `access: none`, `sniffing.enabled=false`, 4 log lines in 5 days; **zero `-j LOG` rules in either netfilter backend**; `LOGLEVEL=off`; no `/var/log/ufw.log`; `nf_conntrack_acct=0` |
| **8 · the hop is unharmed** | **PASS** — handshake 1 m 18 s → **56 s**; received **+6 332 B**, sent **+4 564 B**. It carried the owner's traffic throughout. |

**Proven for the first time, and no stand could:** **two AmneziaWG instances on
one node, two ports side by side** (`51830` live hop + `51930` test) — M15's
uniqueness decision, and field-checklist item 3.

**The leaf is as it was found:** no `awgt0`, no `10.99.7.0/24` route, nothing in
519xx, FORWARD holds only the two `amneziawg` ACCEPTs, all three conf files at
their original timestamps and byte sizes, **no container restarted** (all Up 5
days). `/opt/hashi/conf` is bind-mounted `:ro` into the only container that could
have written to it.

### Could not check — the exact observations a person must make

**The Russian entry (`158.160.67.252`)** refuses this machine's key and is
observable only through the hop's counters:
- M16's *"a friend's DNS lookup does not leave the entry's own interface"* — run
  `ip route get <resolver>` and `awg show` on the entry while a friend resolves.
- Whether the entry's friend-facing transports serve anyone at all.
- **The charter's first success criterion** — *"survives a mobile whitelist
  shutdown"* — a field observation on a real Russian mobile network **during a
  real shutdown. Nothing in this walk touches it.**

**Apply to the real leaf** was never attempted, by design — so the product's
revoke → apply → peer-removed path was proven on a throwaway node, and on the leaf
the peer was removed with `awg set` instead.

**The probe against the real leaf**: not run, because `apply` sits beside `probe`
in the same row and one misclick rewrites the live hop's config. **A person with
the leaf registered as a node closes this by pressing probe once and reading the
banner.**

**The deployed fleet still runs pre-M16 code** — `/opt/hashi/conf` dated
2026-09-09, and `vless-reality.json` greps zero for `dns`, `domainStrategy`,
`sendThrough`.

---

## ✅ M22 — The probe says a crash-looping transport is serving · found in acceptance 2026-09-13 · done 2026-09-14 (acceptance folded into M23's real-host walk)

**Proposed by the autopilot run on 2026-09-13 and approved by the owner the same
day** ("m22 yes"). Written down separately because the run declined to build it
inside M18: the owner's own rule is that a milestone needing work the plan does
not mention is a new milestone to approve, not a bigger one to finish.

**Ordered before M23**, because M23 walks the real hosts and will use the probe
to ask whether a node is actually serving. A walk carrying a lying instrument
measures nothing.

**What was measured.** On a real applied host, `vless-ws-tls` was crash-looping —
exiting 23 every second on a missing certificate file — with nothing listening on
its port. The panel answered **"realhost is serving amneziawg, vless-ws-tls" on
six consecutive probes.** With the same container **fully stopped**, the probe is
correct. So `Restarting` counts as serving: the probe measures that a container
*exists*, not that it works.

**Why it matters more than it sounds.** The probe is the operator's **only**
oracle for *is this node actually working*. A certificate path that is not there
yet is an ordinary first-run mistake — exactly the moment the operator most needs
a true answer. And it is the same shape as **M14**: handshake completes, nothing
moves; every signal green, nothing carried. The charter treats that shape as the
one that hurts most, because it is the one where the operator stops looking.

**Why it is not a patch.** The work is a decision before it is code:

### M22.1 — Decide what "serving" means
Four candidate answers, each with a different cost and a different failure mode:
the container **exists**; the container is **running** (not restarting); something
is **listening on the port**; a peer has **handshaked**. The last is the only one
that answers the operator's real question, and the only one that cannot be
answered without touching the data plane — which `edge` may not do.

### M22.2 — Whatever is chosen, say it where the operator reads it
A probe that answers "running" must not be read as "working". If the honest
answer is narrower than the question, the wording carries that, the way M18's
refusals now carry what they cannot know.

### M22.3 — A successful probe must be visible
Acceptance clicked probe four times, waiting 2, 3, 4 and 8 seconds, and **no
success banner ever appeared** — while every *failing* probe's banner appeared at
the same waits. An oracle nobody can read is not an oracle.

**Done when**
- [ ] A transport that is restarting, or listening on nothing, is not reported as serving.
- [ ] What the probe actually checked is written where the operator reads the answer.
- [ ] A successful probe is as visible as a failing one.

acceptance: yes
Break a transport's config so its container crash-loops, then press probe. The
answer must not say the node is serving it.

---

## ✅ M21 — A gate that fails at random is a gate people stop reading · found 2026-09-09 · done 2026-09-10

`tests/control/test_node_timeouts.py::test_a_node_that_never_answers_is_reported_with_a_plain_reason`
and `tests/control/test_first_apply_failure.py` fail intermittently, returning
`could not establish an SSH session: OSError` where they assert the timeout
sentence M4.4 introduced. **Observed at least twice in one session**, always
under load, always passing on a re-run.

**The cause is a test coupled to one failure mode rather than to the property.**
M4.4 set `node_connect_timeout=1` in the `settings` fixture so an unreachable
node costs a second instead of twenty. The fixtures point at `192.0.2.10`
(TEST-NET-1, reserved for documentation). What that address *does* is not
guaranteed: on a host where it is silently dropped the connect times out and the
assertion holds; on a busy machine, or one where something answers or rejects
sooner — this run's own operator host routes it over a `wg0` interface — the
connection fails fast with an `OSError` instead. **Both outcomes are the same
fact — the node could not be reached — and the test accepts only one of them.**

**Why it is worth a milestone rather than a re-run.** It is the M6.6 lesson one
layer in. A gate that goes red for reasons unrelated to the change trains
everyone reading it to re-run rather than investigate, and the habit does not
distinguish this flake from a real regression. `make verify` is now *the* gate;
it takes ten minutes; a random failure in it is expensive in both time and trust.

### M21.1 — Assert the property, not the sentence

"The operator is told the node could not be reached, in words, without a
traceback" is the property. Which kernel error produced it is not.

### M21.2 — Stop depending on what an address happens to do

A reserved address's behaviour is a property of the network the test runs on, not
of the code. Consider a listener that accepts and never answers, or a closed port
on loopback — something whose behaviour the test itself decides.

### M21.3 — The gate must be runnable on the owner's own machine · scope extended by the owner 2026-09-10

Two tests in `tests/edge/test_the_wireguard_family_can_start.py` cannot pass on
macOS. `edge/bootstrap/node_stack.py`'s `_WG_QUICK_SUPERVISOR` ends in `sleep
infinity` — a GNU coreutils extension that BSD `sleep` rejects — and that test
deliberately runs the supervisor under the **host's** `/bin/sh`. On Linux CI it
is green; on the owner's laptop `make verify` is red, so the owner cannot run
their own gate. Same defect class as the rest of M21: a gate that goes red for
reasons unrelated to the change.

**The constraint the owner set.** The shipped supervisor only ever runs inside a
Linux container. Do not contort production code for a host that never runs it
*unless the portable form is genuinely no worse*. A portable idle, a host
capability skip carrying a reason a reader can act on, or running that script the
way the container does — any of the three is admissible; which one is for the
implementer and the reviewer to settle.

**E2E:** none — this is a unit-level fixture question. `make test-control` is the
gate for M21.1 and M21.2, `make test-edge` for M21.3, and the honest proof is
running them repeatedly under load and getting the same answer every time.

**Done when**
- [x] The unreachable-node tests give the same result on a loaded machine as on
      an idle one. — both files now dial a loopback socket the suite itself opens
      (`unanswering_ssh` listens and never accepts; `refusing_ssh` is bound and
      never listening), so the target's behaviour is decided by the test rather
      than by the host's routing table. 40/40 identical runs idle and under
      eight busy loops on four cores, reproduced independently by the reviewer.
- [x] The assertion names the property the operator depends on, not the errno
      that happened to produce it. — `assert_plain_reason(reason, *addresses)` in
      `tests/control/conftest.py`. Proven by mutation to still fail on a
      traceback, a bare class name, an empty reason, and a reason carrying either
      of the node's two addresses.
- [x] `make verify` is not red on a host whose `sleep` is BSD's, and the reason
      it is not is written where the next reader will find it. — the supervisor's
      idle is now `while :; do sleep 86400 & wait $!; done`, measured
      byte-identical to `sleep infinity` inside the container across `dash`,
      `bash` and `busybox sh` on every signal and failure arm; and the edge test
      now puts a POSIX-strict `sleep` first on `PATH`, so the host's own `sleep`
      stops mattering and a future non-portable idle goes red on Linux CI too.
      Written up in `docs/tracker/M21/step-notes.md`.

acceptance: no

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
- **Every arrangement on real hosts.** The co-located C+E | L has been walked on real
  hosts (2026-10-02); C+L | E and C | E | L — the arrangements in which an entry answers
  its own users' refreshes — have run on the disposable stand only (M27).
- **A leaf node's console.** There is none, deliberately — a node runs only its
  data-plane container, exposes nothing for management, and never dials the control
  plane. Nothing to build.
