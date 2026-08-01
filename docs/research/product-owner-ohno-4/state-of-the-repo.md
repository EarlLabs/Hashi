# State of the repository — hashi, 2026-08-01

Factual survey for `product-owner-ohno-4`. No roadmap, no prioritisation, no
recommendations: those are ohno's. This is ground truth only.

---

## Ten-line summary

1. hashi is a **scaffold**, and its own `README.md` says so accurately. Nine
   commits, ~700 lines of first-party Python, of which ~130 are product code.
2. The entire product surface is one route: `GET /healthz` in
   `control/app/main.py:26`. There is no database, no auth, no panel, no
   subscription endpoint, no node, no transport.
3. `edge/` contains exactly one working function — `discover()` in
   `edge/registry.py:29` — which correctly returns `{}` because zero transport
   profiles exist. `edge/bootstrap/` and `edge/health/` are empty `.gitkeep`s.
4. `make test` **passes: 14 tests** (control 3, edge 2, infra 9) plus ruff, in
   under a second. I ran it (see §3 for the environment caveat).
5. **Zero e2e scenarios exist.** All three `tests/e2e/<zone>/` directories hold
   only a `.gitkeep`, and `make test-e2e` is written to report "no scenarios yet"
   as success.
6. Of the charter's six success criteria: **none is met**. Criterion 4 ("a new
   protocol is one package") is the only one with real architecture behind it,
   and a packaging defect (§5.1) breaks it inside the container image.
7. The compose stack (Postgres + control + Caddy) builds and boots, publishes
   nothing in production shape, and is guarded by nine structural tests — the
   `infra` zone is the most complete of the three, by a wide margin.
8. Postgres runs in the stack and **nothing connects to it**: `sqlalchemy`,
   `asyncpg` and `alembic` are deliberately absent from `pyproject.toml`.
9. `HASHI_SECRET_KEY` is declared, required at boot, and **used by nothing** —
   encryption at rest is documented doctrine with no implementation.
10. `deploy/warden/` (latest commit) is not product code: it is a gRPC daemon
    that lets Kaizen's tracker Hub dispatch slash-commands into this repo's own
    agent fleet. It mounts the repo read-write. Details in §6.

---

## 1. What exists

### 1.1 Size and shape

| Area | Tracked files | First-party lines | Character |
|---|---:|---:|---|
| `control/` | 6 | ~60 | scaffold: app factory + settings |
| `edge/` | 4 | ~39 | scaffold: registry only |
| `deploy/` (product) | 5 | ~180 | **real**: builds and boots |
| `deploy/warden/` | 4 + 10 vendored | ~340 | **real**, non-product |
| `tests/` | 3 files, 14 tests | ~150 | real but structural only |
| `scripts/` | 4 | ~750 | real; 2 shell shims + 2 kit-render tools |
| `.claude/` | 22 | ~3300 | complete fleet definition |
| `docs/` | 1 (charter) + gitkeeps | 208 | charter only |

The git history is nine commits: one scaffold, four review-loop rounds, a
`.dockerignore`, a render-reproducibility chore, and warden. `main` and
`develop` point at the same commit (`1cfd7d7`). `origin` is
`https://github.com/earlzdev/Hashi.git` and `main` is pushed.

### 1.2 `control/` — control plane

Real:

- `control/app/main.py` — `create_app(settings=None) -> FastAPI`. Builds the
  app, stores settings on `app.state`, disables `docs_url`/`redoc_url`, and
  registers one route: `GET /healthz` returning `{"status": "ok"}`. That is the
  whole file (31 lines).
- `control/app/settings.py` — `Settings(BaseSettings)` with `env_prefix="HASHI_"`
  and two fields: `secret_key: str` (no default → boot fails without it) and
  `public_host: str = "localhost"`.

Empty (`.gitkeep` only): `control/app/api/`, `control/app/models/`,
`control/app/panel/`, `control/app/services/`, `control/app/templates/`.

