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
#
#       WHERE IT GOES. When HASHI_BACKUP_ENABLED is 1, the same artifact is then sent to
#       an object store addressed by the S3 PROTOCOL — never by a provider's name, exactly
#       as a node's country and address are node-record data and not code. The credential
#       that sends it is write-only: PutObject and nothing else, so this host can add to
#       the backup history and can neither read nor destroy it. That is also why nothing
#       here verifies an upload by reading it back — it cannot, and the one place that
#       would be possible is the machine an attacker holds. See deploy/backup/upload.py
#       for exactly what a successful upload does and does not prove.
#       COMING BACK. `restore-from-bucket` is the whole of a rebuild in one command, for
#       the day the box is gone: it installs the control plane on this machine, reads the
#       bucket with a credential you are carrying, takes the newest artifact that actually
#       opens, and restores it. It needs three things you carry and nothing that was on
#       the machine you lost — HASHI_SECRET_KEY in the env file here, the age identity,
#       and a READ credential for the bucket. The last two are handed to the command in
#       its environment and are never written onto this host; that is what
#       HASHI_RESTORE_* names are for. What it deliberately does NOT do — DNS, the
#       delivery endpoint's certificate, and telling any user anything — it says on its
#       last screen, because those three are what decide whether a restored control plane
#       serves anybody, and none of them is something a script may do for you.
# HOW:  ./scripts/backup.sh dump [path]
#       ./scripts/backup.sh upload <path>
#       HASHI_RESTORE_AGE_IDENTITY=<path> ./scripts/backup.sh restore <path>
#       HASHI_RESTORE_AGE_IDENTITY=<path> HASHI_RESTORE_S3_ACCESS_KEY_ID=… \
#         HASHI_RESTORE_S3_SECRET_ACCESS_KEY=… ./scripts/backup.sh restore-from-bucket \
#         [object-name]
#
#       EXIT CODES, because a schedule and a panel both have to tell these apart:
#         0  the artifact was written, and sent offsite if that is switched on
#         1  nothing usable happened — refused before the dump, or the dump failed
#         2  wrong usage
#         3  the artifact WAS written and did NOT leave this machine. The dump is on this
#            host and nowhere else; `scripts/backup.sh upload <path>` sends the same file
#            once the store is reachable again. A backup that silently did not leave the
#            machine is the failure this exists to prevent, so it is never a 0.
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
#       as the connection details below: this script does not open .env. The bucket's
#       address and its credential arrive the same way, through
#       deploy/docker-compose.upload.yml, into a container that exists for one upload —
#       so the secret is never in this script, never in an argument list, and never in the
#       environment of the long-running control plane.
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
# The first wall on a machine that has never run this project, which is exactly the machine
# `restore-from-bucket` exists for — so it names the way out rather than only the problem.
[ -f "${ENV_FILE}" ] || {
  cat >&2 <<MSG
no env file at ${ENV_FILE}.

Copy .env.example to .env and fill it in first: this file is deliberately not in any
backup, because it holds HASHI_SECRET_KEY and keeping that beside the data it opens would
mean one theft took both. Everything in it but the values you carry — the hostnames, the
operator password hash, the database password — comes from .env.example.

  cp .env.example ${ENV_FILE}
  make hash-password        # the one value you cannot type: it prints the whole
                            # HASHI_OPERATOR_PASSWORD_HASH line to paste in, and needs
                            # nothing on this host but the container runtime
MSG
  exit 1
}

COMPOSE=(docker compose --env-file "${ENV_FILE}" -f deploy/docker-compose.yml)
# The same stack plus the one variable a dump needs. Separate file, because in the base
# file it would have to carry a `:?` guard like every other interpolation there — and a
# guard on this one would refuse to start the WHOLE STACK on a host whose keypair does not
# exist yet. Here it refuses exactly one thing, the backup, at the moment it is asked for.
COMPOSE_BACKUP=("${COMPOSE[@]}" -f deploy/docker-compose.backup.yml)
# The same stack plus the object store's address and credential, for the length of one
# container. Separate from the recipient's overlay because the two are needed at different
# moments and by different code, and because this one carries a bearer secret that must
# never reach the long-running control plane — see that file's own header.
COMPOSE_UPLOAD=("${COMPOSE[@]}" -f deploy/docker-compose.upload.yml)
# The same stack plus the address of the bucket and the credential that may READ it, for
# the length of one container. A separate file from the upload overlay for the sharpest
# reason of the three: that credential is the one a control plane must never hold, and the
# two must not be able to arrive together by accident. See that file's own header.
COMPOSE_RESTORE=("${COMPOSE[@]}" -f deploy/docker-compose.restore.yml)
SERVICE="db"

