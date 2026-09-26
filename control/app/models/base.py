"""The declarative base and the column types every model shares.

WHAT: ``Base``, the timestamp mixin, ``EncryptedText`` — a column type that encrypts
      on the way in and decrypts on the way out — and ``EnumText``, a text column
      that reads back as its enum member.
WHY:  encryption belongs in the type rather than in each service, because "we
      encrypt secrets at rest" is only true if it is impossible to forget. A
      service that assigns a plaintext string to an ``EncryptedText`` column gets
      encryption whether or not the author remembered the rule.
HOW:  ``EncryptedText`` needs the key, and a SQLAlchemy type cannot read
      application configuration. So the key is installed once at startup by
      ``bind_secret_box`` and the type raises if it is used before that — a loud
      failure at first write, never a silent plaintext one.
"""

import datetime
import enum
import uuid

from sqlalchemy import DateTime, String, TypeDecorator, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from control.app.crypto import SecretBox


class Base(DeclarativeBase):
    """Declarative base for every model in the control plane."""


def new_id() -> str:
    """A fresh primary key.

    UUIDs rather than serial integers, stored as text. Two reasons, one of them
    security: a sequential node or user id in a URL or an error message tells a
    reader how many users exist and in what order they were added, and the
    charter's whole posture is that the system reveals as little as possible about
    who uses it. The other is that an id can be minted before the row is inserted,
    which is what lets a node record and its key material be built in one
    transaction.
    """
    return str(uuid.uuid4())


class TimestampMixin:
    """When a row was created and last changed.

    Note what this is NOT: a record of activity. These are timestamps on
    configuration — when the operator added a node — never on a connection. Core
    invariants §3 forbids "timestamps of individual connections", and no model in
    this codebase has a "last seen" column for a user, deliberately.
    """

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


_secret_box: SecretBox | None = None


def bind_secret_box(box: SecretBox) -> None:
    """Install the key used by every ``EncryptedText`` column.

    Called once, from the application factory. Module-level state is a deliberate
    trade: the alternative is threading a key through every model constructor and
    every query, and the first place someone forgets to do that is the place a
    plaintext secret gets written.
    """
    global _secret_box
    _secret_box = box


def secret_box() -> SecretBox:
    """The installed key, or a loud failure."""
    if _secret_box is None:
        raise RuntimeError(
            "no encryption key installed — bind_secret_box() must run before any "
            "secret is read or written. Refusing rather than storing plaintext."
        )
    return _secret_box


class EncryptedText(TypeDecorator):
    """A text column whose contents are encrypted in the database.

    Values are ciphertext on disk, plaintext in Python. A dump, a stolen volume or
    a replica therefore contains nothing usable without ``HASHI_SECRET_KEY``.

    ``cache_ok = True`` is safe here because the type carries no per-instance
    configuration — the key lives in module state, not in the type object.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return secret_box().encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return secret_box().decrypt(value)


class EnumText(TypeDecorator):
    """A short text column that reads back as its enum member, not as a plain ``str``.

    ``Mapped[SomeEnum]`` over a bare ``String`` is a promise SQLAlchemy does not keep:
    it writes the member's value and hands back a ``str``, so every reader that trusts
    the annotation is quietly wrong. What that cost (M4.5): ``set_node_state`` compared
    ``state is not node.state``, which was therefore ALWAYS true, so the "setting a
    state to the one it already has is a no-op" branch never fired. A second failed
    apply was refused ``degraded -> degraded``, ``_record_failure`` swallowed the
    Conflict by design, and the operator kept being shown the FIRST failure's reason.

    Fixed in the TYPE rather than at the comparison, because one identity check was the
    instance and the lying annotation was the class: nothing lints it, and the next
    reader makes the same assumption. With this, ``==`` and ``is`` agree again — though
    call sites still say ``==``, since what they mean is "the same state", not "the same
    object".

    Python-side only, deliberately. SQLAlchemy's own ``Enum`` would coerce too, but it
    also emits a native enum type or a CHECK constraint — a migration now and another
    one every time a member is added, for a guarantee the application already enforces
    in ``allowed_from``. The column stays ``VARCHAR(n)`` and the DDL is unchanged.

    Stored as the member's ``value``, never its ``name``: the values are what is already
    in the database, and a member whose stored text stopped matching the subscription
    filter would take a node out of every user's configuration.

    ``cache_ok = True`` is safe: both constructor arguments are hashable, which is what
    SQLAlchemy's statement cache key needs from a type.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[enum.Enum], length: int) -> None:
        super().__init__(length)
        self.enum_class = enum_class

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        # Raises on a value the enum does not know, and that is the point: a mistyped
        # state fails at the write rather than becoming a row nothing can read back.
        return self.enum_class(value).value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self.enum_class(value)
