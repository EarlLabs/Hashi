"""A container that is up is not a transport that is serving — M22.

WHAT: that a crash-looping container is reported as crash-looping rather than as
      running, that a running container whose port nothing holds is reported as such,
      that a port nobody could ask about is reported as neither, and that the accept
      case — a node that really is serving — still says so.
WHY:  measured in acceptance on 2026-09-13. On a real applied host a proxy was exiting
      23 every second on a missing certificate file, with nothing listening on its port,
      and the panel answered *"realhost is serving amneziawg, vless-ws-tls"* on six
      consecutive probes. Fully stopping the same container gave the right answer, so
      the probe measured that a container EXISTS: Docker reports ``Running: true`` for
      the whole of a restart backoff.

      It is M14's shape — every signal green, nothing carried — on the one instrument
      the operator has for "is this node actually working". A probe that reports a
      broken node as working and a probe that reports a working node as broken are the
      same defect, so every refusal below has its accept case beside it.
HOW:  against a fake node, because what has to be modelled is one rule of the ENGINE and
      one output format, and both are stated here rather than assumed: a restarting
      container answers ``Running: true`` and ``Restarting: true`` at once (measured on
      engine 29.4.0, 2026-09-14), and ``ss`` prints a header line and interface-suffixed
      and bracketed addresses. The crash loop against a REAL engine is
      ``tests/e2e/edge/test_a_crash_looping_container_is_not_reported_as_running.py``,
      which is where the first of those two claims is actually proven.

      Boundary: nothing here proves a node's socket table is reachable over SSH, and
      nothing anywhere proves a client can connect. The probe does not claim it either —
      that is the whole of M22.2.
"""

import socket
import subprocess

import pytest

from edge.bootstrap import node_stack
from edge.bootstrap.ssh import CommandResult
from edge.health import listening
from edge.health.listening import Listener, is_answering, parse_sockets
from edge.health.probe import probe
from edge.registry import Layer4

# A real transport name, so the config path resolves through the real registry. The
# config TEXT is arbitrary: a digest is a digest of whatever bytes were rendered.
TRANSPORT = "vless-reality"
A_CONFIG = '{"inbounds": []}'

# The port this node's transport was given. A number of no significance: what the port
# IS belongs to a node record, and borrowing a shipped transport's default would make
# these pass for a reason that has nothing to do with the probe.
A_PORT = 45123

# A node's listening table as ``ss -l -n -t -u`` really prints it — header, an
# interface-suffixed address, an IPv6 one. Copied from a live reading rather than
# idealised: every line here is a shape the parser has to survive, and a fixture that
# dropped the header would leave the parser free to mis-handle the first line of every
# real answer.
#
# It always carries a listening sshd, because a node this code is talking to has one.
SSH_ONLY = """Netid State  Recv-Q Send-Q    Local Address:Port  Peer Address:PortProcess
tcp   LISTEN 0      4096            0.0.0.0:22         0.0.0.0:*
tcp   LISTEN 0      4096      127.0.0.53%lo:53         0.0.0.0:*
tcp   LISTEN 0      4096               [::]:22            [::]:*
"""

TCP_BOUND = SSH_ONLY + f"tcp   LISTEN 0      4096            0.0.0.0:{A_PORT}      0.0.0.0:*\n"
UDP_BOUND = SSH_ONLY + f"udp   UNCONN 0      0                  [::]:{A_PORT}         [::]:*\n"

# What `control` passes in for this node: the port the operator chose and the protocols
# the transport declared it binds. Never derived from a transport's name here either.
ON_TCP = {TRANSPORT: Listener(port=A_PORT, protocols=frozenset({Layer4.TCP}))}


