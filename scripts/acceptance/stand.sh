#!/usr/bin/env bash
#
# hashi — the disposable stand an acceptance agent walks.
#
# WHAT: `up` brings up a throwaway control plane and prints how to reach it;
#       `down` destroys it with its volumes.
# WHY:  the acceptance agent clicks everything, types a thousand characters into
#       fields, double-clicks buttons and abandons flows halfway — on purpose.
#       That belongs somewhere that gets destroyed afterwards, never near the
#       owner's dev stack and never anywhere near a real deployment.
# HOW:  layered ON TOP of the existing e2e stand (`make e2e-up` / `e2e-down`),
#       not beside it. A second stack with the same services diverges from the
#       first within one milestone, and acceptance would then be checking a
#       configuration nobody ships. See .e2e/profile.yml for what that stand is.
#
# The one thing this file adds over `make e2e-up`: a database role that can read
# and cannot write, because the honest answer to "did the button actually save
# it?" cannot come from the same screen that claimed it did. See query.py.
set -euo pipefail

# Defaults mirror the Makefile's, and are overridable for the same single reason
# it documents: an engine that is not the machine you are sitting at. On the
# fleet's dind engine 127.0.0.1 is dind's own loopback, so nothing can reach a
# published port there — hence E2E_BIND_ADDR=0.0.0.0 and E2E_API_HOST=hashi-dind.
E2E_API_HOST="${E2E_API_HOST:-127.0.0.1}"
E2E_API_PORT="${E2E_API_PORT:-54200}"
E2E_DB_HOST="${E2E_DB_HOST:-$E2E_API_HOST}"
E2E_DB_PORT="${E2E_DB_PORT:-54232}"
READY_TIMEOUT="${READY_TIMEOUT:-180}"

# The read-only role the acceptance agent reads through. Fixed and obviously fake,
# and committed on the same grounds as deploy/e2e.env: it guards a stack with no
# real nodes and no real friends in it, whose volume is destroyed on the way out.
# Nothing here may ever be copied into .env.
RO_ROLE="${ACCEPTANCE_DB_ROLE:-acceptance_ro}"
RO_PASSWORD="${ACCEPTANCE_DB_PASSWORD:-acceptance-ro-not-a-real-password}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

say() { printf '[stand] %s\n' "$*"; }
die() { printf '[stand] %s\n' "$*" >&2; exit 1; }

healthz() { curl -fsS --max-time 5 "http://${E2E_API_HOST}:${E2E_API_PORT}/healthz" >/dev/null 2>&1; }

