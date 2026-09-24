#!/usr/bin/env bash
# WHAT: installs, shows and removes the one crontab entry that calls
#       scripts/backup-run.sh every 15 minutes.
# WHY:  this is the whole "something runs it every day" mechanism, and it is deliberately
#       the dumbest part of it. Three shapes were on the table (M28.5): a cron entry, a
#       systemd timer, and a service in the compose stack.
#
#       THE COMPOSE SERVICE WAS REJECTED, and it is the one this milestone's own habits
#       point at — M28.2 put `age` in the control image and M28.3 runs the uploader in a
#       one-off container so that the HOST needs nothing installed. A container cannot
#       take this backup, though: the dump comes out of the db container and is encrypted
#       inside the control container, so anything that runs `scripts/backup.sh` needs to
#       drive this host's docker. A permanently running container with `/var/run/docker.sock`
#       mounted has root on the host, and it would also need the env file, which holds
#       HASHI_SECRET_KEY, POSTGRES_PASSWORD and the object store's credential. That is the
#       most dangerous container in the stack, created to do the least: wait. This
#       repository has refused that mount once already — deploy/warden/docker-compose.yml
#       runs an isolated engine instead of sharing the host's socket. Cron costs no new
#       privilege, no new image and no root: the entry goes in the crontab of the same
#       account that already runs `make up`.
#
#       A SYSTEMD TIMER is the same shape and is written out in docs/deploy/runbook.md for
#       a host without cron. It needs root to install, and its one apparent advantage —
#       `Persistent=true`, which runs a missed job at the next boot — is an advantage over
#       a timer that fires once a day at 04:00, which is not what is installed here. The
#       entry below carries no hour at all.
#
#       THAT IS THE POINT. `0 4 * * *` is a promise cron cannot keep: if the box is off,
#       asleep or being rebuilt at 04:00, the minute passes and NOTHING RECORDS THAT IT
#       DID. A schedule that silently skips is the failure discovered during a restore. So
#       the entry fires every 15 minutes and carries no opinion about the hour; whether
#       the day's backup is owed is decided by scripts/backup-run.sh, from a record that
#       stays true across a reboot, and the days that had no backup are written down.
#       It also means cron's timezone — which differs between implementations and from the
#       host's — decides nothing: HASHI_BACKUP_TZ does.
# HOW:  scripts/backup-schedule.sh install | show | remove
#       or: make backup-schedule / make backup-status / make backup-unschedule
#
#       Idempotent: install replaces its own block and touches no other crontab line.
#
#       `show` ANSWERS A QUESTION and has three exit codes for it: 0 the entry is there,
#       1 this account's crontab has no entry, 3 nothing here can tell — the host has no
#       `crontab` at all, which is the supported systemd-timer shape. `install` and
#       `remove` keep the ordinary 1: they could not do the job, and there is no third
#       answer to give. The third code exists because scripts/backup-run.sh asks this
#       question on `make backup-status`, and collapsing "no" into "cannot tell" would
#       have that command tell a host running the systemd timer that nothing backs it up.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

STATE_DIR="${HASHI_BACKUP_STATE_DIR:-${REPO_ROOT}/backups/state}"

# The markers that make this idempotent. Everything between them belongs to this script
# and is replaced wholesale; everything outside them is the operator's and is copied
# through untouched.
OPEN="# >>> hashi backup schedule — scripts/backup-schedule.sh >>>"
CLOSE="# <<< hashi backup schedule <<<"

usage() {
  cat >&2 <<'USAGE'
usage:
  scripts/backup-schedule.sh install   # add (or refresh) the cron entry
  scripts/backup-schedule.sh show      # print the entry this account has, if any
  scripts/backup-schedule.sh remove    # take it out again

The entry runs scripts/backup-run.sh every 15 minutes. It carries no hour: when the day's
backup is owed is HASHI_BACKUP_AT and HASHI_BACKUP_TZ in the env file, and a box that was
down at that hour takes the backup when it comes back rather than skipping the day.

`show` exits 0 when the entry is installed, 1 when this account's crontab has none, and 3
when this host has no `crontab` for anything to be installed in.
USAGE
  exit 2
}

