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
#       `due` and `status` are the two that SPEAK ABOUT the record, and both of them refuse
#       it rather than repeat it when it is not the file this writes: exit 1, naming the key
#       that failed and never its contents. Both also say out loud when the record is dated
#       ahead of this host's clock, which is the state in which no backup is taken at all
#       and every age on the screen is worthless — `due` exits 1 for it too, because
#       `action=wait` at exit 0 is what a working schedule answers 95 ticks out of 96.
#       `tick` and `now` take backups and assert nothing to anybody, so neither refuses.
#
#       ALL FOUR READ THE RECORD THROUGH scripts/lib/backup-record.sh AND NOTHING ELSE
#       DOES (M28.18). One reader, one answer: either a refusal naming what made the file
#       unreadable, or a reading nothing was assumed into. A record this script cannot read
#       is NO RECORD — `tick` and `now` proceed as if the host had none and take a backup,
#       which is the fail-safe direction the owner settled on 2026-09-24 (docs/decisions.md);
#       `status` and `due` refuse it, and `due` now also says what the tick will do about it.
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

`due` and `status` exit 1 instead when the record is not the file this script writes, or
when it is dated ahead of this host's clock. Neither reads anything out of it in that case.
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

# THE RECORD IS READ BY scripts/lib/backup-record.sh AND BY NOTHING ELSE HERE (M28.18).
# Until this step this script held TWO readers of one file: a lenient one behind `tick` and
# `now` which pulled fields out of whatever was at the path without checking any of them,
# and a strict one behind `status` and `due` which refused the same file by name. So a
# damaged `last_attempt` made `tick` conclude the day's backup had been taken, out of a file
# it could not parse and about which the panel said nothing could be assumed — the channel
# that actually takes backups was the one that believed it. The library says why the
# collapse is a library rather than a tidier function, what a refusal now means to each
# verb, and which neighbouring state it deliberately does NOT close.
#
# shellcheck source=lib/backup-record.sh
. "${REPO_ROOT}/scripts/lib/backup-record.sh"

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
  "schema": ${RECORD_SCHEMA},
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