Entirely absent: `control/migrations/` (the Alembic directory named in
`.claude/projects/01-control-rulebook.md:37` does not exist), any database
engine or session, any authentication, any router, any error-envelope handler,
any logging configuration, any use of `jinja2` (which is a declared dependency).

`control/AGENTS.md` is honest about all of this: *"A scaffold. `create_app()`
serves `/healthz` and nothing else."*

### 1.3 `edge/` — data plane

Real:

- `edge/registry.py` — a frozen dataclass `TransportMeta(name, family,
  needs_tls)` and `discover() -> dict[str, TransportMeta]`, which walks
  `pkgutil.iter_modules(edge.transports.__path__)`, imports
  `edge.transports.<name>.meta`, reads `META`, and raises `ValueError` on a
  duplicate name. No hardcoded list. This function works and is tested.

Empty: `edge/transports/` (only `__init__.py` — **zero transport packages**),
`edge/bootstrap/` (`.gitkeep`), `edge/health/` (`.gitkeep`).

Entirely absent: any Xray/VLESS/Reality/XTLS-Vision profile; any AmneziaWG
profile; any Jinja config template (`server.j2`); the `Params` /
`render_server` / `render_client` half of the transport contract — it exists as
a prose table in `.claude/projects/02-edge-rulebook.md:61-66` and **nowhere in
code**, not as a `Protocol`, an ABC, or a docstring in `registry.py`; `asyncssh`
(not a dependency); any node-record type — the `node` argument that
`render_server(node, params)` is specified to take has no definition anywhere in
the repository.

### 1.4 `deploy/` — infrastructure (product stack)

This is the one zone with substance.

- `deploy/docker-compose.yml` — `name: hashi`; three services. `db`
  (`postgres:16.4-alpine`, named volume `hashi-db`, `pg_isready` healthcheck),
  `control` (built from `deploy/docker/control.Dockerfile`, `expose: 8000`,
  urllib healthcheck against `/healthz`, `depends_on: db service_healthy`),
  `caddy` (`caddy:2.8.4-alpine`, admin-API healthcheck, `depends_on: control
  service_healthy`). No `ports:` anywhere. Every variable written
  `${VAR:?message}`.
- `deploy/docker-compose.dev.yml` — the only file that publishes: `127.0.0.1:
  ${DEV_DB_PORT:-55432}:5432` and `127.0.0.1:${DEV_API_PORT:-8000}:8000`.
- `deploy/docker/control.Dockerfile` — `FROM python:3.14-slim`, copies
  `pyproject.toml`, `control/`, `edge/`, `pip install .`, runs
  `uvicorn control.app.main:create_app --factory --host 0.0.0.0 --port 8000
  --no-access-log`.
- `deploy/caddy/Caddyfile` — global block sets `email`, binds `admin
  127.0.0.1:2019`, and sets `log { output discard }`; the site block
  `{$HASHI_PUBLIC_HOST}` repeats `log { output discard }` and does
  `reverse_proxy control:8000`. Both loggers are silenced deliberately.
- `.dockerignore` — denies `.env`, `*.key`, `*.pem`, `secrets/`, `.git/`,
  `docs/`, `tests/`, `.claude/`.
- `.github/workflows/ci.yml` — one matrix job per zone running
  `make setup && make test-<zone>` on `ubuntu-latest` with Python 3.14. No e2e
  job.

Absent from `deploy/`: anything node-side. There is no node compose file, no
node Dockerfile, no Xray or AmneziaWG image reference, no bootstrap payload, no
backup or restore target, no Caddy camouflage-front config.

### 1.5 `Makefile`

Twenty targets in four groups: setup (`setup`, `env`), verification (`test`,
`test-control`, `test-edge`, `test-infra`, `test-e2e`, `lint`), stack (`up`,
`up-dev`, `down`, `logs`, `ps`), warden (`warden-sync`/`-up`/`-down`/`-logs`),
e2e (`e2e-up`, `e2e-down`, `e2e-reset`). All real and consistent with the infra
rulebook's contract table. `COMPOSE` always carries `--env-file .env`. The e2e
stack is a separate compose project (`-p hashi-e2e`, ports 8100/55532), so
`down -v` appears in exactly one target.

