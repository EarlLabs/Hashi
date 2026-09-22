#!/usr/bin/env python3
"""hashi — seed the identities the security audit attacks as.

WHAT: creates the audit's three users on the disposable stand — two live and
      one revoked — and writes their subscription tokens to a roles file that
      ``role.sh`` reads.

WHY:  the audit's highest-value boundary is "user A's token must not reach
      user B's configuration", and a single identity cannot test it. The
      acceptance stand deliberately seeds NOTHING (its whole value is that every
      awkward first-time step is still ahead of the agent), so the audit's
      identities are seeded here, on top of it, rather than by changing what
      acceptance walks.

WHY a revoked user too. ``docs/security/threat-model.md`` §3.4: a revoked
      token's answer must be indistinguishable from a token that was never
      issued. That is a comparison between two requests, so both sides have to
      exist before the hunt starts — a hunter that revokes someone mid-run has
      spent budget and still cannot replay the pair.

WHY the tokens go to a file and not into the report. A token is a bearer
      credential (CLAUDE.md), so it is written under the gitignored evidence root
      with owner-only permissions, never printed by ``stand.sh``, and never put
      anywhere a verdict or a log could carry it. ``role.sh`` is the one thing
      that prints one, to the agent that needs it.

WHY it is re-run on every stand. Tokens are 32 random bytes minted by the control
      plane; a rebuilt stand mints different ones, and nothing can pin them
      without writing to the database. So the roles file is rewritten by every
      ``stand.sh up``, and both the hunter and the refuter read the CURRENT
      token through ``role.sh`` rather than trusting one embedded in a transcript.
      That is exactly why the refuter is allowed to re-send a proof with a fresh
      id instead of only replaying bytes.

HOW:  stdlib only — urllib and http.cookiejar. Adding a dependency is an
      architect decision (CLAUDE.md), and ``requests`` would be one for a script
      that makes six calls.

NEVER point this at anything but the stand. It creates records and revokes one.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

# Defaults mirror scripts/acceptance/stand.sh, and are overridable for the one
# reason it documents: an engine that is not the machine you are sitting at.
API_HOST = os.environ.get("E2E_API_HOST", "127.0.0.1")
API_PORT = os.environ.get("E2E_API_PORT", "54200")
BASE = f"http://{API_HOST}:{API_PORT}"

# The stand's fixed operator credentials, printed by scripts/acceptance/stand.sh.
# Obviously fake and committed on the same grounds as deploy/e2e.env: they guard a
# stack with no real nodes and no real users, whose volume is destroyed on the
# way out. Nothing here may ever be copied into .env.
OPERATOR_USER = os.environ.get("HASHI_OPERATOR_USERNAME", "owner")
OPERATOR_PASSWORD = os.environ.get("HASHI_OPERATOR_PASSWORD", "e2e-operator-password")

# Under the gitignored evidence root, not in the repository: this file holds three
# bearer credentials.
ROLES_FILE = pathlib.Path(
    os.environ.get("SECURITY_ROLES_FILE", ".acceptance/security/roles.json")
)

# The nicknames are recognisable on purpose. Someone reading the stand's database
# while debugging should be able to tell an audit fixture from a real record at a
# glance — on the stand there are no real records, and the habit is still right.
USERS = [
    ("user_a", "audit-user-a"),
    ("user_b", "audit-user-b"),
    ("user_revoked", "audit-user-revoked"),
]


def fail(message: str) -> None:
    print(f"[seed] {message}", file=sys.stderr)
    raise SystemExit(1)


def opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    """A client that keeps cookies, and the jar itself — the jar is the evidence.

    Returned as a pair because "did the login work?" is answered by the jar and not
    by a status code: urllib FOLLOWS the 303 the login handler returns, so a
    successful login reports 200 (the panel it landed on) and a failed one reports
    401. Checking for a redirect here would reject every success, which is exactly
    what it did the first time this ran.
    """
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def call(
    client: urllib.request.OpenerDirector,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    form_body: dict | None = None,
) -> tuple[int, bytes]:
    body: bytes | None = None
    headers: dict[str, str] = {}
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form_body is not None:
        body = urllib.parse.urlencode(form_body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with client.open(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:  # a status is an answer, not a crash
        return exc.code, exc.read()
    except OSError as exc:
        fail(f"{method} {path} could not reach {BASE}: {exc}. Is the stand up?")
        raise  # unreachable; keeps the type checker honest


SESSION_COOKIE = "hashi_operator"


def login(client: urllib.request.OpenerDirector, jar: http.cookiejar.CookieJar) -> None:
    """Open an operator session, and prove it opened.

    The panel's form login, not an API key: the session cookie IS the operator's
    credential and there is no other way in.

    Success is checked TWICE and neither check is the status code. The handler
    answers 303 to ``/panel/`` and urllib follows it, so a success arrives as 200 and
    a refusal as 401 — a 200 alone would also be what a redirect to the login form
    looks like. So: the cookie has to be in the jar, and a guarded route has to
    actually answer. The second check is the one that matters; a signed cookie the
    app will not accept is still a cookie.
    """
    status, _ = call(
        client,
        "POST",
        "/panel/login",
        form_body={"username": OPERATOR_USER, "password": OPERATOR_PASSWORD},
    )
    if status == 401:
        fail(
            f"the stand refused {OPERATOR_USER}/… — its credentials are not the ones "
            f"this script defaults to. Check what scripts/acceptance/stand.sh printed "
            f"and set HASHI_OPERATOR_USERNAME / HASHI_OPERATOR_PASSWORD."
        )
    if not any(cookie.name == SESSION_COOKIE for cookie in jar):
        fail(f"login answered {status} and set no {SESSION_COOKIE} cookie — no session")
    guarded, raw = call(client, "GET", "/api/users")
    if guarded != 200:
        fail(
            f"the session does not open /api/users: {guarded} {raw[:200]!r}. The "
            f"cookie exists and the app will not accept it."
        )


def create_user(client: urllib.request.OpenerDirector, nickname: str) -> str:
    status, raw = call(client, "POST", "/api/users", json_body={"nickname": nickname})
    if status != 201:
        fail(f"creating {nickname} returned {status}: {raw[:400]!r}")
    return str(json.loads(raw)["id"])


def token_of(client: urllib.request.OpenerDirector, user_id: str) -> str:
    status, raw = call(client, "GET", f"/api/users/{user_id}/subscription")
    if status != 200:
        fail(f"no subscription for {user_id}: {status} {raw[:400]!r}")
    # The response carries a full URL built from the stand's configured public base,
    # which is not necessarily the address the agent reaches it on. The TOKEN is what
    # is wanted, so take the last path segment and let the agent compose the URL from
    # the target it was given.
    url = str(json.loads(raw)["url"])
    token = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if len(token) < 16:
        fail(f"{user_id}'s subscription URL does not end in a token: {url!r}")
    return token


def revoke(client: urllib.request.OpenerDirector, user_id: str) -> None:
    status, raw = call(client, "POST", f"/api/users/{user_id}/revoke")
    if status != 200:
        fail(f"revoking {user_id} returned {status}: {raw[:400]!r}")


def main() -> int:
    client, jar = opener()
    login(client, jar)

    roles: dict[str, dict[str, str]] = {
        "anon": {"kind": "none"},
        "operator": {
            "kind": "form-login",
            "username": OPERATOR_USER,
            "password": OPERATOR_PASSWORD,
            "path": "/panel/login",
        },
    }

    for key, nickname in USERS:
        user_id = create_user(client, nickname)
        token = token_of(client, user_id)
        roles[key] = {
            "kind": "path-token",
            # The roles file is a two-file contract: scripts/security/role.sh reads
            # this key by name, so it moves only when that script moves with it — and a
            # roles file left over from an older stand still carries the old key, which
            # is why every `stand.sh up` re-seeds rather than reusing one.
            "user_id": user_id,
            "nickname": nickname,
            "token": token,
            "path": f"/sub/{token}",
        }

    # Revoked LAST and after its token was read: the token has to be known in order
    # to ask what a revoked one answers, which is the whole point of §3.4.
    revoke(client, roles["user_revoked"]["user_id"])
    roles["user_revoked"]["revoked"] = "true"

    ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 0600 on a file holding three bearer credentials, and the mode is set before the
    # write so there is no instant at which it is world-readable.
    handle = os.open(ROLES_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(handle, "w") as file:
        json.dump(roles, file, indent=2)

    # Counts and names only. A token never goes to stdout from here — `role.sh` is
    # the one thing that prints one, to the one agent that asked for it.
    print(
        f"[seed] {len(USERS)} users seeded "
        f"({', '.join(nickname for _, nickname in USERS)}), one of them revoked"
    )
    print(f"[seed] credentials in {ROLES_FILE} (0600, gitignored) — read them with role.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
