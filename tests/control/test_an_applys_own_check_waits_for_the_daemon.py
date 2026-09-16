"""An apply's own check watches the daemon instead of glancing at it — M26, walk 2.

WHAT: that an apply refuses a node whose container is crash-looping however that crash
      loop happens to be sampled, that it does NOT refuse one whose container took a
      moment to come up, that it waits no longer than the ceiling it is given, that a
      container still down when the ceiling runs out is refused and can still be applied
      once it is up, and that none of these answers is a coin toss.

      What the apply does with the SOCKET half of the same wait is one file over
      (``test_an_apply_measures_serving_and_not_liveness.py``, M26's third walk); this
      one is the container half and keeps to it.
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

import asyncio
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

# A node's listening table, with only the session we arrived over on it.
#
# EVERY HOST IN THIS FILE HOLDS ITS PORT, and that is a rule rather than a convenience —
# M26's third walk taught an apply to refuse a container that is up and holds nothing, so
# a fake here that held nothing could be refused for its SOCKET while the file believed it
# was proving something about its CONTAINER. Reverting the life-token comparison would
# then leave every test in this file green. The socket question's own scenarios are in
# ``test_an_apply_measures_serving_and_not_liveness.py``; here the port is held so that
# the container is the only thing that can fail.
SSH_ONLY = """Netid State  Recv-Q Send-Q    Local Address:Port  Peer Address:PortProcess
tcp   LISTEN 0      4096            0.0.0.0:22         0.0.0.0:*
"""


def bound(port: int) -> str:
    """The same table with the transport's own socket on it — a host that is serving."""
    return SSH_ONLY + f"tcp   LISTEN 0      4096            0.0.0.0:{port}      0.0.0.0:*\n"


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

    def __init__(
        self,
        behaviour: str,
        *,
        sockets: str,
        comes_up_after: float = 0.0,
        keeps_its_clock: bool = False,
    ) -> None:
        self.files: dict[str, str] = {}
        self.behaviours: dict[str, _Behaviour] = {}
        self._kind = behaviour
        self._comes_up_after = comes_up_after
        # What ``ss`` prints here. A separate knob from the behaviour above, because the
        # two questions an apply now asks are separate questions about one host: a
        # container can stay up holding nothing, and a container that never starts holds
        # nothing either.
        # What ``ss`` prints here, and it has no default: see ``SSH_ONLY`` above. A test
        # that did not say what this host is holding would not know which of the two
        # questions its refusal came from.
        self.sockets = sockets
        # Whether a second ``docker compose up -d`` starts this container's clock again.
        # It does by default, which is what Compose does to a service whose definition
        # changed. A host that KEEPS its clock is one whose data plane is slow for a
        # reason that outlives one apply — an image being pulled, a kernel module being
        # loaded — and it is the only way to model a container that is still down when
        # the ceiling runs out and up by the time the operator presses again.
        self.keeps_its_clock = keeps_its_clock
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
                if self.keeps_its_clock and service in self.behaviours:
                    continue
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
            return CommandResult(exit_status=0, stdout=self.sockets, stderr="")

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
    host_for(
        monkeypatch,
        _FakeHost("silent-crash-loop", sockets=bound(reality_params["port"])),
    )
    node_id = await a_node_with_a_transport(client, reality_params)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code != 200, (
        "an apply reported success about a container that has never once stayed up"
    )
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert str(node.state) == "degraded", node.state
    assert TRANSPORT in (node.state_detail or ""), node.state_detail
    # THE FAULT AND NOT MERELY A FAULT. This host holds its port, so the only thing that
    # can refuse it is the container — and naming the clause is what stops this test from
    # passing on a product that has lost the life-token comparison and is refusing the
    # node for a socket instead.
    assert "did not come up" in (node.state_detail or ""), node.state_detail


