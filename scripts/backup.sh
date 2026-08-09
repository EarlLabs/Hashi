#!/usr/bin/env bash
# WHAT: dump and restore the control database — backlog item 22.
# WHY:  the control database is the single source of truth (core invariants §3): a node
#       holds nothing that cannot be regenerated from it. That cuts both ways. Losing a
#       node is nothing; losing this database is losing every friend's access and every
#       node's credentials at once, with no way to rebuild them.
#
#       The dump is USELESS WITHOUT HASHI_SECRET_KEY, and that is the design (§3,
#       encryption at rest) — not an oversight to work around. It also means the key is
#       part of the backup in a way this script cannot help with: whoever holds only the
#       dump can restore nothing. Say so out loud, every run, because a backup you
#       cannot restore is worse than no backup — it is a false sense of one.
# HOW:  ./scripts/backup.sh dump [path]
#       ./scripts/backup.sh restore <path>
#
#       Runs pg_dump INSIDE the db container, so no Postgres client is needed on the
#       host and the version always matches the server. Reads connection details from
#       .env through compose, exactly like every other target.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

COMPOSE=(docker compose --env-file .env -f deploy/docker-compose.yml)
SERVICE="db"

usage() {
  cat >&2 <<'USAGE'
usage:
  scripts/backup.sh dump [output-path]      # default: backups/hashi-<timestamp>.sql.gz
  scripts/backup.sh restore <input-path>    # DESTRUCTIVE: replaces the current database

Both read POSTGRES_* from .env via compose. The stack must be up (`make up`).
USAGE
  exit 2
}

# Read only the variables this script needs, and only their names — never printing the
# file. .env holds real secrets and must not be echoed (CLAUDE.md, hard rules).
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

  # 0600: this file contains every node's encrypted credentials and every friend's
  # encrypted token. Encrypted is not the same as safe to leave world-readable.
  chmod 600 "${output}"

  echo "wrote ${output} ($(du -h "${output}" | cut -f1))" >&2
  cat >&2 <<'WARNING'

IMPORTANT: this dump is encrypted with HASHI_SECRET_KEY and cannot be restored
without it. Back that key up SEPARATELY, somewhere this dump is not — a copy of
both in one place defeats the encryption; a copy of only the dump restores nothing.
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
    echo "This REPLACES the contents of database '${name}'. Every current node," >&2
    echo "friend and credential is overwritten by the dump." >&2
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
  echo "If friends cannot connect afterwards, HASHI_SECRET_KEY does not match the" >&2
  echo "one this dump was written with — the app will say so loudly on first use." >&2
}

case "${1:-}" in
  dump)    shift; command_dump "$@" ;;
  restore) shift; command_restore "$@" ;;
  *)       usage ;;
esac
