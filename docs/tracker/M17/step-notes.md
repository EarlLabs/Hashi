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

---

## From M17.1c and its fix round (2026-09-13) — what M17.2 inherits

**Gate: `make verify` green — control 642 / 2 skipped, edge 321 / 3 skipped,
infra 174, e2e 163.** The second control skip is the hop-end test on `wireguard`,
which declares it cannot carry a hop. The edge jump (299 → 321) is
`carriage_problem`'s own tests.

### Call these; do not re-derive them

- **`edge.carriage_problem(address, within)`** — the "can this tunnel still carry
  an address somebody already holds" question. Same rules as `pool_problem`, same
  order, but it answers with the **cause as a clause that names nothing** —
  neither the address nor the tunnel. **Use it for any such question and never put
  `pool_problem(x, within, 1)` in a sentence an operator reads: `pool_problem`
  quotes the address it was asked about**, which is why `control` could only ever
  use its verdict and not its words.
- **`rotation._causes(dict)`** composes *"N is/are &lt;clause&gt;"*. M17.2 can use the
  same dict to show a shortfall **before** the operator commits, which is exactly
  what M17.2 is for.
- **`addresses.stranded_by` now returns `dict[cause, count]`, not `int`.** Falsy-
  empty still means "nothing stranded", so `if stranded:` is safe — arithmetic on
  it is not.
- **`nodes.sized_pool`** is still the single definition of a workable pool.
  Its refusal **messages** now name the node (`transport 'x' on node 'y' rejected
  these parameters — …`); the **per-box sentences are unchanged**, because the
  console opened the dialog from a row and the API caller has only an opaque id.
  Anything matching the old message prefix breaks; nothing in the tree did.

### Operator-facing wording acceptance will judge — match it, do not re-word it

`POOL_WOULD_STRAND`:

> a tunnel at {within} could not carry addresses already handed out on this
> transport: {causes}. Moving an address a device already holds is the one thing
> this cannot do — the device is configured with it and nobody is going to
> reconfigure it. Nothing has been changed — leave this tunnel where it is, or
> take them off this transport first.

`rotation.POOL_SIZE_NOT_ON_A_HOP`:

> this row is one end of a hop, and no user holds anything on it — the far end is
> another of your own nodes, at the single address this row already names. There
> is no pool to size here.

### Behaviour M17.2 must not "fix"

**A rotation on a short serving row now returns 200 with `complete: false`** — the
node is reported as not updated, because the render legitimately refuses. Do not
degrade the node and do not re-raise. **The summary is the operator's channel
until M17.2 puts holders-of-pool on screen** — which is M17.2's whole job.

### Divergences to know

- **`_resize` returns early for a relay row**, so a hop end's parameters no longer
  pass through `sized_pool` at all — including the `pool_problem(peer, within, 1)`
  it incidentally performed. Deliberate: *hop ends are unchanged*. A hop end's two
  addresses are now judged **only** by `relay.check_renders_as_a_pair`. A later
  step wanting shape checks on hop addresses needs its own, not `sized_pool`.
- **The range race is left open, deliberately, and the header now argues its own
  risk instead of borrowing the port rule's.** See `docs/decisions.md`. The trade:
  closing it needs a per-node lock taken by every writer of that node's rows, but
  `relay.establish_hop` writes rows on **two** nodes in one transaction, so it
  needs a fixed lock order or two hops laid in opposite directions deadlock — a
  500 in exchange for a race one operator cannot have with themselves (decision 8).
  A unique constraint cannot express overlap at all.

### Test harness

`resize(client, row_id, **body)` posts `/api/transports/{id}/params`.
`as_it_was_before_m17(session, row_id)` produces the field's post-0006 state (pool
NULL, addresses cleared) — **the only setup that reaches `settle`'s `PoolFull` on a
serving row.** A hop end for panel work is built inline in
`test_a_hop_end_is_offered_no_pool_box_and_refuses_a_size_typed_at_it` (10.93.0.x,
skip when `not profile(name).meta.hop_capable`).

**The trap that cost two runs:** after any successful resize the push fails and the
node goes `degraded`, which empties `config_files_for`. Call
`session.expire_all()` **then** `set_node_state(..., ACTIVE)` before you render, or
the test session's stale `active` makes it a silent no-op.

`pool_size` is a **reserved form-field name**, now asserted against every
discovered transport in `test_no_transport_declares_a_parameter_the_pool_box_would_shadow`.

### Left open, with reasons — do not silently absorb these

