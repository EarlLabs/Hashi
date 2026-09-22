"""Do the migrations produce the schema the models describe?

WHAT: runs the real ``alembic upgrade head`` against a real database and asks Alembic
      whether anything still differs from the models.
WHY:  core invariants §2 requires every schema change to go through a migration,
      because ``create_all`` against a changed model silently diverges from a live
      database and the failure mode is "every user is locked out". The rest of this
      suite builds its tables with ``create_all`` for speed — which means without THIS
      file, a migration that forgot a column would never be noticed until deployment.
HOW:  the migration is run as a SUBPROCESS, with exactly the command
      ``deploy/docker/entrypoint.sh`` uses. That is deliberate: invoking Alembic's
      Python API in-process would prove that some configuration works, not that the
      one shipped in the image does. A broken ``alembic.ini`` or a migrations directory
      missing from the wheel fails here.

      Downgrade is exercised too: a migration that cannot be reversed is one an
      operator cannot back out of at 3am.
"""

import os
import pathlib
import subprocess

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from control.app.models import Base

from .conftest import DATABASE_URL, database_is_available

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "control" / "alembic.ini"


def run_alembic(*arguments: str) -> subprocess.CompletedProcess:
    """Run Alembic the way the container does, against the test database.

    The URL is passed through the environment rather than on the command line, because
    that is how ``env.py`` reads it — and a connection string on a command line is
    world-readable in ``/proc``.
    """
    environment = {
        **os.environ,
        "HASHI_DATABASE_URL": DATABASE_URL,
        "HASHI_SECRET_KEY": "test-only-not-a-real-key-000000000000000000000000",
        # Unused by the migrations themselves, but `env.py` builds the whole Settings
        # object to get the URL — and Settings refuses a hash that is not one, so a
        # placeholder word here would stop every migration.
        "HASHI_OPERATOR_PASSWORD_HASH": "scrypt$32768$8$1$c2FsdHNhbHQ=$aGFzaGhhc2g=",
    }
    return subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "bin" / "alembic"),
            "-c",
            str(ALEMBIC_INI),
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO_ROOT,
        env=environment,
    )


@pytest.fixture
async def empty_database():
    """A database with no tables and no Alembic bookkeeping.

    Dropped rather than created fresh, because the point is to migrate from zero — and
    a leftover ``alembic_version`` row from another test would make ``upgrade head`` a
    no-op that passes without running anything.
    """
    if not await database_is_available():
        pytest.skip(f"no Postgres at {DATABASE_URL} — see tests/control/conftest.py")

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()

    yield DATABASE_URL

    # Left in a usable state for whatever runs next.
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()


async def test_upgrade_head_succeeds_from_an_empty_database(empty_database) -> None:
    """The exact command the container runs on boot, against nothing."""
    result = run_alembic("upgrade", "head")
    assert result.returncode == 0, (
        f"`alembic upgrade head` failed — the container would refuse to boot.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


async def test_migrations_produce_exactly_the_schema_the_models_describe(
    empty_database,
) -> None:
    """After ``upgrade head``, Alembic must see nothing left to change.

    This is the assertion that makes the fast ``create_all`` used by the rest of the
    suite safe. A column added to a model without a migration shows up here as a
    pending difference.
    """
    assert run_alembic("upgrade", "head").returncode == 0

    engine = create_async_engine(DATABASE_URL)

    def differences(connection) -> list:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "include_schemas": False}
        )
        return compare_metadata(context, Base.metadata)

    async with engine.connect() as connection:
        found = await connection.run_sync(differences)
    await engine.dispose()

    # Alembic's own bookkeeping table is not described by our models, and should not be.
    interesting = [item for item in found if "alembic_version" not in str(item)]
    assert interesting == [], (
        "the migrations and the models disagree. Every schema change goes through a "
        f"migration (core invariants §2) — generate one for: {interesting}"
    )


async def test_the_migration_can_be_reversed(empty_database) -> None:
    """A migration an operator cannot back out of is one they cannot deploy at 3am."""
    assert run_alembic("upgrade", "head").returncode == 0

    downgrade = run_alembic("downgrade", "base")
    assert downgrade.returncode == 0, (
        f"downgrade failed:\nstdout:\n{downgrade.stdout}\nstderr:\n{downgrade.stderr}"
    )

    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as connection:
        remaining = (
            await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name <> 'alembic_version'"
                )
            )
        ).scalars().all()
    await engine.dispose()

    assert sorted(remaining) == [], f"downgrade left tables behind: {sorted(remaining)}"


