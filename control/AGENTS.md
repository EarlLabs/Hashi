# control — orientation

The control plane: the API, the admin panel, subscription delivery, and the
database that is the single source of truth for nodes, transports and users.

**Zone owner:** Thomas Anderson (`dev-anderson`).
**Rules:** `.claude/projects/01-control-rulebook.md` — read it before editing.
**Verify:** `make test-control`.

## What is here

| Path | What it holds |
|---|---|
| `app/main.py` | application factory; wiring only |
| `app/settings.py` | every environment variable this service reads |
| `app/api/` | JSON endpoints, one module per resource |
| `app/panel/` | HTMX routes returning HTML fragments |
| `app/models/` | SQLAlchemy models — persistence shape, no behaviour |
| `app/services/` | the logic; anything a route does beyond wiring lives here |
| `app/templates/` | Jinja2 — `panel/` fragments, `pages/` full pages |

## What is true today

A scaffold. `create_app()` serves `/healthz` and nothing else: no database, no
authentication, no panel, no subscription endpoint. The persistence dependencies
are deliberately not installed yet — see `pyproject.toml`.

## The two things newcomers get wrong

1. **Subscription tokens live in the URL path.** Anything that records a request
   line records a live credential. That is why the container runs uvicorn with
   `--no-access-log` and Caddy discards its access log.
2. **`edge` is imported, never imported *from*.** Config rendering is a pure
   library this zone calls; if you need `control` inside `edge`, the boundary is
   wrong.
