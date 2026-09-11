"""Nodes and the transports enabled on them.

WHAT: ``Node`` (one host the fleet routes through) and ``NodeTransport`` (one
      protocol enabled on one node, with its parameters and its key material).
WHY:  this is where "nodes and transports are data" stops being a slogan. A new
      exit country is a row in ``nodes``; enabling a protocol is a row in
      ``node_transports``. Neither is a code path, and neither has a column naming
      a specific provider, country or protocol — ``transport_name`` holds whatever
      the transport declared about itself, and nothing in `control` compares it to
      a literal.
HOW:  parameters split across two columns on purpose. ``params`` is JSONB and
      readable; ``secrets`` is encrypted text holding a JSON object. The split is
      what lets the panel show a node's configuration without decrypting anything.
"""

import datetime
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from control.app.models.base import Base, EncryptedText, EnumText, TimestampMixin, new_id


class NodeState(enum.StrEnum):
    """Where a node is in its life.

    ``DEGRADED`` is the load-bearing one. Core invariants §4: a partially applied
    node operation marks the node degraded, never active — because silence about a
    half-configured node is worse than an outage, since friends get routed onto it
    and report a broken client instead of a broken node.
    """

    # Created in the panel, no configuration pushed yet. Never in a subscription.
    DRAFT = "draft"

    # Configured, verified, and serving. The only state that reaches a friend.
    ACTIVE = "active"

    # Something failed halfway. Excluded from subscriptions until an operator
    # looks at it, precisely so nobody is routed onto it.
    DEGRADED = "degraded"

    # Deliberately taken out. Kept as a row rather than deleted so its address is
    # not silently reused and so an operator can see what the fleet used to be.
    RETIRED = "retired"

    @classmethod
    def allowed_from(cls, current: NodeState) -> tuple[NodeState, ...]:
        """Which states a node may move to from ``current`` — backlog item 17.

        A declared machine rather than a free-form column, because one transition is
        genuinely wrong and easy to write by accident:

        * ``retired -> active`` is refused. A retired node's host has usually been
          destroyed; re-activating the RECORD would put an address that may now belong
          to a stranger back into every friend's subscription. Create a new node
          instead — which is the ten-minute operation the charter is built around.

        ``draft -> degraded`` was refused here too, on the reading that degraded means
        "was working, now is not". That reading cost an evening in the field on
        2026-09-08 and is retracted deliberately, written out so nobody restores it:

        * a first apply STARTS from draft, and ``apply_node`` marks a node degraded on
          any failure (core invariants §4). The refusal therefore fired INSIDE the
          failure path, before the caller could raise its own message — so an operator
          whose first apply hit a permission error on the host was told "a node cannot
          go from draft to degraded" instead, and the real reason reached nobody, not
          even a log.
        * a node whose first apply failed has been dialled, and usually written to,
          before the failure was detected. It is not a draft any more, and leaving it
          in draft is the same silence about a half-configured node that §4 forbids.
        * "which nodes have never been applied" is still answerable and never was this
          column's job: ``NodeTransport.applied_at`` stays NULL until a config actually
          landed. A state says where a node IS; whether it ever worked is history, and
          the reason lives in ``state_detail``.

        Everything else is permitted, including ``degraded -> active`` (a successful
        apply after a fix) and ``active -> draft`` (taking a node out of rotation
        without retiring it, so it stops reaching friends but keeps its configuration).
        """
        match current:
            case cls.DRAFT:
                return (cls.ACTIVE, cls.DEGRADED, cls.RETIRED)
            case cls.ACTIVE:
                return (cls.DEGRADED, cls.DRAFT, cls.RETIRED)
            case cls.DEGRADED:
                return (cls.ACTIVE, cls.DRAFT, cls.RETIRED)
            case cls.RETIRED:
                # Terminal by design. See the note above.
                return ()
        return ()

    @classmethod
    def serving(cls) -> tuple[NodeState, ...]:
        """The states a friend may be routed onto. Defined once, here.

        Every query that builds a subscription filters on this, so "which nodes do
        friends see" has exactly one answer in the codebase rather than one per
        call site.
        """
        return (cls.ACTIVE,)


