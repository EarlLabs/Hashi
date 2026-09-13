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


async def test_an_unrecognised_failure_still_reads_as_a_sentence(monkeypatch) -> None:
    """The fallback, and the one place a class name is allowed to survive.

    An exception nothing here has a sentence for leaves the operator with only its type,
    so the type is kept — in brackets, at the end of a sentence, rather than as the
    sentence. The line between "we know what this means" and "we do not" has to be
    visible on the screen, because the second kind is the one that goes to the log.
    """
    async def refusing(*_args, **_kwargs):
        raise OSError(113, "No route to host")

    monkeypatch.setattr(asyncssh, "connect", refusing)
    target = NodeTarget(host=LOOPBACK, port=22, username="node", connect_timeout=5)

    with pytest.raises(NodeUnreachable) as caught:
        async with NodeConnection(target):
            pass

    said = str(caught.value)
    assert said == "could not establish an SSH session (OSError)", said
    # Not the errno text either, which is where an address can travel.
    assert "113" not in said and "No route to host" not in said, said


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
