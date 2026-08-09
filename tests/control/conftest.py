"""Fixtures for the control zone's tests.

WHAT: a real Postgres schema, freshly created per test, an application built against
      it, and an HTTP client already authenticated as the operator.
WHY:  the control rulebook requires a real Postgres rather than SQLite — async
      drivers, JSONB and constraints all behave differently, and a suite that passes
      on SQLite proves nothing about production. This schema has a JSONB column and
      relies on ON DELETE CASCADE, so SQLite would not even exercise the interesting
      parts.
HOW:  every test starts against a freshly dropped and recreated schema. Tables are
      created from the models' metadata here; the MIGRATIONS are verified separately by
      ``tests/control/test_migrations.py`` against the same database, so this
      shortcut cannot hide a migration that disagrees with the models.

Skips loudly, with the command to fix it, when no database is configured — a control
suite that silently passes without a database is a suite that proves nothing.
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from control.app.crypto import hash_password
from control.app.main import create_app
from control.app.models import Base
from control.app.settings import Settings

# Where the tests find a database. Defaults to the dev stack's published Postgres, so
# a developer who ran `make up-dev` needs no extra configuration. Override with
# HASHI_TEST_DATABASE_URL — the fleet does, because its engine is an isolated dind
# where 127.0.0.1 is not the machine running pytest.
DEFAULT_URL = "postgresql+asyncpg://hashi:replace-me@127.0.0.1:54132/hashi"
DATABASE_URL = os.environ.get("HASHI_TEST_DATABASE_URL", DEFAULT_URL)

# Fixed and obviously fake. 48 characters so it satisfies the minimum length the
# application enforces at boot.
TEST_SECRET_KEY = "test-secret-key-not-real-000000000000000000000000"

OPERATOR_USERNAME = "owner"
OPERATOR_PASSWORD = "test-operator-password"


async def database_is_available() -> bool:
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect():
            return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def operator_password_hash() -> str:
    """Hashed once per session — scrypt is deliberately slow (~100ms)."""
    return hash_password(OPERATOR_PASSWORD)


@pytest.fixture
async def clean_database() -> None:
    """Drop and recreate every table before each test.

    Sequential drop/create rather than a schema or database per test. A database per
    test costs about a second each; a private schema is faster but has to be pinned
    with asyncpg's ``server_settings``, which is not expressible in a SQLAlchemy URL
    and would mean this fixture reaching into how ``Database`` builds its engine.
    Dropping is milliseconds and the isolation is equally complete for a suite that
    runs in one process.
    """
    if not await database_is_available():
        pytest.skip(
            f"no Postgres at {DATABASE_URL} — the control zone's tests need a real "
            "database (the rulebook forbids SQLite here). Start one with "
            "`make up-dev`, or set HASHI_TEST_DATABASE_URL."
        )

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        # drop_all first so a leftover table from an interrupted run cannot make the
        # next run fail on a stale constraint instead of on its own behaviour.
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
async def settings(clean_database, operator_password_hash: str) -> Settings:
    return Settings(
        secret_key=TEST_SECRET_KEY,
        database_url=DATABASE_URL,
        operator_username=OPERATOR_USERNAME,
        operator_password_hash=operator_password_hash,
        public_host="control.test",
        # The in-process client speaks http, so the session cookie must not be
        # https-only or no test could ever hold a session.
        public_https=False,
    )


@pytest.fixture
async def app(settings: Settings):
    """An application against the freshly created schema."""
    application = create_app(settings)
    yield application
    await application.state.database.dispose()


@pytest.fixture
async def session(app):
    """A database session against the same schema the app uses."""
    async for handle in app.state.database.session():
        yield handle


@pytest.fixture
async def anonymous(app):
    """An HTTP client with no operator session — for testing that guards hold."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://control.test", follow_redirects=False
    ) as client:
        yield client


@pytest.fixture
async def client(app):
    """An HTTP client already logged in as the operator.

    Logs in through the real login form rather than by forging a cookie, so every
    test that uses this fixture also exercises the authentication path — and a broken
    login shows up as every test failing rather than as one.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://control.test", follow_redirects=False
    ) as handle:
        response = await handle.post(
            "/panel/login",
            data={"username": OPERATOR_USERNAME, "password": OPERATOR_PASSWORD},
        )
        assert response.status_code == 303, "the test operator could not log in"
        yield handle


@pytest.fixture
def reality_params() -> dict[str, object]:
    """Operator-supplied parameters for the Reality transport.

    Only what an OPERATOR types: no keys. Key material is minted by the control
    plane from the transport's declaration, which is the behaviour under test.
    """
    return {
        "port": 8443,
        "decoy_host": "www.example.com",
        "decoy_port": 443,
        "server_names": ["www.example.com"],
    }


@pytest.fixture
def ws_params() -> dict[str, object]:
    return {
        "port": 8444,
        "server_name": "front.example.com",
        "certificate_path": "/etc/hashi/certs/fullchain.pem",
        "certificate_key_path": "/etc/hashi/certs/privkey.pem",
    }
