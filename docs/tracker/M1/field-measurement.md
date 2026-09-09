# M1 — the bug, measured on live hardware before the fix

Taken on the entry node, 2026-09-09, after M13 made it a working node. This is
the red-first evidence for the whole milestone: the fix has to change these
numbers.

**The sequence.** A node was applied, became `active` and `healthy`, and its
data-plane container came up. Then a friend was added — which changes the
rendered config — and the node was applied again. That second apply returned:

```
200 {"node_id":"…","transports_applied":["vless-reality"]}
```

**What the host actually shows:**

```
container started : 2026-09-09T01:39:46Z
config written    : 2026-09-09 01:48:11Z
```

The config was written **8 minutes 25 seconds after** the process that is
supposed to be serving it started. The file on disk carries the new client; the
running daemon has never read it, because `docker compose up -d` saw no change to
the *service definition* and left the container alone. Xray parses its config
only at process start.

**So the state of the world after a successful-looking apply is:**

| | |
|---|---|
| API | `200`, transports applied |
| node state | `active`, `state_detail` null |
| health probe | `reachable: true, healthy: true, drifted: []` |
| config on disk | contains the friend |
| running daemon | does not |
| the friend | cannot connect |

**The health probe says `drifted: []`, and that is the second half of the bug.**
Drift detection compares the file on disk against the digest the control plane
pushed — and those genuinely do match. Nothing anywhere compares either of them
against what the *process* loaded. The control plane is not lying; it is
answering a question that does not establish the thing an operator thinks it
establishes.

**Why this is the milestone that gates the others.** Every other fix tonight is
verified by changing a config and looking at a live node. Until this is fixed, a
correct change and an incorrect one produce the same observation.

The revocation direction is the dangerous one and follows the same mechanism: the
credential leaves the file, the subscription stops serving it, and the daemon
keeps accepting the revoked key until something unrelated restarts the container.
That is criterion 6 failing while the panel reports success.
