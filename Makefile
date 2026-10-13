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
# The deployed shape: the base stack plus the only overlays that open a port on a
# real host. Never the dev overlay — that publishes the database.
#
# Two of them, and the split is M28.10's: everything a deployed host publishes whether
# or not it has a management tunnel is in public.yml, and the console on the TUNNEL's
# own address — the one mapping that needs an address this host actually holds — is in
# tunnel.yml. A host restored from a bucket has no tunnel yet, so `up-panel` there fails
# on a bind docker cannot make, and `up-panel-over-ssh` below is the same publication
# without that one line.
COMPOSE_PANEL_SSH := $(COMPOSE) -f deploy/docker-compose.public.yml
COMPOSE_PANEL := $(COMPOSE_PANEL_SSH) -f deploy/docker-compose.tunnel.yml

.PHONY: setup env verify e2e-verify test test-control test-edge test-infra test-e2e lint \
        up up-dev up-panel up-panel-over-ssh restart-control down logs ps \
        e2e-up e2e-down e2e-reset e2e-psql \
        e2e-secrets e2e-secrets-live panel-bootstrap mgmt-tunnel node-bootstrap hash-password

## --- setup ------------------------------------------------------------------

setup:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -e ".[dev]"
	@echo "ready — run: make test"

# The state directory is created HERE, before anything brings the stack up, and that
# ordering is the whole reason it is in this target: the control service mounts it
# read-only (deploy/docker-compose.yml), and a bind mount whose source does not exist is
# created by the docker daemon — as root. The backup schedule, which runs as the operator,
# could then never write the record it exists to write.
env:
	@test -f .env || { cp .env.example .env; echo ".env created from .env.example — fill it in"; }
	@mkdir -p backups/state deploy/delivery

# Every script under scripts/ is a bash script (`#!/usr/bin/env bash`), and Make runs
# recipes with /bin/sh — so a host without bash used to meet `env: can't execute 'bash'`,
# exit 127, before a single one of the script's own prerequisite checks could say anything
# (M31.7, the restore walk on a minimal image). Asked here, in sh, before the script is
# started; every recipe that runs one of them starts with it, which
# tests/infra/test_a_bare_host_can_finish_the_restore.py holds them to.
define need_bash
@command -v bash >/dev/null 2>&1 || { \
  echo "this command runs a bash script, and this machine has no bash."; \
  echo "Install it with the package manager (e.g. apk add bash, apt-get install bash),"; \
  echo "then run the same command again. Nothing has been changed."; \
  exit 1; }
endef

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
	$(PY) -m ruff check tests/infra deploy/backup deploy/warden .e2e
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

# The same publication on a host that has no management tunnel yet — which is every
# host `make restore-from-bucket` has just rebuilt, because the tunnel's keys were on
# the machine that was lost and a fresh one has no address to bind to. `make up-panel`
# there fails on `cannot assign requested address`, and the walk that found it answered
# with `ip addr add`, by hand, at the point where the operator cannot log in yet.
#
# What it publishes: the delivery endpoint on 80/443, and the console on THIS HOST'S
# LOOPBACK only. Nothing off the box can reach the console; you reach it the way the
# runbook's "The way back in when the tunnel is unavailable" already describes, and
# which the field run used all night:
#
#   ssh -L <HASHI_PRIVATE_PORT>:127.0.0.1:<HASHI_PRIVATE_PORT> you@this-host
#
# It is not a weaker `up-panel`: the mapping it leaves out is an ADDITIONAL address to
# reach the same console on, and nothing here publishes the console on an address the
# internet can reach. Move to `make up-panel` once the tunnel is up.
up-panel-over-ssh: env
	$(NO_ATTESTATIONS) $(COMPOSE_PANEL_SSH) up -d --build

# What to run after a restore, and deliberately not `make down && make up`.
#
# The restore used to end by telling the operator exactly that, and on a deployed host
# it is the one sequence the Makefile itself warns against: `make up` converges the
# stack back to the base file's shape and takes the published ports away, so the
# instruction that was supposed to finish a rebuild ends with a panel nobody can reach
# (M28.10, finding 3). `restart` restarts the containers that are there and changes
# nothing about what the stack publishes, so it is correct whichever of `up-dev`,
# `up-panel` and `up-panel-over-ssh` this host was brought up with.
restart-control:
	$(COMPOSE) restart control

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
	$(need_bash)
	@scripts/panel-bootstrap.sh $(if $(ENV_FILE),--env-file $(ENV_FILE),)

