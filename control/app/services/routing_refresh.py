"""The routing lists' nightly refresh, and "fetch now" — M34.

WHAT: ``due`` (is tonight's run owed), ``nightly_pass`` (fetch every source that is on, then
      apply every entry whose config the lists changed), ``apply_changed`` (that second
      half on its own, which the Routing screen's "apply" also calls), the loop the app's
      lifespan holds, and ``FetchNow`` — the owner's "fetch now", run beside the request
      that asked for it rather than inside it.
WHY:  the owner accepted (2026-10-03) that list updates apply by themselves at night.
      Applying restarts Xray, which drops every connected user for a second or two, so it
      runs in the backup's quiet hour (``HASHI_BACKUP_AT`` in ``HASHI_BACKUP_TZ``) and
      touches only the entries whose rendered config actually differs from what they hold.
      A fetch can take tens of seconds against a slow host, so no page waits for one.
HOW:  the loop wakes every ``HASHI_ROUTING_CHECK_INTERVAL`` seconds and asks ``due``; the
      run is owed once per local day, at or after the hour, and the day is written BEFORE
      the run so a run that crashes is not retried in a loop. A control plane that was down
      at the hour runs it when it comes back the same day — the backup schedule's reasoning
      (scripts/backup-schedule.sh), for the same failure: a minute that passes unrecorded.

      The control plane polls and fetches; no node is asked for anything but its apply,
      and nothing a node carried is read. It logs source names, node ids and counts only.
"""

import asyncio
import contextlib
import dataclasses
import datetime
import logging
import zoneinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.db import Database
from control.app.models import Node, NodeState, RoutingSchedule
from control.app.services import apply, console, routing

logger = logging.getLogger(__name__)


# The hour scripts/backup-run.sh falls back to for a malformed HASHI_BACKUP_AT — the same
# value, so the two jobs keep sharing an hour when the setting is wrong.
FALLBACK_HOUR = datetime.time(4, 0)


@dataclasses.dataclass(frozen=True)
class QuietHour:
    """The hour and zone the nightly run uses, and what was wrong with the settings, if anything."""

    at: datetime.time
    zone: datetime.tzinfo
    label: str  # how the screen names it, e.g. "04:00 Europe/Moscow"
    problem: str | None


