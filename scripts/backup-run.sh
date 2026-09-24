#!/usr/bin/env bash
# WHAT: the thing a schedule calls — decides whether a backup is owed right now, runs
#       scripts/backup.sh when it is, and writes down what happened so that a day which
#       was missed is still visible tomorrow.
# WHY:  a schedule that silently skips is the failure mode discovered during a restore.
#       Everything that could skip silently is therefore decided HERE rather than in the
#       thing that ticks:
#
#         - WHEN. `cron` fires this every 15 minutes and carries no opinion about the
#           hour; this script decides whether the day's run is owed. That is deliberate.
#           A crontab line that says `0 4 * * *` is a promise cron cannot keep — if the
#           box is asleep, off, or being rebuilt at 04:00, the minute passes and nothing
#           anywhere records that it did. Here, "today's backup has not been taken" stays
#           true until a backup is taken, so the box that comes back at 10:00 takes it at
#           10:00 and the panel can still say the run was late.
#
#         - IN WHOSE 04:00. A host's clock is UTC and its owner is not. HASHI_BACKUP_AT
#           and HASHI_BACKUP_TZ are read out of the env file and applied here, so the
#           answer does not depend on the host's timezone, on cron's timezone, or on
#           which of the two a given cron implementation uses (they disagree).
#
#         - AND WHETHER IT WORKED. Nothing else on this host knows. The bucket cannot be
#           asked: the credential this machine holds may only write, so "is yesterday's
#           object there" is a question it is physically unable to put. The record this
#           script leaves is therefore the only account of the backup history that exists
#           on the control plane, which is why it is written on every run, including the
#           runs that failed, and why a missed date is kept rather than counted.
#
#       WHAT IS NOT IN THE RECORD, on purpose: anything about a person. No user, no node,
#       no address, no subscription — dates, exit codes and the schedule's own settings,
#       and nothing else, for ever (CLAUDE.md: never log who connected to what). A file
#       written once a day for years is exactly the thing that grows into a log, so the
#       set of keys is fixed and tests/infra/test_backup_schedule.py fails on a new one.
# HOW:  scripts/backup-run.sh tick     # what cron calls: run a backup only if one is owed
#       scripts/backup-run.sh now      # take one now whatever the schedule says (make backup)
#       scripts/backup-run.sh due      # say what `tick` would do; change nothing
#       scripts/backup-run.sh status   # what the record says, in words
#
#       ENV_FILE (default .env) selects which stack, exactly as scripts/backup.sh does,
#       and is passed through to it. HASHI_BACKUP_STATE_DIR (default backups/state) moves
#       the record; the control container is given a read-only view of the DEFAULT one —
#       see deploy/docker-compose.yml — so moving it means the panel looks elsewhere.
#
#       This script reads THREE names out of the env file and can read no others: the
#       whitelist below is enforced, and `scripts/backup.sh` still opens nothing. All
#       three are settings, not secrets — they are in `.env.example` in the clear — and
#       the alternative was to have the schedule learn its own hour from a container it
#       cannot start when the stack is down, which is precisely the moment it has to
#       decide that a backup is owed. The same grep-one-named-key shape as
#       scripts/panel-bootstrap.sh, and for the same reason: never `source`, never print.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

BACKUP="${REPO_ROOT}/scripts/backup.sh"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
STATE_DIR="${HASHI_BACKUP_STATE_DIR:-${REPO_ROOT}/backups/state}"
STATE_FILE="${STATE_DIR}/last-run.json"
LOCK_DIR="${STATE_DIR}/.tick.lock"

# The record's own version. M28.6 reads this file; a reader that finds a number it does
# not know should say so rather than guess at the fields.
SCHEMA=1
# How long a run that produced NOTHING (exit 1 — refused, or the stack was not up yet)
# waits before the next tick tries again, and how many times per day it may. Exit 3 is
# excluded on purpose: the artifact exists and is intact, re-dumping would fill the disk
# with copies of the same database, and the remedy is `make backup-upload FROM=<path>`.
RETRY_AFTER_SECONDS=3600
MAX_ATTEMPTS=6
# A tick that crashes must not stop every later tick. A lock older than this is broken and
# the breaking is said out loud — a lock directory left behind by a killed run is otherwise
# a schedule that stops for ever, silently, which is the shape this whole file refuses.
STALE_LOCK_SECONDS=21600
# How many missed dates are kept by date. Older ones survive as a count, which is what
# `missed_total` is for: the fact that a day was missed must survive, even when the list
# has rolled over.
MISSED_KEPT=30

# How far back the walk over missing days goes. Beyond it the walk stops, so a gap of more
# than a year is understated — which is a gap nobody is going to be surprised by, and the
# alternative is a tick that spends a second counting days nobody will read.
MISSED_SCAN_LIMIT=400

