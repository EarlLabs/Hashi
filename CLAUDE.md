# hashi — project conventions

A self-hosted multi-protocol VPN for the owner and ~30–50 friends, built to keep
working from Russia. A Russian **entry node** fronts foreign **leaf nodes**; both
nodes and protocols are data, replaceable in minutes without a user touching
their device.

The full statement of what this is and is not: `docs/product/charter.md`.
How the agent fleet coordinates: `.claude/workflow.md`.

## Architecture (who talks to whom)

```
friend's client ──subscription URL──► control plane (delivery endpoint,
                                        reachable from inside Russia)
owner ──admin panel──► control plane ──SSH──► entry node (RU)  ──obfuscated──►
                            │                                     leaf nodes (abroad)
                            └── renders configs with `edge` (a pure library)

control plane → node, always. A node NEVER dials the control plane.
```

## Zones

| Zone | Paths | Rulebook | Verify |
|---|---|---|---|
| `control` | `control/**`, `tests/control/**` | `.claude/projects/01-control-rulebook.md` | `make test-control` |
| `edge` | `edge/**`, `tests/edge/**` | `.claude/projects/02-edge-rulebook.md` | `make test-edge` |
| `infra` | `deploy/**`, `.github/**`, `Makefile`, `tests/infra/**` | `.claude/projects/04-infra-rulebook.md` | `make test-infra` |

A developer edits one zone. Cross-zone work is split into separate tasks, never
shared files. `docs/**` and `.claude/**` belong to no zone.

## Hard rules

- **NEVER read or print `.env`** — real secrets. Use `.env.example`.
- **Never log who connected to what.** No connection, traffic or DNS logs, at any
  level, including debug and including "temporarily, while debugging". This is a
  charter non-goal and the one record that can hurt a real person.
- **Never hardcode a country, provider, IP, domain or port** in code. It belongs
  in a node record or in configuration — a hardcoded value is a node you cannot
  rotate away from.
- **Nodes and transports are data.** No `if provider ==`, no `if transport ==`
  outside a transport's own package. A new protocol is one new package under
  `edge/transports/`.
- **`edge` is pure and `control` imports it, never the reverse.** Config
  rendering does no I/O: no database, no network, no clock, no randomness.
- **Subscription tokens are bearer credentials in a URL path.** Access logging is
  off in uvicorn and discarded in Caddy; keep it that way, and check every new
  place a path could be recorded.
- **Never ship a shared default Reality decoy destination** — if every node
  borrows the same handshake, the fleet becomes enumerable.
- **No public signup, no billing, no advertising.** All three are charter
  non-goals; the third carries a legal penalty for the owner.
- Stack is strict: Python 3.14, FastAPI, SQLAlchemy async + Postgres, Alembic
  migrations, Jinja2 + HTMX, Caddy, docker compose. **No Kubernetes** — see the
  charter for why.
- Adding a dependency is an architect decision, not an implementation detail.
- Every module gets a WHAT/WHY/HOW header comment; the owner is learning from
  this codebase, so explain non-obvious decisions where they are made.

## Commands

- `make setup` — create `.venv` and install dependencies (Python 3.14)
- `make test` / `make test-control` / `make test-edge` / `make test-infra`
- `make up` (production shape, nothing published) / `make up-dev` (loopback ports)
- `make down`, `make logs`, `make ps`
- Compose always runs with `--env-file` — the Makefile does it for you. Running
  it by hand without that flag turns every `${VAR}` into an empty string and
  nothing errors.

## Verification

`make test` proves the code holds together. It does **not** prove a tunnel
carries traffic, and it cannot prove the charter's first success criterion —
"survives a mobile whitelist shutdown" is a field observation on a real Russian
network. Never report it as covered by a test run.
