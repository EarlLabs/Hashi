"""The person who uses hashi is a user: ``friends`` becomes ``users``.

Revision ID: 0008
Revises: 0007

M29 (``docs/decisions.md``, 2026-09-22). The panel has said *users* since it was
written and everything underneath it said *friends*, so the operator read one word and
the schema held another. This is the half of that rename the database can see.

Renames only. **Not one row is read, written or moved**, and no column changes type,
width, nullability or default — so there is nothing here that can fail on data, and
nothing that depends on ``HASHI_SECRET_KEY``: the encrypted columns are not opened,
because a rename never looks inside them. In particular every ``subscriptions`` row
keeps its ``token`` and its ``token_digest`` byte for byte, which is the reason a
subscription URL somebody's phone already holds still resolves after this runs, and
still resolves after it is reversed.

WHAT IS RENAMED, and it is everything that names the old word:

* the table ``friends`` → ``users``;
* ``subscriptions.friend_id`` → ``user_id`` and ``credentials.friend_id`` → ``user_id``;
* the two indexes over those columns, ``ix_subscriptions_friend_id`` and
  ``ix_credentials_friend_id``, because SQLAlchemy derives an ``index=True`` name from
  the column and the model would otherwise disagree with the database forever;
* ``uq_friend_node_transport`` → ``uq_user_node_transport``, the constraint that makes
  revocation countable — one credential per person per node-transport.

The two foreign keys and the primary/unique constraints on the table are renamed too,
but GUARDED: their names (``subscriptions_friend_id_fkey``, ``friends_pkey`` and so on)
were chosen by Postgres rather than written in ``0001``, so a database assembled some
other way may not have them. Nothing in this repository reads those names, so a
database that does not carry them is left with its own and is otherwise correct —
whereas an unguarded ``ALTER TABLE ... RENAME CONSTRAINT`` that misses would abort the
boot ``deploy/docker/entrypoint.sh`` performs on every restart. What ``0001`` named
itself is renamed unguarded, because a database missing one of those is not one this
chain produced and stopping is the right answer.

REVERSIBLE IS THE REQUIREMENT, NOT A NICETY. There is no way to delete a node record in
this product, and this milestone must not add a second irreversible act to it. So
``downgrade`` is the exact inverse, statement for statement in reverse order, and puts
back every name ``0007`` left behind — the table, both columns, both indexes, the
unique constraint and the guarded four. An operator who deploys M29 and backs it out
lands on a schema the pre-M29 code reads, with the same rows in it and the same tokens
on the same devices. Unlike ``0004`` and ``0006`` this downgrade has nothing to refuse
over: those dropped something a row could be holding, and a rename holds nothing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("friends", "users")
    _rename_constraint_if_present("users", "friends_pkey", "users_pkey")
    _rename_constraint_if_present("users", "friends_nickname_key", "users_nickname_key")

    op.alter_column("subscriptions", "friend_id", new_column_name="user_id")
    op.execute("ALTER INDEX ix_subscriptions_friend_id RENAME TO ix_subscriptions_user_id")
    _rename_constraint_if_present(
        "subscriptions", "subscriptions_friend_id_fkey", "subscriptions_user_id_fkey"
    )

    op.alter_column("credentials", "friend_id", new_column_name="user_id")
    op.execute("ALTER INDEX ix_credentials_friend_id RENAME TO ix_credentials_user_id")
    op.execute(
        "ALTER TABLE credentials "
        "RENAME CONSTRAINT uq_friend_node_transport TO uq_user_node_transport"
    )
    _rename_constraint_if_present(
        "credentials", "credentials_friend_id_fkey", "credentials_user_id_fkey"
    )


def downgrade() -> None:
    _rename_constraint_if_present(
        "credentials", "credentials_user_id_fkey", "credentials_friend_id_fkey"
    )
    op.execute(
        "ALTER TABLE credentials "
        "RENAME CONSTRAINT uq_user_node_transport TO uq_friend_node_transport"
    )
    op.execute("ALTER INDEX ix_credentials_user_id RENAME TO ix_credentials_friend_id")
    op.alter_column("credentials", "user_id", new_column_name="friend_id")

    _rename_constraint_if_present(
        "subscriptions", "subscriptions_user_id_fkey", "subscriptions_friend_id_fkey"
    )
    op.execute("ALTER INDEX ix_subscriptions_user_id RENAME TO ix_subscriptions_friend_id")
    op.alter_column("subscriptions", "user_id", new_column_name="friend_id")

    _rename_constraint_if_present("users", "users_nickname_key", "friends_nickname_key")
    _rename_constraint_if_present("users", "users_pkey", "friends_pkey")
    op.rename_table("users", "friends")


def _rename_constraint_if_present(table: str, old: str, new: str) -> None:
    """Rename a constraint Postgres named for us, or leave it alone if it is not there.

    ``ALTER TABLE ... RENAME CONSTRAINT`` has no ``IF EXISTS``, and the four names this
    is used for were never written down in a migration — Postgres derived them from
    ``0001``'s ``primary_key``, ``unique`` and ``ForeignKeyConstraint``. No code, no
    model and no test in this repository reads them, so the cost of skipping one is a
    database whose foreign key is still called ``..._friend_id_fkey`` while its column
    is ``user_id``: untidy and entirely inert. The cost of NOT skipping it is a control
    plane that will not boot, since the entrypoint runs ``alembic upgrade head`` on
    every start.

    Parameters go through bound values rather than into the string, and the names that
    do reach the statement are the literals above — never anything read from a row.
    """
    present = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = :old AND conrelid = to_regclass(:table)"
            ),
            {"old": old, "table": table},
        )
        .scalar()
    )
    if present:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')
