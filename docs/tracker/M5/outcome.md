# M5 — outcome

**One commit, `edge` zone, five files under `tests/e2e/edge/`. One review round,
CLEAN — no findings at any severity.** `acceptance: no` per the plan.

**Gate at close:** `make test` green — 188 control, 230 edge (3 skipped), 96
infra. The four new scenarios: 49 tests in 61s; the whole `tests/e2e/edge`
directory 74 passed in 113s, with a real Docker engine.

## The "done when" was a demonstration, and it was demonstrated

> Reverting any of M1–M3 turns a specific scenario red.

Performed by the implementer and **independently reproduced by the reviewer for
all three**:

| revert | what went red | what stayed green |
|---|---|---|
| M1 — the digest label | **only M5.3**, 14 assertions across all four transports | M5.1, M5.2, M5.4 |
| M2 — `command=("up", …)` | M5.1, with `exec: "up": executable file not found in $PATH` | — (M5.2–M5.4 *error*: nothing starts) |
| M3 — the hop's egress policy | **only M5.4**, two assertions | M5.1, M5.2, M5.3 |

The word that matters is *only*. A suite that goes red when anything breaks is
an alarm; one that names which thing broke is a test.

## What each scenario proves, and what it does not

All four need a real Docker engine. Each file states its own non-proofs; the
reviewer checked those lists are accurate and complete.

- **M5.1** starts the *whole rendered argv* against the real image — the gap the
  three existing sibling checks name themselves and none of them closed
  ("`awg-quick` exec-ing is not `awg-quick` accepting that config"). It does not
  prove a tunnel forms.
- **M5.2** every transport reaches `running`, same container id and
  `RestartCount 0` after 8s. Not reachability, not port availability on a node.
- **M5.3** is the milestone's centre: M1's own unit test says in its header that
  it cannot prove Docker recreates on a label change. **This does, for real** —
  and also reproduces the field-measurement state exactly, a file changed under a
  running daemon reporting `stale=[…], drifted=[]`.
- **M5.4** two containers, two networks, minted X25519 keys, a real AmneziaWG
  handshake, and the *control* that makes it discriminating: through the hop the
  destination sees the leaf, by the entry's own route it sees the entry. It does
  not prove any border crossing, carrier NAT, DPI, a whitelist shutdown, the
  obfuscation, or any MTU path — a bridge does not fragment as a tunnel-in-tunnel
  across the internet does. And it *sets* the `ip_forward`/`rp_filter` a real node
  is merely assumed to have, so it is more permissive than a node.

## Why this milestone was cheaper to build tonight than it would have been first

The plan sequenced M5 after M1–M3 so its scenarios could be written red against a
node known to be broken. What actually happened is better: all three were fixed
*and proven on real hardware* first, so each scenario was written against a
mechanism whose behaviour had been observed rather than inferred, and the
red-first step became a re-run rather than an archaeology exercise. The field
proofs in `docs/tracker/M1`, `M3` and `M14` are effectively this suite's
specification.
