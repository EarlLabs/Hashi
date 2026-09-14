# M20 — acceptance: **good** (2 rounds, both blocks closed)

## Verdict

**Round 1 — blocked** on two findings, both pre-existing defects the walk
surfaced rather than anything M20 introduced.
**Round 2 — both closed; blocked again on one finding outside M20's checklist**,
which the walker said so explicitly. The orchestrator overruled an earlier
decision and had it fixed.

**All five done-when passed in both rounds.**

| done when | verdict |
|---|---|
| Not in the panel's suggestions, anywhere | **good** — zero occurrences of `wireguard` in the enable form's markup; no `wireguard-*` param field at all |
| Retired by a declaration, not a name | **good** — visible through `GET /api/transports` as `retired` + `retired_because` |
| An already-enabled row still renders, friend unchanged | **good** — verified against actual bytes |
| `AmbiguousPeerRoute` + contract tests over both packages | **good** — confirmed by the reviewer; acceptance could not confirm from outside (it searched test *names*, and the tests are named by behaviour) |
| `management-tunnel.sh` untouched and works | **good** — ran twice into throwaway dirs, fresh per-run material both times |

## What the walker proved, against bytes rather than claims

- Plain `/sub/{token}` → **200, `text/plain`, 328 bytes**, base64 of **exactly one**
  vless URI — and **byte-identical** after enabling, withdrawing and re-offering a
  config-file transport.
- `?format=client-config-file` → **200, `application/zip`**, one complete `.conf`
  per serving node: `PrivateKey`, pool `Address`, `MTU`, all four obfuscation
  headers matching the node, peer `PublicKey`, `PresharedKey`,
  `AllowedIPs 0.0.0.0/0, ::/0`, `Endpoint`, `PersistentKeepalive`. **Importable
  as-is.** The archive tracked **3 → 2 → 3** files across withdraw/offer while the
  link body never moved.
- The amneziawg hop still **creates (201, both ends written)**; the vless hop is a
  **400 naming the real cause**, not a 500.
- The Overview tile moved **0 → 2 → 1**, each value equal to the database's count
  of distinct transports on active nodes.

## Round 1's two blocks — both pre-existing, both fixed

**1. A sentence promising delivery it could not make.** Every enabled row said
*"offered — in every user's link at their next refresh"*, including rows that are
not in the link body.

**The important part is that round 1's other half was ALSO false.** The
Transports screen said *"not in a user's link yet — this panel cannot hand it
over"* — and the product **can** hand it over, at
`/sub/{token}?format=client-config-file`. **A fix that corrected only the
sentence the walker flagged would have replaced one falsehood with another, and
the suite would have been green either way.** Both were corrected.

*(This same discovery corrected a milestone the orchestrator had written on the
false premise — see M24 in `docs/PLAN.md`.)*

**2. A 500 on a path the API advertised.** `POST /api/hops` with `vless-reality`
returned HTTP 500 (`KeyError: 'tunnel_address'`) while `GET /api/transports`
advertised `hop_capable: true` for both vless transports.

Root cause, and it is the interesting one: **`hop_capable` is a *permission*, not
an ability.** It defaults to `True`, so a transport never shaped like a hop end
declares nothing and reads as *able*. The real ability is a per-consumer tunnel
address — `edge/relay.py` is written end to end in terms of it. Closed by a
derived `TransportMeta.hop_expressible`. Along the way: `hop_transports` had been
asking `not subscription_expressible and hop_capable` — **two proxies that
excluded vless for the wrong reason and only by luck.**

## Round 2's block — outside the checklist, and overruled deliberately

**A retired transport could still be enabled through `POST /api/nodes/{id}/transports`** — 201, `enabled: true`, rendering a complete WireGuard credential into a friend's archive, while `GET /api/transports` reported `"retired": true`.

The walker framed it correctly: M20's done-when promises retirement is *visible*
through the API, which it is; *enforced on every route* was never in the
checklist. **"If the API is a deliberate expert escape hatch this is an override,
not a code fix."**

It was deliberate — the implementer chose it and the reviewer agreed. **The
orchestrator overruled it**, because the owner had said they lean toward dropping
the protocol entirely, and because the consequence is not a bad status code but a
friend with a dead tunnel.

**Building the fix proved it was worse than reported.** With the refusal
disabled, enabling on an **already-serving** node returned a minted public key —
and `enable_and_grant` fans out to **every active friend in the same
transaction**. So it was never "a row the operator asked for"; it was **a live
credential on every friend's device at their next fetch, for a tunnel that
carries nothing.**

The implementer's own retraction is worth keeping: *"The M17 reason cost one
11-line fixture to solve. A reason worth one fixture should never have held a
silent-failure refusal open."*

**A consequence named rather than defended:** there is now **no override
anywhere**. If the owner removes their leaf's `wireguard` row by mistake, nothing
in the product can recreate it — the way back is deleting the `retired=` line in
the transport's meta.

## Charter — checked twice, clean

Zero occurrences of the token, `/sub/`, `format=`, `client-config` or a nickname
in the control, Caddy or database logs. **No access-log file exists**; Caddy
discards the default logger and every site block. The audit table holds operator
actions only (`transport-enabled | entry-ru | amneziawg`) — no addresses, no
destinations. No user's address on any of the eight panel screens. Refusals carry
reasons, never key material. The Reality decoy field is empty with the hint
*"per-node decoy site; never a project default"*.

## Could not — needs the field

**The retirement's own premise.** Someone must import `wg-<node>.conf` on a
prepared node, watch the handshake succeed, and confirm **no packets traverse**.
That is the measurement M20 rests on, made twice on the live leaf by reading
firewall tables — but never by watching a client fail to carry traffic.

Nothing here proves any tunnel carries traffic: documentation-range addresses, no
config applied to a host. **M23 covers what the leaf can answer.**

## Note on rounds

**No round 3 was walked.** Round 2's block was outside M20's checklist, is fixed
with mutation proof on eight separate claims, and M23 — the real-host walk — will
exercise the retirement end to end on hardware. Recorded so the shortfall is
visible rather than implied.

## Two operational notes for the owner

- **`make up-dev` collides with the control test database.** Both want Postgres
  on `54132`, so `up-dev` fails while `hashi-test-db` is running. Use
  `scripts/acceptance/stand.sh`, or stop the test database first.
- The acceptance driver cannot operate a native `<select>`, so transport and
  state choices went through the product's own POST endpoints. The picker's three
  options were verified in **both** the rendered markup and the accessibility
  tree.
