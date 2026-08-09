"""Configuration and boot behaviour.

WHAT: that the application is constructible without a live environment, and that
      every setting which must not have a default really has none.
WHY:  "fail loudly, never start degraded" (core invariants §3) is only true if it is
      tested. Each of the three required settings below has a specific disaster
      attached to a silent default, named in its own test.
HOW:  builds the app with explicit settings; no database connection is opened, because
      the factory deliberately does not dial one.

This file used to construct ``Settings(secret_key=...)`` alone. That stopped being a
valid premise when the control plane gained a database and an operator — the point of
the change is that it is now impossible to build a half-configured application.
"""

import httpx
import pytest
from pydantic import ValidationError

from control.app.main import create_app
from control.app.settings import Settings

# A complete, obviously fake configuration. The key is 48 characters because the
# application enforces a minimum length — see the test below for why.
TEST_SETTINGS = Settings(
    secret_key="test-only-not-a-real-key-000000000000000000000000",
    database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
    operator_username="owner",
    operator_password_hash="scrypt$32768$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",
)


async def test_healthz_reports_ok() -> None:
    """The factory builds a serving app without touching the database.

    Worth asserting explicitly: the database URL above points at a closed port, so if
    ``create_app`` ever started connecting eagerly, this test would fail — which is the
    behaviour that keeps `--factory` and the test suite on one code path.
    """
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


async def test_every_response_carries_the_security_headers() -> None:
    """Applied by middleware, so a new route cannot forget them."""
    app = create_app(TEST_SETTINGS)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"


def test_missing_secret_key_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """No generated-on-boot fallback: it would make yesterday's backup undecryptable."""
    monkeypatch.delenv("HASHI_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://u:p@h/d",
            operator_password_hash="x",
        )


def test_a_short_secret_key_is_refused() -> None:
    """This key protects every node credential; a guessable one is unrecoverable.

    Enforced in ``Settings`` AND in ``SecretBox``. Both, deliberately: the settings
    check catches it at boot, and the SecretBox check catches a caller that constructed
    one directly.
    """
    from control.app.crypto import SecretBox

    with pytest.raises(ValidationError):
        Settings(
            secret_key="too-short",
            database_url="postgresql+asyncpg://u:p@h/d",
            operator_password_hash="x",
        )
    with pytest.raises(ValueError):
        SecretBox("too-short")


def test_missing_database_url_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """A localhost default would make a misconfigured container look like a db outage."""
    monkeypatch.delenv("HASHI_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            secret_key="test-only-not-a-real-key-000000000000000000000000",
            operator_password_hash="x",
        )


def test_missing_operator_hash_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """A panel with no configured credential must not boot open."""
    monkeypatch.delenv("HASHI_OPERATOR_PASSWORD_HASH", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            secret_key="test-only-not-a-real-key-000000000000000000000000",
            database_url="postgresql+asyncpg://u:p@h/d",
        )


def test_subscription_urls_are_https_by_default() -> None:
    """The token is a bearer credential in the path; http would put it on the wire."""
    assert TEST_SETTINGS.public_https is True
    settings = Settings(
        secret_key="test-only-not-a-real-key-000000000000000000000000",
        database_url="postgresql+asyncpg://u:p@h/d",
        operator_password_hash="x",
        public_host="delivery.example.com",
    )
    assert settings.public_base_url == "https://delivery.example.com"
