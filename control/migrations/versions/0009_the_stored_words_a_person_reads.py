"""The stored words a person reads: ``friends`` and ``friend-*`` become ``user``'s.

Revision ID: 0009
Revises: 0008

M29 (``docs/decisions.md``, 2026-09-22). ``0008`` moved every NAME the old word was
written into — the table, the columns, the indexes, the constraints. Two things it
could not take are **values inside rows**, and both of them are read by a person:

* ``node_transports.purpose``, whose default value ``'friends'`` (``0002``) means "a
  transport users connect to". It is returned by the API on a hop end and decides what
  the console shows a row as;
* ``audit_entries.action``, whose ``'friend-added'`` and ``'friend-revoked'`` (``0003``)
  are what the audit screen renders a sentence from. An operator reads the sentence, but
  the value is what the row holds and what every scenario asserting the trail's closed
  vocabulary lists.

So this is a DATA migration, and it is the only one in M29 that writes to rows. It runs
``UPDATE``s, nothing more: no column changes type, width or nullability, no table or
column is renamed, and no encrypted column is opened — so like ``0008`` it needs no
``HASHI_SECRET_KEY`` and can be rehearsed against a copy of real data without one.
Neither column is a Postgres native ``ENUM``: ``purpose`` is ``VARCHAR(16)`` written by
``0002`` and ``action`` is ``VARCHAR(32)`` written by ``0003`` and read back through
``EnumText``, which is Python-side only by design (see its docstring). There is
therefore no type to alter and no ``ALTER TYPE ... RENAME VALUE`` anywhere in here —
the values are ordinary text and the vocabulary is closed in the application.

REVERSIBLE IS THE REQUIREMENT, NOT A NICETY, and it is a harder claim here than in
``0008`` because a rename holds nothing while an ``UPDATE`` overwrites something.
``downgrade`` is the exact inverse, statement for statement in reverse order, and it is
exact rather than approximately exact because the new values could not have existed
before the upgrade: ``EnumText`` raises on an undeclared value at the WRITE, and no
version of this application ever wrote ``'users'`` into ``purpose`` or ``'user-added'``
into ``action``. So every row the downgrade moves back is a row the upgrade moved, and
an operator who deploys M29 and backs it out lands on values the pre-M29 code reads.

TWO CASES THAT ARE DECIDED HERE RATHER THAN DISCOVERED LATER:

* **A value that is neither the old one nor the new one is left alone.** Every statement
  carries a ``WHERE``, so ``'relay-entry'``, ``'relay-leaf'``, ``'node-added'`` and the
  rest keep their text, and so does a value nothing declared — which this migration is
  emphatically not the place to judge. Refusing on one would abort the
  ``alembic upgrade head`` that ``deploy/docker/entrypoint.sh`` runs on EVERY boot, over
  a row the application already cannot read back.
* **An empty table is a no-op.** ``UPDATE`` over zero rows succeeds and reports zero, so
  a fresh database migrates through this revision as cheaply as a populated one, and
  running it twice changes nothing the second time — which the entrypoint requires.

NOTHING HERE PRINTS A ROW. No count, no nickname, no label, no token: the audit table is
exactly where a well-meant log line would turn a trail that deliberately holds no
identity into one that names a person in a boot log. Alembic's own revision line is the
only output, and it names this revision and nothing from the data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The two vocabularies, old on the left. Written as data so ``upgrade`` and ``downgrade``
# are the same statement read in opposite directions — the shape that makes "the inverse
# is exact" checkable by eye rather than by comparing two prose paragraphs.
_PURPOSE = ("friends", "users")
_ACTIONS = (("friend-added", "user-added"), ("friend-revoked", "user-revoked"))


def upgrade() -> None:
    _rewrite("node_transports", "purpose", _PURPOSE[0], _PURPOSE[1])
    for old, new in _ACTIONS:
        _rewrite("audit_entries", "action", old, new)

    # The column default moves with the values, or the next row inserted without an
    # explicit purpose — which is any row written by something other than this
    # application — arrives holding a word the vocabulary no longer has.
    op.alter_column(
        "node_transports",
        "purpose",
        existing_type=sa.String(16),
        existing_nullable=False,
        server_default=_PURPOSE[1],
    )


def downgrade() -> None:
    op.alter_column(
        "node_transports",
        "purpose",
        existing_type=sa.String(16),
        existing_nullable=False,
        server_default=_PURPOSE[0],
    )

    for old, new in _ACTIONS:
        _rewrite("audit_entries", "action", new, old)
    _rewrite("node_transports", "purpose", _PURPOSE[1], _PURPOSE[0])


def _rewrite(table: str, column: str, old: str, new: str) -> None:
    """Replace one exact value in one column, and touch no other row.

    The table and column names are the literals above and go into the statement; the two
    VALUES are bound parameters, because they are the only part a reader could imagine
    ever coming from somewhere else. Nothing is selected back and nothing is logged —
    the return value of the ``UPDATE`` is deliberately dropped, since a row count from
    ``audit_entries`` is a fact about how much of a trail exists and has no business in
    a boot log.
    """
    op.get_bind().execute(
        sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"),
        {"old": old, "new": new},
    )