usage() {
  cat >&2 <<'USAGE'
usage:
  scripts/backup-run.sh tick      # what the schedule calls: back up only if one is owed
  scripts/backup-run.sh now       # back up now, whatever the schedule says
  scripts/backup-run.sh due       # say what `tick` would do right now; change nothing
  scripts/backup-run.sh status    # what the record says, in words

The schedule is HASHI_BACKUP_AT and HASHI_BACKUP_TZ in the env file. `make backup-schedule`
installs the cron entry that calls `tick`; `make backup-unschedule` removes it.

Exit codes are scripts/backup.sh's, unchanged: 0 written (and sent, if that is on), 1 no
artifact, 2 usage, 3 the artifact exists and did not leave this machine. A `tick` with
nothing owed exits 0 and prints nothing, so a schedule that is working is quiet.
USAGE
  exit 2
}

# --- the three settings, read by name and never by the fileful --------------------------

# The only names this script may take out of the env file. Enforced rather than intended:
# the whole reason scripts/backup.sh opens nothing is that a routine which reads the env
# file is one mistake away from printing it, and this one runs unattended, every 15
# minutes, with its output going wherever cron sends it.
SCHEDULE_KEYS=" HASHI_BACKUP_AT HASHI_BACKUP_TZ HASHI_BACKUP_ENABLED "

# shellcheck source=lib/env-value.sh
. "${REPO_ROOT}/scripts/lib/env-value.sh"

env_value() {
  case "${SCHEDULE_KEYS}" in
    *" $1 "*) ;;
    *) echo "scripts/backup-run.sh may not read ${1} out of an env file." >&2; exit 2 ;;
  esac
  [ -f "${ENV_FILE}" ] || return 0
  # The whitelist above is this script's own and stays here, in front of the read. The
  # EXTRACTION is the library's — last assignment wins, the way an env file is read, and
  # since M28.13 a `\r` goes with it. Nothing this script reads changes: all three values
  # pass through `sanitised` below, whose allowlist never admitted a carriage return.
  env_value_of "${ENV_FILE}" "$1"
}

# Everything that reaches the record comes through here. The values are read from a file
# the operator edits, and the record is JSON: an unescaped quote in HASHI_BACKUP_TZ would
# otherwise write a file M28.6 cannot parse, on the one host that cannot be asked again.
sanitised() {
  printf '%s' "$1" | tr -cd 'A-Za-z0-9_+:/.-' | cut -c1-64
}

AT=""; AT_SOURCE=""; ZONE=""; ZONE_SOURCE=""; OFFSITE=""

