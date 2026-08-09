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

from control.app.models.base import Base, EncryptedText, TimestampMixin, new_id


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
    def serving(cls) -> tuple[NodeState, ...]:
        """The states a friend may be routed onto. Defined once, here.

        Every query that builds a subscription filters on this, so "which nodes do
        friends see" has exactly one answer in the codebase rather than one per
        call site.
        """
        return (cls.ACTIVE,)


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

    # Indexed: every subscription render filters nodes by state, and that is the one
    # query that must stay fast when a node has just been blocked and every friend is
    # refreshing at once.
    state: Mapped[NodeState] = mapped_column(
        String(16), nullable=False, default=NodeState.DRAFT, index=True
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
        # A node runs one instance of a given transport. Two would mean two ports
        # and two sets of keys under one name, and every render would have to pick.
        UniqueConstraint("node_id", "transport_name", name="uq_node_transport"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    node_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Whatever name the transport package declared. `control` stores and passes it
    # back to the registry; it never compares it to a literal.
    transport_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Non-secret parameters, validated by the transport's own Params model before
    # they land here. JSONB rather than columns because the shape belongs to the
    # transport — a column per knob would mean a migration per protocol, which is
    # exactly the surgery the charter's fourth criterion forbids.
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Node-scoped secret material, as a JSON object in one encrypted string.
    # Encrypted as a whole rather than per value so a dump reveals not even how
    # many secrets a transport has.
    secrets: Mapped[str] = mapped_column(EncryptedText(8192), nullable=False, default="{}")

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
