"""The audit trail: one append-only table of what the operator changed.

Revision ID: 0003
Revises: 0002

Decision 8 (docs/decisions.md, 2026-09-11). Five columns and no sixth: a time, an
action from a closed vocabulary, and two nullable labels drawn from the fleet's own
inventory. There is no free-text column here on purpose — that is the load-bearing
part of the decision, and it is why this table can never become the record of who
connected to what that the charter says is absent.

``action`` is VARCHAR(32) rather than a native enum type or a CHECK constraint, which
is the same choice ``EnumText`` makes everywhere else in this schema: the closed
vocabulary is enforced in Python at the write, so adding a member is not a migration.

``at`` is indexed because both readers use it — the screen orders by it, and the
retention sweep deletes everything older than a cutoff.

The downgrade drops the table whole, which loses the trail. That is the honest
behaviour for a record with a retention window measured in days: there is nothing
here to preserve into a schema that has no place for it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        # 64 characters is the width of every value they may hold — a node name, a
        # friend's nickname, a transport name, a node state. Narrow on purpose: it is
        # far too small for the 500-character node diagnostic that sits one attribute
        # away from the node state this table is allowed to record.
        sa.Column("first_label", sa.String(64), nullable=True),
        sa.Column("second_label", sa.String(64), nullable=True),
    )
    op.create_index("ix_audit_entries_at", "audit_entries", ["at"])


def downgrade() -> None:
    op.drop_index("ix_audit_entries_at", table_name="audit_entries")
    op.drop_table("audit_entries")