`make test-e2e` probes `127.0.0.1:$(E2E_API_PORT)/healthz` first and translates
pytest exit code 5 into "no e2e scenarios yet" + exit 0.

### 1.6 `pyproject.toml`

Runtime deps: `fastapi`, `uvicorn`, `pydantic-settings`, `jinja2` — **no version
constraints on any of them**. Dev extras: `pytest`, `pytest-asyncio`, `httpx`,
`ruff`, `pyyaml`. A comment records that `sqlalchemy`/`asyncpg`/`alembic` are
deliberately absent until there is a database.

`[tool.setuptools] packages = ["control", "control.app", "edge",
"edge.transports"]` — an explicit list, not auto-discovery. See §5.1.

Ruff selects `E,F,I,UP,B`, line length 100, excludes `deploy/warden/vendor`.
Pytest runs with `asyncio_mode = "auto"` and `--import-mode=importlib`.

### 1.7 `scripts/`

- `notify.sh` (13 lines) — timestamps a message and `tee -a`s it to
  `docs/tracker/notifications.log`. There is no bot and no channel.
- `ask_owner.sh` (22 lines) — appends to `docs/tracker/questions.log` and prints
  an instruction telling the calling agent to stop. It cannot fetch an answer.
- `render.py` (292 lines) and `patches.py` (423 lines) — regenerate `.claude/`
  from Kaizen's agentkit and re-apply this project's surgery (no leads, no
  tracker service, per-zone e2e dirs). Build tooling for the fleet, not the
  product.

### 1.8 `.claude/`

Complete and internally consistent: eight agent personas, ten commands, four
rulebooks (`00-core-invariants`, `01-control`, `02-edge`, `04-infra`), a
security checklist, and a 212-line `workflow.md`. `KIT_VERSION` is `1`. This is
the most finished artefact in the repository and the one place where the
transport contract, the surface access rules, and the node lifecycle are
specified — as prose.

### 1.9 `.e2e/profile.yml`

Describes how e2e would run (boot `make e2e-up`, ready-probe 8100, run
`make test-e2e`, write to `tests/e2e/<zone>/`). Its own header states that
**nothing reads this file**, and that the `/e2e` command it pairs with does not
exist in this repo. Its `boundary` block states explicitly that no real node, no
real tunnel and no Russian network is part of any e2e run.

---

## 2. Charter criteria vs. reality

Summary: **0 of 6 met. 1 partially scaffolded. 5 entirely absent.**

### Criterion 1 — Survives a whitelist shutdown

**Entirely absent.** Nothing in the repository represents an entry node, a leaf
node, or the hop between them. There is no node record, no node table, no
routing concept, no relay configuration. The two-hop topology — the load-bearing
idea of the whole product — exists only in `docs/product/charter.md:91-107` and
in rulebook prose.

This criterion is also, by design, unprovable by any test in this repo:
`.e2e/profile.yml:45-53` says so, `README.md:51-54` says so, and `CLAUDE.md`
says so. It requires a device on a real Russian mobile network.

### Criterion 2 — A node is replaceable in ten minutes

**Entirely absent.** Every component this needs is missing:

- node inventory (host, SSH key, location label, enabled transports) — no model,
  no table, no migration; `control/app/models/` is a `.gitkeep`
- bootstrap over SSH — `edge/bootstrap/` is a `.gitkeep`; `asyncssh` is not a
  dependency
- a panel to trigger it from — `control/app/panel/` and
  `control/app/templates/` are `.gitkeep`s
- re-render-and-republish so subscriptions resolve to the new node — no
  subscription renderer exists
- the `degraded` vs `active` node state named in `00-core-invariants.md:81` —
  no state machine exists

### Criterion 3 — A protocol is swappable without touching users

**Entirely absent in behaviour; the discovery half is scaffolded.**

