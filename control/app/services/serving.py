"""Did the daemon this apply restarted actually come up AND start serving? — M26.

WHAT: ``confirm_serving`` — a bounded settle-and-resample over a node's containers AND
      over its listening sockets, which refuses to conclude from one sample and refuses
      to conclude about SERVING from a reading of LIVENESS. It answers with the placed
      configs observed running continuously across a measured interval with something
      holding the port they were given, the ones running and holding nothing, the ones
      still crash-looping when the wait ended, the ones that never came up at all, and
      the ones whose port question nobody could ask.
WHY:  two acceptance walks, one fault each, and the second one is why the socket reading
      is in this module rather than only in the probe.

      * **Walk 2.** The apply looked once, in the first second of the container's first
        start — running, not yet restarting — concluded the node was serving, cleared a
        true probe finding and left the row reading ``active / in sync`` while the
        container sat in a crash loop and the user's ping was 100% loss. The same check
        fired the other way on a leaf whose container came up a moment later: ``degraded``
        while that user's ping was 0% loss.
      * **Walk 3.** With the crash loop closed, the walk replaced a leaf's image with one
        identical except that the data plane's ``up`` exits 0 having done nothing. The
        node's own generated compose command is ``sh -c 'set -e; … "$0" up "$1"; while :;
        do sleep 86400 & wait $!; done'`` — so a data plane that returns 0 without
        establishing anything leaves the container up FOR EVER. The apply reported
        success, deleted a true probe finding, and the row read ``active / in sync`` over
        a host with no tunnel device, no process but ``sleep 86400``, and 100% loss across
        the hop. Deterministic, reproduced twice.

      Given that supervisor shape, container liveness is not a weak signal for whether a
      node is serving — it is an UNRELATED one. A container that holds a port and a
      container running ``sleep 86400`` are indistinguishable to it, permanently. So this
      module asks the second question too, and it asks the one the probe already asks:
      **an apply may only clear a finding it has actually contradicted, with a
      measurement of the same kind.**

      * **Walk 4.** The port question was defeated twice in one walk: once by ``nc -u -l``
        on the number, and once — contriving nothing — by the real data plane with its
        peer removed, which is what an ordinary wrong peer key leaves behind. Device up,
        right daemon, right port, ``peers=[]``, 100% loss, and this module confirmed it.
        A question about a SOCKET is answered by anything holding the number, so this
        module now also puts each transport's OWN serving question to the node
        (``TransportMeta.serving_question``, run by ``edge.health.serving``), and for a
        transport that declares one, THAT is what confirms it — the held port no longer
        does. A transport that declares none is confirmed by the port exactly as before,
        which is the most anything can say about it and is said as no more.
HOW:  three things make the answer stable, and none of them is a longer sleep.

      * **Two readings, not one.** A container that is up in two readings taken an
        interval apart has survived that interval. One reading is an instant and an
        instant is what walk 2 caught.
      * **The readings have to be comparable.** ``RunningContainers.started`` carries an
        opaque token per service saying which LIFE of that container was looked at, so
        "up in both" is not satisfied by two different lives of a crash loop — which is
        what a pair of readings either side of a fast restart would otherwise look like.
        A service whose token is empty is never confirmed: an engine that would not say
        which life it was cannot be argued with.
      * **And the port is asked about, in THREE answers rather than two** — held, not
        held, and nobody could ask (``edge.health.listening.bound_ports`` returns ``None``
        for a host without ``ss`` and for a table it did not understand). The third state
        is the reason walk 2 gave for not asking at all; it is a reason to HANDLE the
        state, not to skip the reading. A reading that could not be taken never confirms
        anything and never refuses anything: it leaves the config unchecked, the caller
        keeps whatever finding was standing, and no host loses an apply because it is
        missing a tool.

      The port question is inside the settle loop rather than after it, and that is not
      tidiness: a daemon binds its socket some time after its container starts, so a
      reading taken at the instant of the last container reading would call a healthy
      late binder dead — walk 2's false red rebuilt one layer down. A late binder gets
      exactly the patience a late starter gets.

      The loop stops as soon as everything expected is confirmed, and otherwise when the
      ceiling runs out — so a healthy node costs one interval and a broken one costs the
      ceiling once, rather than the operator's afternoon. Whatever is unconfirmed when
      the wait ends is reported as unconfirmed; the wait ending is not evidence of
      anything and this module never treats it as such.

      THE TIMING LIVES HERE AND NOT IN ``edge`` — the zone rule, and it is the right
      line: `edge` reads a host and says what it saw, and how long to watch a node before
      believing it is a decision about this control plane's own patience. Both readings
      are `edge`'s (``node_stack.running_containers``, ``listening.bound_ports``); every
      clock in this file is ours.
"""

