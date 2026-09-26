"""Which hosts serve delivery, and why nobody is asked — M27.4.

WHAT: ``delivery.is_delivery_host`` — both halves of the predicate, what it costs the
      host it says no to, and the apply that acts on it.
WHY:  the three roles are placed on one, two or three machines in any combination, and
      where they are CO-LOCATED the feature must be absent rather than inert: no second
      name, no second certificate, no second listener, and no setting an operator has to
      know to leave off. A setting is the failure this whole step is written against —
      an operator who has never read M27 must not be able to arrive at the wrong shape
      by following the panel — so the arrangement is derived from what is already true.
HOW:  the two halves are tested where each of them lives. The row half is a unit test
      over rows, because it is exactly the branchy logic the control rulebook keeps unit
      tests for; the host half goes through an apply against the shared
      ``accepting_nodes`` harness with the host's answer replaced, because the question
      is asked on a connection and the answer decides what the apply does next.

Nothing here proves a listener runs anywhere: nothing wires one up yet — a site block
needs an address and a port, and both are M27.6's. What it proves is which hosts would
get one, and that the one that must not is answered no for a reason no operator can
mistype.
"""

import pathlib

import pytest

from control.app.models import NodeTransport, TransportPurpose
from control.app.services import delivery
from control.app.services import transports as transports_service
from edge.bootstrap import delivery as node_delivery
from edge.bootstrap import node_stack
from edge.bootstrap.ssh import CommandResult, NodeUnreachable
from edge.registry import discover, profile

from .conftest import GENERATED_SSH_KEY, pinned

# RFC 5737, as everywhere in this zone. Never dialled — the connection is replaced.
NODE_ADDRESS = "192.0.2.91"

# Any transport this image offers a user. The declaration, never a name.
USER_TRANSPORTS = sorted(transports_service.offerable_transports())

USER_PARAMS: dict[str, object] = {
    "port": 8443,
    "decoy_host": "www.example.com",
    "decoy_port": 443,
    "server_names": ["www.example.com"],
    "server_name": "front.example.com",
    "certificate_path": "/etc/hashi/certs/fullchain.pem",
    "certificate_key_path": "/etc/hashi/certs/privkey.pem",
    "tunnel_address": "10.92.0.1/24",
    "peer_tunnel_address": "10.92.0.2/24",
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}

pytestmark = pytest.mark.skipif(
    not USER_TRANSPORTS, reason="this image offers no transport a user can be given"
)


@pytest.fixture(params=USER_TRANSPORTS)
def user_transport(request) -> str:
    return request.param


class _Host:
    """A node that answers the one question this predicate asks it.

    Not the shared harness's connection: this file is about what the answer decides, so
    it has to be able to give both answers — and to record whether it was asked at all,
    which is what the row half of the predicate is proven by.
    """

    def __init__(self, *projects: str) -> None:
        self.commands: list[str] = []
        self._projects = projects

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)
        return CommandResult(
            exit_status=0, stdout="".join(f"{one}\n" for one in self._projects), stderr=""
        )


def a_row(purpose: TransportPurpose) -> NodeTransport:
    """One enabled row, of the purpose under test and of no transport in particular."""
    return NodeTransport(
        node_id="a-node", transport_name="whatever", config_name="whatever", purpose=purpose
    )


# --- the predicate ---------------------------------------------------------------------


async def test_a_host_that_carries_users_and_nothing_of_ours_serves_delivery() -> None:
    """The arrangement this milestone was asked for: the entry is its own machine."""
    assert await delivery.is_delivery_host(
        _Host("hashi-node"), enabled=[a_row(TransportPurpose.USERS)]
    )


async def test_the_box_this_control_plane_is_deployed_on_serves_no_delivery() -> None:
    """Co-location, and the whole of what "absent rather than inert" rests on.

    ``/sub/{token}`` is already answered from this box by the control plane itself, so a
    second answer for the same document would be a second name, a second certificate and
    a second listener on one machine — which is what an operator following the panel must
    not be able to end up with.
    """
    assert not await delivery.is_delivery_host(
        _Host(delivery.CONTROL_STACK_PROJECT, "hashi-node"),
        enabled=[a_row(TransportPurpose.USERS)],
    )


@pytest.mark.parametrize(
    "purpose", [TransportPurpose.RELAY_ENTRY, TransportPurpose.RELAY_LEAF]
)
async def test_a_host_nobody_fetches_from_is_not_asked_about_at_all(purpose) -> None:
    """A node carrying only the far end of a hop has no user to answer and no material.

    And the host is not even dialled for it: the row half is a fact this control plane
    already holds, so a leaf in every arrangement is settled without a command.
    """
    host = _Host("hashi-node")

    assert not await delivery.is_delivery_host(host, enabled=[a_row(purpose)])
    assert host.commands == [], host.commands


