# Deployment and operations rulebook — hashi

<!--
WHAT: The rules for working inside the `infra` zone: the compose stacks, Caddy,
      CI, backups, secret handling and the Makefile.
WHY:  this zone decides whether the control plane can be moved to another host
      in an afternoon — which the charter treats as a survival property, not an
      operational nicety.
HOW:  pre-read by every agent that touches deploy/**, .github/**, the Makefile
      or tests/infra/**.
-->

## Stack

- **Docker Compose v2** (`docker compose`, never the legacy `docker-compose`).
- **Caddy** — TLS termination and the admin panel front, plus camouflage fronts
  on nodes. Automatic ACME; no hand-managed certificates.
- **PostgreSQL 16**.
- **GitHub Actions** for CI.
- **GNU Make** — the project's verbs. Every operation an owner performs has a
  Make target; a documented `docker compose` incantation that is not in the
  Makefile is a bug in this zone.

## Layout

```
deploy/
  docker-compose.yml       base stack — production shape, NOTHING published
  docker-compose.dev.yml   dev overlay — the only file that publishes ports
  docker/                  Dockerfiles, one per service
  caddy/Caddyfile          reverse proxy config
.github/workflows/ci.yml   lint + tests for all three zones
Makefile                   up / down / logs / test / test-<zone> / setup
```

**The rule for where a new file goes:** anything that only matters when the stack
runs belongs here. Anything that matters when the code runs belongs to `control`
or `edge`.

## Idioms — how code is written here

- **The base compose file publishes no ports.** Not the database, not the API,
  not Caddy's admin endpoint. `expose` is fine; `ports:` in the base file is a
  finding. Only `docker-compose.dev.yml` publishes, and only to `127.0.0.1`.
- **Every required environment variable uses `${VAR:?message}`.** See Traps — a
  bare `${VAR}` silently becomes an empty string.
- **Every service declares a `healthcheck` and a `restart` policy.** A service
  with neither will sit dead while `docker compose ps` reports it up.
- **Images are pinned to an exact patch version** (`caddy:2.8.4-alpine`), and to a
  digest as well once the image has been pulled on a real host. Never a floating
  tag — not `latest`, not a bare major. Same rule as data-plane binaries, same
  reason: an upstream that changes under you changes how detectable every node is.
- **Secrets reach containers only through `env_file`**, never through `build`
  args, never baked into an image layer, never in a compose literal.
- Make targets are **idempotent** and safe to re-run. `make up` on a running
  stack converges it rather than failing.

## Interfaces this zone exposes

The Makefile is the contract with the owner. These verbs exist in every project
and mean the same thing here:

| Target | Meaning |
|---|---|
| `make setup` | create `.venv` and install dependencies |
| `make up` / `make up-dev` | build and start the stack (prod shape / dev overlay) |
| `make down` | stop the stack, keep volumes |
| `make logs` | follow logs |
| `make test` | verify **every** zone statically — no Docker required |
| `make test-control` / `make test-edge` / `make test-infra` | verify one zone |
| `make test-e2e` | acceptance scenarios against an already-running stack |

Adding a verb is fine; changing what an existing verb means is not.

## Testing

- `tests/infra/` validates the deployment description itself: `docker compose
  config` parses, the base stack publishes no ports, every service has a
  healthcheck and a restart policy, no image uses a floating tag.
  *Why: these are exactly the mistakes that are invisible until the day the stack
  is exposed to the internet.*
- Acceptance scenarios go in **`tests/e2e/infra/`** — owned by this zone.
  `make test-infra` does not run them; `make test-e2e` does, against a stack you
  started with `make up-dev`.
- A test that needs Docker must **skip loudly** when the daemon is absent rather
  than pass vacuously.

## Verification

```bash
make test-infra
```

Green proves the compose files parse and obey the exposure rules above. It does
**not** prove the stack boots, that Caddy obtained a certificate, or that backups
restore — booting is `make up`, and a backup nobody has restored is not a backup.

## Traps

- **`docker compose` must run with `--env-file`.** Without it, `${VAR}` resolves
  to an empty string rather than failing: the database starts with an empty
  password, Caddy serves on the wrong domain, and nothing errors. Every Make
  target passes `--env-file`, and every required variable is written
  `${VAR:?set this in .env}` so the failure is loud.
- **The control plane must stay relocatable.** No absolute host paths, no
  provider-specific volume drivers, no baked-in domain. The charter allows the
  owner to move it — including out of Russia in a hurry — and that only works if
  moving it is a `.env` change plus a restore.
- **Caddy access logs record full request paths**, which include subscription
  tokens. Access logging for `/sub/**` is disabled or path-stripped in the
  Caddyfile; this pairs with the same rule in the control zone and both are
  needed.
- **Backups are encrypted before they leave the host, and the private key never
  lives on the host.** A backup of this database is a copy of every user
  credential and every node key.
- **`docker compose down -v` deletes the database volume.** It is never part of a
  Make target, and never suggested to the owner as a fix for a stuck stack.
