"""What the control plane pushes to an entry node that has a hop — M3.

WHAT: that a friend-facing transport on a node with a hop is rendered to leave through
      that hop, and that a node without one is rendered exactly as it always was.
WHY:  this is the charter's core claim and the failure it hides is invisible. Before M3
      the entry's config had one hardcoded outbound and the node dialled the internet
      itself: the friend connects, pages load, the panel shows two active nodes and a
      live hop, and the exit is in Russia. Nothing logs it, and nothing may.

      The edge zone proves a renderer given the policy obeys it. This file proves the
      other half, which is where M14's own bug lived: that the policy and the address
      actually REACH the renderer from the database. A correct mapping whose argument
      never arrives is exactly the shape of that failure — everything right, nothing
      connected.
HOW:  real Postgres, real encryption, real rendering, through the same API an operator
      uses. No node is contacted: the claim is about the text that WOULD be pushed.

      Whether a friend's traffic then emerges at the leaf's address is a field
      observation on two real hosts with a real client. Nothing here stands in for it —
      and decision 3 says so explicitly, because the success and the failure differ only
      in where packets come out.
"""

import json

import pytest

from control.app.models import NodeState
from control.app.services import apply, nodes, relay
from edge.egress import Egress

HOP_TRANSPORT = "amneziawg"
FRIEND_TRANSPORT = "vless-reality"

ENTRY_TUNNEL = "10.44.0.1/24"
ENTRY_EXIT_ADDRESS = "10.44.0.1"
LEAF_TUNNEL = "10.44.0.2/24"


@pytest.fixture
def hop_params() -> dict[str, object]:
    """The operator-supplied half of one hop end. Key material is minted, never typed."""
    return {
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


async def entry_node_serving_friends(client, session, reality_params) -> str:
    """A Russian entry node with a friend-facing transport and no hop yet."""
    created = await client.post(
        "/api/nodes",
        json={"name": "entry-ru", "address": "192.0.2.20", "location_label": "Russia"},
    )
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": FRIEND_TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    return node_id


async def hop_to_a_leaf(client, hop_params, entry_id: str) -> str:
    """A foreign leaf, and the hop the entry dials it over."""
    created = await client.post(
        "/api/nodes",
        json={"name": "leaf-nl", "address": "192.0.2.10", "location_label": "Netherlands"},
    )
    leaf_id = created.json()["id"]
    established = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": {
                **hop_params,
                "tunnel_address": ENTRY_TUNNEL,
                "peer_tunnel_address": LEAF_TUNNEL,
            },
            "leaf_params": {
                **hop_params,
                "tunnel_address": LEAF_TUNNEL,
                "peer_tunnel_address": ENTRY_TUNNEL,
            },
        },
    )
    assert established.status_code == 201, established.text
    return leaf_id


async def friend_config(session, node_id: str) -> dict:
    """The friend-facing config that would be pushed to one node, parsed."""
    node = await nodes.get_node(session, node_id)
    return json.loads((await apply.render_for_node(session, node))[FRIEND_TRANSPORT])


# --- the claim ----------------------------------------------------------------

async def test_a_friend_on_an_entry_node_leaves_through_the_hop(
    client, session, reality_params, hop_params
) -> None:
    """Every outbound in the pushed config is bound to the hop's near address.

    Asserted over ALL outbounds rather than "the hop outbound is there": a config that
    grew a direct outbound beside it would satisfy the weaker claim and is precisely the
    invisible failure — the friend exits in Russia and every screen stays green.
    """
    entry_id = await entry_node_serving_friends(client, session, reality_params)
    await hop_to_a_leaf(client, hop_params, entry_id)

    config = await friend_config(session, entry_id)

    assert config["outbounds"]
    for outbound in config["outbounds"]:
        assert outbound.get("sendThrough") == ENTRY_EXIT_ADDRESS, outbound


async def test_a_node_with_no_hop_still_exits_directly(
    client, session, reality_params
) -> None:
    """M3's second "done when". Every leaf, and every single-box deployment, is this."""
    entry_id = await entry_node_serving_friends(client, session, reality_params)

    config = await friend_config(session, entry_id)

    assert [outbound["protocol"] for outbound in config["outbounds"]] == ["freedom"]
    assert "sendThrough" not in config["outbounds"][0]
    assert "routing" not in config


async def test_a_hop_end_that_is_switched_off_is_still_the_way_out(
    client, session, reality_params, hop_params
) -> None:
    """Decision 3, guarding the query rather than a workflow.

    ``exit_through_hop`` deliberately reads the row's EXISTENCE and not ``enabled``. A hop
    end that is off is a tunnel that is not running — which is "the hop is down" — and the
    friend's config must still point into it and give them no exit. Had the query filtered
    on ``enabled``, this node would get its direct outbound back and every friend on it
    would exit in Russia with nothing saying so.

    The flag is set on the row rather than through the API on purpose: the API refuses to
    switch a hop end off at all (``nodes.set_transport_enabled``), so this state is only
    reachable by editing the database. It is guarded anyway, because the refusal is a
    different decision from this one and either could be revisited alone.
    """
    entry_id = await entry_node_serving_friends(client, session, reality_params)
    await hop_to_a_leaf(client, hop_params, entry_id)

    end = (await relay.hop_ends(session, entry_id))[0]
    end.enabled = False
    await session.flush()

    config = await friend_config(session, entry_id)

    for outbound in config["outbounds"]:
        assert outbound.get("sendThrough") == ENTRY_EXIT_ADDRESS, outbound


async def test_the_entry_learns_an_address_and_never_what_carries_the_hop(
    client, session, reality_params, hop_params
) -> None:
    """M3.2. The friend-facing config must not name the transport the hop runs on.

    The rule this milestone was most likely to break — and the whole reason the policy
    travels as an address. A protocol name here would mean a new hop transport is surgery
    on another transport's template.
    """
    entry_id = await entry_node_serving_friends(client, session, reality_params)
    await hop_to_a_leaf(client, hop_params, entry_id)

    node = await nodes.get_node(session, entry_id)
    rendered = await apply.render_for_node(session, node)

    assert HOP_TRANSPORT not in rendered[FRIEND_TRANSPORT]


# --- the policy the rendering comes from --------------------------------------

def test_a_friend_facing_row_on_a_node_with_a_hop_exits_through_it() -> None:
    """The table's third answer, stated as the property it exists for.

    Keyed on the purpose the row already carries AND on whether the node has a way out of
    its own, because the same friend-facing row means "exit here" on a leaf and "exit
    through the hop" on an entry — and getting that wrong in the second direction is
    silent.
    """
    from control.app.models import NodeTransport, TransportPurpose

    friends = NodeTransport(purpose=TransportPurpose.FRIENDS)
    assert nodes.egress_for(friends, ENTRY_EXIT_ADDRESS) is Egress.HOP
    assert nodes.egress_for(friends, None) is Egress.LOCAL
    assert nodes.egress_for(NodeTransport(purpose="something-later"), ENTRY_EXIT_ADDRESS) is (
        Egress.NONE
    )