have_crontab() {
  command -v crontab >/dev/null 2>&1
}

# The exit code is the caller's, because what "no crontab here" MEANS depends on what was
# asked: install and remove could not act (1), and `show` could not find out (3).
no_crontab() {
  cat >&2 <<'MSG'
there is no `crontab` on this host, so there is nothing here to install into.

Every operation this project needs is in the Makefile, and this is the one that depends on
something the host provides. The equivalent systemd timer — two files, the same
scripts/backup-run.sh, the same fifteen-minute tick — is written out in
docs/deploy/runbook.md under "When the backup runs, and how you know it did". Install
that instead; the schedule itself lives in the env file either way.
MSG
  exit "${1:-1}"
}

# The current crontab, or nothing. `crontab -l` exits non-zero when the account has none,
# which is an ordinary state and not a failure.
current() {
  crontab -l 2>/dev/null || true
}

# Everything that is not ours, in order. A crontab is the operator's file and may hold
# entries that matter more than this one.
without_our_block() {
  current | awk -v open="${OPEN}" -v ending="${CLOSE}" '
    $0 == open { skip = 1; next }
    $0 == ending { skip = 0; next }
    !skip { print }
  '
}

our_block() {
  cat <<BLOCK
${OPEN}
# Installed by scripts/backup-schedule.sh. Edit the schedule in the env file
# (HASHI_BACKUP_AT, HASHI_BACKUP_TZ), not here: this entry carries no hour on purpose.
# Output is NOT discarded. A tick with nothing to do prints nothing, so a working
# schedule is silent; a failed run prints, and cron delivers that wherever it delivers
# mail. The record at ${STATE_DIR} is the channel that does not depend on mail existing.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/15 * * * * ${REPO_ROOT}/scripts/backup-run.sh tick
${CLOSE}
BLOCK
}

command_install() {
  have_crontab || no_crontab

  # Created before the first tick and owned by whoever installs the schedule. Docker would
  # otherwise create it as root the first time the stack came up — the control container
  # reads it through a read-only mount — and the cron entry would then fail to write the
  # record on a host where everything else works.
  mkdir -p "${STATE_DIR}"

  { without_our_block; our_block; } | crontab -

  cat >&2 <<MSG
installed. This account's cron now runs, every 15 minutes:

  ${REPO_ROOT}/scripts/backup-run.sh tick

It will take the first backup at the next tick, because this host has no record of one —
which is deliberate: you find out within a quarter of an hour whether the schedule works,
rather than the morning after. After that it takes one a day, at HASHI_BACKUP_AT in
HASHI_BACKUP_TZ, and if the box is down at that hour it takes the day's backup when it
comes back and records which days had none.

  scripts/backup-run.sh due       # what it would do right now
  make backup-status              # what the record says
MSG
}

command_show() {
  have_crontab || no_crontab 3
  local block
  block="$(current | awk -v open="${OPEN}" -v ending="${CLOSE}" '
    $0 == open { keep = 1 }
    keep { print }
    $0 == ending { keep = 0 }
  ')"
  if [ -z "${block}" ]; then
    echo "no hashi backup schedule is installed for this account." >&2
    echo "install it with: make backup-schedule" >&2
    return 1
  fi
  printf '%s\n' "${block}"
}

command_remove() {
  have_crontab || no_crontab
  without_our_block | crontab -
  echo "removed. Nothing runs a backup on this host now." >&2
  echo "The record of what ran before is untouched, at ${STATE_DIR}." >&2
}

case "${1:-}" in
  install) command_install ;;
  show)    command_show ;;
  remove)  command_remove ;;
  *)       usage ;;
esac
