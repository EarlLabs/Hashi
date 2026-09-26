# Data plane rulebook — hashi

<!--
WHAT: The rules for working inside the `edge` zone: transport profiles, node
      bootstrap, config rendering, health probing.
WHY:  this zone decides whether a node survives a censor. Its rules are about
      indistinguishability and disposability, not about code style.
HOW:  pre-read by every agent that touches `edge/**` or `tests/edge/**`.
-->

## Stack

- **Python 3.14**, same interpreter and dependency file as `control`.
- **Jinja2** for config templates — the same rendering engine, different job.
- **asyncssh** for node bootstrap and probing. SSH is the only channel to a node.
- Upstream data-plane software, configured and never reimplemented:
  **Xray-core** (VLESS + Reality + XTLS-Vision), **AmneziaWG**, **WireGuard**,
  **Caddy** (camouflage fronts only). All run as pinned container images on the
  node under `docker compose`.

## Layout

```
edge/
  transports/
    <name>/
      meta.py        TransportMeta: name, family, needs_tls, listens_on, port range
      params.py      Pydantic model for this transport's parameters
      render.py      render_server(node, params) -> str
                     render_client(node, credential) -> ClientEntry
      server.j2      the server config template
  registry.py        discovers transports/<name>/ packages — never a hardcoded list
  bootstrap/         SSH: install, place compose files, start, verify
  health/            liveness probing, initiated by the control plane
```

**Where a new file goes:** a new protocol is a new directory under `transports/`
and nothing else. If a change needs an edit in `registry.py`, the profile
contract is too narrow — say so instead of special-casing. One exception exists,
scoped to the first transport only — see *Completing the contract* below.

## Idioms — how code is written here

- **A comment says what this code does and why; never what another module
  does.** `edge` is pure and is imported by `control`, so a comment here that
  describes what `control` does with a rendered config cannot see the thing it
  describes and will not be corrected when it changes. Record the decision and
  the rejected alternative — that is what a reader cannot recover from the
  source — and name anything outside this package rather than paraphrasing it.
- **Rendering is pure.** `render_server` and `render_client` take data and return
  data: no database, no network, no filesystem, no clock, no randomness. Key
  material is *passed in*, never generated inside a renderer.
  *Why: purity is what makes golden-file tests meaningful and drift detectable.*
- **I/O lives only in `bootstrap/` and `health/`**, and is always initiated by the
  control plane over SSH. Nothing in this zone opens a listening socket.