resolve_schedule() {
  local raw

  # THE HOUR. Unset or unreadable falls back to 04:00 and says which — a typo in a time
  # must not stop the backups, it must be visible in the panel while they keep happening.
  raw="$(sanitised "$(env_value HASHI_BACKUP_AT)")"
  if [ -z "${raw}" ]; then
    AT="04:00"; AT_SOURCE="unset"
  elif [[ "${raw}" =~ ^([0-9]|[01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    # `4:00` means what it looks like; the record and every comparison use `04:00`.
    #
    # `10#` is not decoration. Both printf and $(( )) read a leading zero as OCTAL, so a
    # perfectly ordinary `08:30` or `09:15` was a fatal "invalid octal number" under
    # `set -e` — and fatal BEFORE the record is written, so the tick left no trace at all
    # and the panel would have shown nothing wrong. That is worse than the malformed
    # fallback below, which at least still takes a backup, and it is this milestone's own
    # silent skip arriving through the front door for two hours out of twenty-four.
    AT="$(printf '%02d:%s' "$((10#${raw%%:*}))" "${raw##*:}")"; AT_SOURCE="configured"
  else
    AT="04:00"; AT_SOURCE="malformed"
  fi

  # THE ZONE, and this is the one the plan calls out. A host's clock is UTC and its owner
  # is not, so 04:00 has to name a place or it means nothing. An IANA zone NAME rather
  # than an offset, because an offset is a decision taken once about a rule that changes:
  # zones move their clocks by decree and by season, a name follows that and a number
  # silently stops being what was meant.
  #
  # `TZ=Nowhere/Useful date` does NOT fail — it prints UTC and exits 0 (checked, not
  # assumed). So an unknown zone would otherwise be indistinguishable from a working one,
  # which is exactly the silent skew this variable exists to prevent. It is looked up
  # against the host's own zone database instead, and what was found is recorded.
  #
  # And it is looked up by NAME, not by path: a value carrying `..`, or starting with `/`
  # or `.`, is refused before the file test, because `../../../../etc/passwd` names a real
  # file and would otherwise have been recorded as a configured zone. No zone is spelled
  # that way, nothing is disclosed either way (`date` ignores a file that is not a zone
  # file), and the refusal keeps the sentence in docs/decisions.md true — the zone is
  # CHECKED against the host's zone database rather than trusted. Residual, stated: a
  # symlink inside that database pointing out of it would still pass, which is not a shape
  # an operator's env file can create.
  raw="$(sanitised "$(env_value HASHI_BACKUP_TZ)")"
  local zonedir="${TZDIR:-/usr/share/zoneinfo}"
  local named="yes"
  case "${raw}" in /*|.*|*/../*|*/..) named="no" ;; esac
  if [ -z "${raw}" ]; then
    # No zone configured is not a place; it is the absence of one, and the host's own
    # clock is the only remaining answer. Recorded as `unset` so the panel can say so —
    # no country is defaulted to here, ever.
    ZONE="UTC"; ZONE_SOURCE="unset"
  elif [ "${named}" = "no" ]; then
    # Recorded as `unknown`, the same as any other value the database does not have: it is
    # the same fact and the same sentence for the operator, and a state nobody added is a
    # state M28.6 cannot get wrong.
    ZONE="UTC"; ZONE_SOURCE="unknown"
  elif [ ! -d "${zonedir}" ]; then
    ZONE="UTC"; ZONE_SOURCE="no-zone-database"
  elif [ -f "${zonedir}/${raw}" ]; then
    ZONE="${raw}"; ZONE_SOURCE="configured"
  else
    ZONE="UTC"; ZONE_SOURCE="unknown"
  fi

  # Whether a successful run means the artifact also left the machine. Derived from the
  # exit code plus this flag rather than from reading the script's output: 0 with the
  # upload on already means "written AND sent" (a send that failed is 3), so the two
  # together are the whole answer and no message has to be parsed.
  raw="$(sanitised "$(env_value HASHI_BACKUP_ENABLED)")"
  [ "${raw}" = "1" ] && OFFSITE="yes" || OFFSITE="no"
}

zoned() { TZ="${ZONE}" date "$@"; }

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# The date whose backup is owed at this instant. Before the appointed time, the day that
# is owed is still yesterday's — which is what makes "the box was down at 04:00" work:
# it comes back at 10:00, the owed date has rolled over, and a run is due immediately.
due_date() {
  local now_hm
  now_hm="$(zoned +%H:%M)"
  if [[ "${now_hm}" < "${AT}" ]]; then zoned -d yesterday +%F; else zoned +%F; fi
}

# --- the record -------------------------------------------------------------------------

# One field of the record. Written one key per line precisely so this can be a line-wise
# read with no JSON parser on a host that has none.
field() {
  [ -f "${STATE_FILE}" ] || return 0
  sed -n "s/^[[:space:]]*\"$1\": *\"\{0,1\}\([^\",]*\)\"\{0,1\},\{0,1\}$/\1/p" "${STATE_FILE}" \
    | head -n 1
}

missed_dates() {
  [ -f "${STATE_FILE}" ] || return 0
  grep '"missed_dates"' "${STATE_FILE}" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' || true
}

json_entry() {
  # A nested object, or `null` when that thing has never happened. `null` and not an empty
  # object: "no backup has ever succeeded here" is a different statement from "one
  # succeeded and we lost the details", and a restore is planned off the difference.
  local at="$1" due="$2" code="$3" outcome="$4"
  if [ -z "${at}" ]; then printf 'null'; return; fi
  printf '{ "at": "%s", "due_date": "%s", "exit_code": %s, "outcome": "%s" }' \
    "${at}" "${due}" "${code}" "${outcome}"
}

write_state() {
  mkdir -p "${STATE_DIR}"
  local dates="" first=1 date
  for date in ${MISSED_LIST}; do
    [ ${first} -eq 1 ] && first=0 || dates="${dates}, "
    dates="${dates}\"${date}\""
  done

  local tmp="${STATE_FILE}.partial"
  cat > "${tmp}" <<JSON
{
  "schema": ${SCHEMA},
  "written_at": "$(now_utc)",
  "at": "${AT}",
  "at_source": "${AT_SOURCE}",
  "zone": "${ZONE}",
  "zone_source": "${ZONE_SOURCE}",
  "offsite": "${OFFSITE}",
  "due_date": "${STATE_DUE}",
  "attempts": ${STATE_ATTEMPTS},
  "retry_not_before": "${STATE_RETRY_AT}",
  "last_attempt": $(json_entry "${LAST_AT}" "${LAST_DUE}" "${LAST_CODE}" "${LAST_OUTCOME}"),
  "last_success": $(json_entry "${OK_AT}" "${OK_DUE}" "${OK_CODE}" "${OK_OUTCOME}"),
  "last_failure": $(json_entry "${BAD_AT}" "${BAD_DUE}" "${BAD_CODE}" "${BAD_OUTCOME}"),
  "missed_dates": [${dates}],
  "missed_total": ${MISSED_TOTAL}
}
JSON
  # World-readable on purpose, and it carries nothing that would matter if it were: the
  # control container reads it as an unprivileged user through a read-only mount, which is
  # how the panel answers "when did a backup last succeed" without a credential that could
  # look in the bucket.
  chmod 644 "${tmp}"
  mv "${tmp}" "${STATE_FILE}"
}

STATE_DUE=""; STATE_ATTEMPTS=0; STATE_RETRY_AT=""
LAST_AT=""; LAST_DUE=""; LAST_CODE=0; LAST_OUTCOME=""
OK_AT=""; OK_DUE=""; OK_CODE=0; OK_OUTCOME=""
BAD_AT=""; BAD_DUE=""; BAD_CODE=0; BAD_OUTCOME=""
MISSED_LIST=""; MISSED_TOTAL=0

# The two numbers that come back OUT of the record and then go into arithmetic. `$(( ))`
# reads a leading zero as octal and dies on `08`, so anything that has been on a disk —
# where a hand edit, a half-written file or a future writer can put one — is forced to
# base 10 before it is counted with. The same trap as HASHI_BACKUP_AT's hour, one file over.
as_number() {
  local raw="${1//[^0-9]/}"
  [ -n "${raw}" ] || { printf '0'; return; }
  printf '%s' "$((10#${raw}))"
}

read_state() {
  [ -f "${STATE_FILE}" ] || return 0
  STATE_DUE="$(field due_date)"
  STATE_ATTEMPTS="$(as_number "$(field attempts)")"
  STATE_RETRY_AT="$(field retry_not_before)"
  MISSED_LIST="$(missed_dates | tr '\n' ' ')"
  MISSED_TOTAL="$(as_number "$(field missed_total)")"
  # The three nested objects, read off their single lines.
  local line
  for line in last_attempt last_success last_failure; do
    local raw at due code outcome
    raw="$(sed -n "s/^[[:space:]]*\"${line}\": \(.*\),\{0,1\}$/\1/p" "${STATE_FILE}" | head -n 1)"
    [ -n "${raw}" ] && [ "${raw}" != "null," ] && [ "${raw}" != "null" ] || continue
    at="$(printf '%s' "${raw}" | sed -n 's/.*"at": "\([^"]*\)".*/\1/p')"
    due="$(printf '%s' "${raw}" | sed -n 's/.*"due_date": "\([^"]*\)".*/\1/p')"
    code="$(printf '%s' "${raw}" | sed -n 's/.*"exit_code": \([0-9]*\).*/\1/p')"
    outcome="$(printf '%s' "${raw}" | sed -n 's/.*"outcome": "\([^"]*\)".*/\1/p')"
    case "${line}" in
      last_attempt) LAST_AT="${at}"; LAST_DUE="${due}"; LAST_CODE="$(as_number "${code}")"; LAST_OUTCOME="${outcome}" ;;
      last_success) OK_AT="${at}"; OK_DUE="${due}"; OK_CODE="$(as_number "${code}")"; OK_OUTCOME="${outcome}" ;;
      last_failure) BAD_AT="${at}"; BAD_DUE="${due}"; BAD_CODE="$(as_number "${code}")"; BAD_OUTCOME="${outcome}" ;;
    esac
  done
}

# The exit-code contract of scripts/backup.sh, turned into one word the panel can show.
# It is the contract that is being read here, not a message: 0 with the upload on can only
# mean the store accepted it, because a send that failed is 3.
outcome_for() {
  case "$1" in
    0) [ "${OFFSITE}" = "yes" ] && echo "offsite" || echo "on-this-host-only" ;;
    3) echo "not-sent" ;;
    1) echo "no-artifact" ;;
    *) echo "refused" ;;
  esac
}

# --- deciding ---------------------------------------------------------------------------

ACTION=""; REASON=""; DUE=""

decide() {
  DUE="$(due_date)"
  if [ -z "${STATE_DUE}" ]; then
    # Nothing has ever run here. A control plane with no backup at all should not wait
    # until tomorrow's 04:00 to get its first one — and taking it at once is also what
    # makes an operator find out that the schedule works within a quarter of an hour of
    # installing it, rather than the morning after.
    ACTION="run"; REASON="no backup has ever been recorded on this host"
  elif [[ "${STATE_DUE}" < "${DUE}" ]]; then
    ACTION="run"; REASON="the backup for ${DUE} has not been taken"
  elif [[ "${DUE}" < "${STATE_DUE}" ]]; then
    # The record is ahead of the clock: the host's time moved backwards, or the zone was
    # changed westward. Not an error and not a reason to dump again.
    ACTION="wait"; REASON="the record is for ${STATE_DUE}, which is ahead of this clock"
  elif [ "${LAST_CODE}" = "0" ]; then
    ACTION="wait"; REASON="the backup for ${DUE} was taken"
  elif [ "${LAST_CODE}" = "3" ]; then
    # The artifact exists and did not leave the machine. Dumping again would write a
    # second copy of the same database and never fix the reason; the remedy is named in
    # the run's own output and is `make backup-upload FROM=<path>`.
    ACTION="wait"; REASON="the artifact for ${DUE} is on this host and has not been sent"
  elif [ "${STATE_ATTEMPTS}" -ge "${MAX_ATTEMPTS}" ]; then
    ACTION="wait"; REASON="the backup for ${DUE} failed ${STATE_ATTEMPTS} times; waiting for tomorrow"
  elif [ -n "${STATE_RETRY_AT}" ] && [[ "$(now_utc)" < "${STATE_RETRY_AT}" ]]; then
    ACTION="wait"; REASON="the backup for ${DUE} failed; the next attempt is not before ${STATE_RETRY_AT}"
  else
    ACTION="run"; REASON="the backup for ${DUE} failed and is being retried"
  fi
}

# Every whole day between the last due date accounted for and this one. Not backups that
# will be taken — they cannot be, a dump is a copy of the database as it is now and five
# runs today would be five copies of today wearing five different dates. They are the days
# that HAVE NO BACKUP, recorded so that M28.6 can say which ones, and so that the answer
# survives the next successful run.
MISSED_NEW=""

find_missed() {
  local from="$1" to="$2" day scanned=0
  MISSED_NEW=""
  [ -n "${from}" ] || return 0
  day="$(zoned -d "${from} + 1 day" +%F)"
  while [[ "${day}" < "${to}" ]]; do
    MISSED_NEW="${MISSED_NEW}${MISSED_NEW:+ }${day}"
    scanned=$((scanned + 1))
    [ "${scanned}" -ge "${MISSED_SCAN_LIMIT}" ] && break
    day="$(zoned -d "${day} + 1 day" +%F)"
  done
}

record_missed() {
  find_missed "$1" "$2"
  [ -n "${MISSED_NEW}" ] || return 0
  local day
  for day in ${MISSED_NEW}; do
    MISSED_LIST="${MISSED_LIST} ${day}"
    MISSED_TOTAL=$((MISSED_TOTAL + 1))
  done
  # Keep the most recent by date; the count above keeps the rest honest.
  #
  # NEWEST FIRST, and the sort is the whole of it (M28.12). Both readers label the first
  # few of these "most recent", and until now the writer appended them in the order the
  # walk found them — oldest first — so during a live gap the label pointed six weeks
  # back. The panel sorts what it reads and keeps doing so (M28.11: the file is on a disk
  # where a hand edit goes, so no reader may take the order on trust); this is the same
  # invariant established at the source, so the two readers stop disagreeing about a file
  # neither of them wrote badly. These are YYYY-MM-DD, so sorting them as text is sorting
  # them as dates, and `head` then keeps the recent end rather than the ancient one.
  MISSED_LIST="$(printf '%s\n' ${MISSED_LIST} | sort -r | head -n ${MISSED_KEPT} | tr '\n' ' ')"
}

# --- running ----------------------------------------------------------------------------

# A schedule that cannot write its record must SAY SO, not shrug. The directory is bind
# mounted read-only into the control container, so the docker daemon will have created it —
# as root — if a stack came up before anything else made it; every tick after that would
# then fail to record, on a host where the backups themselves work. That is the silent
# shape this whole script exists to refuse, so it is a loud exit rather than a skipped run.
ensure_state_dir() {
  mkdir -p "${STATE_DIR}" 2>/dev/null || true
  [ -d "${STATE_DIR}" ] && [ -w "${STATE_DIR}" ] && return 0
  cat >&2 <<MSG
cannot write the backup record at ${STATE_DIR}.

Nothing was dumped. If the directory belongs to root, the docker daemon created it when
the stack first came up — the control container reads it read-only — and it has to belong
to the account that runs the schedule:

  sudo chown -R "\$(id -un)" ${STATE_DIR}

Set HASHI_BACKUP_STATE_DIR to keep the record somewhere else.
MSG
  exit 1
}

take_lock() {
  if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    local age=0
    if [ -d "${LOCK_DIR}" ]; then
      age=$(( $(date +%s) - $(date -r "${LOCK_DIR}" +%s 2>/dev/null || date +%s) ))
    fi
    if [ "${age}" -lt "${STALE_LOCK_SECONDS}" ]; then
      return 1
    fi
    # A run that was killed leaves this behind, and a lock nobody ever breaks is a
    # schedule that stops for ever without saying so.
    echo "breaking a backup lock left behind ${age}s ago at ${LOCK_DIR}" >&2
    rm -rf "${LOCK_DIR}"
    mkdir "${LOCK_DIR}" 2>/dev/null || return 1
  fi
  trap 'rm -rf "${LOCK_DIR}"' EXIT
  return 0
}

# Run the backup, record what it did, and exit with the code scripts/backup.sh gave —
# unchanged, because 0/1/3 is a contract M28.6 keys the panel's states on.
run_backup() {
  local trigger="$1" quiet="$2" status=0 output
  local when
  when="$(now_utc)"

  if [ "${quiet}" = "quiet" ]; then
    # A tick that worked prints nothing: cron mails whatever a job writes, and a daily
    # mail that is almost always the same is a daily mail nobody opens. The record is the
    # channel that does not depend on anybody reading mail. A tick that FAILED prints
    # everything, so the one mail that matters still arrives.
    output="$("${BACKUP}" dump 2>&1)" || status=$?
    [ "${status}" -eq 0 ] || printf '%s\n' "${output}" >&2
  else
    "${BACKUP}" dump || status=$?
  fi

  local outcome
  outcome="$(outcome_for "${status}")"

  if [ "${DUE}" = "${STATE_DUE}" ]; then
    STATE_ATTEMPTS=$((STATE_ATTEMPTS + 1))
  else
    record_missed "${STATE_DUE}" "${DUE}"
    STATE_ATTEMPTS=1
  fi
  STATE_DUE="${DUE}"

  LAST_AT="${when}"; LAST_DUE="${DUE}"; LAST_CODE="${status}"; LAST_OUTCOME="${outcome}"
  if [ "${status}" -eq 0 ]; then
    OK_AT="${when}"; OK_DUE="${DUE}"; OK_CODE=0; OK_OUTCOME="${outcome}"
    STATE_RETRY_AT=""
  else
    BAD_AT="${when}"; BAD_DUE="${DUE}"; BAD_CODE="${status}"; BAD_OUTCOME="${outcome}"
    # Only "there is no artifact at all" is worth trying again today: it is the failure a
    # stack that had not finished booting produces, and it costs nothing to repeat.
    if [ "${status}" -eq 1 ]; then
      STATE_RETRY_AT="$(date -u -d "+${RETRY_AFTER_SECONDS} seconds" +%Y-%m-%dT%H:%M:%SZ)"
    else
      STATE_RETRY_AT=""
    fi
  fi

  write_state
  return "${status}"
}

# --- the four verbs ----------------------------------------------------------------------

command_tick() {
  resolve_schedule
  read_state
  decide
  [ "${ACTION}" = "wait" ] && return 0
  ensure_state_dir
  take_lock || return 0
  local status=0
  run_backup schedule quiet || status=$?
  return "${status}"
}

command_now() {
  resolve_schedule
  read_state
  DUE="$(due_date)"
  ensure_state_dir
  take_lock || {
    echo "another backup is running (${LOCK_DIR}); nothing was dumped." >&2
    return 1
  }
  local status=0
  # Loud, and the output is scripts/backup.sh's own: `make backup` still looks and reads
  # exactly as it did. What is new is that a backup taken by hand now counts as the day's
  # backup, so the panel cannot report a host as un-backed-up an hour after its operator
  # backed it up, and the schedule does not take a second one at 04:00 for a day that
  # already has one.
  run_backup manual loud || status=$?
  return "${status}"
}

command_due() {
  resolve_schedule
  read_state
  decide
  # The days this run would write down as having had no backup. Shown here, where nothing
  # is changed, so an operator coming back to a box that was off can see what the next tick
  # is about to record before it records it.
  find_missed "${STATE_DUE}" "${DUE}"
  printf 'action=%s due=%s at=%s at_source=%s zone=%s zone_source=%s offsite=%s missed=%s state=%s\n' \
    "${ACTION}" "${DUE}" "${AT}" "${AT_SOURCE}" "${ZONE}" "${ZONE_SOURCE}" "${OFFSITE}" \
    "$(printf '%s' "${MISSED_NEW:-none}" | tr ' ' ',')" "${STATE_FILE}"
  printf '%s\n' "${REASON}"
}

# --- reading the record back, as strictly as the panel reads it -------------------------
#
# WHY THIS EXISTS AT ALL, because `status` used to have none of it and that was the
# finding (M28.12). A record with `schema: 99`, or a thousand-character `outcome`, or a
# `last_success` that is not a run, was printed VERBATIM as fact — "last success: never,
# last attempt: never", a confident schedule line, exit 0 — which is byte-for-byte what a
# machine that has simply never taken a backup prints. Meanwhile the panel, reading the
# same file, called it unreadable and assumed nothing from it, and then sent the operator
# here to find out more. The two channels have to agree about a damaged file or the
# weaker one teaches the operator to disbelieve the other.
#
# The rules are control/app/services/backups.py's, deliberately, key for key: an unknown
# `schema`, a missing key this reads, a timestamp that is not one, a number that is not
# one, a missed date that is not a date, a nested entry that is not a run, or any string
# over LONGEST_VALUE. And deliberately NOT unreadable, in both readers: an `outcome` this
# version has no meaning for (it is named verbatim instead) and an `offsite` word it does
# not know (it collapses into neither answer).
LONGEST_VALUE=200
# The two shapes every date in the record has. Checked rather than trusted because these
# are printed on a terminal and because a file on a disk is where a hand edit goes.
A_TIMESTAMP='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
A_DATE='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'

# The raw text after `"key":`, trailing comma removed. Empty when the key is absent — the
# two are told apart with `has_key`, because "no such key" and "an empty value" are
# different faults and only one of them is this reader's business.
raw_field() {
  sed -n "s/^[[:space:]]*\"$1\"[[:space:]]*://p" "${STATE_FILE}" \
    | head -n 1 \
    | tr -d '\r' \
    | sed -e 's/^[[:space:]]*//' -e 's/,[[:space:]]*$//' -e 's/[[:space:]]*$//'
}

has_key() { grep -q "^[[:space:]]*\"$1\"[[:space:]]*:" "${STATE_FILE}"; }

# Anything out of the record that reaches the terminal goes through here first. The writer
# already restricts what it writes to [A-Za-z0-9_+:/.-]; a hand edit does not, and an
# escape sequence in a value is a record that rewrites the screen it is being read on. The
# panel has autoescaping for the same job; this is the terminal's half of it.
printable() { printf '%s' "$1" | tr -cd '[:print:]' | cut -c1-${LONGEST_VALUE}; }

# One `"key": "value"` string, or a reason it is not one. Everything the panel's ``_text``
# refuses is refused here: a missing key, and a value longer than it reads.
string_problem() {
  local raw
  has_key "$1" || { printf '%s' "$1"; return 0; }
  raw="$(raw_field "$1")"
  case "${raw}" in
    '"'*'"') ;;
    *) printf '%s' "$1"; return 0 ;;
  esac
  raw="${raw#\"}"; raw="${raw%\"}"
  [ "${#raw}" -le "${LONGEST_VALUE}" ] || printf '%s' "$1"
}

# One of the three nested entries: `null`, or a run with a timestamp, a whole exit code
# and an outcome. `null` and a run are both statements the record is entitled to make;
# "this line is not a run" is not, and it becomes the same refusal as a broken schema
# rather than being reported as a host that has never had a successful backup.
entry_problem() {
  local raw at code outcome
  has_key "$1" || { printf '%s' "$1"; return 0; }
  raw="$(raw_field "$1")"
  [ "${raw}" = "null" ] && return 0
  case "${raw}" in
    '{'*'}') ;;
    *) printf '%s' "$1"; return 0 ;;
  esac
  case "${raw}" in *'"outcome":'*) ;; *) printf '%s' "$1"; return 0 ;; esac
  at="$(printf '%s' "${raw}" | sed -n 's/.*"at": *"\([^"]*\)".*/\1/p')"
  code="$(printf '%s' "${raw}" | sed -n 's/.*"exit_code": *\(-\{0,1\}[0-9]\{1,9\}\).*/\1/p')"
  outcome="$(printf '%s' "${raw}" | sed -n 's/.*"outcome": *"\([^"]*\)".*/\1/p')"
  [[ "${at}" =~ ${A_TIMESTAMP} ]] || { printf '%s' "$1"; return 0; }
  [ -n "${code}" ] || { printf '%s' "$1"; return 0; }
  [ "${#outcome}" -le "${LONGEST_VALUE}" ] || printf '%s' "$1"
}

# Which key made this file unreadable, or nothing at all. A KEY NAME and never a value:
# the reason an operator needs is which field is wrong, and printing the field's contents
# back at them is how a record starts being a place things leak from.
record_problem() {
  local raw problem key day
  raw="$(raw_field schema)"
  [ "${raw}" = "${SCHEMA}" ] || { printf 'schema'; return 0; }

  for key in at at_source zone zone_source offsite; do
    problem="$(string_problem "${key}")"
    [ -z "${problem}" ] || { printf '%s' "${problem}"; return 0; }
  done

  for key in last_attempt last_success last_failure; do
    problem="$(entry_problem "${key}")"
    [ -z "${problem}" ] || { printf '%s' "${problem}"; return 0; }
  done

  has_key missed_total || { printf 'missed_total'; return 0; }
  raw="$(raw_field missed_total)"
  [[ "${raw}" =~ ^[0-9]{1,9}$ ]] || { printf 'missed_total'; return 0; }

  has_key missed_dates || { printf 'missed_dates'; return 0; }
  raw="$(raw_field missed_dates)"
  case "${raw}" in
    '['*']') ;;
    *) printf 'missed_dates'; return 0 ;;
  esac
  raw="${raw#[}"; raw="${raw%]}"
  for day in $(printf '%s' "${raw}" | tr -d '"' | tr ',' ' '); do
    [[ "${day}" =~ ${A_DATE} ]] || { printf 'missed_dates'; return 0; }
  done
}

# The three sentences the panel closes with, chosen the way the panel chooses them: by
# where the RECORD says this host sends, never by how a run went and never by this script
# reading the env file for it. Both channels answer the same question from the same field,
# so an operator who sees one and then the other is not told two different things.
#
# The middle one is the shipped default (HASHI_BACKUP_ENABLED=0). It is not the weaker
# sentence: the upload being off is a supported mode, the artifact is still written, and
# what this refuses is the inference the first one invites — a caveat about a bucket, on a
# host with no bucket, hands over the belief it was meant to take away.
backup_caveat() {
  case "$1" in
    yes)
      cat <<'MSG'
What this does NOT say: whether any of those artifacts is still in the bucket. The
credential on this host may only write, so it cannot look — nothing here has ever read
that store, and no test in this project asserts what it keeps. The only thing that proves
a backup is a restore: docs/deploy/runbook.md, under "Backups".
MSG
      ;;
    no)
      cat <<'MSG'