# The management tunnel ALONE: writes the host file, hands out new devices' configs,
# removes unlisted ones — and touches no container. This is what adding or removing a
# device runs on a host that is already serving (M33.4, finding D1).
#
# It exists because a device change used to be a re-run of `make panel-bootstrap`, and
# on the real host (2026-10-03) that re-run took Caddy's 80/443 and the console away:
# users' /sub/ answered "connection refused" until `make up-panel`. Rejected: having panel-bootstrap re-publish what it
# found — which overlay a host was published with is not something the running stack
# says reliably, and guessing wrong publishes the console somewhere it was not.
#
# HASHI_MGMT_DIR and HASHI_MGMT_CONFIGS_TO are read from this command's environment by
# the script, so `HASHI_MGMT_CONFIGS_TO=~/mgmt-devices make mgmt-tunnel` works as it does
# for panel-bootstrap.
.PHONY: mgmt-tunnel

mgmt-tunnel:
	$(need_bash)
	@scripts/management-tunnel.sh $(if $(ENV_FILE),--env-file $(ENV_FILE),)

# The one value in .env that cannot be typed, on a host where nothing can produce it.
#
# HASHI_OPERATOR_PASSWORD_HASH comes from `python -m control.cli hash-password`, which
# needs this project's dependencies and Python 3.14 — and a rented Ubuntu box has 3.10,
# no venv and no way to make one (`make setup` looks for python3.14 and does not find
# it). So the restore runbook asked for four values and one of them could only be made
# on a SECOND working machine, which is the difference between "read the command" and
# "have another computer" (M28.10, finding 1).
#
# It runs in the control image, which is the same answer this project already gives for
# pg_dump and for age: the tool lives where the stack lives, and the host needs nothing
# but a container runtime. Nothing here reads an env file — it cannot, because the file
# is what this command exists to help fill in.
hash-password:
	$(need_bash)
	@scripts/hash-password.sh

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

## --- the control plane's own node commands (see control/cli.py) ------------

# Run INSIDE the running control container, on the control-plane host, where the database
# and HASHI_SECRET_KEY already are: no operator password, no browser. They exist for
# `make restore-node` (below), which calls them over SSH from the operator's machine, and
# they are ordinary verbs on the host for the same three steps by hand. NAME is a node's
# name as the panel shows it. Each prints `key=value` lines and exits 1 with a sentence.
.PHONY: node-plan node-relocate node-apply

node-plan:
	@test -n "$(NAME)" || { echo "usage: make node-plan NAME=<node name>"; exit 2; }
	@$(COMPOSE) exec -T control python -m control.cli node-plan "$(NAME)"

# ARGS carries --ssh-host, --ssh-user and --ssh-port (all three required), and optionally
# --address and --host-key '<one public host-key line>'. Quote it.
node-relocate:
	@test -n "$(NAME)" || { echo "usage: make node-relocate NAME=<node name> ARGS=\"--ssh-host H --ssh-user U --ssh-port N\""; exit 2; }
	@$(COMPOSE) exec -T control python -m control.cli relocate-node "$(NAME)" $(ARGS)

node-apply:
	@test -n "$(NAME)" || { echo "usage: make node-apply NAME=<node name>"; exit 2; }
	@$(COMPOSE) exec -T control python -m control.cli apply-node "$(NAME)"

## --- rebuilding a lost host, from YOUR machine (M36) -------------------------

# The two commands for the day a box is gone. Both run on the operator's own machine,
# from this checkout, and reach the new host over SSH — nothing needs to be typed on it.
#
#   make restore-panel HOST=root@NEW_IP
#       the control plane, from the bucket: prerequisites, code, .env, restore, publish,
#       backup schedule. Reads secrets/server.env, secrets/restore.env and
#       secrets/hashi-backup-identity.txt (override with SERVER_ENV=, RESTORE_ENV=,
#       IDENTITY=); the identity is on the new host only for the restore and is shredded
#       after it, failure included.
#   make restore-node NODE=entry-1 HOST=root@NEW_IP [ACCOUNT=hashi] [PANEL=root@PANEL_IP]
#       one node, onto a fresh host, from the restored control plane's record: account,
#       key, firewall, the record moved to the new host (audited), apply.
#
# Move DNS first: the panel command waits for HASHI_PUBLIC_HOST to resolve to HOST
# before it asks a public CA for a certificate. See docs/deploy/runbook.md, the cheat
# sheet's "Восстановить после потери сервера".
.PHONY: restore-panel restore-node