def quiet_hour(settings) -> QuietHour:
    """``HASHI_BACKUP_AT`` in ``HASHI_BACKUP_TZ``, read with the backup script's tolerance.

    A malformed hour is 04:00 and an empty or unknown zone is UTC (this container's clock),
    each with a sentence saying so — never a refusal to boot over a backup setting.
    """
    problems = []
    try:
        hours, minutes = settings.backup_at.strip().split(":")
        at = datetime.time(int(hours), int(minutes))
        if len(hours) != 2 or len(minutes) != 2:
            raise ValueError
    except ValueError:
        at = FALLBACK_HOUR
        problems.append(f"HASHI_BACKUP_AT={settings.backup_at!r} is not HH:MM, so 04:00 is used")
    zone_name = settings.backup_tz.strip()
    zone: datetime.tzinfo = datetime.UTC
    if not zone_name:
        problems.append("HASHI_BACKUP_TZ is not set, so UTC is used")
        zone_name = "UTC"
    else:
        try:
            zone = zoneinfo.ZoneInfo(zone_name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            problems.append(
                f"HASHI_BACKUP_TZ={zone_name!r} is not a zone this control plane knows, "
                "so UTC is used"
            )
            zone_name = "UTC"
    return QuietHour(
        at=at,
        zone=zone,
        label=f"{at.strftime('%H:%M')} {zone_name}",
        problem="; ".join(problems) + "." if problems else None,
    )


def local_day(now: datetime.datetime, settings) -> datetime.date:
    return now.astimezone(quiet_hour(settings).zone).date()


def due(now: datetime.datetime, settings, last_run_on: datetime.date | None) -> bool:
    """Whether tonight's run is owed: past the backup's hour, and not yet run today."""
    hour = quiet_hour(settings)
    local = now.astimezone(hour.zone)
    if local.time() < hour.at:
        return False
    return last_run_on is None or last_run_on < local.date()


def schedule_line(settings) -> str:
    """The sentence the Routing screen states the schedule in."""
    if settings.routing_check_interval <= 0:
        return (
            "The nightly refresh is off (HASHI_ROUTING_CHECK_INTERVAL=0); lists change only "
            "when you press fetch now."
        )
    hour = quiet_hour(settings)
    line = (
        f"Every night at {hour.label} — the backup's hour (HASHI_BACKUP_AT, "
        "HASHI_BACKUP_TZ) — the sources that are on are fetched, and every entry whose "
        "config changed is applied. Applying restarts the entry's proxy: anyone connected "
        "through it is dropped for a second or two."
    )
    return f"{line} {hour.problem}" if hour.problem else line


async def _schedule(session: AsyncSession) -> RoutingSchedule:
    row = await session.get(RoutingSchedule, 1)
    if row is None:
        row = RoutingSchedule(id=1, last_run_on=None)
        session.add(row)
        await session.flush()
    return row


async def last_run_on(session: AsyncSession) -> datetime.date | None:
    row = await session.get(RoutingSchedule, 1)
    return row.last_run_on if row else None


async def nodes_switched_on(session: AsyncSession) -> list[Node]:
    result = await session.execute(
        select(Node).where(Node.direct_routing.is_(True)).order_by(Node.name)
    )
    return list(result.scalars().unique())


@dataclasses.dataclass(frozen=True)
class Applied:
    node: str
    failure: str | None  # None: applied


async def apply_changed(session: AsyncSession) -> list[Applied]:
    """Apply every serving node with the switch on whose config differs from what it holds.

    "Differs" is the Nodes screen's own drift reading (``console.drift_of``), so an entry
    this applies is one that screen was already calling behind, and one in sync is never
    restarted. Through ``apply.apply_nodes``, the fan-out every other automatic apply uses:
    a node not serving is refused rather than taken into service.

    What that costs is stated rather than hidden: an entry that was behind for another
    reason — the owner changed something and did not apply it — gets that change too.
    The same is already true of every automatic apply (M32's add-a-user), and an entry the
    owner wants left alone is one whose switch they turn off.
    """
    behind = []
    for node in await nodes_switched_on(session):
        if node.state not in NodeState.serving():
            continue
        if await console.drift_of(session, node) in (console.IN_SYNC, console.NOTHING_ENABLED):
            continue
        behind.append(node)
    if not behind:
        return []
    names = {node.id: node.name for node in behind}
    outcomes = await apply.apply_nodes(session, [node.id for node in behind])
    return [
        Applied(node=names[node_id], failure=None if outcome is None else outcome.reason)
        for node_id, outcome in outcomes.items()
    ]


async def nightly_pass(
    database: Database, settings, *, now: datetime.datetime | None = None
) -> bool:
    """Run tonight's refresh if it is owed. Returns whether it ran.

    The lists are fetched only while some node has the switch on: a feature nobody uses
    is a feature that has no reason to contact a list host every night.
    """
    now = now or datetime.datetime.now(datetime.UTC)
    ran = False
    async for session in database.session():
        ran = await _run_if_due(session, settings, now)
    return ran


async def _run_if_due(session: AsyncSession, settings, now: datetime.datetime) -> bool:
    schedule = await _schedule(session)
    if not due(now, settings, schedule.last_run_on):
        await session.rollback()
        return False
    schedule.last_run_on = local_day(now, settings)
    await session.commit()

    if not await nodes_switched_on(session):
        logger.info("routing refresh: no node has direct routing on; nothing fetched")
        return True
    refreshed = await routing.refresh_all(session, settings)
    applied = await apply_changed(session)
    logger.info(
        "routing refresh: %d source(s) fetched, %d held, %d failed; %d node(s) applied, "
        "%d not updated",
        len(refreshed),
        sum(1 for outcome in refreshed if outcome.outcome == "held"),
        sum(1 for outcome in refreshed if outcome.outcome == "failed"),
        sum(1 for a in applied if a.failure is None),
        sum(1 for a in applied if a.failure is not None),
    )
    return True


async def refresh_forever(database: Database, settings) -> None:
    """Sleep, ask whether tonight's run is owed, run it — until cancelled."""
    while True:
        await asyncio.sleep(settings.routing_check_interval)
        try:
            await nightly_pass(database, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "the routing refresh failed; next check in %.0f seconds",
                settings.routing_check_interval,
            )


def start_refresher(database: Database, settings) -> asyncio.Task | None:
    if settings.routing_check_interval <= 0:
        return None
    return asyncio.create_task(refresh_forever(database, settings), name="routing-refresh")


async def stop_refresher(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class FetchNow:
    """The owner's "fetch now": one run at a time, beside the request that asked for it.

    The request answers at once; the Routing screen asks again while ``running`` and reads
    the result from the rows the run writes. Held on the app's state, so there is one per
    process — and this control plane is one process.
    """

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.started: datetime.datetime | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, database: Database, settings) -> bool:
        """Start a run unless one is going. Returns whether this call started one."""
        if self.running:
            return False

        async def run() -> None:
            try:
                async for session in database.session():
                    await routing.refresh_all(session, settings)
            except Exception:
                logger.exception("fetching the routing lists failed")

        self.started = datetime.datetime.now(datetime.UTC)
        self.task = asyncio.create_task(run(), name="routing-fetch-now")
        return True

    async def stop(self) -> None:
        await stop_refresher(self.task)


__all__ = [
    "Applied",
    "FetchNow",
    "apply_changed",
    "due",
    "nightly_pass",
    "schedule_line",
    "start_refresher",
    "stop_refresher",
]