class _FakeNode:
    """A node that answers the two questions a probe asks about what is up.

    ``restarting`` is modelled the way the engine really answers, and that is the whole
    reason this class exists rather than a simpler one: a container in a restart backoff
    is ``Running: true`` AND ``Restarting: true`` at the same instant. A fake that
    answered ``Running: false`` for it would be a fake in which the defect this file is
    about cannot occur, and every assertion here would be decoration.

    ``sockets`` is the raw ``ss`` output, so the product's own parser runs. ``ss_fails``
    is a host without the tool — the third answer, which is neither "listening" nor
    "not listening".
    """

    learned_host_key = None

    def __init__(
        self,
        containers: dict[str, str],
        *,
        files: dict[str, str] | None = None,
        restarting: tuple[str, ...] = (),
        sockets: str = SSH_ONLY,
        ss_fails: bool = False,
        started: dict[str, str] | None = None,
    ) -> None:
        self.containers = containers
        self.files = files or {}
        self.restarting = restarting
        self.sockets = sockets
        self.ss_fails = ss_fails
        self.started = started or {}
        self.commands: list[str] = []

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)

        if "docker inspect" in command:
            lines = [
                f"{service}|{digest}|true"
                f"|{'true' if service in self.restarting else 'false'}"
                # The fifth field: which LIFE of this container the reading looked at
                # (``node_stack._INSPECT_FORMAT``). A fake host's containers never
                # restart, so one token per service for the whole run is what that
                # models — and it has to be there, or every reading of this fake would
                # be one no caller may compare with the next.
                f"|{self.started.get(service, '2026-01-01T00:00:00.000000000Z')}"
                for service, digest in self.containers.items()
            ]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if command == listening.LISTENING_SOCKETS:
            if self.ss_fails:
                # What a shell answers for a command it cannot find.
                return CommandResult(exit_status=127, stdout="", stderr="ss: not found")
            return CommandResult(exit_status=0, stdout=self.sockets, stderr="")

        return CommandResult(exit_status=0, stdout="", stderr="")

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)


def _serving_node(**kwargs) -> _FakeNode:
    """A node doing everything right: the container we pushed, the file we pushed."""
    return _FakeNode(
        containers={TRANSPORT: node_stack.digest_of(A_CONFIG)},
        files={node_stack.config_path_for(TRANSPORT): A_CONFIG},
        **kwargs,
    )


# --- the crash loop ----------------------------------------------------------------


async def test_a_crash_looping_transport_is_not_reported_as_running() -> None:
    """The acceptance finding, as an assertion.

    The container exists, carries the digest of the config we pushed, and the engine
    calls it running. It has never served a byte.
    """
    node = _serving_node(restarting=(TRANSPORT,), sockets=TCP_BOUND)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    assert health.running == [], (
        "a container the engine is restarting after it died is reported as running, so "
        "the panel says the node is serving a transport that has never once started — "
        "this is the M22 defect"
    )
    assert health.restarting == [TRANSPORT]
    assert health.healthy is False


async def test_a_crash_loop_is_not_reported_as_a_transport_that_was_never_pushed() -> None:
    """Crash-looping and missing are different faults with different repairs.

    "Not running" sends the operator to apply the node again, and applying the same
    configuration that will not start changes nothing. The word has to be the specific
    one or the repair is the wrong one.
    """
    node = _serving_node(restarting=(TRANSPORT,))

    health = await probe(node, expected={TRANSPORT: A_CONFIG})

    assert health.missing == [], (
        "a crash-looping transport is also reported as not running, which reads as "
        "'never pushed' and sends the operator to apply it again"
    )
    assert health.restarting == [TRANSPORT]
    assert "crash-looping" in health.detail


async def test_a_node_whose_containers_are_all_up_is_still_healthy() -> None:
    """The accept case for the crash-loop check, without which it could refuse everything."""
    node = _serving_node(sockets=TCP_BOUND)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    assert health.restarting == []
    assert health.running == [TRANSPORT]
    assert health.healthy is True, health.detail


# --- the port ----------------------------------------------------------------------


async def test_a_running_transport_with_nothing_on_its_port_is_not_serving() -> None:
    """The other half of the field state: up, and holding no socket at all.

    A daemon that starts, fails to bind and idles is up for ever. Nothing about the
    container says so, which is why this question is asked of the node's socket table
    rather than of Docker.
    """
    node = _serving_node(sockets=SSH_ONLY)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    assert health.not_listening == [TRANSPORT]
    assert health.listening == []
    assert health.healthy is False
    assert "nothing listening on the port" in health.detail


async def test_a_transport_holding_its_port_is_reported_as_listening() -> None:
    """The accept case, and the one that decides whether the check is worth having."""
    node = _serving_node(sockets=TCP_BOUND)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    assert health.listening == [TRANSPORT]
    assert health.not_listening == []
    assert health.unchecked_ports == []
    assert health.healthy is True, health.detail


