"""What ``compose_projects`` asks a host, and what it makes of the answer — M27.4.

WHAT: the command ``edge.bootstrap.node_stack.compose_projects`` runs on a node, and the
      set it returns for what a host prints back.
WHY:  M27.4 decides which hosts serve delivery, and the one arrangement it must get
      right is the host that is already the control plane's own. That cannot be read off
      a node record: the runbook has an operator register a co-located box with its
      public IP while the control plane's public host is a DNS name, so the two true
      spellings of one machine are two different strings. The host itself is the only
      source that cannot be spelled two ways, and this is the question put to it.
HOW:  against a stub connection, as ``test_node_preparation`` does — this function
      touches a node only through ``run``, so a recorder that answers with scripted
      output exercises the parsing in microseconds.

      Stated plainly: nothing here proves what a real engine prints. What it proves is
      that this function asks for the machine-readable form, counts a stopped stack, and
      never turns a host's silence into an answer it did not give.
"""

import pytest

from edge.bootstrap.node_stack import compose_projects
from edge.bootstrap.ssh import CommandResult, NodeUnreachable


class _Recorder:
    """A node that answers the one command with scripted output."""

    def __init__(self, stdout: str = "", *, exit_status: int = 0) -> None:
        self.commands: list[str] = []
        self._result = CommandResult(exit_status=exit_status, stdout=stdout, stderr="")

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)
        if check and not self._result.ok:
            raise NodeUnreachable(f"command failed: {command!r}")
        return self._result


async def test_a_host_is_asked_for_names_and_not_for_a_table() -> None:
    """``--quiet`` and ``--all``, both of them load-bearing.

    The table Compose prints for a person and the JSON it prints for a program have both
    changed shape between versions; a name per line has not. ``--all`` is the other half:
    a stack whose containers are stopped is still installed on the box, and a caller
    deciding whether to put a second one beside it has to count it.
    """
    node = _Recorder()

    await compose_projects(node)

    assert node.commands == ["docker compose ls --all --quiet"], node.commands


async def test_every_project_the_host_names_comes_back() -> None:
    node = _Recorder("hashi\nhashi-node\n")

    assert await compose_projects(node) == {"hashi", "hashi-node"}


async def test_a_host_with_nothing_deployed_answers_with_nothing() -> None:
    """An empty answer is an answer: this host holds no compose project at all."""
    assert await compose_projects(_Recorder("\n\n")) == frozenset()


async def test_a_host_that_cannot_answer_is_not_read_as_an_empty_one() -> None:
    """The failure direction that matters. A host whose engine cannot answer is a host
    nothing is known about — and an empty set reads as "nothing else is here", which is
    the answer that puts a second stack on a box that already has one."""
    with pytest.raises(NodeUnreachable):
        await compose_projects(_Recorder("", exit_status=127))
