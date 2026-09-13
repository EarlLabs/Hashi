# M17 — acceptance: **partial** (good on the stand; three items need the field)

Two rounds, walked by an independent agent on a disposable stand with **no sight
of the diff, the changed file names, or any account of how the milestone was
built**. Round 1: 186 actions, ~63 minutes. Round 2: 96 actions, ~52 minutes.

## Verdict

**Round 1 — blocked.** One finding, produced by the stand, on a done-when.
**Round 2 — good.** Blocker closed; nothing blocks.

Recorded as **partial** rather than good because three lines genuinely need
hardware, under the owner's written lift of 2026-09-12. Nothing was waived: each
is recorded as *"could not — needs the field"* with the exact observation
required, and none of them is written as "good".

## The round-1 blocker, and why it mattered

The plan's done-when: *"Enable, add user, **offer**, set active and replace each
refuse a pool that cannot hold every active user **before anything commits**."*

**Offer did not. It was only hidden** — the button's absence was decided when the
page was rendered, so a stale page got around it. Acceptance reached it with
buttons alone: withdraw a wg-family row (pool 3, 3 friends) → open the transports
dialog, where the offer button renders → **add a fourth friend in another tab**
(allowed: a withdrawn row is not counted) → return to the still-open dialog and
click offer. It committed, with a success toast.

The row was then offered with a pool of 3 against 4 active friends — precisely
the state the plan says cannot be committed.

**This was not an oversight but an under-scoped decision.** M17.2 deliberately
withheld the offer button on the row's own pool whatever the node's state, and
recorded that in `docs/decisions.md`. The reasoning was sound; what it did not
anticipate was that the page could go stale. The defence was presentational, and
the done-when asks for a refusal.

Fixed in `nodes.set_transport_enabled`, above the flag, the audit entry and the
fan-out. The fix holds where `PoolFull` structurally cannot: `grant_everywhere`
grants on serving rows only, so a draft or degraded node allocated nothing and
therefore refused nothing.

## Round 2 — how the fix was established, not merely observed

Acceptance re-walked the exact path, then **attacked the new check where no
button exists**: `POST /panel/transports/<id>/offer` straight at the server on a
**draft** node and a **degraded** node, refused identically. Then enable,
add-user, set-active and replace on draft, degraded and serving, through both the
panel and the JSON API; a **second instance** of one transport on one node
(`wireguard-2`) getting its own pool check; and withdraw-then-offer **twice**,
idempotent at 8 holders and 8 distinct addresses.

**Four refusals in a row wrote nothing.** Counts identical before and after:
audit 33, credentials 18, rows 6, pool-sum 22, friends 7.

The refusal the operator reads:

> wireguard on leaf-one is sized for 3 and would need 4. Offering it gives every
> active user an address on it the moment this node serves, so as it stands
> nobody can be. Nothing has been changed — make the pool bigger on that
> transport first, or take somebody off the fleet.

## What passed, with what was done to establish it

- **The owner's scenario works.** Five friends onto one friend-facing `amneziawg`
  row and five onto a `wireguard` row: **ten config files, ten distinct
  addresses**, no collision — `10.77.0.2–.6/32` and `10.88.0.2–.6/32`. The thing
  M17 exists to stop does not happen. Enabling with `pool_size=1` against two
  friends refuses before anything is written (`node_transports` → 0 rows).
- **Nothing moves a held address.** Key rotation, revoking the holder of `.3`,
  resizing 8→5, changing `mtu`, and moving the pool start to `.20` all left
  `.2 .4 .5 .6` untouched; the freed `.3` was reused by the next friend. Moving
  the tunnel to `10.99.0.1/24` is refused — *"5 are outside the range this tunnel
  describes. Moving an address a device already holds is the one thing this
  cannot do."*
- **Overlap** refused on enable **and** on establishing a hop.
- **Hop ends unchanged**: `/panel/hops/new` has no `pool_size`; both relay rows
  have `pool_size` NULL; Keys & configs reads `hop — none`.
- **Charter scale**: `pool_size=50` accepted on a `/24`; 300 refused with
  *"235 are left from there."*
- **The panel speaks before the operator commits**: Keys & configs reads `5 of
  50` and `5 of 5`; set-active does not even offer the option, saying *"active —
  not offered — wireguard on leaf-one is sized for 3 and would need 4… Make the
  pool bigger first: Keys & configs, replace params."* The add-user dialog lists
  every full pool, has **no submit**, and its named path exists and was used.

## The charter's hard rule — checked twice, not assumed

**Zero user addresses on any panel surface.** Round 1 swept every surface; round 2
swept 25. The only tunnel addresses anywhere are `x.x.x.1` (the node's own) and
`x.x.x.2` (the operator-set pool start), each once, in the params dialog.
`audit_entries` has five columns and two labels — an address is structurally
impossible. Control-plane logs carry ids only: **no nickname, no address, no
token, no `/sub/` path**; no access log in uvicorn or Caddy.

**The one qualification, judged independently by both rounds and upheld.** The
first holder's address equals the row's own `peer_tunnel_address`, because
`pool[0]` is byte-identical to the renderers' old fallback — which is what keeps a
pre-upgrade device working. Both rounds judged it **inherent and correctly
bounded, not a hole being explained away**: any other choice moves a working
device, which is the thing M17 exists to prevent; the dialog says so out loud;
the panel never ties a person to it; and it stops being anyone's address the
moment the pool start moves. The residual is an **inference** available to
someone who knows the creation order — about the owner's own friend's tunnel
address, never a destination and never a connection record. There is nothing to
subpoena.

## Could not — needs the field (3)

Recorded as instructions in `docs/tracker/field-checklist.md`, items 15–20.

1. **Traffic, and the node-side `AllowedIPs`.** Every apply on the stand dies at
   SSH, so no node-side file is ever written. **Required observation:** after
   apply, the interface shows **one peer per friend, each with its own `/32`
   AllowedIPs**; then two friends connected at once, each reaching the internet,
   **neither seeing the other's return traffic**.
2. **The byte-identical pre-M17 render** — and it became *less* reachable, which
   is itself a good sign: this build now refuses to create a pool-less row at all
   (`enable` without `pool_size` → 400), so a pre-upgrade row cannot exist on a
   fresh stand. The comparison needs a database written before M17 — which the
   **leaf already is**. Checklist item 20 turns it into two `sha256sum` calls.
3. **Byte-identical hop renders** — only visible when pushed to a host.

**No scaffolding was built to simulate any of them.** A simulated proof of a
physical property is worse than an honest gap.

## Works, but awkward (6) — dispositioned in carry-over.md

The first is larger than M17 and is the one acceptance said it would look at
next: **a friend who opens their subscription link gets an empty page** —
`GET /sub/<token>` returns 200 with `content-length: 0`, and the configs come
only from `?format=client-config-file`, which no screen mentions. Not M17's
defect: wg-family transports have no URI form. But M17 just made a WireGuard row
able to carry the whole fleet, so *how a friend receives it* is now the next
question.