class TransportPurpose(enum.StrEnum):
    """Who consumes a transport enabled on a node — backlog item 16.

    The charter's topology is a Russian ENTRY node fronting foreign LEAF nodes, and
    the hop between them is an ordinary transport whose consumer happens to be another
    node rather than a friend's device. That difference has to be recorded, because
    everything downstream reads it:

    * a hop must never appear in a subscription, and must never be granted to a
      friend — a friend handed the entry↔leaf tunnel would bypass the entry entirely;
    * exactly one end of a hop dials the other. The entry dials, always: it sits
      behind a Russian carrier NAT and cannot be dialled. Recording which end is which
      is what lets ``edge.relay`` render the asymmetry.

    Stored as text, and the values are about topology rather than about any protocol —
    nothing here names a transport, and `control` still never compares a transport name
    to a literal.
    """

    # The default, and what every existing row is: a transport friends connect to.
    FRIENDS = "friends"

    # This end of a node-to-node hop, on the node that DIALS.
    RELAY_ENTRY = "relay-entry"

    # The far end of that hop, on the node that waits.
    RELAY_LEAF = "relay-leaf"

    @classmethod
    def relays(cls) -> tuple[str, ...]:
        return (cls.RELAY_ENTRY, cls.RELAY_LEAF)


class Node(Base, TimestampMixin):
    """One host the fleet can route through."""

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)

    # Operator-facing name, e.g. "leaf-ams-1". Unique so two nodes cannot be
    # confused in the panel at the moment one of them has to be destroyed.
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Hostname or IP a client dials. Not unique: an operator may legitimately
    # point two records at one host while migrating, and enforcing uniqueness here
    # would block the fastest possible rotation, which is the product's promise.
    address: Mapped[str] = mapped_column(String(255), nullable=False)

    # The exit country as the operator labelled it. Text, never an enum: an enum of
    # countries is a code change per country, and "a new exit country is a row"
    # would stop being true.
    location_label: Mapped[str] = mapped_column(String(64), nullable=False)

    # Where this node's users' destination names are looked up while its traffic leaves
    # through a hop — M16 (docs/decisions.md, 2026-09-09). An address the operator gives,
    # like every other address on this row, and never a project default: a default would
    # be a resolver this code chose for the whole fleet. ``edge`` reads it only on a node
    # that dials a hop, and refuses to render such a node without one rather than let the
    # host's own resolver answer — on an entry node, the network the hop exists to leave.
    #
    # Nullable because a node with no hop has no use for it, and because no value could be
    # backfilled onto an existing row that would not be one this project invented. Set when
    # the node is created, like the address above: this row has no edit path.
    resolver: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Indexed: every subscription render filters nodes by state, and that is the one
    # query that must stay fast when a node has just been blocked and every friend is
    # refreshing at once.
    #
    # ``EnumText`` rather than ``String(16)``, and the difference is not cosmetic: over
    # a bare String this column is annotated ``NodeState`` and hands back a ``str``, so
    # a reader that trusts the annotation is wrong. That is how M4.5 happened — see the
    # type's own docstring. Same VARCHAR(16) on disk, so no migration.
    state: Mapped[NodeState] = mapped_column(
        EnumText(NodeState, 16), nullable=False, default=NodeState.DRAFT, index=True
    )

    # Why the node is degraded, for the operator. Node-level configuration
    # diagnostics only — never anything about traffic or users.
    state_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- how `control` reaches this node over SSH ----------------------------
    # Control dials the node; the node never dials us (core invariants §1).
    ssh_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_user: Mapped[str] = mapped_column(String(32), nullable=False, default="root")

    # The private key `control` authenticates with, encrypted at rest. A password
    # is deliberately not an option: the charter's bring-your-own-SSH model means
    # this key is the only thing standing between the control database and every
    # node, so it is never written in clear.
    ssh_private_key: Mapped[str | None] = mapped_column(EncryptedText(4096), nullable=True)

    # The node's SSH host key, recorded on first successful connect. Pinned so a
    # later connection cannot be silently intercepted — a censor who can reroute
    # a Russian IP can also answer on port 22.
    ssh_host_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    transports: Mapped[list[NodeTransport]] = relationship(
        back_populates="node", cascade="all, delete-orphan", lazy="selectin"
    )

    def is_serving(self) -> bool:
        return self.state in NodeState.serving()


