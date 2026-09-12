# M17 — step notes

**Read this before writing a line.** Each step of this milestone is built by a
fresh agent that has not seen the earlier ones. What is here is what they
established; do not relitigate it and do not reinvent it.

M17 is the largest remaining milestone. The owner's instruction was explicit:
**do not build a bigger milestone than the one written.** If a step needs work
the plan does not name, say so rather than absorbing it.

## The decision this milestone implements (owner, 2026-09-11)

WireGuard-family transports **stay friend-facing**. The tunnel address becomes
**per-credential state**: minted with the credential, released on revocation,
drawn from a pool **sized by the operator on the node-transport record**.

**Never a hardcoded range.** This is the charter's "never hardcode a country,
provider, IP, domain or port" applied to address space. The pool's first address
and its size are operator data; no default range exists anywhere in the tree.

The two rejected answers, so nobody re-proposes them: *hop-only* removes the
obfuscated friend-facing transport the runbook recommends for Shape A, and *one
friend, deliberately* contradicts the charter's ~30–50 friends.

## What the real fleet shows — this is the problem, not a hypothetical

On the Amsterdam leaf, live: `wireguard` is up on `10.66.0.1/24` with **exactly
one peer**, `allowed ips 10.66.0.2/32`. A `/24` is configured and 253 of its
addresses are unreachable because nothing mints them. That is M17.1 in one line.

When M17 lands, `docker exec <c> wg show` on that host is the acceptance
evidence: **one peer entry per credential, each with its own `/32`.**

## The hazard that governs every step: `AllowedIPs` is two things at once

In WireGuard, `AllowedIPs` is **simultaneously the authorisation list and the
routing table**. Two peers sharing an address is not a conflict that surfaces as
an error — it is a **silent return-path hijack**, where the kernel sends one
friend's return traffic to another friend's peer.

Consequences that are settled and must hold:

- An address a device already holds is **never moved or reassigned**. Reuse only
  after an explicit release.
- Two wg-family interfaces on one node must **never have overlapping networks**
  — this is M17.1c, and it is a real gap: `AmbiguousPeerRoute` inspects one file
  and therefore cannot see a second interface's network. A judge panel over three
  competing decompositions surfaced this; it was closed by none of them.

## What M17.1a built — `edge/addressing.py` (pure, no I/O)

`edge` is pure: no database, no network, no clock, no randomness. This module
holds the arithmetic and nothing else.

- `host_of(...)` — the host part of an address.
- `pool_problem(first, within, size)` — returns a refusal or `None`. **Ten
  distinct refusals**, and the room available is computed arithmetically rather
  than by trying and failing.
- `pool(first, size)` — a **lazy iterator**. Element 0 equals
  `str(ip_interface(first))` **byte-identically to the renderers' existing
  fallback**, so the first credential on an upgraded node keeps the address it
  already has. Do not break this; it is what makes the migration safe.
- `networks_overlap(...)` — the M17.1c primitive.

`edge/registry.py` gained `PeerAddress(name, within)` and
`TransportMeta.peer_address: PeerAddress | None = None`. A transport **declares**
that its users need their own address; no `if transport ==` anywhere.

## What M17.1b built — `control/app/services/addresses.py`

`spec_for`, `pool_of`, `settle`, `edge_credential`, `shortfalls`, `PoolFull`.

- **`held_digests` is a named seam, on purpose** — it exists so the race between
  two credentials minting at once can be tested deterministically. It is not
  dead code and it is not over-engineering. Leave it named.
- A pool too small is refused **before anything commits**, not discovered
  halfway through.

Migration `0006_an_address_per_user.py` — **no backfill**, with a pre-flight
refusal on downgrade, matching `0004` and `0005`.

## Conventions inherited, still binding

- **Panel work follows `docs/tracker/M8/step-notes.md`** — how a screen is added,
  the mutation/OOB-swap rules, the fragment shape. M17.2 is panel work and is
  bound by it.
- **A refusal never carries a secret's value** (`docs/decisions.md`). Redaction
  happens in the service, where the values are still in scope — not in the
  template.
- **The danger hue** — a refusal is not drawn in the primary button's slate blue.
  Folded into M9 from M8's acceptance; it applies here too.

## The gate hazard — read before running anything

- **Every control test shares one Postgres** (`tests/control/conftest.py:39`).
  Two concurrent runs deadlock on schema teardown and manufacture false
  failures. See `docs/tracker/M9/gate-hazard.md`.
- **`make e2e-verify` builds the control image from the WORKING TREE, not
  `HEAD`** — so it cannot be trusted while another agent has uncommitted work.
  One run measured half-built code and reported 18 failures belonging to nobody.
