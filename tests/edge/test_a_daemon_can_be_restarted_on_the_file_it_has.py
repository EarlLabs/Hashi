"""A service can be restarted on the definition it already has — M31.3.

WHAT: the command ``node_stack.restart_services`` sends a node: ``docker compose restart``
      for exactly the services it is given, quoted, in the node stack's own directory —
      and nothing at all when it is given nothing.
WHY:  the field walk of 2026-10-02 removed a wg-family daemon's peer live on a leaf. The
      file on disk was unchanged, so its digest and its compose definition were too, and
      ``docker compose up -d`` — the only verb this package had — left the container
      exactly as it was: still serving none of its peers, apply after apply.
      ``docker compose restart <service>`` repaired it. This is that verb; whether an
      apply should use it, and when, is the control plane's decision and is tested there.
HOW:  against a recording connection; nothing reaches a host. Whether the engine then
      restarts the container is Docker's documented behaviour and was observed on the
      field walk, not here.
"""

from edge.bootstrap import node_stack
from edge.bootstrap.ssh import CommandResult


class _Recording:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)
        return CommandResult(exit_status=0, stdout="", stderr="")


async def test_it_restarts_exactly_the_services_named() -> None:
    connection = _Recording()
    await node_stack.restart_services(connection, ["wg-leaf", "amneziawg"])
    assert connection.commands == [
        f"cd {node_stack.NODE_ROOT} && docker compose restart amneziawg wg-leaf"
    ], "not a restart of the named services alone — an `up -d` would leave them be"


async def test_told_nothing_it_does_nothing() -> None:
    """A bare ``docker compose restart`` restarts EVERY service on the node — every user
    on every transport loses their session — so an empty list must send no command."""
    connection = _Recording()
    await node_stack.restart_services(connection, [])
    assert connection.commands == []


async def test_a_name_reaches_the_shell_quoted() -> None:
    connection = _Recording()
    await node_stack.restart_services(connection, ["a b;reboot"])
    assert connection.commands[0].endswith("docker compose restart 'a b;reboot'")
