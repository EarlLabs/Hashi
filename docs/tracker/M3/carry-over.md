# M3 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design.

## Promoted out of carry-over into a milestone

- **The DNS lookup still happens on the entry, in Russia.** `sendThrough` binds
  the TCP socket to the hop; nothing binds the *lookup*. A friend's exit address
  is the leaf's and their destination names are resolved from Russia. That is
  now **M16** in `docs/PLAN.md`. Not made worse by M3 — before M3 both were in
  Russia — but M3 moved one and left the other.

## Left open

- **`ip` is not declared in `DataPlane.executables`** for either WireGuard-family
  entry, although `PostUp`/`PostDown` now run `ip rule` and `ip route` under
  `Egress.HOP`. M2.2's offline command check therefore would not catch a future
  pinned image without `iproute2`. Confirmed by hand that the current amneziawg
  image ships `iproute2 6.6.0`. Adding it needs
  `tests/edge/golden/image-facts.json` re-recorded, which needs the network.
  **Failure mode if it ever bites is loud** — the container fails to start under
  `set -e` and the node degrades — not silent, which is why it was left.

- **`rp_filter` must be `0` or `2` on an entry node** for replies arriving on the
  hop interface to be accepted. Nothing in this project can set it: `/proc/sys`
  is read-only inside the data-plane container, the same constraint
  `docs/tracker/M14/carry-over.md` already records for `ip_forward`. Both field
  hosts happen to ship `2`, and the two-hop was verified working on them, so this
  is not a regression today. It belongs with `scripts/node-bootstrap.sh`'s
  "does it tune the kernel or not" question, which is a decision rather than a
  fix.

- **One routing-table number per node (`51821`).** Two hops dialled from the same
  node would collide. `exit_through_hop` refuses that combination out loud rather
  than silently picking one, so the failure is a readable message, not a wrong
  route.

## Verified NOT a problem, recorded so it is not re-litigated

- **The zone deviation was the right call.** The edge commit touches one function
  in a `tests/control/` file, because that test asserted "neither end of a hop
  exits locally" and the edge change deliberately makes that false for the leaf.
  The reviewer looked for a third sequencing honouring both the zone rule and
  M1's no-red-intermediate lesson and **found none**: M1's "additive first"
  prescription applies to an API *signature* change where both shapes can
  coexist, whereas this is a *behavioural* change inside `edge/relay.py` itself —
  the assertion becomes false the moment the edge commit lands, whichever commit
  edits it. Splitting would relocate the red gap, not remove it.

- **The entry's wide `AllowedIPs` does not endanger the control plane's SSH.**
  See `docs/decisions.md` and `field-proof.md`: `Table = off` plus source-based
  policy routing, with the main routing table verified untouched on the live host
  and SSH surviving the apply.

- **`sendThrough` is validated, not silently ignored.** The reviewer ran the
  pinned `xray 1.8.24` binary directly: a malformed value is refused at config
  test time, and an address absent from the host fails the connection with
  `EADDRNOTAVAIL` — **and emits no log line at `loglevel: warning`**, which is
  what the no-connection-logging rule requires.
