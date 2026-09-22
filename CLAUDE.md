# hashi — project conventions

A self-hosted multi-protocol VPN for the owner and ~30–50 users, built to keep
working from Russia. A Russian **entry node** fronts foreign **leaf nodes**; both
nodes and protocols are data, replaceable in minutes without a user touching
their device.

The full statement of what this is and is not: `docs/product/charter.md`.
How the agent fleet coordinates: `.claude/workflow.md`.

## Architecture (who talks to whom)

```
user's client ──subscription URL──► control plane (delivery endpoint,
                                      reachable from inside Russia)
owner ──admin panel──► control plane ──SSH──► entry node (RU)  ──obfuscated──►
                            │                                     leaf nodes (abroad)
                            └── renders configs with `edge` (a pure library)

control plane → node, always. A node NEVER dials the control plane.
```

## Zones

| Zone | Paths | Rulebook | Verify |
|---|---|---|---|
| `control` | `control/**`, `tests/control/**`, `tests/e2e/control/**` | `.claude/projects/01-control-rulebook.md` | `make test-control` |
| `edge` | `edge/**`, `tests/edge/**`, `tests/e2e/edge/**` | `.claude/projects/02-edge-rulebook.md` | `make test-edge` |
| `infra` | `deploy/**`, `.github/**`, `Makefile`, `scripts/**`, `.e2e/**`, `.env.example`, `tests/infra/**`, `tests/e2e/infra/**` | `.claude/projects/04-infra-rulebook.md` | `make test-infra` |

Solo topology: Ohno owns every zone (no per-zone developer). Cross-zone work
still stays in separate tasks, never mixed in one diff — the zone split exists
for `CLAUDE.md`'s own table and for how acceptance scenarios are organized
(`tests/e2e/<zone>/`), not to hand a zone to a second agent.

`docs/**`, `.claude/**` and `pyproject.toml` belong to no zone. `pyproject.toml`
is architect territory on purpose: adding a dependency is an architect decision,
so a developer who needs one asks instead of editing.

## Hard rules

- **NEVER read or print `.env`** — real secrets. Use `.env.example`. Same rule
  for `.env.e2e.live.secrets` (real, spend-capped e2e `live`-tier credentials —
  see `docs/e2e/README.md` §8 in Kaizen): edit via its `.example` template,
  never read the real file. `.env.e2e.generated` is throwaway and fine to read.
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

## Published ports and credentials

This project's published-port block is **54100–54299, loopback only**, driven
from `.env`: `+00` app HTTP, `+32` Postgres, `+90` gRPC; the e2e stack takes the
next hundred so both can run at once. Inside the compose network services keep
their standard ports — those never collide. **Never publish a service default**
(`5432`, `6379`, `8000`, `3000`): the host already runs something, and Kaizen's
own dev overlay publishes `127.0.0.1:5432`.

| | dev | e2e |
|---|---|---|
| control HTTP | `54100` | `54200` |
| Postgres | `54132` | `54232` |

The fleet's git credential is `GH_TOKEN` in `deploy/warden/.env` (its own env
file, separate from this project's root `.env`), wired into git and `gh` by
`deploy/warden/entrypoint.sh` at boot. **No agent ever reads it** — `git push`
and `gh pr create` already work. Empty `GH_TOKEN` is a supported mode: the
project stays local-only and reports changed files instead of a PR.

## Commands

- `make setup` — create `.venv` and install dependencies (Python 3.14)
- `make verify` — **the gate**: the three static zones, then the e2e stand booted,
  `tests/e2e/` run against it, and the stand torn down. Needs a docker engine and
  **fails** without one rather than skipping
- `make test` / `make test-control` / `make test-edge` / `make test-infra` — the
  static half only, no Docker. `make e2e-verify` is the other half on its own
- `make up` (production shape, nothing published) / `make up-dev` (loopback ports)
- `make down`, `make logs`, `make ps`
- `cd deploy/warden && make up` / `login` / `down` / `logs` / `vendor-kit` — the
  tracker integration, its own stack with its own Makefile and `.env`,
  independent of the product stack. Work arrives from the Hub by dispatch;
  there is no `/next` and nothing polls a queue.
- `make e2e-secrets` / `e2e-secrets-live` — regenerate e2e tokens (see
  `.e2e/profile.yml` and `docs/e2e/README.md` in Kaizen).
- Compose always runs with `--env-file` — the Makefile does it for you. Running
  it by hand without that flag turns every `${VAR}` into an empty string and
  nothing errors.

## Verification

`make verify` is the gate. `make test` is its static half and is a **smaller
claim**: it excludes `tests/e2e/` on purpose, because a `make test` that silently
needs Docker is one that gets skipped. That exclusion is fine; what was not fine
is that for eleven milestones nothing else included those scenarios, and one of
them had been failing since the day it was written. Gate on `make verify`.

Neither proves a tunnel carries traffic, and neither can prove the charter's first
success criterion — "survives a mobile whitelist shutdown" is a field observation
on a real Russian network. Never report it as covered by a test run.
