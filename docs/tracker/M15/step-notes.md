# M15 — step notes

Conventions established here. They bind later steps, and later milestones in this
codebase, until something supersedes them. Follow them; do not relitigate.

## Read first

`docs/tracker/M9/step-notes.md` (six sections) and `docs/tracker/M10/step-notes.md`
are the console's rulebook and still bind. `docs/tracker/M9/carry-over.md`,
`fix-notes.md`, `gate-hazard.md` and `docs/tracker/M10/infra-followup.md` are
read-only background.

---

# Established by M15.1 — what actually collides on one node

## The rule

Uniqueness moved **off `(node, transport_name)`** — the owner's decision of
2026-09-10 — and onto what genuinely collides:

- **The listening port**, qualified by the transport-layer protocol. Two rows on
  one node collide only when their ports match **and their bind sets intersect**.
  Reality on TCP 8443 and AmneziaWG on UDP 8443 are fine; nothing binds twice.
- **The config name** — the stem of the file under `/opt/hashi/conf/` and, for the
  wg-quick family, the interface `awg-quick`/`wg-quick` brings up.

Both per node. Two nodes on one port is ordinary.

**`enabled` is deliberately not consulted.** A disabled row still holds its port
and name, because freeing them would move the collision to the moment it is
switched back on. **Removal is the exit — that is M15.2.**

## `TransportMeta.listens_on` — a required `edge` contract field

`Layer4` and `listens_on: frozenset[Layer4]` live in `edge/registry.py`. **Any new
transport package must declare it**, and the edge rulebook now says so.

**It is not `family`, and that matters.** `family` is free text whose own contract
violation message says *"`control` reads it to decide nothing at all — an operator
reads it to tell UDP from TCP"*. A transport declaring `"quic"` would bucket alone
and collide with nothing, which is the M15 defect in a new coat. A **frozenset**
because a transport may legitimately bind both and the question asked is *do these
overlap*, not *are these equal*. Recorded in `docs/decisions.md` (2026-09-11).

## The port rule has NO database constraint, deliberately

Postgres cannot evaluate `listens_on` — it is a fact about a **package**, not
about a row — so an index would need a stale copy of another component's
declaration on every row. This codebase already makes that call the other way for
`config_format`, asked of the registry at every render rather than stored.

So: **`placement.port_is_free` is the only holder.** A fourth write path must call
it. `test_the_database_holds_the_half_of_the_rule_it_can_hold` asserts
`uq_node_transport_port` is **absent** from `pg_indexes`, with the reasoning — so
re-adding it fails a gate loudly rather than quietly. The **config name** keeps its
constraint, because it is ours to choose and true of the row.

**The port check is a read, not a lock.** Nothing serialises `claim` /
`port_is_free`. The window is milliseconds, the product has one operator, the
symptom is legible (a second container that will not bind, on a node not yet
applied), and the repair is remove-and-re-apply. A lock would mean a row-level
lock on a table the delivery endpoint reads, to close a race one operator cannot
have with themselves.

**An earlier version of this step wrote an unqualified port index and it was
removed in the same milestone** — it aborted the control plane's boot on a
database holding Reality/TCP 8443 beside AmneziaWG/UDP 8443, a state the runbook
puts within reach, and `entrypoint.sh` runs `alembic upgrade head` every boot.
Recorded in both the journal and migration `0004` so the next reader does not
re-add it.

## Where it is enforced

`control/app/services/placement.py`, called by all three paths that write a port:
`nodes.enable_transport`, `relay.establish_hop` (per end — the ends are on
different nodes, and a same-node hop is refused earlier), and
`rotation.replace_params` (port only, `excluding` its own row). `rotate_keys`
cannot move a port: it preserves `surviving` params.

The old `(node, transport_name)` SELECT was **deleted** from both creation paths,
not left beside the new rule.

## The interface name, and how two rows stop sharing one

`config_path` now takes a **config name**; `config_path_of(config_name,
transport_name)` splits the two questions — the file's name is ours, the extension
is the transport's. `services_for` / `probe` take an optional `transports` mapping
**defaulting to identity**, which is the historical truth for every node in the
field; a forgotten mapping raises `KeyError` rather than writing wrong paths.

`NodeTransport.config_name` stores the choice: the transport's plain name when
free, else `-2`, `-3`…, each measured against `node_stack.config_name_is_usable`.
**The first instance keeps the plain name** — renaming would take a live interface
down. The suffix is numeric and uniform; purpose-based names are not unique (a
leaf can hold two leaf ends).

