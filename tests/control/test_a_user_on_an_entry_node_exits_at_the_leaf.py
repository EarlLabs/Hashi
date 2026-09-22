"""What the control plane pushes to an entry node that has a hop — M3.

WHAT: that a user-facing transport on a node with a hop is rendered to leave through
      that hop, and that a node without one is rendered to leave by its own route.
WHY:  this is the charter's core claim and the failure it hides is invisible. Before M3
      the entry's config had one hardcoded outbound and the node dialled the internet
      itself: the user connects, pages load, the panel shows two active nodes and a
      live hop, and the exit is in Russia. Nothing logs it, and nothing may. Since M16
      the same holds for where a user's destination NAMES are looked up, which
      ``sendThrough`` alone never reached.

      The edge zone proves a renderer given the policy obeys it. This file proves the
      other half, which is where M14's own bug lived: that the policy and the address
      actually REACH the renderer from the database. A correct mapping whose argument
      never arrives is exactly the shape of that failure — everything right, nothing
      connected.
HOW:  real Postgres, real encryption, real rendering, through the same API an operator
      uses. No node is contacted: the claim is about the text that WOULD be pushed.

      Whether a user's traffic then emerges at the leaf's address is a field
      observation on two real hosts with a real client. Nothing here stands in for it —
      and decision 3 says so explicitly, because the success and the failure differ only
      in where packets come out.
"""

import json

import pytest

from control.app.errors import NodeOperationFailed
from control.app.models import NodeState
from control.app.services import apply, nodes, relay
from edge.egress import NOT_THE_INTERNET, Egress

HOP_TRANSPORT = "amneziawg"
USER_TRANSPORT = "vless-reality"

ENTRY_TUNNEL = "10.44.0.1/24"
ENTRY_EXIT_ADDRESS = "10.44.0.1"
LEAF_TUNNEL = "10.44.0.2/24"

# The resolver an entry node's record names — M16. RFC 5737 documentation address.
RESOLVER = "192.0.2.53"

# The two outbounds a proxy's config carries, named once so the assertions below read as
# sentences. ``direct`` is this node's own route; ``refused`` opens nothing at all.
BY_THE_NODES_OWN_ROUTE = "direct"
REFUSED = "refused"


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


async def entry_node_serving_users(
    client, session, reality_params, *, resolver: str | None = RESOLVER
) -> str:
    """A Russian entry node with a user-facing transport and no hop yet.

    Given a resolver unless a test says otherwise — M16: a node that dials a hop does not
    render without one, and every test here but the one about that refusal is about a
    node registered the way the product asks.
    """
    created = await client.post(
        "/api/nodes",
        json={
            "name": "entry-ru",
            "address": "192.0.2.20",
            "location_label": "Russia",
            "resolver": resolver,
        },
    )
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": USER_TRANSPORT, "params": reality_params},
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


async def user_config(session, node_id: str) -> dict:
    """The user-facing config that would be pushed to one node, parsed."""
    node = await nodes.get_node(session, node_id)
    return json.loads((await apply.render_for_node(session, node))[USER_TRANSPORT])


# --- the claim ----------------------------------------------------------------

async def test_a_user_on_an_entry_node_leaves_through_the_hop(
    client, session, reality_params, hop_params
) -> None:
    """Every outbound in the pushed config is bound to the hop's near address.

    Asserted over ALL outbounds rather than "the hop outbound is there": a config that
    grew a direct outbound beside it would satisfy the weaker claim and is precisely the
    invisible failure — the user exits in Russia and every screen stays green.
    """
    entry_id = await entry_node_serving_users(client, session, reality_params)
    await hop_to_a_leaf(client, hop_params, entry_id)

    config = await user_config(session, entry_id)

    assert config["outbounds"]
    for outbound in config["outbounds"]:
        assert outbound.get("sendThrough") == ENTRY_EXIT_ADDRESS, outbound