up() {
  # Tear down whatever is already listening BEFORE starting anything. This is the
  # failure that does not announce itself: a previous stand still up answers the
  # health check, so `up` exits 0 while serving the PREVIOUS BUILD and the whole
  # acceptance run walks yesterday's code and reports on it. `down -v` also takes
  # the volume, so the next stack starts from nothing rather than from a database
  # in which every awkward first-time step has already been done.
  say "tearing down any previous stand"
  make e2e-down >/dev/null 2>&1 || true

  # And prove it is gone. A health check the old stand can satisfy is not a health
  # check — if something still answers here it is not ours, and starting on top of
  # it would produce a run that reports on a stack we did not build.
  if healthz; then
    die "something is still serving http://${E2E_API_HOST}:${E2E_API_PORT}/healthz after teardown — refusing to walk a stand we did not build"
  fi

  # E2E_PROFILES=browser adds the acceptance agent's Chromium (see
  # deploy/docker-compose.e2e.yml). It publishes nothing and reaches the control
  # plane over the compose network; the driver is scripts/acceptance/drive.py.
  # Set ACCEPTANCE_BROWSER=0 to walk the stand with curl instead — faster, and the
  # right choice for a scenario with nothing to look at.
  say "building and starting the stand"
  make e2e-up E2E_BIND_ADDR="${E2E_BIND_ADDR:-127.0.0.1}" \
              E2E_API_PORT="$E2E_API_PORT" E2E_DB_PORT="$E2E_DB_PORT" \
              E2E_PROFILES="$([ "${ACCEPTANCE_BROWSER:-1}" = "0" ] || echo browser)" \
    || die "the stand did not come up"

  say "waiting for the control plane (up to ${READY_TIMEOUT}s)"
  local waited=0
  until healthz; do
    waited=$((waited + 3))
    [ "$waited" -lt "$READY_TIMEOUT" ] || die "no /healthz after ${READY_TIMEOUT}s — the stand half came up, which is worse than not coming up at all"
    sleep 3
  done

  # Migrations run in the container's entrypoint before uvicorn (deploy/docker/
  # entrypoint.sh), so a green /healthz means the tables exist and the grants
  # below have something to apply to.
  say "granting the read-only role '${RO_ROLE}'"
  grant_readonly || die "could not create the read-only role — a stand whose truth source cannot connect proves nothing"

  cat <<EOF

[stand] ready.

  Owner panel        http://${E2E_API_HOST}:${E2E_API_PORT}/panel/
  Delivery endpoint  http://${E2E_API_HOST}:${E2E_API_PORT}/sub/{token}

  Sign in as         owner / e2e-operator-password

Plain HTTP on purpose: the e2e overlay sets HASHI_PUBLIC_HTTPS=false, so the
operator's session cookie is not https-only and the panel actually logs in.

The control plane is empty — no nodes, no transports, no friends, no hops.
EOF
}

grant_readonly() {
  # ON_ERROR_STOP is why this can be trusted: without it psql reports success
  # after a failed GRANT, and the first thing anyone would learn is a confusing
  # permission error from query.py three steps into a run.
  #
  # NOTE the privileges are REVOKED first and granted back narrowly. The lock on
  # this role is the absence of INSERT in the database, not a sentence in a prompt
  # asking an agent not to write — an agent that CAN fix the stand to match its
  # expectation eventually will, and will then report a pass.
  make e2e-psql <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${RO_ROLE}') THEN
    CREATE ROLE ${RO_ROLE} LOGIN PASSWORD '${RO_PASSWORD}';
  END IF;
END
\$\$;

ALTER ROLE ${RO_ROLE} WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT LOGIN
  PASSWORD '${RO_PASSWORD}';

-- Postgres 16 already withholds CREATE on public from PUBLIC. Stated anyway, so
-- the role's shape does not depend on a server default staying what it is.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM ${RO_ROLE};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ${RO_ROLE};

GRANT USAGE ON SCHEMA public TO ${RO_ROLE};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${RO_ROLE};

-- Tables a later migration creates must be readable too, or the truth source
-- goes blind on exactly the milestone that added a table.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${RO_ROLE};
SQL
}

down() {
  # E2E_PROFILES=browser is NOT optional here. `docker compose down` only touches
  # services whose profile is active, so a teardown without it leaves the browser
  # container running — and the next `up` then finds a stale one holding the old
  # image.
  say "destroying the stand and its volumes"
  make e2e-down E2E_PROFILES=browser

  # And wait for the ports to actually close. `down` returns when the containers
  # are gone, not when the kernel has released what they published, and autopilot
  # runs the whole test suite immediately after acceptance tears a stand down. The
  # control zone's tests skip when no Postgres answers and RUN when one does — so a
  # database that is still accepting connections for another second, then vanishes
  # mid-test, produces a red suite nobody can reproduce. Observed on 2026-09-08.
  local waited=0
  while nc -z "$E2E_DB_HOST" "$E2E_DB_PORT" 2>/dev/null || healthz; do
    sleep 1
    waited=$((waited + 1))
    if [ "$waited" -ge 30 ]; then
      die "the stand's ports are still open after ${waited}s — something outlived the teardown"
    fi
  done
  say "gone."
}

case "${1:-}" in
  up)   up ;;
  down) down ;;
  *)    die "usage: $(basename "$0") {up|down}" ;;
esac