restore-panel:
	$(need_bash)
	@test -n "$(HOST)" || { echo "usage: make restore-panel HOST=user@new-host [SSH_PORT=N] [OBJECT=name]"; exit 2; }
	@scripts/restore-panel.sh --host "$(HOST)" \
	  $(if $(SSH_PORT),--ssh-port "$(SSH_PORT)",) \
	  $(if $(DIR),--dir "$(DIR)",) \
	  $(if $(SERVER_ENV),--server-env "$(SERVER_ENV)",) \
	  $(if $(RESTORE_ENV),--restore-env "$(RESTORE_ENV)",) \
	  $(if $(IDENTITY),--identity "$(IDENTITY)",) \
	  $(if $(OBJECT),--object "$(OBJECT)",)

restore-node:
	$(need_bash)
	@test -n "$(NODE)" -a -n "$(HOST)" || { echo "usage: make restore-node NODE=<node name> HOST=user@new-host [ACCOUNT=hashi] [PANEL=user@panel-host]"; exit 2; }
	@scripts/restore-node.sh --node "$(NODE)" --host "$(HOST)" \
	  $(if $(SSH_PORT),--ssh-port "$(SSH_PORT)",) \
	  $(if $(ACCOUNT),--account "$(ACCOUNT)",) \
	  $(if $(PANEL),--panel "$(PANEL)",) \
	  $(if $(PANEL_SSH_PORT),--panel-ssh-port "$(PANEL_SSH_PORT)",) \
	  $(if $(DIR),--dir "$(DIR)",) \
	  $(if $(NODE_SSH_HOST),--node-ssh-host "$(NODE_SSH_HOST)",) \
	  $(if $(NODE_SSH_PORT),--node-ssh-port "$(NODE_SSH_PORT)",) \
	  $(if $(ADDRESS),--address "$(ADDRESS)",) \
	  $(if $(KEY),--key "$(KEY)",)

## --- backup / restore (see scripts/backup.sh) -------------------------------

# The control database is the single source of truth, so it is the one thing whose
# loss cannot be repaired by rebuilding a node. The WHOLE dump is encrypted with age, to
# HASHI_BACKUP_AGE_RECIPIENT, before it reaches the disk — this host holds only the public
# half, so it can write a backup and cannot read one back. Underneath that layer the
# columns holding node and user secrets are encrypted again and are useless without
# HASHI_SECRET_KEY; back that up separately and keep it somewhere the age identity is not.
# A restore costs both, and neither of them lives on this machine. See the script's own
# warning, and docs/deploy/runbook.md, "Backups".
#
# With HASHI_BACKUP_ENABLED=1 the same artifact is then sent to the object store in the
# HASHI_BACKUP_S3_* block, with a credential that may only write — so this host can add to
# the backup history and can neither read nor destroy it. `make backup` exits 3, not 0,
# when the dump succeeded and the upload did not: the file is here, and a backup that
# never left the machine is not an offsite backup.
#
# WHEN it happens is `make backup-schedule` — one cron entry that calls
# scripts/backup-run.sh every 15 minutes. The entry carries no hour on purpose: the hour
# is HASHI_BACKUP_AT in HASHI_BACKUP_TZ, decided by that script, so a box that was down at
# 04:00 takes the day's backup when it comes back instead of skipping the day in silence.
# `make backup-status` is what the record of all that says.
.PHONY: backup backup-upload backup-schedule backup-unschedule backup-status restore \
        restore-from-bucket checkers

# Goes through the recorder rather than straight to the script, so that a backup taken by
# hand counts as the day's backup: without it the panel would report a host as un-backed-up
# an hour after its operator backed it up, and the schedule would take a second one at
# 04:00 for a day that already had one. What it prints is scripts/backup.sh's own output,
# unchanged, and it exits with the same 0/1/3.
backup:
	$(need_bash)
	@scripts/backup-run.sh now

# The schedule itself. Idempotent: it replaces its own block in this account's crontab and
# leaves every other line alone. No root, no new package, no daemon of ours — see the
# script's header for why a container with the docker socket was rejected instead.
backup-schedule:
	$(need_bash)
	@scripts/backup-schedule.sh install

backup-unschedule:
	$(need_bash)
	@scripts/backup-schedule.sh remove

# "When did a backup last succeed, and has one failed since?" — answered from the record
# on this host, because the credential here may only write and cannot look in the bucket.
backup-status:
	$(need_bash)
	@scripts/backup-run.sh status

# What exit 3 leaves you holding. Sends an artifact that is already on disk, and never
# dumps — so it costs the database nothing and can be retried as often as the store needs.
backup-upload:
	@test -n "$(FROM)" || { echo "usage: make backup-upload FROM=backups/hashi-....sql.gz.age"; exit 2; }
	$(need_bash)
	@scripts/backup.sh upload "$(FROM)"

