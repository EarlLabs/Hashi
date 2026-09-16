"""Did the daemon this apply restarted actually stay up? — M26, the second walk.

WHAT: ``confirm_serving`` — a bounded settle-and-resample over a node's containers that
      refuses to conclude from one sample. It answers with the placed configs observed
      running CONTINUOUSLY across a measured interval, the ones still crash-looping when
      the wait ended, and the ones that never came up at all.
WHY:  the walk pressed apply on a leaf whose data plane could not start. Step 5 of the
      apply looked once, in the first second of the container's first start — running,
      not yet restarting — concluded the node was serving, cleared a true probe finding
      and left the row reading ``active / in sync`` for at least 65 seconds while the
      container sat in a crash loop and the friend's ping was 100% loss. The same check
      fired the other way on a leaf whose container came up a moment later: the row read
      ``degraded`` while that friend's ping was 0% loss.

      Both directions are the same defect, and it is this project's signature one in its
      newest form — not a verification that cannot fail, but one that fails AT RANDOM,
      depending on how fast a container starts. An operator told their node is broken
      while it carries traffic is an operator who learns to ignore the warning.
HOW:  two things make the answer stable, and neither is a longer sleep.

      * **Two readings, not one.** A container that is up in two readings taken an
        interval apart has survived that interval. One reading is an instant and an
        instant is what the walk caught.
      * **The readings have to be comparable.** ``RunningContainers.started`` carries an
        opaque token per service saying which LIFE of that container was looked at, so
        "up in both" is not satisfied by two different lives of a crash loop — which is
        what a pair of readings either side of a fast restart would otherwise look like.
        A service whose token is empty is never confirmed: an engine that would not say
        which life it was cannot be argued with.

      The loop stops as soon as everything expected is confirmed, and otherwise when the
      ceiling runs out — so a healthy node costs one interval and a broken one costs the
      ceiling once, rather than the operator's afternoon. Whatever is unconfirmed when
      the wait ends is reported as unconfirmed; the wait ending is not evidence of
      anything and this module never treats it as such.

      THE TIMING LIVES HERE AND NOT IN ``edge`` — the zone rule, and it is the right
      line: `edge` reads a host and says what it saw, and how long to watch a node before
      believing it is a decision about this control plane's own patience. The reading is
      `edge`'s (``node_stack.running_containers``); every clock in this file is ours.
"""

import asyncio
import logging
import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from edge.bootstrap import NodeConnection, node_stack

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settled:
    """What a node's containers were still doing when the watching stopped.

    Three answers rather than two, and the third is the one the walk needed: a container
    that never came up and one the engine is restarting after it died are different
    faults with different repairs, and neither of them is "it is serving".

    Every placed config is in exactly one of the three. A caller that adds them up and
    finds a name missing is looking at a bug in this module, not at a node.
    """

    # Config name → the digest the container was created with, for every config observed
    # running as ONE life of one container across the settle interval. The digest is off
    # the later of the two readings; a container's labels are fixed when it is created,
    # so the two readings cannot disagree about it without also disagreeing about which
    # life they saw.
    staying_up: dict[str, str]

    # Config names whose container the engine was restarting after a death when the wait
    # ended. Sorted.
    restarting: tuple[str, ...]

    # Config names whose container was neither staying up nor restarting: never created,
    # stopped, exited for good — or up in one reading and a different life in the next,
    # which is a crash loop caught between two of its lives. Sorted.
    absent: tuple[str, ...]

    # How long this took and how many times the node was asked, for the log line. Not
    # part of any operator-facing sentence: what the operator needs is which transports,
    # and a duration reads as a promise about how long the next one will take.
    waited: float
    readings: int


async def confirm_serving(
    connection: NodeConnection,
    *,
    expected: Collection[str],
    interval: float,
    timeout: float,
) -> Settled:
    """Watch ``expected`` until each is known to be staying up, or until time runs out.

    ``interval`` is how far apart two readings have to be before the pair means
    anything, and ``timeout`` is the ceiling on the whole wait. Both come from settings
    rather than from constants here, because they are the one pair of values a real
    fleet can force us to raise — a node on a slow link whose images are being pulled
    legitimately takes longer to come back than one on a laptop.

    A ceiling shorter than one interval confirms nothing, and that is the honest answer
    rather than a special case: nothing watched the node, so nothing may be said about
    whether it stayed up. Every arm of this function fails in that direction.
    """
    started_at = time.monotonic()
    deadline = started_at + timeout
    names = set(expected)
    if not names:
        # A node with nothing placed on it. Reached only by a caller that renders no
        # configs, which ``apply`` refuses far above this line — answered rather than
        # asserted, because an empty answer is correct and an exception here would turn
        # an impossible state into an outage.
        return Settled(
            staying_up={}, restarting=(), absent=(), waited=0.0, readings=0
        )

    readings = 1
    previous = None
    current = await node_stack.running_containers(connection)

    while True:
        if previous is not None:
            settled = _one_life_across_both(previous, current, names)
            if len(settled) == len(names):
                return _answer(settled, current, names, started_at, readings)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # Never past the deadline, so the ceiling is a ceiling on the whole wait rather
        # than on the wait before the last interval.
        await asyncio.sleep(min(interval, remaining))
        previous, current = current, await node_stack.running_containers(connection)
        readings += 1

    settled = (
        _one_life_across_both(previous, current, names) if previous is not None else {}
    )
    return _answer(settled, current, names, started_at, readings)


def _one_life_across_both(
    previous: node_stack.RunningContainers,
    current: node_stack.RunningContainers,
    names: Collection[str],
) -> dict[str, str]:
    """The configs running as ONE life of one container in both readings.

    Three conditions, and dropping any one of them is how this becomes a check that
    cannot fail: running in the earlier reading, running in the later one, and the same
    life in both. A container that crashed and came back between them satisfies the
    first two — that is exactly the reading the walk's apply took — and is refused by the
    third.

    An empty token is refused with them. It means the engine printed nothing for that
    container's start, and two silences are not an agreement.
    """
    staying_up = {}
    for name in names:
        if name not in previous.loaded or name not in current.loaded:
            continue
        token = current.started.get(name, "")
        if not token or previous.started.get(name, "") != token:
            continue
        staying_up[name] = current.loaded[name]
    return staying_up


def _answer(
    staying_up: Mapping[str, str],
    current: node_stack.RunningContainers,
    names: Collection[str],
    started_at: float,
    readings: int,
) -> Settled:
    """Sort every expected config into exactly one of the three answers."""
    unconfirmed = set(names) - set(staying_up)
    restarting = sorted(unconfirmed & set(current.restarting))
    answer = Settled(
        staying_up=dict(staying_up),
        restarting=tuple(restarting),
        absent=tuple(sorted(unconfirmed - set(restarting))),
        waited=time.monotonic() - started_at,
        readings=readings,
    )
    # No node name, no address, no transport parameters — the same rule every log line
    # in this zone keeps. Counts and a duration, which is what a slow settle looks like
    # from here when somebody asks why an apply took twenty seconds.
    logger.info(
        "settled after %d readings in %.1fs: %d staying up, %d restarting, %d absent",
        answer.readings,
        answer.waited,
        len(answer.staying_up),
        len(answer.restarting),
        len(answer.absent),
    )
    return answer