In place: `edge/registry.py:29` `discover()` is genuinely dynamic and tested
(`tests/edge/test_scaffold.py:18`).

Absent: any transport to enable; per-node transport enablement (no node record);
any panel control; any subscription render, so "present in every subscriber's
config at their next refresh" has no mechanism at all. And see §5.1 — a
transport added today would not be present in the built container.

### Criterion 4 — A new protocol is one package, not surgery

**Partially in place — the strongest criterion, and still not met.**

In place:

- `discover()` uses `pkgutil` walking, never a list — adding a package requires
  no edit to `registry.py` (`edge/registry.py:32-38`)
- `TransportMeta` deliberately exposes only what the control plane may know
  without knowing which transport (`edge/registry.py:20-26`)
- an executable guard that `edge` never imports `control`
  (`tests/edge/test_scaffold.py:25`)

Not in place:

- the other three symbols of the contract — `Params`, `render_server`,
  `render_client` — are specified only in `.claude/projects/02-edge-rulebook.md`
  and are not expressed in code, so nothing enforces them and nothing type-checks
  a profile
- `TransportMeta` lacks the "default port range" field the rulebook's contract
  table (`02-edge-rulebook.md:63`) requires
- the "subscription renderer" the criterion says must not be modified **does not
  exist**, so the claim is untested by construction
- `pyproject.toml`'s explicit package list means adding a transport *does*
  require surgery outside the package — in a file that is architect territory
  (§5.1)

### Criterion 5 — Onboarding is one link

**Entirely absent.** No `/sub/{token}` route (the surface table at
`01-control-rulebook.md:69` describes it; no code implements it). No user or
friend record. No token generation, no constant-time lookup, no 404-for-both
behaviour. No subscription serialisation, and **no decision anywhere in the
repository about which subscription format to emit** (base64 v2ray list, Clash,
sing-box). No exit-country selection. No client has ever been pointed at this
system.

### Criterion 6 — Revocation is total

**Entirely absent.** There is no user record to revoke, no credential store, no
fan-out to nodes, and no push channel to a node. The rulebooks describe the
requirement in three places (`01-control-rulebook.md:125`,
`03-security-checklist.md:62`, charter) and nothing implements it.

---

## 3. Test reality

### 3.1 What I actually ran

The pre-existing `/repo/.venv` was a broken shell (directories present, no
interpreter), so `make test` initially failed with `no .venv yet — run: make
setup`, and `make setup` then failed with `Error: [Errno 2] No such file or
directory: '/repo/.venv/bin/python3.14'`. I removed the stale `.venv`, re-ran
`make setup` (network access to PyPI is available in this environment), and then
ran `make test`.

**Result: pass, 14 tests, all three zones, ruff clean.**

```
ruff check control tests/control   → All checks passed!
pytest tests/control -q            → 3 passed in 0.16s
ruff check edge tests/edge         → All checks passed!
pytest tests/edge -q               → 2 passed in 0.01s
ruff check tests/infra deploy/warden → All checks passed!
pytest tests/infra -q              → 9 passed in 0.03s
```

Not run: `make test-e2e` (needs a booted stack; Docker was not exercised), and
`make up` / `make up-dev` (not attempted). So "the stack builds and boots", which
`deploy/AGENTS.md:25` asserts, is **not verified by this survey** — I verified
only that its description parses and obeys the exposure rules.

### 3.2 Test inventory

| File | Tests | Kind | What it actually pins |
|---|---:|---|---|
| `tests/control/test_scaffold.py` | 3 | unit | `/healthz` returns 200/`{"status":"ok"}`; `/docs` and `/redoc` 404; `Settings()` raises `ValidationError` without `HASHI_SECRET_KEY` |
| `tests/edge/test_scaffold.py` | 2 | unit | `discover()` returns `{}`; no file under `edge/` imports `control` |
| `tests/infra/test_compose.py` | 9 | structural | base publishes no ports (1); every service has healthcheck + restart (3, parametrised); images pinned, not `latest`, not bare-major (3, parametrised); dev overlay binds loopback only (1); every `${VAR}` in the base file carries a `:?` guard (1) |
| **total** | **14** | | |

