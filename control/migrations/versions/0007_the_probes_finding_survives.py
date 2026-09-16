"""What the last probe of a node found, kept on the node's own row.

Revision ID: 0007
Revises: 0006

M26's first acceptance walk. The walk stopped a leaf's friend-facing daemon and pressed
probe; the probe answered correctly, and one reload later the row read ``active`` beside
``in sync`` with the finding gone, the node still counted as serving on the Overview and
still in every user's link while that friend's traffic was 100% lost. The finding was a
flash message and nothing else, so it survived exactly as long as the next click.

Two nullable columns, no backfill and no default. Every existing node takes NULL in both,
which reads as "never probed" — the true statement about a fleet upgrading into this, and
the same answer a node registered tomorrow starts with. Nothing here can fail on existing
data: adding a nullable column with no default rewrites no row.

Reversible: the downgrade drops both, and nothing outside ``services/health.py``,
``services/apply.py`` and ``services/console.py`` refers to them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nodes", sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "nodes", sa.Column("last_probe_finding", sa.String(1000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("nodes", "last_probe_finding")
    op.drop_column("nodes", "last_probe_at")
