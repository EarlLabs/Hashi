"""Docker calls a crash loop running. We must not — M22, asked of a real engine.

WHAT: builds a real restart loop out of a real rendered service on a real engine, and
      asserts that the engine really does report it ``Running: true``, and that
      ``running_containers`` does not.
WHY:  this is the premise the whole milestone rests on, and it is a fact about somebody
      else's software. The offline suite models it — a fake answers ``Running: true``
      and ``Restarting: true`` together — and a model of the engine is exactly what
      cannot prove the engine behaves that way. If it ever stopped, every assertion
      built on it would still be green and the probe would be measuring nothing.

      It is also the field state, reproduced: on a real applied host a transport was
      exiting non-zero every second with nothing on its port, and the panel reported the
      node as serving it on six consecutive probes.
HOW:  the same technique as ``test_a_data_plane_container_reaches_up_and_stays_up``'s
      own check on itself — take a data plane whose command is a shell command line and
      replace the SCRIPT, keeping its image, its shell, its labels, its restart policy
      and its volumes. Nothing here names a protocol or a tool. The script is ``false``:
      it exits non-zero at once, which is what a daemon refusing its configuration does.

Boundary. This proves the CONTAINER half only. The port half of M22 — that something is
listening on the port a transport was given — cannot be asked here: this directory's
plumbing gives each container a network namespace of its own (``network_mode: none``)
rather than the node's, precisely so a test does not create interfaces on the machine it
runs on, so the host's socket table has nothing of the data plane's in it either way.
That parser is held against the real ``ss`` in
``tests/edge/test_a_transport_that_is_not_serving_is_not_reported_as_serving.py``.

And a sampling limit, stated rather than left to be discovered: a container in a restart
loop IS running for the instant between its restart and its next exit, and a probe that
lands in that instant answers "running" truthfully. What changes is the odds — Docker's
backoff doubles, so within a few seconds the loop is restarting for seconds at a time and
alive for milliseconds. Making it deterministic would mean comparing clocks across two
machines, which ``loaded_digests`` rejected for its own question and for the same reason.
"""

import asyncio
import copy
import time

import pytest

from edge.bootstrap import node_stack

# The flag that makes the next argument a script rather than a filename — the same
# constant, for the same reason, as the offline command check in
# ``tests/edge/test_every_data_plane_command_is_executable.py``.
INTERPRETED = "-c"

# A command that fails at once, which is what a daemon handed a configuration it cannot
# read does. ``false`` rather than ``true``: the field state was a non-zero exit, and a
# restart policy of ``unless-stopped`` loops on either.
REFUSES_TO_START = "false"

# How many restarts are waited for before the reading is taken. Docker's backoff doubles
# from 100ms, so by the fourth the container is dead for the best part of a second at a
# time — long enough that a `docker inspect` issued now lands inside the gap rather than
# inside the millisecond the process is alive for.
ENOUGH_RESTARTS = 4

# How long that is allowed to take before the scenario gives up and says the loop it
# needed was never built — a failure about the scenario, not about the product.
DEADLINE_SECONDS = 60


@pytest.fixture(scope="module")
def crash_looping(data_plane_stack, golden_server_config):
    """One node whose only transport cannot start, brought to a steady restart loop.

    Yields the stack and the service name. The waiting is here rather than in a test so
    that the two questions below are asked of one loop rather than of two.
    """
    from edge.registry import discover

    interpreted = [
        (name, golden_server_config(name))
        for name in sorted(discover())
        if INTERPRETED in node_stack.services_for({name: golden_server_config(name)})[0]["command"]
    ]
    assert interpreted, "no data plane runs a shell command line, so this shape cannot be built"

    name, config = interpreted[0]
    stack = data_plane_stack()
    stack.place({name: config})

    broken = copy.deepcopy(stack.services)
    script = broken[0]["command"].index(INTERPRETED) + 1
    broken[0]["command"] = [*broken[0]["command"][:script], REFUSES_TO_START]
    (stack.directory / "docker-compose.yml").write_text(node_stack.render_compose(transports=broken))
    stack.up()

    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        container = stack.container_id(name)
        if int(stack.inspect(container, "{{.RestartCount}}")) >= ENOUGH_RESTARTS:
            break
        time.sleep(0.5)
    else:
        pytest.fail(
            f"a service whose command is {REFUSES_TO_START!r} was not observed restarting "
            f"{ENOUGH_RESTARTS} times in {DEADLINE_SECONDS}s, so this scenario never built "
            f"the state it is about.\n{stack.logs(name)[-2000:]}"
        )

    return stack, name


def _while_restarting(stack, name, read):
    """Take one reading at a moment the engine says the container is restarting.

    The state alternates, so the reading has to be paired with an observation of it
    rather than taken whenever. Retried because the gap is large and the alive instant is
    small, not because the answer is uncertain: what is asserted on is what the product
    said at a moment the engine said "restarting".
    """
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        container = stack.container_id(name)
        state = stack.inspect(
            container, "{{.State.Status}}|{{.State.Running}}|{{.State.Restarting}}"
        )
        status, running, restarting = state.split("|")
        if restarting == "true":
            return status, running, read()
        time.sleep(0.2)
    pytest.fail(
        f"the container for {name!r} was never observed in the restarting state, so "
        f"nothing below was measured.\n{stack.logs(name)[-2000:]}"
    )


def test_the_engine_really_does_call_a_restarting_container_running(crash_looping) -> None:
    """The premise, from the engine itself.

    If this ever fails, the milestone's whole diagnosis is wrong and the fake in the
    offline suite is modelling something Docker no longer does.
    """
    stack, name = crash_looping
    status, running, _ = _while_restarting(stack, name, lambda: None)

    assert status == "restarting"
    assert running == "true", (
        "the engine no longer reports a restarting container as running, so the field "
        "state this milestone is built on cannot occur the way it was measured — check "
        "the diagnosis before trusting anything downstream of it"
    )


def test_a_container_in_that_state_is_not_reported_as_loaded(crash_looping) -> None:
    """And the product's own reading of the same moment, which is the whole fix."""
    stack, name = crash_looping
    _, _, containers = _while_restarting(
        stack, name, lambda: asyncio.run(node_stack.running_containers(stack.node()))
    )

    assert name not in containers.loaded, (
        f"a container that has never once started is reported as running {name!r}, so "
        f"the panel tells the operator the node is serving it — the M22 defect, against "
        f"a real engine.\n{stack.logs(name)[-2000:]}"
    )
    assert name in containers.restarting, (
        f"a crash-looping container is reported as absent rather than as crash-looping, "
        f"which sends the operator to apply the same configuration again"
    )
