"""Do the migrations produce the schema the models describe?

WHAT: runs the real ``alembic upgrade head`` against a real database and asks Alembic
      whether anything still differs from the models.
WHY:  core invariants §2 requires every schema change to go through a migration,
      because ``create_all`` against a changed model silently diverges from a live
      database and the failure mode is "every friend is locked out". The rest of this
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
        "HASHI_OPERATOR_PASSWORD_HASH": "unused-for-migrations",
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