async def test_a_node_with_no_hop_still_exits_directly(
    client, session, reality_params
) -> None:
    """M3's second "done when". Every leaf, and every single-box deployment, is this.

    Registered with no resolver on purpose: a node without a hop needs none (M16), because
    its lookups and its exit already leave by the same route — so it carries no ``dns``
    object at all, and is not refused for the missing value.

    "Directly" is asserted as three facts and not as an absence, which is what M23's tenth
    round changed here. It used to read ``"routing" not in config``, and that was a true
    statement of the bytes standing in for a claim about the exit — which the bytes stopped
    making the moment such a node had anything to refuse. A proxy on a leaf now carries a
    routing section, and a user on it may reach the internet and NOT the entry at the far
    end of that node's hop, its provider's LAN or its metadata service. So: the rule that
    carries a user is the LAST one, it names an outbound that binds no source address,
    and the only rule read before it is the refusal. Nothing below it means nothing else
    can decide; no ``sendThrough`` means the node's own route; and both together are what
    "exits directly" is.
    """
    entry_id = await entry_node_serving_users(
        client, session, reality_params, resolver=None
    )

    config = await user_config(session, entry_id)

    outbounds = {outbound["tag"]: outbound for outbound in config["outbounds"]}
    assert outbounds[BY_THE_NODES_OWN_ROUTE]["protocol"] == "freedom"
    assert outbounds[REFUSED]["protocol"] == "blackhole"
    for outbound in config["outbounds"]:
        assert "sendThrough" not in outbound, outbound

    rules = config["routing"]["rules"]
    assert [rule["outboundTag"] for rule in rules] == [REFUSED, BY_THE_NODES_OWN_ROUTE]
    assert tuple(rules[0]["ip"]) == NOT_THE_INTERNET
    assert "ip" not in rules[1], rules[1]
    assert "dns" not in config


async def test_a_hop_end_that_is_switched_off_is_still_the_way_out(
    client, session, reality_params, hop_params
) -> None:
    """Decision 3, guarding the query rather than a workflow.

    ``exit_through_hop`` deliberately reads the row's EXISTENCE and not ``enabled``. A hop
    end that is off is a tunnel that is not running — which is "the hop is down" — and the
    user's config must still point into it and give them no exit. Had the query filtered
    on ``enabled``, this node would get its direct outbound back and every user on it
    would exit in Russia with nothing saying so.

    The flag is set on the row rather than through the API on purpose: the API refuses to
    switch a hop end off at all (``nodes.set_transport_enabled``), so this state is only
    reachable by editing the database. It is guarded anyway, because the refusal is a
    different decision from this one and either could be revisited alone.
    """
    entry_id = await entry_node_serving_users(client, session, reality_params)
    await hop_to_a_leaf(client, hop_params, entry_id)

    end = (await relay.hop_ends(session, entry_id))[0]
    end.enabled = False
    await session.flush()

    config = await user_config(session, entry_id)

    for outbound in config["outbounds"]:
        assert outbound.get("sendThrough") == ENTRY_EXIT_ADDRESS, outbound


async def test_the_entry_learns_an_address_and_never_what_carries_the_hop(
    client, session, reality_params, hop_params
) -> None:
    """M3.2. The user-facing config must not name the transport the hop runs on.

    The rule this milestone was most likely to break — and the whole reason the policy
    travels as an address. A protocol name here would mean a new hop transport is surgery
    on another transport's template.
    """
    entry_id = await entry_node_serving_users(client, session, reality_params)
    await hop_to_a_leaf(client, hop_params, entry_id)

    node = await nodes.get_node(session, entry_id)
    rendered = await apply.render_for_node(session, node)

    assert HOP_TRANSPORT not in rendered[USER_TRANSPORT]


# --- M16: the lookup takes the same way out -------------------------------------

