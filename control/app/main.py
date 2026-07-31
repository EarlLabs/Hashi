"""Control-plane application factory.

WHAT: builds the FastAPI application. Currently a scaffold: it serves ``/healthz``
      and nothing else.
WHY:  a factory rather than a module-level ``app`` object, so importing this
      module never requires the environment to be configured — tests build an app
      with explicit settings, while the container passes ``--factory``.
HOW:  ``create_app()`` reads Settings when called. Routers get mounted here as
      they are built; route logic itself belongs in ``control/app/services``.
"""

from fastapi import FastAPI

from control.app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Pass ``settings`` in tests; production reads env."""
    settings = settings or Settings()

    # docs_url/redoc_url are off: the panel is the highest-value target in the
    # system, and a public schema of its API is free reconnaissance.
    app = FastAPI(title="hashi control plane", docs_url=None, redoc_url=None)
    app.state.settings = settings

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness only. Says nothing about nodes, users or configuration."""
        return {"status": "ok"}

    return app