Migration `0004` adds the column nullable, **backfills `config_name =
transport_name`**, tightens to NOT NULL and swaps the constraints. The backfill is
load-bearing: nothing on a live node is renamed, so the next apply writes the same
bytes to the same paths. Reversible — but the downgrade correctly **fails** on a
database where a second instance exists, which the docstring states.

## The console

`console.placed_as(transport_name, config_name)` is **the one place a transport is
labelled on a node**. It returns the bare name when the two are equal — so nothing
pre-M15 changes appearance — and otherwise `amneziawg (amneziawg-2)`. It feeds
`TransportChip.name`, `OfferRow.transport` and `KeyRow.transport`. **M15.2's
removal confirmation must use it**, or the dialog will name the wrong one of two.

The enable dialog **no longer subtracts what the node already runs** — a filter
cannot answer "is a second one legal here" without repeating `placement`'s rule,
so it does not try. Its on-screen hint says so.

## Wording acceptance will judge

`placement.PORT_TAKEN`: *"node {name!r} already listens on {protocol} port {port}
for {holder!r}. Two transports on one node cannot share a port — each data plane
binds the node's own address — so give this one a different port."*
`placement.NO_NAME_LEFT` ends *"Put this one on another node."* (the second answer
arrives with M15.2). The enable hint: *"Something already on this node can be
added again — it is refused only if it wants a listening port the node is already
using."*

## THE THING M15.3 MUST NOT MISS

**Following the runbook literally is refused TWICE, and M15 only ever named the
first.** On an **entry** node a friend-facing wg-quick-family transport gets
`Egress.HOP`, and `edge/egress.py` refuses to render it:

> *"A tunnel whose packets this node's kernel routes cannot send them out through
> a different interface… Give this node's friends a transport that terminates
> their connection and re-originates it, or take the hop away."*

So `entry-ru` now **accepts** the hop and **fails at apply** — as a
`NodeOperationFailed` with an operator-actionable sentence and the node left
degraded, not a 500. That is M14.3 and decision 3 working as designed, pinned by
`test_an_entry_node_with_a_kernel_tunnel_for_friends_still_will_not_render`.

**M15.1 alone does not unblock the field situation.** M15.3's runbook fix must
address both refusals. The **leaf** side of the same shape renders fine.

## Testing

`tests/control/test_what_collides_on_one_node.py`: `a_box_carrying_both(client,
wg_params)` (entry side — establishes, does not render) and
`a_leaf_carrying_both(client, wg_params)` (leaf side — renders). Standard
`client`/`session` fixtures, no chdir. The e2e file
`test_the_runbook_shape_a_then_the_hop_it_mandates.py` has `shape_a_box(operator,
unique)` and `side(address, peer, port)`.

`BROKEN_DECLARATIONS` in `tests/e2e/edge/test_a_brand_new_transport_package.py`
gained a `listens_on=frozenset()` case — **the empty form, not an omitted one**: a
missing field dies as `TypeError` at import and can never reach
`_check_declaration`.

---

# Established by M15.2 — removal

## What removal is

`nodes.remove_transport(session, *, node_transport_id) -> node_id` **deletes** the
`NodeTransport` row and, by the same ORM cascade plus `ON DELETE CASCADE` that
`dissolve_hop` relies on, **every `Credential` minted under it**. Verified at the
database level, not only in the ORM: `credentials_node_transport_id_fkey` is
`confdeltype = 'c'`, and a raw `DELETE FROM node_transports` removes the
credentials too. Only two FKs reference the table — `credentials` (CASCADE) and
`fk_node_transports_peer` (SET NULL), and the peer case is the one refused.

**It deliberately leaves:** the friend (**removing a protocol is not revoking a
person** — those users lose that entry from their subscription at the next
refresh and keep everything else), the audit trail (append-only), and the daemon
on the host.

**It does not push.** The caller is handed the node that needs re-applying, for
`dissolve_hop`'s reason: a removal that failed because the host is down is useless
exactly when it is needed. The operator is told in three places — the confirmation
dialog, the toast, and the API's `{"needs_apply": [node_id]}`. That instruction is
genuinely actionable: `node_stack.restart` runs `docker compose up -d
--remove-orphans` against a compose file regenerated **without** the removed
service, so applying really does stop the container.

## What it refuses