# The program that speaks the S3 protocol, kept as a readable file in this repository and
# handed to the container as an argument rather than baked into the image. Two reasons: a
# rebuild is not a precondition for an upload (the restore host is rented an hour before
# use), and the thing that signs a request with a credential is a file a reviewer can read
# rather than a string embedded in a shell script.
UPLOADER="${REPO_ROOT}/deploy/backup/upload.py"
# Its mirror: the program that reads the bucket back. Kept as a second file rather than a
# second verb of the first, because the two are used by different people holding different
# credentials — one on a host that may only write, one on a machine that is being rebuilt.
FETCHER="${REPO_ROOT}/deploy/backup/fetch.py"
# How many artifacts a restore will walk past before it stops. A bucket whose newest few
# objects do not open is not a bucket with one bad night in it, and decrypting a year of
# dailies one at a time is not help at 3am — at that point the operator needs to be told,
# and to name the object they want themselves.
RESTORE_CANDIDATES=5

usage() {
  cat >&2 <<'USAGE'
usage:
  scripts/backup.sh dump [output-path]      # default: backups/hashi-<timestamp>.sql.gz.age
  scripts/backup.sh upload <input-path>     # send an artifact that is already on disk
  scripts/backup.sh restore <input-path>    # DESTRUCTIVE: replaces the current database
  scripts/backup.sh restore-from-bucket [object-name]
                                            # the whole rebuild: install, fetch, restore

A dump is encrypted to HASHI_BACKUP_AGE_RECIPIENT (an age PUBLIC key, in the env file)
before it is written, so this host cannot read back what it wrote. A restore of such a
file needs the private half, which is never stored here:

  HASHI_RESTORE_AGE_IDENTITY=/path/to/identity scripts/backup.sh restore <input-path>

Artifacts written before that encryption existed — plain SQL, gzipped — still restore,
and need no identity. The shape is sniffed from the file, not from its name.

With HASHI_BACKUP_ENABLED=1 a dump is also sent to the object store described by the
HASHI_BACKUP_S3_* block in the env file, with a credential that may only write. If that
send fails the dump still exists here and the exit code is 3 — retry it with `upload`,
which never dumps and never touches the database.

`restore-from-bucket` is the one for the day the machine is gone. On a host that has
never run this project it installs the control plane, reads the bucket, takes the newest
artifact that opens and restores it. It needs three things, all of them carried by you:

  HASHI_SECRET_KEY                     in the env file here — the control plane needs it
  HASHI_RESTORE_AGE_IDENTITY           a path, in this command's environment only
  HASHI_RESTORE_S3_ACCESS_KEY_ID       a READ credential, in this command's environment
  HASHI_RESTORE_S3_SECRET_ACCESS_KEY   only — never written into the env file here

Name an object to restore something other than the newest. It does not move DNS, does not
re-issue the delivery endpoint's certificate and tells no user anything; it says so again
when it has finished.

All of them read POSTGRES_* from the env file via compose. The stack must be running for
every verb but `restore-from-bucket`, which brings it up itself — `make up` on a machine
that publishes nothing, `make up-panel` or `make up-panel-over-ssh` on a deployed host,
and never a bare `make up` there, which would take its published ports away.
Set ENV_FILE and COMPOSE_PROJECT_NAME to act on a stack other than the default one.
USAGE
  exit 2
}

# The env-file gate, M28.7, now shared with scripts/panel-bootstrap.sh — which reached
# compose the same way and printed the same complaint, verbatim, during an install (M28.8).
# One implementation and two callers rather than two scrubbers that drift apart; the file's
# own header carries the finding and the structural property. It uses the COMPOSE array and
# ENV_FILE defined above, so what it tests is this script's own invocation.
ENV_GATE_NOTHING_HAPPENED="Nothing was dumped, written or sent."
# shellcheck source=lib/env-file-gate.sh
. "${REPO_ROOT}/scripts/lib/env-file-gate.sh"

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

# Run the uploader inside a one-off control container. Everything it needs to reach the
# store is in that container's environment, put there by compose; nothing sensitive is on
# the command line, where a process list would show it to every account on this host.
# --no-deps and --entrypoint, so this starts the interpreter and not the control plane.
upload_run() {
  [ -f "${UPLOADER}" ] || {
    echo "the uploader is missing at ${UPLOADER}; this checkout is incomplete." >&2
    return 1
  }
  "${COMPOSE_UPLOAD[@]}" run --rm --no-deps -T --entrypoint python3 control \
    -c "$(cat "${UPLOADER}")" "$@"
}

# Is this artifact going anywhere, and is what it needs to get there actually configured?
# Answered BEFORE the database is read, for the same reason the recipient is: a host whose
# offsite block is half-filled is refused while the database is untouched and no file
# exists, instead of being dumped and then found wanting.
UPLOAD="no"
resolve_upload() {
  local status=0
  upload_run preflight </dev/null || status=$?
  case "${status}" in
    0)  UPLOAD="yes" ;;
    10) UPLOAD="no" ;;  # switched off, and the uploader has already said so out loud
    *)  cat >&2 <<'MSG'

