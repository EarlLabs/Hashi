"""Does a link somebody already holds survive M29's rename of the person who holds it?

WHAT: one subscription, issued while the database is on the FAR side of ``0008``/``0009``
      from head, is carried across the rename and then fetched from ``/sub/{token}`` the
      way a user's client fetches it. Three claims, and they are three different
      assertions: it still **resolves**, it returns the **same material** byte for byte,
      and it is still reachable at the **same token**.
WHY:  M29 renames *friend* to *user* across ~3650 occurrences, and the milestone's
      sharpest promise is that nothing on anybody's device changes. ``/sub/{token}``
      contains no such word, so the promise ought to hold by construction — but "ought
      to" and "does" are different claims and only one of them is worth having. M29.5
      established it once, by hand, on a copy of real data; this is the regression that
      keeps it true, so that a LATER change which quietly breaks it goes red here
      instead of going dark on thirty phones.

      ``test_migrations.py``'s
      ``test_the_rename_to_users_goes_forward_and_back_without_moving_a_token`` is the
      nearest thing to this and it stops one layer short: it proves the STORED
      token is unmoved, through raw SQL, with no application in the picture. What a
      device receives is rendered from that row and several others at fetch time, so
      "the token is still there" does not imply "their client still works".
HOW:  the pre-migration world is constructed by the ``0008``/``0009`` DOWNGRADE rather
      than by seeding raw rows into a ``friends`` table. That is the one construction
      whose faithfulness this file can also check, and it does: between the downgrade and
      the upgrade it asserts the subscription really is sitting in ``friends`` /
      ``friend_id`` with ``purpose = 'friends'``, which is the schema and the vocabulary
      the row would have been written into on 2026-09-21. Seeding a `friends` table by
      hand would model the same state and prove nothing about whether a REAL row reaches
      it, and it could not produce ciphertext for the six encrypted columns without
      reimplementing the secret box.

      The baseline the "same material" claim compares against is therefore captured
      from the running application BEFORE anything is migrated — both shapes of the
      response, digested — which is what makes this a before/after measurement rather
      than an opinion about what the body ought to contain. Nothing about the body's
      format is asserted; a rendering change that affects everybody is not this file's
      business and must not turn it red.

      ``clean_database`` is overridden here so the schema comes from the real migration
      chain instead of from ``create_all``: this file has to move between two revisions,
      and a metadata-built schema has no ``alembic_version`` to move from.

      THE TOKEN IS A BEARER CREDENTIAL AND THIS FILE FETCHES IT. Nothing below puts a
      token, a digest or a response body into an assertion message, and the last
      assertion in the long test is that the token reached no log record and no line of
      Alembic's output — a test that fetches this path is itself a new place the path
      could be recorded.
"""

import base64
import contextlib
import hashlib
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from control.app.main import create_app
from control.app.models import NodeState
from control.app.services import nodes
from edge.registry import SubscriptionFormat, discover

from .conftest import (
    DATABASE_URL,
    OPERATOR_PASSWORD,
    OPERATOR_USERNAME,
    database_is_available,
)
from .test_migrations import run_alembic

# The revision the fleet was on before M29 touched it: 0008 renames the table on top of
# it and 0009 rewrites the two stored words on top of that. Named once, because "the
# state a subscription was issued in" is the premise of every assertion here.
BEFORE_THE_RENAME = "0007"

# Which transports in this image serialise into each shape. Resolved from the registry
# rather than named, so this file never becomes a place that knows a protocol by name —
# and so it follows the image rather than a literal when one is added or retired.
URI_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.V1_URI_LIST in meta.subscription_formats and not meta.retired
)
FILE_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
    and not meta.retired
)

# Parameters for the file-shaped transport. The magic headers are an AmneziaWG thing and
# are ignored by a plain WireGuard parameter model, which is why one mapping serves
# whichever member of the family this image ships.
FILE_TRANSPORT_PARAMS: dict[str, object] = {
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
    "port": 51820,
    "tunnel_address": "10.20.0.1/24",
    "peer_tunnel_address": "10.20.0.2/24",
}

# Room enough that no test here is ever about the pool's edges.
POOL_SIZE = 200

