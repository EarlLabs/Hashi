#!/usr/bin/env bash
# WHAT: dump and restore the control database — backlog item 22.
# WHY:  the control database is the single source of truth (core invariants §3): a node
#       holds nothing that cannot be regenerated from it. That cuts both ways. Losing a
#       node is nothing; losing this database is losing every user's access and every
#       node's credentials at once, with no way to rebuild them.
#
#       WHAT THE FILE ACTUALLY IS, because this header has got it wrong in both
#       directions before: the WHOLE artifact is encrypted with age, to the public key in
#       HASHI_BACKUP_AGE_RECIPIENT, before a single byte of it reaches the disk. This host
#       holds only that public half, so it can write a backup and CANNOT read one back.
#       Underneath the age layer it is plain SQL, gzipped, in which a subset of COLUMNS is
#       encrypted again — node `ssh_private_key`, node_transport `secrets`, user `token`,
#       `subject`, `secrets`, `tunnel_address` (§3, encryption at rest) — and those cannot
#       be restored without HASHI_SECRET_KEY. So a restore costs TWO secrets that never
#       meet on this machine: the age identity you carry, and HASHI_SECRET_KEY. That is
#       the whole design, and it is why the previous shape — plain SQL, gzipped, a map of
#       every node's real address including the leaf addresses no user is ever shown —
#       was never safe to put anywhere. This one is.
#
#       What else belongs in a backup — `caddy_data`, `~/.hashi/management/`, `.env`,
#       and why `/opt/hashi` on a node is not backup material — is decided and written
#       down in docs/deploy/runbook.md, "Backups". This script writes the database and
#       nothing else.
# HOW:  ./scripts/backup.sh dump [path]
#       HASHI_RESTORE_AGE_IDENTITY=<path> ./scripts/backup.sh restore <path>
#
#       Runs pg_dump INSIDE the db container, so no Postgres client is needed on the
#       host and the version always matches the server. age runs inside the CONTROL
#       container for the same reason and one more: a restore has to work on a host that
#       was rented an hour ago, and "apt install age first" is a step nobody has at 3am.
#       Nothing new is required on the box beyond what the stack already needs.
#
#       Where the plaintext ever exists: in RAM, in flight, between three processes on
#       this host — pg_dump inside the db container, gzip here, age inside the control
#       container. It is never a file, never a temp, and the only thing written to disk
#       is already-encrypted. Doing better than that would mean pg_dump and age in one
#       container, which means building our own Postgres image; the database is pulled by
#       tag deliberately (see tests/infra/test_builds_converge.py) so that it is never
#       recreated by a build, and trading that away for a shorter pipe is a bad bargain.
#
#       The recipient is read out of the env file by COMPOSE, through
#       deploy/docker-compose.backup.yml, and never passes through this script. Same rule
#       as the connection details below: this script does not open .env.
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
# The same stack plus the one variable a dump needs. Separate file, because in the base
# file it would have to carry a `:?` guard like every other interpolation there — and a
# guard on this one would refuse to start the WHOLE STACK on a host whose keypair does not
# exist yet. Here it refuses exactly one thing, the backup, at the moment it is asked for.
COMPOSE_BACKUP=("${COMPOSE[@]}" -f deploy/docker-compose.backup.yml)
SERVICE="db"

