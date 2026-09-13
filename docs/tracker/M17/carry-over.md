# M17 — carry-over

## Counts

| source | Blocking | Medium | Low |
|---|---|---|---|
| M17.1a review | 0 | — | — |
| M17.1b review (2 independent reviews, 6 + 5 lenses) | 1 (fixed) | 8 | 16 |
| M17.1c review (6 lenses) | 0 | 11 | 12 |
| M17.2 review (6 lenses) | 0 | 3 | 14 |
| acceptance round 1 | 1 (fixed) | — | 4 awkward |
| acceptance round 2 | 0 | — | 6 awkward |

**Nothing blocking is open.** Both blockers were closed inside the milestone and
each has a regression test that was mutation-verified red.

Every Medium and Low above was either fixed in a review round or is listed below
with a reason. The review rounds' full finding lists are in the workflow
transcripts; what survives is here.

## Open, with reasons recorded in `docs/decisions.md`

**[19] The replace dialog withholds a refusal's reason for a stored optional
parameter.** Console-only, reachable only for an API-created row. Every real fix
either widens `_refused_parameters`' printable allow-list — relitigating the
2026-09-10 redaction decision that helper exists to carry — or renders a box for
optional parameters, which is a new surface. M17.2 correctly did not touch that
dialog, so it did not decide it.

**The release/apply window.** A revoked friend's address is freed at revoke's
commit, before the node is re-applied. **Mostly safe, and the reason is worth
knowing:** a failed push runs `_record_failure` (inside `apply_node`'s try at
line 417), marking the node `degraded`, and `NodeState.serving()` is `(ACTIVE,)`
— so `serving_transports` excludes it and `create_friend` grants nobody on that
row. **The hole is an operator returning such a node to serving by hand without
applying.** Closing it needs a column the schema does not have — *which addresses
a node was last applied with*, not a digest of the file — plus a rule at that one
door, plus a decision about what to do when the answer is "we do not know", which
is every row upgraded before that column exists. A step, not a paragraph.

**The range race.** `placement.tunnel_network_is_free` is an unserialised read.
Left open **deliberately, and the header now argues its own risk instead of
borrowing the port rule's** — which was the actual defect a reviewer found, since
the port race degrades into a container that will not bind (legible, repairable)
while this one degrades into the silent hijack. Closing it needs a per-node lock
taken by every writer of that node's rows, but `relay.establish_hop` writes rows
on **two** nodes in one transaction, so it needs a fixed lock order or two hops
laid in opposite directions deadlock — a 500 in exchange for a race one operator
cannot have with themselves (decision 8).

**`set_node_state` has no pool pre-check**, unlike `offer`. Deliberate: returning
a node to service is the operator's recovery path from a failed apply, so a
pre-check would leave a fleet carrying one short row **unable to be brought back
at all** — including the field's own pre-pool row this milestone exists to repair.

**`console.address_note` is not gated on deliverability**, so a future package
could carry two contradictory notes. The real fix is a constraint in
`edge/registry._check_declaration` between `peer_address` and
`subscription_formats` — an `edge`-zone product decision.

## From acceptance — works, but awkward

**1. A friend who opens their link gets an empty page. ← look at this one next.**
`GET /sub/<token>` → 200, `content-length: 0`. The configs come only from
`?format=client-config-file`, which no screen mentions. The Transports screen
says *"not in a user's link yet — this panel cannot hand it over"* while the
subscription dialog says *"One URL, every serving node"*.

**Not M17's defect** — wg-family transports have no URI form, so they are not in
the subscription body. But M17 just made a WireGuard row able to carry the whole
fleet, so **how a friend actually receives it is now the first question**, and the
two screens contradict each other about it. Acceptance, independently, said this
is the one it would look at next. **Recommend a milestone of its own.**

2. The plain filename `wg-<node>.conf` rebinds between rows when a node carries
   `wireguard` and `wireguard-2` — names permute across a withdraw/re-offer;
   addresses never moved.
3. The **API** set-active refusal states a hypothetical as fact — *"its pool holds
   4: 4 are taken"* when nothing is taken. The panel's wording is right; the API's
   is not.
4. In-dialog pool refusals name node and transport only by context, not in the
   sentence.
5. The Users screen column "nodes served" counts node-transports (`3 / 3` with two
   nodes).
6. The hop dialog's `peer_tunnel_address` hint still carries its friend-facing
   half, and the two wg packages word the same box differently.

## The finding worth remembering beyond this milestone

**`AmbiguousPeerRoute` — the refusal that stops two peers holding one address, and
therefore the only backstop against the silent return-path hijack — had never
been asserted in any commit, in any zone.** A reviewer proved it by deleting the
raise from both renderers and watching `make test-edge` stay green. The only
occurrences in `tests/` were three docstrings.

It is now pinned in `edge` for both packages, **including a positive half so a
package cannot pass by refusing everything**, and mutation-verified in both
directions. This was the eleventh instance in this run of the defect class *"a
verification that cannot fail"* — and the most consequential, because it guarded
the property the whole milestone was written to protect.
