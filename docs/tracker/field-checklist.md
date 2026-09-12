# Field checklist — what only you can check, on the two hosts

**What this is.** Everything the overnight run could not settle because the stand
has no data plane, no tunnel and no second host. Each item is written as an
instruction you can carry out yourself, in the order you should do them. Nothing
here was waived — each one was walked as far as the stand could honestly go, and
the part that needed hardware is recorded as *"could not — needs the field"*
rather than passed.

**Before you start:** the Amsterdam leaf and the Russian entry are the two hosts.
**Both were read during the run, read-only, with your authorisation of
2026-09-12** — state was inspected, key material was redacted in anything echoed,
nothing was written to either host and no capture was taken or kept.

---

## ZERO — two walls that block most of this list. Clear them first.

**Neither is a defect. Both are preconditions, and almost nothing below can be
observed until they are cleared.**

### 0a. The branch has to be merged and applied before any of this is visible

Every config in `/opt/hashi/conf` on the leaf is dated **2026-09-09 08:41**. The
live `vless-reality.json` greps **zero** for `"dns"`, `domainStrategy` and
`sendThrough`. The fleet is running pre-M16 code.

So: **merge the run's branches, then apply to each node**, and only then work
this list. Checking any DNS item against the fleet as it stands today measures
the old behaviour and will look like a failure of the new one.

### 0b. The entry will not take the key — and it is the only node that can answer the DNS items

`158.160.67.252` answers and refuses. Seven accounts were tried — `root`,
`ubuntu`, `hashi`, `admin`, `debian`, `yc-user`, `cloud-user` — every one
`Permission denied (publickey)`.

The host is **healthy**, not down: the leaf's `amneziawg` shows a live hop to it
with a handshake seconds old and ~744 KiB in / ~760 KiB out. It is up and
carrying your traffic. It simply will not take this key.

**Per M19's own finding, that box takes keys from cloud metadata, not from a
file on disk** — so `authorized_keys` on the host is not where to add one. Add
it through the provider's metadata for the instance.

**Why this blocks so much:** the entry is the node that dials the hop, so it is
the only node that gets a `dns` block at all. Items 7, 8, 9, 10, 11, 12 and 13
are all observations on the entry. The leaf cannot stand in for it.

---

## From M15 — a transport that locked a node out of a hop

### 1. Orphaned key material on disk, after any removal or teardown

**Do this on both hosts, and then whenever you remove anything.**

```sh
ls -la /opt/hashi/conf/
```

**What you are looking for:** a rendered config whose transport is no longer
enabled on that node. **Mind the extension — it is the transport's, not always
`.conf`.** `edge/bootstrap/node_stack.py`'s `EXTENSION` map gives the WireGuard
family `.conf` and the VLESS pair `.json`.

That second case is the one to watch, because **item 2 below is what sends you to
VLESS on an entry node** — so the next orphan you create is a `.json`, and it
holds the Reality private key, the `ws_path_secret` and every user's UUID. Every one of them contains **the node's private key and every
user's credential for that transport**.

**Why it is there.** Removing a node transport, withdrawing one, or dissolving a
hop deletes the row and its credentials from the control plane's database — and
the next apply stops and removes the *container*. **No code path in this
repository ever unlinks a rendered config.** `apply` writes;
`node_stack.restart` runs `docker compose up -d --remove-orphans`, which removes
the service and leaves the file. So the daemon is gone and the key material is
still on the host until somebody deletes it by hand.

**What to do:** `rm /opt/hashi/conf/<name>.<ext>` — `.conf` or `.json` per the
map above — **for a transport that is no longer enabled on that node**. Do it every time, or the fleet accumulates orphaned
key material on disk.

**Never touch a `.conf` whose transport IS still enabled.** The runbook's standing
rule — never edit anything under `/opt/hashi` — holds for those, and for the
reason it gives: the control plane generates them and overwrites them on every
apply. **An orphan is the one exception, because nothing regenerates it**, which
is exactly why the standing rule's reason does not reach it. `docs/deploy/runbook.md`
carries the same carve-out; if the two ever disagree, they are describing the same
file and one of them is stale.

**This is not a regression** — it is identical for all three actions and has
always been true. The panel's wording (*"the material minted for it is gone with
it"*) is accurate about the control plane's database and silent about the node's
disk. A product fix would be an apply that reconciles the directory against what
it just rendered — `apply`/`edge.bootstrap`, a step of its own, not yet written.

### 2. Whether the entry node can serve friends a kernel tunnel at all

**On the Russian entry host**, after the fleet is back up:

