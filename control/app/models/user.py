"""Users, their subscription tokens, and their per-node credentials.

WHAT: ``User`` (a person the operator gave access to), ``Subscription`` (the one
      URL they hold) and ``Credential`` (their material on one node × transport).
WHY:  the three-table split is what makes the charter's sixth criterion —
      revocation is total — expressible rather than aspirational. A user's access
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


class User(Base, TimestampMixin):
    """One person with access. Identified by a nickname the operator chose."""

    __tablename__ = "users"

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
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    credentials: Mapped[list[Credential]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class Subscription(Base, TimestampMixin):
    """The single URL a user holds — the only artefact they ever receive."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
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
    # to a user who lost it, without re-issuing and breaking their client.
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

    # Revoking one subscription without revoking the user is a real operation:
    # a user whose phone was taken gets a new URL, not a new identity.
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="subscriptions", lazy="joined")

    @property
    def is_active(self) -> bool:
        """Live only if neither the subscription nor the user was revoked."""
        return self.revoked_at is None and self.user.revoked_at is None


class Credential(Base, TimestampMixin):
    """One user's material for one node × one transport."""

    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "node_transport_id", name="uq_user_node_transport"),
        # ONE ADDRESS PER PERSON INSIDE ONE TUNNEL — M17, and this is the rule the
        # database holds rather than a service remembering it. On a WireGuard server
        # ``AllowedIPs`` is simultaneously the authorisation list and the routing table,
        # so two credentials on one row holding one address is not a duplicate: it is a
        # silent hijack of the first person's return path by the second. ``edge`` refuses
        # to render such a pair (``AmbiguousPeerRoute``) — correctly, and that refusal is
        # untouched — but a refusal at render time arrives after the rows are committed,
        # at which point every push to that node fails, including a revocation's.
        #
        # WHY A CONSTRAINT AND NOT ONLY THE ALLOCATOR. The allocator reads the addresses
        # in use and takes the lowest free one; that is a READ, and nothing serialises
        # two of them (the same reasoning ``services/placement.py`` sets out for ports).
        # Here, unlike there, the losing write must not be allowed to land — so the
        # database decides, one of the two flushes fails, and the service turns that into
        # a refusal that changed nothing. No lock is taken anywhere.
        #
        # Over the DIGEST rather than the address, because the address itself is
        # encrypted and Fernet output is randomised: the same address stored twice is two
        # different strings, so a constraint over the ciphertext would hold nothing at
        # all. Per node-transport rather than fleet-wide: two nodes handing out the same
        # private address is the ordinary case, and only one tunnel's routing table is
        # at stake. NULL digests do not collide in Postgres, which is what lets every row
        # that pre-dates M17 — and every credential on a transport that hands out no
        # addresses at all — sit in this table unaffected.
        UniqueConstraint(
            "node_transport_id",
            "tunnel_address_digest",
            name="uq_credential_tunnel_address",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_transport_id: Mapped[str] = mapped_column(
        ForeignKey("node_transports.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The transport's opaque identity for this user on this node — a VLESS UUID,
    # for instance. `control` never interprets it. Encrypted because possessing it
    # IS access: it is the credential the node authenticates.
    subject: Mapped[str] = mapped_column(EncryptedText(512), nullable=False)

    # Any further client-scoped material this transport declared, as a JSON object
    # in one encrypted string.
    secrets: Mapped[str] = mapped_column(EncryptedText(4096), nullable=False, default="{}")

    # This person's own address inside this row's tunnel — M17. Written in the form the
    # renderer wants (with the prefix the operator typed), and NULL for every credential
    # on a transport that hands out no addresses, which is most of them.
    #
    # WHY NOT IN ``secrets`` ABOVE, which is where every other piece of per-person
    # material lives. ``rotation.rotate_keys`` replaces that column WHOLESALE
    # (``services/rotation.py``, the line that assigns ``credential.secrets``): it mints
    # fresh client material and writes the new mapping over the old one, because which
    # keys a transport's material has is the transport's business and merging would mean
    # `control` deciding what survives. An address is not key material — rotating a key
    # must not move the address a device is already configured with — so a value kept
    # there would be destroyed by the next rotation, silently, and every rotated user
    # would fall back to the pool's first address and collide.
    #
    # WHY ENCRYPTED, AND WHY A DIGEST BESIDE IT. The same pair as ``Subscription.token``
    # and for the same two reasons: an encrypted column cannot be searched or constrained
    # (Fernet output is randomised), so the digest is what the uniqueness rule above is
    # written over and what the allocator compares. The encryption is what keeps a stolen
    # dump from being a list of which address belongs to whom.
    #
    # WHAT THAT PROTECTION IS NOT, stated plainly rather than implied: it is PARTIAL. The
    # allocator hands out the lowest free address in ``(created_at, id)`` order, and both
    # of those columns are in clear — so somebody holding a dump and no key can replay
    # the order and reconstruct most of the mapping anyway. What the encryption genuinely
    # buys is that the file itself is not readable, that a row edited or revoked out of
    # order is not reconstructible, and that no address is ever printed by an accident of
    # logging or serialisation. It is not a claim that the mapping is secret.
    tunnel_address: Mapped[str | None] = mapped_column(EncryptedText(512), nullable=True)

    # The keyed digest of the address above, over this row and the address's CANONICAL
    # bare host — ``SecretBox.address_digest``. Canonical so that ``10.0.0.2/24`` and
    # ``10.0.0.2/32`` cannot both satisfy the constraint: they are one host, one route,
    # and one hijack.
    #
    # Keyed (HMAC) rather than a plain hash, like the token digest: without
    # ``HASHI_SECRET_KEY`` a dump's digests cannot even be tested against a guessed
    # address, which is the small private range every one of them is in.
    tunnel_address_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="credentials", lazy="joined")
    node_transport: Mapped[NodeTransport] = relationship(  # noqa: F821
        back_populates="credentials", lazy="joined"
    )