Nothing was dumped, written or sent. Fix the block named above in your env file, or set
HASHI_BACKUP_ENABLED=0 to take a backup that stays on this host on purpose.
MSG
        exit 1 ;;
  esac
}

# Send one artifact, once, and turn the uploader's verdict into this script's. A failure
# here is never fatal to the artifact: the file is on the disk, intact and encrypted, and
# the exit code says exactly that so a schedule can tell it apart from having no backup.
upload_artifact() {
  local artifact="$1"
  if upload_run put "$(basename "${artifact}")" < "${artifact}"; then
    return 0
  fi
  cat >&2 <<MSG

The artifact is written and it did NOT leave this machine. It is at:

  ${artifact}

A backup of this host, on this host, is the failure an offsite copy exists to prevent —
one seizure, one disk, and both are gone together. Nothing needs dumping again: fix what
the store said above and send the same file with

  make backup-upload FROM=${artifact}
MSG
  exit 3
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

  resolve_upload

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

  # Last, so the final thing on the screen is where this artifact actually is. When the
  # upload is off that is said rather than left to be assumed: a backup that never left
  # the machine is not a covered backup, and silence here is how that gets believed.
  if [ "${UPLOAD}" = "yes" ]; then
    upload_artifact "${output}"
  else
    echo "" >&2
    echo "This artifact is on this host and nowhere else. Offsite upload is switched off" >&2
    echo "(HASHI_BACKUP_ENABLED); see the backup block in .env.example." >&2
  fi
}

command_upload() {
  local input="${1:-}"
  [ -n "${input}" ] || usage
  [ -f "${input}" ] || { echo "no such file: ${input}" >&2; exit 1; }

  # Only the encrypted shape ever goes to a bucket. An artifact from before the encryption
  # existed is a readable map of the fleet — every node's real address, including the leaf
  # addresses no user is ever shown — and the one place it must never be put is somewhere
  # somebody else holds. Sniffed from the file, like a restore, because the name proves
  # nothing.
  if [ "$(artifact_kind "${input}")" != "age" ]; then
    echo "${input} is not an encrypted artifact, and only an encrypted artifact is" >&2
    # Quoted heredoc: this text names shell commands, and an unquoted one would RUN the
    # backticked make target instead of printing it — which is exactly what it did the
    # first time it was written.
    cat >&2 <<'MSG'
sent offsite. A file this script wrote begins "age-encryption.org/v1". A plain gzipped
dump reads as the fleet to anyone who obtains it — keep it on media you control and take
a fresh backup with `make backup`, which encrypts before it writes. Nothing was sent.
MSG
    exit 1
  fi

  resolve_upload
  if [ "${UPLOAD}" != "yes" ]; then
    cat >&2 <<'MSG'

Offsite upload is switched off, so there is nowhere to send this. Set HASHI_BACKUP_ENABLED=1
and the HASHI_BACKUP_S3_* block in your env file first. Nothing was sent.
MSG
    exit 1
  fi
  upload_artifact "${input}"
  echo "the artifact is unchanged on this host as well: ${input}" >&2
}

# How much this restore would actually replace, measured rather than asserted — M28.10.
#
# The confirmation used to say "Every current node, user and credential is overwritten"
# on every restore, and on the machine this command exists for that sentence describes
# NOTHING: a control plane installed minutes ago holds a migrated schema and no rows. A
# prompt that overstates what it is protecting is a prompt an operator learns to type
# through, and this one was being asked in exactly the case where there was nothing to
# protect.
#
# Echoes a row count, or nothing at all when it could not be asked — in which case the
# caller treats it as unknown and keeps the confirmation, because the safe direction for
# a destructive act is to ask.
#
# It names no table of ours. The count is over every base table in `public`, discovered
# from the catalogue, so this stays true across the schema changing under it; the one
# name it does mention is alembic's own bookkeeping row, which every migrated database
# has, which is nobody's data, and which the dump replaces anyway.
rows_at_stake() {
  local user="$1" name="$2"
  "${COMPOSE[@]}" exec -T "${SERVICE}" \
    psql --username="${user}" --dbname="${name}" --tuples-only --no-align --quiet \
    --command "select coalesce(sum(n), 0) from (
        select (xpath('/row/c/text()', query_to_xml(
                 format('select count(*) as c from %I.%I', table_schema, table_name),
                 false, true, '')))[1]::text::bigint as n
        from information_schema.tables
        where table_schema = 'public' and table_type = 'BASE TABLE'
          and table_name <> 'alembic_version') t" 2>/dev/null | tr -d '[:space:]'
}