async def test_the_rename_to_users_goes_forward_and_back_without_moving_a_token(
    empty_database,
) -> None:
    """0008 renames ``friends`` to ``users`` both ways, and no subscription moves.

    ``test_the_migration_can_be_reversed`` above proves the whole chain unwinds from an
    EMPTY database, which a rename passes trivially — nothing is there to survive it. So
    this is the other half: a row is put in, the rename is run forward and then back and
    then forward again, and the token that row holds is compared byte for byte each
    time. That token is a bearer credential already on somebody's phone; if a rename
    ever disturbed it, the person would find out by their client going dark, and no
    other test in this file would have noticed.

    Raw SQL rather than the ORM, in the shape the two downgrade tests below already use:
    the models describe the schema at HEAD and this test has to speak to the schema on
    either side of one migration. Nothing here needs a secret box, because a rename
    never opens an encrypted column — which is also why M29.5 can rehearse this against
    a copy of real data without a key.
    """
    assert run_alembic("upgrade", "head").returncode == 0

    engine = create_async_engine(DATABASE_URL)

    async def names_of(kind: str) -> list[str]:
        query = {
            "tables": "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()",
            "credential_columns": "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'credentials'",
            "subscription_columns": "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'subscriptions'",
            "indexes": "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema()",
            "constraints": "SELECT conname FROM pg_constraint",
        }[kind]
        async with engine.connect() as connection:
            return list((await connection.execute(text(query))).scalars().all())

    assert "users" in await names_of("tables")
    assert "friends" not in await names_of("tables")
    assert "user_id" in await names_of("subscription_columns")
    assert "user_id" in await names_of("credential_columns")
    assert "ix_credentials_user_id" in await names_of("indexes")
    assert "ix_subscriptions_user_id" in await names_of("indexes")
    assert "uq_user_node_transport" in await names_of("constraints")

    # One person and the one URL they hold. The digest is what the delivery endpoint
    # looks a request up by, so it is the value that decides whether their client still
    # works — and it is stored, not derived, which is why it can be compared literally.
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO users (id, nickname) VALUES ('user-1', 'nadia')")
        )
        await connection.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, token, token_digest) "
                "VALUES ('sub-1', 'user-1', 'a-token', 'a-digest')"
            )
        )
    await engine.dispose()

    backed_out = run_alembic("downgrade", "0007")
    assert backed_out.returncode == 0, (
        f"stdout:\n{backed_out.stdout}\nstderr:\n{backed_out.stderr}"
    )

    engine = create_async_engine(DATABASE_URL)
    assert "friends" in await names_of("tables")
    assert "users" not in await names_of("tables")
    assert "friend_id" in await names_of("subscription_columns")
    assert "friend_id" in await names_of("credential_columns")
    assert "ix_credentials_friend_id" in await names_of("indexes")
    assert "uq_friend_node_transport" in await names_of("constraints")

    async with engine.connect() as connection:
        held = (
            await connection.execute(
                text(
                    "SELECT f.nickname, s.token, s.token_digest FROM friends AS f "
                    "JOIN subscriptions AS s ON s.friend_id = f.id"
                )
            )
        ).all()
    await engine.dispose()
    assert [tuple(row) for row in held] == [("nadia", "a-token", "a-digest")]

    assert run_alembic("upgrade", "head").returncode == 0

    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as connection:
        held = (
            await connection.execute(
                text(
                    "SELECT u.nickname, s.token, s.token_digest FROM users AS u "
                    "JOIN subscriptions AS s ON s.user_id = u.id"
                )
            )
        ).all()
    await engine.dispose()
    assert [tuple(row) for row in held] == [("nadia", "a-token", "a-digest")]


