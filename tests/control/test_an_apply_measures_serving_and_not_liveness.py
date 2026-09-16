"""An apply measures serving, not liveness — M26, the third acceptance walk.

WHAT: that an apply refuses a node whose container is up and holds nothing, that it says
      so in the probe's own words, that it does not delete a true probe finding on the
      strength of a reading that never asked the same question, that it still applies a
      host whose socket table cannot be read at all — and that it clears a finding when,
      and only when, it took that reading and got a different answer.
WHY:  walk 2 left this hole on purpose and wrote the residual down as acceptable: *"apply
      does not re-ask the socket question… it widens apply's failure surface with a
      reading that has its own 'nobody could ask' third state."* Walk 3 falsified it in
      one press.

      The node's own generated compose command is ``sh -c 'set -e; … "$0" up "$1"; while
      :; do sleep 86400 & wait $!; done'``, so a data plane whose ``up`` returns 0 without
      establishing anything leaves the container up FOR EVER. The walk built that image.
      The apply reported success, the row read ``active / in sync``, the probe sub-line
      vanished and the Overview went silent — over a host with no tunnel device, nothing
      running but ``sleep 86400``, and 100% packet loss across its hop. A probe sixty
      seconds later caught it in under ten (*"nothing listening on the port for:
      amneziawg"*) and the next apply deleted that finding too. Deterministic, twice.

      The walker's own sentence is the brief for this file: **the apply discards a
      measurement of SERVING on the strength of a measurement of LIVENESS, and the port
      check that would have refused already exists, in the probe.** Given that supervisor
      shape, liveness is not a weak signal for serving — it is an unrelated one.
HOW:  against a fake host at the SHELL, like the two files either side of it — the real
      compose render, the real ``docker inspect`` parser, the real ``ss`` parser and the
      real settle loop all run, and the only invented thing is what the host answers.
      The socket table is a function of WALL-CLOCK TIME where the scenario is about
      timing, because a daemon binds its port some time after its container starts and a
      check that could not wait for that would be walk 2's false red rebuilt one layer
      down.

      Both directions, always. A file that only proved refusals would pass on a product
      that refuses every apply in the fleet, which is the same uselessness as one that
      refuses none.

      Boundary: nothing here says a friend's packets move. What a held port establishes
      is that something on the node binds it — not that our container did, and not that
      anyone can reach it (``edge.health.listening``). The walk carried real traffic; a
      test run never does.
"""

import time

import pytest
import yaml

from control.app.services import apply, console, health, nodes
from edge.bootstrap import node_stack
from edge.health import listening

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. Never dialled: the
# connection is replaced.
NODE_ADDRESS = "192.0.2.42"

TRANSPORT = "vless-reality"

# The host's listening table with nothing of ours on it — walk 3's leaf, whose data plane
# exits 0 having bound nothing and whose container therefore stays up for ever.
SSH_ONLY = """Netid State  Recv-Q Send-Q    Local Address:Port  Peer Address:PortProcess
tcp   LISTEN 0      4096            0.0.0.0:22         0.0.0.0:*
tcp   LISTEN 0      4096               [::]:22            [::]:*
"""


def bound(port: int) -> str:
    """The same table with the transport's own socket on it — a host that is serving."""
    return SSH_ONLY + f"tcp   LISTEN 0      4096            0.0.0.0:{port}      0.0.0.0:*\n"


