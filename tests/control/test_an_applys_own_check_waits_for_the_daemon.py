"""An apply's own check watches the daemon instead of glancing at it — M26, walk 2.

WHAT: that an apply refuses a node whose container is crash-looping however that crash
      loop happens to be sampled, that it does NOT refuse one whose container took a
      moment to come up, that it waits no longer than the ceiling it is given, and that
      neither answer is a coin toss.
WHY:  the second acceptance walk pressed probe on a leaf whose data plane could not
      start and got the truth — *"r2leaf answered but is not serving — not running:
      amneziawg."* Then it pressed apply. Twenty seconds later, and still at sixty-five,
      the row read ``active / in sync``, the finding was gone, the Overview was silent
      and the friend's ping was 100% loss, with the container sitting in ``Restarting
      (1)`` on the host. Pressing apply a SECOND time on the same host produced the
      correct refusal — so the check existed and was sampling the container inside the
      first seconds of its first start, which is exactly the apply an operator makes
      after a change.

      It fired the other way too: one apply on a leaf whose container came up a moment
      later left the row ``degraded`` while that friend's ping was 0% loss. Both
      directions are the same defect, and both are here, because a fix for one of them
      is half a fix. An operator told their working node is broken is an operator who
      learns to ignore the warning.
HOW:  against a fake host at the SHELL — the real compose render, the real ``docker
      inspect`` parser and the real settle loop all run, and the only invented thing is
      what the host answers. **What the host answers is a function of WALL-CLOCK TIME**,
      which is the whole point: a double that returned a fixed answer would prove
      nothing about a check whose fault was that it looked too early. The windows come
      from ``settle_window`` and every assertion reads them off the settings object, so
      a value that stops being used shows up as a failure rather than as a test quietly
      proving nothing.

      Boundary: nothing here proves how long a real daemon takes to come up, and nothing
      here is evidence about a real node. What it holds is that this control plane does
      not conclude from one look.
"""

import itertools
import time

import pytest
import yaml

from control.app.services import apply, console, health, nodes, serving
from edge.bootstrap import node_stack
from edge.health import listening

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. Never dialled: the
# connection is replaced.
NODE_ADDRESS = "192.0.2.41"

TRANSPORT = "vless-reality"

# A node's listening table with nothing on the transport's port. The subject of this file
# is what the CONTAINER is doing, and an apply asks no port question at all — so the fake
# answers the one command the probe adds, and answers it the same way throughout.
SSH_ONLY = """Netid State  Recv-Q Send-Q    Local Address:Port  Peer Address:PortProcess
tcp   LISTEN 0      4096            0.0.0.0:22         0.0.0.0:*
"""


@pytest.fixture
def settle_window() -> tuple[float, float]:
    """Wide enough to model a container that takes a moment, short enough to run.

    Overrides the suite's default. The interval is what two readings have to be apart
    before the pair means anything, and the ceiling is the whole wait — so a container
    that never settles costs one ceiling and a healthy one costs one interval.
    """
    return (0.05, 1.5)


class _Behaviour:
    """What one service's container is doing, as a function of how long ago it started.

    Three of them, and each is a shape a real engine produces. They answer the two
    booleans and the life token that ``node_stack._INSPECT_FORMAT`` asks for; nothing
    here knows what the settle loop does with them.
    """

    def __init__(self, kind: str, *, comes_up_after: float = 0.0) -> None:
        self.kind = kind
        self.comes_up_after = comes_up_after
        self.started_at = time.monotonic()
        self._lives = itertools.count(1)
        self._life = f"life-{next(self._lives)}"

    def reading(self) -> tuple[str, str, str]:
        """``(running, restarting, life token)`` as the engine would print them now."""
        elapsed = time.monotonic() - self.started_at

        if self.kind == "stays-up":
            return "true", "false", self._life

        if self.kind == "silent-crash-loop":
            # THE WORST CASE, and the one the walk met. A container that dies and is
            # restarted between two of our readings is ``Running: true`` and
            # ``Restarting: false`` in both of them — the engine is only "restarting"
            # during the backoff itself. Every single reading of this host therefore
            # looks perfectly healthy, and the only thing that gives it away is that no
            # two readings are of the same life.
            self._life = f"life-{next(self._lives)}"
            return "true", "false", self._life

        if self.kind == "slow":
            # Down, then up and staying up. Before it comes up the engine is retrying it,
            # which is the state an apply used to read as "this node is degraded" about a
            # host that was seconds away from serving.
            if elapsed < self.comes_up_after:
                return "true", "true", ""
            return "true", "false", self._life

        raise AssertionError(f"no such behaviour: {self.kind}")  # pragma: no cover


