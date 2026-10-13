#!/usr/bin/env bash
# WHAT: rebuilds one node onto a fresh host from the operator's own machine, in one
#       command: reads the node's record from the control plane, prepares the host for
#       it (the account the control plane will log in as, the record's public key, a
#       firewall that opens the ports the record says the node listens on), moves the
#       record to the new host through the audited relocation, and applies.
# WHY:  the second of the two commands the owner asked for on 2026-10-13 — "move DNS, run
#       two commands" — after `scripts/restore-panel.sh`. That day the node's record could
#       not be moved at all: its SSH host, account and pinned host key were fixed at
#       registration, so the rebuild re-created an account named after the dead box and
#       finished with a raw UPDATE that the audit trail never saw. The node account is now
#       a parameter (ACCOUNT=, default `hashi`), created when missing, and the move is
#       `control.cli relocate-node`.
# HOW:  make restore-node NODE=<name> HOST=root@NEW_IP [ACCOUNT=hashi] [PANEL=user@panel]
#       (or scripts/restore-node.sh --node NAME --host USER@HOST …; --help for options).
#
#       PANEL is where the control plane runs, and defaults to HOST — the arrangement where
#       the entry box carries the control plane too. The control plane is only ever asked
#       through `make node-plan`, `make node-relocate` and `make node-apply` in its own
#       directory, so this works the same whether the two are one box or two.
#
#       The node's ports come from its RECORD (`node-plan`), and when the host is also the
#       control plane's, the ports its Caddy publishes are added — read off the running
#       container, not written here. Docker-published ports do not pass through ufw's
#       INPUT chain, so they answer either way; they are opened anyway so that the answer
#       does not depend on docker's own iptables rules staying where they are.
#
#       The new host's key is read over YOUR session to it and pinned on the record, rather
#       than learned by the control plane on first contact: that way the one unverified
#       first contact with this host is yours, made once, and the control plane never
#       trusts an answer it got on its own.
#
#       SAFE TO RE-RUN: the account and the bootstrap converge, a relocation onto the same
#       coordinates records nothing, and an apply is an apply.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/remote.sh
. "${REPO_ROOT}/scripts/lib/remote.sh"

NODE_NAME=""
HOST=""
SSH_PORT=""
ACCOUNT="hashi"
PANEL=""
PANEL_SSH_PORT=""
DIR="/opt/hashi-control"
NODE_SSH_HOST=""
NODE_SSH_PORT=""
ADDRESS=""
KEY_FILE=""

usage() {
  cat <<'USAGE'
usage: scripts/restore-node.sh --node NAME --host USER@HOST [options]
   or: make restore-node NODE=NAME HOST=USER@HOST [ACCOUNT=hashi] [PANEL=USER@HOST]

  --node NAME            the node, by the name the panel shows
  --host USER@HOST       the fresh host; root, or an account with passwordless sudo
  --ssh-port N           its SSH port, when not 22
  --account NAME         the account the control plane will log in as (default hashi);
                         created when missing
  --panel USER@HOST      where the control plane runs (default: --host)
  --panel-ssh-port N     its SSH port (default: --ssh-port when the panel is the host)
  --dir PATH             the control plane's directory there (default /opt/hashi-control)
  --node-ssh-host H      the address the CONTROL PLANE dials (default: --host's address)
  --node-ssh-port N      the port it dials (default: --ssh-port, else 22)
  --address A            change the address users are sent to (default: keep the record's
                         — the usual case, when users dial a name you moved in DNS)
  --key FILE.pub         authorise this public key instead of the record's own
USAGE
}

value_after() {
  [ $# -ge 2 ] || { echo "restore-node: $1 expects a value" >&2; exit 2; }
}
while [ $# -gt 0 ]; do
  case "$1" in
    --node) value_after "$@"; NODE_NAME="$2"; shift 2 ;;
    --host) value_after "$@"; HOST="$2"; shift 2 ;;
    --ssh-port) value_after "$@"; SSH_PORT="$2"; shift 2 ;;
    --account) value_after "$@"; ACCOUNT="$2"; shift 2 ;;
    --panel) value_after "$@"; PANEL="$2"; shift 2 ;;
    --panel-ssh-port) value_after "$@"; PANEL_SSH_PORT="$2"; shift 2 ;;
    --dir) value_after "$@"; DIR="$2"; shift 2 ;;
    --node-ssh-host) value_after "$@"; NODE_SSH_HOST="$2"; shift 2 ;;
    --node-ssh-port) value_after "$@"; NODE_SSH_PORT="$2"; shift 2 ;;
    --address) value_after "$@"; ADDRESS="$2"; shift 2 ;;
    --key) value_after "$@"; KEY_FILE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "restore-node: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "${NODE_NAME}" ] && [ -n "${HOST}" ] || { usage >&2; exit 2; }