usage() {
  cat >&2 <<'USAGE'
usage:
  scripts/backup.sh dump [output-path]      # default: backups/hashi-<timestamp>.sql.gz.age
  scripts/backup.sh restore <input-path>    # DESTRUCTIVE: replaces the current database

A dump is encrypted to HASHI_BACKUP_AGE_RECIPIENT (an age PUBLIC key, in the env file)
before it is written, so this host cannot read back what it wrote. A restore of such a
file needs the private half, which is never stored here:

  HASHI_RESTORE_AGE_IDENTITY=/path/to/identity scripts/backup.sh restore <input-path>

Artifacts written before that encryption existed — plain SQL, gzipped — still restore,
and need no identity. The shape is sniffed from the file, not from its name.

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

# Which shape is this file? Sniffed, never trusted to the extension: the operator who
# needs this most is restoring a file somebody else named, at an hour when a confusing
# error is expensive. Exactly two shapes are legitimate — the age artifact this script
# writes now, and the plain gzipped SQL it wrote before, which exists in the world and
# must still come back.
artifact_kind() {
  local opening
  # NULs stripped before the command substitution can see one: the gzip shape has them in
  # its first bytes, and bash warns on stderr when a substitution swallows a NUL — an
  # alarming line at the exact moment an operator needs a calm one. age's own header is
  # ASCII, so nothing that matters here is lost.
  opening="$(head -c 21 "$1" 2>/dev/null | tr -d '\000' || true)"
  if [ "${opening}" = "age-encryption.org/v1" ]; then echo "age"; return; fi
  if [ "$(head -c 2 "$1" | od -An -tx1 | tr -d ' \n')" = "1f8b" ]; then echo "gzip"; return; fi
  echo "unknown"
}

command_dump() {
  local output="${1:-}"
  if [ -z "${output}" ]; then
    mkdir -p "${REPO_ROOT}/backups"
    output="${REPO_ROOT}/backups/hashi-$(date -u +%Y%m%dT%H%M%SZ).sql.gz.age"
  fi

  # The recipient is resolved BEFORE pg_dump runs, not discovered as the last stage of the
  # pipeline. A host with no keypair yet is refused while the database is still untouched
  # and no file exists; the other order dumps the fleet first and fails afterwards, having
  # written a partial artifact that looks like a backup.
  local refusal
  if ! refusal="$("${COMPOSE_BACKUP[@]}" config --quiet 2>&1)"; then
    echo "${refusal}" >&2
    cat >&2 <<'MSG'

This dump is encrypted before it is written, so it needs the PUBLIC half of your backup
keypair in HASHI_BACKUP_AGE_RECIPIENT. Generate the pair somewhere that is not this host:

  age-keygen -o hashi-backup-identity.txt

Put the public key it prints in HASHI_BACKUP_AGE_RECIPIENT in your env file, and keep the
identity file with you. It must never be copied onto this machine — a host that can read
its own backups is a host whose seizure hands over every one of them.
MSG
    exit 1
  fi

  local user name
  user="$(db_user)"
  name="$(db_name)"

  echo "dumping database ${name}…" >&2
  local partial="${output}.partial"
  rm -f "${partial}"
  # Created empty and restricted BEFORE any byte lands in it, rather than chmod 600 after
  # the write: for the length of the write the file would otherwise be whatever the
  # operator's umask says, and what is in it is every node's credentials and every user's
  # token. Encrypted, now — one layer, not a reason to drop the other.
  (umask 077; : > "${partial}")

  # --clean --if-exists so the dump can be restored over an existing database without
  # a manual drop; -Fp (plain) so that what comes out from under the age layer is
  # greppable and restorable with psql alone, which matters when you are restoring on a
  # fresh host with no tooling. gzip before age, because ciphertext does not compress.
  #
  # The last stage is a one-off container rather than an exec: compose re-reads the env
  # file at this moment, so a recipient you rotated this morning is the one used tonight,
  # with no stack restart in between.
  if ! "${COMPOSE[@]}" exec -T "${SERVICE}" \
        pg_dump --username="${user}" --dbname="${name}" --clean --if-exists --format=plain \
      | gzip -9 \
      | "${COMPOSE_BACKUP[@]}" run --rm --no-deps -T --entrypoint sh control \
          -c 'exec age --recipient "${HASHI_BACKUP_AGE_RECIPIENT}"' \
      > "${partial}"; then
    rm -f "${partial}"
    echo "the dump failed. Nothing was written." >&2
    exit 1
  fi

  chmod 600 "${partial}"
  mv "${partial}" "${output}"

  echo "wrote ${output} ($(du -h "${output}" | cut -f1))" >&2
  cat >&2 <<'WARNING'

This file is encrypted with age, to HASHI_BACKUP_AGE_RECIPIENT, before it was written.
This host holds only the public half and CANNOT read back what it just wrote. Opening it
takes the private identity you carry, which is not on this machine and must never be put
here.

Opening it is not the same as reading it. Underneath, a subset of columns — node SSH
keys, node_transport secrets, user tokens and secrets — is encrypted again, and those
cannot be restored without HASHI_SECRET_KEY. A restore therefore costs TWO secrets that
never meet on this host. Keep them apart, and keep both somewhere this file is not: a
copy of everything in one place means one theft takes everything.

What somebody who obtains this file learns without those two secrets: that it exists, how
big it is and when it was written. Not a node address, not a leaf address, not how many
users there are, not when any of them arrived.

To restore it:
  HASHI_RESTORE_AGE_IDENTITY=/path/to/identity make restore FROM=<this file>
See docs/deploy/runbook.md, "Backups".
WARNING
}

# Set while an artifact is staged inside the control container, so that an interrupted or
# failed restore does not leave a copy of it there.
STAGED=""
remove_staged() {
  [ -n "${STAGED}" ] || return 0
  "${COMPOSE[@]}" exec -T control rm -f "${STAGED}" >/dev/null 2>&1 || true
  STAGED=""
}

command_restore() {
  local input="${1:-}"
  [ -n "${input}" ] || usage
  [ -f "${input}" ] || { echo "no such file: ${input}" >&2; exit 1; }

  # What the file is, and what opening it needs, are settled BEFORE the confirmation
  # prompt. An operator who types the database name and is then told they are missing the
  # identity has been made to authorise a destructive act for nothing.
  local kind identity=""
  kind="$(artifact_kind "${input}")"
  case "${kind}" in
    age)
      identity="${HASHI_RESTORE_AGE_IDENTITY:-}"
      if [ -z "${identity}" ]; then
        cat >&2 <<'MSG'
this artifact is age-encrypted, and opening it needs the private half of the keypair.
That half is deliberately NOT on this host: the control plane holds only the public half,
so it can write a backup and cannot read one back. Supply it at the moment you restore,
from whatever you are carrying:

  HASHI_RESTORE_AGE_IDENTITY=/path/to/identity make restore FROM=<file>

Never write it into the env file on this machine. Nothing has been changed.
MSG
        exit 1
      fi
      [ -f "${identity}" ] || {
        echo "HASHI_RESTORE_AGE_IDENTITY points at ${identity}, which is not a file." >&2
        echo "Nothing has been changed." >&2
        exit 1
      }
      ;;
    gzip)
      echo "this artifact is PLAIN SQL, gzipped — the shape this script wrote before it" >&2
      echo "encrypted anything. It restores as it always did and needs no age identity." >&2
      ;;
    *)
      cat >&2 <<MSG
