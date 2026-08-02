# express-the-transport-contract-in-code-and-ship-the-first-tr-12

**Type:** feature (`/develop`)
**Epic:** `directive-90be25f3-9` — task 3 of 18 (M1, backlog item `1`
`edge-transport-contract-vless-reality`)
**Zone:** `edge` — single zone, single developer (`dev-neumann`).

**Goal:** complete the transport-profile contract in `edge/registry.py` and ship
its first implementation — a pure renderer producing a VLESS + Reality +
XTLS-Vision server config and a client entry for a described node — so that every
future protocol is one new package under `edge/transports/` and the control plane
never learns a protocol name.

**Review baseline:** `50fe8c1cd2e82cddd1e4d4bc1db5690eeceaec3e` (= `origin/develop`).
**Branch:** `task/3-express-the-transport-contract-directive-90be25f3-9`.

**Acceptance:** the six frozen scenarios S1–S6 of
`docs/research/product-owner-ohno-4/research.md` §3 item 1. **S2 cannot execute
in this environment** (no Xray binary — it arrives in task 4) and skips loudly.
