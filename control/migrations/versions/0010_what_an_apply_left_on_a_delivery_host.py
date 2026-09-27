"""What the last apply actually placed on a host to serve refreshes.

Revision ID: 0010
Revises: 0009

M27.7. The Nodes screen claimed *"the last apply put a listener on this host"* and gave
an expiry, choosing that sentence on whether any transport row had ever been pushed —
which records that a CONFIG was placed, never that a listener was. Nothing in the schema
could tell the two apart, so the sentence was false on every fleet the day a delivery
certificate is first configured, and its date was the new certificate's rather than the
one the host is still holding after a renewal.

Two nullable columns on ``nodes``, no backfill and no default. Every existing row takes
NULL in both, which reads as "the last apply placed no listener here" — true of every
node in every fleet today, because nothing has written these until now. Adding a nullable
column with no default rewrites no row.

Reversible: the downgrade drops both, and nothing outside ``services/apply.py``,
``services/delivery.py`` and ``services/console.py`` refers to them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("delivery_placed_digest", sa.String(64), nullable=True))
    op.add_column(
        "nodes",
        sa.Column("delivery_placed_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nodes", "delivery_placed_until")
    op.drop_column("nodes", "delivery_placed_digest")
