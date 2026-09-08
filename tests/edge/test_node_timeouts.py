"""Nothing on the path to a node waits forever — M4.4.

WHAT: the two ceilings in ``bootstrap/ssh.py``: reaching a node, and one operation
      over a session that already opened.
WHY:  a censored node is not one that refuses packets, it is one that swallows them.
      Without a ceiling the control plane inherits the block: the panel request that
      was trying to replace the dead node is the one that hangs.
HOW:  against a local loopback socket that behaves the way a blackholed node does —
      it completes the TCP handshake and then says nothing — because that failure
      cannot be produced by pointing at an unroutable address without waiting out the
      kernel's own retry budget, which is the very cost this step removes.
"""

import asyncio
import socket
import time

import pytest

from edge.bootstrap import NodeConnection, NodeTarget, NodeUnreachable

# Loopback, port 0 so the kernel picks a free one. Not a node address and never
# written down anywhere: this is a socket in this process, standing in for a host
# that answers the handshake and then goes quiet.
LOOPBACK = "127.0.0.1"


@pytest.fixture
def silent_listener():
    """A socket that accepts connections at the kernel level and never speaks.

    ``listen()`` without ``accept()`` is deliberate: the kernel completes the
    three-way handshake from the backlog, so a client connects successfully and then
    waits forever for an SSH banner that no one will send.
    """
    listener = socket.socket()
    listener.bind((LOOPBACK, 0))
    listener.listen(1)
    try:
        yield listener.getsockname()
    finally:
        listener.close()


async def test_a_node_that_answers_and_then_says_nothing_is_bounded(
    silent_listener,
) -> None:
    host, port = silent_listener
    target = NodeTarget(
        host=host,
        port=port,
        username="node",
        connect_timeout=1,
        # Deliberately far larger, so a pass proves the CONNECT ceiling governs
        # getting a session rather than the command ceiling doing it by accident.
        timeout=60,
    )

    started = time.monotonic()
    with pytest.raises(NodeUnreachable) as caught:
        async with NodeConnection(target):
            pass
    elapsed = time.monotonic() - started

    assert "within 1s" in str(caught.value), (
        f"the reason must name how long we waited, got {caught.value!r}"
    )
    assert host not in str(caught.value), "the node's address must not travel with the reason"
    assert elapsed < 10, f"the connect ceiling was not honoured: {elapsed:.1f}s"


class _NeverOpens:
    """An SFTP client that hangs on open — a node that stopped reading mid-transfer."""

    async def __aenter__(self):
        await asyncio.Event().wait()

    async def __aexit__(self, *_exc_info) -> bool:
        return False


class _StalledSession:
    def start_sftp_client(self) -> _NeverOpens:
        return _NeverOpens()


async def test_placing_a_file_on_a_stalled_node_is_bounded() -> None:
    """The half a connect ceiling cannot cover: the session opened, then went quiet.

    Reaches into the connection's session attribute rather than standing up an SSH
    server, because the behaviour under test is what happens when the far side stops
    responding after authentication — and a real server that can be made to do that on
    demand is more machinery than the property is worth.
    """
    connection = NodeConnection(NodeTarget(host=LOOPBACK, port=22, username="node", timeout=1))
    connection._connection = _StalledSession()

    started = time.monotonic()
    with pytest.raises(NodeUnreachable) as caught:
        await connection.write_file("/etc/hashi/anything", "x")
    elapsed = time.monotonic() - started

    assert "stopped responding" in str(caught.value)
    assert "/etc/hashi/anything" not in str(caught.value), (
        "a node-side path must not travel into operator-facing text"
    )
    assert elapsed < 10, f"the file-transfer ceiling was not honoured: {elapsed:.1f}s"
