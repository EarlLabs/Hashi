#!/usr/bin/env bash
#
# hashi — the disposable stand an acceptance agent walks.
#
# WHAT: `up` brings up a throwaway control plane, PROVES ITS HANDS by taking one
#       real action through the real driver, and prints how to reach it; `down`
#       destroys it with its volumes.
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
#
# The second thing, added after the field run of 2026-09-08: this script used to
# report `ready.` on a stand whose driver could not take a single action — the
# browser image shipped no `playwright` package, and every verb failed against a
# perfectly healthy stack. Health checks prove the SUBJECT; they say nothing about
# the INSTRUMENT the milestone is judged with. So `up` now ends by driving one
# real verb, and refuses to say ready if it fails. See `prove_the_hands`.
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
# The compose project the Makefile creates. Named here only to ask docker what is
# left after `down` — mirrors E2E_PROJECT in the Makefile and in drive.py.
E2E_PROJECT="${E2E_PROJECT:-hashi-e2e}"

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

# Whether this stand carries the acceptance browser. ACCEPTANCE_BROWSER=0 walks it
# with curl instead — faster, and the right choice for a scenario with nothing to
# look at. Asked in one place so the profile that starts the browser and the check
# that proves it cannot disagree.
hands_wanted() { [ "${ACCEPTANCE_BROWSER:-1}" != "0" ]; }

# The name the instrument check files its evidence under, in .acceptance/. Not a
# milestone: it belongs to the stand, so a milestone's own directory holds only
# what that milestone's agent did.
HANDS_CHECK="stand-check"

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
  # The image is BUILT here rather than pulled — that is what puts the `playwright`
  # package inside it — so the first stand on a machine takes a build; every one
  # after that is cached.
  say "building and starting the stand"
  make e2e-up E2E_BIND_ADDR="${E2E_BIND_ADDR:-127.0.0.1}" \
              E2E_API_PORT="$E2E_API_PORT" E2E_DB_PORT="$E2E_DB_PORT" \
              E2E_PROFILES="$(hands_wanted && echo browser || true)" \
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

  if hands_wanted; then
    say "proving the hands: one real action through the real driver"
    prove_the_hands || die "the stand is up and its driver cannot take an action — the message above is the cause; fix the browser image before walking a milestone with it"
    say "the hands work — evidence in .acceptance/${HANDS_CHECK}/${HANDS_CHECK}.png"
  fi

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

prove_the_hands() {
  # The cheapest honest check there is: `begin` a session and `open` one page,
  # through the same driver and the same container an acceptance run uses. Not a
  # `docker exec python -c "import playwright"` — that would prove the import and
  # leave the socket, the mount, the budget file and the compose invocation
  # unproved, and the reason this check exists is that everything AROUND the
  # broken part looked healthy.
  #
  # The panel's front door, which is a redirect to a login form: no token in that
  # URL, and none in the screenshot it leaves. Never a /sub/ address — those carry
  # a bearer credential in the path and this output is read by whoever runs the
  # stand.
  local status=0
  scripts/acceptance/drive.py begin "$HANDS_CHECK" --max-actions 4 --minutes 2 \
    || status=$?
  if [ "$status" -eq 0 ]; then
    # The tree goes to /dev/null: this is a liveness check, and its answer is the
    # exit code. Anything the driver says on stderr is kept — that is the cause.
    scripts/acceptance/drive.py open "http://${E2E_API_HOST}:${E2E_API_PORT}/panel/" \
      --name "$HANDS_CHECK" >/dev/null || status=$?
  fi
  # Leave no session open: the agent's own `begin` starts a fresh one with the
  # milestone's real budget, and a check that spent actions from it would be a
  # check that made the run shorter.
  scripts/acceptance/drive.py end >/dev/null 2>&1 || true
  return "$status"
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
  # No E2E_PROFILES here, deliberately. `docker compose down` only touches services
  # whose profile is active, so a teardown that names one profile tears down one
  # profile — and the day a second is added, this line silently stops covering it.
  # The Makefile widens it instead: `e2e-down` forces E2E_PROFILES to
  # E2E_ALL_PROFILES, so the list lives in one place and every profile the overlay
  # defines is torn down whatever the caller asked for. A command-line assignment
  # would OVERRIDE that target-specific one, which is the same bug wearing a fix.
  say "destroying the stand and its volumes"
  make e2e-down

  # Then prove it is gone, the same way `up` proves the previous stand is. `down`
  # used to leave the browser running: compose does not touch a service whose
  # profile is off, and nothing ever looked. Each leaked container held a gigabyte
  # of shared memory and was invisible to `up`'s /healthz check — a browser answers
  # nothing there — so they accumulated one per acceptance run. This checks the
  # PROJECT, not a service name, so it catches a profile nobody remembered.
  local left
  left="$(docker ps -a --filter "label=com.docker.compose.project=${E2E_PROJECT}" \
          --format '{{.Names}}' | tr '\n' ' ')"
  [ -z "${left// /}" ] || die "the stand is down and these containers are still up: ${left}— every profile the overlay defines has to be in E2E_ALL_PROFILES in the Makefile"

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
