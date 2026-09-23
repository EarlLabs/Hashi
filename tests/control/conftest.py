"""Fixtures for the control zone's tests, and the assertions they share.

WHAT: a real Postgres schema, freshly created per test, an application built against
      it, an HTTP client already authenticated as the operator, ``nothing_retired`` for
      the family tests that must still reach a retired transport's capabilities,
      ``accepting_nodes`` for the two files that need an apply to SUCCEED, and — at the
      bottom — ``assert_plain_reason``, imported with ``from .conftest import`` the way
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

import dataclasses
import inspect
import os
import pathlib
import socket
from collections.abc import Iterator
from typing import NamedTuple

import asyncssh
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from control.app.crypto import hash_password
from control.app.main import create_app
from control.app.models import Base
from control.app.services import transports as transports_service
from control.app.settings import Settings
from edge.bootstrap import NodeConnection, node_stack
from edge.health import listening
from edge.registry import Layer4, discover

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

# An SSH private key a node record can really hold, for the fixtures whose node is
# registered with one.
#
# It has to be a REAL key, and cannot go back to being the string "not-a-real-key" it
# was in three files: since M9's acceptance fixes, a key that the SSH layer cannot load
# is refused when the node is registered and again before any connection is attempted
# (``nodes.ssh_key_is_usable``, ``apply.target_for``) — because a paste that will not
# import used to reach the operator as an internal error naming an exception class.
# A fixture holding a placeholder now stops at the registration it is not testing.
#
# Generated per run rather than committed: a private key in a repository is a private
# key in a repository, even a useless one, and this costs microseconds. It authenticates
# nothing here — every test that uses it replaces the connection or dials an address
# nothing answers on.
GENERATED_SSH_KEY = (
    asyncssh.generate_private_key("ssh-ed25519").export_private_key("openssh").decode()
)


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
def settle_window() -> tuple[float, float]:
    """How long an apply watches a restarted daemon, and how far apart its readings are.

    Tiny by default, because almost every test here applies to a node that comes straight
    up and pays this window for nothing. A file whose subject IS the watching overrides
    this fixture with a window wide enough to model a container that takes a moment —
    which is the point of it being a fixture: the numbers live where the scenario is, and
    the assertions read them off the settings object rather than repeating them.
    """
    return (0.02, 0.4)


@pytest.fixture
def backup_record(tmp_path) -> pathlib.Path:
    """Where this suite's control plane reads the host's backup record from — M28.6.

    A path under the test's own ``tmp_path`` which DOES NOT EXIST unless a test writes it,
    so every other test in this zone draws the Overview against "no backup has ever been
    recorded on this host" — which is what a control plane with no backup schedule beside
    it really sees, and what the default (a read-only mount that arrived empty) produces
    in the field.

    A fixture rather than a literal for ``settle_window``'s reason: the file that is ABOUT
    the backup standing overrides it to a record it wrote itself, so the value lives where
    the scenario is, and a value the suite never moves is a value no test can prove is
    read.
    """
    return tmp_path / "backup" / "last-run.json"


@pytest.fixture
async def settings(
    clean_database,
    operator_password_hash: str,
    settle_window: tuple[float, float],
    backup_record: pathlib.Path,
) -> Settings:
    return Settings(
        secret_key=TEST_SECRET_KEY,
        database_url=DATABASE_URL,
        operator_username=OPERATOR_USERNAME,
        operator_password_hash=operator_password_hash,
        public_host="control.test",
        # The in-process client speaks http, so the session cookie must not be
        # https-only or no test could ever hold a session.
        public_https=False,
        # No test in this zone reaches a real node: the two that dial one at all dial a
        # loopback socket this file opened (see ``unanswering_ssh`` below), so the
        # connect ceiling is time the suite spends waiting for a certainty. One second,
        # and the whole suite stops costing minutes — the default of five is a field
        # value, chosen for a lossy link, and nothing here is on a link at all.
        node_connect_timeout=1,
        # The settle window an apply watches a restarted daemon for — M26's second walk.
        # Off its declared default for ``node_connect_timeout``'s first reason and for one
        # of its own: every apply in this suite would otherwise pay two real seconds, and
        # a value the suite never moves is a value no test can prove is read. It comes
        # from a fixture rather than from a literal here so the file that is ABOUT the
        # settling can widen it — see ``settle_window``.
        node_settle_interval=settle_window[0],
        node_settle_timeout=settle_window[1],
        # Moved off its declared default (30) for a different reason than the ceiling
        # above — that one is about the suite's cost, this one is what makes two claims
        # provable. Two screens STATE this window, the Settings row and the audit log's
        # footnote, and both compose it from the live object; with the fixture on the
        # default, a screen that had hardcoded "30 days" would read correctly and every
        # assertion about it would stay green.
        # Nine: not the default, not either bound, and not a value any other test uses.
        # The tests that rely on this assert the premise first, so moving it back shows
        # up as a failure rather than as a test quietly proving nothing.
        audit_retention_days=9,
        # Off its declared default — the read-only mount inside the container — because
        # the suite must not depend on what is on the machine running pytest, and because
        # the one file that is about this points it at a record it wrote.
        backup_record=backup_record,
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
def nothing_retired(monkeypatch) -> None:
    """A fabricated fleet in which no transport is retired — M20's acceptance, round 2.

    THE OTHER HALF OF ``test_a_retired_transport_is_not_offered``'s harness, and the same
    tool pointed the other way: that file fabricates a retirement onto a transport the
    registry offers, to prove the panel reads a declaration rather than a name; this one
    lifts the declaration off the one that carries it, so a test about what a transport
    DOES can still reach both members of the WireGuard family.

    It exists because ``nodes.enable_transport`` now refuses to create a row for a retired
    transport on every route — a retired transport is one whose handshake completes and
    which carries nothing, and minting a fresh complete credential for it is the silent
    failure the charter calls the worst kind. Without this fixture the family tests below
    would each have narrowed to their one un-retired member, which is how a family stops
    being a family: the whole reason they are parametrised is that the allocator, the
    renderer and the refusals must not know one member from the other.

    ONE PATCH POINT, ``services.transports.discover``, because that module is where this
    zone asks whether a transport is retired — every surface and the enable service alike
    read ``retired_transports()``, so a fleet fabricated here is the answer all of them
    get. The metas are REAL ones with one field replaced, so ``profile()`` still loads
    each transport's renderers and parameter model.

    What it does NOT do is weaken the refusal. The code under test is untouched; the test
    is simply asking it about a world in which nothing has been retired. A test that wants
    the refusal itself does not take this fixture.
    """
    fleet = {
        name: dataclasses.replace(meta, retired=None)
        for name, meta in discover().items()
    }
    monkeypatch.setattr(transports_service, "discover", lambda: fleet)


@pytest.fixture
def ws_params() -> dict[str, object]:
    return {
        "port": 8444,
        "server_name": "front.example.com",
        "certificate_path": "/etc/hashi/certs/fullchain.pem",
        "certificate_key_path": "/etc/hashi/certs/privkey.pem",
    }


# --- an SSH endpoint whose behaviour this suite decides (M21.2) --------------
#
# Two tests here need a node the control plane cannot get a session from. They used
# to get one by pointing at a reserved documentation address and trusting that
# nothing routes to it — but what such an address DOES is a property of the host's
# routing table, not of this code: silently dropped here, refused in a millisecond
# on a machine that routes it over a tunnel. Both are the same fact and only one of
# them was the fact the timing assertion needed, so the suite answered differently on
# different machines.
#
# So the endpoint is opened here instead, on loopback, on a port the kernel picks.
# The socket is held for the whole test: while it is bound, nothing else on the host
# can take that port, which is what makes the answer the same every run. Loopback is
# already a hard dependency of this zone — the database is reached over it — so this
# adds no assumption the suite did not already make. It is not a "hardcoded IP" in
# the sense CLAUDE.md forbids either: there is no node here to rotate away from, only
# this machine talking to itself.

# The interface, and the only address in this file that is not a node's.
LOOPBACK = "127.0.0.1"


class LoopbackSSH(NamedTuple):
    """Where a test node's SSH endpoint is, and therefore what happens when it is dialled."""

    host: str
    port: int


