"""Control-plane application factory.

WHAT: builds the FastAPI application and wires everything to it.
WHY:  a factory rather than a module-level ``app`` object, so importing this module
      never requires the environment to be configured — tests build an app with
      explicit settings, while the container passes ``--factory``.
HOW:  ``create_app()`` reads Settings when called. Routers get mounted here; route
      logic itself belongs in ``control/app/services``.
"""

import contextlib
import logging
import pathlib

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from control.app import auth, crypto, errors
from control.app.api import delivery
from control.app.api import routes as api_routes
from control.app.crypto import SecretBox, session_secret
from control.app.db import Database
from control.app.models.base import bind_secret_box
from control.app.panel import routes as panel_routes
from control.app.services import apply, audit
from control.app.settings import Settings

logger = logging.getLogger(__name__)

STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"


def configure_logging() -> None:
    """One logging setup for the process.

    WARNING, not INFO, as the root level. Not a preference: at INFO, several
    libraries in this stack log request lines and SQL with bound parameters, and a
    request line here contains a subscription token while a bound parameter can be a
    decrypted secret. The application's own loggers are raised to INFO explicitly,
    because their messages are written to carry no path and no user data.
    """
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("control").setLevel(logging.INFO)
    logging.getLogger("edge").setLevel(logging.INFO)

    # Explicitly silenced. uvicorn is also started with --no-access-log, and both are
    # needed: the flag covers the server's own logger, this covers the case where the
    # app is run by something else (a test harness, gunicorn, a developer's `uvicorn`
    # invocation without the flag).
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Pass ``settings`` in tests; production reads env."""
    settings = settings or Settings()
    configure_logging()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # The pool is opened here rather than at import so that building an app never
        # dials a database — which is what lets `--factory` and the tests share a
        # code path.
        #
        # The audit trail's retention sweep is started here and nowhere else, because
        # this is the only place in the process that outlives a request. Sweeping on
        # write instead would mean a trail that expires only when the operator acts,
        # which is not retention on an idle machine (docs/decisions.md, 2026-09-11).
        # It is held on app state so a test can see it running rather than infer it.
        app.state.audit_sweeper = audit.start_sweeper(
            app.state.database, retention_days=settings.audit_retention_days
        )
        try:
            yield
        finally:
            # Cancelled BEFORE the pool is disposed: the sweeper holds a session while
            # it runs, and disposing an engine out from under it is how a clean
            # shutdown turns into a traceback nobody reads.
            await audit.stop_sweeper(app.state.audit_sweeper)
            await app.state.database.dispose()

    # The panel is the highest-value target in the system, and a public schema of
    # its API is free reconnaissance. openapi_url is the load-bearing one of the
    # three: turning off docs_url/redoc_url only removes the two HTML viewers,
    # while /openapi.json keeps serving the machine-readable schema those viewers
    # were reading — every route, every parameter, every model.
    app = FastAPI(
        title="hashi control plane",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Installed before anything can touch an encrypted column. A write that happened
    # before this line would raise rather than store plaintext (see
    # models/base.py:secret_box), but the ordering is the real guarantee.
    box = SecretBox(settings.secret_key)
    bind_secret_box(box)
    app.state.secret_box = box
    app.state.database = Database(settings.database_url)
    apply.bind_settings(settings)

    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret(settings.secret_key),
        max_age=settings.session_max_age,
        # The session cookie is the operator's credential for a panel that can read
        # every node key, so: not readable from JavaScript, not sent cross-site, and
        # https-only whenever the deployment is https.
        https_only=settings.public_https,
        same_site="lax",
        # Scoped to nothing narrower than "/" because the panel and the API are both
        # served from this app, but named distinctly so it cannot collide with another
        # service on the same host.
        session_cookie="hashi_operator",
    )

    app.add_exception_handler(errors.DomainError, errors.domain_error_handler)
    # Registered BEFORE the catch-all so a wrong HASHI_SECRET_KEY is a sentence the
    # operator can act on rather than an opaque 500. See errors.SecretsUnreadable: the
    # moment this exists for is a restore onto a new host with the key mistyped.
    app.add_exception_handler(crypto.SecretUnreadable, errors.secret_unreadable_handler)
    app.add_exception_handler(Exception, errors.unhandled_error_handler)
    app.add_exception_handler(auth.RedirectToLogin, auth.redirect_to_login_handler)

    app.include_router(api_routes.router)
    app.include_router(panel_routes.public)
    app.include_router(panel_routes.router)
    # Mounted last, and with no auth: the token in its path IS the credential. See
    # control/app/api/delivery.py for the rules that route lives under.
    app.include_router(delivery.router)

    if STATIC_DIR.is_dir():
        # Served by us rather than from a CDN on purpose: the panel has to work on a
        # network where a CDN is blocked, which is the same network the operator is on
        # when a node needs replacing.
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness only. Says nothing about nodes, users or configuration."""
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        """Send a human to the panel.

        Deliberately a redirect to the login page and not a landing page of any kind:
        this host is reachable from inside Russia by anyone who guesses it, and the
        charter forbids anything that advertises the service.
        """
        return RedirectResponse(url="/panel/")

    @app.get("/robots.txt", include_in_schema=False)
    async def robots() -> PlainTextResponse:
        """Ask crawlers to stay out. Belt and braces with the per-page meta tag."""
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Headers every response carries.

        The CSP is strict because the panel's own pages are the attack surface that
        matters: node names and error strings from remote hosts are rendered there.
        ``'unsafe-inline'`` is present for style and script only because the panel
        deliberately has no build step — the alternative is a bundler, which the
        charter declined, and both the inline style and the one inline script are
        written by us and shipped in the image.
        """
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            # Stated rather than inherited from default-src, deliberately. The panel
            # self-hosts Barlow because decision 7 forbade the font service the design
            # system imported from, and this is the line a browser would enforce if
            # that @import ever came back — a rule that is written down is one nobody
            # widens by accident while relaxing default-src for something else.
            "font-src 'self'; "
            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; "
            "base-uri 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")

        # Nothing this application generates may be STORED by a browser or a proxy.
        # Two reasons, either sufficient: every /panel and /api response is a view of
        # an operator session, and one panel fragment renders a live subscription
        # token, which is a bearer credential and must not survive on disk.
        #
        # The defect that put this here was neither of those, though. A console URL
        # has TWO representations — the whole document a browser navigates to, and
        # the fragment htmx swaps into #main — and without a directive the browser
        # stored the fragment under /panel/users. A back/forward navigation reuses
        # a stored entry WITHOUT revalidating, so pressing Back landed the operator
        # on the bare fragment as a whole document: no <head>, therefore no
        # stylesheets, therefore an unstyled console until a manual reload.
        # `setdefault` so /sub/{token}'s own stricter value (delivery.py) still wins.
        if not request.url.path.startswith("/static"):
            response.headers.setdefault("Cache-Control", "no-store")
        # And the two representations are declared different even to a cache that
        # ignores the line above: a request without HX-Request may never be answered
        # from an entry stored for one that had it. Appended rather than assigned —
        # SessionMiddleware runs inside this one and has already put `Cookie` there,
        # and overwriting that would tell a cache the panel is the same for every
        # operator session.
        if request.url.path.startswith(panel_routes.router.prefix):
            response.headers.add_vary_header("HX-Request")
        return response

    logger.info("control plane built")
    return app
