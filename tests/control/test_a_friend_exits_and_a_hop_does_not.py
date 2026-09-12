"""Which tunnels a node is told to let out, and which it is not — M14.3.

WHAT: that the egress policy `control` hands a renderer comes from the ``purpose``
      column and nothing else, and that a hop end never gets a local exit.
WHY:  M14 was measured in the field: a friend's handshake completed and the friend
      carried nothing, because the node had no forwarding or NAT for the tunnel. Adding
      those rules fixes that transport and creates a new way to fail — quietly. The same
      rules on a hop end would masquerade entry↔leaf traffic out of the ENTRY, so a
      friend in Russia would exit in Russia while the panel showed two active nodes and a
      live hop. Nothing would log it and nothing should.

      So the two halves are asserted together, in one file: the exit that must exist and
      the exit that must not.
HOW:  real Postgres, real encryption, real rendering. No node is contacted — the claim
      is about the text that WOULD be pushed, which is the half provable without a host.

      Whether a packet then reaches the internet is a field observation on real hardware
      with a real client, and nothing here stands in for it.
"""

import ipaddress

import pytest

from control.app.models import NodeState, NodeTransport, TransportPurpose
from control.app.services import apply, nodes
from edge.bootstrap.node_stack import DATA_PLANES
from edge.egress import Egress
from edge.registry import discover, profile

# The transports whose data plane hands decrypted packets to the host's routing stack —
# derived from the declaration that its tool takes the interface name from the config
# file, which is what makes it a kernel interface rather than a userspace proxy. Derived
# rather than named so a third family member is covered by arriving.
KERNEL_TUNNELS = sorted(
    name
    for name, meta in discover().items()
    if DATA_PLANES[meta.config_format].interface_from_config_filename
)

WG_PARAMS: dict[str, object] = {
    "port": 51820,
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}

ENTRY_TUNNEL = "10.77.0.1/24"
LEAF_TUNNEL = "10.77.0.2/24"

# How many users a friend-facing row here may hand an address to — M17. Comfortably
# inside the /24 above and comfortably above any count this file reaches.
POOL_SIZE = 200


def params_for(transport_name: str, **overrides) -> dict[str, object]:
    """The operator-supplied half, minus knobs this transport does not declare.

    Filtered against the transport's own model rather than branched on its name, so this
    one literal serves every member of the family.
    """
    declared = set(profile(transport_name).params_model.model_fields)
    supplied = {**WG_PARAMS, **overrides}
    return {key: value for key, value in supplied.items() if key in declared}


@pytest.fixture(params=KERNEL_TUNNELS)
def kernel_tunnel(request) -> str:
    return request.param


async def friend_facing_node(client, session, transport_name: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
    )
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": transport_name,
            "params": params_for(
                transport_name,
                tunnel_address=ENTRY_TUNNEL,
                peer_tunnel_address=LEAF_TUNNEL,
            ),
            # Every user on such a transport holds an address of their own since M17, so
            # enabling one says how many it may hand out. Far above anything this file
            # creates, on purpose: nothing here is about the pool's edges, and a size
            # that only just fits would make an unrelated test fail the day somebody adds
            # a user to it. The /24 above leaves room for this and more.
            "pool_size": POOL_SIZE,
        },
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    return node_id


# --- the exit that must exist ------------------------------------------------

async def test_a_friend_facing_tunnel_is_told_to_let_its_traffic_out(
    client, session, kernel_tunnel: str
) -> None:
    """The rendered config carries the NAT rule whose absence was M14.

    Asserted on the pushed text rather than on the mapping, because the mapping being
    right and the argument never arriving at the renderer is exactly the shape of the
    original bug: everything correct, nothing connected.
    """
    node_id = await friend_facing_node(client, session, kernel_tunnel)
    node = await nodes.get_node(session, node_id)

    config = (await apply.render_for_node(session, node))[kernel_tunnel]

    network = ipaddress.ip_interface(ENTRY_TUNNEL).network
    assert "PostUp" in config
    assert "PostDown" in config
    assert f"-s {network} ! -o %i -j MASQUERADE" in config


# --- and the exit that must not ----------------------------------------------

async def test_the_entry_end_of_a_hop_is_never_told_to_let_traffic_out(
    client, session
) -> None:
    """The quiet failure, asserted on the stored end that could have it.

    Built through the same API an operator uses and then rendered as ``apply`` would, so
    what is asserted is the text that would reach a node.

    M14 wrote this as "neither end, ever", and M3 kept the half that is a safety property
    and inverted the other. The ENTRY masquerading is a friend in Russia exiting in Russia
    while the panel shows two active nodes and a live hop. The LEAF masquerading is the
    exit itself — the foreign address the friend is supposed to appear from — so a leaf
    end with no rule is a hop that carries nothing, which is why it is asserted here too
    rather than merely allowed.
    """
    for name, address, label in (
        ("entry-ru", "192.0.2.20", "Testland"),
        ("leaf-nl", "192.0.2.10", "Otherland"),
    ):
        response = await client.post(
            "/api/nodes",
            json={"name": name, "address": address, "location_label": label},
        )
        assert response.status_code == 201, response.text

    listed = (await client.get("/api/nodes")).json()
    ids = {node["name"]: node["id"] for node in listed}

    created = await client.post(
        "/api/hops",
        json={
            "entry_node_id": ids["entry-ru"],
            "leaf_node_id": ids["leaf-nl"],
            "transport_name": KERNEL_TUNNELS[0],
            "entry_params": params_for(
                KERNEL_TUNNELS[0],
                tunnel_address=ENTRY_TUNNEL,
                peer_tunnel_address=LEAF_TUNNEL,
            ),
            "leaf_params": params_for(
                KERNEL_TUNNELS[0],
                tunnel_address=LEAF_TUNNEL,
                peer_tunnel_address=ENTRY_TUNNEL,
            ),
        },
    )
    assert created.status_code == 201, created.text

    rendered = {}
    for node_id in (ids["entry-ru"], ids["leaf-nl"]):
        node = await nodes.get_node(session, node_id)
        rendered[node.name] = (await apply.render_for_node(session, node))[KERNEL_TUNNELS[0]]

    assert "MASQUERADE" not in rendered["entry-ru"]
    assert f"-s {ipaddress.ip_interface(LEAF_TUNNEL).network} ! -o %i -j MASQUERADE" in (
        rendered["leaf-nl"]
    )


# --- the policy itself -------------------------------------------------------

def test_every_purpose_has_a_decided_egress_policy() -> None:
    """A purpose nobody decided the exit for is a decision waiting to be made silently."""
    for purpose in TransportPurpose:
        assert nodes.egress_for(NodeTransport(purpose=purpose)) in tuple(Egress)


def test_only_a_friend_facing_row_exits_locally() -> None:
    """The table, stated as the property it exists for."""
    assert nodes.egress_for(NodeTransport(purpose=TransportPurpose.FRIENDS)) is Egress.LOCAL
    for purpose in TransportPurpose.relays():
        assert nodes.egress_for(NodeTransport(purpose=purpose)) is Egress.NONE


def test_a_purpose_nobody_taught_the_table_about_does_not_exit() -> None:
    """Fail closed — decision 3. No exit at all beats a quiet local one."""
    assert nodes.egress_for(NodeTransport(purpose="something-later")) is Egress.NONE