# Every column that holds what a device is handed, or what it is handed under. Read as a
# digest per column rather than as rows, which is M29.5's rule and the reason this file
# can compare the whole corpus without a nickname, an address or a token appearing
# anywhere: ``md5(string_agg(...))`` names nobody.
#
# Both tables that hold per-person material keep their NAMES across 0008 — only the
# foreign key column is renamed — so one census speaks to the schema on either side of
# the migration without knowing which side it is on. That is why no query below mentions
# ``users``, ``friends``, ``user_id`` or ``friend_id``.
CARRIED_MATERIAL: dict[str, tuple[str, ...]] = {
    "subscriptions": ("token", "token_digest", "revoked_at"),
    "credentials": ("subject", "secrets", "tunnel_address", "tunnel_address_digest"),
    "node_transports": ("secrets", "params"),
    "nodes": ("ssh_private_key", "address"),
}


@pytest.fixture
async def clean_database() -> None:
    """Override: the schema the MIGRATIONS produce, not the one ``create_all`` does.

    Deliberately shadows ``conftest.clean_database`` for this module only, which is what
    lets the ``settings``, ``app`` and ``session`` fixtures above it stay exactly as
    every other file in this zone uses them. A metadata-built schema carries no
    ``alembic_version`` row, so nothing could be downgraded from it — and this file's
    whole subject is a database that moves between two revisions with somebody's
    subscription already in it.
    """
    if not await database_is_available():
        pytest.skip(
            f"no Postgres at {DATABASE_URL} — the control zone's tests need a real "
            "database (the rulebook forbids SQLite here). Start one with "
            "`make up-dev`, or set HASHI_TEST_DATABASE_URL."
        )

    await _strip_the_database()
    upgraded = run_alembic("upgrade", "head")
    assert upgraded.returncode == 0, (
        f"the chain would not build the schema:\n{upgraded.stdout}\n{upgraded.stderr}"
    )

    yield

    # Left the way the rest of the zone expects to find it: no tables and no Alembic
    # bookkeeping, so the next file's ``create_all`` starts from nothing and
    # ``test_migrations.py`` still migrates from zero.
    await _strip_the_database()


async def _strip_the_database() -> None:
    """Every table in the schema, whatever it is called, and Alembic's bookkeeping.

    NOT ``Base.metadata.drop_all``, which is what the rest of this zone uses and what
    ``test_migrations.py``'s ``empty_database`` uses. The metadata describes HEAD, so it
    knows ``users`` and has never heard of ``friends`` — and this is the one file that
    deliberately puts the database into a state where the table is called ``friends``.
    A failure between the downgrade and the upgrade would leave that table standing,
    ``drop_all`` would walk past it, and the NEXT run of anything would die on
    ``relation "friends" already exists`` from ``0001``. That trap is recorded in M29.3's
    step notes as the one that bites every developer once; this file would have made it
    bite on every red run.
    """
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DO $$ DECLARE found record; BEGIN "
                "FOR found IN SELECT tablename FROM pg_tables "
                "WHERE schemaname = current_schema() LOOP "
                "EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(found.tablename) "
                "|| ' CASCADE'; END LOOP; END $$"
            )
        )
    await engine.dispose()


@contextlib.asynccontextmanager
async def a_running_panel(settings):
    """The real application over ASGI, an operator logged in, and its pool closed after.

    Not the ``client`` fixture, because this file needs two application lifetimes with a
    migration between them: asyncpg caches prepared statements per connection, and a pool
    carried across a table rename and back is a source of flakes that says nothing about
    the code under test. Disposing is also what makes the schema movable at all.
    """
    application = create_app(settings)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://control.test",
            follow_redirects=False,
        ) as handle:
            login = await handle.post(
                "/panel/login",
                data={"username": OPERATOR_USERNAME, "password": OPERATOR_PASSWORD},
            )
            assert login.status_code == 303, "the test operator could not log in"
            yield handle, application
    finally:
        await application.state.database.dispose()


async def serving_node(client, application, *, name, address, transport_name, params):
    """A node in service with one transport enabled — the shape a user can be granted on.

    The state change goes through the service rather than through a route because that is
    how the rest of this zone does it, and it is the moment every existing user is handed
    a credential on the node.
    """
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]

    body: dict[str, object] = {"transport_name": transport_name, "params": params}
    if discover()[transport_name].peer_address is not None:
        body["pool_size"] = POOL_SIZE
    enabled = await client.post(f"/api/nodes/{node_id}/transports", json=body)
    assert enabled.status_code == 201, enabled.text

    async for session in application.state.database.session():
        await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
        break
    return node_id


