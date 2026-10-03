"""The routing lists, and the switch that sends their destinations out of an entry — M34.

Revision ID: 0011
Revises: 0010

Two columns on ``nodes`` and four tables. ``direct_routing`` is NOT NULL with a server
default of false, so every existing node is off and renders exactly what it rendered
before; ``direct_resolver`` is nullable with no default, for ``resolver``'s reason — any
value backfilled would be a resolver this project chose. The four tables start empty: no
source is seeded here, because a source is a URL and a URL in a migration is a domain in
code (``CLAUDE.md``). Suggested sources live in configuration
(``HASHI_ROUTING_SUGGESTED_SOURCES``) and become rows only when the owner adds them.

Reversible: the downgrade drops the tables and the columns. Nothing a user holds refers to
any of it; a fleet downgraded with the switch on renders, at its next apply, what it would
have rendered with the switch off.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column(
            "direct_routing", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("nodes", sa.Column("direct_resolver", sa.String(255), nullable=True))

    op.create_table(
        "routing_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "routing_list_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("routing_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("entries", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("invalid", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("hold_reason", sa.String(500), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_one_version_in_force_per_source",
        "routing_list_versions",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in-force'"),
    )
    op.create_table(
        "routing_owner_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list", sa.String(8), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("list", "value", name="uq_routing_owner_entry"),
    )
    op.create_table(
        "routing_schedule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_run_on", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("routing_schedule")
    op.drop_table("routing_owner_entries")
    op.drop_index("uq_one_version_in_force_per_source", table_name="routing_list_versions")
    op.drop_table("routing_list_versions")
    op.drop_table("routing_sources")
    op.drop_column("nodes", "direct_resolver")
    op.drop_column("nodes", "direct_routing")
