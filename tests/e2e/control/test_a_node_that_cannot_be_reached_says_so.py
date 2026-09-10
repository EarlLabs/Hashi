"""A half-configured node is never reported as fine — items 14 and 17.

WHAT: what happens when the owner applies configuration to a node that cannot be
      reached, and which state changes the control plane refuses.
WHY:  core invariants §4. A node that is half-configured and shown as active gets
      friends routed onto it, and what comes back is a bug report about their client
      rather than about the node. The honest failure is worth more than the optimistic
      success, and this is the scenario that keeps it honest.
HOW:  the nodes in the e2e stack are records with no reachable host, which is exactly
      the condition under test — no stub, no mock, a real SSH attempt that really
      fails.

Boundary: real control + postgres. There is no node, so nothing here proves a
SUCCESSFUL apply. That half needs a host and belongs to the owner's own check.
"""

import uuid

import pytest


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post(
        "/panel/login", data={"username": "owner", "password": "e2e-operator-password"}
    )
    assert response.status_code == 303, response.text
    return client


async def a_node(operator, unique: str, *, port: int) -> str:
    node_id = (await operator.post(
        "/api/nodes",
        json={"name": f"leaf-{unique}", "address": "192.0.2.10",
              "location_label": f"Testland-{unique}"},
    )).json()["id"]
    enabled = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": {
            "port": port, "decoy_host": "www.example.com", "decoy_port": 443,
            "server_names": ["www.example.com"],
        }},
    )
    assert enabled.status_code == 201, enabled.text
    return node_id


async def test_an_apply_that_cannot_reach_the_node_degrades_it_and_says_why(
    operator, unique: str
) -> None:
    node_id = await a_node(operator, unique, port=8460)
    await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})

    outcome = await operator.post(f"/api/nodes/{node_id}/apply")
    assert outcome.status_code == 502, outcome.text

    node = (await operator.get(f"/api/nodes/{node_id}")).json()
    assert node["state"] == "degraded"
    # The reason is carried, not just the state: an unexplained degraded node is a node
    # nobody fixes.
    assert node["state_detail"], node


async def test_a_degraded_node_stops_reaching_friends(operator, client, unique: str) -> None:
    """The point of the state, proven through the delivery endpoint."""
    import base64

    node_id = await a_node(operator, unique, port=8461)
    await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})

    friend_id = (await operator.post(
        "/api/friends", json={"nickname": f"kolya-{unique}"}
    )).json()["id"]
    token = (await operator.get(f"/api/friends/{friend_id}/subscription")).json()[
        "url"
    ].rsplit("/", 1)[-1]

    def mine(text: str) -> list[str]:
        lines = base64.b64decode(text).decode().splitlines()
        return [line for line in lines if unique in line]

    assert len(mine((await client.get(f"/sub/{token}")).text)) == 1

    await operator.post(f"/api/nodes/{node_id}/apply")  # fails, degrades the node

    assert mine((await client.get(f"/sub/{token}")).text) == []


async def test_a_retired_node_cannot_be_brought_back(operator, unique: str) -> None:
    """Its host is usually destroyed, and its address may now belong to a stranger.

    Re-activating the RECORD would put that address back into every friend's
    subscription. Creating a new node is the ten-minute operation instead.
    """
    node_id = await a_node(operator, unique, port=8462)
    assert (await operator.post(
        f"/api/nodes/{node_id}/state", json={"state": "retired"}
    )).status_code == 200

    refused = await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})

    assert refused.status_code == 409, refused.text
    # The refusal names what IS allowed, so the operator is not left guessing.
    assert "final" in refused.text or "may become" in refused.text


async def test_taking_a_node_out_of_rotation_is_not_the_same_as_retiring_it(
    operator, unique: str
) -> None:
    """active -> draft: it stops reaching friends immediately and keeps its config."""
    node_id = await a_node(operator, unique, port=8463)
    await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})

    assert (await operator.post(
        f"/api/nodes/{node_id}/state", json={"state": "draft"}
    )).status_code == 200

    node = (await operator.get(f"/api/nodes/{node_id}")).json()
    assert node["state"] == "draft"
    # Its configuration survives — read from the dialog that lists what this node
    # offers, which is where the operator would look now that M9.6 has deleted the
    # per-node page. Retiring is the operation that ends a node; this one only takes it
    # out of rotation, and the difference is worth nothing if the transports have to be
    # re-entered afterwards.
    offers = (await operator.get(f"/panel/nodes/{node_id}/transports")).text
    assert "vless-reality" in offers