- **[19] the withheld reason on the replace dialog.** Every real fix either widens
  the printable allow-list from "boxes" to "boxes ∪ declared non-secret params" —
  relitigating the 2026-09-10 redaction decision that `_refused_parameters` exists
  to carry — or renders a box for optional parameters, **which is a new surface on
  the dialog M17.2 owns.** Console-only, and reachable only for an API-created row.
  **If M17.2 touches that dialog anyway, this is the moment to decide it.**
- **[12] a pre-existing overlap is never detected** on read, render, apply or
  migration. A detector at render or apply changes what `apply` does to live nodes,
  outside M17.1c's written scope. Note the fix to the rotation deadlock changed its
  character: such a node is **no longer sealed, only undetected.**
- **[21] a non-address `within`** raises `ValueError` out of `networks_overlap`.
  Unreachable for every shipped transport; the only cheap fix skips the row, which
  fails **open** on a safety rule. Left as a guard for the next transport package.

---

## From M17.2 and its fix round (2026-09-13) — the milestone as built

**Gate: `make verify` green — control 664 / 2 skipped, edge 327 / 3 skipped,
infra 177, e2e 168.**

### The gap that nearly closed the milestone with its safety property untested

`AmbiguousPeerRoute` — the refusal that stops two peers holding one address, and
therefore the backstop against the silent return-path hijack this whole milestone
is built around — **had never been asserted in any commit, in any zone.** A
reviewer proved it: delete the raise from both renderers and `make test-edge`
stayed green. The only occurrences in `tests/` were three docstrings.

Now pinned in `edge`, for both packages, parameterised over `KERNEL_TUNNELS` so
no protocol is named, using each package's own
`transport.profile.AmbiguousPeerRoute`. **Three tests, and the third matters:**
two peers handed one address; two peers with no address of their own colliding on
the one in `params` (the field failure verbatim); and **the positive half — two
peers from one pool render two distinct `/32` routes — so a package cannot pass
by refusing everything.** Mutation-verified in both directions.

### Sentence vocabulary — match it, do not re-word

- A pool **is sized for** N. A person **holds** an address. The two screens used
  to disagree about what "holds N" meant; they no longer do.
- A withheld control **states the ceiling and the next thing that will be
  refused** — never *"would be refused"*, which was false on a node that is not
  serving and on the field's own row. The withholding behaviour is unchanged and
  its decision is not reopened; only the claim was wrong.
- `addresses.named`: *"{transport} on {node} is sized for {size} and would need
  {needed}"*.

### Cross-zone couplings created deliberately — know them before you edit

- **`placement.TUNNEL_TAKEN` is quoted in the runbook and pinned by
  `tests/infra/test_deploy_runbook.py`.** Rewording that `control` constant reds
  an **infra** test. Intentional: the operator must be able to search the page
  for the dialog in front of them.
- **`addresses.named` imports `console.placed_as` inside the function** — a
  service reaching into the console projection, the opposite of the usual
  direction. Safe today (`console` imports `addresses` at module scope; `named`
  is only called at request time), but **a future module imported by `console` at
  import time that calls `named()` would cycle.** The alternative was a second
  copy of `placed_as`'s rule, which its own docstring forbids.

### Test harness

`panel_surfaces(node_id, row_id)` and `friend_surfaces(friend_id)` are now two
helpers — **walk the second for every friend**, not just one; the original sweep
opened per-friend dialogs only for the user whose address it excluded.
`enable_pool(..., tunnel=…, peer=…, port=…)` puts a second instance of one
transport on one node — it needs **its own port and its own range**.
`_text_of(response)` strips markup and Jinja comments. `"not offered —"` is the
marker for a withheld control and appears in no standing sentence.

### Known and written down rather than fixed

- **pool[0] is byte-identical to the row's own `peer_tunnel_address`** — M17.1a
  made it so, and that is what keeps a pre-M17 device working across the upgrade.
  So the first holder's address is on screen **as the row's operator-set
  parameter**, and combined with the Users ordering it is an inference about who
  holds it. Recorded in the sweep's docstring. **It cannot be fixed without
  breaking migration 0006's promise**, which is the stronger obligation.
- `console.address_note` is not gated on deliverability, so a future package
  could carry two contradictory notes. The real fix is a constraint in
  `edge/registry._check_declaration` between `peer_address` and
  `subscription_formats` — an `edge`-zone product decision, not this milestone's.
- Open item **[19]** (the replace dialog's withheld reason), the **release/apply
  window**, and the **range race** all remain open with their reasons recorded in
  `docs/decisions.md`.