say() { printf '==> %s\n' "$*"; }
fail() { printf '\nrestore-node: %s\n' "$*" >&2; exit 1; }

# An account name the way useradd takes one, refused here before any host is touched.
case "${ACCOUNT}" in
  ""|-*|*[!a-z0-9_-]*) fail "'${ACCOUNT}' is not an account name this command will create
  (lower-case letters, digits, '-' and '_'). Nothing has been changed." ;;
esac
[ "${#ACCOUNT}" -le 32 ] || fail "'${ACCOUNT}' is longer than 32 characters. Nothing has been changed."

if [ -z "${PANEL}" ]; then
  PANEL="${HOST}"
  PANEL_SSH_PORT="${PANEL_SSH_PORT:-${SSH_PORT}}"
fi
NODE_SSH_HOST="${NODE_SSH_HOST:-$(host_part_of "${HOST}")}"
NODE_SSH_PORT="${NODE_SSH_PORT:-${SSH_PORT:-22}}"

trap remote_close_all EXIT
trap 'exit 130' INT TERM

# --- 1. what the control plane says this node is -------------------------------------
say "asking the control plane on ${PANEL} about node ${NODE_NAME}"
remote_open panel "${PANEL}" "${PANEL_SSH_PORT}" || fail "cannot reach ${PANEL} over SSH with
  this machine's keys. That is where the control plane is asked; pass PANEL= if it is not on
  ${HOST}."
on panel "test -f $(q "${DIR}/Makefile") && test -f $(q "${DIR}/.env")" </dev/null || fail \
  "there is no control plane in ${DIR} on ${PANEL}. Restore it first (make restore-panel), or
  pass DIR= / PANEL= if it lives elsewhere. Nothing has been changed."

# key=value lines, read without eval: a value is data, whatever it holds.
declare -A PLAN=()
plan_text="$(on panel "cd $(q "${DIR}") && make -s node-plan $(q "NAME=${NODE_NAME}")" </dev/null)" \
  || fail "the control plane would not describe node ${NODE_NAME} — its sentence is above.
  Nothing has been changed."
while IFS= read -r line; do
  case "${line}" in *=*) PLAN["${line%%=*}"]="${line#*=}" ;; esac
done <<< "${plan_text}"
[ "${PLAN[name]:-}" = "${NODE_NAME}" ] || fail "the control plane answered something that is not
  a plan for ${NODE_NAME}. Nothing has been changed."

if [ -n "${KEY_FILE}" ]; then
  [ -s "${KEY_FILE}" ] || fail "${KEY_FILE} is missing or empty."
  PUBLIC_KEY="$(cat "${KEY_FILE}")"
else
  PUBLIC_KEY="${PLAN[public_key]:-}"
fi
[ -n "${PUBLIC_KEY}" ] || fail "node ${NODE_NAME}'s record holds no SSH key, so there is nothing
  to authorise on the new host and nothing the control plane could log in with. Give it one
  (Nodes → ssh key), then run this again. Nothing has been changed."

say "${NODE_NAME}: state ${PLAN[state]:-?}, address ${PLAN[address]:-?}, now dialled as ${PLAN[ssh_user]:-?}@${PLAN[ssh_host]:-?}:${PLAN[ssh_port]:-?}"
say "the record says the node listens on: ${PLAN[ports]:-nothing yet}"

# --- 2. the host ----------------------------------------------------------------------
say "reaching ${HOST}"
remote_open host "${HOST}" "${SSH_PORT}" || fail "cannot reach ${HOST} over SSH with this
  machine's keys (BatchMode). Check the address, SSH_PORT= and that your key is there."
remote_root_access host || fail "the account on ${HOST} is not root and has no passwordless
  sudo; preparing a node needs one of the two. Nothing has been changed."

# The ports a control plane on THIS box publishes, off the running container — when there
# is one. Only addresses other than loopback: the console's loopback mapping is reached
# over ssh -L, never through the firewall.
EXTRA_PORTS="$(on_as_root host "docker ps --filter label=com.docker.compose.service=caddy --format '{{.Ports}}' 2>/dev/null" </dev/null \
  | tr ',' '\n' \
  | awk -F'->' 'NF == 2 {
      n = split($1, left, ":"); host_port = left[n]
      addr = substr($1, 1, length($1) - length(host_port) - 1); gsub(/^[ \t]+/, "", addr)
      split($2, right, "/")
      if (addr ~ /^127\./ || addr == "[::1]" || host_port !~ /^[0-9]+$/) next
      print host_port "/" right[2]
    }' | sort -u | tr '\n' ' ' || true)"
[ -n "${EXTRA_PORTS// /}" ] && say "this host also runs the control plane's Caddy, publishing ${EXTRA_PORTS% }"

