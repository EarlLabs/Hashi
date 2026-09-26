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

- **A comment says what this script does and why; never what the panel does.**
  This zone and `control/**` read the same records and speak to the same
  operator, and every instance of prose drifting from behaviour in M28 crossed
  that line. Name `control/app/services/…` and let the reader look. **Operator
  output names the state it holds for** — a warning printed over several record
  shapes must be true of each, and `make backup-status` is read by someone who
  cannot check it against the code.
- **The base compose file publishes no ports.** Not the database, not the API,
  not Caddy's admin endpoint. `expose` is fine; `ports:` in the base file is a
  finding. Only `docker-compose.dev.yml` publishes, and its bind address
  defaults to `127.0.0.1` — `${DEV_BIND_ADDR:-127.0.0.1}`. The override exists
  for one case: an engine that is not the machine you are sitting at (the
  fleet's isolated dind, where `127.0.0.1` is dind's own loopback and no test
  runner can reach the stack). Changing the *default*, or writing a literal
  `0.0.0.0`, is still a finding — and `tests/infra/test_compose.py` fails on it.
- **A published port is never a service's default** — not `5432`, `8000`, `6379`,
  `3000`. The host already runs something, and the collision surfaces as an
  opaque "port is already allocated" halfway through a build. Inside the compose
  network, defaults are fine and preferred. Enforced by
  `tests/infra/test_compose.py::test_published_ports_avoid_service_defaults`.
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
  `make test-infra` does not run them; `make test-e2e` does, against the stack
  `make e2e-up` starts.
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
- **`docker compose down -v` deletes the database volume.** It appears in exactly
  one Make target, `e2e-down`, and only because the e2e stack is a **separate
  compose project** (`-p hashi-e2e`) whose volumes are disposable by design. It is
  never used against the `hashi` project, and never suggested to the owner as a
  fix for a stuck stack. If you ever make the two share a project, this target
  starts destroying live data — check the project name before touching it.