- **Every rendered config is validated before it is handed over** — with the
  upstream binary's own checker (`xray run -test -config <file>`, `wg-quick
  strip`), not a regex of ours. A config we believe is valid is not a config the
  daemon accepts.
- Templates render **complete** configs. No fragment concatenation, no
  post-processing of rendered text with string replacement.

## Interfaces this zone exposes

The **transport profile contract** — the whole reason this zone exists. Every
package under `transports/` provides exactly:

| Symbol | Shape | Must be true |
|---|---|---|
| `META` | `TransportMeta` | unique `name`, protocol family, whether it needs TLS, `listens_on`, port range |

**All five of those are required — they have no defaults, so a `META` missing one
raises `TypeError` at import, before `registry._check_declaration` can say which.**
`listens_on` is a `frozenset[Layer4]`: which transport-layer protocols this
transport's listener actually binds. `control` reads it for exactly one decision —
whether two transports on one node may hold the same port number (M15) — and it is
not `family`, which is free text this contract says `control` reads to decide
nothing at all.
| `Params` | Pydantic model | every knob validated: ports in range, hostnames resolvable-shaped, no free-text passed to a shell |
| `render_server(node, params) -> str` | pure | deterministic; identical inputs → identical bytes |
| `render_client(node, credential) -> ClientEntry` | pure | the transport's own finished serialisation of one client entry, plus protocol-agnostic metadata — see below |

`control` consumes only this contract. A transport that requires the control
plane to know its name has broken the charter's "new protocol is one package".

### What `render_client` returns, and why it is not a dict of parts

The v1 subscription format is a base64-encoded list of client-entry URIs
(`docs/product/charter.md`, amendment A). Every part of a VLESS + Reality URI is
protocol-specific: the scheme *is* the protocol name, and the query carries
`security`, `pbk`, `sid`, `fp`, `sni`, `flow`. If `control` assembled that URI
from a dict of parts it would have to branch on the protocol — breaking core
invariants §1 and the charter's fourth success criterion in the same move.

So the transport owns its serialisation end to end. `render_client` returns a
`ClientEntry` carrying:

| Field | What it is |
|---|---|
| `entry` | the complete serialised client entry for this node × this transport — one line, ready to place in the subscription, **without a display label** |
| `display_label` | the human-readable name this entry should show in a client |
| `country_label` | the exit country, taken from the node record's location label — **never** a geo lookup on the node's address |
| `node_id` | which node this entry points at, so `control` can order, filter and revoke without ever parsing `entry` |

`control`'s half of the contract, and all of it: order the entries, compose the
display text from `display_label` and `country_label`, append it as the URI
fragment, join, base64-encode. It treats every field as opaque text — it never
parses `entry`, never branches on any value, and never compares a label or a
transport name against a literal. Labelling stays in `control` deliberately: the
fragment is a property of the *subscription format*, shared by every scheme in
it, so the charter's one-link-many-countries behaviour is written once instead of
once per transport.

The test of this contract is arithmetic: adding a transport adds **zero** lines
to the subscription renderer.

A transport whose serialisation cannot carry an externally appended display
label is not deliverable in the v1 subscription format. That is a question about
*which transport to ship*, and it belongs to the PO — it is not a licence to move
assembly back into `control`.

### Completing the contract — authorised once, in the first transport

Two symbols in the table are ahead of the code, and closing that gap is a
deliberate, single, architect-authorised act:

- `TransportMeta` (`edge/registry.py`) carries `name`, `family` and `needs_tls`,
  and **not** the default port range the table requires;
- `ClientEntry` does not exist yet.

Adding both to `edge/registry.py` is authorised **inside M1 item 1
(`edge-transport-contract-vless-reality`) and only there** — architect decision,
recorded in §7.2–§7.3 of
`docs/tracker/product-owner-ohno-4/tasks/xavier-review-ohno-product-owner-ohno-4.md`.
This is the contract being completed for the first time, not widened to fit a
special case, which is why it is not the failure the rule above describes.

From the second transport onward that rule applies unchanged and without appeal:
**a transport that needs an edit to `registry.py` is a contract failure.** Stop
and raise it with the architect. The contract is fixed by its first
implementation; every transport after it is one directory and nothing else.

## Testing

- **Golden-file tests** for every transport: a fixed node record plus fixed
  parameters render to a checked-in expected config, compared byte for byte.
  A diff in the golden file is a deliberate act, reviewed as such.
- **Validation tests** run the upstream checker when the binary is present, and
  **skip loudly** (`pytest.skip("xray binary not present")`) when it is not.
  Never silently pass — a skipped validation that reads as green is how a broken
  config reaches a node.
- Unit tests only for pure branchy logic: parameter validation, port allocation,
  client-entry serialisation.
- Acceptance scenarios go in **`tests/e2e/edge/`** — owned by this zone, so two
  developers never meet in one file. `make test-edge` does not run them: start the
  disposable stack with `make e2e-up`, then `make test-e2e`, and say in your
  status file which of the two you actually ran.
- Fixtures use **fake keys and reserved example domains** (`example.com`,
  `192.0.2.0/24`, `2001:db8::/32`). Never a real decoy host, never a real key.

## Verification

```bash
make test-edge
```

Runs `ruff` over `edge/` and pytest over `tests/edge/`. Green proves configs
render deterministically and match their golden files. It does **not** prove the
daemon accepts them (only the validation tests do, and only when the binary is
present), and it proves nothing about whether the transport survives DPI — that
is a field observation, never a test result.

## Traps

- **A shared Reality decoy destination is a fingerprint.** If every node borrows
  the same site's TLS handshake, the set of hashi nodes becomes enumerable. The
  decoy is a per-node field with no project-wide default.
- **Never reuse key material across nodes.** One seized node must not reveal
  anything about another. Keys are generated per node, per transport, and passed
  into the renderer — never derived inside it from something shared.
- **Plain WireGuard only on links that never cross the Russian border.** It is
  protocol-blocked by TSPU. The entry-node → leaf-node hop *does* cross it and
  must use an obfuscated transport like anything else.
- **UDP transports need explicit MTU handling.** The entry→leaf hop is a tunnel
  inside a tunnel; the default MTU fragments, and the symptom is "TLS works, large
  downloads hang", which nobody debugs as MTU on the first day.
- **Time skew breaks every TLS-based transport.** Node bootstrap must ensure time
  sync before starting Xray, or Reality handshakes fail with errors that look
  like blocking.
- **A node that fails halfway through bootstrap is `degraded`, not `active`.**
  Routing a user onto a half-configured node produces a bug report about the
  client, not about the node.
