"""A node's resolver — where its users' destination names are looked up through its hop.

Revision ID: 0005
Revises: 0004

M16 (``docs/decisions.md``, 2026-09-09). M3 moved an entry node's EXIT abroad and left its
LOOKUPS at home: the proxy resolved every destination through the host's own resolver,
inside the network the hop exists to leave. ``edge`` now sends that lookup through the hop
to a resolver named on the node's record, and this is the record's column.

NO BACKFILL, and that is the decision rather than an omission. Every existing row takes
NULL, because any value this migration wrote would be a resolver the project chose for the
operator — a hardcoded address, which ``CLAUDE.md`` forbids, arriving through the one door
nobody reviews. The consequence is stated rather than hidden: a node that already dials a
hop refuses to render from its next apply until it has a resolver, which is decision 3's
fail-closed rule applied to the lookup — and a revocation cannot reach it either. So the
first thing after this upgrade, before the next apply and before anybody is revoked, is to
set a resolver on every node that dials a hop, from the Nodes screen or through
``POST /api/nodes/{id}/resolver``: docs/deploy/runbook.md, *A node that dials a hop needs a
resolver*. A node with no hop is untouched: it renders the same bytes as before.

Nothing here can fail on existing data — a nullable column with no default touches no
row. Reversible: the downgrade drops the column, and nothing else refers to it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("resolver", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "resolver")
