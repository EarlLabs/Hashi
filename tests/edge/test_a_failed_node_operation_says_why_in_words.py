"""What the operator reads when a node operation fails — M18's acceptance.

WHAT: the two sentences this zone composes about a failure: why no SSH session could be
      opened, and what a command that exited non-zero said.
WHY:  both were leaking the layer below. A connect that failed to resolve the node's
      address arrived on the panel as ``could not establish an SSH session: gaierror`` —
      every word plain English except the one that carries the meaning, which is a Python
      class name. M9's acceptance filed exactly that and it was fixed in one place and
      not this one; M18's acceptance filed it again, beside the other half: a failed
      ``docker compose up`` that had to pull first was reported as the FIRST 300
      characters of its stderr, which is a screenful of image-layer ids, with the daemon's
      actual error — printed last, as every Unix tool prints it — cut off past the limit.
HOW:  the real arm every time. One connect is genuinely refused by the local kernel; the
      others raise the real exception classes through ``asyncssh.connect``; the command
      half drives ``NodeConnection.run`` against a session object that answers with a
      scripted result, which is the same shape ``test_node_timeouts.py`` uses for the
      failure it cannot ask a real host for.

No host and no network: the one socket here is this process talking to itself, and the
addresses below are loopback and a name reserved by RFC 2606 for exactly this.
"""

import errno
import socket
from types import SimpleNamespace

import asyncssh
import pytest

from edge.bootstrap import NodeConnection, NodeTarget, NodeUnreachable

LOOPBACK = "127.0.0.1"

# What an operator must never be shown, whatever went wrong: the name of a class. Each of
# these is a real leak this pair of sentences has produced, or the shape of one.
CLASS_NAMES = ("gaierror", "OSError", "PermissionDenied", "HostKeyNotVerifiable")


@pytest.fixture
def refused_port():
    """A bound, never-listening loopback port: every connect to it is one RST.

    Bound rather than closed so nothing else on the host can take it while the test
    runs, which is what makes the kernel's answer the same on every machine.
    """
    sock = socket.socket()
    sock.bind((LOOPBACK, 0))
    try:
        yield sock.getsockname()
    finally:
        sock.close()


