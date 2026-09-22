#!/usr/bin/env bash
#
# hashi — print one security-audit role's current credential.
#
# WHAT: `role.sh <name>` prints what the hunter or the refuter needs in order to
#       act as that identity, and how to use it through `probe`.
# WHY:  `aikit.yml`'s `security.roles[].auth` is either a fixed header or a
#       command the agent runs to obtain a session. Neither of this project's two
#       credentials is a header: the operator's is a SIGNED COOKIE that only the
#       probe's own jar can hold, and a friend's is a PATH SEGMENT with no header
#       to pin at all. So the command is this one — it hands over the material and
#       says which probe verb turns it into a session.
# WHY it is re-read and never remembered: a friend's token is 32 random bytes
#       minted by the control plane, so every `stand.sh up` produces different
#       ones. The refuter runs this AFTER its own fresh stand and gets that
#       stand's token, which is what lets it re-send a proof the hunter wrote
#       against different bytes.
# HOW:  reads the roles file `seed.py` wrote. No network, no state of its own.
#
# The tokens this prints are bearer credentials. It prints them to one caller on
# stdout and nowhere else: never into a verdict, never into a log, never into a
# screenshot. See CLAUDE.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ROLES_FILE="${SECURITY_ROLES_FILE:-.acceptance/security/roles.json}"
E2E_API_HOST="${E2E_API_HOST:-127.0.0.1}"
E2E_API_PORT="${E2E_API_PORT:-54200}"
BASE="http://${E2E_API_HOST}:${E2E_API_PORT}"

die() { printf '[role] %s\n' "$*" >&2; exit 1; }

[ $# -eq 1 ] || die "usage: scripts/security/role.sh <anon|operator|friend_a|friend_b|friend_revoked>"
NAME="$1"

[ -f "$ROLES_FILE" ] || die "no ${ROLES_FILE} — run \`scripts/security/stand.sh up\` first; it seeds the roles"

# python over jq: jq is not a dependency of this project and the venv's python is
# already required by every other script here.
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3

"$PY" - "$ROLES_FILE" "$NAME" "$BASE" <<'PYEOF'
import json, pathlib, sys

path, name, base = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
roles = json.loads(path.read_text())
role = roles.get(name)
if role is None:
    print(f"[role] no such role: {name}. Seeded: {', '.join(roles)}", file=sys.stderr)
    raise SystemExit(1)

kind = role["kind"]
if kind == "none":
    print("anon: send nothing. `probe request GET <url> --role anon`")
elif kind == "form-login":
    # The session is a signed cookie, so it has to be obtained THROUGH probe — an
    # external curl would put the cookie in a jar probe cannot see.
    body = f"username={role['username']}&password={role['password']}"
    print(f"operator: obtain the session through probe itself, so its jar holds the cookie:")
    print(f"  probe request POST '{base}{role['path']}' --role operator \\")
    print(f"      --header 'Content-Type: application/x-www-form-urlencoded' \\")
    print(f"      --data '{body}'")
    print("  probe does not follow redirects, so a 303 to /panel/ IS the successful")
    print("  login and the Set-Cookie on it is the session. A refusal is 401 with the")
    print("  same generic message for a wrong username and a wrong password.")
elif kind == "path-token":
    revoked = role.get("revoked") == "true"
    what = "REVOKED — for the revoked-vs-unknown comparison" if revoked else "live"
    print(f"{name} ({role['nickname']}, {what}):")
    print(f"  friend id  {role['friend_id']}")
    print(f"  token      {role['token']}")
    print(f"  url        {base}{role['path']}")
    print("  the credential is the PATH, not a header — there is nothing to pin with")
    print("  `probe auth`. Put it in the URL: `probe request GET '<url>' --role " + name + "`")
else:
    print(f"[role] unknown credential kind {kind!r} in {path}", file=sys.stderr)
    raise SystemExit(1)
PYEOF