class _FakeHost:
    """A node whose containers behave the way a real engine's do, over real time."""

    learned_host_key = None

    def __init__(self, behaviour: str, *, comes_up_after: float = 0.0) -> None:
        self.files: dict[str, str] = {}
        self.behaviours: dict[str, _Behaviour] = {}
        self._kind = behaviour
        self._comes_up_after = comes_up_after
        self.readings = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    async def run(self, command: str, *, check: bool = True):
        from edge.bootstrap.ssh import CommandResult

        if "docker compose up -d" in command:
            # Every service in the compose file gets a container, and its clock starts
            # here — the moment the apply restarted it, which is the moment the check
            # under test used to conclude from.
            for service in yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]:
                self.behaviours[service] = _Behaviour(
                    self._kind, comes_up_after=self._comes_up_after
                )
            return CommandResult(exit_status=0, stdout="", stderr="")

        if "docker inspect" in command:
            self.readings += 1
            definitions = yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            lines = []
            for service, behaviour in self.behaviours.items():
                running, restarting, life = behaviour.reading()
                digest = definitions[service]["labels"][node_stack.CONFIG_DIGEST_LABEL]
                lines.append(f"{service}|{digest}|{running}|{restarting}|{life}")
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if command == listening.LISTENING_SOCKETS:
            return CommandResult(exit_status=0, stdout=SSH_ONLY, stderr="")

        if "docker version" in command:
            return CommandResult(exit_status=0, stdout="27.1.1\n", stderr="")

        return CommandResult(exit_status=0, stdout="", stderr="")

    async def write_file(self, path: str, content: str, *, mode: int = 0o600) -> None:
        self.files[path] = content

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)


def host_for(monkeypatch: pytest.MonkeyPatch, fake: _FakeHost) -> _FakeHost:
    """One fake host, reached by the apply that pushes and the probe that measures."""
    for module in (apply, health):
        monkeypatch.setattr(module, "NodeConnection", lambda target: fake)
    return fake


