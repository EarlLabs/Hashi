#!/usr/bin/env bash
# WHAT: dump and restore the control database — backlog item 22.
# WHY:  the control database is the single source of truth (core invariants §3): a node
#       holds nothing that cannot be regenerated from it. That cuts both ways. Losing a
#       node is nothing; losing this database is losing every user's access and every
#       node's credentials at once, with no way to rebuild them.
#
#       WHAT THE FILE ACTUALLY IS, because this header used to get it wrong: plain
#       SQL, gzipped, NOT encrypted. What is encrypted inside it is a subset of
#       COLUMNS — node `ssh_private_key`, node_transport `secrets`, user `token`,
#       `subject`, `secrets`, `tunnel_address` (§3, encryption at rest) — so those
#       cannot be restored without HASHI_SECRET_KEY. Everything else is in the clear,
#       including every node's real address and the leaf addresses no user is ever
#       shown. Both halves are true at once: the file is a map of the fleet to anyone
#       who opens it, AND it rebuilds nothing without the key. Each half is printed on
#       every run, because the previous wording said only the second and an operator
#       who believed it would have put the fleet's addresses somewhere public.
#
#       What else belongs in a backup — `caddy_data`, `~/.hashi/management/`, `.env`,
#       and why `/opt/hashi` on a node is not backup material — is decided and written
#       down in docs/deploy/runbook.md, "Backups". This script writes the database and
#       nothing else.
# HOW:  ./scripts/backup.sh dump [path]
#       ./scripts/backup.sh restore <path>
#
#       Runs pg_dump INSIDE the db container, so no Postgres client is needed on the
#       host and the version always matches the server. Reads connection details from
#       the env file through compose, exactly like every other target.
#
#       ENV_FILE (default .env) and COMPOSE_PROJECT_NAME select WHICH stack it acts on.
#       That is not a convenience: until item 32 this script could only ever act on the
#       one stack described by .env, which meant "restore" could not be exercised
#       anywhere but on the owner's live data — and a backup that has never been
#       restored is not a backup. The acceptance scenario installs a disposable stack and
#       drives this script against it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
[ -f "${ENV_FILE}" ] || { echo "no env file at ${ENV_FILE}" >&2; exit 1; }

COMPOSE=(docker compose --env-file "${ENV_FILE}" -f deploy/docker-compose.yml)
SERVICE="db"

usage() {
  cat >&2 <<'USAGE'
usage:
  scripts/backup.sh dump [output-path]      # default: backups/hashi-<timestamp>.sql.gz
  scripts/backup.sh restore <input-path>    # DESTRUCTIVE: replaces the current database

Both read POSTGRES_* from the env file via compose. The stack must be up (`make up`).
Set ENV_FILE and COMPOSE_PROJECT_NAME to act on a stack other than the default one.
USAGE
  exit 2
}

# Read only the variables this script needs, and only their names — never printing the
# file. The env file holds real secrets and must not be echoed (CLAUDE.md, hard rules).
# Asked of the RUNNING container rather than parsed out of the file, so the answer is the
# database this stack actually has rather than the one the file describes.
db_user() { "${COMPOSE[@]}" exec -T "${SERVICE}" printenv POSTGRES_USER | tr -d '\r\n'; }
db_name() { "${COMPOSE[@]}" exec -T "${SERVICE}" printenv POSTGRES_DB | tr -d '\r\n'; }

command_dump() {
  local output="${1:-}"
  if [ -z "${output}" ]; then
    mkdir -p "${REPO_ROOT}/backups"
    output="${REPO_ROOT}/backups/hashi-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
  fi

  local user name
  user="$(db_user)"
  name="$(db_name)"

  echo "dumping database ${name}…" >&2
  # --clean --if-exists so the dump can be restored over an existing database without
  # a manual drop; -Fp (plain) so it is greppable and restorable with psql alone, which
  # matters when you are restoring on a fresh host with no tooling.
  "${COMPOSE[@]}" exec -T "${SERVICE}" \
    pg_dump --username="${user}" --dbname="${name}" --clean --if-exists --format=plain \
    | gzip -9 > "${output}"

  # 0600: this file contains every node's credentials and every user's token — those
  # encrypted — and every node's ADDRESS in the clear. Neither is safe to leave
  # readable by every account on the host, and the second is not protected at all.
  chmod 600 "${output}"

  echo "wrote ${output} ($(du -h "${output}" | cut -f1))" >&2
  cat >&2 <<'WARNING'

IMPORTANT: this file is NOT encrypted. It is plain SQL, gzipped. What is encrypted
inside it is a SUBSET OF COLUMNS — node SSH keys, node_transport secrets, user
tokens and secrets — and those cannot be restored without HASHI_SECRET_KEY.

Everything else is readable by anyone who opens the file: every node's real address
and port, including the leaf addresses no user is ever shown, every SSH host key,
which transports run where, and how many users there are with the date each arrived.
That is a map of the fleet, which is the one thing the entry/leaf split hides.

So both halves are true: this file rebuilds nothing without HASHI_SECRET_KEY, and it
still must not go anywhere you would put something you believed was encrypted — no
object store, no chat, no mail. Keep it on media you control, and keep the key
somewhere this file is not: a copy of both in one place means one theft takes
everything. See docs/deploy/runbook.md, "Backups".
WARNING
}

command_restore() {
  local input="${1:-}"
  [ -n "${input}" ] || usage
  [ -f "${input}" ] || { echo "no such file: ${input}" >&2; exit 1; }

  local user name
  user="$(db_user)"
  name="$(db_name)"

  # Interactive confirmation, because this replaces live data and there is no undo.
  # Skippable for automation with FORCE=1, which has to be set deliberately.
  if [ "${FORCE:-0}" != "1" ]; then
    # WHICH stack, named before anything else. The database is called `hashi` on every
    # stack this project builds — dev, e2e, the disposable ones the acceptance scenarios
    # install — so "type the database name" cannot distinguish them. Since this script
    # learned to obey ENV_FILE and COMPOSE_PROJECT_NAME, a stale export left in a shell
    # from an earlier session would silently aim a destructive restore somewhere else,
    # and the confirmation would look identical. So it shows what it resolved.
    echo "About to restore into:" >&2
    echo "  env file: ${ENV_FILE}" >&2
    echo "  compose project: ${COMPOSE_PROJECT_NAME:-<default: the directory name>}" >&2
    echo "  database: ${name}" >&2
    echo "This REPLACES its contents. Every current node, user and credential is" >&2
    echo "overwritten by the dump." >&2
    printf "Type the database name to confirm: " >&2
    read -r answer
    [ "${answer}" = "${name}" ] || { echo "aborted" >&2; exit 1; }
  fi

  echo "restoring into ${name}…" >&2
  # ON_ERROR_STOP so a failed restore is a failure, not a half-populated database that
  # looks like it worked. --single-transaction so a failure rolls back to the previous
  # state rather than leaving the fleet half-replaced.
  gunzip -c "${input}" | "${COMPOSE[@]}" exec -T "${SERVICE}" \
    psql --username="${user}" --dbname="${name}" \
      --set=ON_ERROR_STOP=on --single-transaction

  echo "restored." >&2
  echo "Restart the control plane so it reconnects: make down && make up" >&2
  echo "If users cannot connect afterwards, HASHI_SECRET_KEY does not match the" >&2
  echo "one this dump was written with — the app will say so loudly on first use." >&2
}

case "${1:-}" in
  dump)    shift; command_dump "$@" ;;
  restore) shift; command_restore "$@" ;;
  *)       usage ;;
esac
