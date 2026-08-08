"""Control-plane scaffold tests.

WHAT: proves the application builds and that configuration fails loudly.
WHY:  the scaffold has no features yet, but the two invariants it does have are
      worth pinning from day one: the app must be constructible without a live
      environment, and a missing secret must stop the boot rather than degrade it.
HOW:  builds the app with explicit settings; no database, no network.
"""

import httpx
import pytest
from pydantic import ValidationError

from control.app.main import create_app
from control.app.settings import Settings

TEST_SETTINGS = Settings(secret_key="test-only-not-a-real-key")


async def test_healthz_reports_ok() -> None:
    app = create_app(TEST_SETTINGS)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_openapi_schema_is_not_served() -> None:
    """The panel is the highest-value target; a public schema is free recon.

    /openapi.json is included deliberately: it is the schema itself, and it kept
    serving after docs_url/redoc_url were turned off — the two HTML viewers are
    not what leaks.
    """
    app = create_app(TEST_SETTINGS)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/redoc")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404


def test_missing_secret_key_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """No generated-on-boot fallback: it would make yesterday's backup undecryptable."""
    monkeypatch.delenv("HASHI_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings()
