#!/usr/bin/env bash
# WHAT: rebuilds the control plane on a fresh host from the operator's own machine, in one
#       command: the host's prerequisites, this checkout's code, the control plane's .env,
#       the newest backup in the bucket, the delivery endpoint published once DNS points
#       here, and the backup schedule — then says how to reach the console.
# WHY:  the 2026-10-13 rebuild of a dead entry+panel box took a dozen hand-typed steps and
#       met three traps on the way: a fresh Ubuntu's ufw logs (panel-bootstrap refuses),
#       the lost host's real management-tunnel block (the bootstrap would have printed new
#       device keys for the dead endpoint), and the backup schedule living in the crontab
#       of the machine that was gone. The owner asked for the rebuild to be "move DNS and
#       run two commands"; this is the first, `scripts/restore-node.sh` the second.
# HOW:  make restore-panel HOST=root@NEW_IP [SSH_PORT=N] [OBJECT=name]
#       (or scripts/restore-panel.sh --host root@NEW_IP …; --help lists every option).
#
#       Inputs, all on THIS machine and none of them printed: secrets/server.env (becomes
#       the host's .env), secrets/restore.env (the bucket's READ credential) and
#       secrets/hashi-backup-identity.txt (the age identity). The last two go to the host
#       for the length of the restore only, into a private directory in RAM where the host
#       has one, and are shredded when it ends — by an EXIT trap here, so a failure, a
#       Ctrl-C or a dropped connection does not leave them behind while this machine can
#       still reach the host.
#
#       SAFE TO RE-RUN. A host whose database already holds nodes is not restored again
#       (FORCE_RESTORE=1 says otherwise, and replaces it); every other step converges. So
#       the answer to any failure below is: fix what it names, run the same command.
#
#       What it does not do, and says on its last screen: move DNS, restore any node
#       (that is restore-node), or build a management tunnel (keys for that were on the
#       lost host; `make mgmt-tunnel` builds a new one when you want it).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env-value.sh
. "${REPO_ROOT}/scripts/lib/env-value.sh"
# shellcheck source=lib/remote.sh
. "${REPO_ROOT}/scripts/lib/remote.sh"

HOST=""
SSH_PORT=""
DIR="/opt/hashi-control"
SERVER_ENV="${REPO_ROOT}/secrets/server.env"
RESTORE_ENV="${REPO_ROOT}/secrets/restore.env"
IDENTITY="${REPO_ROOT}/secrets/hashi-backup-identity.txt"
OBJECT=""
# How long to wait for DNS, and for the delivery endpoint to answer with a certificate.
# Overridable for a slow resolver or a slow CA; both are waits, never skips.
DNS_WAIT="${DNS_WAIT:-600}"
DELIVERY_WAIT="${DELIVERY_WAIT:-180}"
# Upstream docker's installer — the same default, and the same reason it is a variable, as
# scripts/node-bootstrap.sh.
DOCKER_INSTALL_URL="${DOCKER_INSTALL_URL:-https://get.docker.com}"

usage() {
  cat <<'USAGE'
usage: scripts/restore-panel.sh --host USER@HOST [options]
   or: make restore-panel HOST=USER@HOST [SSH_PORT=N] [OBJECT=name]

  --host USER@HOST     the fresh host; root, or an account with passwordless sudo
  --ssh-port N         its SSH port, when not 22
  --dir PATH           where the control plane goes (default /opt/hashi-control)
  --server-env PATH    the control plane's .env you keep (default secrets/server.env)
  --restore-env PATH   the bucket's read credential (default secrets/restore.env)
  --identity PATH      the age identity (default secrets/hashi-backup-identity.txt)
  --object NAME        restore this object instead of the newest one that opens

  FORCE_RESTORE=1      restore again onto a host that already holds a fleet (replaces it)
  DNS_WAIT=SECONDS     how long to wait for HASHI_PUBLIC_HOST to point here (default 600)
  SKIP_DNS_CHECK=1     publish without checking DNS — only for a name no public CA is
                       asked about; with a real one, every failed validation counts
                       against that name's rate limit
USAGE
}