Try what the runbook currently tells you to do — offer `amneziawg` to friends on
the entry box, and establish the entry→leaf hop over `amneziawg` from that same
box. **Since M15.1 the hop is now accepted** (the old
`409 'amneziawg' is already configured` is gone, and uniqueness sits on the port
and config name instead).

**What to watch for:** the *apply* should fail, with this sentence or close to it —

> *"A tunnel whose packets this node's kernel routes cannot send them out through
> a different interface… Give this node's friends a transport that terminates
> their connection and re-originates it, or take the hop away."*

— and, **importantly, the node's state should NOT change.**

**Correcting something I got wrong when I first wrote this item.** I said the node
would be left *degraded*. It is not, and the truth is worse.
`apply.render_for_node` runs **before** the window `_record_failure` guards, so an
`EgressNotRenderable` never reaches it: the panel answers 200 with the banner and
the node's state is untouched. Verified by running it — state stays `draft`,
`state_detail` stays `None`.

**Why that matters on a live host.** `NodeState.serving()` is `(ACTIVE,)`. So an
entry node that was **already active** stays active and **stays in every friend's
link**, serving its last-applied config, while the apply is refused. Scanning the
Nodes screen for a degraded node will find none. The only exit is to remove the
friend-facing row (M15.2 shipped that) and apply again.

**Why this matters.** The runbook's Shape A is refused **twice** and M15 only ever
named the first. The second refusal is `edge/egress.py` enforcing your own
fail-closed decision, and it is correct — but it means the single-box shape with a
*kernel-tunnel* friend transport on the entry node does not work, and never did.
It simply failed later. **The leaf side of the same shape renders fine.**

The practical answer for a single-box entry node: give friends a transport that
**terminates and re-originates** their connection (the VLESS family) rather than
one the kernel routes.

Confirm on the real host that the failure arrives **as a sentence in a banner,
with the node's state unmoved** — not as a hang, not as a 500, and not as a
degraded node, because it will not be one. That is the half the stand cannot
show, since the stand has no host behind a node at all.

### 3. Prove the two instances actually bind two ports

**On the entry node**, once the fleet is back up and a node carrying both a
friend-facing and a hop-end instance has been applied:

```sh
ss -lunp | grep 5182
ip -brief link | grep -E 'awg|wg'
```

**What you should see:** **two** listeners, one per port, and **two** interfaces
— one per config name. The stand proved the control plane will *write* two rows
with distinct ports and config names; it cannot show that the node's kernel
accepts them side by side, because nothing was ever applied (`applied_at` was null
throughout the walk).

This is the half M15's whole decision rests on. If the two interfaces do not come
up together, the uniqueness rule is right about the database and wrong about the
host.

### 4. Prove a removed port is genuinely released on the box

**On whichever host you test removal on:**

```sh
ss -lunp | grep <the port>      # before
# then: remove the transport in the panel, and APPLY the node
ss -lunp | grep <the port>      # after
```

Removal does not push — **the apply is a separate step and is what stops the
container.** The control plane frees the port in its own bookkeeping immediately;
whether the daemon lets go of it on the host is only observable here.

### 5. The exit address, end to end

**With a friend's config from the entry node:**

```sh
curl ifconfig.me
```

**It must show the LEAF's address.** This is M3's criterion re-checked after M15
moved the uniqueness rule and M15.2 added removal — neither should have touched
it, and the stand cannot show it at all.

### 6. The hazard the stand could not reach

The acceptance walk saw a node in the un-renderable shape keep its state
untouched — but **its node had never been successfully applied**, so it never saw
the half that matters: an **already-active** node whose render now refuses,
**still serving a config you did not choose**, with nothing red on the Nodes
screen.

