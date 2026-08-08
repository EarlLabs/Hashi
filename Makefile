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

.PHONY: setup env test test-control test-edge test-infra test-e2e lint \
        up up-dev down logs ps e2e-up e2e-down e2e-reset \
        e2e-secrets e2e-secrets-live

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

# Static verification of all three zones. Deliberately does NOT include e2e:
# those need a booted stack, and a `make test` that silently requires Docker is a
# `make test` that agents start skipping. Run `make test-e2e` separately.
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

# Production shape: nothing is published to the outside world.
up: env
	$(COMPOSE) up -d --build

# Dev overlay: the only thing that publishes ports, and only to 127.0.0.1.
up-dev: env
	$(COMPOSE_DEV) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

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
COMPOSE_E2E  := docker compose --env-file .env -p $(E2E_PROJECT) \
                -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml
E2E_PORTS    := DEV_API_PORT=$(E2E_API_PORT) DEV_DB_PORT=$(E2E_DB_PORT)

e2e-up: env
	$(E2E_PORTS) $(COMPOSE_E2E) up -d --build

e2e-down:
	$(E2E_PORTS) $(COMPOSE_E2E) down -v

# Isolation is per-run (the stack is torn down with its volumes), so there is
# nothing to reset between scenarios. Kept as a target so the profile can name it.
e2e-reset:
	@echo "isolation is per-run — nothing to reset"

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
