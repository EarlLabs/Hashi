# hashi — the project's verbs.
#
# WHAT: every operation an owner or an agent performs, as a Make target.
# WHY:  the same verbs mean the same thing in every project built from this kit;
#       a documented `docker compose` incantation that is not a target is a bug.
# HOW:  `make setup` once, then `make test` / `make up-dev`. Compose always runs
#       with --env-file, because without it ${VAR} silently becomes "".

PYTHON      ?= python3.14
VENV        := .venv
PY          := $(VENV)/bin/python
COMPOSE     := docker compose --env-file .env -f deploy/docker-compose.yml
COMPOSE_DEV := $(COMPOSE) -f deploy/docker-compose.dev.yml
# The deployed shape: the base stack plus the only overlay that opens a port on a
# real host. Never the dev overlay — that publishes the database.
COMPOSE_PANEL := $(COMPOSE) -f deploy/docker-compose.public.yml

.PHONY: setup env verify e2e-verify test test-control test-edge test-infra test-e2e lint \
        up up-dev up-panel down logs ps e2e-up e2e-down e2e-reset e2e-psql \
        e2e-secrets e2e-secrets-live panel-bootstrap node-bootstrap

## --- setup ------------------------------------------------------------------

setup:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -e ".[dev]"
	@echo "ready — run: make test"

env:
	@test -f .env || { cp .env.example .env; echo ".env created from .env.example — fill it in"; }

# Every verify target needs the venv. Fail with an instruction, not a traceback.
define need_venv
@test -x $(PY) || { echo "no $(VENV) yet — run: make setup"; exit 1; }
endef

## --- verification -----------------------------------------------------------

# THE GATE. One command, and the honest answer to "is this green".
#
# `make test` is deliberately not that answer and never was — see its comment
# below. The hole was that nothing else was: "run `make test-e2e` separately" is
# an instruction to a person, and an unattended run has no person. Eleven
# milestones were gated on `make test` alone; tests/e2e ran three times in the
# whole run, by accident, and a scenario that had been failing since before it
# started was found the same way.
#
# So both halves keep their properties: `test` still needs no Docker and still
# means what it meant, and `verify` needs one and says so loudly rather than
# skipping. A gate whose absence looks like success is the thing being fixed.
verify: test e2e-verify

# The e2e half on its own, for CI, where the three zone jobs already ran `test`.
#
# The stand is torn down whether the scenarios passed or not, and the scenarios'
# exit code is what this target exits with: `e2e-down` runs `down -v`, so leaving
# it out on failure would leave a stack and its volumes behind on every red run.
# That is the trade the Makefile's own comment on `test-e2e` warns about — you
# lose the failed stack to inspect. Reach for `make e2e-up && make test-e2e`
# when that is what you need; this target is for the gate, which has nobody
# waiting to look.
e2e-verify:
	$(need_venv)
	@docker info >/dev/null 2>&1 || { \
	  echo "make verify needs a running docker engine: it boots the e2e stack and runs"; \
	  echo "tests/e2e against it, and \`docker info\` just failed."; \
	  echo ""; \
	  echo "This is a failure and not a skip on purpose. A gate that passes when its"; \
	  echo "engine is missing is how tests/e2e went unrun for eleven milestones."; \
	  echo ""; \
	  echo "Start docker, or run \`make test\` for the three static zones only —"; \
	  echo "which is a smaller claim, not the same one."; \
	  exit 1; }
	@$(MAKE) --no-print-directory e2e-up
	@status=0; $(MAKE) --no-print-directory test-e2e || status=$$?; \
	  $(MAKE) --no-print-directory e2e-down >/dev/null || true; \
	  exit $$status

# Static verification of all three zones. Deliberately does NOT include e2e:
# those need a booted stack, and a `make test` that silently requires Docker is a
# `make test` that agents start skipping. `make verify` is the one that includes
# them, and it fails rather than skips when there is no engine.
test: test-control test-edge test-infra

test-control:
	$(need_venv)
	$(PY) -m ruff check control tests/control
	$(PY) -m pytest tests/control -q

test-edge:
	$(need_venv)
	$(PY) -m ruff check edge tests/edge
	$(PY) -m pytest tests/edge -q

test-infra:
	$(need_venv)
	$(PY) -m ruff check tests/infra deploy/warden .e2e
	$(PY) -m pytest tests/infra -q

# Acceptance scenarios, run against the disposable e2e stack (`make e2e-up`) —
# never against your dev stack, and this target does not boot one for you,
# because a target that boots and tears down hides which state a failure came
# from. Scenarios live in tests/e2e/<zone>/, owned by that zone's developer.
# Exit code 5 is pytest's "no tests ran": on a fresh clone there are no scenarios
# yet, and that is a true statement rather than a failure.
# E2E_API_HOST defaults to the host loopback; the fleet's own /e2e run
# overrides it to hashi-dind, since a published port there lands on the
# isolated dind engine, never on 127.0.0.1 — see .e2e/profile.yml.
E2E_API_HOST ?= 127.0.0.1