async def census() -> dict[str, str]:
    """A digest per column of everything a subscription is rendered out of.

    One short-lived engine per call: this is read between migrations, when no application
    is holding the database, and a pool left open across an ``ALTER TABLE`` is the thing
    ``a_running_panel`` exists to avoid.
    """
    engine = create_async_engine(DATABASE_URL)
    taken: dict[str, str] = {}
    try:
        async with engine.connect() as connection:
            for table, columns in CARRIED_MATERIAL.items():
                for column in columns:
                    digest = (
                        await connection.execute(
                            text(
                                "SELECT md5(coalesce(string_agg("
                                f"{column}::text, '|' ORDER BY id), ''))"
                                f" FROM {table}"
                            )
                        )
                    ).scalar_one()
                    taken[f"{table}.{column}"] = digest
    finally:
        await engine.dispose()
    return taken


def fingerprint(response) -> str:
    """What this response's body is, said in a way that can appear in a failure message.

    The two shapes of ``/sub/{token}`` are the user's own key material; a comparison of
    the bytes themselves puts both operands into pytest's report the moment it fails,
    which is a credential in a CI log. Same rule as ``census`` above and M29.5's: compare
    by digest, print nothing that identifies anybody.
    """
    return hashlib.sha256(response.content).hexdigest()


async def one_value(query: str):
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(text(query))).scalar_one()
    finally:
        await engine.dispose()