# --- a node that accepts an apply (M4.2, moved here in M23) -------------------
#
# Lived in ``test_revocation_push.py`` until M23's round 2, which needed the same node in
# a second file: an apply is also the moment a node STARTS SERVING, and what that must do
# for every existing user is not a fact about revocation. Moved rather than copied,
# because two harnesses standing in for one set of upstream calls is exactly the drift
# ``pinned`` below exists to refuse.
#
# THE BOUNDARY, stated where the double is: this stands in for the five calls in
# ``edge.bootstrap.node_stack`` that touch a host, and for nothing else. What a test using
# it proves is the control plane's own bookkeeping after a push the host accepted. It
# proves nothing about a real daemon reloading, and nothing about a real network.


def _parameters(function) -> list[tuple]:
    """A callable's parameters as a call site depends on them: name, kind, default.

    Annotations are deliberately left out. The doubles leave ``connection`` untyped,
    because typing it would mean importing the very class they exist to stand in for —
    and an annotation is not what breaks a caller. A renamed keyword is.
    """
    return [
        (parameter.name, parameter.kind, parameter.default)
        for parameter in inspect.signature(function).parameters.values()
    ]


def pinned(monkeypatch: pytest.MonkeyPatch, module, name: str, double) -> None:
    """Install a double, refusing if it and the real function have drifted apart.

    The gap this closes: a double is monkeypatched in whether or not it still resembles
    anything. Change ``place_config``'s keyword and the file keeps passing, still green,
    no longer standing in for code that exists — and what it guards is charter criterion
    6, that a revocation reports per node instead of 500-ing. A stale double there buys a
    suite that proves nothing at exactly the moment it matters.

    Fails at fixture setup, naming both signatures, because a drift is a fact about the
    test rather than about the node being simulated.
    """
    real = getattr(module, name)
    assert _parameters(real) == _parameters(double), (
        f"the double for {module.__name__}.{name} no longer matches the real one:\n"
        f"  real:   {inspect.signature(real)}\n"
        f"  double: {inspect.signature(double)}"
    )
    assert inspect.iscoroutinefunction(real) == inspect.iscoroutinefunction(double), (
        f"{module.__name__}.{name} and its double disagree about being a coroutine"
    )
    monkeypatch.setattr(module, name, double)