# --- 3. the account -----------------------------------------------------------------
#
# Created here, not by node-bootstrap: that script prepares an account and deliberately
# never makes one (a host's accounts belong to whoever owns the host). This command is that
# owner saying which one, so it makes it — with a home, because the key goes there, and a
# login shell, because the control plane runs commands over it. No password is set, so it
# logs in by key or not at all.
if on host "id $(q "${ACCOUNT}") >/dev/null 2>&1" </dev/null; then
  say "the account ${ACCOUNT} already exists on the host"
else
  on_as_root host "useradd -m -s /bin/bash $(q "${ACCOUNT}")" </dev/null \
    || fail "could not create the account ${ACCOUNT} on ${HOST}."
  say "created the account ${ACCOUNT} on the host (no password; key login only)"
fi

# --- 4. node-bootstrap, piped, exactly as `make node-bootstrap` runs it ---------------
args=(--user "${ACCOUNT}" --authorized-key "${PUBLIC_KEY}")
# shellcheck disable=SC2206 # the port lists are space-separated words on purpose
for spec in ${PLAN[ports]:-} ${EXTRA_PORTS}; do args+=(--port "${spec}"); done
[ "${NODE_SSH_PORT}" != "22" ] && args+=(--ssh-port "${NODE_SSH_PORT}")
say "preparing the host for ${ACCOUNT}, opening: ${PLAN[ports]:-} ${EXTRA_PORTS}"
on host "bash -s -- $(q "${args[@]}")" < "${REPO_ROOT}/scripts/node-bootstrap.sh" \
  || fail "node-bootstrap refused or failed on ${HOST}; its sentence is above. The record has
  NOT been moved, so the control plane still dials the old host. Fix what it names and run
  this again."

# --- 5. the record moves, audited -----------------------------------------------------
# ed25519 when the host has it — the key every current OpenSSH generates — read over this
# operator's own session. Without one the pin is cleared and the first apply learns it.
HOST_KEY="$(on host 'cat /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null' </dev/null | awk 'NR==1 {print $1, $2}' || true)"
relocate_args=(--ssh-host "${NODE_SSH_HOST}" --ssh-user "${ACCOUNT}" --ssh-port "${NODE_SSH_PORT}")
[ -n "${HOST_KEY}" ] && relocate_args+=(--host-key "${HOST_KEY}")
[ -n "${ADDRESS}" ] && relocate_args+=(--address "${ADDRESS}")
moved="$(on panel "cd $(q "${DIR}") && make -s node-relocate $(q "NAME=${NODE_NAME}") $(q "ARGS=$(q "${relocate_args[@]}")")" </dev/null)" \
  || fail "the control plane refused to move ${NODE_NAME}'s record — its sentence is above.
  The host is prepared; run this again once that is fixed."
changed="$(printf '%s\n' "${moved}" | sed -n 's/^changed=//p')"
needs_apply="$(printf '%s\n' "${moved}" | sed -n 's/^needs_apply=//p')"
if [ "${changed}" = "yes" ]; then
  say "the record now dials ${ACCOUNT}@${NODE_SSH_HOST}:${NODE_SSH_PORT}${HOST_KEY:+, host key pinned (${HOST_KEY%% *})} — recorded in the audit trail"
else
  say "the record already pointed at this host — nothing to move"
fi

# --- 6. apply ---------------------------------------------------------------------------
STATUS=0
APPLIED=()
FAILED=()
for name in ${needs_apply:-${NODE_NAME}}; do
  say "applying ${name}"
  if result="$(on panel "cd $(q "${DIR}") && make -s node-apply $(q "NAME=${name}")" </dev/null)"; then
    state="$(printf '%s\n' "${result}" | sed -n 's/^state=//p')"
    applied="$(printf '%s\n' "${result}" | sed -n 's/^applied=//p')"
    say "${name}: ${state:-?}, serving ${applied:-nothing}"
    APPLIED+=("${name} (${state:-?})")
  else
    FAILED+=("${name}")
    STATUS=1
  fi
done

cat <<MSG

──────────────────────────────────────────────────────────────────────────────
Node ${NODE_NAME} is on ${HOST}, driven as ${ACCOUNT}.
  applied:  ${APPLIED[*]:-none}
  failed:   ${FAILED[*]:-none}$( [ ${#FAILED[@]} -gt 0 ] && printf '\n            the sentence for each is above; fix it and run this same command again' )

Proven: the control plane reached the new host with the record's key, pushed the
configuration and found it serving — measured on the host. NOT proven: that anyone
can connect from outside (a provider's security group sits in front of this host and
nothing here sees it), and nothing at all about a Russian network: that is a field
observation with a real device.
──────────────────────────────────────────────────────────────────────────────
MSG
exit "${STATUS}"
