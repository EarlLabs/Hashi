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
# The properties this script holds itself to, each of which is asserted by
# tests/infra/test_panel_bootstrap_script.py or tests/e2e/infra/test_panel_bootstrap.py
# rather than promised here. The first four are the charter's; the fifth is decision 5's:
#
#   1. IDEMPOTENT. A second run changes nothing. Nothing below deletes, recreates or
#      re-initialises; `compose up -d` converges and leaves running containers alone.
#   2. NOT ONE INTERACTIVE QUESTION. Every input comes from the env file. There is no
#      `read` in this file, and there must never be: this script is run over a flaky
#      SSH session, and a prompt is a run that hangs until the session dies.
#   3. IT VERIFIES BEFORE IT REPORTS SUCCESS. The last thing it does is ask the running
#      control plane two real questions over HTTP. `echo ok` is how an operator ends up
#      believing a broken panel is up — and so is printing a panel URL that nothing on
#      this host serves, which is why the closing lines name what was proved and what was
#      not. See the end of this file.
#   4. IT NEVER GENERATES HASHI_SECRET_KEY. See the refusal below — this is the one rule
#      here that protects a person rather than an uptime figure.
#   5. IT NEVER TURNS CONNECTION LOGGING ON, and refuses to install onto a host whose
#      firewall already has. See section 1b — that is a charter rule, not a preference.
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
# HASHI_SECRET_KEY decrypts every user's credentials and every node's private key. If
# the panel is installed on the Russian entry node — which the topology allows and the
# charter anticipates — then a key generated on that host lives on the machine most
# likely to be seized, next to the data it opens. So it must arrive from outside, and
# the only safe behaviour when it is absent is to stop.
#
# Generating one here would be worse than useless: the stack would come up, the owner
# would see a working panel, and the key protecting their users' access would exist
# only on the host they are least able to trust — with nobody having decided that.
if ! has_value HASHI_SECRET_KEY; then
  fail "HASHI_SECRET_KEY is not set in ${ENV_FILE}.

  This script does NOT generate it, on purpose. That key decrypts every user's
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
#
# HASHI_PRIVATE_HOST and HASHI_PRIVATE_PORT joined this list in M7: the Caddyfile has
# two site blocks now, the private one carries the panel and the API, and compose
# interpolates both values into the caddy service. Without them the stack does not
# start at all — this check turns that into a sentence instead of a compose error.
MISSING=()
for key in HASHI_PUBLIC_HOST HASHI_PRIVATE_HOST HASHI_PRIVATE_PORT \
           HASHI_OPERATOR_USERNAME HASHI_OPERATOR_PASSWORD_HASH \
           POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
  has_value "$key" || MISSING+=("$key")