# Deliberately requires the path on the command line rather than picking the newest
# dump: restoring is destructive and "the latest one" is not a decision a Makefile
# should make for the operator.
#
# The age identity is handed over at the moment of the restore and never stored here:
#   HASHI_RESTORE_AGE_IDENTITY=/path/to/identity make restore FROM=backups/hashi-....sql.gz.age
# An artifact written before the encryption existed — plain SQL, gzipped — still restores
# and needs no identity. The script tells the two apart by reading the file, not its name.
restore:
	@test -n "$(FROM)" || { echo "usage: make restore FROM=backups/hashi-....sql.gz.age"; exit 2; }
	$(need_bash)
	@scripts/backup.sh restore "$(FROM)"

# The one for the day the machine is gone, and the only verb here that is a whole rebuild
# rather than a step of one. On a host that has never run this project it installs the
# control plane, reads the bucket with a credential you are carrying, takes the newest
# artifact that actually opens and restores it:
#
#   HASHI_RESTORE_AGE_IDENTITY=/path/to/identity \
#   HASHI_RESTORE_S3_ACCESS_KEY_ID=... HASHI_RESTORE_S3_SECRET_ACCESS_KEY=... \
#   make restore-from-bucket
#
# Three inputs, all carried by the operator and none of them on the host that was lost:
# HASHI_SECRET_KEY, which goes in this machine's own .env because the control plane cannot
# start without it; the age identity; and a READ credential for the bucket. The last two
# are taken from this command's environment and are never written into an env file here —
# that is what the HASHI_RESTORE_* names are for, and the command refuses rather than
# reading them from anywhere else.
#
# OBJECT= names a specific artifact instead of the newest that opens. Unlike `restore`,
# which deliberately makes the operator name a file, this one does choose — because the
# operator cannot see into the bucket and the alternative is a restore that cannot be
# started at all. What it chose is printed beside everything it did not choose.
#
# What it does NOT do — DNS, the delivery endpoint's certificate, telling any user
# anything — it says on its last screen, and docs/deploy/runbook.md says it beside the
# command. A restored control plane on a new address that the old name still does not
# point at serves nobody.
restore-from-bucket:
	$(need_bash)
	@scripts/backup.sh restore-from-bucket $(if $(OBJECT),"$(OBJECT)",)

# Fetch the upstream data-plane checkers, so the validation tests stop skipping.
checkers:
	$(need_bash)
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
#
# Recursively expanded (`=`, not `:=`) so `e2e-down` below can widen E2E_PROFILES
# for itself. With `:=` the profile list would be frozen at the empty value this
# file starts with, and the target-specific override would silently do nothing.
COMPOSE_E2E  = docker compose --env-file .env --env-file deploy/e2e.env -p $(E2E_PROJECT) \
                $(foreach p,$(E2E_PROFILES),--profile $(p)) \
                -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml \
                -f deploy/docker-compose.e2e.yml
E2E_PORTS    := DEV_API_PORT=$(E2E_API_PORT) DEV_DB_PORT=$(E2E_DB_PORT) \
                DEV_BIND_ADDR=$(E2E_BIND_ADDR)

# EVERY profile the e2e overlay defines — what `down` has to know about, whatever
# `up` was asked for. `docker compose down` only touches services in the profiles
# CURRENTLY enabled, so a `down` with no profile did not know `browser` existed
# and left it running: one leaked container per acceptance run, each holding a
# gigabyte of shared memory. Worse, it defeated `stand.sh up`'s own safety check —
# that refuses to continue if anything still answers /healthz, and a leaked
# browser answers nothing, so it passed and accumulated.
# tests/infra/test_the_hands_can_take_an_action.py fails if the overlay grows a
# profile this list does not have.
E2E_ALL_PROFILES := browser

e2e-up: env
	$(NO_ATTESTATIONS) $(E2E_PORTS) $(COMPOSE_E2E) up -d --build

# `down` takes away everything any `up` could have started, not only what this
# invocation happened to ask for — see E2E_ALL_PROFILES.
# `override`, deliberately: without it a command-line `E2E_PROFILES=...` silently
# wins over a target-specific variable, which is a latent way to defeat the very
# leak this line exists to close (M12.4 — a browser left running per acceptance
# run, holding 1 GB of shm). Teardown takes everything, always.
e2e-down: override E2E_PROFILES := $(E2E_ALL_PROFILES)
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