**To see it:** apply an entry node successfully, then add the combination that
will not render, then apply again. The apply is refused; check that the node is
still `active`, still in a user's link, and still running the *old* config on the
host (`docker ps` on the node, and the config file's mtime). That is the state the
Nodes screen currently gives no red signal for — the only standing hint is the
words *"cannot render"* in the config column.


---

## From M16 — the exit was Amsterdam, the DNS lookup was still Russia

### 7. Set the entry node's resolver FIRST — before any apply or revocation touches it

**Do this immediately after deploying M16, before anything else.**

Migration `0005` leaves every existing node with **no resolver** — deliberately
without a backfill, because any value it wrote would be a resolver the project
chose, which the M16 decision forbids. On a node that **dials a hop**, the product
now refuses to render a friend-facing proxy without one, because rendering
without it *is* the leak.

**What that means until you set it:**

- **Apply is refused** on the entry node.
- **A revocation's re-push to that node is refused too** — so a friend you revoke
  keeps working on the entry, on its last-pushed config, until the resolver is set
  and the node is applied.
- **The node does not turn red.** A render refusal leaves a node's state untouched
  (M15's finding, item 6 above), so the Nodes screen shows it as it was.

**What to do:** in the panel, **Nodes → the entry's row → resolver**, set it, then
**apply** the entry node (setting a resolver does not push). The API equivalent is
`POST /api/nodes/<id>/resolver`. The runbook's section *"A node that dials a hop
needs a resolver"* says the same thing, and says to do it before the next apply
and before you revoke anybody.

**If you revoke someone before doing this**, the revocation banner will now say so
honestly — *"'entry-ru' has no resolver on its record, so its configuration cannot
be rendered and retrying will not change that — set its resolver on the Nodes
screen, then apply it"* — and that friend's credential stays live on the entry
until you do.

**Choosing the resolver:** a plain IPv4 address that **the far end of the hop can
reach** — the query leaves from the leaf. Refused by the product: names, URLs,
`localhost` and the `+local` forms, IPv6 (the hop carries IPv4 only), and loopback
or `0.0.0.0`, which would be answered by the host's own upstream and put the leak
back by another route. The resolver you choose sees the queries — but from the
Netherlands, not from a Russian network. That residual is accepted knowingly
(`docs/decisions.md`, the M16 row).

### 8. Watch where a lookup actually leaves — the half the stand cannot show

**The stand has no data plane, so nothing it ran could see a DNS query leave a
host.** This is the observation M16's whole reason for existing depends on.

On the **entry** host, while a friend browses to a name:

```sh
sudo tcpdump -ni any 'port 53'
```

**You should see no query leaving the entry's own public interface for the cloud
provider's resolver.** Before M16, every name a friend visited went there, in
order, with timing.

On the **leaf** host at the same time:

```sh
sudo tcpdump -ni any 'port 53'
```

**You should see the friend's destination lookups leaving the leaf** for the
resolver you set.

> **Look, then stop. Do not save the capture and do not leave it running.** A
> running packet capture of a friend's lookups is exactly the record the charter
> forbids at any level. This is a one-off check on your own test host, taken by
> you — not something the product records.

A DNS-leak test site opened from the friend's device should report a resolver seen
from the Netherlands.

### 9. The entry's Xray log must stay silent about names

On the entry host, during the same browsing:

```sh
docker logs <the entry's xray container> 2>&1 | tail -50
```

**Zero lines should name a destination.** M16.1 measured that at `loglevel:
warning` a failed lookup writes nothing, while **the same flow at `info` writes the
destination name 38 times**. So `loglevel: warning` is now load-bearing: confirm
the deployed config says `warning`, and never lower it, even while debugging.

---

## RETRACTED, 2026-09-12 — "a container Up 3 days serving nothing"

**This section previously claimed the leaf's plain-WireGuard interface was gone
while its container reported healthy. That claim was false, and the reasoning
built on top of it was invented. Both are retracted here rather than deleted,
because the way it went wrong is the same defect this run keeps finding.**

**What was actually observed, re-checked on the host:**

- `wireguard` **is up**, addressed `10.66.0.1/24`, listening on `51840`.
- It has **one peer**, `allowed ips 10.66.0.2/32`.
- **Last handshake 3 days 13 hours ago; 1.02 KiB received, 252 B sent.**
- Both node containers run `network_mode: host`, so these are the host's own
  interfaces — there is no namespace to look inside.

**How the false claim was manufactured.** The check was
`ip -brief link | grep -Ei "wg|awg"`. The string `wireguard` **does not contain
the substring `wg`**. The pattern could match `amneziawg` and could never match
`wireguard`, whatever the host's state. It was a grep that could only return one
answer — *the same "verification that cannot fail" this run has now found seven
times, and the first one found in the orchestrator's own checking rather than in
the code.* The companion `ss` check did print `51840`, with an empty process
column, and that was read as "absent" instead of as what it is.

**Why the process column is empty, and why it is not a symptom.** Plain
WireGuard is a **kernel module**: the UDP socket belongs to the kernel and no
userspace process owns it. `amneziawg` shows `amneziawg-go` beside its port
because that one *is* a userspace daemon. An empty process column on `51840` is
the correct and expected output.

**Item 1 of this checklist — orphaned key material — is NOT confirmed by this
host.** `/opt/hashi/conf/wireguard.conf` is a **live, bound, in-use config**, not
an orphan. The item itself stands as written and still needs a field check; what
is withdrawn is the claim that this host demonstrated it.

### What the host does show, and it matters for M17

`wireguard` carries **exactly one peer, holding exactly one address**
(`10.66.0.2/32`) out of a `/24`. That is M17.1's problem statement standing on
real hardware: the transport as deployed today can serve **one friend**, because
nothing mints a second address. The `/24` is there; 253 addresses in it are
unreachable because no code hands them out. When M17 lands, this same command is
the acceptance evidence — the peer list should grow one entry per credential,
each with its own `/32`.

### The one real hazard, correctly demoted

The supervisor **does** run `wg-quick up` once and then wait on a sleep, never
watching the interface. So a container *could* report healthy with its interface
gone. That is a true property of `edge/bootstrap/node_stack.py`'s
`_WG_QUICK_SUPERVISOR` — but it is a **latent hazard, not an observed failure**,
and nothing on either host has exhibited it. It is recorded here so it is not
lost, and it is **not** a defect report.

**The product-side question, unchanged and still for the owner:** a data-plane
container should not be able to report healthy while the interface it exists to
run is absent. M1 made `apply` verify the daemon *loaded the config*; nothing
verifies the interface *stays up*. The cheapest honest fix is for the supervisor
to watch what it brought up and exit when that goes away — a change to
`_WG_QUICK_SUPERVISOR`, which M21 has already shown is portability-sensitive.

**The check that actually works** — use this one, not the retracted one:

```sh
ip -brief link | grep -Ei 'wireguard|amneziawg|wg[0-9]'   # matches all three names
ss -lnup                       # a listener with an EMPTY process column is normal
                               # for kernel WireGuard; it is not evidence of absence
docker exec <container> wg show   # peers, handshakes, transfer — the real evidence
docker ps                      # "Up" must never be the only evidence
```

---

## VERIFIED ON THE LEAF, 2026-09-12 — what the real host actually shows

Checked directly on `45.151.69.107` (root). **Read-only; nothing was changed.**

| claim | on the host |
|---|---|
| It is the **leaf end** of the hop, exiting locally | `10.90.0.2/30` on `amneziawg`; **no `ip rule`** diverts anything through it — only `local`/`main`/`default`. So `Egress.LOCAL`, and it correctly gets **no `dns` block** even after M16. |
| M16's premise, pre-upgrade | The deployed `vless-reality.json` has **no `dns` object**, no `domainStrategy`, no routing rules, `sendThrough` null. Exactly the state M16 was written to fix. |
| The charter's logging line already holds | `log: {"loglevel": "warning", "access": "none"}` in the live config. M16.1 measured that `warning` is load-bearing — at `info` the same flow writes a destination name 38 times. |
| The exit address | `curl ifconfig.me` from the leaf returns `45.151.69.107` — its own, as a leaf should. |
| The host's own resolver | `46.254.22.138` / `46.254.23.138` (the provider's). This is what an **entry** would leak a friend's lookups to before M16 — the whole reason M16 exists. |
| **Orphaned key material on disk (item 1)** | **NOT confirmed — an earlier "Confirmed" here was withdrawn.** `/opt/hashi/conf/wireguard.conf` is a **live, bound config**: `wireguard` is up on `10.66.0.1/24`, listening on `51840`, one peer. All three files on this host are in use. The retraction and how the false reading was produced are in the RETRACTED section above. Item 1 still needs a field check; this host did not supply it. |
| **A wg-family transport serves one friend today (M17's premise)** | `wg show` on the leaf: **one peer, `allowed ips 10.66.0.2/32`**, out of a `/24`. Last handshake 3 d 13 h ago, 1.02 KiB in / 252 B out — configured and listening, effectively idle. This is M17.1's problem on real hardware, and the same command is its acceptance evidence once M17 lands. |

**Still to do on the leaf**, once M17 lands: two `amneziawg` instances binding two
ports side by side (checklist item 3) — the thing M15's whole uniqueness decision
rests on, and which no stand can show.

**Blocked on the entry** (`158.160.67.252`): it answers but refuses my key —
`root`, `ubuntu`, `hashi`, `admin`, `debian` all `Permission denied (publickey)`.
Everything about where a friend's **lookup** leaves (items 8 and 9) needs that
host, because the leaf has no hop to dial and so is not the node under test.
Per M19's own finding, that box takes keys from cloud metadata, so a key may have
to be added there rather than in `authorized_keys`.

---

## HOW ACCEPTANCE VERIFIES ON THE REAL HOSTS — owner's instruction, 2026-09-12

The owner has authorised using the two hosts as test hardware and asked that the
acceptance agent verify on them, not only on the stand. The permission rule lives
in `.claude/settings.local.json`.

**Access, as measured 2026-09-12:**

- **Leaf `45.151.69.107` — the `root` account works.** Verified live.
- **Entry `158.160.67.252` — refuses every account tried** (`root`, `ubuntu`,
  `hashi`, `admin`, `debian`: `Permission denied (publickey)`). The host is up and
  healthy: the leaf's `amneziawg` shows a **live hop to `158.160.67.252:51830`**,
  handshake seconds old, ~744 KiB in / ~760 KiB out. So it is reachable and
  carrying traffic — it simply will not take this key. Per M19's own finding, that
  box takes keys from cloud metadata, so a key may have to be added **there**
  rather than in the file.

**Two capabilities are blocked by the local harness, not by the hosts**, and
acceptance will hit the same wall:

- A packet capture run remotely is refused by the auto-mode classifier. So the DNS
  observation (items 8 and 9) cannot be taken that way. **Alternatives that need
  no capture:** read the entry's rendered config for the `dns` block and the
  `lookup`-tag routing rule; have the friend's device ask for a name whose
  authoritative side you control and see which address asked; or open a DNS-leak
  test page through the tunnel, which reports the resolver's location directly.
- A raw TCP reachability probe to the hosts is likewise refused, though the shell
  session itself is allowed.

**The rule that does not bend, whatever the access.** These are live hosts
carrying a friend's traffic. **Look, do not keep.** A saved packet capture of a
friend's lookups is exactly the record the charter forbids — the one thing that
can hurt a real person. Read state, count things, redact key material in anything
echoed, and never write a capture to disk on either host or bring one back.

**What acceptance should do on the hosts, per milestone:**

- **M15** — two `amneziawg` instances on one node binding two ports, with two
  interfaces (`ip -brief link`, `ss -lnup`). This is what M15's uniqueness
  decision rests on and no stand can show.
- **M16** — the entry's rendered config carries the `dns` block and the routing
  rule; the leaf's does not (**already verified: it does not**). Then where a
  lookup lands, by the indirect means above.
- **M17** — two users on one WireGuard-family transport, each with their own
  address, both carrying traffic. The interface's peer list and its `transfer:`
  counters are the evidence; no key material need be read.
- **M18/M19** — the first-run messages and the bootstrap script's refusals, on a
  host that has never run hashi. **Do not run the bootstrap script against either
  live host**: it is written to prepare a fresh node and would rewrite state these
  two are serving from.

---

## From M16.2 — what the real hosts must show that a container fleet cannot

M16.2 built a scenario that proves, in containers, that a friend's lookup leaves
from the **leaf** and that removing `domainStrategy` makes the resolver see
nothing at all — while the friend's page loads identically either way. That is the
bug reproduced, not approximated. **Five things it still cannot answer**, and each
needs the two hosts.

### 10. The resolver must answer *through the hop*, in time

A tunnel inside a tunnel fragments and adds latency; two containers on a bridge do
not. **A resolver that answers in the lab can time out from Amsterdam**, and a
friend then has a node where nothing resolves.

With a friend's config up, ask for a name and time it. If lookups are slow or
intermittent, the resolver — not the code — is the thing to change; it is
node-record data precisely so it can be.

### 11. No UDP/53 may leave the entry's own public interface

The scenario counts packets at the **resolver's** side. On the real entry, watch
its **own** side: while a friend browses, nothing on UDP/53 should leave the
entry's public address for anywhere.

*(A capture is the natural tool and the local harness refuses to run one remotely.
Ask the friend's device for a name whose authoritative side you control and see
which address asked, or open a DNS-leak test page through the tunnel — it reports
the resolver's location with no capture at all. **Whatever you use: look, do not
keep.**)*

### 12. The node's own resolver stays the node's own

`/etc/resolv.conf` on the entry still points at the provider's resolver inside the
Russian VPC — **and that is correct** for the node's own traffic (package updates,
its own name lookups). What must not appear there is a **friend's** destination
name. The two paths are meant to be separate; confirm they are.

### 13. The entry must have a resolver at all before any of this can pass

Migration `0005` leaves every existing node with `resolver = NULL`, deliberately.
A hop-dialling node without one **refuses to render** — surfacing as
`ConfigRefused`, not as a leak. So on the real entry the first step is to set the
resolver through the new edit path (**Nodes → resolver**, or
`POST /api/nodes/<id>/resolver`), then apply. Until then there is nothing to
observe.

### 14. What must never be claimed from any of this

The charter's first criterion — **surviving a mobile whitelist shutdown** —
is untouched by M16 and by every test in this run. It is a field observation on a
real Russian mobile network and nothing here covers it. Do not let a green run be
read as covering it.
