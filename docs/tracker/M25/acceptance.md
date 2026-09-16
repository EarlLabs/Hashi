# M25 — acceptance: **good** (2 walks, 2 fix rounds)

**Route A carries.** Asked for by the owner on 2026-09-16 after M23 proved route B
nine times and route A had never been observed carrying a packet.

## The question, and the answer

A friend's config can point at either node, and `control` picks the policy from
one table: friend-facing on a node with **no** hop exits locally (**route B**);
friend-facing on a node **with** a hop exits through it and never locally
(**route A**). Route A is the charter's design — a friend inside Russia reaches a
*Russian* address when foreign ones are blocked, and the traffic leaves obfuscated.

**Route A carries, measured on the owner's real Amsterdam leaf with real packets.**

| | |
|---|---|
| **M25.1** a friend behind an entry exits at the leaf | **passed** — `45.151.69.107` from inside the tunnel, three times running, while the entry's own route (`178.208.65.94`) never appeared. **10 MB in 3.0 s** (round 1); the hop's own counters moved for it, both ways: `7 092 / 14 596` → `143 892 / 3 216 424` bytes |
| **M25.2** an entry never exits on its own route | **passed, and it survived being attacked.** 20 consecutive exits, 20 the leaf, none the entry's. By rule: the entry's Xray has exactly **two** outbounds and **both** carry `sendThrough` — there is no socket without it; the hop interface renders `Table = off` plus one `ip rule from … lookup 51821`, no MASQUERADE, no FORWARD ACCEPT |
| **M25.3** the far end treats entry traffic as an entry's | **passed, measured not asserted** — same interface, same packet, two policies: under `RELAY` an ACCEPT; under the product's own friend-facing line on the same interface, `DROP` for `172.16.0.0/12` with the ACCEPT rows at 0 |

## The test that mattered most

`Egress.HOP` exists so a friend's traffic leaves through the hop **and nowhere
else**. If an entry leaks locally, **a friend's traffic surfaces in Russia** — the
exact outcome the fleet exists to prevent, arrived at silently, with every screen
green.

**So the walk tried to break it.** Round 1, twice: the far end blackholed with the
interface still up, and the hop taken fully down through the product's own
`PostDown`. Round 2, once more. **Every time the friend went dark** — `http=000`,
`rc=28`, nothing — while Xray kept running and the friend's handshake kept
completing, *and at the same moment the entry's own address was reachable.*

**It went dark rather than falling back. That is the right answer.**

## The blocking finding, and what it really cost

**The panel sold a route A that cannot exist.** Enabling a WireGuard-family
transport *for friends* on a node that already dials a hop was accepted at every
step — and the subscription handed the friend a **complete, importable 2 077-byte
`.conf`**. Only the apply refused, correctly and fail-closed.

**Why it cannot work:** a friend's packets would have to arrive on one tunnel and
leave by another, which wg-quick's source-routing cannot express — `Egress.HOP`
source-routes *the node's own address*, and a friend's packets do not carry it. A
proxy can, because it terminates the connection and re-originates it.

**The fix round found the blast radius was larger than the walk saw:**
`enable_and_grant` mints **per-friend key material and a pool address for every
active friend** in the same transaction; `set_node_state(active)` and re-offering
a withdrawn row run the same fan-out; an audit entry is written. So the silent
acceptance was not one bad row — **it was key material minted for the whole fleet
on a node that could never render.**

Closed by a **declaration**, not a name: `Datapath.KERNEL_ROUTED` /
`RE_ORIGINATING`, **defaulted to the restrictive member** so a package that
forgets is refused with a sentence rather than accepted at three surfaces. And
pinned to reality — the contract test **parses each renderer's imports** and
asserts the declaration matches what the code does, so a package cannot declare
one thing and do another.

**Round 2 verified nothing is minted** — in the **archive**, not just the
database: the friend's zip still held exactly one file. Both refusals name a way
out, and the walk **walked both** to confirm they work.

## The practical rule this settles

**On an entry that dials a hop, friends must be on VLESS — not a WireGuard-family
transport.** And, because the runbook recommends `amneziawg` for Shape A's
friends:

**When a one-box fleet grows, the box you already have becomes the LEAF, and the
new box becomes the entry.** Its `amneziawg` friends keep working — a node can
carry `amneziawg/friends` **and** `amneziawg/relay-leaf` at once, both enabled,
users untouched. Point the move the other way and the refusal names two ways out,
of which *"remove that transport"* is the one an operator reaches for — and the
panel's own words for it are **"the material minted for it is gone with it."**

That passage did not exist; round 2 found the gap and the fix round wrote it,
with the claim it rests on **pinned by an AST test over `relay.establish_hop`**:
if the refusal ever grows to ask the leaf, the advice starts costing credentials
and the test goes red.

**One qualification the fix round added rather than leave implicit:** the new
entry reaches every friend's subscription automatically, but on the **plain** link
as a VLESS URI, while their working `amneziawg` is a **config file**. *"Nobody
touches a device"* is true of **keeping** what they have, not of **taking** the new
path.

## What the substitution proves, and what it does not

**Stated plainly, because a green result reads as more than it is.** The "entry"
was a throwaway container running **the product's own rendered bytes** — configs
from `render_for_node`, the same function apply pushes, and the friend's
`vless://` verbatim from the product.

**It proves the product's half:** the source-routing an entry renders, Xray's
`sendThrough` binding, a real obfuscated AmneziaWG hop across the real internet to
the real leaf, and `Egress.RELAY` at the far end.

**It does not prove the Russian host's own conditions.** That container has no
`rp_filter` of its own, no Russian provider, no blocking, no carrier NAT, and its
"own route" is this machine's. **A person must still observe on the real host:**
that a friend inside Russia can reach it at all; that its `rp_filter` does not
drop the hop's return path; and that Reality survives that provider's filtering.

**Apply was never pressed at either live host**, by the safety rule. The SSH push
half is unexercised on the leaf.

**The charter's first criterion — surviving a mobile whitelist shutdown — is
untouched by both walks and nothing here covers it.**

## Recorded rather than claimed

**Recovery after a hop flap is unsettled.** The going-dark half is proven three
times. But the single post-recovery fetch came back empty, and the kill gesture
(`ip link set down/up` on a userspace device) **is not what a real hop failure
looks like.** Field-checklist item 23 has the observation.

## The owner's hop was never at risk

Baselined and re-read at both walks, and it **moved both times** — round 2:
`1 510 000 → 1 590 072` received, `1 320 000 → 1 386 755` sent. No file in
`/opt/hashi/conf` was opened for writing; all three kept their `2026-09-09 08:41`
timestamps. **No container restarted** — all three `Up 7 days` at the end.

## Two self-corrections by the walker, worth keeping

It nearly filed a finding about a generic banner; driving a real Chromium showed
the full sentence in the dialog — the 409/JSON was an artifact of `curl` not
sending `HX-Request`. And it wiped its own stand's database mid-walk, rebuilt the
state, and **re-walked every door**.
