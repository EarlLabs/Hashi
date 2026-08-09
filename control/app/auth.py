"""Operator authentication — backlog item 5.

WHAT: the login check, the session cookie, and the dependency that guards every
      operator surface.
WHY:  the control rulebook requires auth to be a ROUTER-LEVEL dependency rather
      than a check inside each handler: a route added to a guarded router inherits
      the rule, whereas a per-handler check is one forgotten line away from a public
      admin endpoint. There is exactly one operator (the charter's "one operator,
      one fleet"), so credentials come from the environment and there is no users
      table — a table would imply the signup flow the charter names as a non-goal.
HOW:  ``require_operator`` is attached to the API and panel routers. It fails closed:
      any error inside it denies access rather than falling through to the resource
      (core invariants §4).

Deliberately absent: lockout after repeated failures. Recorded as a decision, not an
oversight (backlog nit N6) — with a single operator and a slow KDF, a lockout is a
denial-of-service against the one person who needs to reach the panel during an
emergency rotation.
"""

import logging

from fastapi import Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse

from control.app.crypto import verify_password
from control.app.settings import Settings

logger = logging.getLogger(__name__)

# The session key holding the authenticated operator's name.
SESSION_USER = "operator"


def authenticate(settings: Settings, username: str, password: str) -> bool:
    """Check a login attempt.

    Both halves are checked even when the username is already wrong, so the response
    time does not reveal whether the username was right — the username is guessable
    ("owner" is the default) but confirming it is still free information.
    """
    password_ok = verify_password(password, settings.operator_password_hash)
    username_ok = username == settings.operator_username
    return password_ok and username_ok


def is_authenticated(request: Request) -> bool:
    """Whether this request carries a valid operator session.

    Wrapped in a try/except that denies on ANY failure: a malformed or
    wrong-key-signed cookie raises inside the session middleware, and an exception
    escaping here would become a 500 that some frameworks treat as "no decision" and
    others as a redirect loop. Authorisation fails closed.
    """
    try:
        return bool(request.session.get(SESSION_USER))
    except Exception:  # noqa: BLE001 - fail closed, whatever went wrong
        logger.warning("session could not be read; denying access")
        return False


async def require_operator(request: Request) -> str:
    """Router dependency for `/api/**`. Denies with a JSON 401.

    Never a redirect: these are machine endpoints, and a 302 to a login page is
    parsed by a client as a successful response with strange content.
    """
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "operator login required"}},
        )
    return str(request.session[SESSION_USER])


class RedirectToLogin(Exception):
    """Raised by the panel's guard; converted into a redirect by a handler.

    An exception rather than returning a response from the dependency, because a
    dependency that returns a response does not actually stop the handler from
    running — it just gets ignored, and the guarded page renders anyway.
    """


async def require_operator_page(request: Request) -> str:
    """Router dependency for `/panel/**`. Sends a browser to the login page."""
    if not is_authenticated(request):
        raise RedirectToLogin
    return str(request.session[SESSION_USER])


async def redirect_to_login_handler(request: Request, exc: RedirectToLogin) -> RedirectResponse:
    """Send an unauthenticated browser to the login form.

    The originally requested path is NOT carried in a query parameter, deliberately:
    a `?next=` is an open-redirect surface, and the panel is small enough that
    landing on its index costs the operator one click.
    """
    return RedirectResponse(url="/panel/login", status_code=status.HTTP_303_SEE_OTHER)


def log_in(request: Request, username: str) -> None:
    request.session[SESSION_USER] = username
    logger.info("operator session opened")


def log_out(request: Request) -> None:
    request.session.clear()
    logger.info("operator session closed")
