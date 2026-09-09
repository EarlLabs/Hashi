"""Does the data plane actually RUN? — M5.2, asked of a real engine.

WHAT: brings up a node's whole data plane — every installed transport, from its real
      rendered config, through the real rendered compose file — and asserts each
      container is running, was not merely created, and is still the same container a
      few seconds later having restarted nothing.
WHY:  "it was created" is the answer M2 had. Both WireGuard-family containers existed,
      were listed by ``docker compose ps``, and had never executed a byte: ``Created``,
      exit 127. And "it is running" on its own is the answer the supervisor exists to
      make true — ``wg-quick up`` configures and RETURNS, so a container whose whole
      command is that exits 0 immediately and ``restart: unless-stopped`` turns into a
      restart loop that is ``Up`` about half the time you look at it.

      So the question is deliberately three questions, and the third — the same
      container, still up, having restarted zero times — is the one no static check can
      answer and the one a node's operator actually cares about.
HOW:  the configs are the golden files: real output of the real renderer, so a daemon
      that refuses one is a real refusal and not a fixture's fault. The compose file is
      ``render_compose``'s, unedited, with the two host-isolation deviations described
      in this directory's ``conftest.py``.

Boundary: needs a docker engine, ``/dev/net/tun`` and the pinned images. Because the
containers get their own network namespace rather than the node's, this proves the
daemon starts and stays up on our config — NOT that it is reachable from outside, that
its port is free on a node, or that a handshake completes. The tunnel is M5.4's
question, and whether it survives a Russian network is a field observation.

One more thing it is given rather than proving: a transport whose config names a file the
control plane places by another route — a certificate — is handed a throwaway one at that
path (see ``files_the_config_names`` in ``conftest.py``). So the answer here is "the
daemon starts GIVEN that file", never that anything puts it there.
"""

import copy
import time

import pytest

from edge.bootstrap import node_stack
from edge.registry import discover

INSTALLED = sorted(discover())

# How long a container is watched before it is believed. A supervisor that exits when
# its tool returns does so at once, and ``restart: unless-stopped`` turns that over in
# well under this; a daemon that dies on its config dies in the first second or two.
SETTLE_SECONDS = 8

# The flag that makes the next argument a script rather than a filename — the same
# constant, for the same reason, as the offline command check in
# ``tests/edge/test_every_data_plane_command_is_executable.py``.
INTERPRETED = "-c"


@pytest.fixture(scope="module")
def golden_configs(golden_server_config) -> dict[str, str]:
    """Every installed transport's real rendered server config."""
    return {name: golden_server_config(name) for name in INSTALLED}


@pytest.fixture(scope="module")
def node(data_plane_stack, golden_configs):
    """A node running every installed transport at once, brought up once for this module.

    Every transport rather than one per data plane: a node runs the transports it was
    given, and the cost of asking all of them is one ``up -d`` rather than four.
    """
    stack = data_plane_stack()
    stack.place(golden_configs)
    stack.up()

    started = {name: stack.container_id(name) for name in golden_configs}
    time.sleep(SETTLE_SECONDS)
    return stack, started


@pytest.mark.parametrize("transport_name", INSTALLED)
def test_the_container_is_running_and_not_merely_created(transport_name: str, node) -> None:
    """M2's state, as an assertion: ``Created`` with an exit code is not a data plane."""
    stack, started = node
    status = stack.inspect(started[transport_name], "{{.State.Status}}|{{.State.ExitCode}}")
    state, _, exit_code = status.partition("|")

    assert state == "running", (
        f"the container for {transport_name!r} is {state!r} (exit {exit_code}), so this "
        f"node is serving nothing on that transport while every offline check is "
        f"green.\n{stack.logs(transport_name)[-2000:]}"
    )


@pytest.mark.parametrize("transport_name", INSTALLED)
def test_it_is_still_the_same_container_and_has_restarted_nothing(
    transport_name: str, node
) -> None:
    """Up, and STAYING up — the half a single glance at ``docker ps`` cannot see.

    A restart loop is up for most of any given second. What distinguishes it is that the
    container is a different one, or the same one on its second life: both are read here
    rather than inferred from a second glance at its state.
    """
    stack, started = node
    current = stack.container_id(transport_name)
    restarts = stack.inspect(started[transport_name], "{{.RestartCount}}")

    assert current == started[transport_name], (
        f"the container serving {transport_name!r} is not the one that came up "
        f"{SETTLE_SECONDS}s ago — it died and was replaced, which on a node is a "
        f"transport that is up whenever nobody is watching.\n"
        f"{stack.logs(transport_name)[-2000:]}"
    )
    assert restarts == "0", (
        f"the container for {transport_name!r} has restarted {restarts} times in "
        f"{SETTLE_SECONDS}s: its command returns instead of holding the container open, "
        f"which is what `restart: unless-stopped` turns into a loop.\n"
        f"{stack.logs(transport_name)[-2000:]}"
    )


def test_a_command_that_returns_is_seen_as_a_restart_loop(
    data_plane_stack, golden_configs
) -> None:
    """The check on the check, and it is M2's second half reproduced deliberately.

    Without it, "running with zero restarts" could be true of a scenario that cannot see
    a restart loop at all — a settle time too short, a field read wrongly — and every
    assertion above would be decoration.

    The broken command is built by replacing the SCRIPT of a data plane that runs an
    interpreter, keeping its image and its shell, so nothing here names a protocol or a
    tool. That is exactly the shape ``wg-quick up`` alone has: it does its work, returns
    0, and the container is restarted for ever.
    """
    interpreted = [
        (name, config)
        for name, config in sorted(golden_configs.items())
        if INTERPRETED in node_stack.services_for({name: config})[0]["command"]
    ]
    assert interpreted, "no data plane runs a shell command line, so this shape cannot be built"

    name, config = interpreted[0]
    stack = data_plane_stack()
    stack.place({name: config})

    broken = copy.deepcopy(stack.services)
    script = broken[0]["command"].index(INTERPRETED) + 1
    # ``true`` and nothing else: succeed, and return. Everything else about the service —
    # image, shell, labels, volumes, restart policy — is the rendered one.
    broken[0]["command"] = [*broken[0]["command"][:script], "true"]
    (stack.directory / "docker-compose.yml").write_text(
        node_stack.render_compose(transports=broken)
    )
    stack.up()
    time.sleep(SETTLE_SECONDS)

    restarts = stack.inspect(stack.container_id(name), "{{.RestartCount}}")

    assert int(restarts) > 0, (
        "a command that returns immediately was not observed restarting, so this "
        "scenario cannot tell a data plane that holds the container open from one that "
        "does not — and the assertions above prove nothing"
    )
