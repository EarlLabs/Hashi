"""Uniqueness moves from (node, transport) onto what actually collides on a host.

Revision ID: 0004
Revises: 0003

M15. ``uq_node_transport`` said a node runs one instance of a given transport, which
is not what a host refuses. The runbook MANDATES AmneziaWG for the entry→leaf hop and
RECOMMENDS it for friends on the same box, so a node following both pieces of advice
was refused — and, with no delete for a node transport, refused forever. What two
transports on one node genuinely cannot share is:

* the LISTENING PORT. The data planes run with ``network_mode: host``, so two of them
  asking for one port is one bind. Expressed as a unique index over
  ``params ->> 'port'`` because the port is the transport's own value inside a
  document this schema deliberately does not model. A transport naming no port yields
  NULL, and Postgres treats NULLs as distinct — which is the behaviour wanted, not a
  hole: there is nothing to collide over.
* the CONFIG NAME, which is the stem of the file on the node and — for the wg-quick
  family — the network interface it brings up (``edge/bootstrap/node_stack.py``).

THE BACKFILL IS THE LOAD-BEARING PART. Every existing row takes its transport's own
name, which is exactly what every node in the field already has on disk and in its
compose file. Nothing is renamed, no container is recreated, and the first apply after
this migration writes the same bytes to the same paths.

The downgrade restores ``uq_node_transport`` and will FAIL, correctly, on a database
where the new freedom has been used — a node with two AmneziaWG rows cannot satisfy the
old rule, and the honest behaviour is to refuse rather than to pick a row to delete.
Back out before making a second one, or remove it by hand first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added nullable, backfilled, then tightened: a NOT NULL column with no default
    # cannot be added to a table that already has rows, and a server default would
    # outlive the migration as a value nobody chose.
    op.add_column(
        "node_transports", sa.Column("config_name", sa.String(64), nullable=True)
    )
    op.execute("UPDATE node_transports SET config_name = transport_name")
    op.alter_column("node_transports", "config_name", nullable=False)

    op.drop_constraint("uq_node_transport", "node_transports", type_="unique")
    op.create_unique_constraint(
        "uq_node_transport_config_name", "node_transports", ["node_id", "config_name"]
    )
    # An expression index rather than a table constraint, because Postgres has no
    # UNIQUE constraint over an expression. ``params ->> 'port'`` is text, which is all
    # this needs: two rows collide when they hold the same port, and JSON numbers that
    # are equal serialise the same.
    op.create_index(
        "uq_node_transport_port",
        "node_transports",
        ["node_id", sa.text("(params ->> 'port')")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_node_transport_port", table_name="node_transports")
    op.drop_constraint(
        "uq_node_transport_config_name", "node_transports", type_="unique"
    )
    op.create_unique_constraint(
        "uq_node_transport", "node_transports", ["node_id", "transport_name"]
    )
    op.drop_column("node_transports", "config_name")