Characterisation: **all 14 are unit or static-structural. None boots the stack,
none touches Postgres, none renders a config, none exercises a node, none
exercises a subscription.** The infra tests parse YAML rather than calling
`docker compose config`, so they run with the daemon stopped — which is what the
infra rulebook asks for.

### 3.3 e2e coverage against acceptance criteria

| Criterion | Owning zone dir | Scenario present? |
|---|---|---|
| 1 — survives whitelist shutdown | — | **No, and unprovable here by design** (`.e2e/profile.yml:45-53`) |
| 2 — node replaceable in 10 min | `tests/e2e/edge/` | **No** |
| 3 — protocol swappable | `tests/e2e/control/` + `edge/` | **No** |
| 4 — new protocol is one package | `tests/e2e/edge/` | **No** |
| 5 — onboarding is one link | `tests/e2e/control/` | **No** |
| 6 — revocation is total | `tests/e2e/control/` | **No** |

All three `tests/e2e/<zone>/` directories contain a `.gitkeep` and nothing else.
**Zero e2e scenarios exist for zero of six criteria.**

Reporting hazard worth stating plainly: `make test-e2e` is written to exit 0 and
print "no e2e scenarios yet" when pytest collects nothing (`Makefile:67-68`). It
is an honest message, but a green `make test-e2e` today is evidence of nothing.
The same is true of `make test`: it is green over a codebase with no features.

### 3.4 Test-quality observations

- `test_images_are_pinned` (`tests/infra/test_compose.py:44-49`) returns early
  for any service without an `image:` key — i.e. it exempts `control`, the one
  image this project builds. Its base image `python:3.14-slim` is a bare minor
  tag, which is exactly what core invariants §5 forbids, and no test covers it.
- `test_edge_never_imports_control` matches with `line.startswith(("import
  control", "from control"))`, so an indented import inside a function body, or
  an `importlib.import_module("control...")`, would not be caught.
- Nothing tests that uvicorn keeps `--no-access-log`, or that the Caddyfile keeps
  `output discard`. Both are the repo's primary defence for the
  token-in-the-path problem and both are unpinned by any assertion.

---

## 4. What is missing to get to a first working tunnel

Descriptive inventory only, no ordering. "A friend pastes one subscription URL
into a stock client and traffic flows" requires all of the following, none of
which exists today.

### 4.1 Control plane — persistence

- `sqlalchemy`, `asyncpg`, `alembic` added to `pyproject.toml` (architect
  decision by rule)
- async engine + `AsyncSession` dependency, `expire_on_commit=False`
- `control/migrations/` with Alembic initialised; the directory does not exist
- models: node, transport-enablement per node, user/friend, credential,
  subscription token — none exist
- `DATABASE_URL`-equivalent setting: `settings.py` declares no database setting,
  and `deploy/docker-compose.yml` passes no database variable to `control`,
  though it does start Postgres and gate `control` on its health

### 4.2 Control plane — secrets at rest

- `HASHI_SECRET_KEY` is required at boot and read by nothing; there is no
  encrypt/decrypt helper, no encrypted column type, and no key-rotation story

### 4.3 Control plane — surfaces

- operator authentication (session or API token) — nothing
- `/api/**` routers — nothing
- `/panel/**` HTMX routes and Jinja templates — nothing (`jinja2` is installed
  and unused)
- `/sub/{token}` delivery endpoint: token generation (≥32 bytes
  `secrets.token_urlsafe`), constant-time lookup, 404 for unknown *and* revoked
- the `{"error": {"code", "message"}}` envelope handler named in core
  invariants §4

### 4.4 Control plane — subscription rendering