async def test_the_wrong_protocol_on_the_right_port_is_not_listening() -> None:
    """A port number is not a port — the same rule ``services.placement`` is written on.

    Something else on the node holding the same NUMBER over the other protocol must not
    read as this transport answering; two sockets on one number are two sockets.
    """
    node = _serving_node(sockets=UDP_BOUND)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    assert health.not_listening == [TRANSPORT], (
        "a UDP socket on the same number was accepted as a TCP transport listening"
    )


async def test_a_transport_binding_both_protocols_must_hold_both() -> None:
    """All of them, never any: holding one of two declared protocols is being half up."""
    both = {TRANSPORT: Listener(port=A_PORT, protocols=frozenset({Layer4.TCP, Layer4.UDP}))}
    node = _serving_node(sockets=TCP_BOUND)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=both)

    assert health.not_listening == [TRANSPORT]

    on_both = _serving_node(
        sockets=TCP_BOUND + UDP_BOUND.replace(SSH_ONLY, "")
    )
    assert (await probe(on_both, expected={TRANSPORT: A_CONFIG}, listeners=both)).listening == [
        TRANSPORT
    ]


# --- and what it must NOT claim ----------------------------------------------------


async def test_a_port_nobody_could_ask_about_is_not_reported_as_silent() -> None:
    """A host without the tool is not a fleet-wide outage.

    "Nothing is listening" and "nobody could ask" are different facts. Collapsing them
    would be this milestone's own defect pointed the other way: a confident answer
    nobody measured.
    """
    node = _serving_node(ss_fails=True)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    assert health.not_listening == []
    assert health.listening == []
    assert health.unchecked_ports == [TRANSPORT]
    assert health.healthy is True, (
        "a node whose socket table could not be read is reported as broken, which is a "
        "true-looking answer to a question nobody managed to ask"
    )


async def test_a_socket_table_we_did_not_understand_is_not_read_as_an_empty_one() -> None:
    """We arrived over a listening socket on this node, so a reading with none is wrong.

    The guard exists for the day ``ss`` changes its output: without it, an unparseable
    answer would report every transport in the fleet as holding nothing, confidently.
    """
    node = _serving_node(sockets="a shape this parser has never seen\n")

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    assert health.unchecked_ports == [TRANSPORT]
    assert health.not_listening == []


async def test_a_transport_with_no_port_to_check_is_not_reported_either_way() -> None:
    """A caller that names no port for one config gets no port answer about THAT one.

    Two configs, because one is not a test of this: a caller that names no port at all
    asks no port question, and the case that matters is the one where the question was
    asked and this config was not part of it — a transport that declares no port, or one
    whose row this control plane could not resolve.
    """
    other = "vless-ws-tls"
    node = _FakeNode(
        containers={
            TRANSPORT: node_stack.digest_of(A_CONFIG),
            other: node_stack.digest_of(A_CONFIG),
        },
        files={
            node_stack.config_path_for(TRANSPORT): A_CONFIG,
            node_stack.config_path_for(other): A_CONFIG,
        },
        sockets=TCP_BOUND,
    )

    health = await probe(
        node, expected={TRANSPORT: A_CONFIG, other: A_CONFIG}, listeners=ON_TCP
    )

    assert health.listening == [TRANSPORT]
    assert health.unchecked_ports == [other], (
        "a config nobody named a port for is reported as an answer rather than as "
        "unchecked, which is a confident statement about something nobody measured"
    )
    assert health.not_listening == []


async def test_a_caller_that_names_no_port_at_all_asks_no_port_question() -> None:
    """An empty mapping is "nothing to ask", not "ask about nothing"."""
    node = _serving_node(sockets=TCP_BOUND)

    health = await probe(node, expected={TRANSPORT: A_CONFIG}, listeners={})

    assert listening.LISTENING_SOCKETS not in node.commands
    assert health.unchecked_ports == [TRANSPORT]
    assert health.listening == []
    assert health.not_listening == []


async def test_a_probe_that_was_asked_no_port_question_runs_no_port_command() -> None:
    """The pre-M22 caller's behaviour, unchanged and costing nothing extra."""
    node = _serving_node()

    await probe(node, expected={TRANSPORT: A_CONFIG})

    assert listening.LISTENING_SOCKETS not in node.commands


# --- the rules that do not bend ----------------------------------------------------