async def test_a_users_lookups_go_through_the_hop_to_the_nodes_own_resolver(
    client, session, reality_params, hop_params
) -> None:
    """The resolver on the node's record reaches the pushed config, and the lookup is
    routed out of the same address as the traffic.

    The edge zone proves a renderer given a resolver uses it. This proves the value gets
    there from the database — M14's bug had exactly this shape: a correct renderer whose
    argument never arrived.
    """
    entry_id = await entry_node_serving_users(client, session, reality_params)
    await hop_to_a_leaf(client, hop_params, entry_id)

    config = await user_config(session, entry_id)

    assert config["dns"]["servers"] == [RESOLVER]
    outbounds = {outbound["tag"]: outbound for outbound in config["outbounds"]}
    carriers = [
        rule["outboundTag"]
        for rule in config["routing"]["rules"]
        if config["dns"]["tag"] in rule["inboundTag"]
    ]
    assert carriers, "the resolver's own queries are routed by default, not into the hop"
    for carrier in carriers:
        assert outbounds[carrier]["sendThrough"] == ENTRY_EXIT_ADDRESS
        assert outbounds[carrier]["settings"]["domainStrategy"] == "UseIPv4"


async def test_an_entry_with_a_hop_and_no_resolver_is_refused_rather_than_resolved_at_home(
    client, session, reality_params, hop_params
) -> None:
    """Decision 3, applied to the lookup, through the path an apply takes.

    The alternative is the M16 bug itself: a config the daemon accepts, an exit abroad,
    and every name a user visits resolved on the near side of the hop. Refused as a
    node operation, with the sentence the operator reads.
    """
    entry_id = await entry_node_serving_users(
        client, session, reality_params, resolver=None
    )
    await hop_to_a_leaf(client, hop_params, entry_id)
    node = await nodes.get_node(session, entry_id)

    with pytest.raises(NodeOperationFailed) as refusal:
        await apply.render_for_node(session, node)

    assert "names no resolver" in str(refusal.value), refusal.value


async def test_the_resolver_is_kept_on_the_record_it_was_given_to(client) -> None:
    """Node-record data, like every other address, and handed back by the API as such."""
    created = await client.post(
        "/api/nodes",
        json={
            "name": "entry-ru",
            "address": "192.0.2.20",
            "location_label": "Russia",
            "resolver": RESOLVER,
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["resolver"] == RESOLVER
    fetched = await client.get(f"/api/nodes/{created.json()['id']}")
    assert fetched.json()["resolver"] == RESOLVER


@pytest.mark.parametrize("resolver", ["localhost", "dns.example.com", "127.0.0.53"])
async def test_a_resolver_that_could_never_carry_a_lookup_is_refused_at_registration(
    client, resolver: str
) -> None:
    """Refused while the operator is still at the form: a value ``edge`` would refuse
    surfaces otherwise at the first apply after a hop — on another screen, maybe weeks
    later, after users have been given the node."""
    refused = await client.post(
        "/api/nodes",
        json={
            "name": "entry-ru",
            "address": "192.0.2.20",
            "location_label": "Russia",
            "resolver": resolver,
        },
    )

    assert refused.status_code == 400, refused.text
    assert "resolver" in refused.text
    assert (await client.get("/api/nodes")).json() == []


# --- the policy the rendering comes from --------------------------------------

def test_a_user_facing_row_on_a_node_with_a_hop_exits_through_it() -> None:
    """The table's third answer, stated as the property it exists for.

    Keyed on the purpose the row already carries AND on whether the node has a way out of
    its own, because the same user-facing row means "exit here" on a leaf and "exit
    through the hop" on an entry — and getting that wrong in the second direction is
    silent.
    """
    from control.app.models import NodeTransport, TransportPurpose

    users = NodeTransport(purpose=TransportPurpose.FRIENDS)
    assert nodes.egress_for(users, ENTRY_EXIT_ADDRESS) is Egress.HOP
    assert nodes.egress_for(users, None) is Egress.LOCAL
    assert nodes.egress_for(NodeTransport(purpose="something-later"), ENTRY_EXIT_ADDRESS) is (
        Egress.NONE
    )