class _FakeHost:
    """A node whose container always stays up, and whose sockets are the variable.

    The container half is deliberately perfect here: one life, running, never restarting,
    on exactly the digest it was created with. That is walk 3's host — the settle check
    from walk 2 passes it every time — so anything this file refuses, it refuses for the
    socket and for nothing else.

    ``binds_after`` is how long the daemon takes to bind, measured from the moment
    Compose created it. ``None`` means never, which is the walk's own image.
    ``no_ss`` is the third answer: a host whose socket table cannot be read at all.
    """

    learned_host_key = None

    def __init__(
        self, *, port: int, binds_after: float | None = None, no_ss: bool = False
    ) -> None:
        self.files: dict[str, str] = {}
        self.services: list[str] = []
        self.port = port
        self.binds_after = binds_after
        self.no_ss = no_ss
        self.started_at = time.monotonic()
        self.socket_readings = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    def sockets(self) -> str:
        if self.binds_after is None:
            return SSH_ONLY
        if time.monotonic() - self.started_at < self.binds_after:
            return SSH_ONLY
        return bound(self.port)

    async def run(self, command: str, *, check: bool = True):
        from edge.bootstrap.ssh import CommandResult

        if "docker compose up -d" in command:
            self.services = list(
                yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            )
            self.started_at = time.monotonic()
            return CommandResult(exit_status=0, stdout="", stderr="")

        if "docker inspect" in command:
            definitions = yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            lines = [
                f"{service}"
                f"|{definitions[service]['labels'][node_stack.CONFIG_DIGEST_LABEL]}"
                f"|true|false|one-life"
                for service in self.services
            ]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if command == listening.LISTENING_SOCKETS:
            self.socket_readings += 1
            if self.no_ss:
                # What a shell answers for a command that is not on the host.
                return CommandResult(exit_status=127, stdout="", stderr="ss: not found")
            return CommandResult(exit_status=0, stdout=self.sockets(), stderr="")

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


async def a_registered_node(client, reality_params, *, name: str = "r3leaf") -> str:
    """One node with one transport enabled, and nothing applied yet."""
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
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


# --- the refuse direction ------------------------------------------------------------


async def test_a_container_that_is_up_and_holds_nothing_is_not_reported_as_serving(
    client, session, reality_params, monkeypatch
) -> None:
    """Walk 3's host, through the button it pressed.

    Every container reading says running, not restarting, one life, right digest — so the
    settle check from walk 2 is satisfied and nothing about the CONTAINER is wrong. What
    is wrong is that nothing holds the port, which is the whole of what "serving" means
    to the person whose traffic does not move.

    Red against the previous commit for the reason the walk filed it: the apply reported
    success and the row read ``active / in sync``.
    """
    host_for(monkeypatch, _FakeHost(port=reality_params["port"]))
    node_id = await a_registered_node(client, reality_params)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code != 200, (
        "an apply reported success over a container that is up and holds no port — the "
        "operator reads that as 'this node is serving'"
    )
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert str(node.state) == "degraded", node.state
    assert TRANSPORT in (node.state_detail or ""), node.state_detail


async def test_the_refusal_is_in_the_probes_own_words(
    client, session, reality_params, monkeypatch
) -> None:
    """One fault about one host must not have two vocabularies.

    The probe has said *"nothing listening on the port for: …"* since M22, and the walk
    read that exact sentence sixty seconds after the apply that had called the same host
    healthy. The two surfaces now compose the same clause, so an operator who reads one
    and then the other is not left working out whether they are about the same thing.
    """
    host_for(monkeypatch, _FakeHost(port=reality_params["port"]))
    node_id = await a_registered_node(client, reality_params)

    applied = await client.post(f"/api/nodes/{node_id}/apply")
    probed = (await client.get(f"/api/nodes/{node_id}/health")).json()

    assert "nothing listening on the port for" in applied.text, applied.text
    assert "nothing listening on the port for" in (probed["detail"] or ""), probed


async def test_the_apply_does_not_delete_a_finding_it_did_not_contradict(
    client, session, reality_params, monkeypatch
) -> None:
    """The deletion the walk watched happen twice, and the rule that stops it.

    The probe found the truth about this host and the panel stored it. An apply that
    rebuilds the container and finds the port still holding nothing has not contradicted
    that finding — it has reproduced it — and the row must go on saying so.
    """
    host_for(monkeypatch, _FakeHost(port=reality_params["port"]))
    node_id = await a_registered_node(client, reality_params)
    await client.post(f"/api/nodes/{node_id}/apply")

    await client.get(f"/api/nodes/{node_id}/health")
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    found = node.last_probe_finding
    assert found, "the probe recorded nothing, so this test proves nothing"

    await client.post(f"/api/nodes/{node_id}/apply")

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.last_probe_finding == found, (
        "an apply deleted a true probe finding while measuring the same fault again"
    )
    rows = await console.node_rows(session)
    row = next(row for row in rows if row.id == node_id)
    assert row.probe, "the Nodes screen has dropped a finding nothing contradicted"
    assert console.fleet_doubt(rows), (
        "the Overview counts this node and says nothing at all about it"
    )