- Before any gate: `pgrep -af 'make |pytest|docker build'`. The narrower pattern
  that missed a bare `pytest` is what allowed the 18 false failures.

## Branch discipline — learned the expensive way

`task/M17` was branched off `task/M16` **while M16 was still in flight**, and
four M16 commits landed here. Recovered by cherry-picking in an isolated
`git worktree` so the checkout a review was reading stayed untouched. See
`docs/tracker/M16/branch-recovery.md`.

**Do not branch the next milestone until this one's last commit has landed**,
and never leave two milestones' agents sharing one checkout.

---

## From M17.1b's fix round (2026-09-12) — what the next step inherits

**Gate at that point: `make verify` green — control 604 / 1 skipped, edge 299 / 3
skipped, infra 174, e2e 163.**

### Call these, do not re-derive them

- **`addresses.fleet_size(session, extra=0)` is the single definition of "who is
  in the fleet."** The count used to be copied in three places. Call it; do not
  re-query `Friend`.
- **`addresses.settle` writes nothing when it refuses.** It plans the whole
  allocation and writes only after every waiting credential has an address, so
  its "Nothing has been changed" is true *at the raise* rather than true because
  the caller rolled back. M17.1c's resize may therefore catch `PoolFull`, report
  it, and continue its own transaction. (`grant_everywhere` still rolls back, for
  its own separate reason.)

### The rule that came out of the BLOCKING defect — it will bite again

**A panel refusal helper must be `async` and must re-read its subject after any
service that can roll back.**

Why: a rollback expires **every** object in the identity map — `expire_on_commit=False`
does not save you. A `Node` fetched before the call is a husk in the
`except DomainError` branch, and touching any attribute emits a SELECT from a sync
frame on an AsyncSession → `MissingGreenlet` → not a `DomainError` → a 500 the
console never swaps, because the htmx dialog only swaps 422. The operator sees a
spinner stop and nothing else.

**Known divergence, deliberate and scoped:** `_refuse_state` now re-queries;
`_refuse_resolver` still takes a pre-fetched node, as do the handlers on
`health.check_node` and `apply.apply_node`. Those paths have no rollback today.
**If a later change puts a rollback on any of them, that handler gets the same
500** — and the fix is the same three-line shape.

### Operator-facing wording acceptance will judge — match it, do not re-word it

- `PoolFull`: *"… 2 are taken and 1 more friend needs one. Nothing has been
  changed. Make the pool bigger on that transport, or take somebody off it."*
- `0006`'s downgrade: *"Remove those transports, which takes their credentials
  with them, and run this again."*

**Migration 0006 now promises, in writing, that a serving pre-M17 row is sized by
replacing that row's parameters.** If M17.1c ships resizing under a different
name or surface, **that paragraph has to change with it.**

### Test harness in `tests/control/test_every_user_holds_their_own_address.py`

`enable_form(transport, pool_size=...)` builds the panel submission with the group
prefix; `field_errors(response)` reads the enable dialog's per-box errors; `HTMX`
is the header dict; `enable_pool` / `params_for` / `as_the_node_sees_it` /
`add_user` drive the API half; `calls_in(module)` + `ROUTE_MODULES` is the ast
helper for static route assertions. Paths resolve from `__file__`; no chdir.

### Carried forward to M17.1c — these are yours

1. **`control/app/services/rotation.py:286`** — `replace_params` can move or
   narrow the tunnel network under addresses already held, with **no pool
   re-check**.
2. **Overlapping tunnel networks between two wg-family rows on one node.**
3. **The release/apply window's residual hole.** A revoked friend's address is
   freed at revoke's commit, before the node is re-applied. This is *mostly*
   safe and the reason is worth knowing: a failed push runs `_record_failure`
   (inside `apply_node`'s try at line 417) which marks the node `degraded`, and
   `NodeState.serving()` is `(ACTIVE,)`, so `serving_transports` excludes it and
   `create_friend` grants nobody on that row. **The hole is an operator returning
   such a node to serving by hand without applying** — the console shows drift,
   the allocator does not read it. Closing it needs state the schema does not
   carry: *which addresses a node was last applied with*, not a digest of the
   file. Decide deliberately whether that is in scope; it may not be.

**Note the asymmetry, because it has already misled this run once:**
`render_for_node` is called at `apply.py:381`, **outside** both try blocks, so a
*render* failure leaves node state **unchanged** — an already-active node keeps
serving its last config. A *push* failure is inside the try and does degrade the
node. Do not generalise either one to the other.