async def test_a_host_that_cannot_be_asked_is_not_assumed_to_be_a_stranger() -> None:
    """The failure direction. A host whose engine cannot answer is not a host known to
    be free of this control plane — and treating it as one is how a second listener
    lands on the box that already answers."""

    class _Mute(_Host):
        async def run(self, command: str, *, check: bool = True) -> CommandResult:
            raise NodeUnreachable(f"command failed: {command!r}")

    with pytest.raises(NodeUnreachable):
        await delivery.is_delivery_host(_Mute(), enabled=[a_row(TransportPurpose.USERS)])


def test_the_project_name_is_the_one_this_product_deploys_under() -> None:
    """Held against ``deploy/docker-compose.yml`` rather than remembered.

    The predicate recognises this control plane's own box by the compose project on it,
    so a value copied across a zone boundary that nothing compares is a value that
    drifts — and the drift would be silent in the safe-looking direction: every
    co-located box would start being told it is a stranger.
    """
    compose = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"
    declared = [
        line.split(":", 1)[1].strip()
        for line in compose.read_text().splitlines()
        if line.startswith("name:")
    ]

    assert declared == [delivery.CONTROL_STACK_PROJECT], (
        f"deploy/docker-compose.yml deploys as {declared}, and the predicate looks for "
        f"{delivery.CONTROL_STACK_PROJECT!r}"
    )


# --- and what an apply does with it ------------------------------------------------------


def params_for(transport_name: str) -> dict[str, object]:
    declared = set(profile(transport_name).params_model.model_fields)
    return {key: value for key, value in USER_PARAMS.items() if key in declared}


async def a_node_carrying_a_user(client, transport_name: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={
            "name": "the-entry",
            "address": NODE_ADDRESS,
            "location_label": "Testland",
            "ssh_host": NODE_ADDRESS,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    user = await client.post("/api/users", json={"nickname": "boris"})
    assert user.status_code == 201, user.text
    asked = {"transport_name": transport_name, "params": params_for(transport_name)}
    # A pool only where the transport declares that each user gets an address of their
    # own — the declaration, never the transport's name. The others refuse the key
    # rather than ignoring it. Sized past the one user below rather than to it, so this
    # file is never about a pool that ran out.
    if profile(transport_name).meta.peer_address is not None:
        asked["pool_size"] = 8
    enabled = await client.post(f"/api/nodes/{node_id}/transports", json=asked)
    assert enabled.status_code == 201, enabled.text
    return node_id


class Watched:
    """Which of the two calls an apply made, and what it handed over."""

    def __init__(self) -> None:
        self.artifacts: list = []
        self.pushes = 0
        self.removals = 0


@pytest.fixture
def watched(accepting_nodes, monkeypatch) -> Watched:
    """Both delivery calls, layered over the shared harness rather than replacing it."""
    seen = Watched()
    placing = node_delivery.place_delivery
    removing = node_delivery.remove_delivery

    async def place_delivery(connection, *, artifacts) -> None:
        seen.artifacts = list(artifacts)
        seen.pushes += 1
        await placing(connection, artifacts=artifacts)

    async def remove_delivery(connection) -> bool:
        seen.removals += 1
        return await removing(connection)

    pinned(monkeypatch, node_delivery, "place_delivery", place_delivery)
    pinned(monkeypatch, node_delivery, "remove_delivery", remove_delivery)
    return seen


@pytest.fixture
def co_located(watched, monkeypatch) -> Watched:
    """The same accepting node, on the box this control plane is deployed on."""

    async def compose_projects(connection) -> frozenset[str]:
        return frozenset({delivery.CONTROL_STACK_PROJECT, "hashi-node"})

    pinned(monkeypatch, node_stack, "compose_projects", compose_projects)
    return watched


async def test_an_apply_to_a_co_located_host_leaves_no_delivery_material_on_it(
    client, co_located: Watched, user_transport: str
) -> None:
    """Absent, not inert: no directory, not an emptied one.

    The apply itself is unaffected — the node is configured, restarted and taken into
    service exactly as before — and the one difference is that the box which already
    answers ``/sub/{token}`` is not handed a second plaintext copy of every subscription
    it serves, beside the database those are rendered from.
    """
    node_id = await a_node_carrying_a_user(client, user_transport)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    assert (co_located.pushes, co_located.removals) == (0, 1), (
        "the box this control plane is deployed on was handed delivery material, or was "
        "left holding whatever it had"
    )
    node = await client.get(f"/api/nodes/{node_id}")
    assert node.json()["state"] == "active", node.text


async def test_the_same_apply_on_a_host_of_its_own_is_handed_the_material(
    client, watched: Watched, user_transport: str
) -> None:
    """The other half of the same arrangement, so the test above is not vacuous.

    Nothing about the node's record differs between the two — same address, same
    transport, same user. What differs is the box, which is the only thing that can
    differ: an arrangement is not a field on a row.
    """
    node_id = await a_node_carrying_a_user(client, user_transport)

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    assert (watched.pushes, watched.removals) == (1, 0), (
        "a host of its own was not handed the material its own users would fetch"
    )
    assert watched.artifacts, "the push carried nothing for a host with a user on it"


def test_discovery_offers_the_transports_this_file_exercises() -> None:
    """The red half of the parametrisation: a file that silently exercises nothing."""
    assert set(USER_TRANSPORTS) <= set(discover())