- the subscription renderer itself
- **a chosen wire format** — the repository contains no decision on whether the
  endpoint emits a base64 v2ray URI list, Clash YAML, sing-box JSON, or several
  by client detection. Criterion 5 ("an unmodified stock client") cannot be
  scoped until that is fixed.
- multi-exit-country presentation, since criterion 5 requires the friend can
  "choose an exit country"

### 4.5 Data plane — transports

- at least one working profile. The charter names VLESS + Reality + XTLS-Vision
  as primary; `edge/transports/` is empty.
- the `Params` / `render_server` / `render_client` contract expressed in code
- Jinja server templates and checked-in golden files
- validation against the upstream checker (`xray run -test -config`) with a loud
  skip when the binary is absent
- per-node Reality decoy destination as a required field with **no project-wide
  default** (core invariants §6)
- key generation: renderers are forbidden to generate keys, and no other
  component generates them either — the responsibility is currently unassigned

### 4.6 Data plane — nodes

- a node-record type (the `node` parameter has no definition anywhere)
- bootstrap over SSH: install docker, place compose files, start, verify —
  `edge/bootstrap/` is empty and `asyncssh` is not a dependency
- health probing initiated by the control plane — `edge/health/` is empty
- time synchronisation before starting Xray (rulebook trap, unimplemented)
- MTU handling for the tunnel-in-tunnel entry→leaf hop (rulebook trap,
  unimplemented)
- the entry→leaf relay itself: no representation of a node's *role*, and no
  configuration for the obfuscated hop across the border

### 4.7 Infrastructure

- node-side artefacts: compose file, pinned Xray/AmneziaWG images, Caddy
  camouflage front — `deploy/` covers only the control plane
- a delivery endpoint reachable from inside Russia — Caddy currently fronts one
  host, `{$HASHI_PUBLIC_HOST}`, with no separation between panel and delivery
- backup and restore (rulebook requires encrypted-before-leaving-host)
- an actual host to bootstrap onto. Renting one is on the charter's
  "agents must ask the owner" list, as is exposing a port to the internet.

### 4.8 Verification

- e2e scenarios for criteria 2–6 in the correct `tests/e2e/<zone>/` directories
- a real-network field test for criterion 1, which no automation can substitute
- the `/e2e` command referenced by `.e2e/profile.yml` does not exist in
  `.claude/commands/`

---

## 5. Risks and inconsistencies observed

### 5.1 CONFIRMED: a new transport package would not ship in the container

`pyproject.toml:30` uses an explicit package list:

```toml
packages = ["control", "control.app", "edge", "edge.transports"]
```

`edge.transports.<name>` subpackages are not listed and setuptools will not
discover them. I verified this empirically: I created
`edge/transports/demo/{__init__.py,meta.py}` in a copy of the tree and ran
`pip install --target`. The installed result contains `edge/transports/` and
**no `demo/` directory**.

Consequences, in the terms the charter uses:

- `deploy/docker/control.Dockerfile:15` runs `pip install .`, so the running
  container would find zero transports while `make test-edge` on a laptop
  (editable install, repo root on `sys.path`) finds them. `registry.discover()`
  returns `{}` in production and the failure is silent.
- Adding a protocol would therefore require editing `pyproject.toml`, which is
  explicitly architect territory (`CLAUDE.md`, `workflow.md`, core invariants
  §5) and explicitly *not* what "a new protocol is one new directory and nothing
  else" (`edge/AGENTS.md:30`) promises. This is criterion 4 failing in the build
  system rather than in the code.

### 5.2 Base images are not pinned to a patch version

`00-core-invariants.md:89` and `04-infra-rulebook.md:49`: pin to an exact patch,
"never a bare major". `deploy/docker/control.Dockerfile:7` is `FROM
python:3.14-slim` — a moving minor tag. `deploy/warden/Dockerfile:20` is the
same, and additionally installs `nodesource setup_22.x` and `npm install -g
@anthropic-ai/claude-code` with no version. The infra test that would catch this
exempts built services by design (`tests/infra/test_compose.py:49`).