# The record, read ONCE and adopted as this script's working state — or refused, in which
# case nothing is adopted and the working state stays the one a host with no record has.
#
# THE ADOPTION IS THE WHOLE OF THE OWNER'S DECISION OF 2026-09-24 (docs/decisions.md): a
# record this cannot read is no record. `tick` and `now` call this and carry on, so they
# take a backup rather than concluding out of an unparseable file that the day's was taken;
# `status` and `due` call it and refuse when it does. One answer, four verbs — which is the
# thing that was not true before, and the reason a damaged key could stop this host's
# backups while the panel had a banner up about the same file.
#
# NOT COVERED BY THIS, still true, and written here because this is where somebody will
# look for it: a record dated ahead of the clock is VALID, so it arrives as a reading and
# `decide` answers `wait` — exit 0, in silence, until the calendar catches up. See the
# library's header and docs/deploy/runbook.md; it is an owner decision in its own step.
#
# `READING_*` is what the library is prepared to be believed about; the names below are this
# script's own working state, which `run_backup` then MOVES ON and `write_state` writes out.
# The copy is what keeps the two apart: nothing writes back into a reading.
read_the_record() {
  backup_record_read "${STATE_FILE}" || return 1
  STATE_DUE="${READING_DUE_DATE}"
  STATE_ATTEMPTS="${READING_ATTEMPTS}"
  STATE_RETRY_AT="${READING_RETRY_AT}"
  MISSED_LIST="${READING_MISSED_DATES}"
  MISSED_TOTAL="${READING_MISSED_TOTAL}"
  LAST_AT="${READING_LAST_AT}"; LAST_DUE="${READING_LAST_DUE}"
  LAST_CODE="${READING_LAST_CODE}"; LAST_OUTCOME="${READING_LAST_OUTCOME}"
  OK_AT="${READING_OK_AT}"; OK_DUE="${READING_OK_DUE}"
  OK_CODE="${READING_OK_CODE}"; OK_OUTCOME="${READING_OK_OUTCOME}"
  BAD_AT="${READING_BAD_AT}"; BAD_DUE="${READING_BAD_DUE}"
  BAD_CODE="${READING_BAD_CODE}"; BAD_OUTCOME="${READING_BAD_OUTCOME}"
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

# Whether the failure in the record is the more recent of the two — the panel's
# `failed_since`, in one place rather than written out at each of the two lines that ask it.
# A record keeps `last_failure` for ever, so "there is a failure in here" is not the same
# statement as "this host is failing", and everything an operator is told to DO belongs to
# the second one.
failed_since_the_last_success() {
  [ -n "${BAD_AT}" ] || return 1
  [ -n "${OK_AT}" ] || return 0
  [[ "${OK_AT}" < "${BAD_AT}" ]]
}

# --- a clock that ran ahead ---------------------------------------------------------------
#
# The state nothing said out loud until M28.15, and the one nobody gets out of by waiting.
# A host whose clock jumped forward writes a record dated next March; the clock is then put
# back; and from that moment `decide` answers "the record is for a day ahead of this clock"
# — WAIT — at every tick, for as many months as it takes the calendar to catch up. No
# backup is taken, and the two surfaces an operator reaches said nothing about it: `status`
# printed "last success: 2027-03-01 (ok)" and `due` printed `action=wait`, exit 0.
#
# The panel already goes loud on the same file (M28.11, M28.14). These are the other two
# channels saying the same thing about the same record.
#
# AND `tick` IS STILL SILENT ABOUT IT, which is the state of this as of M28.18. The record
# is valid — one reader, one answer, and every channel agrees about the file — so it comes
# back as a reading and `decide` says WAIT: exit 0, no output, no backup, until the
# calendar catches up. M28.18 collapsed the two READERS and deliberately did not decide
# this, because what the schedule should do with a record from the future is a choice
# between two shapes that already exist here — refusing loudly the way a path that is not a
# file is refused, or taking the backup — and that is the owner's, in its own step.

# One minute, exactly as control/app/services/backups.py::CLOCK_AHEAD_GRACE. A second or
# two between two clocks is ordinary and is not what this is about; what this catches is a
# clock that MOVED, which is minutes to years.
CLOCK_AHEAD_GRACE_SECONDS=60

# Whether one moment out of the record is dated after the moment it is being read at.
# Empty — a thing that never happened — is not ahead of anything.
ahead_of_now() {
  local when="$1" moment
  [ -n "${when}" ] || return 1
  # The record has been validated against A_TIMESTAMP before anything calls this, so `date`
  # is being handed a shape it can read; a value it cannot is "not ahead" rather than a
  # crash, because this is on the path that draws a screen for an operator.
  moment="$(date -u -d "${when}" +%s 2>/dev/null)" || return 1
  [ -n "${moment}" ] || return 1
  # `-gt` compares as decimal without $(( ))'s octal reading, which is what the rest of this
  # script needs `10#` for — and both sides here came from `date`, not off the disk.
  [ "${moment}" -gt "$(( $(date -u +%s) + CLOCK_AHEAD_GRACE_SECONDS ))" ]
}

CLOCK_AHEAD=""

# Set once, from the record that has already been read. Both the run timestamps and the due
# date are asked, because they fail in different orders: a clock put back leaves timestamps
# ahead of now, and a due date ahead of today's is what actually stops the schedule.
note_clock() {
  CLOCK_AHEAD=""
  if ahead_of_now "${LAST_AT}" || ahead_of_now "${OK_AT}" || ahead_of_now "${BAD_AT}"; then
    CLOCK_AHEAD="yes"
  elif [ -n "${STATE_DUE}" ] && [[ "$(due_date)" < "${STATE_DUE}" ]]; then
    CLOCK_AHEAD="yes"
  fi
}

# Said in the same words on both verbs, so an operator who reads one and then the other is
# not told two different things about one host. Quoted heredoc: it names a command.
clock_ahead_warning() {
  cat <<'MSG'
THIS RECORD IS DATED AHEAD OF THIS HOST'S CLOCK.

Something in it claims to have happened after the moment it was just read, so no age here
can be believed: a backup taken weeks ago reads as one taken this morning. It does not
clear by waiting — the schedule asks whether the day's backup has been taken, this record
answers for a day that has not arrived yet, and NOTHING IS BACKED UP AT ALL until this
host's calendar reaches the date in it. Fix the clock on this host; the panel says the
same thing about the same file. `make backup` takes one now whatever the record says.
MSG
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
  # The RECORD ITSELF has to be a file, and this is the only place that can find out before
  # a database is dumped for nothing. `mv` onto a directory does not fail — it moves
  # last-run.json.partial INSIDE it — so a tick took the backup, wrote no record, and
  # exited 0, every fifteen minutes, on a host whose backups were working. A schedule that
  # reports success and leaves nothing behind is the silent skip this whole script refuses,
  # so it is a loud exit here rather than a run nobody can see the result of (M28.17).
  #
  # Refused, never repaired: nothing here deletes or moves what an operator put on their
  # own disk. The reading verbs refuse the same shape by the same name — literally the same
  # name now: this is the `shape` fault the one reader already reported, not a second test
  # of the same path that could come to disagree with it.
  if [ "${RECORD_FAULT}" = "shape" ]; then
    cat >&2 <<MSG
cannot write the backup record at ${STATE_FILE}.

Nothing was dumped. There is ${RECORD_SHAPE} at that path and the record is
a file, so a run would leave ${STATE_FILE}.partial inside it and record nothing at all —
the schedule would go on reporting success and this host would go on having no record of
a backup. Move it aside; the next run writes the record in its place.

\`make backup-status\` and the panel both refuse to read that path for the same reason.
MSG
    exit 1
  fi
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
  # A REFUSAL IS AN EMPTY READING HERE, and the tick then takes a backup — the owner's
  # decision of 2026-09-24, in docs/decisions.md. A reader that cannot parse the file must
  # not conclude the day's backup was taken, and the only other answer, refusing to run,
  # stops backups on the strength of a file the product itself cannot understand. The cost
  # is accepted knowingly: a damaged record triggers a dump rather than suppressing one, so
  # a host in that state takes at most one extra backup per due period until the record is
  # rewritten — which this same run does.
  #
  # The one refusal that does NOT end in a backup is `shape`, and not because this decides
  # differently about it: `ensure_state_dir` below refuses a path that is not a file before
  # anything is dumped, since `mv` onto a directory would deposit the half-written record
  # INSIDE it and record nothing at all (M28.17).
  read_the_record || true
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
  # As `tick`: a record this cannot read is no record, so a hand-taken backup goes ahead
  # and the record it writes replaces the one nothing could read. What that costs is stated
  # rather than hidden — the history in the unreadable file is not carried forward, because
  # carrying it forward means asserting values the validator refused, which is the laundering
  # M28.15 took out of the over-large case.
  read_the_record || true
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

  # THE RECORD IS CHECKED BEFORE A WORD OF IT IS REPEATED — M28.15, and it is round 1's
  # discipline arriving at the one verb that missed it. `status` was taught to refuse a
  # record it cannot read; this went on printing `offsite=no missed=none` and "no backup
  # has ever been recorded on this host" at exit 0, which is byte-for-byte what a host that
  # has genuinely never run one prints. Those are assertions out of a file this script
  # could not parse, and they are exactly the sentences an operator would act on.
  #
  # Since M28.18 it is the SAME check `tick` makes, which is what lets the refusal end by
  # saying what the next tick will do instead of saying that it cannot know.
  if ! read_the_record; then
    refuse_damaged_record "${RECORD_FAULT}"
    echo >&2
    what_a_tick_would_do >&2
    return 1
  fi

  decide
  note_clock
  # The days this run would write down as having had no backup. Shown here, where nothing
  # is changed, so an operator coming back to a box that was off can see what the next tick
  # is about to record before it records it.
  find_missed "${STATE_DUE}" "${DUE}"
  # `clock=` is the machine-readable half of the warning below, on the line every other
  # answer this verb gives is already on. `offsite=` is what the NEXT run will do, read from
  # the env file — which is where scripts/backup.sh now takes it from too, so the two no
  # longer disagree about a run neither of them has taken yet.
  local clock="ok"
  if [ -n "${CLOCK_AHEAD}" ]; then clock="ahead"; fi
  printf 'action=%s clock=%s due=%s at=%s at_source=%s zone=%s zone_source=%s offsite=%s missed=%s state=%s\n' \
    "${ACTION}" "${clock}" "${DUE}" "${AT}" "${AT_SOURCE}" \
    "${ZONE}" "${ZONE_SOURCE}" "${OFFSITE}" \
    "$(printf '%s' "${MISSED_NEW:-none}" | tr ' ' ',')" "${STATE_FILE}"
  printf '%s\n' "${REASON}"
  # Exit 1, and the reason it is not 0: `action=wait` at exit 0 is the answer a working
  # schedule gives 95 ticks out of 96, and this host is not taking backups at all. Anything
  # watching this verb for a non-zero would have watched that state go by for months.
  if [ -n "${CLOCK_AHEAD}" ]; then
    echo >&2
    clock_ahead_warning >&2
    return 1
  fi
}

# --- putting a value out of the record on a terminal ------------------------------------

# Anything out of the record that reaches the terminal goes through here first. The writer
# already restricts what it writes to [A-Za-z0-9_+:/.-]; a hand edit does not, and an
# escape sequence in a value is a record that rewrites the screen it is being read on. The
# panel has autoescaping for the same job; this is the terminal's half of it. The length it
# cuts at is the library's own `LONGEST_VALUE`, which is also the length over which a value
# makes the whole record unreadable — so this only ever trims what the validator let past.
printable() { printf '%s' "$1" | tr -cd '[:print:]' | cut -c1-${LONGEST_VALUE}; }

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

# Whether anything on this host actually runs a backup — ASKED, never assumed.
#
# WHY THIS IS NOT THE PANEL'S ANSWER. M28.14 forbade the panel from saying a schedule
# exists, and rightly: it renders from the one record it reads, does no I/O, and the record
# is written by a RUN, so it cannot attest that a SCHEDULE exists. This script is on the
# host. It may look, and until M28.15 it did not — `make backup-status` printed
# "scheduled: 04:00 <zone> (configured), checked every 15 minutes" on a host with no cron
# entry at all, and printed the same line unchanged the minute after `make backup-unschedule`
# answered "removed. Nothing runs a backup on this host now." Three commands in one family
# and one of them contradicting another about the same host in the same minute.
#
# The exit code IS the answer, and there are three of them: 0 installed, 1 this account's
# crontab has no entry, 3 no crontab on this host to tell from — which is the supported
# systemd-timer shape and must not be reported as "nothing is backing this up".
SCHEDULER="${REPO_ROOT}/scripts/backup-schedule.sh"

schedule_answer() {
  local status=0
  # Output discarded on purpose: what `show` prints is the crontab block, and this is a
  # yes/no/cannot-tell question whose answer is the exit code. Nothing of another file
  # reaches this screen through here.
  "${SCHEDULER}" show >/dev/null 2>&1 || status=$?
  printf '%s' "${status}"
}

# One refusal, printed by both of the verbs that read the record back — `status` since
# M28.12 and `due` since M28.15. One function rather than two copies for the reason the
# whole milestone keeps finding: independently written sentences about one file are how two
# channels come to say different things about it.
#
# THREE FAULTS, THREE SENTENCES, one function. What varies is the paragraph saying which
# fact about the file made it unreadable, and what to do with the file; the opening, the
# "nothing has been assumed" clause and the closing advice are shared, so `status` and `due`
# still cannot drift about any of the three. The size and shape faults got their own
# sentences in M28.17: both were forced through the key sentence and came out as
# `its "size" is not what scripts/backup-run.sh writes there`, naming a key that does not
# exist in a record — and every other argument this function takes (schema, missed_dates,
# last_success) IS a real key, so an operator went looking for that one and found nothing.
refuse_damaged_record() {
  local fault keep
  case "$1" in
    shape)
      # The size is not printed here and there is nothing to print: this never opened.
      # Both facts — the shape that is there and, below, how big the file was — were
      # gathered by `backup_record_read` during the read and are still here, because that
      # runs in this shell. Until M28.18 the reader ran inside `$( )` and this branch had to
      # go and measure the file a second time to be able to say anything about it.
      fault="${STATE_FILE} could not be read: there is ${RECORD_SHAPE} at
that path, and the record is a file. Nothing in it has been read and nothing of it could
be — the panel refuses the same path for the same reason, so both channels call this a
record that is there and is not legible rather than a host that has never run one."
      keep="Move it aside rather than deleting it: nothing here knows what put it there, and while it
is in the way nothing on this host can write the record either — a scheduled run leaves
its half-written file INSIDE it and records nothing, every tick, silently."
      ;;
    size)
      fault="${STATE_FILE} could not be read: it is ${RECORD_BYTES} bytes, and
this reads at most ${MOST_OF_A_RECORD}. Not one byte of it has been read, so nothing here is a
statement about what is in it. The record this script writes is well under a kilobyte,
so a file that size is a wrong path — a mount pointing somewhere else, a log — rather
than a long history, and the panel refuses it at the same number."
      keep="Move it aside rather than deleting it if you want to look at what is in it: the
next scheduled run writes a new record at that path and what is there now is gone."
      ;;
    *)
      fault="${STATE_FILE} could not be read: its \"$1\" is not what scripts/backup-run.sh
writes there. Either the file is damaged, or it was written by a newer version of that
script than this one."
      keep="What is in it is a history of runs and nothing else can tell you what it said,
so move it aside rather than deleting it if you want to look at it later. The next
scheduled run writes a new record at that path."
      ;;
  esac
  cat >&2 <<MSG
There is a backup record on this host and this is not the file the schedule writes.

${fault}

NOTHING HAS BEEN ASSUMED FROM IT — this is not telling you backups are working and not
telling you they are failing, and the panel says exactly that about the same file, for the
same reason.

${keep}

\`make backup\` takes one now, on a host that still has what a backup needs in the env
file — HASHI_BACKUP_AGE_RECIPIENT and the HASHI_BACKUP_S3_ block are in no backup by
design, so a machine rebuilt out of the backup history has to have them put back first.
MSG
}

# What the NEXT TICK will do with the record `due` has just refused — the sentence the
# collapse in M28.18 made possible, and the one this verb could not say before.
#
# It used to end with "Nothing is said above about what the next tick would do, because that
# answer is read out of this same file", which was true while there were two readers: the
# tick read leniently and this verb had no way of knowing what the lenient read would make
# of the bytes. There is one reader now, so this verb is holding exactly the reading the
# tick will hold.
#
# ASKED, NOT RESTATED. `decide` below is the same function `tick` calls, run over the same
# empty reading `tick` will have — writing out "it will take a backup" in prose here would
# be a second copy of the tick's rule, which is this milestone's own defect in a new
# costume. The one refusal that is not `decide`'s to answer is `shape`, because `tick` never
# reaches `decide`'s verdict on it: `ensure_state_dir` refuses a path that is not a file
# before anything is dumped, and promising a backup there would be a promise nothing keeps.
#
# THE VERDICT ONLY, NEVER `decide`'s REASON. On an empty reading that reason is the words
# "no backup has ever been recorded on this host" — which is byte-for-byte what a genuinely
# fresh host is told, and printing it under a refusal would put the one sentence M28.15
# took off this verb back on it. `action=` is the answer; the sentence beside it is about
# THIS file and is written here.
what_a_tick_would_do() {
  if [ "${RECORD_FAULT}" = "shape" ]; then
    cat <<MSG
The next scheduled run will not take a backup either. It refuses this path before it dumps
anything, for the reason above — a record cannot be written onto something that is not a
file — and it says so every fifteen minutes until the path is a file again.
MSG
    return 0
  fi
  decide
  cat <<MSG
What the next scheduled run will do about it: action=${ACTION}. A record this could not
read is no record, so the run decides as it does on a host that has none rather than
concluding out of a file nobody could parse that the day's backup was taken — that answer
came from the same code the run itself uses and from nothing in this file.

The run writes a new record at that path. Move this file aside first if you want to keep
what is in it.
MSG
}

command_status() {
  resolve_schedule
  if ! read_the_record; then
    refuse_damaged_record "${RECORD_FAULT}"
    return 1
  fi
  # ABSENCE IS THE LIBRARY'S ANSWER, not a second look at the path. `RECORD_PRESENT` is set
  # from `-e` and then `-f`, so a directory here is presence-with-nothing-legible and has
  # already been refused above — this used to answer "no backup has ever been recorded"
  # about a path the panel called unreadable, because `[ -f ]` reads a directory as absence.
  if [ -z "${RECORD_PRESENT}" ]; then
    cat >&2 <<MSG
No backup has ever been recorded on this host.

There is no record at ${STATE_FILE}, which means either that nothing has run yet or that
the schedule was never installed. Install it with \`make backup-schedule\`, or take one
now with \`make backup\`.
MSG
    return 1
  fi

  local sends
  sends="$(printable "${READING_OFFSITE}")"

  echo "Backups on this host, from ${STATE_FILE}:"
  echo
  # WHETHER anything runs, asked of the thing that knows, and WHEN it would run if it does
  # — two different questions with two different sources, so they are two lines. Printed as
  # one confident sentence they read as a working schedule, which on a host with no cron
  # entry is the sentence this whole milestone exists to stop.
  case "$(schedule_answer)" in
    0)
      echo "  scheduled:    yes — this account's cron runs scripts/backup-run.sh every 15"
      echo "                minutes; \`scripts/backup-schedule.sh show\` prints the entry"
      ;;
    1)
      echo "  scheduled:    NO — nothing on this host takes a backup. This account's"
      echo "                crontab has no entry for it; \`make backup-schedule\` installs"
      echo "                one, and everything below is the history of runs before that"
      ;;
    3)
      echo "  scheduled:    NOT KNOWN — this host has no \`crontab\`, so nothing here can"
      echo "                say whether a backup is being taken. If you installed the"
      echo "                systemd timer instead, ask systemctl:"
      echo "                systemctl list-timers hashi-backup.timer"
      ;;
    *)
      # Any other code is the installer itself failing to answer — it is not on this
      # checkout, it is not executable, it refused the verb. "Could not tell" is the only
      # honest reading of that, and reporting it as "nothing runs a backup here" would be
      # this command inventing the very answer it was sent to go and find.
      echo "  scheduled:    NOT KNOWN — scripts/backup-schedule.sh could not answer"
      echo "                whether an entry is installed; ask it directly:"
      echo "                scripts/backup-schedule.sh show"
      ;;
  esac
  # Named as coming from the env file, because it does: this line is what a run would
  # resolve if one happened right now, while everything under it is what the record says
  # happened. On a damaged or absent record the same line used to be printed with the same
  # confidence beside "last success: never", which reads as a fact about the backups.
  echo "  appointed:    ${AT} ${ZONE} (${ZONE_SOURCE}), whenever something runs it"
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
  if failed_since_the_last_success; then
    echo "  FAILED SINCE THE LAST SUCCESS: ${BAD_AT} ($(printable "${BAD_OUTCOME}"), exit ${BAD_CODE})"
  fi
  # 3 is a state with its own remedy rather than a failure to retry, and until now it was
  # shown as a digit and nowhere as what it means. The artifact of that run is on this
  # machine: dumping again would write a second copy of the same database and never fix
  # the reason the store refused the first.
  #
  # ONLY WHILE IT IS STILL TRUE, which it was not until M28.15: `last_failure` is kept for
  # ever, so `BAD_CODE` is still 3 under a run that succeeded and DID leave the machine
  # this morning, and this advice was printed under it. The panel shows a failure only
  # where it is the more recent of the two; so does this now, through the same test the
  # line above it uses.
  if [ "${LAST_CODE}" = "3" ] || { [ "${BAD_CODE}" = "3" ] && failed_since_the_last_success; }; then
    echo "                exit 3 means the artifact WAS written and did NOT leave this"
    echo "                machine. Nothing needs dumping again — send that same file with"
    echo "                make backup-upload FROM=${REPO_ROOT}/backups/<the artifact>"
  fi
  if [ "${MISSED_TOTAL}" -gt 0 ]; then
    # Newest first. The writer sorts them that way now and so does the panel; this sorts
    # what it read as well, because the order of dates in a file on a disk is not a thing
    # any reader may take on trust — and the label says "most recent".
    #
    # THE LABEL IS ONLY PRINTED WHEN THERE IS SOMETHING TO PUT AFTER IT. `missed_total`
    # counts every day ever missed and `missed_dates` keeps thirty of them, so a record old
    # enough to have rolled over — or one whose list was emptied by hand — printed
    # "days with no backup: 12 — most recent:" and then nothing at all. The panel guards
    # this; this did not.
    local recent
    recent="$(printf '%s\n' ${MISSED_LIST} | sort -r | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
    if [ -n "${recent}" ]; then
      echo "  days with no backup: ${MISSED_TOTAL} — most recent: ${recent}"
    else
      echo "  days with no backup: ${MISSED_TOTAL} — this record no longer names which"
    fi
  fi
  # Last of the reading and before the caveat, because it is about every age above it.
  note_clock
  if [ -n "${CLOCK_AHEAD}" ]; then
    echo
    clock_ahead_warning
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