async def a_node_with_a_transport(client, reality_params) -> str:
    """One registered node with one transport enabled, and nothing applied yet."""
    created = await client.post(
        "/api/nodes",
        json={
            "name": "r2leaf",
            "address": NODE_ADDRESS,
            "location_label": "Testland",
            "ssh_host": NODE_ADDRESS,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    return node_id


# --- the refuse direction -----------------------------------------------------------


async def test_a_container_that_never_stays_up_is_never_reported_as_serving(
    client, session, reality_params, monkeypatch
) -> None:
    """The walk's own host, modelled at its most flattering to the old check.

    Every reading of this container says running and not restarting — a crash loop only
    reports ``Restarting`` during its backoff, and a reading taken between two lives sees
    a healthy container. So this passes on any amount of looking that does not ask WHICH
    LIFE it looked at, and that is the assertion: the apply refuses, the node is degraded,
    and the transport is named.

    Red against the previous commit for the reason the walk found it: the check sampled
    once, saw ``running``, and reported a node in a crash loop as serving.
    """
    host_for(monkeypatch, _FakeHost("silent-crash-loop"))
    node_id = await a_node_with_a_transport(client, reality_params)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code != 200, (
        "an apply reported success about a container that has never once stayed up"
    )
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert str(node.state) == "degraded", node.state
    assert TRANSPORT in (node.state_detail or ""), node.state_detail


async def test_what_the_walk_saw_the_row_say_is_not_what_it_says_now(
    client, session, reality_params, monkeypatch
) -> None:
    """The whole finding, end to end, on the two screens the walk read.

    The walk probed a host whose data plane could not start, got the correct finding,
    pressed apply — and read ``active / in sync`` with the sub-line gone and the Overview
    silent, for at least sixty-five seconds. The product may now say several things about
    this host; ``in sync`` and nothing else is not one of them.
    """
    host_for(monkeypatch, _FakeHost("silent-crash-loop"))
    node_id = await a_node_with_a_transport(client, reality_params)
    await client.post(f"/api/nodes/{node_id}/apply")

    await client.post(f"/panel/nodes/{node_id}/probe")
    await client.post(f"/api/nodes/{node_id}/apply")

    rows = await console.node_rows(session)
    row = next(row for row in rows if row.id == node_id)

    assert row.state != "active", (
        "the row reads active over a host whose container has never stayed up"
    )
    assert row.state_detail, "the row says the node is not serving and does not say why"
    assert console.fleet_doubt(rows), (
        "the Overview counts this node and says nothing at all about it"
    )


async def test_the_wait_has_a_ceiling_and_it_is_the_one_in_settings(
    client, session, reality_params, monkeypatch, settings
) -> None:
    """A node that never settles costs the ceiling once, not the operator's afternoon.

    Both bounds, because only one of them is about the setting being READ: an apply that
    returned instantly would prove the check is not waiting, and one that ran for a
    minute would prove the ceiling is not a ceiling.
    """
    host_for(monkeypatch, _FakeHost("silent-crash-loop"))
    node_id = await a_node_with_a_transport(client, reality_params)

    began = time.monotonic()
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    elapsed = time.monotonic() - began

    assert applied.status_code != 200
    assert elapsed >= settings.node_settle_timeout / 2, (
        f"the apply gave up after {elapsed:.2f}s, well inside the "
        f"{settings.node_settle_timeout}s it is configured to watch for — the ceiling "
        "is not being read"
    )
    assert elapsed < settings.node_settle_timeout * 5, (
        f"the apply took {elapsed:.2f}s against a {settings.node_settle_timeout}s "
        "ceiling, so the ceiling is not bounding the wait"
    )


# --- the accept direction, without which the refusals above refuse every node --------


async def test_a_container_that_takes_a_moment_is_not_called_degraded(
    client, session, reality_params, monkeypatch, settings
) -> None:
    """The other direction of the same defect, and the one that teaches an operator to
    ignore the warning.

    The walk watched an apply leave a leaf reading ``degraded`` while that friend's ping
    was 0% loss, because the container came up a moment after the check looked. This host
    is being restarted by the engine when the apply first looks and is up and staying up
    well inside the ceiling.
    """
    delay = settings.node_settle_timeout / 3
    host_for(monkeypatch, _FakeHost("slow", comes_up_after=delay))
    node_id = await a_node_with_a_transport(client, reality_params)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert str(node.state) == "active", node.state
    assert node.state_detail is None, node.state_detail


async def test_a_node_that_comes_straight_up_costs_one_interval(
    client, session, reality_params, monkeypatch, settings
) -> None:
    """The ordinary apply, and the price it pays for the two above.

    One interval, because two readings are what makes a pair — not the ceiling, which is
    what a check that always waited it out would cost every operator on every press.
    """
    host = host_for(monkeypatch, _FakeHost("stays-up"))
    node_id = await a_node_with_a_transport(client, reality_params)

    began = time.monotonic()
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    elapsed = time.monotonic() - began

    assert applied.status_code == 200, applied.text
    assert host.readings >= 2, (
        f"the apply concluded from {host.readings} reading(s) of the host, which is the "
        "defect this file is about"
    )
    assert elapsed < settings.node_settle_timeout, (
        f"a node that came straight up cost {elapsed:.2f}s against a "
        f"{settings.node_settle_timeout}s ceiling — a healthy apply is waiting out the "
        "whole window"
    )


# --- the reading itself, asked directly ---------------------------------------------


async def test_a_ceiling_shorter_than_one_interval_confirms_nothing(
    monkeypatch, reality_params, client
) -> None:
    """The fail-safe direction, stated where it is decided.

    Nothing watched the node, so nothing may be said about whether it stayed up — and
    "nothing was said" has to mean the node is not confirmed rather than that it is fine.
    A settle loop that answered "all good" when it had no time to look would be this
    project's signature defect rebuilt inside its own fix.
    """
    host = _FakeHost("stays-up")
    await host.write_file(
        node_stack.COMPOSE_PATH,
        yaml.safe_dump(
            {"services": {TRANSPORT: {"labels": {node_stack.CONFIG_DIGEST_LABEL: "d"}}}}
        ),
    )
    await host.run("cd /opt/hashi && docker compose up -d")

    settled = await serving.confirm_serving(
        host, expected=[TRANSPORT], interval=0.05, timeout=0.0
    )

    assert settled.staying_up == {}, (
        "a wait with no time in it confirmed a container was staying up"
    )
    assert TRANSPORT in settled.absent + settled.restarting