class NodeTransport(Base, TimestampMixin):
    """One transport enabled on one node."""

    __tablename__ = "node_transports"
    __table_args__ = (
        # WHAT HAS TO BE UNIQUE ON ONE NODE, and it is not the transport — M15.
        #
        # It used to be ``(node_id, transport_name)``, on the reasoning that two
        # instances of one transport would mean two ports and two sets of keys under
        # one name. That is true and it is not a reason to forbid them: the runbook
        # MANDATES AmneziaWG for the entry→leaf hop and RECOMMENDS it for friends on
        # the same box, so the old rule made a node that followed both pieces of advice
        # impossible — and, with no delete for a node transport at the time, impossible
        # forever. Removing one is ``nodes.remove_transport`` since M15.2, which is also
        # the only thing that gives a config name below back to the node.
        #
        # So uniqueness moved onto the two things that genuinely collide on a host: the
        # CONFIG NAME, which this table holds, and the LISTENING PORT, which it cannot.
        #
        # The config name is the stem of the row's file on the node and, for the
        # wg-quick family, the network interface name ``edge`` derives from it. Two rows
        # sharing it would be two configs at one path and one interface the second
        # container cannot create. It is ours to choose and true of the row, so it is a
        # constraint here — per NODE, never fleet-wide: two nodes writing
        # ``amneziawg.conf`` is the ordinary case.
        #
        # THE PORT RULE IS NOT HERE, and that is a decision rather than an omission. Two
        # transports collide on a port only when they bind the same number over the same
        # transport-layer PROTOCOL — a TCP proxy and an obfuscated UDP tunnel on 8443 are
        # two sockets — and the protocol is declared by the transport's own package
        # (``TransportMeta.listens_on``), not by anything in this row. Expressing it in
        # SQL would mean storing a copy of somebody else's declaration on every row,
        # which goes stale the day they change it; this codebase already makes that call
        # the same way for ``config_format``. So the port rule lives in
        # ``services.placement``, which every path that writes a port goes through, and
        # that module's header says why.
        UniqueConstraint("node_id", "config_name", name="uq_node_transport_config_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    node_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Whatever name the transport package declared. `control` stores and passes it
    # back to the registry; it never compares it to a literal.
    transport_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # The name this row's rendered config is placed under on the node: the stem of its
    # file, the name of its compose service and — for the wg-quick family — the network
    # interface it brings up. Stored rather than derived, for two reasons. It is what
    # the unique constraint above is written over, so the database can hold the rule
    # instead of four services remembering it; and every node already in the field has
    # its files named after the transport, so a derived name would rename them under a
    # running daemon. ``services.placement`` chooses it — the transport's own name when
    # that is free on this node, which is every row that existed before M15.
    config_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Non-secret parameters, validated by the transport's own Params model before
    # they land here. JSONB rather than columns because the shape belongs to the
    # transport — a column per knob would mean a migration per protocol, which is
    # exactly the surgery the charter's fourth criterion forbids.
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Node-scoped secret material, as a JSON object in one encrypted string.
    # Encrypted as a whole rather than per value so a dump reveals not even how
    # many secrets a transport has.
    secrets: Mapped[str] = mapped_column(EncryptedText(8192), nullable=False, default="{}")

    # Who consumes this transport — see ``TransportPurpose``. Defaulted rather than
    # nullable so that "not a hop" is a value rather than an absence: every query that
    # builds a subscription filters on it, and a NULL there would be a friend routed
    # onto an entry↔leaf tunnel.
    purpose: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TransportPurpose.FRIENDS, index=True
    )

    # The other end of the hop, when this row is one end of one. Self-referential and
    # nullable: a friend-facing transport has no peer. SET NULL rather than CASCADE on
    # delete, so removing one end leaves the other visible and obviously half a hop
    # instead of silently disappearing with it.
    peer_node_transport_id: Mapped[str | None] = mapped_column(
        ForeignKey("node_transports.id", ondelete="SET NULL"), nullable=True
    )

    # An operator can enable a transport without exposing it to friends yet.
    # Disabled means "configured on the node but not in anyone's subscription".
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Set when the rendered config was last accepted and pushed. Configuration
    # state, not activity: it records what WE did, not what any user did.
    applied_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Hash of the config last successfully applied, for drift detection. Comparing
    # a fresh render against this is only meaningful because rendering is pure and
    # deterministic (core invariants §1).
    applied_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    node: Mapped[Node] = relationship(back_populates="transports", lazy="joined")
    credentials: Mapped[list[Credential]] = relationship(  # noqa: F821
        back_populates="node_transport", cascade="all, delete-orphan"
    )
