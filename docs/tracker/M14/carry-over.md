# M14 — carry-over

Non-blocking findings left open, with the reason each was left. Read them as
BACKGROUND: they tell you what is known-wrong so you do not mistake it for the
intended design. Do not fix them as part of another step.

## Read this one before enabling plain WireGuard for a friend anywhere

**M14's forwarding fix is field-proven for ONE member of the WireGuard family, and
the other one is very likely still broken in exactly M14's way.**

The two data-plane images do not agree on which netfilter ruleset their `iptables`
writes to, and the difference is invisible from the rendered config — both get the
identical `PostUp`/`PostDown` lines, because those lines are correct for both.

| pinned image | `iptables` resolves to | writes into |
|---|---|---|
| `docker.io/amneziavpn/amneziawg-go:3.0.3` | `xtables-nft-multi` (`v1.8.10 (nf_tables)`) | the **nft** ruleset |
| `docker.io/masipcat/wireguard-go:0.0.20230223` | `xtables-legacy-multi` (`v1.8.9 (legacy)`) | the **legacy** ruleset |

Measured directly in both images, not inferred. The plain-WireGuard image ships no
nft-backed variant at all (`command -v iptables-nft` finds nothing; it has only
`/sbin/iptables-legacy`), and no `ip6tables`.

**Why that matters here and nowhere else.** `scripts/node-bootstrap.sh` prepares every
node the same way, with `ufw`, and ufw on a current Ubuntu populates the **nft**
ruleset — including the `deny (routed)` FORWARD policy that dropped the packet M14 was
opened for. Legacy and nft are independently registered netfilter hooks and a packet
traverses **both**; a DROP from either is terminal. So:

* an `amneziawg` transport inserts its `ACCEPT`s into the same ruleset as ufw's DROP,
  ahead of it, and the packet lives. **Confirmed on real hardware:** a real client from
  a friend's own subscription loaded four sites, exiting at the node's address, where
  before M14 the same client handshaked and every request timed out.
* a `wireguard` transport inserts its `ACCEPT`s into the legacy ruleset, whose FORWARD
  policy is ACCEPT and where they change nothing that matters, while ufw's nft DROP
  still applies. Expect **M14's exact silent failure**: handshake completes both ends,
  interface `UP`, container `Up`, bytes counted, nothing moves, nothing logged — and
  nothing should be logged, that is charter.

Confirmed three ways before this was written: by probing both images, by the reviewer
independently, and on the live node — `iptables -S FORWARD` shows the `amneziawg`
`ACCEPT`s ahead of ufw's DROP, and `iptables-legacy -S FORWARD` shows the `wireguard`
ones sitting in a separate table with policy ACCEPT.

**Why it was left.** The fix is a different image pin, and a data-plane pin is an
architect decision (core invariants §5, `CLAUDE.md`) — it is the owner's call, not an
implementer's, and M14's scope was the rules rather than the images that run them.
There is no code change that repairs it: the rendered lines are already right.

**What this does NOT mean.** Plain WireGuard is not broken as a protocol here and its
config is not wrong. It is one packaging fact about one pinned image. Note also that
the transport is `hop_capable=False` and `blocked_by_inspection=True`, so it was never
going to carry a border-crossing hop — the exposure is a friend-facing `wireguard`
transport on any node, which is a configuration an operator can make today.

## Minor

- **A friend whose tunnel address is outside the interface's own network is forwarded
  and never masqueraded.** The `FORWARD` rules are scoped to the interface (`-i %i` /
  `-o %i`) and therefore cover every peer, but the `MASQUERADE` is scoped to the source
  range derived from the interface's own `tunnel_address` — so a peer allocated outside
  that prefix passes the first two rules and is skipped by the third. The result is
  M14's quiet failure for that one friend while every other friend on the same node
  works, which is a worse thing to debug than a node that is uniformly dead.

  Nothing validates a peer address against the interface's subnet: `peer_allowed_ips`
  derives a `/32` from whatever address the credential carries, and the renderer's only
  refusal is for two peers claiming ONE address. In practice an operator allocates from
  the interface's prefix, and nothing allocates automatically yet (backlog item 33), so
  this is reachable only through a hand-typed address. Left out of M14 deliberately: it
  is a new refusal in a renderer, which would degrade a node on a config that renders
  cleanly today, and that is a decision rather than a fix. Flagged by the implementer,
  confirmed by the reviewer.

- **`net.ipv4.ip_forward` is relied on, and nothing in this project sets it.** It was
  `1` on the field host, and it is `1` on any hashi node because dockerd sets it at
  every start and a node must have docker — but that is a side effect of a dependency,
  not a property anybody stated. It cannot be set from where M14 put everything else:
  `/proc/sys` is mounted read-only inside the container, so the config's own hooks
  cannot reach it. The obvious home is `scripts/node-bootstrap.sh`, whose header
  explicitly says it "does not tune the kernel" (non-goal E), so putting it there is a
  decision about that script's contract rather than an M14 detail. If it is ever `0`,
  the symptom is M14 again, exactly. Checked in the field with `sysctl net.ipv4.ip_forward`.

## Not a carry-over — it is the shape M3 builds on

The egress policy is data (`edge/egress.py`, `control/app/services/nodes._EGRESS`, keyed
on `node_transports.purpose`). M3's "route friend traffic into the hop" is a third value
in that same table and a change to `edge.relay.render_hop`'s own call — not a new
mechanism, and not a branch on a transport.