async def test_what_the_walk_saw_the_row_say_is_not_what_it_says_now(
    client, session, reality_params, monkeypatch
) -> None:
    """The whole finding, end to end, on the two screens the walk read.

    The walk probed a host whose data plane could not start, got the correct finding,
    pressed apply — and read ``active / in sync`` with the sub-line gone and the Overview
    silent, for at least sixty-five seconds. The product may now say several things about
    this host; ``in sync`` and nothing else is not one of them.

    THE ONE HOST IN THIS FILE THAT HOLDS NOTHING, and it is the realistic pairing rather
    than an exception: a daemon that will not start binds no port either, which is what
    gives the probe in the middle of this something to find. It still cannot mask the
    life-token comparison, because the clause asserted below is the CONTAINER's — a
    settle check that believed this container would refuse the node for its socket and
    say so in different words.
    """
    host_for(monkeypatch, _FakeHost("silent-crash-loop", sockets=SSH_ONLY))
    node_id = await a_node_with_a_transport(client, reality_params)
    await client.post(f"/api/nodes/{node_id}/apply")

    await client.post(f"/panel/nodes/{node_id}/probe")
    await client.post(f"/api/nodes/{node_id}/apply")

    rows = await console.node_rows(session)
    row = next(row for row in rows if row.id == node_id)

    assert row.state != "active", (
        "the row reads active over a host whose container has never stayed up"
    )
    assert row.state_detail and "did not come up" in row.state_detail, (
        "the row does not say why the node is not serving, or says the wrong why: this "
        "host holds its port and its container is what never stayed up"
    )
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
    host_for(
        monkeypatch,
        _FakeHost("silent-crash-loop", sockets=bound(reality_params["port"])),
    )
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
    host_for(
        monkeypatch,
        _FakeHost("slow", sockets=bound(reality_params["port"]), comes_up_after=delay),
    )
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
    host = host_for(
        monkeypatch, _FakeHost("stays-up", sockets=bound(reality_params["port"]))
    )
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


async def test_a_node_starved_past_the_ceiling_is_refused_and_can_then_be_applied(
    client, session, reality_params, monkeypatch, settings
) -> None:
    """THE EDGE OF THE WINDOW, which M26's third walk tried to reach and could not.

    The walk starved the watcher on purpose — a container down for longer than the
    ceiling, then recovering — and ran out of budget before it could, so it filed that
    nobody knows what this window does at its edge. This is that host, built where the
    edge is known: ``comes_up_after`` is past ``node_settle_timeout``, so the container
    is still being restarted when the wait ends.

    Both halves matter and they pull opposite ways.

    * The apply REFUSES, because the ceiling running out is not evidence of anything. A
      settle loop that concluded "well, nothing was obviously wrong" at the edge would be
      the walk-2 defect rebuilt inside the fix for it.
    * And the refusal is NOT A VERDICT ON THE HOST. The same host, pressed again once its
      data plane is up, applies and goes active — so an operator whose node is slow for a
      reason that outlives one press (an image being pulled) is told to press again
      rather than being locked out of their own node.
    """
    starved = settings.node_settle_timeout * 1.5
    host = host_for(
        monkeypatch,
        _FakeHost(
            "slow",
            sockets=bound(reality_params["port"]),
            comes_up_after=starved,
            keeps_its_clock=True,
        ),
    )
    node_id = await a_node_with_a_transport(client, reality_params)

    began = time.monotonic()
    refused = await client.post(f"/api/nodes/{node_id}/apply")
    elapsed = time.monotonic() - began

    assert refused.status_code != 200, (
        "an apply reported success about a container still being restarted when its "
        "ceiling ran out — the wait ending is being read as an answer"
    )
    assert elapsed < starved, (
        f"the apply waited {elapsed:.2f}s for a container that comes up at "
        f"{starved:.2f}s, so the ceiling is not bounding the starved case"
    )
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert str(node.state) == "degraded", node.state
    # AND FOR THE RIGHT REASON. The clause matters here more than anywhere else in this
    # file: a settle loop that read the ceiling running out as "everything is fine" would
    # hand this container's empty digest to the staleness comparison instead, and the
    # apply would still fail — on a sentence about an older configuration, about a
    # container that has never started once.
    assert "did not come up" in (node.state_detail or ""), node.state_detail

    # The far side of the edge: the container is up now, and nothing about the refusal
    # above may stop the next press from succeeding.
    behaviour = next(iter(host.behaviours.values()))
    await asyncio.sleep(max(0.0, starved - (time.monotonic() - behaviour.started_at)))

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert str(node.state) == "active", node.state
    assert node.state_detail is None, node.state_detail


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
    host = _FakeHost("stays-up", sockets=SSH_ONLY)
    await host.write_file(
        node_stack.COMPOSE_PATH,
        yaml.safe_dump(
            {"services": {TRANSPORT: {"labels": {node_stack.CONFIG_DIGEST_LABEL: "d"}}}}
        ),
    )
    await host.run("cd /opt/hashi && docker compose up -d")

    settled = await serving.confirm_serving(
        host, expected=[TRANSPORT], listeners={}, interval=0.05, timeout=0.0
    )

    assert settled.staying_up == {}, (
        "a wait with no time in it confirmed a container was staying up"
    )
    assert TRANSPORT in settled.absent + settled.restarting