test-e2e:
	$(need_venv)
	@curl -fsS http://$(E2E_API_HOST):$(E2E_API_PORT)/healthz >/dev/null 2>&1 || { \
	  echo "no e2e stack on $(E2E_API_HOST):$(E2E_API_PORT) — run: make e2e-up"; exit 1; }
	@$(PY) -m pytest tests/e2e -q; status=$$?; \
	  if [ $$status -eq 5 ]; then echo "no e2e scenarios yet"; exit 0; fi; exit $$status

lint:
	$(need_venv)
	$(PY) -m ruff check .

## --- running the stack ------------------------------------------------------

# NO_ATTESTATIONS is on every `up -d --build` in this file, and it is what makes
# them converge instead of churn.
#
# BuildKit attaches a provenance attestation to every image it exports, and the
# attestation records when the build ran. So a FULLY CACHED rebuild still exports
# a manifest with a new digest — which is the image ID compose compares against
# the running container — and compose recreated `control` and `caddy` on every
# single invocation, with nothing in the output to say why. Not the database:
# postgres is PULLED by tag rather than built, so it was never touched by this and
# no data was ever at risk. What it cost was a control-plane and TLS restart on
# every routine deploy, and a `make up` that could not be used to check whether a
# stack was already converged.
#
# The attestation is inert here: these images are built on the host that runs them
# and are never pushed anywhere that could check a signature. Found and fixed for
# scripts/panel-bootstrap.sh in M6.5, where the same behaviour made that script's
# own IDEMPOTENT header untrue; these three are the rest of it.
NO_ATTESTATIONS := BUILDX_NO_DEFAULT_ATTESTATIONS=1

# Production shape: nothing is published to the outside world.
up: env
	$(NO_ATTESTATIONS) $(COMPOSE) up -d --build

# Dev overlay: the only thing that publishes ports, and only to 127.0.0.1.
up-dev: env
	$(NO_ATTESTATIONS) $(COMPOSE_DEV) up -d --build

# The deployed panel host, M7: the delivery endpoint on 80/443 for everyone, and the
# console on the management tunnel's address and on loopback — never on a public one.
#
# This exists because that publication IS the milestone. It used to be a heredoc in the
# runbook that the operator typed onto the box, which was survivable while the answer was
# "Caddy, 80 and 443"; it is not survivable now that getting a bind address wrong is the
# difference between a private console and a public one. Use this on a deployed host and
# never plain `make up`, which converges the stack back to publishing nothing.
up-panel: env
	$(NO_ATTESTATIONS) $(COMPOSE_PANEL) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

## --- installing the panel on a host (see scripts/panel-bootstrap.sh) --------

# The second of the charter's two deployment scripts (the first is the node
# bootstrap in edge/bootstrap/). Bare host -> control plane, database and delivery
# endpoint, from one env file, with a real health probe before it claims success.
#
# ENV_FILE exists so a host can carry more than one stack — the acceptance
# scenarios install a throwaway one beside whatever is already there.
.PHONY: panel-bootstrap

panel-bootstrap:
	@scripts/panel-bootstrap.sh $(if $(ENV_FILE),--env-file $(ENV_FILE),)

## --- preparing a host to be a node (see scripts/node-bootstrap.sh) ----------

# The other half of the pair above: panel-bootstrap installs a control plane, this
# prepares a host the control plane can then drive. It runs ON the node, and it is
# piped there rather than copied — nothing of this repository is left on a node.
#
# NODE is user@host and never lives in this file: a node's address is node-record
# data, like its country and its ports. ARGS carries the public key and one --port
# per transport; quote it, the key contains spaces.
.PHONY: node-bootstrap

node-bootstrap:
	@test -n "$(NODE)" || { echo "usage: make node-bootstrap NODE=user@host ARGS=\"--authorized-key '<public key>' --port <number>/udp\""; exit 2; }
	@ssh $(if $(SSH_PORT),-p $(SSH_PORT),) $(NODE) "bash -s -- $(ARGS)" < scripts/node-bootstrap.sh

## --- backup / restore (see scripts/backup.sh) -------------------------------

# The control database is the single source of truth, so it is the one thing whose
# loss cannot be repaired by rebuilding a node. The dump is useless without
# HASHI_SECRET_KEY — back that up separately, and see the script's own warning.
.PHONY: backup restore checkers

backup:
	@scripts/backup.sh dump

# Deliberately requires the path on the command line rather than picking the newest
# dump: restoring is destructive and "the latest one" is not a decision a Makefile
# should make for the operator.
restore:
	@test -n "$(FROM)" || { echo "usage: make restore FROM=backups/hashi-....sql.gz"; exit 2; }
	@scripts/backup.sh restore "$(FROM)"

# Fetch the upstream data-plane checkers, so the validation tests stop skipping.
checkers:
	@scripts/fetch-upstream-checkers.sh

