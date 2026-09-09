# M2 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design.

- **Low — `services_for` is called outside `apply_node`'s `try:`**
  (`control/app/services/apply.py`). It can now raise
  `node_stack.UnrunnableTransport`, so a future transport with an illegal
  interface name would surface unhandled from the single-node apply path. It
  still resolves to the typed envelope, because `unhandled_error_handler` catches
  every `Exception` at the app boundary, and `apply_many`'s fan-out already
  handles it per node. **Unreachable today** — both registered WireGuard-family
  names are legal, and a unit test catches an illegal one at CI time before any
  request. Left because the catch is a `control`-zone change and this milestone's
  work was `edge`; the zone rule forbids mixing them in one diff. Flagged by the
  implementer, agreed by the reviewer, recorded here so it is not forgotten.

- **The `loaded_digests` dead filter** from `docs/tracker/M1/carry-over.md` is
  still untouched and still uncommented.

## Not a carry-over — it became a milestone

M2's second "done when", *"a client on a WireGuard-family transport carries
traffic"*, is **not discharged**, and the reason is not M2's. On the live node a
real client completed a handshake in both directions and carried nothing: the
node has no forwarding or NAT for the tunnel subnet, ufw's FORWARD policy is
`DROP`, and the rendered config has no `PostUp`/`PostDown`. That is **M14**,
appended to `docs/PLAN.md`, and it is on M3's critical path as well — the hop
needs the leaf to forward and masquerade traffic arriving over it.
