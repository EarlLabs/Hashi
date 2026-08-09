"""Friends, their subscription tokens, and their per-node credentials.

WHAT: ``Friend`` (a person the operator gave access to), ``Subscription`` (the one
      URL they hold) and ``Credential`` (their material on one node × transport).
WHY:  the three-table split is what makes the charter's sixth criterion —
      revocation is total — expressible rather than aspirational. A friend's access
      is not one secret in one place: it is one credential per node per transport,
      so revoking has a definite meaning ("every row, and re-render every node
      those rows were on") and a definite test.
HOW:  what is deliberately absent matters as much as what is here. There is no
      email, no phone number, no address, no "last seen", no connection count. A
      nickname the operator chose is the whole identity, because this table is the
      one an adversary would most want and the charter's answer is that there is
      nothing in it worth taking.
"""

import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from control.app.models.base import Base, EncryptedText, TimestampMixin, new_id


class Friend(Base, TimestampMixin):
    """One person with access. Identified by a nickname the operator chose."""

    __tablename__ = "friends"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)

    # The operator's own label, e.g. "kolya". Unique so revoking "the right one" is
    # unambiguous at the moment it matters. Nothing here is verified or verifiable:
    # it is a note to self, not an identity document.
    nickname: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Set when access was withdrawn. A timestamp rather than a delete so the
    # operator can see that a revocation happened and that it completed — and so a
    # re-issued nickname does not silently inherit an old subscription.
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="friend", cascade="all, delete-orphan", lazy="selectin"
    )
    credentials: Mapped[list[Credential]] = relationship(
        back_populates="friend", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class Subscription(Base, TimestampMixin):
    """The single URL a friend holds — the only artefact they ever receive."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    friend_id: Mapped[str] = mapped_column(
        ForeignKey("friends.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The bearer credential, in the URL path. Indexed and unique because every
    # delivery request looks a token up, and it is the ONLY authentication on that
    # route.
    #
    # Stored in clear rather than hashed, deliberately, and the reasoning is worth
    # recording because the instinct is the opposite: this token is not a password
    # the user chose and reused elsewhere, it is 32+ bytes of our own entropy, so
    # the offline-cracking risk a hash defends against does not exist. Meanwhile
    # storing it in clear is what lets the operator re-display a subscription URL
    # to a friend who lost it, without re-issuing and breaking their client.
    # Confidentiality comes from the row being unreachable without operator auth,
    # and from the column being unreadable in a dump — which is why it is
    # EncryptedText and why lookup goes through a separate indexed digest.
    token: Mapped[str] = mapped_column(EncryptedText(512), nullable=False)

    # Deterministic keyed digest of the token, for lookup. Needed because an
    # encrypted column cannot be queried: Fernet output is randomised, so the same
    # token encrypts differently every time and `WHERE token = ...` can never match.
    # See control/app/services/subscriptions.py for the derivation and for why the
    # comparison is still constant-time.
    token_digest: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )

    # Revoking one subscription without revoking the friend is a real operation:
    # a friend whose phone was taken gets a new URL, not a new identity.
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    friend: Mapped[Friend] = relationship(back_populates="subscriptions", lazy="joined")

    @property
    def is_active(self) -> bool:
        """Live only if neither the subscription nor the friend was revoked."""
        return self.revoked_at is None and self.friend.revoked_at is None


class Credential(Base, TimestampMixin):
    """One friend's material for one node × one transport."""

    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("friend_id", "node_transport_id", name="uq_friend_node_transport"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    friend_id: Mapped[str] = mapped_column(
        ForeignKey("friends.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_transport_id: Mapped[str] = mapped_column(
        ForeignKey("node_transports.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The transport's opaque identity for this friend on this node — a VLESS UUID,
    # for instance. `control` never interprets it. Encrypted because possessing it
    # IS access: it is the credential the node authenticates.
    subject: Mapped[str] = mapped_column(EncryptedText(512), nullable=False)

    # Any further client-scoped material this transport declared, as a JSON object
    # in one encrypted string.
    secrets: Mapped[str] = mapped_column(EncryptedText(4096), nullable=False, default="{}")

    friend: Mapped[Friend] = relationship(back_populates="credentials", lazy="joined")
    node_transport: Mapped[NodeTransport] = relationship(  # noqa: F821
        back_populates="credentials", lazy="joined"
    )
