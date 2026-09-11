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