async def test_the_stored_words_go_forward_and_back_with_every_other_row_untouched(
    empty_database,
) -> None:
    """0009 rewrites two columns' VALUES both ways, and rewrites nothing else.

    The migration above renames names; this one is the only one in M29 that writes to
    rows, so a schema comparison cannot see whether it worked. The rows are therefore
    seeded BEFORE the upgrade, at 0008, in the old vocabulary — which is the only way to
    watch an ``UPDATE`` move them — and read back at head and again after the downgrade.

    Three kinds of row are planted on purpose, because two of them are what the
    migration must NOT touch: a value the rename covers (``friends``, ``friend-added``,
    ``friend-revoked``), a value from the same column's other members (``relay-entry``,
    ``node-added``), and a value nothing ever declared. The last one is the case the
    migration's header decides rather than discovers: it is left exactly as found,
    because refusing on it would abort the ``alembic upgrade head`` the entrypoint runs
    on every boot over a row the application already cannot read back.

    The empty-table case is covered by the three tests around this one — the fixture
    hands over a database with no tables at all — so it is not re-staged here.

    Raw SQL for the reason the test above gives: the models describe HEAD and this has
    to speak to both sides of one migration. Nothing here opens an encrypted column, so
    no secret box is needed, which is what lets M29.5 rehearse it without a key.
    """
    assert run_alembic("upgrade", "0008").returncode == 0

    engine = create_async_engine(DATABASE_URL)

    async def rows(query: str) -> list[tuple]:
        async with engine.connect() as connection:
            return [tuple(row) for row in (await connection.execute(text(query))).all()]

    async def purposes() -> list[tuple]:
        return await rows(
            "SELECT id, purpose FROM node_transports ORDER BY id"
        )

    async def actions() -> list[tuple]:
        return await rows("SELECT id, action FROM audit_entries ORDER BY id")

    async def default_for(table: str, column: str) -> str | None:
        found = await rows(
            "SELECT column_default, data_type FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = '{column}'"
        )
        # Neither column is a Postgres native ENUM and 0009 depends on that: ``purpose``
        # is VARCHAR(16) from 0002 and ``action`` is VARCHAR(32) from 0003, read back
        # through ``EnumText``, which is Python-side only. A native type would need
        # ``ALTER TYPE ... RENAME VALUE`` instead of an ``UPDATE``.
        assert found[0][1] == "character varying", found
        return found[0][0]

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO nodes (id, name, address, location_label, state) "
                "VALUES ('node-9', 'the-word', '192.0.2.9', 'Testland', 'active')"
            )
        )
        for row_id, purpose in (
            ("row-a", "friends"),
            ("row-b", "relay-entry"),
            ("row-c", "not-a-purpose"),
        ):
            await connection.execute(
                text(
                    "INSERT INTO node_transports "
                    "(id, node_id, transport_name, config_name, params, secrets, "
                    " purpose, enabled) "
                    "VALUES (:id, 'node-9', 'a-transport', :config_name, '{}', '{}', "
                    " :purpose, true)"
                ),
                # One config name per row: ``uq_node_transport_config_name`` is what
                # stops two rows writing the same file on one host.
                {"id": row_id, "config_name": row_id, "purpose": purpose},
            )
        for row_id, action in (
            ("entry-a", "friend-added"),
            ("entry-b", "friend-revoked"),
            ("entry-c", "node-added"),
            ("entry-d", "not-an-action"),
        ):
            await connection.execute(
                text("INSERT INTO audit_entries (id, action) VALUES (:id, :action)"),
                {"id": row_id, "action": action},
            )

    at_0008_purposes = await purposes()
    at_0008_actions = await actions()
    assert at_0008_purposes == [
        ("row-a", "friends"),
        ("row-b", "relay-entry"),
        ("row-c", "not-a-purpose"),
    ]
    assert await default_for("node_transports", "purpose") == "'friends'::character varying"

    assert run_alembic("upgrade", "head").returncode == 0

    assert await purposes() == [
        ("row-a", "users"),
        ("row-b", "relay-entry"),
        ("row-c", "not-a-purpose"),
    ]
    assert await actions() == [
        ("entry-a", "user-added"),
        ("entry-b", "user-revoked"),
        ("entry-c", "node-added"),
        ("entry-d", "not-an-action"),
    ]
    # The default moves with the values, or a row inserted without an explicit purpose
    # by anything other than this application arrives holding a retired word.
    assert await default_for("node_transports", "purpose") == "'users'::character varying"

    backed_out = run_alembic("downgrade", "0008")
    assert backed_out.returncode == 0, (
        f"stdout:\n{backed_out.stdout}\nstderr:\n{backed_out.stderr}"
    )

    # Byte for byte what was seeded, including the two kinds of row the migration was
    # never allowed to move. This is the assertion that makes "reversible" a fact.
    assert await purposes() == at_0008_purposes
    assert await actions() == at_0008_actions
    assert await default_for("node_transports", "purpose") == "'friends'::character varying"

    # And forward once more, because an operator who backs out is expected to deploy
    # again — the second upgrade must land on the same values as the first.
    assert run_alembic("upgrade", "head").returncode == 0
    assert await purposes() == [
        ("row-a", "users"),
        ("row-b", "relay-entry"),
        ("row-c", "not-a-purpose"),
    ]
    assert await actions() == [
        ("entry-a", "user-added"),
        ("entry-b", "user-revoked"),
        ("entry-c", "node-added"),
        ("entry-d", "not-an-action"),
    ]

    await engine.dispose()


async def test_the_data_migration_names_no_row_in_what_it_prints(empty_database) -> None:
    """0009 touches the audit table, so its output is checked for a person's name.

    The trail is the one table in this product that could become a record of who used
    the service, and a data migration over it is exactly where a well-meant ``logger``
    call lands. The migration prints Alembic's own revision line and nothing else; this
    plants labels a person would recognise and asserts none of them, and no row count
    from that table, reaches stdout or stderr on the way through or on the way back.
    """
    assert run_alembic("upgrade", "0008").returncode == 0

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO audit_entries (id, action, first_label) "
                "VALUES ('entry-1', 'friend-added', 'polina')"
            )
        )
    await engine.dispose()

    forward = run_alembic("upgrade", "head")
    assert forward.returncode == 0, f"{forward.stdout}\n{forward.stderr}"
    backward = run_alembic("downgrade", "0008")
    assert backward.returncode == 0, f"{backward.stdout}\n{backward.stderr}"

    for result in (forward, backward):
        printed = result.stdout + result.stderr
        assert "polina" not in printed, printed
        assert "entry-1" not in printed, printed
        # The revision is named — that is Alembic's line, and it is the only thing here
        # that should identify anything.
        assert "0009" in printed, printed


