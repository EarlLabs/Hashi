"""Alembic environment for the control plane.

WHAT: wires Alembic to the application's models and to the configured database.
WHY:  the URL comes from ``Settings`` rather than from ``alembic.ini`` so there is
      exactly one place a connection string is configured, and so no credential is
      ever committed.
HOW:  ``alembic -c control/alembic.ini upgrade head``. Runs in "online" mode
      against a synchronous connection borrowed from the async engine — Alembic's
      migration code is synchronous, and ``run_sync`` is the supported bridge.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# Importing the package (not just Base) is what registers every table on the
# metadata. Import one model short and autogenerate silently proposes dropping it.
from control.app.models import Base
from control.app.settings import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """The URL to migrate, from the same settings the application reads."""
    return Settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it — for review, never for deploys."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # On by default so a widened column or a changed enum is noticed by
        # autogenerate rather than drifting silently between model and database.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