# The refusal when the question cannot be asked at all, and it is its own function
# because two places need to say the same thing.
#
# What happened before: over a non-interactive session the prompt was printed, `read` met
# EOF, and the script exited 2 with no sentence — after installing a control plane and
# fetching an artifact. Nothing anywhere said a terminal was needed. An operator running
# this over `ssh host 'make …'`, from a cron entry, or from any wrapper that closes
# stdin, got a bare exit code at the end of a rebuild.
no_terminal_refusal() {
  local at_stake="$1" measured
  case "${at_stake}" in
    unknown) measured="this database could not be counted, so what it holds is unknown" ;;
    *)       measured="this database holds ${at_stake} row(s) of data" ;;
  esac
  cat >&2 <<MSG

this restore replaces live data and there is no terminal here to confirm it on — stdin
is not a tty, so the question cannot be asked and nothing has been changed.

${measured}, and replacing it is not something to do on an assumption.

Run it again from a terminal, or say deliberately that nothing here needs keeping:

  FORCE=1 <the same command>

FORCE=1 skips the question and nothing else. A machine this command has just installed
from nothing holds no rows at all, and that case never asks in the first place.
MSG
  exit 1
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

  # Interactive confirmation, because this replaces live data and there is no undo —
  # asked only when there IS live data, and refused out loud when it cannot be asked.
  # Skippable for automation with FORCE=1, which has to be set deliberately.
  local at_stake
  if [ "${FORCE:-0}" != "1" ]; then
    # Measured only when it is going to be used: FORCE says the operator has already
    # decided, and a count nobody is shown is one container exec for nothing.
    at_stake="$(rows_at_stake "${user}" "${name}" || true)"
    [ -n "${at_stake}" ] || at_stake="unknown"
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
    if [ "${at_stake}" = "0" ]; then
      # The case this whole command exists for, and the one the old prompt lied about.
      # Nothing is lost here, so nothing is asked: a question whose true answer is
      # always yes is a step, and a step on the way out of a seizure is a step skipped.
      echo "  holding: no rows at all — this control plane was installed and never used." >&2
      echo "Nothing here is being overwritten, so there is nothing to confirm." >&2
    else
      if [ "${at_stake}" = "unknown" ]; then
        echo "  holding: unknown — the row count could not be read from this database." >&2
      else
        echo "  holding: ${at_stake} row(s) of data." >&2
      fi
      echo "This REPLACES its contents. Every current node, user and credential is" >&2
      echo "overwritten by the dump." >&2
      # Before the prompt rather than after it meets EOF: printing a question into a
      # session that cannot answer, and then exiting on the silence, is how this ended
      # a whole rebuild with a bare exit code.
      [ -t 0 ] || no_terminal_refusal "${at_stake}"
      printf "Type the database name to confirm: " >&2
      read -r answer
      [ "${answer}" = "${name}" ] || { echo "aborted" >&2; exit 1; }
    fi
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
  # NOT `make down && make up`, which is what this line used to say. On a deployed host
  # that sequence converges the stack back to the base file's shape and takes away every
  # published port — the Makefile's own comment on `up-panel` warns against exactly it —
  # so the instruction that was meant to finish a rebuild ended with a panel nobody could
  # reach, two paragraphs above the same screen recommending `make up-panel` (M28.10,
  # finding 3). `restart` restarts what is running and changes nothing about what this
  # host publishes, whichever `up` brought it up.
  echo "Restart the control plane so it reconnects: make restart-control" >&2
  echo "If users cannot connect afterwards, HASHI_SECRET_KEY does not match the" >&2
  echo "one this dump was written with — the app will say so loudly on first use." >&2
}

# --- coming back from the bucket, M28.8 ---------------------------------------
#
# Everything below exists for one day, and the measure of it is not that a restore is
# possible — it already was — but that it is possible by somebody frightened and in a
# hurry, on a machine they rented an hour ago, possibly from a phone tether. Every step
# that is not in the command is a step that gets skipped or done wrong.

# The read side of the bucket, inside a one-off control container, exactly as the upload
# runs inside one: the program is read out of this checkout and handed over as a `-c`
# argument, so a restore never waits on a rebuild and a stale image cannot break it. The
# credential reaches the container through compose and never through an argument list.
fetch_run() {
  [ -f "${FETCHER}" ] || {
    echo "the fetcher is missing at ${FETCHER}; this checkout is incomplete." >&2
    return 1
  }
  "${COMPOSE_RESTORE[@]}" run --rm --no-deps -T --entrypoint python3 control \
    -c "$(cat "${FETCHER}")" "$@"
}

