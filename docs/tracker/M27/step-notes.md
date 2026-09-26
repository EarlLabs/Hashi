# M27 — step notes
Conventions established here. They bind later steps, and later milestones in this
codebase, until something supersedes them. Follow them; do not relitigate.

## From M27.1 — what travels to a delivery host, and what is in it

**Stopped at its round cap with one High open** (carried to M27.2, below). Everything else
was verified against the code in both rounds.

**The control plane pre-renders delivery material and pushes it on apply**, placed under
`/opt/hashi` by the apply path that already exists — which places, restarts, and verifies the
daemon came back on this config and stayed up (`control/app/services/apply.py`).

**What serves it is the node stack**, running the Caddy tag the project already uses, reading
a placed directory. *"Caddy or the node stack"* was a false choice: Caddy is what runs, the
node stack is where it is declared. **The tag is chosen and reviewed, but it is not a pin a
node can use** — `deploy/docker/caddy.Dockerfile` is the control host's image in the infra
zone; node images are pinned in `edge/bootstrap/node_stack.py`, keyed by `ConfigFormat`
(2026-08-09 row). M27.2 adds one there or makes a deliberate cross-zone reference: a line of
cost, not a second decision.

**A property of the node, not a transport-like row.** A transport is what a `Credential`
points at and a subscription is rendered *from*, so a purpose that can never be granted and
must never appear in a subscription would need a carve-out at every reader of that table —
`TransportPurpose.relays()` is exactly that, at **seven** production call sites each doing
something different (`services/rotation.py:237,505,651`, `panel/routes.py:1888`,
`services/relay.py:48,570`, `services/apply.py:511`). A second one is `if transport ==`
spelled differently. The material is per-node by construction: the union over every
user-facing transport the host carries and every user holding a credential on one.

**Narrowing is possible and costs nothing in the motivating arrangement.** A subscription is a
*list* of client entries; a shorter list is valid in both shapes it is served in — `render`
answers an empty document, `archive_of` writes a note into an empty archive. Where exactly one
node carries user-facing transports, the narrowed artifact and the full subscription are **the
same document**.

**What narrowing costs from the second such node onward:** a refresh against a delivery host
returns strictly less than the control plane would, so it can **remove** working nodes from a
client — partial, in a direction a user cannot tell apart from revocation. **A pushed
subscription is not only a snapshot, it is a slice**, and M27.5 owns both halves. It also
raises the price of M27.7's multi-URL option: N delivery URLs become N disjoint slices rather
than N chances at one document.

### The gap this milestone inherits rather than a cleanup

**There is no teardown.** `docs/decisions.md` 2026-09-13 records it twice — *"there is no
teardown action anywhere"*, and an apply *"never removes what an earlier one wrote"*, measured
with a leaf's `wireguard.conf` and its `PrivateKey` still on disk after the row was deleted.
Node services carry `restart: unless-stopped`, so deleting the directory would not even stop
the containers.

**Carried to delivery: a host that STOPS being a delivery host keeps its last artifact, and
whatever token store M27.2 lands, on disk.** Worse than the measured leftover key, which was
regenerable material the node held while it served; a token is a **user's** credential and
opens the control plane's own endpoint too. **M27.4's "absent, not inert" does not cover
this** — that requirement is about the co-location arrangements, i.e. a host that never served
delivery, not one that stops.

### The one that reframes the milestone

**Narrowing removes the leaf addresses. It does not remove the tokens.** A stateless server
looks a request up by what the path carries, and the path carries the token, so the naive
store is one file per token — and a seized delivery host yields the live bearer credential of
every user it serves, in the clear, which the control **database** holds only as ciphertext
(`Subscription.token` is `EncryptedText`, lookup through a keyed digest). That token then
fetches the **un-narrowed** document from the control plane, and the same token answers both
shapes on the same route. A subscription token has **no expiry** and is the only artefact a
user holds, so the repair is re-issuing every affected URL through a channel M27.7 records the
product as not having.

**M27's done-when is not satisfied by writing this down:** it requires what a seized delivery
host yields to be *no wider than today* **or** the widening to be a recorded decision. No
non-control host holds a token today, so any token store is strictly a widening.
