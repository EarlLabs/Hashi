"""The lists that decide which destinations an entry opens by its own route — M34.

WHAT: ``RoutingSource`` (one published list this control plane fetches), its
      ``RoutingListVersion`` rows (each distinct content it has fetched, and whether that
      content is in force, held for the owner, rejected or superseded),
      ``RoutingOwnerEntry`` (the owner's own *always direct* and *never direct* entries)
      and ``RoutingSchedule`` (the one date the nightly refresh last ran on).
WHY:  the control database is the single source of truth (core invariants §3), so the
      version a node runs must be one the database can name and show. Files on the
      control host were the rejected alternative: they would be a second store beside the
      database, outside the backup, and a version held for the owner would have to be
      reconciled between the two.

      **Nothing here is about use.** No table has a column that moves when a user
      connects: a version's dates are when this control plane FETCHED a list, an entry's
      are when the owner typed it. There is no hit counter, no "last matched", no per-node
      or per-user row — the charter's one hard record, which this feature must never be
      the first thing to keep.
HOW:  a version stores its content already normalised (``edge.direct``'s canonical form),
      one entry per line, so what is shown, diffed and rendered is one text. Lines are
      ``name`` (the name and every name under it), ``=name`` (exactly that name) and a
      network (it is the only kind with a ``/``).
"""

import datetime
import enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from control.app.models.base import Base, EnumText, TimestampMixin, new_id


class VersionStatus(enum.StrEnum):
    """Where one fetched version of a list stands."""

    # What renders. At most one per source (a partial unique index says so).
    IN_FORCE = "in-force"
    # Fetched, tripped a bound, and waiting for the owner. Never rendered.
    HELD = "held"
    # The owner looked at a held version and said no.
    REJECTED = "rejected"
    # Was in force or held, and a newer version took its place.
    SUPERSEDED = "superseded"


class OwnerList(enum.StrEnum):
    """The owner's two lists. *never* wins over everything, *always* included."""

    ALWAYS = "always"
    NEVER = "never"


class RoutingSource(Base, TimestampMixin):
    """One published list, by URL. Configuration the owner adds, switches and removes."""

    __tablename__ = "routing_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # What the owner calls it. Unique, so the screen, the audit trail and a held update
    # can name it without an id.
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Where it is fetched from. HTTPS only (``services/routing.url_problem``): a list
    # fetched in the clear can be rewritten by any network between here and its host.
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Whether its in-force version is rendered and whether the nightly refresh fetches it.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # The last time this control plane TRIED to fetch it, and how that went. Dates of a
    # fetch, never of a use. ``last_error`` is a sentence composed here (never the text a
    # remote host sent back), so it is safe to show.
    last_attempt_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    versions: Mapped[list[RoutingListVersion]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RoutingListVersion.fetched_at",
    )


class RoutingListVersion(Base):
    """One distinct content of one source, as fetched. Append-mostly: only status moves."""

    __tablename__ = "routing_list_versions"
    __table_args__ = (
        # At most one version in force per source. A partial index, because any number of
        # rejected and superseded versions per source is ordinary history.
        Index(
            "uq_one_version_in_force_per_source",
            "source_id",
            unique=True,
            postgresql_where=text("status = 'in-force'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("routing_sources.id", ondelete="CASCADE"), nullable=False
    )
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # SHA-256 of ``entries`` — the version's name on the screen, and how an unchanged
    # fetch is recognised without storing it again.
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    # The normalised content, one entry per line (see the module header).
    entries: Mapped[str] = mapped_column(Text, nullable=False, default="")
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Lines the source publishes in a form a destination rule cannot carry (a keyword, a
    # pattern, an include) — counted and shown, never guessed at.
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Lines that are not a destination at all. Any is a reason to hold.
    invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[VersionStatus] = mapped_column(
        EnumText(VersionStatus, 16), nullable=False
    )
    # Why a version was held, as a sentence composed here.
    hold_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # When the owner or the refresh last moved ``status``.
    decided_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source: Mapped[RoutingSource] = relationship(back_populates="versions")


class RoutingOwnerEntry(Base, TimestampMixin):
    """One destination the owner typed into *always direct* or *never direct*."""

    __tablename__ = "routing_owner_entries"
    __table_args__ = (UniqueConstraint("list", "value", name="uq_routing_owner_entry"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    list: Mapped[OwnerList] = mapped_column(EnumText(OwnerList, 8), nullable=False)
    # Canonical form, one line of the version grammar (a name suffix or a network).
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class RoutingSchedule(Base):
    """The day the nightly refresh last RAN — one row, id 1.

    A date rather than a time because the rule is "once per day, at or after the backup's
    hour", and a control plane that was down at that hour runs it when it comes back that
    day rather than skipping it — the backup schedule's own reasoning.
    """

    __tablename__ = "routing_schedule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run_on: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
