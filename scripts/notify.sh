#!/usr/bin/env bash
# WHAT: how an agent reports to the project owner.
# WHY:  the personas call one command to notify; this project has no bot and no
#       Hub, so "notify" means "print it and keep a record". Keeping the record
#       matters more than the delivery: an unattended run's reports are the only
#       trace of what the fleet decided.
# HOW:  scripts/notify.sh "message". Appends to docs/tracker/notifications.log.
set -euo pipefail

msg="${*:?usage: notify.sh <message>}"
mkdir -p docs/tracker
printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$msg" \
  | tee -a docs/tracker/notifications.log