# Does this file open with the identity the operator is carrying, and is what comes out of
# it a gzip stream? Asked BEFORE the destructive confirmation, for the same reason the
# shape is: nobody types a database name to authorise a restore that was always going to
# fail. It costs one decryption, and the plaintext goes into `gunzip -t` and nowhere else
# — not to a file, not to a terminal.
#
# Three verdicts, because they call for three different things and "it did not work" is
# the answer that costs an hour at 3am. `no identity matched` is age's own words for "this
# is not the keypair these artifacts were written to", and it is the one failure that
# walking back to an older artifact cannot fix — every object in the bucket was written to
# the same public half, so trying the next one is a slower way to print the same sentence.
OPENS_VERDICT=""
OPENS_COMPLAINT=""
artifact_opens() {
  local file="$1" kind="$2" identity="$3"
  OPENS_VERDICT="damaged"
  OPENS_COMPLAINT=""

  if [ "${kind}" != "age" ]; then
    # The pre-M28.2 shape. Nothing encrypted it, so nothing has to open it; whether it is
    # a whole gzip stream is the only question left.
    if OPENS_COMPLAINT="$(gunzip -t "${file}" 2>&1)"; then OPENS_VERDICT="ok"; fi
    return 0
  fi

  trap remove_staged EXIT
  STAGED="/tmp/hashi-verify-$$.age"
  if ! "${COMPOSE[@]}" exec -T control sh -c "cat > '${STAGED}'" < "${file}"; then
    STAGED=""
    OPENS_COMPLAINT="the artifact could not be handed to the control container, which is
where age lives. Is the control plane running?"
    return 0
  fi
  # The identity is STREAMED in on stdin, exactly as the restore does it, so the private
  # half is never written anywhere on this host — not even inside a container. The
  # plaintext is a pipe into `gunzip -t`; only the two tools' complaints are captured.
  if OPENS_COMPLAINT="$(
      { "${COMPOSE[@]}" exec -T control age --decrypt --identity - "${STAGED}" \
          < "${identity}" | gunzip -t; } 2>&1
    )"; then
    OPENS_VERDICT="ok"
  else
    case "${OPENS_COMPLAINT}" in
      *"no identity matched"*) OPENS_VERDICT="identity" ;;
    esac
  fi
  remove_staged
}

# The delivery name this control plane serves, asked of the RUNNING container rather than
# parsed out of the env file — the same rule as POSTGRES_* above, and the same reason: the
# answer is the stack that exists rather than the file that describes it. It is a public
# hostname and printing it is not a disclosure; a user's client sends it in the clear on
# every refresh.
public_host() {
  "${COMPOSE[@]}" exec -T control printenv HASHI_PUBLIC_HOST 2>/dev/null | tr -d '\r\n' || true
}

