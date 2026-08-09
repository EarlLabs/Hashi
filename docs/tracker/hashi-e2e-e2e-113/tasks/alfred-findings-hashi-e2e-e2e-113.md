# hashi-e2e-e2e-113 — what the first real e2e run found

Five defects. Each one is listed with the evidence that it was real, because the
backlog's rule is that a green run is not acceptance: for every scenario the
behaviour was broken, the right assertion failed, and it was restored.

---

## 1. `/openapi.json` served the full API schema — `control`

**Found by:** `tests/e2e/control/test_control_plane_serves_only_what_it_should.py`
on its first run, against a real socket.

`create_app()` passed `docs_url=None, redoc_url=None`. Those turn off the two
HTML *viewers*. `openapi_url` was left at its default, so the schema those
viewers read — every route, parameter and model — was served to anyone who asked.
The unit test had only ever requested `/docs` and `/redoc`, so it agreed.

**Red:** first e2e run, `assert 200 == 404` on `/openapi.json`.
**Fix:** `openapi_url=None` (`control/app/main.py`); the unit test now asks for
all three.

## 2. Caddy could not boot against any engine but the developer's own — `infra`

`deploy/docker-compose.yml` mounted `./caddy/Caddyfile` into the container. A
bind mount is resolved by the docker **daemon**, so against the fleet's dind
engine the path does not exist, Docker creates a *directory* there, and then
refuses to mount a directory over the image's file.

**Red:** the very first `e2e-up` — `failed to create task for container: ...
error mounting "/repo/deploy/caddy/Caddyfile" ... not a directory`. The stack
came up two-thirds started, with the proxy dead.
**Fix:** `deploy/docker/caddy.Dockerfile` bakes the config in; compose builds
Caddy instead of pulling it. The upstream tag stays pinned, and a new infra test
(`test_dockerfile_base_images_are_pinned`) keeps it pinned now that the service
no longer has an `image:` line for the old check to look at.

## 3. The control image never ran the code it installed — `infra` / packaging

The Dockerfile did `pip install .` in the same `WORKDIR` it then ran from, so
`import edge` resolved to the **copied tree** (cwd wins on `sys.path`), never to
the installed distribution. The install was decoration, and `pyproject.toml`'s
package list was never exercised by anything.

Underneath it, a second defect: that package list was explicit
(`packages = ["control", "control.app", "edge", "edge.transports"]`), so a new
`edge/transports/<name>/` package would not have been installed at all.

**Red, in two steps** — with a throwaway `edge/transports/_e2e_probe/` package
in the tree:

| image | `discover()` inside the container |
|---|---|
| old Dockerfile (runs from the copy) | `['_e2e_probe']` — passing for the wrong reason |
| new Dockerfile + **old** explicit package list | `[]` — the transport is simply absent |
| new Dockerfile + `packages.find` | `['_e2e_probe']`, from `site-packages` |

The middle row is the bug this would have caused in production: a protocol that
exists in the repo, passes every test, and is missing from the deployed image.
The probe package was removed afterwards.

**Fix:** Dockerfile builds in `/src`, installs, deletes the sources, runs from an
empty `/app`; `pyproject.toml` uses `[tool.setuptools.packages.find]`.
**Pinned by:** `tests/e2e/edge/test_shipped_image_discovers_transports.py`, which
compares what the image discovers against the directories in the tree.

## 4. The e2e stack asked a public CA for the owner's production certificate — `infra`

The e2e stack inherited `HASHI_PUBLIC_HOST` from `.env`. Caddy therefore tried to
obtain a certificate for the owner's real delivery hostname on every test run —
against a placeholder it just retried ACME forever and never served a single
request, and against the real name it would burn the issuance rate limit that an
actual deployment needs.

The quieter half of this: because Caddy never served, **every scenario going
through the proxy was testing nothing**. That is how finding 5 stayed invisible.

**Red:** `tls.obtain ... will retry` in a loop in the caddy log, and no route
through the proxy answering at all.
**Fix:** `deploy/docker-compose.e2e.yml` pins the e2e stack to `localhost`, which
Caddy serves from its own internal CA with nothing on the internet involved.
**Pinned by:** `test_the_proxy_actually_serves_the_control_plane`, which exists
precisely so a clean log can never again mean "nothing happened".

## 5. The published port was unreachable from any runner but the local one — `infra`

The dev overlay hardcoded `127.0.0.1:`. On an isolated dind engine that is
*dind's* loopback, so the test runner could not reach the stack at all —
`docker port` said `127.0.0.1:54200` and nothing could connect.

The loopback rule itself is right and stays: it is what keeps a database off a
café network. What was missing is that "the engine" and "your machine" are not
always the same host.

**Fix:** `${DEV_BIND_ADDR:-127.0.0.1}` in the overlay and `E2E_BIND_ADDR ?=
127.0.0.1` in the Makefile — the default is unchanged, and an engine that is not
your machine is a per-run opt-in (`make e2e-up E2E_BIND_ADDR=0.0.0.0`).
**Pinned by:** `test_dev_overlay_binds_loopback_by_default`, rewritten to check
the *default* of an interpolation rather than a literal prefix, so the knob
cannot be turned into a permanently open bind without failing the suite.

---

## Red-first evidence for the two charter-critical scenarios

These two are the charter's "never log who connected to what". Neither was
broken — but a test for an invariant that already holds is worthless unless it
is shown to fail when the invariant stops holding.

**Control plane** (`test_request_paths_are_never_logged.py`): removed
`--no-access-log` from the Dockerfile, rebuilt, re-ran. Red, with the fake token
visible in the failure output:
`'e2e-token-9d21ce74-never-real' is contained here: l?token=... HTTP/1.1" 404`.
Restored.

**Caddy** (`test_caddy_discards_access_logs.py`): the first version of this
scenario **passed with both `log { output discard }` blocks deleted** — it was a
false green, because the requests it sent were turned away before reaching the
site's logger. Rewritten to drive a genuinely proxied `https://localhost/...`
request. Then re-verified: switching the site block to `output stdout` makes it
red with a real `http.log.access` entry containing the URI. Restored.

## Deliberately NOT proven

No node, no tunnel, no Russian network takes part in any of this. Charter
criterion 1 — "survives a mobile whitelist shutdown" — is a field observation and
this suite says nothing about it. Criterion 4 is not closed either: the image
now *ships* whatever transports exist, and zero exist.
