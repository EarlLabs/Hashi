"""A node's resolver can be set after it is registered — M16, and the one field that can.

WHAT: the one edit a node record admits: ``POST /api/nodes/{id}/resolver`` and the Nodes
      screen's resolver dialog, both through ``nodes.set_resolver``.
WHY:  M16 made a node that dials a hop refuse to render without a resolver, and migration
      0005 gives every existing node none. With no way to write the field afterwards, the
      field's own entry node — already active, already dialling a hop — could never be
      applied again, and no revocation could reach it. The value is node-record data; this
      is how it gets onto the node that needs it. Everything else on a node stays fixed.
HOW:  real Postgres through the API and the panel. Nothing is pushed: setting a resolver
      changes the record, and the apply that carries it to the host is the operator's next
      step — which is why the render, not a push, is what proves it took.
"""

import json

import pytest

from control.app.errors import NodeOperationFailed
from control.app.models import NodeState
from control.app.services import apply, nodes

HOP_TRANSPORT = "amneziawg"
USER_TRANSPORT = "vless-reality"

# RFC 5737 documentation address, standing in for the resolver an operator names.
RESOLVER = "192.0.2.53"


@pytest.fixture
def hop_params() -> dict[str, object]:
    """One hop end's operator-supplied half, as in the entry-node file."""
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


async def a_node(client, name: str = "entry-ru", address: str = "192.0.2.20") -> str:
    created = await client.post(
        "/api/nodes", json={"name": name, "address": address, "location_label": "Testland"}
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def an_entry_the_upgrade_stranded(client, session, reality_params, hop_params) -> str:
    """An active entry serving users over a hop, with no resolver — what 0005 leaves."""
    entry = await a_node(client)
    enabled = await client.post(
        f"/api/nodes/{entry}/transports",
        json={"transport_name": USER_TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=entry, state=NodeState.ACTIVE)
    leaf = await a_node(client, "leaf-nl", "192.0.2.10")
    established = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry,
            "leaf_node_id": leaf,
            "transport_name": HOP_TRANSPORT,
            "entry_params": {
                **hop_params,
                "tunnel_address": "10.44.0.1/24",
                "peer_tunnel_address": "10.44.0.2/24",
            },
            "leaf_params": {
                **hop_params,
                "tunnel_address": "10.44.0.2/24",
                "peer_tunnel_address": "10.44.0.1/24",
            },
        },
    )
    assert established.status_code == 201, established.text
    return entry


async def test_an_entry_the_upgrade_stranded_renders_once_its_resolver_is_set(
    client, session, reality_params, hop_params
) -> None:
    """The whole point, end to end short of a push: refused, set, rendered."""
    entry = await an_entry_the_upgrade_stranded(client, session, reality_params, hop_params)
    with pytest.raises(NodeOperationFailed, match="names no resolver"):
        await apply.render_for_node(session, await nodes.get_node(session, entry))

    response = await client.post(f"/api/nodes/{entry}/resolver", json={"resolver": RESOLVER})

    assert response.status_code == 200, response.text
    assert response.json()["resolver"] == RESOLVER
    node = await nodes.get_node(session, entry)
    await session.refresh(node)
    config = json.loads((await apply.render_for_node(session, node))[USER_TRANSPORT])
    assert config["dns"]["servers"] == [RESOLVER]


@pytest.mark.parametrize("resolver", ["localhost", "dns.example.com", "127.0.0.53", "2001:db8::53"])
async def test_a_resolver_that_could_never_carry_a_lookup_is_refused_here_as_at_registration(
    client, resolver: str
) -> None:
    """The same rule, the same status, as at registration — and the record untouched."""
    node = await a_node(client)

    refused = await client.post(f"/api/nodes/{node}/resolver", json={"resolver": resolver})

    assert refused.status_code == 400, refused.text
    assert "resolver" in refused.text
    assert (await client.get(f"/api/nodes/{node}")).json()["resolver"] is None


async def test_an_empty_resolver_is_not_a_way_to_take_one_away(client) -> None:
    """This path gives a node the resolver it needs. It is not the one that removes it."""
    node = await a_node(client)

    assert (
        await client.post(f"/api/nodes/{node}/resolver", json={"resolver": ""})
    ).status_code == 422
    dialog = await client.post(
        f"/panel/nodes/{node}/resolver", data={"resolver": "  "}, headers={"HX-Request": "true"}
    )
    assert dialog.status_code == 422
    assert 'id="node-resolver-error"' in dialog.text
    assert "required" in dialog.text


async def test_the_nodes_own_row_opens_the_dialog_and_the_dialog_sets_it(client) -> None:
    """From the row, through the dialog, onto the record — and it says what is still to do."""
    node = await a_node(client)

    table = await client.get("/panel/nodes/table")
    assert f'hx-get="/panel/nodes/{node}/resolver"' in table.text
    dialog = await client.get(f"/panel/nodes/{node}/resolver")
    assert dialog.status_code == 200
    assert "Set this node" in dialog.text
    assert 'id="node-resolver"' in dialog.text

    response = await client.post(
        f"/panel/nodes/{node}/resolver", data={"resolver": RESOLVER}, headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    assert "resolver set for entry-ru — apply it for the change to reach the node" in response.text
    assert "nodes-changed" in response.headers.get("HX-Trigger", "")
    assert (await client.get(f"/api/nodes/{node}")).json()["resolver"] == RESOLVER
    # …and the dialog, opened again, shows what the record now holds.
    assert f'value="{RESOLVER}"' in (await client.get(f"/panel/nodes/{node}/resolver")).text


async def test_a_refused_resolver_comes_back_under_its_own_box_with_what_was_typed(
    client,
) -> None:
    """M8.6's shape: the sentence under the field, the value kept, nothing written."""
    node = await a_node(client)

    refused = await client.post(
        f"/panel/nodes/{node}/resolver",
        data={"resolver": "localhost"},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422
    assert 'id="node-resolver-error"' in refused.text
    assert "not an IPv4 address" in refused.text
    assert 'value="localhost"' in refused.text
    assert (await client.get(f"/api/nodes/{node}")).json()["resolver"] is None