async def test_upgrade_is_idempotent(empty_database) -> None:
    """Running it twice must be a no-op, because the entrypoint runs it on every boot.

    A container that restarts — which is what ``restart: unless-stopped`` guarantees it
    will do — must not fail its second boot on "table already exists".
    """
    assert run_alembic("upgrade", "head").returncode == 0
    second = run_alembic("upgrade", "head")
    assert second.returncode == 0, (
        f"a second `upgrade head` failed, so the container cannot restart:\n{second.stderr}"
    )


async def test_the_downgrade_refuses_while_a_pool_is_in_use(empty_database) -> None:
    """0006 stops rather than dropping addresses somebody's device is configured with.

    The pre-flight 0004 established, applied to a column whose loss is silent: pre-M17
    code reads no address off a credential, so every user on a sized transport would fall
    back to the one address in its parameters — which is either a render refused for two
    peers on one address, with every push to that node blocked including a revocation's,
    or, for a single holder further up the pool, a config that looks right and carries
    nothing.

    Seeded through raw SQL rather than the ORM on purpose: the encrypted columns need a
    bound secret box, and nothing here reads a value back. What is under test is the
    QUERY the downgrade makes and the sentence it refuses with.
    """
    assert run_alembic("upgrade", "head").returncode == 0

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO nodes (id, name, address, location_label, state) "
                "VALUES ('node-1', 'the-field', '192.0.2.1', 'Testland', 'active')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO node_transports "
                "(id, node_id, transport_name, config_name, params, secrets, purpose, "
                " enabled, pool_size) "
                "VALUES ('row-1', 'node-1', 'a-transport', 'a-transport', '{}', '{}', "
                "'users', true, 4)"
            )
        )
        await connection.execute(
            text("INSERT INTO users (id, nickname) VALUES ('user-1', 'zoya')")
        )
        await connection.execute(
            text(
                "INSERT INTO credentials "
                "(id, user_id, node_transport_id, subject, secrets, tunnel_address, "
                " tunnel_address_digest) "
                "VALUES ('cred-1', 'user-1', 'row-1', 'x', '{}', 'x', 'a-digest')"
            )
        )
    await engine.dispose()

    refused = run_alembic("downgrade", "0005")

    assert refused.returncode != 0, (
        "the downgrade dropped a column holding addresses that are in use:\n"
        f"{refused.stdout}\n{refused.stderr}"
    )
    # The node, which is what the operator can act on — and nothing about the person or
    # the address, which is the record this project does not keep.
    assert "node-1" in refused.stderr, refused.stderr
    # And nothing about the person or their address, which is the record this project
    # does not keep — not even in a boot log nobody is reading at the time.
    assert "a-digest" not in refused.stderr, refused.stderr
    assert "zoya" not in refused.stderr, refused.stderr

    # And nothing was changed: the columns are still there, so a re-run of the upgrade
    # is a no-op rather than a repair.
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as connection:
        columns = (
            await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'credentials'"
                )
            )
        ).scalars().all()
    await engine.dispose()
    assert "tunnel_address" in columns and "tunnel_address_digest" in columns


async def test_the_downgrade_still_works_where_no_pool_is_in_use(empty_database) -> None:
    """The other half: a row nobody holds an address on backs out cleanly.

    Without this the refusal above would be indistinguishable from a downgrade that
    cannot run at all — which is the failure ``test_the_migration_can_be_reversed``
    exists to catch and would then be catching for the wrong reason.
    """
    assert run_alembic("upgrade", "head").returncode == 0

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO nodes (id, name, address, location_label, state) "
                "VALUES ('node-2', 'untouched', '192.0.2.2', 'Testland', 'active')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO node_transports "
                "(id, node_id, transport_name, config_name, params, secrets, purpose, "
                " enabled, pool_size) "
                "VALUES ('row-2', 'node-2', 'a-transport', 'a-transport', '{}', '{}', "
                "'users', true, 4)"
            )
        )
    await engine.dispose()

    reversed_cleanly = run_alembic("downgrade", "0005")
    assert reversed_cleanly.returncode == 0, (
        f"stdout:\n{reversed_cleanly.stdout}\nstderr:\n{reversed_cleanly.stderr}"
    )
