"""The entry→leaf hop, and the friend who must never see it.

WHAT: establishing a tunnel between two nodes through the panel, and proving it stays
      out of every subscription.
WHY:  the hop is the topology the charter is built on, and it is also the most
      dangerous row in the database: it is a working transport configuration on a
      serving node, so anything that treats it like the others hands a friend a
      configuration that routes them straight past the entry node the whole design
      exists to hide behind. Their client would use it happily.
HOW:  the hop is established from the panel, then a friend's subscription is fetched
      anonymously and checked for what it must not contain.

Boundary: real control + postgres. Neither node exists, so nothing here proves a tunnel
comes up — that is the owner's field check. What is proven is that the control plane
records the hop, renders it as a pair, and never delivers it to a person.
"""

import base64
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}
HOP_TRANSPORT = "amneziawg"


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


def hop_side(address: str, peer: str, port: int) -> dict:
    """One end's operator-supplied parameters. RFC 1918 tunnel addresses, per the model."""
    return {
        "port": port,
        "tunnel_address": address,
        "peer_tunnel_address": peer,
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
        "init_packet_magic_header": 1020327352,
        "response_packet_magic_header": 2060487442,
        "underload_packet_magic_header": 3679305607,
        "transport_packet_magic_header": 1436947798,
    }


async def two_nodes(operator, unique: str) -> tuple[str, str]:
    ids = []
    for role, address in (("entry", "192.0.2.20"), ("leaf", "192.0.2.10")):
        created = await operator.post(
            "/api/nodes",
            json={"name": f"{role}-{unique}", "address": address,
                  "location_label": f"{role.title()}land-{unique}"},
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    return ids[0], ids[1]


async def test_a_hop_is_established_and_stays_out_of_every_subscription(
    operator, client, unique: str
) -> None:
    entry_id, leaf_id = await two_nodes(operator, unique)

    created = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": hop_side("10.44.0.1/24", "10.44.0.2/24", 51820),
            "leaf_params": hop_side("10.44.0.2/24", "10.44.0.1/24", 51820),
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["entry"]["purpose"] == "relay-entry"
    assert created.json()["leaf"]["purpose"] == "relay-leaf"

    # A friend-facing protocol on the entry node, so the subscription is not empty for
    # the trivial reason, and both nodes serving so nothing is filtered by state.
    await operator.post(
        f"/api/nodes/{entry_id}/transports",
        json={
            "transport_name": "vless-reality",
            "params": {"port": 8450, "decoy_host": "www.example.com",
                       "decoy_port": 443, "server_names": ["www.example.com"]},
        },
    )
    for node_id in (entry_id, leaf_id):
        await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})

    friend_id = (await operator.post(
        "/api/friends", json={"nickname": f"kolya-{unique}"}
    )).json()["id"]
    token = (await operator.get(f"/api/friends/{friend_id}/subscription")).json()[
        "url"
    ].rsplit("/", 1)[-1]

    document = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    # This run's own entries only — other scenarios' nodes are in the same fleet.
    entries = [line for line in document.splitlines() if unique in line]

    assert HOP_TRANSPORT not in document
    assert len(entries) == 1, entries
    # The leaf's own label must not appear either: a friend picks an exit country from
    # the entries they are given, and the leaf is reached THROUGH the entry.
    assert f"Leafland-{unique}" not in entries


async def test_a_hop_that_would_not_form_a_tunnel_is_refused(
    operator, unique: str
) -> None:
    """Refused before either end is written — half a hop has no symptom."""
    entry_id, leaf_id = await two_nodes(operator, unique)

    response = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": hop_side("10.44.0.1/24", "10.44.0.2/24", 51820),
            # A different tunnel network: neither end would route to the other, and
            # both configuration files would be perfectly valid.
            "leaf_params": hop_side("10.99.0.2/24", "10.99.0.1/24", 51820),
        },
    )

    assert response.status_code == 400, response.text
    # Scoped to this run's own nodes: the e2e database is shared by every scenario in
    # a run, so "no hops at all" would assert on what other scenarios did.
    hops = (await operator.get("/api/hops")).json()
    assert not [hop for hop in hops if hop["entry"]["node_id"] == entry_id]


async def test_the_hop_transport_cannot_be_enabled_for_friends_at_all(
    operator, unique: str
) -> None:
    """Refused out loud rather than delivered as a silently short subscription."""
    entry_id, _ = await two_nodes(operator, unique)

    response = await operator.post(
        f"/api/nodes/{entry_id}/transports",
        json={"transport_name": HOP_TRANSPORT, "params": hop_side(
            "10.44.0.1/24", "10.44.0.2/24", 51821
        )},
    )

    assert response.status_code == 422, response.text
    assert "subscription" in response.text
