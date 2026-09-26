#!/usr/bin/env bash
#
# hashi — the disposable stand the security audit attacks.
#
# WHAT: `up` brings up the SAME stand acceptance walks and then seeds the audit's
#       identities; `down` destroys it with its volumes.
# WHY:  the audit needs more than one identity live at once — authorization bugs
#       are invisible with a single login, and "user A's token must not reach
#       user B's configuration" is this product's highest-value boundary. The
#       acceptance stand deliberately seeds nothing, because an agent walking a
#       milestone should meet every awkward first-time step. Both are right, so
#       this script is a LAYER over that one rather than a second stack: a second
#       compose project with the same services diverges from the first within a
#       milestone, and the audit would then be attacking a configuration nobody
#       ships. Same reasoning, one level up, as scripts/acceptance/stand.sh's own
#       relationship to `make e2e-up`.
# HOW:  delegate to scripts/acceptance/stand.sh, then run seed.py. `down` is pure
#       delegation — there is nothing of ours to tear down that its `down -v` does
#       not already take.
#
# NEVER point this at production. The hunter double-submits, injects, enumerates
# ids and sends malformed input on purpose; that belongs somewhere destroyed
# afterwards. The fence in the plugin's bin/probe allows one origin, and this
# stand is it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

E2E_API_HOST="${E2E_API_HOST:-127.0.0.1}"
E2E_API_PORT="${E2E_API_PORT:-54200}"

say() { printf '[sec-stand] %s\n' "$*"; }
die() { printf '[sec-stand] %s\n' "$*" >&2; exit 1; }

PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3

up() {
  # ACCEPTANCE_BROWSER=0: the audit speaks HTTP through bin/probe and never opens a
  # page, so the Chromium the acceptance stand carries would be a gigabyte of shared
  # memory and an image build bought for nothing. Everything else about the stand —
  # the teardown-first, the health wait, the read-only role — is that script's and is
  # not reimplemented here.
  say "bringing up the stand (no browser: the audit speaks HTTP)"
  ACCEPTANCE_BROWSER=0 scripts/acceptance/stand.sh up \
    || die "the stand did not come up — the message above is the cause"

  say "seeding the audit's identities"
  "$PY" scripts/security/seed.py \
    || die "the stand is up and its identities are not seeded — a one-role audit cannot test an authorization boundary, so this is a failure and not a warning"

  cat <<INNER

[sec-stand] ready for the audit.

  Target        http://${E2E_API_HOST}:${E2E_API_PORT}
  Roles         anon, operator, user_a, user_b, user_revoked
  Credentials   scripts/security/role.sh <role>   (never printed here)
  Truth         scripts/acceptance/query.py       (read-only role, reused)

Threat model: docs/security/threat-model.md — it names what is out of scope, so a
"could not reach" line can be a known boundary rather than a gap.
INNER
}

down() {
  # Pure delegation, deliberately: `acceptance/stand.sh down` runs `e2e-down` with
  # -v, which takes the volume and therefore every user and token this script
  # seeded. A second teardown here would be a second place to forget a profile.
  say "tearing the stand down with its volumes"
  scripts/acceptance/stand.sh down
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  *) die "usage: scripts/security/stand.sh {up|down}" ;;
esac