${input} is neither shape this script can restore:
  - age-encrypted: the file begins "age-encryption.org/v1"
  - plain SQL, gzipped: the shape written before the encryption existed
Nothing has been changed. If you decrypted an artifact by hand, what you hold is the
second shape and it will restore; if you hold a bare .sql file, gzip it first.
MSG
      exit 1
      ;;
  esac

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
  if [ "${kind}" = "age" ]; then
    # The control container is the one place in this stack that carries age. The already
    # encrypted artifact is handed to it, and the identity is STREAMED in on stdin —
    # `--identity -` — so the private half is never written anywhere on this host, not
    # even inside a container. The plaintext comes back out as a pipe and goes straight
    # into psql; it is a file at no point in either direction.
    trap remove_staged EXIT
    STAGED="/tmp/hashi-restore-$$.age"
    if ! "${COMPOSE[@]}" exec -T control sh -c "cat > '${STAGED}'" < "${input}"; then
      STAGED=""
      cat >&2 <<'MSG'
could not hand the artifact to the control container, which is where age lives. Is the
stack up (`make up`)? If the control plane itself cannot start, decrypt by hand on any
machine that has age and restore the result — this script still accepts that shape:

  age --decrypt --identity /path/to/identity <file> > hashi.sql.gz
  make restore FROM=hashi.sql.gz
MSG
      exit 1
    fi
    "${COMPOSE[@]}" exec -T control age --decrypt --identity - "${STAGED}" < "${identity}" \
      | gunzip -c \
      | "${COMPOSE[@]}" exec -T "${SERVICE}" \
        psql --username="${user}" --dbname="${name}" \
          --set=ON_ERROR_STOP=on --single-transaction
    remove_staged
  else
    gunzip -c "${input}" | "${COMPOSE[@]}" exec -T "${SERVICE}" \
      psql --username="${user}" --dbname="${name}" \
        --set=ON_ERROR_STOP=on --single-transaction
  fi

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
