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

**The exact key to install** (this is a *public* key; it is safe to paste
anywhere, and it is the only key this machine has — the leaf already accepts it):

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPqVn7EoK1SIxlD3sv+PkkavpgVVlFAn2g/ZTTZy2AnU
```

The entry runs `OpenSSH_9.6p1 Ubuntu-3ubuntu13.19` and offers **`publickey`
only** — no password fallback, so there is no other way in. Add the key to the
instance's metadata for whichever account you use, and the remaining DNS items
become answerable in one sitting.

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

**On a node that still has another transport enabled after the removal** — that
part is not a detail, see below:

```sh
ss -lunp | grep <the port>      # before
# then: remove the transport in the panel, and APPLY the node
ss -lunp | grep <the port>      # after
```

Removal does not push — **the apply is a separate step and is what stops the
container.** The control plane frees the port in its own bookkeeping immediately;
whether the daemon lets go of it on the host is only observable here.

**Why the node needs a second transport:** applying a node with nothing enabled
renders no config, and since M18.1 that apply is **refused** rather than pushed —
so removing (or withdrawing) a node's *last* transport leaves nothing to apply
and the container keeps running the config it already has. The panel says so in
the toast and again on the apply. That is a real gap and not a test artefact: on
a node whose last row was **withdrawn**, the host keeps authorising everyone who
already holds a credential on it until some transport there is offered again and
applied. Worth exercising once on purpose, on a node nobody depends on, so you
have read the sentences before you meet them.

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

---

## Can this run apply M17 to the leaf? No — and the reason is factual, not cautious

The owner authorised the two hosts as test hardware and asked that acceptance
verify on the real machines. Read-only verification was done and is recorded
above. **Writing to them is blocked by something no authorisation can lift**, and
it is worth stating exactly, because it looks like a policy choice and is not.

### What is actually on the leaf, read 2026-09-12

| file | what it is | state |
|---|---|---|
| `amneziawg.conf` | **the live entry→leaf hop.** `Address = 10.90.0.2/30`, one peer `AllowedIPs = 10.90.0.1/32`, `PersistentKeepalive = 25` — the comment in the file says it "keeps the UDP path open through NAT and stateful firewalls on the way out of Russia" | **carrying real traffic**: ~744 KiB in / ~760 KiB out, handshake seconds old |
| `wireguard.conf` | **the friend-facing row** — `Address = 10.66.0.1/24`, port `51840`, one peer at `10.66.0.2/32` | live, but idle: last handshake 3 d, 1.02 KiB in / 252 B out |
| `vless-reality.json` | Xray, port `49443` | live, pre-M16 (no `dns` block) |

Every one of those files begins **"Generated by hashi. Do not edit on the node —
overwritten on every apply."** So an apply rewrites *all* of them, the live hop
included.

### The blocker

**Applying requires the node's secrets, and they live in the owner's production
control-plane database, not in this run's tree or stand.** The leaf's interface
private key, the hop peer's public and preshared keys, and the per-node AmneziaWG
obfuscation values (`Jc`, `Jmin`, `Jmax`, `H1`–`H4`, deliberately per-node,
because "shared ones would themselves be the fingerprint that identifies the
fleet") are all held there.

A control plane standing up fresh would **mint new keys**. Applying that to the
leaf would rewrite `amneziawg.conf` with a key the entry does not know — **cutting
the owner's own hop**, the one carrying traffic out of Russia — and rewrite
`wireguard.conf` with a key the existing friend's device does not know.

So this is not "an apply might be risky". It is: **this run cannot produce a
correct apply for these hosts at all.** Only the owner's own control plane can.

### What was done instead, and what it is worth

**The promise that protects the hop is testable in the tree**, and the plan already
states it as a done-when: *"Hop ends are unchanged: no address, no pool, the same
dialog boxes, **byte-identical renders**."* M17.1b's
`test_a_hop_end_is_given_no_address_and_no_pool` pins the first half.

**The leaf's real `amneziawg.conf` above is the reference for the second half.** A
hop end on the real fleet has `Address = 10.90.0.2/30` and no pool; after M17 the
renderer must produce that same file, byte for byte. That is a check against
*production shape* rather than against a fixture the project wrote for itself —
which is the difference between a test and a test that agrees with reality.

### What the owner does, when they choose to

1. Merge the branches.
2. Apply from **their own** control plane — the one holding these nodes' records.
3. Then work items 15–19 of this checklist, which are written to be carried out
   after exactly that.

**Order matters: apply the leaf first, and confirm the hop still holds** (the
entry's handshake and the byte counters both keep moving) **before touching the
entry.** If the hop drops, the entry becomes unreachable and there is no second
route to it — the entry already refuses this key (item 0b).

---

## From M17 — one address per user, on a real interface

**Items 15–19, promised by the section above and written here.** All five are on the
**leaf** (`45.151.69.107`), which is the host that actually runs a friend-facing
`wireguard` row — the entry still refuses this key (item 0b) and is not needed for any
of them.

**Do these only after applying from your own control plane**, in the order the section
above gives: leaf first, hop confirmed, then the entry. Every item below measures the
new behaviour, so running any of them against the fleet as it stands today measures the
old one and will look like a failure of M17.

The one thing none of these can be read as: the charter's first criterion. Two users on
one interface is not "survives a mobile whitelist shutdown".

### 15. The peer list must grow one entry per user — the milestone in one command

```sh
docker exec <wireguard-container> wg show
```

**Before M17 this host showed exactly one peer, `allowed ips 10.66.0.2/32`, out of a
`/24`** (recorded above, read 2026-09-12). That is M17's whole problem statement on real
hardware.

**After: one peer entry per credential, each with its own `/32`**, and no two peers
sharing an address. The peer count must equal the number of users this control plane has
granted on that row — the Keys & configs screen now reads `<users> of <pool>` for it, so
the two numbers are checkable against each other without opening a database.

A peer with **no `latest handshake`** is a user who has not connected yet, not a defect.
What would be a defect is two peers with the same `allowed ips`.

### 16. The working device must not have moved — the promise the whole milestone rests on

The friend already on `10.66.0.2/32` **must still be on it** after the upgrade, and must
still connect **without reconfiguring anything**. Check in this order:

1. `wg show` — is `10.66.0.2/32` still in the peer list?
2. the same friend's client, unchanged, still comes up and passes traffic.

The address that device holds exists only as a rendered parameter today; the upgrade
writes it down and never moves it. If that friend has to re-import anything, M17 failed
at the one thing it promised, and the finding is worth more than every item below.

### 17. The hop's own file must be byte-identical

```sh
sha256sum /opt/hashi/conf/amneziawg.conf     # before the apply, and after
```

A hop end takes no address and no pool, so its rendered file must not change at all.
`Address = 10.90.0.2/30`, one peer at `/32`, `PersistentKeepalive = 25` — this is the
file recorded above, and it is the reference. **Take the checksum before you apply**;
afterwards is too late to know.

If it differs, stop and do not restart the interface: this is the tunnel carrying the
owner's traffic out of Russia, and the entry cannot be reached by any other route.

### 18. Two users, both carrying traffic — the half no stand can show

Put a **second** user on the leaf's friend-facing row, connect both devices, and watch:

```sh
docker exec <wireguard-container> wg show   # transfer: per peer
```

**Both peers' `transfer:` counters must move**, in both directions, at the same time.
This is the acceptance line — *"either both work, or the refusal arrived early enough
that the operator never believed it would"* — and the only place the first half of it
can be observed. The stand proves both are configured; only this proves both work.

Do it on `amneziawg` on a node with **no hop** if you have one, since that is the
combination the runbook recommends and the one the charter's users will actually be on.

### 19. Revoke one of the two, and watch the other keep working

Revoke the second user in the panel, apply the node, then:

```sh
docker exec <wireguard-container> wg show
```

The revoked peer entry is **gone**; the remaining peer keeps **the same `allowed ips`**
and its session does not drop. Then add a third user and apply again: they are handed the
address the revoked user gave back, which is what keeps a pool from shrinking every time
somebody leaves.

**Nothing here needs key material read or echoed.** `wg show` prints public keys only,
and none of these five items requires more than that.

### 20. The upgrade must not rewrite a file that was already right

**Acceptance could not reach this one and said so rather than passing it.** It
needs a row in the state migration `0006` leaves behind — `pool_size` NULL, one
user, no stored address — and the only way to build that on a stand is to write
the database by hand before the migration, which proves nothing about the real
upgrade.

**Your leaf is that row.** `wireguard.conf` there was written 2026-09-09 and has
one peer at `10.66.0.2/32`. So:

**Before you apply anything after the upgrade**, take a copy of the file as it
stands — on the host, not through the panel:

```sh
ssh root@45.151.69.107 'sha256sum /opt/hashi/conf/wireguard.conf /opt/hashi/conf/amneziawg.conf'
```

Write those two hashes down. Then upgrade, then apply, then run the same command.

- **`wireguard.conf`'s hash must be unchanged.** That is the milestone's promise
  that a row enabled before M17, with one user, renders byte-identical after the
  upgrade — the promise that keeps your existing friend's device working without
  anyone re-importing anything.
- **`amneziawg.conf`'s hash must also be unchanged**, for the separate reason in
  item 17: it is the **live hop**, and hop ends are promised untouched.

**If either changes, stop and look before applying to the entry.** A changed
`amneziawg.conf` means the hop's key or address moved, and the entry is the node
you cannot currently log in to (item 0b) — so a broken hop there is not something
you can go and fix.

*Why a hash and not a diff: the file holds private key material. A hash tells you
whether it changed without putting any of it on your screen or in your
scrollback.*

---

## From M23 — a friend's IPv6, and the one premise nothing in this run measured

### 21. Does the client actually TAKE the `::/0` route it is given?

**Nothing was built for this and nothing should be. It is an observation, and it
is on the list because it is the one assumption under the IPv6 decision that no
test on this machine can settle.**

A friend's file routes **every** address into the tunnel, v6 included, because
the alternative — narrowing the route to IPv4 — sends their v6 traffic out of
their own connection, from their own address, in the country the topology exists
to leave. Slow beats leaking, and the file says so where a friend reads it.

**The unmeasured part:** whether a client honours a v6 route on an interface that
has **no v6 address**. The Apple and Android apps build their v6 settings from the
v6 addresses in `Address =`, of which a node has none to give. A client that
silently declines the route does not fail loudly — it simply keeps sending v6
traffic the old way, and **the friend's IPv6 is already leaving by their own
connection today**, before any of this.

**How to tell, on a device you hold:**

1. With the tunnel **down**, confirm the device has working IPv6 at all — any
   address it can already reach over v6 will do. If it has none, this question
   does not arise for that device and the answer is not evidence either way.
2. Bring the tunnel **up** and look at what the client installed:
   - Linux: `ip -6 route show` — is there a default route on the tunnel interface?
   - iOS/macOS/Android: the app's own connection details, which list the routes it
     took. A client that declined shows no v6 route at all.
3. Reach the same v6 destination again. **Times out or fails over to v4** means
   the route was taken and the node has nowhere to send it — which is the decided,
   documented behaviour. **Succeeds at full speed** means the route was declined
   and that traffic never entered the tunnel.

**What to do with the answer: write it here, and nothing else.** If a real client
declines the route, that is a finding about a client and a question for the owner
— it may be an argument for giving nodes a v6 address, which is a milestone, not
a patch. Do not narrow `AllowedIPs` because a device was slow.

### 22. The device class the IPv6 premise was not measured on

Round 2 of M23 measured this on a client with **no global IPv6 address**: the
`::/0` route **is** taken (`ip -6 route get <AAAA>` resolves to the tunnel), so
**nothing leaks by the client's own connection**, and IPv4-first sorting connects
ordinary traffic in **~0.31 s**. The 30-second stall appears only when an app is
*forced* to v6 (`curl -6`).

**Unmeasured, and it is the case that matters:** a friend whose device has
**working global IPv6 of its own**. RFC 6724 then prefers the AAAA, so every
dual-stack connection *starts* on the family the node discards — and the wait
becomes the default path rather than an edge case.

**To tell:** with the tunnel **down**, confirm the device reaches a v6-only
destination. Bring the tunnel up, then:

```sh
curl -sv https://<a dual-stack host> 2>&1 | head -20
```

Read **which family it connected on** and **how long the first byte took**.

- Connects on IPv4 quickly → the cost is as measured, and nothing needs doing.
- Waits → that is an argument for a node that can carry IPv6, which is **a
  milestone and not a patch**.

**Do not narrow `AllowedIPs` as a fix.** Dropping `::/0` sends the friend's IPv6
out their own connection, showing their real address to every site that has one —
which is the failure this product exists to prevent, traded for a faster one.