async def test_a_subscription_issued_before_the_rename_still_resolves_to_the_same_bytes(
    settings, caplog
) -> None:
    """The milestone's promise, as an assertion: nothing on anybody's device changed.

    Read as a sequence: a user is given a link while the fleet is in the pre-rename
    world, the rename runs underneath them, and their client fetches the same URL it has
    always fetched. If that returns anything other than the bytes it returned before,
    somebody has to re-import a config and M29 was done wrong.

    A second, revoked user rides along, because "still resolves" only means something
    beside a link that must NOT: a migration that resurrected a withdrawn subscription
    would satisfy every other assertion in this file.
    """
    if not URI_TRANSPORTS or not FILE_TRANSPORTS:
        pytest.skip(
            "this image ships no transport in one of the two subscription shapes, so "
            "what a device receives cannot be compared across the migration"
        )

    # DEBUG, over everything, for the last assertion in this test: the question is not
    # whether the token is logged at the level an operator runs, it is whether any line
    # anywhere in the application writes it down.
    caplog.set_level(logging.DEBUG)
    # EXCEPT THE TEST CLIENT ITSELF, WHICH DOES. ``httpx._client`` logs
    # "HTTP Request: GET http://control.test/sub/<token> ..." at INFO on every request,
    # so any test in this zone that fetches this path with logging turned up writes a
    # live bearer credential into the captured log — and pytest prints that log whenever
    # the test fails. Nothing in `control` does this; the client does. Muted here rather
    # than exempted from the assertion below, so that removing this line turns the test
    # red instead of quietly re-opening the leak.
    caplog.set_level(logging.WARNING, logger="httpx")

    # --- the link, issued through the real panel ---------------------------------
    #
    # The application cannot speak to the pre-rename schema — its models describe head —
    # so the subscription is issued at head and pushed back across the rename below.
    # What makes that a faithful model of a link issued in September, rather than a round
    # trip for its own sake, is asserted after the downgrade: the row lands in
    # ``friends``, under ``friend_id``, on a transport whose purpose reads ``friends``.
    async with a_running_panel(settings) as (client, application):
        uri_node = await serving_node(
            client,
            application,
            name="uri-node",
            address="192.0.2.30",
            transport_name=URI_TRANSPORTS[0],
            params={
                "port": 8443,
                "decoy_host": "www.example.com",
                "decoy_port": 443,
                "server_names": ["www.example.com"],
            },
        )
        file_node = await serving_node(
            client,
            application,
            name="file-node",
            address="192.0.2.31",
            transport_name=FILE_TRANSPORTS[0],
            params=FILE_TRANSPORT_PARAMS,
        )

        held = (await client.post("/api/users", json={"nickname": "nadia"})).json()
        withdrawn = (await client.post("/api/users", json={"nickname": "polina"})).json()
        token = (
            await client.get(f"/api/users/{held['id']}/subscription")
        ).json()["url"].rsplit("/", 1)[-1]
        dead_token = (
            await client.get(f"/api/users/{withdrawn['id']}/subscription")
        ).json()["url"].rsplit("/", 1)[-1]
        await client.post(f"/api/users/{withdrawn['id']}/revoke")

        # PUT THE FLEET BACK IN SERVICE, and this is not tidying. No node in this zone
        # has an SSH key, so the re-push a revocation fans out cannot land and both nodes
        # are marked degraded by it — at which point the OTHER user's document renders
        # empty, and every byte comparison below would compare nothing to nothing and
        # pass. The revocation itself is not what this test is about; what it needs from
        # it is one link that must stay dead beside one that must not.
        async for session in application.state.database.session():
            for node_id in (uri_node, file_node):
                await nodes.set_node_state(
                    session, node_id=node_id, state=NodeState.ACTIVE
                )
            break

        # What a device is handed, in both shapes, kept as a fingerprint. The contents
        # are never inspected: the claim is that they do not MOVE, and an assertion
        # about what they contain would make an unrelated rendering change look like a
        # broken migration. A digest rather than the bytes because a failing comparison
        # puts both operands in the report, and these bytes ARE the user's key material.
        document = await client.get(f"/sub/{token}")
        archive = await client.get(
            f"/sub/{token}", params={"format": SubscriptionFormat.CLIENT_CONFIG_FILE}
        )
        assert document.status_code == 200
        assert archive.status_code == 200
        handed_over = (fingerprint(document), fingerprint(archive))
        # The premise: an empty document would satisfy every comparison below.
        assert base64.b64decode(document.text).strip(), (
            "the user was handed an empty subscription before the migration, so this "
            "test would prove nothing about what survives it"
        )
        assert (await client.get(f"/sub/{dead_token}")).status_code == 404

    material_when_issued = await census()

    # --- back across the rename: the schema and the words the row was written under ---
    backed_out = run_alembic("downgrade", BEFORE_THE_RENAME)
    assert backed_out.returncode == 0, (
        f"stdout:\n{backed_out.stdout}\nstderr:\n{backed_out.stderr}"
    )

    assert await one_value("SELECT to_regclass('users') IS NULL") is True
    assert await one_value("SELECT count(*) FROM friends") == 2
    assert await one_value(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'subscriptions' AND column_name = 'friend_id'"
    ) == 1
    # The stored word too, not only the schema: this is the state 0009 exists to move,
    # and a row sitting here on ``purpose = 'users'`` would mean the pre-migration world
    # below is only half of one.
    assert await one_value(
        "SELECT count(*) FROM node_transports WHERE purpose = 'friends'"
    ) == 2
    assert await census() == material_when_issued, (
        "the rename disturbed a column a subscription is rendered out of"
    )

    # --- and forward, over a subscription that was already there ------------------
    forward = run_alembic("upgrade", "head")
    assert forward.returncode == 0, f"stdout:\n{forward.stdout}\nstderr:\n{forward.stderr}"
    assert await census() == material_when_issued, (
        "the rename disturbed a column a subscription is rendered out of"
    )

    async with a_running_panel(settings) as (client, _):
        after_document = await client.get(f"/sub/{token}")
        after_archive = await client.get(
            f"/sub/{token}", params={"format": SubscriptionFormat.CLIENT_CONFIG_FILE}
        )

        # 1. It still resolves. Their client fetches the URL it has always fetched.
        assert after_document.status_code == 200, (
            "a subscription issued before the rename stopped resolving after it — "
            "every user holding one would have to re-import a config"
        )
        assert after_archive.status_code == 200

        # 2. The same material, byte for byte, in both shapes.
        assert fingerprint(after_document) == handed_over[0], (
            "the same link returned different bytes after the rename"
        )
        assert fingerprint(after_archive) == handed_over[1], (
            "the same link returned a different archive after the rename"
        )

        # 3. The same token. Nothing was reissued behind the operator's back — the panel
        #    still shows the URL the user already has, and there is still exactly one
        #    subscription per person rather than a second one beside it.
        still_shown = (
            await client.get(f"/api/users/{held['id']}/subscription")
        ).json()["url"]
        assert still_shown.endswith(token), "the rename moved the user's subscription URL"
        assert await one_value("SELECT count(*) FROM subscriptions") == 2

        # And the link that must stay dead is still dead, indistinguishably.
        assert (await client.get(f"/sub/{dead_token}")).status_code == 404

    # The path is a bearer credential, so a test that fetches it twice is a new place it
    # could be written down. Reported by LOGGER NAME: naming the record would put the
    # token in the failure message, which is the leak this asserts against.
    said_it = sorted(
        {
            record.name
            for record in caplog.records
            if token in record.getMessage() or dead_token in record.getMessage()
        }
    )
    assert said_it == [], f"a subscription token reached a log record from: {said_it}"
    for result in (backed_out, forward):
        printed = result.stdout + result.stderr
        assert token not in printed and dead_token not in printed, (
            "the migration printed a subscription token"
        )
