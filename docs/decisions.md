# hashi — decision journal

<!--
WHAT: One line per decision that the NEXT run has to know about. Read first,
      appended to last, by every persona this project consults.
WHY:  a persona has no memory between runs. Without this, every question starts
      from zero and the owner repeats context they gave an hour ago. The
      short-term half of memory (the last N exchanges) lives in the Warden's
      state volume and is deliberately forgettable; THIS half is durable — it
      survives rebuilds, quota resets and container wipes, and the owner can
      read and correct it.
HOW:  append at the bottom. Never rewrite a line: a decision that was reversed
      gets a NEW line saying so, because "we changed our mind in March" is
      itself the thing a later run needs to know.
-->

**The test for whether a line belongs here:** *if the next run does not know
this, will it decide wrongly?* If no, it is not a decision — it is progress, and
progress belongs in the task's own files.

Good: "chose Postgres over SQLite — the fleet writes concurrently and SQLite
locks." Bad: "implemented the login screen."

| date | decision | why |
|---|---|---|
| 2026-08-09 | Fleet moved from an 8-agent crew to solo topology: one persona `alfred` (display name "Ohno") plus the always-installed, tool-restricted `reviewer-strict`. Kit bumped v1 → v4 in the same pass. | Single-owner project with no genuinely parallel work streams — see `docs/product/charter.md` §Fleet for the full rationale. Review independence is preserved (`reviewer-strict` has no edit tools), only the multi-developer coordination overhead is dropped. |
| 2026-08-08 | The control image now runs the INSTALLED distribution, not a copied source tree (`WORKDIR /src` → install → `rm -rf /src` → `WORKDIR /app`), and `pyproject.toml` finds packages (`[tool.setuptools.packages.find] include = ["control*", "edge*"]`) instead of listing them. | The image installed the package and then imported it from the copied tree, because cwd wins on `sys.path` — so packaging was never exercised. Proved: with the old explicit list, a new `edge/transports/` package was absent from the installed distribution (`discover()` → `[]`) and shipped only by accident. The charter's fourth criterion needs packaging to follow the directory. |
| 2026-08-08 | Caddy is BUILT from `deploy/docker/caddy.Dockerfile` (upstream tag still pinned) instead of pulled with the Caddyfile bind-mounted. | A bind mount is resolved by the docker DAEMON. Against any engine that does not hold this checkout — the fleet's dind, a remote host — the path is missing, Docker creates a directory there, and the stack fails to boot. Config must travel with the image. |
| 2026-08-08 | The dev overlay's publish address is `${DEV_BIND_ADDR:-127.0.0.1}`, and the e2e stack has `E2E_BIND_ADDR` (default `127.0.0.1`). | Loopback-only is right for a laptop and impossible for an isolated dind engine, where `127.0.0.1` is dind's own loopback and no runner can reach the stack. The default is unchanged; an engine that is not your machine is an explicit per-run opt-in. |
| 2026-08-08 | The e2e stack pins `HASHI_PUBLIC_HOST=localhost` via `deploy/docker-compose.e2e.yml` rather than inheriting the owner's real one from `.env`. | Caddy cannot obtain a certificate for a name that does not point at the test machine, so it retried ACME forever and never served a request — every proxy-path scenario was silently testing nothing. Against a name that IS real, each test run would ask a public CA for the production certificate and burn its rate limit. `localhost` is served by Caddy's internal CA, with no CA on the internet involved. |
| 2026-08-08 | `/openapi.json` is now off (`openapi_url=None`), not just `/docs` and `/redoc`. | Turning off the two HTML viewers left the machine-readable schema — every route, parameter and model — served to anyone. Found by the first e2e run against a real socket; the unit test had only ever asked for `/docs` and `/redoc`. |