import asyncio
import logging
import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from edge.bootstrap import NodeConnection, node_stack
from edge.health import listening
from edge.health import serving as serving_question
from edge.health.serving import ServingCheck
from edge.registry import Layer4

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settled:
    """What a node's containers and sockets were doing when the watching stopped.

    Two axes, because the walks found one fault on each and a single verdict would hide
    whichever of them the other explains. The first is liveness — did this container stay
    up — and every placed config lands in exactly one of its three answers. The second is
    the socket, asked only of the configs that stayed up, because the port question means
    nothing about a container that never started.

    A caller that adds the first axis up and finds a name missing is looking at a bug in
    this module, not at a node.
    """

    # Config name → the digest the container was created with, for every config observed
    # running as ONE life of one container across the settle interval. The digest is off
    # the later of the two readings; a container's labels are fixed when it is created,
    # so the two readings cannot disagree about it without also disagreeing about which
    # life they saw.
    #
    # STAYING UP IS NOT SERVING — walk 3, and the two axes of this type are the whole of
    # that finding. A name is in here on the strength of the engine's reading alone, and
    # the node's own compose command keeps a container up for as long as its data plane's
    # ``up`` returned 0, whatever it then did. What a caller wants before it says a node
    # is serving is this MINUS ``not_listening`` and ``unchecked``.
    staying_up: dict[str, str]

    # Config names whose container the engine was restarting after a death when the wait
    # ended. Sorted.
    restarting: tuple[str, ...]

    # Config names whose container was neither staying up nor restarting: never created,
    # stopped, exited for good — or up in one reading and a different life in the next,
    # which is a crash loop caught between two of its lives. Sorted.
    absent: tuple[str, ...]

    # Config names that stayed up and whose declared port NOTHING held when the wait
    # ended — walk 3's host, and the one the probe would have refused. Sorted.
    #
    # It is a subset of ``staying_up``: a container has to be up for "up and serving
    # nothing" to be the fault it has.
    not_listening: tuple[str, ...]

    # Config names that stayed up and whose transport's OWN serving question was asked and
    # answered NO — walk 4's two hosts: a data plane replaced by something that holds the
    # port, and the real one holding a port and none of the peers it was given. Sorted,
    # and a subset of ``staying_up``.
    #
    # Its own list rather than folded into ``not_listening`` for the reason the probe
    # keeps the two apart (``NodeHealth.not_serving``): one says nothing holds the number,
    # the other says what holds it is not doing the job, and an operator told the wrong
    # one goes and looks at the wrong thing.
    not_serving: tuple[str, ...]

    # Config names that stayed up, were refused by nothing, and were CONFIRMED by nothing
    # either. Sorted, and also a subset of ``staying_up``. Since walk 4 what confirms a
    # config is its transport's own serving question when it declares one, and the held
    # port when it does not — so a config is here when THAT reading could not be taken:
    # the question could not be put (an image without the tool, an engine that would not
    # exec it) or its reader declined to judge, or — for a transport with no question —
    # no port was resolved for the row or the socket table could not be read.
    #
    # NOT A FAILURE AND NOT A CONFIRMATION, which is the point of it being its own list.
    # A host without ``ss`` still applies — refusing there would widen an apply's failure
    # surface on the strength of a missing tool — but nothing may be said about what it
    # is serving, so a caller holding a finding about this node has not contradicted it,
    # and a caller reporting success has to say that this part was not measured.
    unchecked: tuple[str, ...]

    # How long this took and how many times the node was asked, for the log line. Not
    # part of any operator-facing sentence: what the operator needs is which transports,
    # and a duration reads as a promise about how long the next one will take.
    waited: float
    readings: int

    # Config names that are SERVING by the only reading their transport offers — the held
    # port — because the transport declares no serving question of its own. Sorted, and a
    # subset of ``serving``. M31.5: such a config is measured, but by "something holds
    # this number", which ``nc`` satisfies as well as the daemon does (walk 4); a caller
    # that says what an apply established has to be able to say this part was the weaker
    # reading. Empty when every serving config answered its transport's own question.
    port_only: tuple[str, ...] = ()

    # Service name → the opaque token for the LIFE of the container the last reading saw
    # (``RunningContainers.started``) — M31.3. Exposed so a caller holding a reading taken
    # BEFORE it acted can tell a container its own action restarted from one it left
    # alone; compared for equality and never read as a time, the rule that type states.
    started: Mapping[str, str] = field(default_factory=dict)

    @property
    def serving(self) -> dict[str, str]:
        """The configs this wait may honestly claim are serving, with their digests.

        Staying up, and confirmed by the strongest reading this transport offers — its own
        serving question, or the held port when it declares none. Derived rather than
        stored so it cannot disagree with the two lists it subtracts — the shape
        ``NodeHealth.unchecked_ports`` already keeps one zone over, and for the same
        reason: a second stored list is a second place for one answer to be wrong.
        """
        withheld = set(self.not_listening) | set(self.not_serving) | set(self.unchecked)
        return {
            name: digest
            for name, digest in self.staying_up.items()
            if name not in withheld
        }