# --- the accept direction, without which the refusals above refuse every node ---------


async def test_a_host_that_holds_its_port_applies_and_clears_the_finding(
    client, session, reality_params, monkeypatch
) -> None:
    """The contradiction that is allowed to clear a finding: the same reading, answered
    the other way.

    Without this the checks above could pass on a product that refuses every apply in the
    fleet — which is the failure surface walk 2 was right to worry about, arrived at by a
    different route.
    """
    host_for(monkeypatch, _FakeHost(port=reality_params["port"], binds_after=0.0))
    node_id = await a_registered_node(client, reality_params)
    await client.post(f"/api/nodes/{node_id}/apply")
    await client.get(f"/api/nodes/{node_id}/health")

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert str(node.state) == "active", node.state
    assert node.last_probe_finding is None
    assert node.last_probe_at is None, (
        "a freshly applied node reads as probed, and an apply is not a probe"
    )


async def test_a_daemon_that_binds_a_moment_later_is_not_called_degraded(
    client, session, reality_params, monkeypatch, settings
) -> None:
    """The false-red direction of the new half, and it is the same defect as walk 2's.

    A daemon binds its socket some time after its container starts. A port question asked
    at the instant of the last container reading would call a healthy late binder dead,
    which is exactly the reading that left a leaf ``degraded`` while its friend's ping was
    0% loss — so the socket question is inside the settle loop and a late binder gets the
    patience a late starter gets.
    """
    host_for(
        monkeypatch,
        _FakeHost(
            port=reality_params["port"],
            binds_after=settings.node_settle_timeout / 3,
        ),
    )
    node_id = await a_registered_node(client, reality_params)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert str(node.state) == "active", node.state
    assert node.state_detail is None, node.state_detail


# --- and the third answer, which is neither ------------------------------------------


async def test_a_host_whose_sockets_cannot_be_read_still_applies(
    client, session, reality_params, monkeypatch
) -> None:
    """"Nobody could ask" is not "nothing is listening", and it is not a failed apply.

    This is the state walk 2 named as its reason for not asking at all. It is a reason to
    HANDLE the state: refusing a host for a missing tool would widen an apply's failure
    surface on the strength of a package, and a node nobody can probe is still a node the
    operator has to be able to push configuration to.
    """
    host_for(monkeypatch, _FakeHost(port=reality_params["port"], no_ss=True))
    node_id = await a_registered_node(client, reality_params)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert str(node.state) == "active", node.state


async def test_an_apply_that_could_not_ask_clears_nothing(
    client, session, reality_params, monkeypatch
) -> None:
    """The other half of the third answer, and the one that decides this milestone.

    A reading that could not be taken is not a confirmation. The apply succeeds, because
    the containers were watched and they stayed up — and the standing finding is left
    exactly where it was, because nothing re-asked the question it answers. Without this
    the third state is a hole of precisely the shape walk 3 found: an apply that clears a
    measurement it never took.
    """
    host = host_for(monkeypatch, _FakeHost(port=reality_params["port"], no_ss=True))
    node_id = await a_registered_node(client, reality_params)
    await client.post(f"/api/nodes/{node_id}/apply")

    # A probe that CAN read the table finds the fault and records it; the host then loses
    # the tool. Two different readings of one host, which is the situation this is about.
    host.no_ss = False
    await client.get(f"/api/nodes/{node_id}/health")
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    found = node.last_probe_finding
    assert found, "the probe recorded nothing, so this test proves nothing"
    host.no_ss = True

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.last_probe_finding == found, (
        "an apply that could not ask what holds the port deleted a finding about what "
        "holds the port"
    )
    assert node.last_probe_at is not None, (
        "the row reads as never probed over a finding it is still carrying"
    )
