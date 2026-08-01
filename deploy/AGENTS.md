# deploy — orientation

Deployment and operations: the compose stacks, Caddy, CI, backups and secret
handling. This zone decides whether the control plane can be moved to another
host in an afternoon — which the charter treats as a survival property.

**Zone owner:** Pepper Potts (`dev-potts`).
**Rules:** `.claude/projects/04-infra-rulebook.md` — read it before editing.
**Verify:** `make test-infra`.

## What is here

| Path | What it holds |
|---|---|
| `docker-compose.yml` | base stack, production shape — **publishes nothing** |
| `docker-compose.dev.yml` | the only file that publishes ports, loopback only |
| `docker/` | Dockerfiles, one per service |
| `caddy/Caddyfile` | reverse proxy; access logging deliberately discarded |
| `warden/` | the tracker integration — its own stack, its own README |

The `Makefile` and `.github/workflows/` also belong to this zone.

## What is true today

The stack builds and boots: Postgres, the control plane, Caddy. Caddy will not
obtain a real certificate until `HASHI_PUBLIC_HOST` points at a host that
resolves to it — locally, use `make up-dev` and talk to the control plane on
`127.0.0.1:8000` directly.

## The two things newcomers get wrong

1. **Compose must run with `--env-file`.** Without it `${VAR}` becomes an empty
   string instead of failing: the database starts with an empty password and
   nothing errors. Every Make target passes it, and every variable is written
   `${VAR:?...}` so the failure is loud.
2. **`docker compose down -v` deletes the database volume.** It is in exactly one
   Make target, `e2e-down` — and that is safe only because the e2e stack is a
   separate compose project (`-p hashi-e2e`, its own volumes, its own host ports
   8100/55532). The dev and production stacks use project `hashi`. Merge the two
   projects and `make e2e-down` starts wiping live data.
