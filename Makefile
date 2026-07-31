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

.PHONY: setup env test test-control test-edge test-infra lint \
        up up-dev down logs ps e2e-up e2e-down e2e-reset

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
	$(PY) -m ruff check tests/infra
	$(PY) -m pytest tests/infra -q

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

## --- e2e (see .e2e/profile.yml) ---------------------------------------------

e2e-up: up-dev

e2e-down:
	$(COMPOSE_DEV) down -v

# Isolation is per-run (the stack is torn down with its volumes), so there is
# nothing to reset between scenarios. Kept as a target so the profile can name it.
e2e-reset:
	@echo "isolation is per-run — nothing to reset"
