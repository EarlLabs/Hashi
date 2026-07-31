# Control plane rulebook — hashi

<!--
WHAT: The rules for working inside the `control` zone: its stack, its idioms,
      its traps.
WHY:  this is where stack knowledge lives. The personas are stack-free on
      purpose, so the difference between this zone and `edge` is here.
HOW:  pre-read by every agent that touches `control/**` or `tests/control/**`.
-->

## Stack

- **Python 3.14**, dependencies in `pyproject.toml`, installed with `pip` into
  `.venv` (`make setup`). No Poetry, no uv, no Conda. The container runs the same
  minor version — a venv and an image on different minors is where "works
  locally" and "works in the stack" quietly diverge.
- **FastAPI** + **Uvicorn** — the API and the admin panel are one application.
- **SQLAlchemy 2.x async** + **asyncpg** against **PostgreSQL 16**.
  **Alembic** for every schema change (see core invariants §2).
- **Pydantic v2** / **pydantic-settings** — request models and configuration.
- **Jinja2 + HTMX** for the panel. No React, no build step, no bundler.
- The `edge` package is imported as a **pure library** for config rendering.
  Never the reverse.

## Layout

```
control/
  app/
    main.py          application factory and startup wiring only
    settings.py      pydantic-settings; every env var declared here, nowhere else
    api/             JSON endpoints, one module per resource
    panel/           HTMX routes returning HTML fragments, one module per screen
    models/          SQLAlchemy models — persistence shape only, no behaviour
    services/        the actual logic; everything a route does lives here
    templates/       Jinja2; `panel/` for fragments, `pages/` for full pages
  migrations/        Alembic
```

**The rule for where a new file goes:** if a route function is longer than
wiring — validate input, call a service, shape a response — the logic belongs in
`services/`. A route that queries the database directly is a rule violation, not
a shortcut.

## Idioms — how code is written here

- **Async all the way down.** No synchronous database or HTTP call inside a
  request path, ever. One `AsyncSession` per request, injected with `Depends`.
- **Configuration comes only from `settings.py`.** No `os.environ` anywhere else.
  A missing required setting raises at import, so the app fails at boot rather
  than on the first request that needs it.
- **Errors:** raise a domain exception from `services/`; one exception handler
  converts it into the `{"error": {"code", "message"}}` envelope. Routes do not
  build error responses by hand, and no handler returns a raw `str(exc)`.
- **Logging** goes through the module logger (`logging.getLogger(__name__)`).
  Never `print`. Never log a request URL verbatim — see Traps.
- **Secrets** are decrypted at the point of use and never stored in a variable
  that ends up in a log record, a template context, or an exception message.

## Interfaces this zone exposes

Three surfaces, with three different access rules. Every new route declares which
it is:

| Surface | Access | Enforced by |
|---|---|---|
| `/api/**` | operator only | session or API-token dependency on the router |
| `/panel/**` | operator only | session dependency on the router |
| `/sub/{token}` | **unauthenticated by design** — the token *is* the credential | constant-time token lookup; unknown token → 404, never 403 |

Rules for every new surface:

- Auth is a **router-level dependency**, never a check written inside the handler.
  A route added to an authenticated router inherits the rule; a route that needs
  its own rule states it explicitly.
- `/sub/{token}` returns **404 for both "unknown" and "revoked"**. A 403 confirms
  that a token once existed, which is more than a stranger should learn.
- Subscription tokens are ≥32 bytes of `secrets.token_urlsafe` entropy, looked up
  in constant time, and revocable without touching any other user.
- Every new surface goes in the developer's surface audit (see the persona).

## Testing

- **pytest** + **pytest-asyncio**, `httpx.AsyncClient` against the ASGI app.
- One e2e scenario per acceptance criterion in `tests/e2e/`. Unit tests in
  `tests/control/` only for pure branchy logic — token derivation, subscription
  serialisation, revocation fan-out.
- The database in tests is a real Postgres (the dev compose stack), not SQLite.
  *Why: async drivers, JSONB and constraints all behave differently, and a test
  suite that passes on SQLite proves nothing about production.*
- **Red-first is required** for every scenario proving an acceptance criterion:
  break the behaviour, watch the right assertion fail, restore it, and say so in
  the status file. A green suite with no red-first proof is not evidence.

## Verification

```bash
make test-control
```

Runs `ruff` over `control/` and pytest over `tests/control/`. Green proves the
zone's own logic holds together and nothing in it fails to import. It does **not**
prove a node was configured, that a tunnel carries traffic, or that anything
works from inside Russia — only a real device on a real network proves that.

## Traps

- **The subscription token is in the URL path.** Anything that logs a request
  line logs a live credential: Uvicorn's access log, an exception handler that
  echoes the path, Caddy's access log, a traceback. Access logging for `/sub/**`
  must be off or path-stripped, and this is checked on every review.
- **HTMX routes return fragments, not pages.** Returning a full document from a
  partial route nests `<html>` inside the panel and the bug looks like CSS.
- **Jinja autoescape must stay on.** Node names, user nicknames and error strings
  are attacker-influenced text; a `|safe` on any of them is an injection.
- **`expire_on_commit=False` on the async session.** Otherwise attribute access
  after commit triggers lazy I/O outside the session and raises at runtime, not
  in tests.
- **A revoked user must be revoked everywhere.** Revocation that updates the
  database but does not re-render and push every affected node leaves the user
  connected — the criterion is "stops working on every node and every transport".