def test_the_container_command_asks_whether_a_container_is_restarting() -> None:
    """The question has to be in the command, or the answer cannot be in the reading.

    Everything else in this file models a node that answers four fields. What decides
    whether a real node answers four is this format string, and dropping the fourth is
    invisible to every fake — the engine's own answer to it is proven in
    ``tests/e2e/edge/test_a_crash_looping_container_is_not_reported_as_running.py``.
    """
    assert ".State.Restarting" in node_stack._INSPECT_FORMAT, (
        "the container reading no longer asks whether a container is restarting, so "
        "every crash loop is back to reporting itself as running"
    )


def test_the_container_command_asks_which_life_of_the_container_it_read() -> None:
    """M26's second acceptance walk, at the same seam as the fourth field above.

    Every other field here is an INSTANT, and the walk proved an instant is not enough:
    a container sampled in the first second of its first start reads exactly like one
    that will keep running, and the panel reported a crash loop as serving. What makes a
    second reading mean anything is being able to tell whether it looked at the same life
    of the container, and that is this field. Drop it and every settle loop above
    ``running_containers`` silently concludes on one sample again.
    """
    assert ".State.StartedAt" in node_stack._INSPECT_FORMAT, (
        "the container reading no longer says which life of a container it looked at, "
        "so two readings of a crash loop cannot be told from one container staying up"
    )


async def test_a_container_that_restarted_between_two_readings_says_so() -> None:
    """Two readings, and the fact that is only visible across both of them.

    The accept case is in the same test rather than beside it, because the claim is a
    comparison: a token that never changes would pass an "it changed" assertion never,
    and a token that changed every reading would pass it always. Both directions here.
    """
    node = _FakeNode(
        containers={TRANSPORT: node_stack.digest_of(A_CONFIG)},
        started={TRANSPORT: "2026-09-16T12:57:03.111111111Z"},
    )

    first = await node_stack.running_containers(node)
    same_life = await node_stack.running_containers(node)

    assert first.started[TRANSPORT] == same_life.started[TRANSPORT], (
        "a container nobody restarted reads as a different life on the second look"
    )

    node.started[TRANSPORT] = "2026-09-16T12:57:09.222222222Z"
    after_a_restart = await node_stack.running_containers(node)

    assert first.started[TRANSPORT] != after_a_restart.started[TRANSPORT], (
        "a container that restarted between two readings reads as one that never did"
    )


def test_the_socket_command_asks_only_for_listening_sockets() -> None:
    """The charter's no-logging rule, held at the one command that could break it.

    ``-l`` is what makes a peer's address impossible in the output rather than merely
    unused, and ``-p`` would name processes this probe has no business reading. A future
    edit that drops the first would put every established connection's remote address on
    the wire into this process.
    """
    flags = listening.LISTENING_SOCKETS.split()

    assert "-l" in flags, (
        "the socket command no longer restricts itself to LISTENING sockets, so its "
        "output now carries the address of every connected peer"
    )
    assert "-p" not in flags
    assert "-a" not in flags


def test_the_socket_command_asks_for_ports_as_numbers() -> None:
    """``-n``, and it is an operational rule rather than a stylistic one.

    Without it ``ss`` resolves a port through ``/etc/services`` and prints the NAME:
    ``0.0.0.0:https`` for 443, ``127.0.0.1:http-alt`` for 8080. ``parse_sockets`` reads
    the last colon-separated field as a number, so such a line fails ``isdigit`` and is
    skipped — silently, and in the one direction that hurts: the socket is held, the
    parser does not see it, and the probe reports a working transport as holding nothing.

    443 is the most operationally likely port this product ever checks — it is the point
    of Reality — and it is named in ``/etc/services`` on every host. Pinned HERE because
    ``test_the_real_tool_answers_in_the_shape_this_parser_reads`` cannot catch it: it
    binds EPHEMERAL ports, and those have no service name to resolve to.
    """
    flags = listening.LISTENING_SOCKETS.split()

    assert "-n" in flags, (
        "the socket command no longer asks for numeric ports, so a listener on a port "
        "named in /etc/services is invisible to this parser and reports as unbound"
    )


