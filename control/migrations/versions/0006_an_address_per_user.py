"""An address of their own — a pool on the row, and one address per credential.

Revision ID: 0006
Revises: 0005

M17 (``docs/decisions.md``, 2026-09-11), found in the field. ``peer_tunnel_address`` was
one operator parameter, so a WireGuard-family transport had exactly one address to hand
out and therefore exactly one friend — against a charter scale of ~30-50. The second
friend was refused at render (``AmbiguousPeerRoute``), correctly: on a WireGuard server
``AllowedIPs`` is the authorisation list AND the routing table, so two peers on one
address is a silent hijack of the first one's return path. This is where the second
address comes from.

Four things, and nothing else:

* ``node_transports.pool_size`` — how many addresses this row may hand out, with a check
  constraint that a pool is at least one. NULL means a row enabled before this
  migration: its pool is the single address already in ``params``, unvalidated, which is
  exactly what it renders today.
* ``credentials.tunnel_address`` — encrypted, like every other per-person value.
* ``credentials.tunnel_address_digest`` — the keyed digest the constraint below is
  written over, because an encrypted column cannot be constrained: Fernet output is
  randomised, so the same address stored twice is two different strings.
* ``uq_credential_tunnel_address`` over ``(node_transport_id, tunnel_address_digest)`` —
  the rule that two people on one tunnel never hold one address. NULL digests do not
  collide in Postgres, which is what lets every existing credential sit here untouched.

NO BACKFILL, and that is the decision rather than an omission — 0005's reasoning applied
to a different value. A ``pool_size`` written here would be a pool size this project chose
for somebody else's node, and an address written into a credential would be an address a
device is not configured with. Both are the kind of value ``CLAUDE.md`` forbids arriving
through the one door nobody reviews.

The consequence, stated rather than hidden, in 0005's shape — it names the action this
upgrade requires, because there is one.

**Every existing row renders the same bytes.** A pool of one starting at the address
already in ``params`` is byte-identical to the fallback the renderers have always used,
so no file on a node and no file on anybody's device is touched by this upgrade, and a
row that already has two friends on it is still refused at render exactly as it is today.

**What changes is what the control plane will accept next.** ``pool_size`` is NULL on
every upgraded row and a NULL pool is one address long, so while such a row is SERVING it
is measured as holding one person — and ``friends.create_friend`` refuses the next friend
FLEET-WIDE, naming that node and that transport, whether or not the new person would ever
have been routed onto it. So the first thing after this upgrade, before adding anybody,
is to give every serving friend-facing WireGuard-family row a pool size, by replacing
that row's parameters — which pins every address a device already holds before it widens
anything, and is also what repairs the two-friend row above. Nothing else sizes a row:
no backfill writes one here, for the reason given above, and a row enabled from now on is
sized at the moment it is enabled.

WHAT THIS UPGRADE CAN FAIL ON: nothing. ``deploy/docker/entrypoint.sh`` runs
``alembic upgrade head`` on every boot, so a migration that aborts is a control plane
that does not start — two nullable columns with no default touch no row, the check
constraint is vacuously true of NULL, and the unique constraint is over a pair whose
second member is NULL on every existing row.

THE DOWNGRADE REFUSES once the pool is in use, in 0004's shape and for a sharper reason.
Pre-M17 code reads no address off a credential, so it falls back to ``params`` for
everybody — which on a row that has handed out several addresses means either a render
refused for ambiguity (and every push to that node blocked, including a revocation's) or,
for a lone holder at a later pool address, a working-looking config whose traffic goes
nowhere. So it stops, names the nodes, and changes nothing. What downgrades cleanly is a
row nobody holds an address on, whatever its size, and a row that was never sized — there
the only holder is at the pool's first address, which is the value ``params`` already
carries, so old code renders it identically. A SIZED row with a holder does not, not even
with a single one: nothing here can decrypt an address to tell ``pool[0]`` from
``pool[5]``, so it refuses on the size.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("node_transports", sa.Column("pool_size", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_node_transport_pool_size",
        "node_transports",
        "pool_size IS NULL OR pool_size >= 1",
    )

    # String, not a type of its own: ``EncryptedText`` is a type decorator over String
    # and ciphertext is text. 512 is the same width the other encrypted per-person value
    # on this table (``subject``) takes.
    op.add_column("credentials", sa.Column("tunnel_address", sa.String(512), nullable=True))
    op.add_column(
        "credentials", sa.Column("tunnel_address_digest", sa.String(64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_credential_tunnel_address",
        "credentials",
        ["node_transport_id", "tunnel_address_digest"],
    )


def downgrade() -> None:
    _refuse_while_a_pool_is_in_use()

    op.drop_constraint("uq_credential_tunnel_address", "credentials", type_="unique")
    op.drop_column("credentials", "tunnel_address_digest")
    op.drop_column("credentials", "tunnel_address")
    op.drop_constraint("ck_node_transport_pool_size", "node_transports", type_="check")
    op.drop_column("node_transports", "pool_size")


def _refuse_while_a_pool_is_in_use() -> None:
    """Stop, naming the nodes, before dropping addresses somebody's device is using.

    A pre-flight in 0004's shape, and the same argument: the operator reading this is
    backing out at three in the morning, and ``ERROR: column does not exist`` three
    minutes later on the first apply is not something they can act on. What is named is
    the NODE — which is what they can act on — and never a person, an address or a count
    of people: the reason this refuses is a property of the configuration, and a
    migration that printed who holds what would put the one record this project does not
    keep into a boot log.

    The condition is both halves together. A row sized above one that nobody holds an
    address on has nothing to lose, and an address held on a row that was never sized is
    the pool's first one — which is the value ``params`` already carries, so old code
    renders it identically. It is the pair that cannot survive: several people on one
    row, each at a different address, read back by code that knows only the first.

    IT KEYS ON THE SIZE AND NOT ON HOW MANY PEOPLE HOLD AN ADDRESS, because it cannot
    tell ``pool[0]`` from ``pool[5]`` without the key — so a lone holder on a sized row
    is refused too. That is the right refusal and the wrong instruction to pair with
    "take it back to one user": the operator who revoked friends to get there would have
    destroyed real people's access and still be refused. So the sentence below names the
    remedy that actually clears this query.
    """
    in_use = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT DISTINCT t.node_id AS node_id "
                "FROM node_transports AS t "
                "JOIN credentials AS c ON c.node_transport_id = t.id "
                "WHERE t.pool_size > 1 AND c.tunnel_address_digest IS NOT NULL "
                "ORDER BY node_id"
            )
        )
        .all()
    )
    if not in_use:
        return
    listed = ", ".join(row.node_id for row in in_use)
    raise RuntimeError(
        "this database hands out an address per user on at least one transport, so the "
        f"columns holding those addresses cannot be dropped: nodes {listed}. The code "
        "this downgrade returns to reads no address off a credential — every user on "
        "such a transport falls back to the one address in the transport's parameters, "
        "which is either a render refused for two peers on one address (and every push "
        "to that node blocked, a revocation's included) or, for a single holder, a "
        "config that looks right and carries nothing. This asks how big the pool is and "
        "not how many people are on it — nothing here can decrypt an address to tell the "
        "pool's first from its fifth — so taking a transport down to one user does not "
        "clear it, and revoking friends to get there would cost them their access for "
        "nothing. Remove those transports, which takes their credentials with them, and "
        "run this again. Nothing has been changed."
    )