done
if [ ${#MISSING[@]} -gt 0 ]; then
  fail "these keys are missing or empty in ${ENV_FILE}: ${MISSING[*]}.
  See .env.example for what each one is. Nothing is defaulted: a default here would be
  the same value on every host that ever runs this script."
fi

# A `$` that is not doubled. This check earns its place with a bug that cost a whole
# acceptance run to find, and would have cost the owner their own panel.
#
# `docker compose --env-file` INTERPOLATES the values it reads. So a scrypt password hash
# — `scrypt$32768$8$1$<salt>$<digest>` — arrives at the container with `$<salt>` expanded
# as a variable name. Whether that destroys it depends on the salt's first byte: a salt
# starting with a letter looks like a variable and is replaced with nothing, a salt
# starting with a digit survives. So the same command works or silently locks the owner
# out of their own panel depending on random bytes, with "Those credentials were not
# accepted" as the only symptom and a correct-looking hash in the file.
#
# Escaping is `$$`. Refused rather than escaped for them: this script must not rewrite the
# file that holds their secrets, and a value it silently "fixed" would be a value they can
# no longer reason about.
# Only the VALUE half of a `KEY=VALUE` line, and never a comment. The first version of
# this check scanned whole lines and flagged the comments that explain the hazard — a
# refusal an operator cannot act on is one they learn to work around, which is worse than
# not checking. Real line numbers are kept, so the message points at the right line.
UNESCAPED="$(awk '
  /^[[:space:]]*#/ { next }
  !/=/             { next }
  {
    value = substr($0, index($0, "=") + 1)
    gsub(/\$\$/, "", value)
    if (value ~ /\$/) printf "%d ", NR
  }' "${ENV_FILE}")"
if [ -n "${UNESCAPED% }" ]; then
  fail "the env file has an unescaped \$ on line(s): ${UNESCAPED}

  docker compose interpolates the values it reads from an env file, so a lone \$ starts a
  variable reference and the rest of the value is replaced by whatever that variable
  holds — usually nothing. A scrypt password hash is the case that bites: it contains
  four of them, and whether the damage happens at all depends on the random salt, so the
  same file works on one host and silently locks you out on the next.

  Double every literal \$ in ${ENV_FILE} (\$ becomes \$\$) and run this again. Line
  numbers only are named above: this script does not print the file.

  The password hash is the one you are most likely to be looking at, and
  \`python -m control.cli hash-password\` now prints that line already doubled — paste it
  exactly as it comes out. A hash generated before that will need doubling by hand."
fi

# The private port is published TWICE on a panel host — once on the management
# tunnel's address and once on loopback, which is the way back in when the tunnel is
# down (deploy/docker-compose.public.yml). Loopback for both makes docker refuse the
# second bind with "port is already allocated", an error that names neither the cause
# nor the cure. Checked here rather than left to be discovered during a deploy.
PRIVATE_BIND="$(sed -n 's/^[[:space:]]*HASHI_PRIVATE_BIND_ADDR=[[:space:]]*//p' \
  "${ENV_FILE}" | awk 'NR==1' | tr -d '"')"
case "${PRIVATE_BIND}" in
  127.*|localhost|::1)
    fail "HASHI_PRIVATE_BIND_ADDR is ${PRIVATE_BIND}, which is loopback.

  That variable names the address the PANEL is published on, and it is meant to be this
  host's management-tunnel address — that publication is the whole of 'the panel is off
  the public internet'. Loopback is already claimed for the same port by the fallback
  mapping beside it, so docker would refuse the second bind with 'port is already
  allocated' and you would be reading that instead of this.

  If there is no management tunnel on this host yet, leave the variable unset and reach
  the panel over SSH — docs/deploy/runbook.md, 'Reaching the panel'." ;;
esac

say "env file ${ENV_FILE} has every required key and no unescaped \$"

# --- 1b. the host must not be recording who connects ---------------------------
#
# The charter forbids connection logs at any level, and `ufw enable` — which the runbook
# tells an operator to run — turns logging on by default. On the fleet's own leaf that had
# collected source addresses within minutes (docs/decisions.md, decision 5). This host is
# the one users dial for their subscriptions, so its firewall log is a list of who asked
# for a config and when.
#
# Checked, never changed. `scripts/node-bootstrap.sh` owns turning it off, because that
# script is the one that brings a firewall up; this one installs a control plane and has
# no business rewriting the firewall of a host it is standing on over SSH.
#
# The config is read rather than `ufw status` because that needs root, and this script
# does not use sudo anywhere. `awk NR==1` rather than `head -1`: under `pipefail` a closed
# pipe reads as a failed command (M11's notes).
UFW_CONF="${UFW_CONF:-/etc/ufw/ufw.conf}"
if ! command -v ufw >/dev/null 2>&1; then
  say "no ufw on this host, so nothing here switches connection logging on"
else
  if [ -r "${UFW_CONF}" ]; then
    UFW_LOGLEVEL="$(sed -n 's/^[[:space:]]*LOGLEVEL=//p' "${UFW_CONF}" | tr -d '"' | awk 'NR==1')"
  else
    # Unreadable config means unproven, and unproven is treated as on — the same
    # direction node-bootstrap's own guard fails in, and for the same reason: the cost of
    # being wrong the other way is the record the charter exists to not hold.
    UFW_LOGLEVEL="unreadable (${UFW_CONF})"
  fi
  if [ "${UFW_LOGLEVEL}" = "off" ]; then
    say "ufw is here and its connection logging is off"
    if [ -e /var/log/ufw.log ]; then
      say "note: /var/log/ufw.log exists, so this host recorded connections before logging
  was turned off. Deleting that file does not finish the job — rsyslog, kern.log and the
  journal hold the same lines (docs/decisions.md, decision 5). Logging being off is what
  stops the next line, and that is the part still worth having."
    fi
  else
    fail "ufw is installed on this host and its logging is not off: LOGLEVEL=${UFW_LOGLEVEL}.

  The firewall writes a source address for every packet it refuses. That is a connection
  log, and the charter forbids one at any level — it is the one record that can hurt a
  real person, and this host is the one users dial for their subscriptions.

  Turn it off and run this again; a second run is safe:

      sudo ufw logging off

  This script does not do it for you. It installs a control plane and does not touch the
  host's firewall — a deployment script that quietly rewrote a firewall over SSH is one
  that can lock you out of the machine you are standing on.

  If this host has been running with logging on, note that removing /var/log/ufw.log does
  not finish the job either: rsyslog, kern.log and the journal hold the same lines. Off is
  what stops the next one being written."
  fi
fi

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
#
# BUILDX_NO_DEFAULT_ATTESTATIONS is what makes that true, and without it property 1 was
# simply false. BuildKit attaches a provenance attestation to every image it exports, and
# that attestation records when the build ran — so a FULLY CACHED rebuild still produces a
# manifest with a new digest, which is the image ID compose compares against the running
# container. Every service built from a Dockerfile was therefore recreated on every run,
# with nothing in the output to explain why. The attestation itself is inert here: these
# images are built on the host that runs them and never pushed anywhere that could check
# a signature. Set on this one command rather than exported, so it describes the build and
# nothing else.
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
if ! BUILDX_NO_DEFAULT_ATTESTATIONS=1 "${COMPOSE[@]}" up -d --build; then
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

# The delivery endpoint, which is the only route a user ever touches. A 404 for a
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

# --- 3b. the management tunnel ------------------------------------------------
#
# M7. The panel is no longer on the public hostname, so something has to carry the
# owner to it — and the panel cannot hand you the config you need to reach the panel.
# That is why the generation lives in a bootstrap script rather than in a screen, and
# why it happens here rather than in scripts/node-bootstrap.sh: this is the control
# plane's own network, and a node never joins it (M11.1 fixed that script at docker,
# the key and the firewall).
#
# Skipped, not refused, when HASHI_MGMT_ADDRESS is absent. A host reached only over the
# SSH fallback is a real and documented mode, and refusing to install a control plane
# because its owner has not chosen a tunnel range yet would be this script deciding
# something that is not its to decide. It says which mode it left the host in.
if has_value HASHI_MGMT_ADDRESS; then
  say "generating the management tunnel the panel is reached over"
  "${REPO_ROOT}/scripts/management-tunnel.sh" --env-file "${ENV_FILE}"
else
  say "no HASHI_MGMT_ADDRESS in ${ENV_FILE}, so no management tunnel was generated. The
  panel is then reachable only over the SSH fallback — see docs/deploy/runbook.md,
  'Reaching the panel'. Nothing here published it either way."
fi
# There is deliberately no URL on the last line, and its absence is the point.
#
# This script used to end with "The panel is at https://<host>/panel/". On the live host
# that address answered nothing: the base compose file publishes no ports, so 80 and 443
# were closed, and the only thing that had been verified was a probe run from INSIDE the
# compose network. An address a script prints reads as an address a script checked — which
# is the same sin as `echo ok`, one level up, and property 3 of this file forbids it.
#
# Publishing here instead was the other option and is not this script's to take: what a
# host exposes to the internet is a decision about that host, the base file publishes
# nothing on purpose, and a `ports:` in it would follow every laptop's `make up-dev` home.
# So the run ends by naming exactly what it proved and exactly what is still missing.
say "done. Proven: the control plane runs, answers /healthz and routes /sub/{token} —
  all of it asked from inside the compose network."
say "NOT proven, and not yet true: nothing here is reachable from outside this host. This
  stack publishes no ports and this script adds none, so there is no panel address to
  visit until Caddy's ports are published — \`make up-panel\`, which is this same stack
  plus deploy/docker-compose.public.yml. What that costs to re-run this script afterwards
  is in docs/deploy/runbook.md under 'The port-publication gap'."