@dataclass(frozen=True)
class _Reading:
    """One glance at a node: what its containers are doing, and what holds its ports.

    The two are taken as close together as one session allows and travel together, so
    the pair comparison below cannot accidentally compare a container reading with a
    socket reading from a different moment.

    ``bound`` is ``None`` when the socket table could not be read — a host with no ``ss``,
    a command that refused, or a table this code did not understand. Not the same fact as
    an empty table, and ``edge.health.listening.bound_ports`` is where that distinction is
    made and defended.
    """

    containers: node_stack.RunningContainers
    bound: dict[Layer4, frozenset[int]] | None

    # Each running config's answer to its transport's OWN serving question — walk 4.
    # ``True`` / ``False`` / ``None`` as ``edge.health.serving.ask`` gives them, and a
    # config ABSENT here declared no question or was not running in this reading, which
    # is a different fact from ``None`` (asked, and nobody could answer).
    answers: dict[str, bool | None]


async def confirm_serving(
    connection: NodeConnection,
    *,
    expected: Collection[str],
    listeners: Mapping[str, listening.Listener],
    checks: Mapping[str, ServingCheck],
    interval: float,
    timeout: float,
) -> Settled:
    """Watch ``expected`` until each is known to be staying up and answering, or until
    time runs out.

    ``listeners`` says where each placed config should be answering — the port off the
    operator's own row and the protocols off the transport's declaration, resolved by the
    caller exactly as ``edge.health.probe`` requires them. It is REQUIRED rather than
    defaulted: a default of "ask nothing" is how the socket question went unasked through
    two walks, and a caller with nothing to pass says so by passing nothing.

    ``checks`` is each placed config's transport's own serving question, built by the
    caller (``apply.serving_checks``) for the same reason ``listeners`` is: which
    transport rendered which config, and what was rendered, are the caller's facts.
    REQUIRED for ``listeners``' reason — the port question went unasked for two walks
    behind a default, and this one would go unasked behind one too.

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
            staying_up={},
            restarting=(),
            absent=(),
            not_listening=(),
            not_serving=(),
            unchecked=(),
            waited=0.0,
            readings=0,
        )

    readings = 1
    previous = None
    current = await _read(connection, listeners, checks)

    while True:
        if previous is not None:
            settled = _one_life_across_both(previous, current, names)
            # Confirmed means staying up AND refused by no reading. A config whose
            # reading could not be taken stops the loop with the others rather than
            # holding it open to the ceiling: no amount of waiting installs ``ss`` on
            # that host, and the answer it gets is "unchecked" either way.
            #
            # A NO from a transport's own question keeps the loop going exactly as an
            # unheld port does, and for the same reason: a wg-family interface is
            # configured some moments after its container starts, and asking at the
            # instant of the last container reading would call a healthy late
            # configurer dead — walk 2's false red, rebuilt one layer further in.
            if len(settled) == len(names) and not _refused_by_a_reading(
                current, listeners, settled
            ):
                return _answer(settled, current, listeners, names, started_at, readings)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # Never past the deadline, so the ceiling is a ceiling on the whole wait rather
        # than on the wait before the last interval.
        await asyncio.sleep(min(interval, remaining))
        previous, current = current, await _read(connection, listeners, checks)
        readings += 1

    settled = (
        _one_life_across_both(previous, current, names) if previous is not None else {}
    )
    return _answer(settled, current, listeners, names, started_at, readings)


async def _read(
    connection: NodeConnection,
    listeners: Mapping[str, listening.Listener],
    checks: Mapping[str, ServingCheck],
) -> _Reading:
    """One reading of all three questions, the containers first.

    The socket table is skipped entirely when no config has a port expectation, which is
    not an optimisation: an ``ss`` whose answer nothing could be compared against is a
    command run on a node for no reason, and this zone runs none of those.

    The serving questions are put only to configs whose container is running in THIS
    reading — the same rule ``edge.health.probe`` keeps: exec-ing into a container that
    is not up turns one fault into two sentences about one host.
    """
    containers = await node_stack.running_containers(connection)
    bound = await listening.bound_ports(connection) if listeners else None
    answers = (
        await serving_question.ask(connection, checks=checks, about=containers.loaded)
        if checks
        else {}
    )
    return _Reading(containers=containers, bound=bound, answers=answers)


def _one_life_across_both(
    previous: _Reading,
    current: _Reading,
    names: Collection[str],
) -> dict[str, str]:
    """The configs running as ONE life of one container in both readings.

    Three conditions, and dropping any one of them is how this becomes a check that
    cannot fail: running in the earlier reading, running in the later one, and the same
    life in both. A container that crashed and came back between them satisfies the
    first two — that is exactly the reading walk 2's apply took — and is refused by the
    third.

    An empty token is refused with them. It means the engine printed nothing for that
    container's start, and two silences are not an agreement.
    """
    staying_up = {}
    for name in names:
        if name not in previous.containers.loaded or name not in current.containers.loaded:
            continue
        token = current.containers.started.get(name, "")
        if not token or previous.containers.started.get(name, "") != token:
            continue
        staying_up[name] = current.containers.loaded[name]
    return staying_up


def _answering(
    reading: _Reading, listeners: Mapping[str, listening.Listener], name: str
) -> bool | None:
    """Whether something holds this config's port — ``None`` when nobody could ask.

    THREE ANSWERS, and the third is why this exists as a function rather than as a
    condition. "Nothing is listening" and "the socket table could not be read" are
    different facts about a node, and collapsing them would mark a host missing one tool
    as a host serving nothing — the shape of wrongness this milestone is about, pointed
    the other way. The same three the probe reports (``NodeHealth.unchecked_ports``).
    """
    listener = listeners.get(name)
    if listener is None or reading.bound is None:
        return None
    return listening.is_answering(reading.bound, listener)


def _refused_by_a_reading(
    reading: _Reading,
    listeners: Mapping[str, listening.Listener],
    staying_up: Mapping[str, str],
) -> bool:
    """Is any config that stayed up known NOT to be serving, in this reading?

    Two refusals: a definite reading of a socket table without the port in it, and a
    transport's own question answered NO. ``None`` from either does not keep the loop
    going, for the reason ``confirm_serving`` gives at the call site.
    """
    return any(
        _answering(reading, listeners, name) is False
        or reading.answers.get(name) is False
        for name in staying_up
    )


def _confirmed(
    reading: _Reading, listeners: Mapping[str, listening.Listener], name: str
) -> bool:
    """Whether the strongest reading this config's transport offers said YES.

    THE TRANSPORT'S OWN QUESTION WHEN IT DECLARED ONE — walk 4 — and the held port only
    when it did not. A held port is no longer what confirms a transport that can be asked
    something sharper: ``nc`` holds a port, and so does a wg-family daemon holding none of
    the peers it was given. Whether a config declared a question is read off the reading
    (an entry in ``answers``), never off its transport's name.

    What the port no longer does is CONFIRM such a config; it can still REFUSE it
    (``_refused_by_a_reading``). A definite socket table without the declared port is a
    fault whatever the transport says about itself, and keeping that refusal costs
    nothing for a data plane whose socket ``ss`` lists — which the shipped wg family's is.
    """
    if name in reading.answers:
        return reading.answers[name] is True
    return _answering(reading, listeners, name) is True


def _answer(
    staying_up: Mapping[str, str],
    current: _Reading,
    listeners: Mapping[str, listening.Listener],
    names: Collection[str],
    started_at: float,
    readings: int,
) -> Settled:
    """Sort every expected config into exactly one liveness answer, and every one that
    stayed up into exactly one socket answer."""
    unconfirmed = set(names) - set(staying_up)
    restarting = sorted(unconfirmed & set(current.containers.restarting))
    held = {name: _answering(current, listeners, name) for name in staying_up}
    not_listening = {name for name, answer in held.items() if answer is False}
    not_serving = {name for name in staying_up if current.answers.get(name) is False}
    # Everything that stayed up, was refused by nothing and was confirmed by nothing.
    unchecked = {
        name
        for name in staying_up
        if name not in not_listening
        and name not in not_serving
        and not _confirmed(current, listeners, name)
    }
    # Confirmed, and confirmed by the port because no question of the transport's own was
    # put: a config that declared one has an entry in ``answers`` (``_confirmed``).
    port_only = {
        name
        for name in staying_up
        if name not in not_listening
        and name not in not_serving
        and name not in unchecked
        and name not in current.answers
    }
    answer = Settled(
        staying_up=dict(staying_up),
        restarting=tuple(restarting),
        absent=tuple(sorted(unconfirmed - set(restarting))),
        not_listening=tuple(sorted(not_listening)),
        not_serving=tuple(sorted(not_serving)),
        unchecked=tuple(sorted(unchecked)),
        waited=time.monotonic() - started_at,
        readings=readings,
        port_only=tuple(sorted(port_only)),
        started=dict(current.containers.started),
    )
    # No node name, no address, no transport parameters, and no PORT — the same rule
    # every log line in this zone keeps, and the socket reading makes the last of those
    # worth saying out loud. Counts and a duration, which is what a slow settle looks
    # like from here when somebody asks why an apply took twenty seconds.
    logger.info(
        "settled after %d readings in %.1fs: %d serving, %d up holding nothing, "
        "%d up and not serving by their own check, %d unchecked, %d restarting, "
        "%d absent",
        answer.readings,
        answer.waited,
        len(answer.serving),
        len(answer.not_listening),
        len(answer.not_serving),
        len(answer.unchecked),
        len(answer.restarting),
        len(answer.absent),
    )
    return answer
