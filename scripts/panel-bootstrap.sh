#!/usr/bin/env bash
# WHAT: brings up the control plane on a bare host — database, control container,
#       delivery endpoint and TLS front — from one env file and nothing else.
# WHY:  the charter says "everything is deployed by one script", and there are exactly
#       two of them. The node bootstrap has existed since M1 (edge/bootstrap/). This is
#       the other one, and it was missing entirely: scripts/ held ask_owner.sh,
#       backup.sh, fetch-upstream-checkers.sh and notify.sh. Backlog item 31.
#
#       A documented sequence of docker compose incantations is not the same thing. The
#       host this runs on is one the owner may have to replace in an afternoon, from a
#       phone tether, under time pressure — which is when a sequence of steps gets one
#       step skipped.
# HOW:  ./scripts/panel-bootstrap.sh [--env-file PATH]
#       or: make panel-bootstrap [ENV_FILE=path]
#
#       Set COMPOSE_PROJECT_NAME to install a second, separate stack on the same host
#       (the acceptance scenarios do exactly that, which is why nothing below hardcodes
#       a project name).
#
# The four properties the charter asks of this script, each of which is asserted by
# tests/e2e/infra/test_panel_bootstrap.py rather than promised here:
#
#   1. IDEMPOTENT. A second run changes nothing. Nothing below deletes, recreates or
#      re-initialises; `compose up -d` converges and leaves running containers alone.
#   2. NOT ONE INTERACTIVE QUESTION. Every input comes from the env file. There is no
#      `read` in this file, and there must never be: this script is run over a flaky
#      SSH session, and a prompt is a run that hangs until the session dies.
#   3. IT VERIFIES BEFORE IT REPORTS SUCCESS. The last thing it does is ask the running
#      control plane two real questions over HTTP. `echo ok` is how an operator ends up
#      believing a broken panel is up.
#   4. IT NEVER GENERATES HASHI_SECRET_KEY. See the refusal below — this is the one rule
#      here that protects a person rather than an uptime figure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --env-file=*) ENV_FILE="${1#*=}"; shift ;;
    -h|--help)
      echo "usage: $0 [--env-file PATH]"
      exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      echo "usage: $0 [--env-file PATH]" >&2
      exit 2 ;;
  esac
done

# How long to wait for the control plane to answer. Configurable because the first run
# on a small host builds an image and initialises a database, and because the acceptance
# scenario needs a shorter wait to prove the failure path in reasonable time.
HEALTH_TIMEOUT="${PANEL_HEALTH_TIMEOUT:-180}"

COMPOSE=(docker compose --env-file "${ENV_FILE}" -f "${REPO_ROOT}/deploy/docker-compose.yml")

say() { printf '==> %s\n' "$1"; }
fail() { printf 'panel-bootstrap: %s\n' "$1" >&2; exit 1; }

# --- 1. the env file -----------------------------------------------------------
#
# Read for the PRESENCE of keys, never printed. This file holds the owner's real
# secrets, and a script that echoes it — even on failure, even to help — puts them into
# a terminal scrollback and an SSH log.

[ -f "${ENV_FILE}" ] || fail \
  "no env file at ${ENV_FILE}. Copy .env.example to .env and fill it in, or pass
  --env-file. Nothing is generated for you: see the refusal below."

# grep for `KEY=value` with a non-empty value. Deliberately not `source`: sourcing an
# env file runs it, so a stray backtick in a password becomes a command on this host.
has_value() {
  grep -Eq "^[[:space:]]*$1=[[:space:]]*[^[:space:]]" "${ENV_FILE}"
}

# THE refusal. Everything else in this script is about uptime; this is about a person.
#
# HASHI_SECRET_KEY decrypts every friend's credentials and every node's private key. If
# the panel is installed on the Russian entry node — which the topology allows and the
# charter anticipates — then a key generated on that host lives on the machine most
# likely to be seized, next to the data it opens. So it must arrive from outside, and
# the only safe behaviour when it is absent is to stop.
#
# Generating one here would be worse than useless: the stack would come up, the owner
# would see a working panel, and the key protecting their friends' access would exist
# only on the host they are least able to trust — with nobody having decided that.
if ! has_value HASHI_SECRET_KEY; then
  fail "HASHI_SECRET_KEY is not set in ${ENV_FILE}.

  This script does NOT generate it, on purpose. That key decrypts every friend's
  credentials and every node's private key. If this host is the Russian entry node, a
  key generated here would sit on the machine most likely to be seized, beside the data
  it opens — and nobody would have decided that.

  Generate it somewhere you trust, keep a copy somewhere else (a dump without the key
  is not a backup), and put it in ${ENV_FILE}:

      python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
  "
