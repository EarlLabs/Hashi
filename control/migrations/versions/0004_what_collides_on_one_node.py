"""Uniqueness moves from (node, transport) onto what actually collides on a host.

Revision ID: 0004
Revises: 0003

M15. ``uq_node_transport`` said a node runs one instance of a given transport, which
is not what a host refuses. The runbook MANDATES AmneziaWG for the entry→leaf hop and
RECOMMENDS it for friends on the same box, so a node following both pieces of advice
was refused — and, with no delete for a node transport, refused forever.

What replaces it here is ONE constraint: ``config_name``, the stem of the row's config
file on the node and — for the wg-quick family — the network interface ``edge`` derives
from it. The other half of the rule, the listening port, is deliberately NOT a
constraint: two transports collide on a port only when they bind the same number over
the same transport-layer protocol, and which protocols a transport binds is declared by
its own package (``TransportMeta.listens_on``) rather than held in this table.
``control/app/services/placement.py`` holds that half and says why.

THE BACKFILL IS THE LOAD-BEARING PART. Every existing row takes its transport's own
name, which is exactly what every node in the field already has on disk and in its
compose file. Nothing is renamed, no container is recreated, and the first apply after
this migration writes the same bytes to the same paths.

WHAT THIS UPGRADE CAN FAIL ON, stated because ``deploy/docker/entrypoint.sh`` runs
``alembic upgrade head`` on every boot and a migration that aborts is a control plane
that does not start. The new constraint is ``(node_id, config_name)`` over a column
backfilled from ``transport_name``, and the constraint being dropped in the same
breath is ``(node_id, transport_name)`` — so on any database this project has ever
written, the new one is satisfied the moment the old one was. It is checked anyway,
before the constraint is created, so that a database assembled some other way is
refused with a sentence naming the node and the name rather than with a Postgres
traceback the operator has to decode at boot.

An earlier draft of this migration also created a unique index over
``(node_id, params ->> 'port')``. It was removed because it was WRONG, not merely
strict: a pre-M15 database was free to hold a TCP transport and a UDP transport on one
node sharing a port number — the runbook puts that pair within reach by naming 8443 as
a validating Reality port — and that index would have aborted the boot of a control
plane whose data was perfectly sound.

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

    _refuse_duplicates_before_the_constraint_does()

    op.drop_constraint("uq_node_transport", "node_transports", type_="unique")
    op.create_unique_constraint(
        "uq_node_transport_config_name", "node_transports", ["node_id", "config_name"]
    )


def _refuse_duplicates_before_the_constraint_does() -> None:
    """Read what the new constraint would reject, and say it in words first.

    A pre-flight rather than a trust in the old constraint, because this runs at every
    boot and the operator reading its output is doing so because their control plane did
    not come up. ``CREATE UNIQUE INDEX`` names the duplicated key and nothing else; this
    names the node and the config name, which are the two things they can act on.
    """
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT node_id, config_name, count(*) AS rows "
                "FROM node_transports GROUP BY node_id, config_name HAVING count(*) > 1 "
                "ORDER BY node_id, config_name"
            )
        )
        .all()
    )
    if not duplicates:
        return
    listed = "; ".join(
        f"node {row.node_id} has {row.rows} rows named {row.config_name!r}"
        for row in duplicates
    )
    raise RuntimeError(
        "this database holds node transports that would share one config file on their "
        f"node, so the new uniqueness rule cannot be applied: {listed}. Each of those "
        "rows renders to /opt/hashi/conf/<name>, so two of them are one file written "
        "twice. Remove the duplicates, then run the migration again. Nothing has been "
        "changed."
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_node_transport_config_name", "node_transports", type_="unique"
    )
    op.create_unique_constraint(
        "uq_node_transport", "node_transports", ["node_id", "transport_name"]
    )
    op.drop_column("node_transports", "config_name")