value_after() {
  [ $# -ge 2 ] || { echo "restore-panel: $1 expects a value" >&2; exit 2; }
}
while [ $# -gt 0 ]; do
  case "$1" in
    --host) value_after "$@"; HOST="$2"; shift 2 ;;
    --ssh-port) value_after "$@"; SSH_PORT="$2"; shift 2 ;;
    --dir) value_after "$@"; DIR="$2"; shift 2 ;;
    --server-env) value_after "$@"; SERVER_ENV="$2"; shift 2 ;;
    --restore-env) value_after "$@"; RESTORE_ENV="$2"; shift 2 ;;
    --identity) value_after "$@"; IDENTITY="$2"; shift 2 ;;
    --object) value_after "$@"; OBJECT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "restore-panel: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "${HOST}" ] || { usage >&2; exit 2; }

say() { printf '==> %s\n' "$*"; }
fail() { printf '\nrestore-panel: %s\n' "$*" >&2; exit 1; }

# --- 0. what this machine holds ------------------------------------------------
#
# Presence and non-emptiness only. None of these files is opened for its values except
# the two NAMES below, which are public by nature: the delivery hostname every user's
# client sends in the clear, and the console's port.
for input in "${SERVER_ENV}" "${RESTORE_ENV}" "${IDENTITY}"; do
  [ -s "${input}" ] || fail "${input} is missing or empty, and the rebuild needs it.
  secrets/README.md says what each file is and how it is made. Nothing has been changed."
done
grep -q '^AGE-SECRET-KEY-1' "${IDENTITY}" || fail "${IDENTITY} does not hold an age identity
  (a line beginning AGE-SECRET-KEY-1). Nothing has been changed."
grep -Eq '^[[:space:]]*HASHI_SECRET_KEY=[[:space:]]*[^[:space:]]' "${SERVER_ENV}" || fail \
  "${SERVER_ENV} has no HASHI_SECRET_KEY. The restored database cannot be read without the
  key it was written under. Nothing has been changed."
for key in HASHI_RESTORE_S3_ACCESS_KEY_ID HASHI_RESTORE_S3_SECRET_ACCESS_KEY; do
  grep -Eq "^[[:space:]]*${key}=[[:space:]]*[^[:space:]]" "${RESTORE_ENV}" || fail \
    "${RESTORE_ENV} has no ${key}. Nothing has been changed."
done

PUBLIC_HOST="$(env_value_of "${SERVER_ENV}" HASHI_PUBLIC_HOST)"
PRIVATE_PORT="$(env_value_of "${SERVER_ENV}" HASHI_PRIVATE_PORT)"
PRIVATE_BIND="$(env_value_of "${SERVER_ENV}" HASHI_PRIVATE_BIND_ADDR)"
BACKUP_ENABLED="$(env_value_of "${SERVER_ENV}" HASHI_BACKUP_ENABLED)"
BACKUP_RECIPIENT_SET=no
grep -Eq '^[[:space:]]*HASHI_BACKUP_AGE_RECIPIENT=[[:space:]]*[^[:space:]]' "${SERVER_ENV}" \
  && BACKUP_RECIPIENT_SET=yes
[ -n "${PUBLIC_HOST}" ] && [ -n "${PRIVATE_PORT}" ] || fail \
  "${SERVER_ENV} has no HASHI_PUBLIC_HOST or no HASHI_PRIVATE_PORT. Nothing has been changed."