fi

# The remaining required keys. Absence is refused for the same reason as above in
# miniature: every one of them has a plausible-looking default, and a default here is a
# fleet-wide constant. Their VALIDITY is not checked here — control/app/settings.py is
# the single source of truth for that, and a second copy of its rules in bash is a copy
# that will disagree with it.
MISSING=()
for key in HASHI_PUBLIC_HOST HASHI_OPERATOR_USERNAME HASHI_OPERATOR_PASSWORD_HASH \
           POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
  has_value "$key" || MISSING+=("$key")
done
if [ ${#MISSING[@]} -gt 0 ]; then
  fail "these keys are missing or empty in ${ENV_FILE}: ${MISSING[*]}.
  See .env.example for what each one is. Nothing is defaulted: a default here would be
  the same value on every host that ever runs this script."
fi

say "env file ${ENV_FILE} has every required key"

# --- 2. bring the stack up ----------------------------------------------------
#
# The BASE compose file only, never the dev overlay: the overlay is the only file that
# publishes ports, and a panel host must not publish its database to the internet
# because someone copied a command from a laptop.
#
# `up -d --build` converges. It is the whole of property 1: run twice and the second run
# recreates nothing, because compose compares the desired state with the running one.
# Note what is NOT here — no `down`, no `rm`, no `volume rm`, no `alembic` — because each
# would make a second run destructive. Migrations run inside the container's own
# entrypoint, which is also what makes them idempotent.
say "building and starting the stack (this is the slow part on a fresh host)"
# A failure here does NOT end the run, and that is deliberate rather than lax.
# `compose up -d` fails when a service it was told to wait for never becomes healthy —
# which is precisely the case this script exists to report WELL. Letting `set -e` abort
# here would end the run on compose's own message ("dependency failed to start"), with no
# word about where the logs are or that the stack was left up for inspection.
#
# So the verification step below is the single place that decides whether this run
# succeeded. That is also the charter's requirement stated exactly: success is what the
# running control plane answers, not what an orchestrator's exit code says.
if ! "${COMPOSE[@]}" up -d --build; then
  say "compose reported a problem — continuing to the verification step, which is what
  decides whether this run succeeded"
fi

# --- 3. verify, and only then report success ----------------------------------
#
# Two questions, asked from INSIDE the network, because the production stack publishes
# nothing — there is no host port to curl, and adding one to check would defeat the
# reason the base file has none.
probe() {
  "${COMPOSE[@]}" exec -T control python -c "
import sys
import urllib.error
import urllib.request

def get(path):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:8000{path}', timeout=5) as answer:
            return answer.status, answer.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, ''
    except Exception:
        return 0, ''

status, body = get('/healthz')
if status != 200 or 'ok' not in body:
    sys.exit(1)

# The delivery endpoint, which is the only route a friend ever touches. A 404 for a
# token that cannot exist is the correct answer and proves the route is wired — a live
# process with an unrouted /sub is a panel that looks up and delivers nothing.
# Deliberately not a real token: this probe must never carry a credential.
status, _ = get('/sub/panel-bootstrap-probe-not-a-real-token')
if status != 404:
    sys.exit(1)
" >/dev/null 2>&1
}

say "waiting up to ${HEALTH_TIMEOUT}s for the control plane to answer"
waited=0
until probe; do
  waited=$((waited + 3))
  if [ "${waited}" -ge "${HEALTH_TIMEOUT}" ]; then
    printf '\n'
    # Container state, never the env file and never a log body: a log line here could
    # carry a request path, and a request path can carry a subscription token.
    "${COMPOSE[@]}" ps || true
    fail "the control plane did not answer within ${HEALTH_TIMEOUT}s.

  The stack is left RUNNING so it can be inspected — this script does not tear down
  what it did not manage to verify. Look at:

      docker compose --env-file ${ENV_FILE} -f deploy/docker-compose.yml logs control

  and re-run this script once the cause is fixed; a second run is safe."
  fi
  sleep 3
done

say "the control plane answers on /healthz and routes /sub/{token}"
say "done. The panel is at https://\$HASHI_PUBLIC_HOST/panel/ — the value in ${ENV_FILE}."