command_restore_from_bucket() {
  local wanted="${1:-}"

  # --- 1. what this machine must already have ---------------------------------
  #
  # A genuinely bare host has no container runtime; the acceptance walk behind the
  # runbook's prerequisite list met that, `git` and `make` all missing at once. Two of
  # those three cannot be missing HERE, and saying so is the useful half: `git` is what
  # put this checkout on the machine and `make` is what ran this command. The runtime is
  # what is left, and this command does not install it — piping a vendor's shell script
  # into a root shell is not a thing to do on your behalf on the day you are rebuilding
  # after a seizure, and the runbook names the command so you can decide.
  if ! command -v docker >/dev/null 2>&1; then
    cat >&2 <<'MSG'
this machine has no `docker`, and hashi is a compose stack — there is nothing here to
restore into yet. Nothing has been fetched and nothing has been changed.

Install a container runtime with the compose plugin, then run this again; a second run is
safe. The runbook's "What every box must already have" has the one command, and deliberately
leaves running it to you.
MSG
    exit 1
  fi
  # Asked through this script's own compose invocation rather than a bare one, so the rule
  # that has no exceptions here keeps having none: every compose call in this file carries
  # --env-file, because without it every ${VAR} silently becomes an empty string. The
  # `version` verb reads neither the env file nor the compose file; what it answers is
  # whether the plugin is installed at all.
  if ! "${COMPOSE[@]}" version >/dev/null 2>&1; then
    cat >&2 <<'MSG'
`docker` is here but the compose plugin is not, and every stack in this project is a
compose stack. Nothing has been fetched and nothing has been changed.

This is the half of a container runtime that a minimal install leaves out. Install the
compose plugin and run this again.
MSG
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    cat >&2 <<'MSG'
the docker daemon is not answering on this machine, so nothing can be started, fetched or
restored. Nothing has been changed.

Start it — or, if you are not in the group that may talk to it, become a user who is. A
restore is not run as root for you.
MSG
    exit 1
  fi

  # --- 2. the two secrets that never meet, both of them carried ---------------
  #
  # HASHI_SECRET_KEY is the one that has to end up in the env file on THIS host: the
  # control plane cannot start without it and cannot read a single node or user credential
  # without the right one. That is not a weakening of the design — it is where the design
  # puts it. What must never be written here is the other two, and they are checked in
  # THIS COMMAND'S OWN ENVIRONMENT rather than in the env file, which this script does not
  # open (CLAUDE.md, hard rules). The effect is the enforcement: a credential that is only
  # in the env file is a refusal, with the sentence that says where it belongs instead.
  local identity="${HASHI_RESTORE_AGE_IDENTITY:-}"
  if [ -z "${identity}" ]; then
    cat >&2 <<'MSG'
HASHI_RESTORE_AGE_IDENTITY is not set, and without it nothing in the bucket opens.

That is the private half of the backup keypair — the file `age-keygen` printed when the
pair was made. This host holds only the public half, on purpose: it can write a backup and
cannot read one back, which is why a seizure of the old machine handed over every artifact
it ever wrote and opened none of them. Supply it here, from whatever you are carrying:

  HASHI_RESTORE_AGE_IDENTITY=/path/to/identity \
  HASHI_RESTORE_S3_ACCESS_KEY_ID=… HASHI_RESTORE_S3_SECRET_ACCESS_KEY=… \
  make restore-from-bucket

Never write it into the env file on this machine. Nothing has been fetched or changed.
MSG
    exit 1
  fi
  if [ ! -f "${identity}" ]; then
    echo "HASHI_RESTORE_AGE_IDENTITY points at ${identity}, which is not a file." >&2
    echo "That is the path to the age identity you carry, not its contents." >&2
    echo "Nothing has been fetched and nothing has been changed." >&2
    exit 1
  fi

  local absent=()
  [ -n "${HASHI_RESTORE_S3_ACCESS_KEY_ID:-}" ] || absent+=("HASHI_RESTORE_S3_ACCESS_KEY_ID")
  [ -n "${HASHI_RESTORE_S3_SECRET_ACCESS_KEY:-}" ] || \
    absent+=("HASHI_RESTORE_S3_SECRET_ACCESS_KEY")
  if [ ${#absent[@]} -gt 0 ]; then
    cat >&2 <<MSG
not set in this command's environment: ${absent[*]}.

That is the credential a restore READS the bucket with, and it is deliberately not the one
a control plane keeps. The key in the env file may only write — PutObject and nothing else
— so that whoever holds the machine can add to the backup history and can neither read it
nor destroy it. The reading credential is yours, it is handed over at the moment you
restore, and it is checked here rather than in the env file precisely so that putting it
there is not a working shortcut:

  HASHI_RESTORE_AGE_IDENTITY=/path/to/identity \\
  HASHI_RESTORE_S3_ACCESS_KEY_ID=… HASHI_RESTORE_S3_SECRET_ACCESS_KEY=… \\
  make restore-from-bucket

Nothing has been fetched and nothing has been changed.
MSG
    exit 1
  fi

  # --- 3. a control plane to restore into -------------------------------------
  #
  # Before the bucket, and not the other way round, for a mechanical reason worth stating:
  # the program that speaks to the store runs INSIDE this project's control image, which
  # is what makes a restore need nothing installed on the host. There is no image until
  # something builds one. The bootstrap is idempotent, so this is also what makes the
  # whole command safe to run again after any failure below.
  echo "" >&2
  echo "installing the control plane on this machine first — the program that reads the" >&2
  echo "bucket runs inside its image, so there is nothing to fetch with until it exists." >&2
  echo "" >&2
  if ! "${REPO_ROOT}/scripts/panel-bootstrap.sh" --env-file "${ENV_FILE}"; then
    cat >&2 <<MSG

the control plane did not come up, so there is nothing to restore into. Nothing was
fetched and nothing was changed — the bucket has not been touched.

Whatever the bootstrap said above is the thing to fix; it is about ${ENV_FILE} or about
this host, not about your backup. Run this again afterwards; a second run is safe.
MSG
    exit 1
  fi

  # The destructive question this may still have to ask is asked ABOUT here, before a
  # byte leaves the bucket. The restore itself asks it again at the moment it matters —
  # this is only the case where it could never be answered: no terminal, no FORCE, and a
  # database with something in it. Over a non-interactive session that used to be
  # discovered at the very end, after an install and a fetch, and it was discovered as
  # exit 2 with nothing said. Whether there is anything to lose cannot be known before
  # section 3 above, because until then there is no database on this machine at all.
  if [ "${FORCE:-0}" != "1" ] && [ ! -t 0 ]; then
    local standing
    standing="$(rows_at_stake "$(db_user)" "$(db_name)" || true)"
    [ -n "${standing}" ] || standing="unknown"
    [ "${standing}" = "0" ] || no_terminal_refusal "${standing}"
  fi

  # --- 4. what is in the bucket -----------------------------------------------
  echo "" >&2
  if ! fetch_run preflight </dev/null; then
    echo "" >&2
    echo "Nothing was fetched and nothing was changed." >&2
    exit 1
  fi

  local catalogue
  if ! catalogue="$(fetch_run list </dev/null)"; then
    echo "" >&2
    echo "Nothing was fetched and nothing was changed." >&2
    exit 1
  fi

  # Shown rather than summarised. An operator who can see the dates can tell at a glance
  # whether the schedule stopped three weeks ago, which no exit code of ours would say.
  # `awk` rather than `head`: a closed pipe under `pipefail` reads as a failed command.
  echo "" >&2
  echo "what is in the bucket, newest first — the store's own timestamps, not the names:" >&2
  printf '%s\n' "${catalogue}" | awk -F'\t' 'NR<=10 {printf "  %s  %12s bytes  %s\n", $1, $2, $3}' >&2
  echo "" >&2

  # --- 5. the newest one that actually opens ----------------------------------
  local candidates
  if [ -n "${wanted}" ]; then
    candidates="${wanted}"
    echo "restoring the object you named: ${wanted}" >&2
  else
    candidates="$(printf '%s\n' "${catalogue}" \
      | awk -F'\t' -v limit="${RESTORE_CANDIDATES}" 'NR<=limit {print $3}')"
  fi

  local chosen="" name target partial kind tried=0
  while IFS= read -r name; do
    [ -n "${name}" ] || continue
    case "${name}" in
      */../*|../*|*/..|/*)
        echo "the store answered with an object name this will not write to disk: ${name}" >&2
        continue ;;
    esac
    tried=$((tried + 1))

    target="${REPO_ROOT}/backups/${name}"
    partial="${target}.partial"
    mkdir -p "$(dirname "${target}")"
    rm -f "${partial}"
    # Created empty and restricted before a byte lands in it, exactly as a dump is. What
    # arrives is ciphertext, and that is one layer rather than a reason to drop the other.
    (umask 077; : > "${partial}")
    if ! fetch_run get "${name}" </dev/null > "${partial}"; then
      rm -f "${partial}"
      echo "" >&2
      echo "Nothing was restored and nothing was changed." >&2
      exit 1
    fi
    chmod 600 "${partial}"
    mv "${partial}" "${target}"

    kind="$(artifact_kind "${target}")"
    if [ "${kind}" = "unknown" ]; then
      echo "${name} is neither shape this can restore — it is not age ciphertext and it" >&2
      echo "is not a gzipped dump. It is at ${target} if you want to look at it." >&2
      OPENS_VERDICT="damaged"
    else
      artifact_opens "${target}" "${kind}" "${identity}"
    fi

    case "${OPENS_VERDICT}" in
      ok)
        chosen="${target}"
        break ;;
      identity)
        cat >&2 <<MSG

the artifact is intact; the identity is wrong.

${name} came out of the bucket whole — the store held it and this machine read it back.
What it will not do is open: age says no identity matched, which means the file in
HASHI_RESTORE_AGE_IDENTITY is not the private half of the keypair these backups were
written to. Every object in that bucket was written to the same public key, so an older
one would answer the same way and this stops rather than walking the history to say it
again.

Check that you are pointing at the right file — the one \`age-keygen\` printed when the
pair was made, beginning "AGE-SECRET-KEY-1". The artifact is at ${target}; nothing was
changed.
MSG
        exit 1 ;;
      *)
        echo "" >&2
        echo "${name} did not open, and it is not the identity — this artifact is damaged." >&2
        printf '%s\n' "${OPENS_COMPLAINT}" | sed 's/^/  /' >&2
        # Only when there is in fact one before it. An operator who named an object gets a
        # single candidate, and "trying the one before it" followed immediately by "none of
        # them opened" reads as a command that has lost track of what it is doing — at
        # which point they stop believing the rest of the output, which is the part telling
        # them which of their three inputs is wrong.
        if [ -z "${wanted}" ]; then echo "Trying the one before it." >&2; fi
        echo "" >&2 ;;
    esac
  done <<< "${candidates}"

  if [ -z "${chosen}" ]; then
    # Two different sentences, because the operator who named an object has already done
    # the thing the other one is about to be asked to do.
    local reach_further="Name an older object yourself to reach further back than this
command does on its own:

  … make restore-from-bucket OBJECT=<one of the names listed above>"
    if [ -n "${wanted}" ]; then
      reach_further="That is the one object you named. Run this again without OBJECT= to
let it take the newest that opens, or name another from the listing above."
    fi
    cat >&2 <<MSG

${tried} artifact(s) were fetched and none of them opened. Nothing was restored and nothing
was changed.

That is a statement about the bucket rather than about this machine: the objects are there,
they came back whole enough to try, and what is inside them is not what a backup of this
project looks like. ${reach_further}

The ones that were tried are in ${REPO_ROOT}/backups/ and can be examined with the identity
on any machine that has age.
MSG
    exit 1
  fi

  echo "" >&2
  echo "restoring ${chosen}" >&2
  echo "" >&2
  command_restore "${chosen}"

  # --- 6. and what it did not do ----------------------------------------------
  #
  # Last, on the screen the operator is actually looking at, rather than in a paragraph
  # they reach afterwards. A restored control plane on a new address, with the delivery
  # name still pointing at the machine that was lost, serves nobody — and every one of
  # these three is a thing no script may do on somebody's behalf.
  local delivery
  delivery="$(public_host)"
  [ -n "${delivery}" ] || delivery="<HASHI_PUBLIC_HOST>"

  # A restored fleet is an UNBACKED-UP fleet, and until M28.10 nothing said so — not the
  # closing screen and not the runbook. The write-only key and the age recipient lived
  # only in the `.env` that was lost, deliberately, because that file is in no backup: so
  # the machine that has just been rebuilt out of the backup history cannot add to it.
  # `make backup` on the restored host refuses outright, and the panel is honest about
  # what it RECORDS while saying nothing about the fact that nothing will be recorded.
  #
  # Measured, not assumed: the same compose check `dump` makes before it reads the
  # database, which trips on a recipient that is missing or blank. Its complaint is
  # discarded rather than printed — M28.7's rule, and this is not the place to start
  # repeating what compose says about an env file.
  local backup_standing
  if "${COMPOSE_BACKUP[@]}" config --quiet >/dev/null 2>&1; then
    backup_standing="Backups: this host has an age recipient, but nothing is SCHEDULED
here — the crontab was on the machine you lost. \`make backup-schedule\` starts
it again and \`make backup-status\` is what it will say afterwards. Until then
the panel reads \"No backup has ever been recorded on this host.\", and it is
right."
  else
    backup_standing="Backups: this host is NOT backing anything up, and this is the quiet
one. HASHI_BACKUP_AGE_RECIPIENT and the write-only HASHI_BACKUP_S3_* key lived
only in the .env you lost — deliberately, because that file is in no backup —
so \`make backup\` here refuses today rather than writing anything. Put the
PUBLIC half of the age keypair you are carrying into ${ENV_FILE}, refill that
S3 block, then \`make backup-schedule\`. Until you do, this fleet has exactly one
copy of itself and it is this machine."
  fi

  cat >&2 <<MSG

──────────────────────────────────────────────────────────────────────────────
The control plane is back, with the users, nodes and tokens that artifact held.
Three things it did NOT do, and each of them is yours:

  1. DNS. Nothing here moved a record. ${delivery} still points at the machine
     you lost, and until it points at this one, every user's link resolves to a
     box that is gone: the tokens are alive and the address is not. This is the
     one that leaves a perfectly restored control plane serving nobody.

  2. The delivery endpoint's certificate. It was deliberately not in the backup
     — the old host's private keys are to be presumed compromised. Caddy asks a
     public CA for a new one the first time that name resolves HERE and inbound
     80 and 443 reach this machine, which cannot happen before 1. Until then
     /sub/* serves nothing. The panel is unaffected: it is served by Caddy's own
     CA, which is new, so each of your own devices is asked to trust the console
     once more.

  3. Telling anybody. No message goes to any user from this command or from the
     control plane — there is no channel, and that is a charter decision rather
     than an omission. If the delivery NAME is gone rather than merely pointing
     elsewhere, the tokens survived and the URL they live in did not, and every
     user has to be handed a new link by you.

Nothing on this host is reachable from outside it yet, either: this stack
publishes no ports, so there is no panel to log into until you open them:

  make up-panel            the delivery endpoint on 80/443, and the console on
                           this host's management-tunnel address
  make up-panel-over-ssh   the same without that last one, for a host with no
                           tunnel yet — which is this one, unless you have
                           already built one here. The console then answers on
                           loopback only and you reach it from your own machine:
                             ssh -L <panel port>:127.0.0.1:<panel port> you@here

The tunnel that reached the old panel does not reach this one: its keys were on
the machine you lost, and \`make up-panel\` on a host with no tunnel address
fails on a bind docker cannot make.

${backup_standing}

And one thing this command cannot check for you. Whether HASHI_SECRET_KEY in
${ENV_FILE} is the key this artifact was written under: the restore succeeds
either way, because the rows arrive whatever the key is and the columns holding
node and user secrets simply stay shut. Open the panel — if the screens that
touch a node or a user say "The data is intact; the key is wrong.", then it is
not, and the fix is that one line rather than another artifact.
──────────────────────────────────────────────────────────────────────────────
MSG
}

# Here, in the dispatch, and not inside the verb functions: an env file compose cannot
# parse is answered once, before any verb is entered and therefore before every compose
# call any of them can reach, without the file's contents. See env_file_must_be_readable.
# That is why a new verb is added HERE and never given a gate of its own — including
# restore-from-bucket, which reaches compose through panel-bootstrap as well as directly.
case "${1:-}" in
  dump)    shift; env_file_must_be_readable; command_dump "$@" ;;
  upload)  shift; env_file_must_be_readable; command_upload "$@" ;;
  restore) shift; env_file_must_be_readable; command_restore "$@" ;;
  restore-from-bucket)
           shift; env_file_must_be_readable; command_restore_from_bucket "$@" ;;
  *)       usage ;;
esac