# The code that goes to the host is this checkout's HEAD — committed work only.
REF="$(git -C "${REPO_ROOT}" rev-parse --short HEAD)"
if [ -n "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=no)" ]; then
  say "note: this checkout has uncommitted changes. They are NOT shipped — the host gets
  commit ${REF}, exactly as \`git archive HEAD\` makes it."
fi

# --- 1. the host ----------------------------------------------------------------
REMOTE_TMP=""
cleanup() {
  local status=$?
  if [ -n "${REMOTE_TMP}" ]; then
    # Shredded, then removed. On tmpfs shred is a formality — the pages were never on a
    # disk — and on a disk it is the best a script can do; both are said once, here.
    on_as_root host "$(q sh -c 'for f in "$1"/*; do [ -f "$f" ] && shred -u "$f" 2>/dev/null || rm -f "$f"; done; rmdir "$1"' sh "${REMOTE_TMP}")" \
      </dev/null >/dev/null 2>&1 \
      && echo "==> the identity and the bucket credential were shredded on the host" >&2 \
      || echo "restore-panel: COULD NOT CONFIRM that ${REMOTE_TMP} on the host was removed.
  It holds the age identity and the bucket's read credential. Remove it by hand:
      ssh ${HOST} 'shred -u ${REMOTE_TMP}/*; rmdir ${REMOTE_TMP}'" >&2
    REMOTE_TMP=""
  fi
  remote_close_all
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

say "reaching ${HOST}"
remote_open host "${HOST}" "${SSH_PORT}" || fail "cannot reach ${HOST} over SSH with this
  machine's keys (BatchMode — nothing here can answer a password prompt). Check the address,
  the port (--ssh-port / SSH_PORT=) and that your key is authorised there."
remote_root_access host || fail "the account on ${HOST} is not root and has no passwordless
  sudo. Installing prerequisites needs one of the two. Nothing has been changed."
ACCOUNT="$(on host 'id -un' </dev/null | tr -d '[:space:]')"

# The address users will be sent to, as THIS machine dialled it. A cloud host behind
# one-to-one NAT does not carry its public address on any interface, so asking the host
# would answer with a private one.
HOST_ADDRESS="$(host_part_of "${HOST}")"
case "${HOST_ADDRESS}" in
  *[!0-9.]*) HOST_IPS="$(resolve_ipv4 "${HOST_ADDRESS}")" ;;
  *) HOST_IPS="${HOST_ADDRESS}" ;;
esac

# --- 2. prerequisites -------------------------------------------------------------
#
# What a bare Ubuntu or Debian lacks: docker with compose, make, curl, cron. Installed
# only when missing, from the distribution and from docker's own installer — downloaded to
# a file and then run, never piped, for node-bootstrap's reason (a connection that dies
# mid-transfer would execute half an installer). On a host with no apt the missing ones
# are named and nothing is guessed.
missing="$(on host "$(q sh -c 'for c in make curl crontab; do command -v "$c" >/dev/null 2>&1 || printf "%s " "$c"; done')" </dev/null)"
if [ -n "${missing}" ]; then
  on host 'command -v apt-get >/dev/null 2>&1' </dev/null || fail "${HOST} lacks: ${missing}
  and has no apt-get to install them with. Install them and run this again."
  packages=""
  for c in ${missing}; do
    case "${c}" in crontab) packages="${packages} cron" ;; *) packages="${packages} ${c}" ;; esac
  done
  say "installing on the host:${packages}"
  # shellcheck disable=SC2086 # the package list is words on purpose
  on_as_root host "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null && apt-get install -y -qq $(q ${packages}) >/dev/null" </dev/null \
    || fail "installing${packages} on ${HOST} failed — apt-get's own words are above."
  on_as_root host 'command -v systemctl >/dev/null 2>&1 && systemctl enable --now cron >/dev/null 2>&1 || true' </dev/null
fi

if on host 'command -v docker >/dev/null 2>&1' </dev/null; then
  say "docker is already installed on the host — left as it is"
else
  say "installing a container runtime on the host from ${DOCKER_INSTALL_URL}"
  # Its own trace (it runs `set -x`) goes to a log on the host and is shown only when it
  # fails: forty lines of apt on success bury the lines this command writes.
  on_as_root host "$(q sh -c 'f=$(mktemp) && curl -fsSL "$1" -o "$f" && sh "$f" >/var/log/hashi-docker-install.log 2>&1; s=$?; rm -f "$f"; [ $s -eq 0 ] || tail -n 30 /var/log/hashi-docker-install.log; exit $s' sh "${DOCKER_INSTALL_URL}")" </dev/null \
    || fail "the docker installer failed on ${HOST}; the end of its log is above
  (/var/log/hashi-docker-install.log there)."
fi
on_as_root host 'command -v systemctl >/dev/null 2>&1 && systemctl enable --now docker >/dev/null 2>&1 || true' </dev/null
if [ "${ACCOUNT}" != "root" ] && ! on host 'id -nG | tr " " "\n" | grep -qx docker' </dev/null; then
  on_as_root host "usermod -aG docker $(q "${ACCOUNT}")" </dev/null
  say "added ${ACCOUNT} to the docker group"
  # Group membership is read at login, so the multiplexed session is started again.
  remote_close_all
  remote_open host "${HOST}" "${SSH_PORT}" || fail "lost ${HOST} after adding ${ACCOUNT} to the docker group"
  remote_root_access host || true
fi
on host 'docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1' </dev/null || fail \
  "docker on ${HOST} is installed but not usable by ${ACCOUNT}: either the compose plugin is
  missing or the daemon is not answering. Fix that and run this again; nothing of hashi has
  been installed yet."

# ufw logging OFF — the charter forbids a connection log, and panel-bootstrap refuses a host
# whose ufw logs. A fresh Ubuntu ships ufw with LOGLEVEL=low; that refusal ended the first
# run on 2026-10-13. Turning logging off locks nobody out, which is why this command does it
# and panel-bootstrap (which never touches a firewall) only checks it.
if on host 'command -v ufw >/dev/null 2>&1' </dev/null; then
  level="$(on_as_root host "sed -n 's/^[[:space:]]*LOGLEVEL=//p' /etc/ufw/ufw.conf | tr -d '\"' | awk 'NR==1'" </dev/null || true)"
  if [ "${level}" = "off" ]; then
    say "ufw is on the host and its logging is already off"
  else
    on_as_root host 'ufw logging off >/dev/null' </dev/null \
      || fail "could not turn ufw logging off on ${HOST}. Run 'sudo ufw logging off' there."
    say "ufw logging was ${level:-unknown}; it is now off (a connection log is what the charter forbids)"
  fi
fi

# --- 3. code and .env ---------------------------------------------------------------
say "shipping commit ${REF} to ${HOST}:${DIR}"
on_as_root host "install -d -o $(q "${ACCOUNT}") $(q "${DIR}")" </dev/null
git -C "${REPO_ROOT}" archive HEAD | on host "tar -x -C $(q "${DIR}")" \
  || fail "unpacking the code on ${HOST} failed."

# Compared by digest, never by content, and the digest is not printed: this file holds
# every secret the control plane has.
local_sum="$(sha256sum "${SERVER_ENV}" | awk '{print $1}')"
remote_sum="$(on host "test -f $(q "${DIR}/.env") && sha256sum $(q "${DIR}/.env") | awk '{print \$1}'" </dev/null || true)"
if [ "${local_sum}" = "${remote_sum}" ]; then
  say "${DIR}/.env is already your ${SERVER_ENV##*/}"
else
  on host "umask 077 && cat > $(q "${DIR}/.env.new") && mv $(q "${DIR}/.env.new") $(q "${DIR}/.env") && chmod 600 $(q "${DIR}/.env")" \
    < "${SERVER_ENV}" || fail "could not write ${DIR}/.env on ${HOST}."
  say "placed ${SERVER_ENV##*/} as ${DIR}/.env (mode 600)"
fi

# --- 4. the restore ---------------------------------------------------------------
#
# Skipped when the database already holds nodes — a re-run after a later step failed. The
# count is asked of the running database; a stack that is not up answers nothing, and
# nothing means "restore", which is right on a host that has never run one.
nodes_held="$(on host "cd $(q "${DIR}") && docker compose --env-file .env -f deploy/docker-compose.yml exec -T db sh -c 'psql -tAq -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"select count(*) from nodes\"' 2>/dev/null" </dev/null | tr -d '[:space:]' || true)"
case "${nodes_held}" in ''|*[!0-9]*) nodes_held=0 ;; esac

if [ "${nodes_held}" != "0" ] && [ "${FORCE_RESTORE:-0}" != "1" ]; then
  say "the control plane on ${HOST} already holds ${nodes_held} node(s), so the bucket is NOT
  restored again — this is a re-run. FORCE_RESTORE=1 restores over it (and replaces it)."
else
  # RAM where the host has it: the identity is then never written to a disk at all.
  REMOTE_TMP="$(on host 'd=$(mktemp -d -p /dev/shm hashi-restore.XXXXXX 2>/dev/null || mktemp -d /tmp/hashi-restore.XXXXXX) && chmod 700 "$d" && printf %s "$d"' </dev/null)"
  [ -n "${REMOTE_TMP}" ] || fail "could not make a private directory on ${HOST}."
  on host "umask 077 && cat > $(q "${REMOTE_TMP}/identity")" < "${IDENTITY}"
  on host "umask 077 && cat > $(q "${REMOTE_TMP}/restore.env")" < "${RESTORE_ENV}"
  say "the identity and the bucket credential are on the host, in ${REMOTE_TMP}, for the
  length of the restore"

  # FORCE=1 only when the operator said FORCE_RESTORE=1. A database holding rows but no
  # nodes is refused by the restore itself, with its own sentence, and the answer to that
  # is FORCE_RESTORE=1 on this command.
  force=""
  [ "${FORCE_RESTORE:-0}" = "1" ] && force="FORCE=1"
  # restore.env is sourced the way its own header documents. HASHI_RESTORE_AGE_IDENTITY is
  # set AFTER it, because the file names a path on this machine and the copy is elsewhere.
  on host "cd $(q "${DIR}") && set -a && . $(q "${REMOTE_TMP}/restore.env") && set +a && \
HASHI_RESTORE_AGE_IDENTITY=$(q "${REMOTE_TMP}/identity") ${force} make restore-from-bucket $(if [ -n "${OBJECT}" ]; then q "OBJECT=${OBJECT}"; fi)" \
    </dev/null || fail "the restore did not finish; what it said is above. The identity is
  shredded on the way out. Fix what it names and run this same command again."

  # Removed now rather than at exit: the rest of this run has no use for either file, and
  # a publish that hangs should not keep them on the host for its duration.
  staged="${REMOTE_TMP}"
  REMOTE_TMP=""
  if on_as_root host "$(q sh -c 'for f in "$1"/*; do shred -u "$f" 2>/dev/null || rm -f "$f"; done; rmdir "$1"' sh "${staged}")" </dev/null; then
    say "the identity and the bucket credential were shredded on the host"
  else
    say "COULD NOT CONFIRM the identity was removed from the host. Remove it by hand:
      ssh ${HOST} 'shred -u ${staged}/*; rmdir ${staged}'"
  fi
  echo
  say "restore-panel carries on with the steps that screen leaves to you: DNS is checked,
  then the delivery endpoint is published and the backup schedule restored."
fi

# --- 5. DNS, then publish -------------------------------------------------------------
#
# A public CA is asked for a certificate the moment 80/443 are published, and it validates
# against wherever the name points NOW. Publishing early burns the live name's rate limit
# on the old host's address, so this waits — and refuses with a sentence rather than
# publishing on a guess.
if [ "${SKIP_DNS_CHECK:-0}" = "1" ]; then
  say "SKIP_DNS_CHECK=1: not checking where ${PUBLIC_HOST} points"
else
  [ -n "${HOST_IPS}" ] || fail "could not work out the address of ${HOST}, so cannot check
  that ${PUBLIC_HOST} points at it. Pass HOST as user@IP."
  waited=0
  while :; do
    resolved="$(resolve_ipv4 "${PUBLIC_HOST}" | tr '\n' ' ')"
    if [ -n "${resolved}" ] && [ "${resolved% }" = "$(printf '%s\n' ${HOST_IPS} | sort -u | tr '\n' ' ' | sed 's/ $//')" ]; then
      say "${PUBLIC_HOST} resolves to ${resolved% } — this host"
      break
    fi
    if [ "${waited}" -ge "${DNS_WAIT}" ]; then
      fail "${PUBLIC_HOST} resolves to '${resolved% }' from this machine, not to ${HOST_IPS}.
  The control plane IS restored. This run published nothing and asked no CA for anything
  (a publication an earlier run made is left exactly as it was). Point the record at this
  host and run this same command again — it will not restore a second time. (Resolvers cache: a record changed a minute ago can take its TTL
  to show here. DNS_WAIT=<seconds> waits longer.)"
    fi
    [ "${waited}" -eq 0 ] && say "waiting up to ${DNS_WAIT}s for ${PUBLIC_HOST} to resolve to ${HOST_IPS} (now: '${resolved% }')"
    sleep 15
    waited=$((waited + 15))
  done
fi

# up-panel only when the tunnel address the env names is really on this host — which on a
# rebuild it is not, because the tunnel was on the machine that was lost.
publish="up-panel-over-ssh"
if [ -n "${PRIVATE_BIND}" ] && on host "ip -o addr show 2>/dev/null | grep -qw $(q "${PRIVATE_BIND}")" </dev/null; then
  publish="up-panel"
fi
say "publishing: make ${publish}"
on host "cd $(q "${DIR}") && make ${publish}" </dev/null || fail "make ${publish} failed on
  ${HOST}; its output is above. The data is restored. Run this same command again."

# --- 6. backups -----------------------------------------------------------------------
BACKUP_NOTE=""
if [ "${BACKUP_RECIPIENT_SET}" = "yes" ]; then
  if [ "${BACKUP_ENABLED}" = "1" ]; then
    say "taking a backup now, so the bucket's newest object is this host's"
    if on host "cd $(q "${DIR}") && make backup" </dev/null; then
      BACKUP_NOTE="a backup was taken and sent to the bucket;"
    else
      BACKUP_NOTE="the backup taken now did NOT complete (its words are above; exit 3 means
  written here and not sent);"
    fi
  fi
  on host "cd $(q "${DIR}") && make backup-schedule" </dev/null \
    && BACKUP_NOTE="${BACKUP_NOTE:+${BACKUP_NOTE} }the schedule is installed in ${ACCOUNT}'s crontab (make backup-status)." \
    || BACKUP_NOTE="${BACKUP_NOTE:+${BACKUP_NOTE} }the schedule could NOT be installed — run make backup-schedule there."
else
  BACKUP_NOTE="NOTHING is backed up: ${SERVER_ENV##*/} has no HASHI_BACKUP_AGE_RECIPIENT.
  Fill the HASHI_BACKUP_* block in it and run this command again."
fi

# --- 7. what answers ---------------------------------------------------------------------
#
# Asked ON the host, with the name pinned to the host's own loopback: that is Caddy and the
# certificate it holds, checked against the host's CA store, without depending on which
# resolver this machine uses. A 404 for a token that cannot exist is the right answer — the
# route is wired and the certificate verified. Never a real token.
say "waiting up to ${DELIVERY_WAIT}s for https://${PUBLIC_HOST}/sub/ to answer with a valid certificate"
DELIVERY="not verified"
waited=0
while [ "${waited}" -lt "${DELIVERY_WAIT}" ]; do
  code="$(on host "curl -s -o /dev/null -w '%{http_code}' --max-time 10 --resolve $(q "${PUBLIC_HOST}:443:127.0.0.1") $(q "https://${PUBLIC_HOST}/sub/restore-panel-probe-not-a-token")" </dev/null 2>/dev/null || true)"
  if [ "${code}" = "404" ]; then DELIVERY="verified"; break; fi
  sleep 10
  waited=$((waited + 10))
done
CONSOLE="$(on host "curl -sk -o /dev/null -w '%{http_code}' --max-time 10 $(q "https://127.0.0.1:${PRIVATE_PORT}/panel/login")" </dev/null 2>/dev/null || true)"

port_flag=""
[ -n "${SSH_PORT}" ] && port_flag="-p ${SSH_PORT} "
cat <<MSG

──────────────────────────────────────────────────────────────────────────────
The control plane is restored on ${HOST} (commit ${REF}).

  delivery   https://${PUBLIC_HOST}/sub/… — ${DELIVERY}$( [ "${DELIVERY}" = verified ] && echo " (a valid certificate, the route answers)" || echo ".
             Caddy may still be waiting for the CA. Check again in a minute with:
               ssh ${port_flag}${HOST} 'cd ${DIR} && make logs'" )
  console    on the host's loopback only (answered ${CONSOLE:-nothing}). From this machine:
               ssh ${port_flag}-L ${PRIVATE_PORT}:127.0.0.1:${PRIVATE_PORT} ${HOST}
             then open  https://127.0.0.1:${PRIVATE_PORT}/panel/
             (Caddy's own CA is new, so the browser asks you to trust it once more.)
  backups    ${BACKUP_NOTE}

Not done here, on purpose:
  - nodes. The node that lived on the lost box still points at it. Rebuild it with
      make restore-node NODE=<its name> HOST=<user@new host>
    (add PANEL=${HOST} when the node goes on a different box than this one).
  - the management tunnel. Its keys were on the lost host. When you want one here:
      ssh ${port_flag}${HOST} 'cd ${DIR} && HASHI_MGMT_CONFIGS_TO=~/mgmt-devices make mgmt-tunnel'
    then make up-panel there.
──────────────────────────────────────────────────────────────────────────────
MSG
[ "${DELIVERY}" = "verified" ] || exit 3