Related: every runtime dependency in `pyproject.toml:10-15` is unconstrained
(`fastapi`, `uvicorn`, `pydantic-settings`, `jinja2`), against
`03-security-checklist.md:46` ("pinned").

### 5.3 `public_host` has a silent default

`control/app/settings.py:27` — `public_host: str = "localhost"`. The compose
file makes `HASHI_PUBLIC_HOST` mandatory (`${...:?}`), so inside the stack this
is unreachable; outside it, the app boots happily on a wrong hostname. This sits
awkwardly beside the same file's own doctrine (`settings.py:8` — "`Settings()`
raises when a required value is absent") and the delivery endpoint's hostname is
the value a friend's client resolves. It is not a hardcoded *country or
provider*, so it is not a §6 violation; it is a fail-quiet default in the one
setting the subscription URL is built from.

### 5.4 Stale statement in `workflow.md`

`.claude/workflow.md` (branch model, rule 4) states in bold: *"This repository
has no `origin` yet."* It does — `https://github.com/earlzdev/Hashi.git`, with
`main` pushed. The same section says agents never push to `main`; `main` is the
branch that is pushed, and `develop` is identical to it. This is documentation
drift, not a code defect, but it is the document that governs every agent's
branch behaviour.

### 5.5 The warden mount is the largest standing risk in the tree

Covered in §6. In short: `deploy/warden/docker-compose.yml` mounts the repo
read-write into a container that runs `claude -p` with `Bash`, `Write`, `Edit`,
`WebSearch` and `WebFetch` allowed, unattended. `.env` (real secrets) lives in
that mount. `CLAUDE.md`'s "NEVER read or print `.env`" is a prompt-level rule
with no enforcement behind it — there is no `.gitignore`-style guard, no
permission deny-rule in `.claude/`, and no filesystem separation. The README
flags the mount honestly; it does not flag `.env`.

`warden.py:131` strips `ANTHROPIC_API_KEY` from the child environment and passes
everything else through.

### 5.6 Categories where I found nothing

Stating these explicitly, as asked:

- **`edge` → `control` import breaches: none.** Verified by grep and by
  `tests/edge/test_scaffold.py:25`. The test's matching is weak (§3.4) but the
  tree is clean today.
- **Hardcoded country / provider / IP / domain / port in code: none.** The only
  grep hit for "Russia" in `control/` or `edge/` is a comment at
  `control/app/settings.py:26`. No IP literals, no provider names, no port
  constants outside compose and the Dockerfile's `EXPOSE 8000`.
- **Anything that logs a path or a connection: none.** There is no `logging`
  call and no `print` anywhere in `control/` or `edge/`. Uvicorn runs
  `--no-access-log` (`control.Dockerfile:21`); Caddy discards both the default
  logger and the per-site logger (`deploy/caddy/Caddyfile:22,28`). The only
  logging in the repo is `deploy/warden/warden.py`, which logs job ids, kinds,
  task ids and intents — fleet metadata, no user or connection data. Caveat from
  §3.4: nothing *tests* that these settings stay.
- **Secrets in git: none.** `.env` is untracked, in `.gitignore`, and in
  `.dockerignore`. `.env.example` carries only placeholder values. No key or
  certificate material is tracked. No `__pycache__` is tracked.
- **TODO / FIXME / stub markers in handed-over code: none.**
- **Public signup, payment, or advertising code: none.**
- **Shared Reality decoy default: none** — because no Reality profile exists at
  all.

### 5.7 Lesser observations

- Postgres is started and health-gated for a `control` service that has no
  database client and receives no database credentials. Harmless now; it means
  "the stack boots" proves less than it appears to.
- `deploy/warden/` sits inside the `infra` zone path (`deploy/**`) and is linted
  by `make test-infra` (`Makefile:54`) but has **zero tests**, despite being the
  largest piece of first-party runtime code in the repository.
- In a dev run, Caddy will attempt ACME for `hashi.example.com` and fail
  repeatedly. `README.md:32-33` routes the developer around it (talk to
  `127.0.0.1:8000`), so it is noise rather than a blocker.
