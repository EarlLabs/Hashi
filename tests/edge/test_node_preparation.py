"""What ``prepare`` asks of a host, and what it refuses — M13.

WHAT: the order of the commands ``edge.bootstrap.node_stack.prepare`` runs on a node,
      the refusal it raises on a host that was never prepared, and the absence of any
      privilege escalation in either.
WHY:  M13 is a permission error found on a real host: ``/opt`` is root-owned, the node
      was registered with a non-root ``ssh_user``, and the first thing an apply did was
      ``mkdir -p /opt/hashi/conf``. It failed with ``Permission denied``, which reads as
      a broken account and sends the operator to check the key, the user and docker —
      none of which were wrong. The privilege boundary now sits in
      ``scripts/node-bootstrap.sh``, which hands over a directory this account owns, and
      the job of this function is to say so when it did not.
HOW:  against a stub connection rather than a host. ``prepare`` talks to a node only
      through ``NodeConnection.run``, so a recorder that answers each command with a
      scripted ``CommandResult`` exercises every branch, in order, in microseconds —
      the same division as ``test_node_timeouts.py``'s stalled session.

      Stated plainly: nothing here proves a host becomes a node. That is an apply
      against real hardware. What it proves is that this function cannot ask a host for
      something the account it logs in as is not allowed to do, and cannot report the
      wrong reason when the host is not ready.
"""

import pytest

from edge.bootstrap.node_stack import (
    CONFIG_DIR,
    HOST_NOT_PREPARED,
    NODE_ROOT,
    NodeStackUnsupported,
    prepare,
)
from edge.bootstrap.ssh import CommandResult

# What a host that was prepared says to every question ``prepare`` asks it.
OK = CommandResult(exit_status=0, stdout="27.1.1\n", stderr="")


class _Recorder:
    """A node that answers each command with a scripted result, and remembers the order.

    ``failing`` is matched as a substring of the command, so a test names the step it
    wants to break — ``test -d`` — rather than an index into a list that shifts whenever
    a step is added.
    """

    def __init__(self, failing: str | None = None) -> None:
        self.commands: list[str] = []
        self._failing = failing

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)
        if self._failing and self._failing in command:
            failure = CommandResult(exit_status=1, stdout="", stderr="Permission denied")
            if check:
                raise AssertionError(
                    f"the failure of {command!r} was left to `check`, which raises "
                    "NodeUnreachable — the operator then gets the shell's reason instead "
                    "of one written for them"
                )
            return failure
        return OK


async def test_a_host_that_was_never_prepared_is_refused_by_name() -> None:
    """The refusal M13 exists for, and the sentence it must not be replaced by.

    ``Permission denied`` from a `mkdir` is a true statement about the wrong layer. The
    operator is told what is actually missing — the directory the bootstrap script
    creates — and how to create it on a host that predates that script.
    """
    node = _Recorder(failing="test -d")

    with pytest.raises(NodeStackUnsupported) as caught:
        await prepare(node)

    reason = str(caught.value)
    assert reason == HOST_NOT_PREPARED
    assert "scripts/node-bootstrap.sh" in reason, (
        "the reason does not name the script that prepares a host, so the operator is "
        "told what is wrong and not how to fix it"
    )
    assert "Permission denied" not in reason, (
        "the shell's own reason survived into operator-facing text — that is the message "
        "M13 was diagnosed through, and it points at the wrong layer"
    )


async def test_nothing_is_created_on_a_host_that_was_refused() -> None:
    """The check is the FIRST thing, so a refusal costs one command and changes nothing.

    Order is the property: a `mkdir` attempted before the check is the original defect,
    and it fails in a way nobody can read.
    """
    node = _Recorder(failing="test -d")

    with pytest.raises(NodeStackUnsupported):
        await prepare(node)

    assert len(node.commands) == 1, (
        f"the host was asked to do something after it was found unprepared: {node.commands}"
    )
    assert NODE_ROOT in node.commands[0] and "mkdir" not in node.commands[0]


async def test_a_prepared_host_gets_its_config_directory() -> None:
    """The happy path, in the order the node experiences it."""
    node = _Recorder()

    await prepare(node)

    assert node.commands[0] == f"test -d {NODE_ROOT} && test -w {NODE_ROOT}"
    assert any(f"mkdir -p {CONFIG_DIR}" in command for command in node.commands), (
        "the config directory is never created, so the first config lands nowhere"
    )
    assert any("chmod 700" in command for command in node.commands), (
        "the config directory is world-readable, and a rendered server config carries the "
        "node's private key"
    )


async def test_it_never_escalates_privilege_on_a_node() -> None:
    """The decision M13 took, asserted as the absence of the alternative.

    The other shape considered was for this library to `sudo` when the account is not
    root. It was rejected: privilege is host preparation, it belongs to the script that
    already runs privileged, and a library that escalates has a privilege model — which
    is a thing `edge` must not acquire, because every node then inherits it.
    """
    node = _Recorder()

    await prepare(node)

    for command in node.commands:
        for escalation in ("sudo", "su -", "doas", "pkexec"):
            assert escalation not in command, (
                f"prepare() escalates privilege on the node: {command!r}"
            )


async def test_a_host_without_docker_is_still_refused() -> None:
    """The boundary that was already here, unmoved by the one added beside it.

    hashi configures upstream data-plane containers and does not install a container
    runtime — so a host with no docker is refused, and refused for that reason rather
    than for the new one.
    """
    node = _Recorder(failing="docker version")

    with pytest.raises(NodeStackUnsupported) as caught:
        await prepare(node)

    assert "docker" in str(caught.value)
    assert str(caught.value) != HOST_NOT_PREPARED, (
        "a host with docker missing is reported as a host that was never prepared"
    )