class _AllPorts(frozenset):
    """A set of port numbers that contains every one of them.

    Used only by ``accepting_nodes`` below, and it exists because
    ``edge.health.listening.is_answering`` asks ``port in bound.get(protocol)`` — so
    "this node holds whatever it was given" has to be expressible as a container rather
    than as a special case inside the double.
    """

    def __contains__(self, _item) -> bool:
        return True


class _EveryProtocol(dict):
    """``bound_ports``' answer for a node holding every port on every protocol."""

    def get(self, _key, _default=None) -> _AllPorts:
        return _AllPorts()


_EVERY_PORT_HELD = _EveryProtocol()


class AcceptingNode:
    """A node that accepts every step of an apply.

    Records the DIGEST of each config it was handed, so ``loaded_digests`` can answer
    with exactly those — which is what makes the "did the daemon come back up on this
    config" check pass honestly rather than by returning a fixed list. Before M1 it
    recorded only the names, and a node that had accepted the bytes and gone on running
    the previous ones would have satisfied that.
    """

    # No host key is learned, so a test using this says nothing about host-key pinning.
    learned_host_key = None

    def __init__(self) -> None:
        self.placed: dict[str, str] = {}

    # Untyped return: the class is its own annotation and py314 still needs a string
    # for that, which this repo's ruff rules reject (UP037).
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False


