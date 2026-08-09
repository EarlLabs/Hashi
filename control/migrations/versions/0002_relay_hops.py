"""Entry→leaf hops: what a node-transport is for, and which row is its far end.

Revision ID: 0002
Revises: 0001

Backlog item 16. The charter's topology is a Russian entry node fronting foreign
leaves, and the tunnel between them is an ordinary transport whose consumer is another
NODE. Two columns record that, and the defaults are the load-bearing part: every
existing row is friend-facing, so the backfill is a server default rather than a data
migration.

``purpose`` is indexed because every subscription render filters on it — the query
that must stay fast when a node has just been blocked and every friend is refreshing
at once. Getting that filter wrong would put an entry↔leaf tunnel into a friend's
subscription, which is why it is a column and not a convention.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "node_transports",
        sa.Column(
            "purpose",
            sa.String(16),
            nullable=False,
            server_default="friends",
        ),
    )
    op.add_column(
        "node_transports",
        sa.Column("peer_node_transport_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_node_transports_purpose", "node_transports", ["purpose"])
    op.create_foreign_key(
        "fk_node_transports_peer",
        "node_transports",
        "node_transports",
        ["peer_node_transport_id"],
        ["id"],
        # SET NULL, not CASCADE: deleting one end of a hop must leave the other end
        # visible and obviously half-configured rather than silently vanishing — an
        # operator who deletes the wrong row needs to SEE that the hop is broken.
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_node_transports_peer", "node_transports", type_="foreignkey")
    op.drop_index("ix_node_transports_purpose", table_name="node_transports")
    op.drop_column("node_transports", "peer_node_transport_id")
    op.drop_column("node_transports", "purpose")
