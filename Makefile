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
        warden-sync warden-up warden-down warden-logs

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
	$(PY) -m ruff check tests/infra deploy/warden
	$(PY) -m pytest tests/infra -q

# Acceptance scenarios, run against the disposable e2e stack (`make e2e-up`) —
# never against your dev stack, and this target does not boot one for you,
# because a target that boots and tears down hides which state a failure came
# from. Scenarios live in tests/e2e/<zone>/, owned by that zone's developer.
# Exit code 5 is pytest's "no tests ran": on a fresh clone there are no scenarios
# yet, and that is a true statement rather than a failure.
test-e2e:
	$(need_venv)
	@curl -fsS http://127.0.0.1:$(E2E_API_PORT)/healthz >/dev/null 2>&1 || { \
	  echo "no e2e stack on 127.0.0.1:$(E2E_API_PORT) — run: make e2e-up"; exit 1; }
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

# Where Kaizen lives, for the vendored kit. Override: make warden-sync KAIZEN=…
KAIZEN        ?= $(HOME)/stuff/projects/Kaizen
WARDEN_VENDOR := deploy/warden/vendor
COMPOSE_WARDEN := docker compose -f deploy/warden/docker-compose.yml

# Refresh the vendored copy of Kaizen's project-side kit. Vendored rather than
# imported because hashi is a separate repository and there is no package index
# to install it from — see deploy/warden/README.md.
warden-sync:
	@test -d "$(KAIZEN)/infra/wardenkit" || { \
	  echo "no Kaizen at $(KAIZEN) — run: make warden-sync KAIZEN=/path/to/Kaizen"; exit 1; }
	rm -rf $(WARDEN_VENDOR)/infra
	mkdir -p $(WARDEN_VENDOR)/infra/proto
	cp "$(KAIZEN)/infra/__init__.py"       $(WARDEN_VENDOR)/infra/
	cp "$(KAIZEN)/infra/proto/__init__.py" $(WARDEN_VENDOR)/infra/proto/
	cp -R "$(KAIZEN)/infra/proto/gen"      $(WARDEN_VENDOR)/infra/proto/gen
	cp -R "$(KAIZEN)/infra/wardenkit"      $(WARDEN_VENDOR)/infra/wardenkit
	find $(WARDEN_VENDOR) -name __pycache__ -type d -prune -exec rm -rf {} +
	@# `-dirty` matters: the kit is usually edited before it is committed, so a
	@# bare hash would claim two different vendored copies are the same one.
	@{ git -C "$(KAIZEN)" describe --always --dirty --abbrev=7 2>/dev/null \
	   || echo "unknown"; } > $(WARDEN_VENDOR)/KAIZEN_COMMIT
	@echo "vendored from Kaizen @ $$(cat $(WARDEN_VENDOR)/KAIZEN_COMMIT)"

# The Kaizen stack must be up first — this joins its network.
warden-up:
	$(COMPOSE_WARDEN) up -d --build

warden-down:
	$(COMPOSE_WARDEN) down

warden-logs:
	$(COMPOSE_WARDEN) logs -f --tail=100

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
