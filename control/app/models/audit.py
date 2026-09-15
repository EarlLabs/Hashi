"""The audit trail: what the operator changed, and nothing else.

WHAT: ``AuditAction`` (the closed vocabulary of things that can be recorded) and
      ``AuditEntry`` — a time, one action, and at most two labels.
WHY:  decision 8 (``docs/decisions.md``, 2026-09-11) grants a trail and fixes its
      shape, because this is the table that turns into a record of who used the
      service if it is allowed to grow. Every entry moves because the OPERATOR acted;
      none moves because a person used the service. The delivery endpoint writes here
      never, which is a stated rule with a scenario of its own rather than an
      oversight.
HOW:  the shape IS the guarantee, so it is deliberately too narrow to hold anything
      else. There is no free-text column, no JSON detail, no reason, no actor, no
      address — a JSON blob is how a trail acquires a token eighteen months from now
      without anyone deciding to add one, so there is nowhere for such a value to go.
      ``action`` is an enum through ``EnumText``, so a value nobody declared fails at
      the write; the two label columns are 64 characters wide, which is exactly the
      width of the inventory values they may hold (``Node.name``, ``Friend.nickname``,
      a transport name, a ``NodeState``) and nowhere near ``Node.state_detail``'s 500.

      Rows are append-only: written once by the service that made the change, read by
      the panel, deleted only by the retention sweep. Hence no ``TimestampMixin`` —
      an ``updated_at`` here would invite the idea that an entry can be edited.
"""

import datetime
import enum

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from control.app.models.base import Base, EnumText, new_id

# The width of both label columns, and of every inventory value they are allowed to
# hold. Stated here because the service that writes an entry refuses a longer value
# rather than letting the database truncate one: a label that does not fit is a label
# that was composed from something rather than read off a row.
LABEL_MAX_LENGTH = 64


class AuditAction(enum.StrEnum):
    """Everything that may be recorded. A closed vocabulary, deliberately.

    Closed because the alternative — a free ``action`` string — is a column an author
    in a hurry writes a sentence into, and a sentence is where a reason, a parameter
    or a remote host's words end up. A member here has to be declared, reviewed, and
    given wording on the screen; nothing else can be written at all (``EnumText``
    raises on an undeclared value at the WRITE, not at review).

    The values are machine keys and are what lands in the database. The sentence an
    operator reads is composed at render time — see the panel's wording module — so
    these never have to be readable prose and must never be edited casually: a value
    whose text changed would orphan every row already written with the old one.

    Only changes that COMMITTED are in this list. There is no login, no probe, no
    failure and no refusal: a probe changes nothing, and a refusal's text can come
    from a remote host while this table has nowhere safe to put it.
    """

    FRIEND_ADDED = "friend-added"
    FRIEND_REVOKED = "friend-revoked"
    NODE_ADDED = "node-added"
    NODE_STATE_CHANGED = "node-state-changed"
    NODE_APPLIED = "node-applied"
    # M16. The one edit a node record admits after registration, recorded by the node's
    # NAME only: the resolver is an address, and an address against a time is the record
    # this trail was shaped to refuse.
    NODE_RESOLVER_SET = "node-resolver-set"
    # M23. The SECOND edit a node record admits after registration, and it exists for the
    # reason the first one does: the add-node dialog calls the SSH key optional, and until
    # this action existed a node registered on that invitation could never be given one —
    # unappliable, unreachable by a revocation, and permanently in the list. Recorded by
    # the node's NAME only. Nothing about the key itself: not its length, not a
    # fingerprint, not whether it replaced one, because a credential for every host in the
    # fleet has no safe shape in a durable record.
    NODE_SSH_KEY_SET = "node-ssh-key-set"
    TRANSPORT_ENABLED = "transport-enabled"
    TRANSPORT_OFFERED = "transport-offered"
    TRANSPORT_WITHDRAWN = "transport-withdrawn"
    # M15.2. A withdrawal and a removal are two different changes and the trail has to
    # be able to tell them apart: one leaves the row holding its port and its config
    # name, the other frees both and takes every credential minted under it. The row
    # they describe is gone by the time anybody reads this entry, which is exactly what
    # the trail adds over the inventory — and what retention bounds.
    TRANSPORT_REMOVED = "transport-removed"
    HOP_ESTABLISHED = "hop-established"
    HOP_DISSOLVED = "hop-dissolved"
    KEYS_ROTATED = "keys-rotated"
    PARAMS_REPLACED = "params-replaced"


class AuditEntry(Base):
    """One change the operator made. Five columns, and that is the whole table.

    The column set is asserted as an exact whitelist by the zone's tests, the way
    ``PANEL_PAGES`` is asserted for third-party fetches: a sixth column — ``details``,
    ``reason``, ``source``, ``actor`` — fails that test in the change that adds it,
    which is the only moment anybody is thinking about whether it should exist.
    """

    __tablename__ = "audit_entries"

    # A UUID like every other table here, for the reason ``new_id`` gives: a sequential
    # id says how many friends exist and in what order they arrived. It is in the
    # whitelist because a row needs a primary key, not because anything reads it.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)

    # When the change committed. Indexed because both readers order or filter by it —
    # the screen shows newest first, and the retention sweep deletes by cutoff.
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # What happened, from the closed vocabulary above. ``EnumText`` rather than a bare
    # String is load-bearing here rather than cosmetic: over a String this column reads
    # back as a plain ``str`` and accepts anything on the way in, so "the vocabulary is
    # closed" would be a claim about authors rather than about the database.
    action: Mapped[AuditAction] = mapped_column(EnumText(AuditAction, 32), nullable=False)

    # What the change was about — a name the operator already chose or the registry
    # already holds, copied whole and never composed: a node name, a friend's nickname,
    # a transport name, a node state. One label for a change about one thing ("kolya
    # added"), two for a change about a pair ("vless-reality enabled on leaf-ams-1").
    #
    # Nullable rather than empty-string so "this action has one label" is an absence
    # rather than a value the screen has to recognise.
    first_label: Mapped[str | None] = mapped_column(
        String(LABEL_MAX_LENGTH), nullable=True
    )
    second_label: Mapped[str | None] = mapped_column(
        String(LABEL_MAX_LENGTH), nullable=True
    )
