"""Fixtures for the control zone's tests, and the assertions they share.

WHAT: a real Postgres schema, freshly created per test, an application built against
      it, an HTTP client already authenticated as the operator, and — at the bottom —
      ``assert_plain_reason``, imported with ``from .conftest import`` the way
      ``test_migrations.py`` does.
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
        # No test in this zone reaches a real node: every fixture points at a reserved
        # documentation address that never answers, so the connect ceiling is time the
        # suite spends waiting for a certainty. One second, and the whole suite stops
        # costing minutes — the default of five is a field value, chosen for a lossy
        # link, and nothing here is on a link at all.
        node_connect_timeout=1,
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


# --- what the operator is told when a node cannot be reached (M21.1) ---------
#
# The two tests that assert on it used to pin the exact sentence
# ``edge/bootstrap/ssh.py`` writes when a connect TIMES OUT. Which of its arms runs
# is not a property of this code: at a reserved address nothing routes to, a loaded
# machine (or one that routes TEST-NET-1 over a tunnel) gets a fast rejection and the
# other arm's wording instead. Both outcomes are the same fact — the node could not
# be reached — so the fact is asserted structurally by the caller (``reachable is
# False``, or a ``NodeUnreachable`` cause) and the SHAPE of the sentence is asserted
# here.

# Enough of one to be recognisable in a single line of text: a reason is a sentence,
# and any of these means an exception's rendering leaked into operator-facing text.
_TRACEBACK_MARKERS = ("Traceback (most recent call last)", 'File "', ", line ")

# Stripped off each token before it is judged, so ``session:`` counts as a word and
# ``OSError(113,`` does not become one.
_EDGES = "\"'`.,:;!?()[]{}<>—-"

# A sentence has several ordinary words in it. Four is low enough that any reason
# actually written for a person clears it, and high enough that a class name, a repr,
# or an errno string does not — those are the three shapes this rejects.
_WORDS_REQUIRED = 4


def assert_plain_reason(reason: str | None, *, address: str) -> None:
    """The operator was told, in words, why an operation on a node failed.

    Asserts the property M4.4 introduced rather than the sentence it introduced:
    non-empty, one line, prose, no traceback, no bare exception class name, and no
    node address travelling with it (core invariants §6 — a node's address in
    operator-facing text is a step towards a connection record).

    ``address`` is required rather than optional: every caller has one, and the check
    is worthless in exactly the tests that forget to pass it.
    """
    assert isinstance(reason, str), f"the operator was given no reason at all: {reason!r}"

    text = reason.strip()
    assert text, "the operator was given an empty reason"
    assert "\n" not in text, f"a reason is one sentence, not a report: {text!r}"
    for marker in _TRACEBACK_MARKERS:
        assert marker not in text, f"a traceback reached the operator: {text!r}"

    words = [token.strip(_EDGES) for token in text.split()]
    prose = [word for word in words if len(word) > 1 and word.isalpha() and word.islower()]
    assert len(prose) >= _WORDS_REQUIRED, (
        f"{text!r} is not a reason a person can act on — it needs at least "
        f"{_WORDS_REQUIRED} ordinary words, and has {len(prose)}"
    )

    assert address not in text, (
        f"the node's address travelled with the reason: {text!r}"
    )