**A hop end**, 409. The service sentence names the API call that does work
(`DELETE /api/hops/{id}`, now actually substituted); the **console answers in its
own words** (`console.REMOVE_HOP_END`, *"Tear the hop down from the Hops screen:
that takes both ends…"*) because an API path is not what the panel promises. No
remove button is drawn on a hop-end row, so the refusal is typed-URL only.

## It frees exactly what `placement` claims

This is the whole point: M15.1 made a **disabled** row keep holding its port and
config name *on the promise that removal is the exit*. Proven — remove a row, then
re-enable the same transport on the same port: 201, and `config_name` comes back
as the **plain** name rather than a suffix. Removing the plain first instance
while `amneziawg-2` survives lets a new row take the plain name back.

`placement.NO_NAME_LEFT` now ends *"Remove one of them from this node, or put this
one on another."* — the second answer M15.1 deferred to here.

## The trail

A thirteenth `AuditAction`, **`transport-removed`**, labels = node name and
transport name read off the rows **before** the delete, rendered `<transport>
removed from <node>`. Distinct from `transport-withdrawn` on purpose: the row is
gone when the entry is read, so the entry is the only place the difference
survives.

**A new action must be written down in four places, and three of them are lists
that fail late.** `AuditAction`, `_EVENTS` in `wording.py`, and then
`PERMITTED_ACTIONS` and `STORED_KEYS` in the two e2e scenarios. **The e2e database
is shared across scenarios with no reset**, so a missing `PERMITTED_ACTIONS` entry
is green or red depending on **filename order** — this step's gate passed only
because `test_the_audit_...` sorts before the scenario that removes. Reproduced
red by running the removal scenario first.

**A stronger guard was proposed and not built** (out of scope here, worth doing):
a unit test that reads the e2e file's literal set with `ast` and compares it to
`AuditAction`, failing in `make test-control` seconds after the enum grows. Keep
the hand-written list — its value is that a new action must be written down a
second time where somebody asks what it records; what is fragile is the *silence*,
not the duplication.

## Re-run safety on a warm stand — a trap this step fell into

A scenario asserting an **absence** is not re-run safe on a shared stand: an
earlier run's own artefacts satisfy the thing it is proving absent. Here, the
scenario's closing re-enable left an active box, and a second run's friend was
granted it too.

**Fixed the right way, and this is the pattern to copy:** derive the endpoint per
run (`removal_port(unique)`, band 52000–55999 — a census of the dirty stack shows
every other scenario at 8443–8471, 51820–51823, 51931–51932), **and** make the
claim a **delta** — `endpoints_carrying(after) == before - 1` — so it says *one row
left this user's configuration* regardless of what else the stand holds.

The delta still discriminates: it cannot pass while the removal did nothing
(`after == before` fails), and a mere *withdrawal* would pass the delta but then
**409 on the re-enable**, because M15.1 keeps a disabled row holding its port. The
toast assertion (`"removed from"` vs `"withdrawn on"`) is the second
discriminator.

## Reusable

`nodes.remove_transport`, `nodes.REMOVE_IS_FOR_AN_OFFER`,
`console.removal_summary`, `console.REMOVE_HOP_END`, `DELETE
/api/transports/{id}` → `{"needs_apply": [node_id]}`, template
`panel/remove_transport_dialog.html`. Unit helper `a_user_on(client, node_id,
nickname)` — **activate the node, then create the friend; that order is what mints
a credential.** E2E helper `remove_from_the_panel(operator, node_id, transport)`
reads both URLs off the markup.

**Two buttons per row** in the transports dialog now, inside the existing
`.row-actions`; the e2e `withdraw_button` regex still works because it anchors on
`/withdraw`.

## Do not align this backwards

The remove route passes `exc.message` **raw** to `_mutation` with
`keeping=offer.node`. The neighbouring `_set_offered` pre-wraps in
`wording.for_the_page` and `_mutation` then translates again — **translating once
unprotected**, so a node literally named "friend" is mangled. The new route is the
correct one of the two; the comment says so.

## The scope of "gone" — accurate wording for anyone who repeats it

*"The material minted for it is gone with it"* is true of **the control plane's
database only**: the row, its encrypted `secrets`, and every credential minted
under it are deleted, and nothing this control plane will ever render, deliver or
push contains that material again.

**It is not true of the node's disk.** The rendered config — containing the node's
private key and every user's credential for that transport — was written to
`/opt/hashi/conf/<config_name>.conf` by the last apply, and **no code path in this
repository ever unlinks a rendered config.** Identical for `withdraw` and for
`dissolve_hop`, so it is a property of the product rather than anything this step
introduced. **On the field checklist** (`docs/tracker/field-checklist.md`, item 1),
because it is observable only on a real host. A product fix would be an apply that
reconciles the directory against what it just rendered — `apply`/`edge.bootstrap`,
a step of its own.
