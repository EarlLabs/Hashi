"""Is this node serving? — and nothing else.

WHAT: an SSH probe that reports whether a node's data plane is up, whether it is merely
      being restarted, whether anything holds the port each transport was given, whether
      the configuration on it matches what we last pushed, and whether the process that
      is running was started from that configuration — five questions, because M1 proved
      the first two can both be yes while the node serves something else, and M22 proved
      the first one can be yes while nothing has ever started.
WHY:  backlog item 13. The control plane polls; a node never reports in (core
      invariants §1) — an outbound connection from a node to a fixed endpoint is
      both a fingerprint for a censor and a path back to the control plane if the
      node is seized.
HOW:  every field of ``NodeHealth`` is about the NODE. There is deliberately no
      field, and no code path that could produce one, for how many clients are
      connected, which addresses reached it, or how much traffic it carried. The
      charter's no-logging rule covers health: health means "is this node serving",
      never "who used it".

      WHAT "SERVING" MEANS HERE, decided in M22 and written down because the milestone
      was a decision before it was code. Four answers were available — the container
      exists; the container is running and not restarting; something is listening on its
      port; a peer has completed a handshake — and this probe answers the middle two,
      together, per placed config.

      * **Exists** is what shipped, and it is what the field measurement caught: the
        engine reports ``Running: true`` throughout a restart backoff, so a daemon that
        had never once started was reported as serving. Rejected as the answer for the
        reason it was found.
      * **Running and not restarting** costs nothing — one more field in a ``docker
        inspect`` this probe already runs — and catches every daemon that will not start.
        It cannot catch a daemon that starts, binds nothing and idles, and it is a
        SAMPLE: a container that dies 200ms after starting is running when it is looked
        at. Necessary, not sufficient.
      * **Listening on its port** is one more command and answers the second half. It
        also fails in the safe direction: it needs the port the operator gave and the
        protocols the transport declared, and where either is missing the probe says the
        port was not checked instead of inventing an answer. See ``edge.health.listening``
        for why the reading cannot contain a peer's address.
      * **A peer has handshaked** is the question the operator actually has, and it is
        refused on two grounds — it cannot be asked without a command per protocol in
        shared code, and the answer IS a connection record. ``edge.health.listening``'s
        header has the argument in full. Nothing downstream may claim it, which is why
        the console's sentence states what was checked rather than that the node works.

      No transport declares anything new for this. ``listens_on`` already exists, already
      says which protocols a transport binds, and is already read by `control` for the
      port-collision rule — so all four packages are probed by one pair of commands and
      nothing anywhere compares a transport's name to a literal.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from edge.bootstrap.node_stack import config_path_of, digest_of, running_containers
from edge.bootstrap.ssh import NodeConnection, NodeUnreachable
from edge.health.listening import Listener, bound_ports, is_answering

logger = logging.getLogger(__name__)


@dataclass
class NodeHealth:
    """What a probe can truthfully say about a node."""

    reachable: bool

    # Transport names whose container is running on the node — and STAYING running.
    #
    # A container the engine is restarting after it died is not in here since M22, it is
    # in ``restarting``. It used to be: Docker reports ``Running: true`` for the whole of
    # a restart backoff, so a daemon that had never once started was listed here and read
    # as serving.
    running: list[str] = field(default_factory=list)

    # Transport names whose container is being restarted after dying — a crash loop.
    #
    # Its own field rather than an absence from ``running``, for the reason ``stale`` is
    # its own field rather than a kind of ``drifted``: the repairs differ. Nothing running
    # is a transport that was never pushed or a container somebody stopped; a crash loop
    # is a config the daemon will not accept, and the fix is to read what the container
    # itself said and change the configuration — not to apply the same one again.
    restarting: list[str] = field(default_factory=list)

    # Transport names we expected to be running and which are not.
    #
    # A crash-looping one is NOT in here — it is in ``restarting``, which is the more
    # specific and more useful answer about the same transport.
    missing: list[str] = field(default_factory=list)

    # Transport names whose config on the node differs from a fresh render.
    #
    # Only meaningful because rendering is deterministic: a differing digest means
    # someone or something changed the node, not that we rendered differently.
    drifted: list[str] = field(default_factory=list)

    # Transport names whose container is running, on a config that is not the one we
    # would push. A SEPARATE field from ``drifted`` on purpose, and M1's second half.
    #
    # The field measurement of 2026-09-09 is what this exists for: a node whose config
    # on disk matched perfectly and whose daemon had never read it reported
    # ``drifted: []`` — a true answer to a question that does not establish the thing an
    # operator reads it as establishing. Nothing anywhere compared either the file or
    # the digest against what the PROCESS loaded.
    #
    # Not folded into ``drifted`` because the two name different faults with different
    # repairs: drift is somebody editing the node, staleness is an apply that did not
    # take. Reporting staleness as drift would make this report say "the file was
    # changed" about a file nobody touched — the same shape of true-but-misleading
    # answer the milestone is about.
    stale: list[str] = field(default_factory=list)

    # Transport names whose container is running AND whose port something holds — M22.
    #
    # The strongest thing this probe can say, and it is still narrower than "it works":
    # what it establishes is that the port is bound on the node, not that our container
    # is what bound it and not that anything can reach it from outside. See
    # ``edge.health.listening``.
    listening: list[str] = field(default_factory=list)

    # Transport names whose container is running and whose port NOTHING holds.
    #
    # The other half of M22: a daemon that starts, fails to bind and idles is up for ever
    # and carries nobody, and no reading of the container can see it.
    not_listening: list[str] = field(default_factory=list)

    # Operator-facing reason when the node is not healthy.
    detail: str | None = None

    @property
    def unchecked_ports(self) -> list[str]:
        """Running transports this probe could not ask the port question about.

        Derived rather than stored, because it is exactly "everything running that is in
        neither answer" and a second list would be a place for the three to disagree.

        It is not empty in three ordinary cases: the caller named no port for this config
        (a transport that declares none has nothing to check), the caller could not
        resolve one, or the node's socket table could not be read at all. All three are
        "nobody asked", which the operator has to be told apart from "nothing is
        listening" — reporting the first as the second would be this milestone's own
        defect pointed the other way.
        """
        return sorted(set(self.running) - set(self.listening) - set(self.not_listening))

    @property
    def healthy(self) -> bool:
        """Reachable, nothing crash-looping, everything expected up on the config we would
        push, and every port we could check held.

        NOT a claim that a client can connect, and the console's sentence says so. The
        two questions this cannot ask are whether anything reaches the node from outside
        and whether a peer completed a handshake; see this module's header for why the
        second is refused rather than unimplemented.
        """
        return (
            self.reachable
            and not self.restarting
            and not self.missing
            and not self.drifted
            and not self.stale
            and not self.not_listening
        )


async def probe(
    connection: NodeConnection,
    *,
    expected: dict[str, str],
    transports: dict[str, str] | None = None,
    listeners: Mapping[str, Listener] | None = None,
) -> NodeHealth:
    """Probe one node.

    ``expected`` maps the name each config is PLACED under to the config we believe is
    on the node, so this function does no rendering and needs no database — the caller
    renders and passes the result in, which keeps the comparison honest and this module
    pure of everything but SSH.

    ``transports`` says which transport each of those names came from, and defaults to
    the name itself — the single-instance case, which is every node that existed before
    M15. It is needed only to find the file, because the EXTENSION is the transport's
    (``EXTENSION``); a node running two instances of one transport passes it, and a
    caller that does not gets exactly the behaviour it always had.

    ``listeners`` says where each placed config is expected to answer — M22. Passed in
    for ``expected``'s reason: the port is the operator's own parameter and the protocols
    are the transport's declaration, and resolving either would mean a database and a
    registry lookup in a module that has neither. A caller that passes nothing asks no
    port question and gets exactly the behaviour it always had, with every running
    transport reported under ``unchecked_ports`` rather than silently as listening —
    "nobody asked" is never rendered as an answer.
    """
    try:
        # The digest each running container was CREATED with, not merely which services
        # are up — see ``node_stack.loaded_digests``. The weaker question is what let a
        # stale daemon report healthy for eight minutes on a real node. And restarting
        # separately from running, which is M22: the engine calls a crash loop running.
        containers = await running_containers(connection)
    except NodeUnreachable as exc:
        # A blocked or seized node accepts and hangs rather than refusing, so this
        # is the common failure rather than the rare one.
        return NodeHealth(reachable=False, detail=str(exc))

    loaded = containers.loaded
    # Read straight after the container states and before the files, so the two readings
    # of what is UP are as close together as one session allows. ``None`` when the node
    # could not be asked — see ``bound_ports``; not the same fact as an empty table.
    bound = await bound_ports(connection) if listeners else None

    health = NodeHealth(
        reachable=True, running=sorted(loaded), restarting=sorted(containers.restarting)
    )
    # A crash-looping transport is not ALSO missing. It has a container and the operator
    # needs the more specific word for it; saying both would send them to apply again,
    # which is the one repair that changes nothing.
    health.missing = sorted(set(expected) - set(loaded) - set(containers.restarting))

    if bound is not None:
        for config_name in health.running:
            listener = (listeners or {}).get(config_name)
            if listener is None:
                # No port was named for this config, so there is nothing to check and no
                # answer to give. Left out of BOTH lists on purpose — it surfaces as
                # ``unchecked_ports``.
                continue
            target = health.listening if is_answering(bound, listener) else health.not_listening
            target.append(config_name)

    for config_name, config in expected.items():
        wanted = digest_of(config)

        if config_name in loaded and loaded[config_name] != wanted:
            # Up, and up on something else. A container from before this label existed
            # reports an empty digest and lands here too, which is correct: it is
            # provably not running the config we would push.
            health.stale.append(config_name)

        # ``config_path_of``, never ``config_path``: the latter defaults to the Xray
        # JSON extension, so before M2 this looked for every transport's config at a
        # ``.json`` path. Latent only while the one live transport was an Xray one —
        # a WireGuard-family config is written ``.conf``, would never be found here,
        # and the node would be reported as permanently drifted. Carried over from M1
        # (docs/tracker/M1/carry-over.md) and fixed here because M2 is what makes it
        # bite.
        remote = await connection.read_file(
            config_path_of(config_name, (transports or {}).get(config_name, config_name))
        )
        if remote is None:
            # Absent config is reported as drift rather than as "missing service":
            # the container may still be running on a config that is no longer on
            # disk, which is the state that survives a restart as an outage.
            health.drifted.append(config_name)
        elif digest_of(remote) != wanted:
            health.drifted.append(config_name)

    health.drifted.sort()
    health.stale.sort()
    health.listening.sort()
    health.not_listening.sort()

    if not health.healthy:
        # Crash-looping first: it is the loudest fault and the one that explains the rest.
        # Nothing here names a port, an address or a host — this text becomes an API
        # message and a banner, and core invariants §4 keeps a node's own details out of
        # both. The transport's name is enough to find the row it is about.
        health.detail = "; ".join(
            part
            for part in (
                f"crash-looping: {', '.join(health.restarting)}" if health.restarting else "",
                f"not running: {', '.join(health.missing)}" if health.missing else "",
                f"nothing listening on the port for: {', '.join(health.not_listening)}"
                if health.not_listening
                else "",
                f"configuration drifted: {', '.join(health.drifted)}" if health.drifted else "",
                f"still running an older configuration: {', '.join(health.stale)}"
                if health.stale
                else "",
            )
            if part
        )
    return health