## --- warden: the tracker integration (see deploy/warden/README.md) ----------

# The Warden fleet is its OWN stack now, with its own Makefile and its own
# .env — run it from deploy/warden/, never from here:
#   cd deploy/warden && make up            # start the fleet (dev)
#   cd deploy/warden && make login         # one-time claude CLI /login
#   cd deploy/warden && make vendor-kit    # refresh the vendored Kaizen kit
#   cd deploy/warden && make down / logs / ps
# The Kaizen stack (`cd ~/stuff/projects/Kaizen && make up`) must be up first
# — the Warden joins its network to reach the Hub.
#
# `warden-scenarios` (WARDEN_FAKE_PIPELINE-driven contract tests against the
# real Hub) is RETIRED as of the kit v4 warden.py: that env var no longer
# exists upstream (the hand-rolled pipeline it hooked into was replaced by
# ClaudeRunner). `deploy/warden/scenarios.py` is kept but currently has no
# fake-pipeline mode to drive it — needs a follow-up decision, not silently
# patched back in here.

## --- e2e (see .e2e/profile.yml) ---------------------------------------------

# The e2e stack is a SEPARATE compose project with its own volumes and its own
# host ports. That is what makes `down -v` safe here and nowhere else: it
# destroys `hashi-e2e_*` volumes, never the `hashi_*` ones your dev stack uses.
# Sharing a project between the two would mean one `make e2e-down` wipes the
# database you were working against.
E2E_PROJECT  := hashi-e2e
E2E_API_PORT ?= 54200
E2E_DB_PORT  ?= 54232
# Loopback by default, exactly like the dev stack. Override ONLY when the engine
# is not the machine you are sitting at — the fleet's dind engine, where
# 127.0.0.1 is dind's own loopback and no test runner can reach it:
#   make e2e-up E2E_BIND_ADDR=0.0.0.0
# dind is an isolated engine on an internal network, so 0.0.0.0 there is not the
# same promise as 0.0.0.0 on a laptop. See deploy/docker-compose.dev.yml.
E2E_BIND_ADDR ?= 127.0.0.1
# docker-compose.e2e.yml is what keeps a test run away from the owner's real
# delivery hostname — without it Caddy asks a public CA for a certificate for
# the production domain every time someone runs e2e. See that file's header.
# TWO env files, and the order is the point: `.env` first for anything the owner has
# set, then deploy/e2e.env, whose fake values win. Without the second one the
# acceptance suite is unbootable whenever the owner's `.env` is missing a required key
# — and it inherits the owner's real identity when it is not. See deploy/e2e.env.
#
# E2E_PROFILES names compose profiles to switch on, space separated. Only the
# acceptance browser uses one today: its image is ~2 GB and a test run that speaks
# nothing but HTTP should not wait for it. `scripts/acceptance/stand.sh up` passes
# E2E_PROFILES=browser; `make e2e-up` alone stays exactly as fast as it was.
COMPOSE_E2E  := docker compose --env-file .env --env-file deploy/e2e.env -p $(E2E_PROJECT) \
                $(foreach p,$(E2E_PROFILES),--profile $(p)) \
                -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml \
                -f deploy/docker-compose.e2e.yml
E2E_PORTS    := DEV_API_PORT=$(E2E_API_PORT) DEV_DB_PORT=$(E2E_DB_PORT) \
                DEV_BIND_ADDR=$(E2E_BIND_ADDR)

e2e-up: env
	$(NO_ATTESTATIONS) $(E2E_PORTS) $(COMPOSE_E2E) up -d --build

e2e-down:
	$(E2E_PORTS) $(COMPOSE_E2E) down -v

# Isolation is per-run (the stack is torn down with its volumes), so there is
# nothing to reset between scenarios. Kept as a target so the profile can name it.
e2e-reset:
	@echo "isolation is per-run — nothing to reset"

# psql inside the e2e stack's database, reading SQL from stdin. Exists so
# scripts/acceptance/stand.sh does not have to repeat COMPOSE_E2E by hand: both
# --env-file flags and `-p hashi-e2e` are load-bearing (see their comments above),
# and a second copy of that command is a copy that drifts. The credentials are
# read from the container's own environment, so they cannot disagree with the ones
# the database was created with.
e2e-psql:
	@$(E2E_PORTS) $(COMPOSE_E2E) exec -T db \
	  sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# Regenerate throwaway e2e tokens into .env.e2e.generated (flow/contract
# tiers — no real credentials involved, see docs/e2e/README.md §8). Edit
# .env.e2e.generated.example, not the script, to change which keys this
# project generates.
e2e-secrets:
	@$(PYTHON) .e2e/e2e_gen_secrets.py

# Same, but also checks .env.e2e.live.secrets exists and has the expected
# keys — required for the manual `live` tier only, never an automatic gate.
e2e-secrets-live:
	@$(PYTHON) .e2e/e2e_gen_secrets.py --live