async def test_a_refused_connection_is_a_sentence_and_not_a_class_name(
    refused_port,
) -> None:
    """The whole path, with the kernel producing the failure rather than a fake.

    ``ConnectionRefusedError`` is what the operator used to read, verbatim, at the end of
    an otherwise plain sentence. What they need instead is what it means about their
    node: something is wrong with the port, or nothing is listening on it.
    """
    host, port = refused_port
    target = NodeTarget(host=host, port=port, username="node", connect_timeout=5)

    with pytest.raises(NodeUnreachable) as caught:
        async with NodeConnection(target):
            pass

    said = str(caught.value)
    assert "nothing accepted an SSH connection on that port" in said, said
    for name in CLASS_NAMES:
        assert name not in said, f"the operator is reading a class name: {said}"
    assert host not in said, "the node's address travelled with the reason"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (socket.gaierror(-2, "Name or service not known"),
         "this node's address could not be resolved"),
        (asyncssh.PermissionDenied("Permission denied"),
         "the node refused the key this control plane holds for it"),
        (asyncssh.HostKeyNotVerifiable("Host key is not trusted"),
         "different host key"),
    ],
)
async def test_every_cause_an_operator_can_act_on_is_named_as_itself(
    monkeypatch, raised, expected
) -> None:
    """One sentence per cause with its own next action — a name, a key, a pinned host key.

    Injected at ``asyncssh.connect`` because that is where each of these really comes
    from and none of them can be produced on demand from a socket this process owns: a
    resolver failure needs a resolver, and the other two need a server that authenticates.
    Everything below the injection is the real path.
    """
    async def refusing(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(asyncssh, "connect", refusing)
    target = NodeTarget(host=LOOPBACK, port=22, username="node", connect_timeout=5)

    with pytest.raises(NodeUnreachable) as caught:
        async with NodeConnection(target):
            pass

    said = str(caught.value)
    assert expected in said, said
    for name in CLASS_NAMES:
        assert name not in said, f"the operator is reading a class name: {said}"


@pytest.mark.parametrize("code", [errno.EHOSTUNREACH, errno.ENETUNREACH])
async def test_a_node_nothing_can_route_to_is_named_as_itself(monkeypatch, code) -> None:
    """The cause Python gives no class to — M23, round 4, measured on a real record.

    A node registered with an address nothing routes to raises a bare ``OSError``: the
    errno carries the whole diagnosis and the type carries none of it, so the fallback
    below was the arm that answered and the operator read ``(OSError)`` on the banner, in
    the node row and in the probe. Both errnos, because the operator's next move is the
    same for each and this list carries one sentence per next move.

    Injected at ``asyncssh.connect`` for the reason the parametrised test above gives: a
    kernel that refuses a connection is reproducible on loopback, and one that has no
    route to it is not.
    """
    async def refusing(*_args, **_kwargs):
        raise OSError(code, "No route to host")

    monkeypatch.setattr(asyncssh, "connect", refusing)
    target = NodeTarget(host=LOOPBACK, port=22, username="node", connect_timeout=5)

    with pytest.raises(NodeUnreachable) as caught:
        async with NodeConnection(target):
            pass

    said = str(caught.value)
    assert "no route to this node's address" in said, said
    for name in CLASS_NAMES:
        assert name not in said, f"the operator is reading a class name: {said}"
    # Not the errno or the C library's text for it either: that text is written by the
    # layer that knows the address, and it is a place one can travel.
    assert str(code) not in said and "No route to host" not in said, said


async def test_an_unrecognised_failure_still_reads_as_a_sentence(monkeypatch) -> None:
    """The fallback, and the one place a class name is allowed to survive.

    An exception nothing here has a sentence for leaves the operator with only its type,
    so the type is kept — in brackets, at the end of a sentence, rather than as the
    sentence. The line between "we know what this means" and "we do not" has to be
    visible on the screen, because the second kind is the one that goes to the log.

    An errno rather than an exotic class, and deliberately one that is NOT on the
    no-route list: narrowing that list is what round 4 did, and this proves the narrowing
    did not swallow the arm it was carved out of. An errno nobody has met still reaches
    the operator as a readable sentence rather than as a guess.
    """
    async def refusing(*_args, **_kwargs):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(asyncssh, "connect", refusing)
    target = NodeTarget(host=LOOPBACK, port=22, username="node", connect_timeout=5)

    with pytest.raises(NodeUnreachable) as caught:
        async with NodeConnection(target):
            pass

    said = str(caught.value)
    assert said == "could not establish an SSH session (OSError)", said
    # Not the errno text either, which is where an address can travel.
    assert str(errno.EIO) not in said and "Input/output error" not in said, said


class _Answering:
    """A session that answers one command with a scripted exit status and stderr."""

    def __init__(self, stderr: str) -> None:
        self._stderr = stderr

    async def run(self, command: str, *, check: bool = False):
        return SimpleNamespace(exit_status=1, stdout="", stderr=self._stderr)


# The shape of a `docker compose up` that pulled before it failed: one progress line per
# layer, rewritten in place with carriage returns, and the daemon's own error last.
# Written here rather than captured from a host because what matters is the SHAPE — many
# lines of noise, the diagnosis at the end — which is every pulling tool's shape.
LAYERS = "".join(
    f" {index:012x} Pulling\r {index:012x} Downloading [====>    ]\r"
    f" {index:012x} Extracting\n"
    for index in range(40)
)
THE_REAL_ERROR = "Error response from daemon: pull access denied for hashi/nothing"


async def test_a_failed_command_is_reported_by_its_last_words_not_its_first() -> None:
    """The diagnosis survives the noise, and the noise does not reach the operator.

    Both halves matter and only one of them was the finding: a message that merely
    dropped the layer ids and lost the error with them would be worse than the wall.
    """
    connection = NodeConnection(NodeTarget(host=LOOPBACK, port=22, username="node"))
    connection._connection = _Answering(LAYERS + THE_REAL_ERROR + "\n")

    with pytest.raises(NodeUnreachable) as caught:
        await connection.run("docker compose up -d")

    said = str(caught.value)
    assert THE_REAL_ERROR in said, f"the daemon's own error did not survive: {said}"
    # The wall is gone. Asserted as "none of the layers before the last one is here"
    # rather than "no progress line is here": the tail is a fixed number of lines and the
    # last layer's own rewrites are in it, which is the price of a rule that knows
    # nothing about what it is reading. 39 ids absent is the wall, and it is the wall
    # that reached the operator.
    for index in range(39):
        assert f"{index:012x}" not in said, (
            f"the operator is reading a pull's progress display: {said}"
        )
    # One line, because this text becomes a node's ``state_detail`` and an API message,
    # and both are read as a sentence.
    assert "\n" not in said, said
    assert len(said) < 500, f"a reason this long is a report, not a reason: {len(said)}"


# The other shape a failed `docker compose up` arrives in, taken from the field: no pull,
# two lines, and the second one — the daemon's own error — longer on its own than the
# whole ceiling. Round 1 of M18's acceptance was given the layer wall; round 2 was given
# this, cut off on `daemon/i` with nothing to say it had been cut.
A_PROGRESS_LINE = "Container hashi-node-wireguard-1  Creating"
THE_DAEMONS_ERROR = (
    "Container hashi-node-wireguard-1  Error response from daemon: failed to mount "
    "/tmp/containerd-mount3552140296: mount source: \"overlay\", target: "
    "/var/lib/docker/overlay2/" + "d" * 64 + "/merged, data: \"workdir=/var/lib/docker/"
    "containerd/daemon/io.containerd.runtime.v2.task/moby/" + "e" * 64 + "/work\""
)


async def test_output_too_long_to_show_is_cut_where_the_reason_is_not() -> None:
    """The ceiling is spent on the diagnosis, and the cut says that it is one.

    Two failures in one answer, both filed: the progress line was served first and the
    daemon's error got what was left of the budget, and what the operator was handed ended
    mid-word as though the command had stopped talking there. A reason that is a fragment
    must not be readable as a reason that is a sentence — a person deciding whether to
    paste this somewhere has no other way to tell.

    Nothing here is about docker. What is asserted is that a LATER line outranks an
    earlier one for the room available, which is true of the same stderr whatever wrote it.
    """
    connection = NodeConnection(NodeTarget(host=LOOPBACK, port=22, username="node"))
    connection._connection = _Answering(f"{A_PROGRESS_LINE}\n{THE_DAEMONS_ERROR}\n")

    with pytest.raises(NodeUnreachable) as caught:
        await connection.run("docker compose up -d --remove-orphans")

    said = str(caught.value)
    # The diagnosis, from its start: a command writes what went wrong before the detail
    # it went wrong on, so the head of the line is the part worth the room.
    assert "Error response from daemon: failed to mount" in said, (
        f"the daemon's own error lost the budget to a progress line: {said}"
    )
    # And the progress line did not take it.
    assert "Creating" not in said, f"a progress line was shown instead: {said}"
    # Both cuts are marked: one where the dropped line was, one where the kept line ends.
    assert said.endswith("…"), f"the reason stops mid-word with nothing to say so: {said}"
    assert "… Container" in said, (
        f"a line was dropped from the front with nothing to say so: {said}"
    )
    assert "\n" not in said, said


async def test_output_that_fits_is_not_marked_as_cut() -> None:
    """The other side of the mark, without which it means nothing.

    A mark on every answer is a mark that says nothing about this one, and the operator
    who learns to ignore it is the operator the marked answer was for.
    """
    connection = NodeConnection(NodeTarget(host=LOOPBACK, port=22, username="node"))
    connection._connection = _Answering("services must be a mapping\n")

    with pytest.raises(NodeUnreachable) as caught:
        await connection.run("docker compose up -d")

    said = str(caught.value)
    assert said.endswith("services must be a mapping"), said
    assert "…" not in said, f"nothing was dropped and the answer says something was: {said}"