async def test_neither_probe_command_names_a_transport() -> None:
    """Core invariants §1, on the two commands most tempted to break it.

    Asking a daemon whether a peer has handshaked would have been the obvious answer to
    "is it serving", and it is protocol-specific: a different command and a different
    answer per transport. Both commands here are the same for every family alike.
    """
    from edge.registry import discover

    node = _serving_node(sockets=TCP_BOUND)
    await probe(node, expected={TRANSPORT: A_CONFIG}, listeners=ON_TCP)

    for name in discover():
        for command in node.commands:
            assert name not in command, (
                f"a probe command names the transport {name!r}: {command!r}"
            )


@pytest.mark.parametrize(
    "line,expected",
    [
        ("tcp   LISTEN 0 4096 0.0.0.0:8443 0.0.0.0:*", {Layer4.TCP: frozenset({8443})}),
        ("udp   UNCONN 0 0 [::]:51820 [::]:*", {Layer4.UDP: frozenset({51820})}),
        ("udp   UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:*", {Layer4.UDP: frozenset({53})}),
        ("Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port", {}),
        # An address family ``Layer4`` has no name for. ``ss`` prints these when asked
        # for them, and a parser that filed one under a protocol it does know would
        # report a port as bound over something that never bound it.
        ("raw   UNCONN 0 0 0.0.0.0:1 0.0.0.0:*", {}),
        ("nonsense", {}),
        ("", {}),
    ],
)
def test_one_socket_line_at_a_time(line: str, expected: dict) -> None:
    """Every shape a real ``ss`` line comes in, including the ones to skip."""
    assert parse_sockets(line) == expected


def test_nothing_read_from_a_socket_line_is_an_address() -> None:
    """Only the port is taken, and that is a rule rather than an economy.

    Which address a daemon bound is the node's business; the port is the one value the
    control plane gave it. A parser that kept the address would put a node's own
    addresses into a health answer, which core invariants §4 keeps out of one.
    """
    bound = parse_sockets(SSH_ONLY + TCP_BOUND.replace(SSH_ONLY, ""))

    assert bound == {Layer4.TCP: frozenset({22, 53, A_PORT})}


def test_a_listener_with_no_declared_protocol_is_never_answering() -> None:
    """A transport that declares it binds nothing cannot be found holding anything.

    Answering "yes" to an empty set is what ``all()`` does, and it would report every
    such transport as listening without a single socket being looked at.
    """
    assert (
        is_answering(
            {Layer4.TCP: frozenset({A_PORT})}, Listener(port=A_PORT, protocols=frozenset())
        )
        is False
    )


# --- against the real tool ---------------------------------------------------------


def test_the_real_tool_answers_in_the_shape_this_parser_reads() -> None:
    """``ss``'s own output, from ``ss`` itself, holding sockets this test opened.

    Everything above models what the tool prints. This is the one that fails when the
    model is wrong — and it is the assumption most likely to rot, because the output of
    a command-line tool is not an interface anybody promised us.

    BOTH protocols, because they are printed differently and the difference is a trap:
    a TCP listener is state ``LISTEN`` and a UDP one is ``UNCONN``, so a parser written
    against the word LISTEN would find every wg-family transport in the fleet silent
    while nothing was wrong.

    Skipped loudly where the tool is absent — a node has it, a developer's macOS laptop
    does not, and the edge rulebook's rule for an upstream binary is to say so rather
    than to pass quietly.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as over_tcp, socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM
    ) as over_udp:
        over_tcp.bind(("127.0.0.1", 0))
        over_tcp.listen(1)
        over_udp.bind(("127.0.0.1", 0))
        tcp_port = over_tcp.getsockname()[1]
        udp_port = over_udp.getsockname()[1]

        # Through a shell, so the string under test is the exact one a node is sent.
        answer = subprocess.run(
            ["/bin/sh", "-c", listening.LISTENING_SOCKETS],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if answer.returncode != 0:
            pytest.skip(
                "ss (iproute2) is not usable on this host, so the real socket table "
                f"could not be read: {answer.stderr.strip()[:200]!r}"
            )
        bound = parse_sockets(answer.stdout)

    assert tcp_port in bound.get(Layer4.TCP, frozenset()), (
        "a socket this test is holding open on TCP was not found in the real tool's "
        "output, so the parser does not understand what a node actually answers"
    )
    assert udp_port in bound.get(Layer4.UDP, frozenset()), (
        "a UDP socket this test is holding open was not found — a UDP listener is "
        "printed in state UNCONN rather than LISTEN, and every wg-family transport in "
        "the fleet would be reported as holding nothing"
    )
