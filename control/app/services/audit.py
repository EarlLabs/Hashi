"""Writing the audit trail, and sweeping it clean again.

WHAT: ``record`` — the one way an entry is written — and the retention sweep that
      deletes entries older than the configured window.
WHY:  decision 8 (``docs/decisions.md``, 2026-09-11). The trail records what the
      operator changed, and its safety is entirely a matter of what CANNOT reach it:
      one function writes it, its labels are values copied whole off inventory rows,
      and everything it holds is deleted again within days. What the trail adds over
      the rows it describes is ordering across tables and the survival of a row that
      was later deleted — that second one is the whole marginal disclosure, and
      retention is what bounds it.
HOW:  ``record`` adds a pending row to the caller's session and does NOT commit. That
      is what puts the entry in the same transaction as the change it describes: the
      service's own commit writes both or neither, so there is no entry for a change
      that was rolled back and no change that quietly went unrecorded. It is called
      only from ``services/`` — never from a route, because ``/panel`` and ``/api``
      mutate through these same services, and never from ``/sub/{token}``, which
      writes nothing here, ever.

      The sweep runs from the application lifespan on an hourly timer rather than on
      write: a trail that only expires when the operator acts is not retention on an
      idle machine. Nothing sweeps while the host is off — that gap is unavoidable,
      and the sweep runs once at startup so it closes as soon as the host is back.
"""

import asyncio
import contextlib
import datetime
import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.db import Database
from control.app.models import AuditAction, AuditEntry
from control.app.models.audit import LABEL_MAX_LENGTH

logger = logging.getLogger(__name__)

# How often the trail is swept. An hour, not a day: the window is measured in days, so
# an hourly pass keeps what is on disk within a few hours of what the operator was
# promised, and the query it runs is one indexed delete.
SWEEP_INTERVAL_SECONDS = 60 * 60


def record(
    session: AsyncSession,
    action: AuditAction,
    *,
    first_label: str | None = None,
    second_label: str | None = None,
) -> AuditEntry:
    """Add one entry to the caller's transaction. Does not commit.

    Call it immediately before the commit that makes the change durable, from the
    service that made it. Two rules come with it and neither is expressible in a type,
    so they are written here and asserted by the zone's tests:

    * **A label is a value read off an inventory row, copied whole** — ``Node.name``,
      ``Friend.nickname``, a transport name, a ``NodeState`` — and never composed from
      one. ``f"{node.name}: {node.state_detail}"`` satisfies every other rule on this
      table and is exactly the hole this closes: ``state_detail`` is 500 characters of
      free text that can carry a remote host's words, and it sits one attribute away
      from ``state``, which the decision permits.
    * **Only changes that committed.** No probe, no login, no failure, no refusal.

    The length check is the mechanical half of the first rule: the column is as wide as
    the widest inventory value and no wider, so a composed label usually fails here
    rather than arriving truncated — ``ValueError`` because it is a programming mistake
    in this repository, never operator input, and a silent truncation would leave a
    half-sentence in the trail with nobody to notice.
    """
    for label in (first_label, second_label):
        if label is not None and len(label) > LABEL_MAX_LENGTH:
            raise ValueError(
                "an audit label is a value read off an inventory row — a node name, a "
                f"nickname, a transport name, a state — and none is longer than "
                f"{LABEL_MAX_LENGTH} characters. Refusing to store a label this long: "
                "it was composed from something rather than copied from it."
            )

    entry = AuditEntry(action=action, first_label=first_label, second_label=second_label)
    session.add(entry)
    return entry


async def sweep(session: AsyncSession, *, retention_days: int) -> int:
    """Delete every entry older than the window. Returns how many went.

    The cutoff is computed here rather than in SQL so the caller's clock is the one
    that decides — which is what lets a test plant an old entry and watch it go without
    waiting a month.

    Commits its own transaction: this is called from the sweeper's own session, never
    inside an operator's unit of work.
    """
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
    result = await session.execute(delete(AuditEntry).where(AuditEntry.at < cutoff))
    await session.commit()
    return result.rowcount


async def sweep_forever(database: Database, *, retention_days: int) -> None:
    """Sweep now, then once an hour, until the task is cancelled.

    Started by the application lifespan and cancelled by it at shutdown. Two properties
    matter more than the schedule:

    * **A failed pass never ends the loop.** The database being briefly unreachable
      would otherwise stop retention for the lifetime of the process, silently, and the
      operator would find out only by the trail never shrinking. The failure is logged
      and the next pass happens on the ordinary interval.
    * **``CancelledError`` is not caught**, so shutdown is immediate rather than up to
      an hour late.

    The session comes from the same generator every request uses, consumed with
    ``async for`` exactly as the test fixtures do it: one session, closed when the body
    ends, rolled back if the body raised.
    """
    while True:
        try:
            deleted = 0
            async for session in database.session():
                deleted = await sweep(session, retention_days=retention_days)
            if deleted:
                # A count and nothing else. Which entries went is not loggable: their
                # labels are the names this table exists to keep briefly, and a log
                # file is the one place with no retention window at all.
                logger.info("audit trail swept: %d entries past the window", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The traceback, because this runs with nobody watching and a sweep that
            # stops working leaves a record growing past the window it promised. It
            # names no friend and no node: the statement is one comparison against a
            # timestamp.
            logger.exception(
                "the audit retention sweep failed; the next attempt is in %d seconds",
                SWEEP_INTERVAL_SECONDS,
            )
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start_sweeper(database: Database, *, retention_days: int) -> asyncio.Task:
    """The sweeper as a task, for the lifespan to hold and cancel."""
    return asyncio.create_task(
        sweep_forever(database, retention_days=retention_days), name="audit-retention-sweep"
    )


async def stop_sweeper(task: asyncio.Task) -> None:
    """Cancel the sweeper and wait for it, swallowing its own cancellation.

    Awaited rather than merely cancelled: a task dropped at shutdown produces a
    "Task was destroyed but it is pending" warning from asyncio and, worse, may be
    holding a database connection the dispose below is about to close underneath it.
    """
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