@pytest.fixture
def accepting_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the five node_stack calls that touch a host, and nothing else."""
    from control.app.services import apply

    def connection_for(target):
        return AcceptingNode()

    # ``NodeConnection`` is replaced by a factory rather than by a function, so it is
    # pinned against the constructor it stands in for and against the surface
    # ``apply_node`` reaches for on a live connection: the async context manager, and
    # the host key it persists on a first successful connect. A double that lost
    # ``learned_host_key`` would make the pinning branch quietly untestable.
    assert _parameters(NodeConnection.__init__)[1:] == _parameters(connection_for), (
        f"the connection double no longer matches NodeConnection.__init__:\n"
        f"  real:   {inspect.signature(NodeConnection.__init__)}\n"
        f"  double: {inspect.signature(connection_for)}"
    )
    for attribute in ("learned_host_key", "__aenter__", "__aexit__"):
        assert hasattr(AcceptingNode, attribute), (
            f"the connection double has no {attribute!r}, which apply_node uses"
        )
    monkeypatch.setattr(apply, "NodeConnection", connection_for)

    async def prepare(connection) -> None:
        return None

    # ``path`` carries the real function's default, which the double had already drifted
    # away from — found by ``pinned`` the moment it was introduced, which is the whole
    # argument for it.
    async def place_config(
        connection, *, transport_name: str, config: str, path: str | None = None
    ) -> None:
        connection.placed[transport_name] = node_stack.digest_of(config)

    async def place_compose(connection, *, compose: str) -> None:
        return None

    async def restart(connection) -> None:
        return None

    async def running_containers(connection) -> node_stack.RunningContainers:
        # A node whose restart DID take: every container comes back on the config it
        # was just handed, and stays. ``digest_of`` is the real one, so this is the
        # value production would compare against.
        #
        # ``started`` is one token per service, CONSTANT for the life of this double —
        # M26's second walk. The apply's check now confirms a container only when two
        # readings an interval apart saw the same life of it, so a double that invented
        # a fresh token each call would model a node in a permanent crash loop and every
        # apply in this suite would fail. A node that is genuinely staying up is what
        # this double has always stood for.
        return node_stack.RunningContainers(
            loaded=dict(connection.placed),
            restarting=(),
            started={name: "one-life" for name in connection.placed},
        )

    async def bound_ports(connection) -> dict[Layer4, frozenset[int]] | None:
        # AND THE SOCKET HALF OF THE SAME "everything works" — M26's third acceptance
        # walk, which taught an apply to ask what is holding each placed config's port.
        # Without this the double has no ``run`` for ``ss`` to reach and every apply in
        # the suite dies inside the settle loop.
        #
        # It answers "held", for every port on every protocol, because that is what this
        # double has always stood for: a node where every step of an apply works. The
        # alternative answers are both wrong for it — ``None`` would make every test here
        # run against a host whose socket table cannot be read, which is a real state with
        # real consequences (an apply that clears no finding), and a table with particular
        # numbers in it would need this fixture to know each row's port, which it has no
        # route to. A test about a host that is NOT serving builds its own fake and says
        # so in its own file.
        return _EVERY_PORT_HELD

    pinned(monkeypatch, listening, "bound_ports", bound_ports)
    pinned(monkeypatch, node_stack, "prepare", prepare)
    pinned(monkeypatch, node_stack, "place_config", place_config)
    pinned(monkeypatch, node_stack, "place_compose", place_compose)
    pinned(monkeypatch, node_stack, "restart", restart)
    pinned(monkeypatch, node_stack, "running_containers", running_containers)


def _bound_loopback_socket() -> socket.socket:
    """A TCP socket holding one ephemeral loopback port, not yet listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # No SO_REUSEADDR on purpose: the exclusivity of the bind is the point. A
        # second process cannot take this port while the test runs, so nothing can
        # answer where the test decided nothing answers.
        sock.bind((LOOPBACK, 0))
    except BaseException:
        # The fixtures' ``finally`` only ever sees a socket this function returned, so
        # a bind that raises has to close its own fd or the descriptor is lost for the
        # rest of the session.
        sock.close()
        raise
    return sock


@pytest.fixture
def unanswering_ssh() -> Iterator[LoopbackSSH]:
    """A port that completes a TCP connection and then says nothing, ever.

    This is what a blocked node looks like from outside, and it is the shape the
    timeout path needs: a refusal would end the connect in a millisecond and the
    ceiling would never be exercised. ``listen()`` without ``accept()`` is deliberate
    — the kernel finishes the handshake into the accept queue by itself, so there is
    no thread to start and none to join, and asyncssh sends its version banner and
    waits for a reply that cannot come until ``connect_timeout`` ends the wait.
    """
    sock = _bound_loopback_socket()
    try:
        sock.listen()
        yield LoopbackSSH(*sock.getsockname())
    finally:
        sock.close()


@pytest.fixture
def refusing_ssh() -> Iterator[LoopbackSSH]:
    """A port that refuses instantly, because it is bound and never listening.

    For the tests that only need "the node could not be reached" and say nothing about
    how long that took: a connect here is one RST from the local kernel, so five
    applies cost milliseconds instead of five seconds. Bound rather than closed-and-
    released, for the port-exclusivity above and because a closed ephemeral port can
    be handed back to the connecting socket as its own source port, at which point TCP
    connects it to itself and the node answers.
    """
    sock = _bound_loopback_socket()
    try:
        yield LoopbackSSH(*sock.getsockname())
    finally:
        sock.close()


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


def assert_plain_reason(reason: str | None, *addresses: str) -> None:
    """The operator was told, in words, why an operation on a node failed.

    Asserts the property M4.4 introduced rather than the sentence it introduced:
    non-empty, one line, prose, no traceback, no bare exception class name, and no
    node address travelling with it (core invariants §6 — a node's address in
    operator-facing text is a step towards a connection record).

    ``addresses`` is EVERY address that names the node under test, and at least one is
    required: the check is worthless in exactly the tests that forget to pass it. There
    is more than one because a node record carries more than one — the address a user
    dials and the address `control` dials over SSH are separate columns, and until
    M21.2 they held the same string here, which is the only reason one argument ever
    looked sufficient. A reason may leak either.
    """
    assert addresses, "assert_plain_reason needs the node's addresses to check for"
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

    for address in addresses:
        assert address not in text, (
            f"the node's address travelled with the reason: {text!r}"
        )