- `docs/tracker/notifications.log` and the `product-owner-ohno-3/-4` tracker
  directories are untracked, while `workflow.md` states "tracker artifacts are
  never deleted". They are never committed either, so the fleet's record of its
  own decisions currently lives only in the working tree.
- `.e2e/profile.yml` points at `docs/e2e/README.md §10 in the Kaizen repo`, a
  document not present here, and states that nothing consumes the file.

---

## 6. What `deploy/warden/` is

**Not product code.** It is the project side of Kaizen's tracker-v2 contract:
a gRPC daemon that lets an external Hub dispatch work into *this repository's own
agent fleet*. It has no relationship to the VPN, and `README.md` and the compose
file both say the two stacks are independent.

Mechanism (`deploy/warden/warden.py`, 339 lines):

1. `main()` builds a manifest (name, purpose, supported Directive kinds, the
   eight-agent roster as display metadata, `max_concurrent`), starts a gRPC
   server on `0.0.0.0:9200`, then enrolls with the Hub at `tracker:9104`. It
   serves before enrolling so a dispatch arriving at approval-time is not lost.
2. `run_pipeline(job)` maps a Directive `kind` to a slash command via
   `KIND_TO_COMMAND` (`develop`, `fix`, `refactor`, `epic`, `review`,
   `research`, `product`) and shells out to `claude -p "<command> <intent>"` with
   `--model opus`, `--allowedTools "Read Write Edit Bash Glob Grep Task TodoWrite
   WebSearch WebFetch"`, `--output-format stream-json`. It pins the fleet's
   task-id to the Directive's and tells the run it is unattended.
3. `_mirror_statuses(job)` polls `docs/tracker/{task_id}/status/*.yml` every 5s
   and forwards changed entries to the Hub — the agents write files, the warden
   does the network. Failures in the mirror are caught so they cannot kill a job.
4. Timeouts: `RUN_TIMEOUT_S=5400` overall, `IDLE_TIMEOUT_S=600` on stream
   silence; both paths kill the child process.
5. Outcome mapping: a run that changed the tree returns state `review`, **never
   `done`** — the changes sit uncommitted and no human has seen them. A clean run
   with no changes returns `done`.

Deployment (`deploy/warden/docker-compose.yml`): its own compose project
`hashi-warden`, joined to the external `kaizen_default` network; mounts the repo
root at `/repo` **read-write** and a named volume at `/state` for the enrollment
secret, Hub token and `claude` CLI login. `MAX_CONCURRENT=1`, because the fleet
edits a real working tree with no worktree isolation.

`deploy/warden/vendor/infra/` is a committed copy of Kaizen's `wardenkit` and
generated protobuf stubs (10 files), stamped in `vendor/KAIZEN_COMMIT`, refreshed
by `make warden-sync KAIZEN=...`, and excluded from ruff. Its runtime dependency
set is `grpcio` + `protobuf`.

Evidence it is live: `docs/tracker/product-owner-ohno-4/status/warden.yml` shows
`progress: "running /research"`, and `product-owner-ohno-3/status/warden.yml`
shows `"/research exited 1"` — a previous dispatch of this same request failed.

Risk profile, restated for the record: an unattended fleet with `Bash` and write
access to the working tree, in a container that also has network egress, with
real `.env` secrets inside the mount. The README names the mount and the
tool-allowlist as the things to think twice about; it does not name `.env`.

---

## Metadata

- **Date:** 2026-08-01
- **Method:** repository survey — full file walk, targeted greps, one packaging
  experiment (§5.1), one real `make setup` + `make test` run (§3.1). No web
  searches: the assignment is an internal ground-truth survey, not an external
  research question.
- **Commit surveyed:** `1cfd7d7` (`main` == `develop`)
- **Verification run:** `make test` — 14 passed, ruff clean, exit 0
- **Not run:** `make up`, `make up-dev`, `make test-e2e` (Docker not exercised)
