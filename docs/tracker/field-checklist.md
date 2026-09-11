# Field checklist — what only you can check, on the two hosts

**What this is.** Everything the overnight run could not settle because the stand
has no data plane, no tunnel and no second host. Each item is written as an
instruction you can carry out yourself, in the order you should do them. Nothing
here was waived — each one was walked as far as the stand could honestly go, and
the part that needed hardware is recorded as *"could not — needs the field"*
rather than passed.

**Before you start:** the Amsterdam leaf and the Russian entry are the two hosts.
Nothing in the run touched either of them.

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