What this does NOT say: that this host is sending its backups anywhere. The record says
the upload is switched off on it (HASHI_BACKUP_ENABLED), so an artifact it takes is
written to the disk of that one machine and stays there — a copy that shares a disk with
the thing it is a copy of is not a backup of it, and neither of them survives losing the
machine. The only thing that proves a backup is a restore: docs/deploy/runbook.md, under
"Backups", which is also where turning the upload on is.
MSG
      ;;
    *)
      cat <<'MSG'
What this does NOT say: whether anything was sent anywhere. The record holds a word this
script has no meaning for where it says whether this host sends its backups to a store,
so nothing here claims an artifact reached one and nothing here claims none did. The only
thing that proves a backup is a restore: docs/deploy/runbook.md, under "Backups".
MSG
      ;;
  esac
}

command_status() {
  resolve_schedule
  if [ ! -f "${STATE_FILE}" ]; then
    cat >&2 <<MSG
No backup has ever been recorded on this host.

There is no record at ${STATE_FILE}, which means either that nothing has run yet or that
the schedule was never installed. Install it with \`make backup-schedule\`, or take one
now with \`make backup\`.
MSG
    return 1
  fi

  local problem
  problem="$(record_problem)"
  if [ -n "${problem}" ]; then
    cat >&2 <<MSG
There is a backup record on this host and this is not the file the schedule writes.

${STATE_FILE} could not be read: its "${problem}" is not what scripts/backup-run.sh
writes there. Either the file is damaged, or it was written by a newer version of that
script than this one. NOTHING HAS BEEN ASSUMED FROM IT — this is not telling you backups
are working and not telling you they are failing, and the panel says exactly that about
the same file, for the same reason.

What is in it is a history of runs and nothing else can tell you what it said, so move it
aside rather than deleting it if you want to look at it later. The next run rewrites it:
\`make backup\` takes one now, on a host that still has what a backup needs in the env
file — HASHI_BACKUP_AGE_RECIPIENT and the HASHI_BACKUP_S3_ block are in no backup by
design, so a machine rebuilt out of the backup history has to have them put back first.
MSG
    return 1
  fi

  read_state
  local sends
  sends="$(printable "$(field offsite)")"

  echo "Backups on this host, from ${STATE_FILE}:"
  echo
  # Named as coming from the env file, because it does: this line is what the schedule
  # would resolve if it ran right now, while everything under it is what the record says
  # happened. On a damaged or absent record the same line used to be printed with the same
  # confidence beside "last success: never", which reads as a fact about the backups.
  echo "  scheduled:    ${AT} ${ZONE} (${ZONE_SOURCE}), checked every 15 minutes"
  echo "                — from ${ENV_FILE} as it is now, not from this record"
  case "${sends}" in
    yes) echo "  sending:      offsite — the record says the upload is switched on" ;;
    no)  echo "  sending:      nowhere — the record says the upload is switched off" ;;
    *)   echo "  sending:      unknown — the record says \"${sends}\", which this script" \
              "has no meaning for" ;;
  esac
  # The one thing this channel can see and the panel cannot: the record says what was true
  # when it was written, and the env file says what the next run will do. Said only when
  # they differ, because that is a switch thrown between two runs rather than a fault.
  if { [ "${sends}" = "yes" ] || [ "${sends}" = "no" ]; } && [ "${sends}" != "${OFFSITE}" ]; then
    echo "                ${ENV_FILE} says the opposite now (HASHI_BACKUP_ENABLED), so it"
    echo "                was changed after that run and the next one goes the other way"
  fi
  echo "  last success: ${OK_AT:-never} ${OK_OUTCOME:+($(printable "${OK_OUTCOME}"))}"
  echo "  last attempt: ${LAST_AT:-never} ${LAST_OUTCOME:+($(printable "${LAST_OUTCOME}"), exit ${LAST_CODE})}"
  if [ -n "${BAD_AT}" ] && { [ -z "${OK_AT}" ] || [[ "${OK_AT}" < "${BAD_AT}" ]]; }; then
    echo "  FAILED SINCE THE LAST SUCCESS: ${BAD_AT} ($(printable "${BAD_OUTCOME}"), exit ${BAD_CODE})"
  fi
  # 3 is a state with its own remedy rather than a failure to retry, and until now it was
  # shown as a digit and nowhere as what it means. The artifact of that run is on this
  # machine: dumping again would write a second copy of the same database and never fix
  # the reason the store refused the first.
  if [ "${LAST_CODE}" = "3" ] || [ "${BAD_CODE}" = "3" ]; then
    echo "                exit 3 means the artifact WAS written and did NOT leave this"
    echo "                machine. Nothing needs dumping again — send that same file with"
    echo "                make backup-upload FROM=${REPO_ROOT}/backups/<the artifact>"
  fi
  if [ "${MISSED_TOTAL}" -gt 0 ]; then
    # Newest first. The writer sorts them that way now and so does the panel; this sorts
    # what it read as well, because the order of dates in a file on a disk is not a thing
    # any reader may take on trust — and the label says "most recent".
    echo "  days with no backup: ${MISSED_TOTAL} — most recent:" \
         "$(printf '%s\n' ${MISSED_LIST} | sort -r | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  fi
  echo
  backup_caveat "${sends}"
}

case "${1:-tick}" in
  tick)   command_tick ;;
  now)    command_now ;;
  due)    command_due ;;
  status) command_status ;;
  *)      usage ;;
esac
