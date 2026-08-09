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
import io
import uuid
import zipfile

import pytest


def _entries(archive: bytes) -> dict[str, bytes]:
    """Every file in a config archive, by name.

    Read with the stdlib rather than by shelling out: this asserts what a friend's
    client will find in the response body, and nothing about our own tooling.
    """
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}

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


async def test_offering_the_hop_transport_to_friends_leaves_the_hop_END_untouched(
    operator, client, unique: str
) -> None:
    """The assertion this scenario used to make, and why it changed.

    Until backlog item 27 this transport could not be enabled for friends at all, and
    that refusal was asserted here. The refusal was never about the hop, though — it
    was about US: the delivery endpoint could produce only a base64 list of URIs, and
    this protocol has no URI form. Item 26 gave it a friend-facing serialisation and
    item 27 gave the endpoint a way to hand it over, so the refusal would now be a lie.
    It survives for a transport that declares NO friend-facing format at all, which is
    asserted in tests/control (no such transport ships, so it cannot be provoked here).

    What this file is actually about is untouched and is what is asserted instead: a
    hop END is a different row with a different purpose, and enabling the same
    transport for friends must not make the HOP reachable. The two are one protocol and
    two topologies, and conflating them would route a friend straight past the entry
    node the whole design exists to hide behind.
    """
    entry_id, leaf_id = await two_nodes(operator, unique)

    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": hop_side("10.55.0.1/24", "10.55.0.2/24", 51822),
            "leaf_params": hop_side("10.55.0.2/24", "10.55.0.1/24", 51822),
        },
    )
    assert established.status_code == 201, established.text
    hop_port = 51822

    # The same transport, now as an offer to friends — on a THIRD node, and that is not
    # a convenience. ``uq_node_transport`` is unique on (node, transport_name) with no
    # purpose in it, so one host cannot both run a hop and offer the same protocol to
    # friends; ``apply.render_for_node`` also keys rendered configs by transport name,
    # so two rows would collide there too. That is a real limitation of the topology
    # this scenario would otherwise describe, and it is written down as backlog item 34
    # rather than worked around silently here.
    exit_node = (
        await operator.post(
            "/api/nodes",
            json={"name": f"exit-{unique}", "address": "192.0.2.11",
                  "location_label": f"Exitland-{unique}"},
        )
    ).json()["id"]
    offered = await operator.post(
        f"/api/nodes/{exit_node}/transports",
        json={"transport_name": HOP_TRANSPORT, "params": hop_side(
            "10.56.0.1/24", "10.56.0.2/24", 51823
        )},
    )
    assert offered.status_code == 201, offered.text
    assert offered.json()["params"]["port"] == 51823

    for node_id in (entry_id, leaf_id, exit_node):
        assert (
            await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
        ).status_code == 200

    friend_id = (
        await operator.post("/api/friends", json={"nickname": f"hopfriend-{unique}"})
    ).json()["id"]
    token = (
        await operator.get(f"/api/friends/{friend_id}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    archive = await client.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert archive.status_code == 200, archive.text
    # Narrowed by this scenario's own port rather than by a name: the config file carries
    # addresses, keys and ports, and the node's label only reaches the FILENAME, where it
    # is truncated to fit an interface name. The stack is shared by the whole run, so the
    # port is the only marker of this fleet that is certain to be in the bytes.
    files = {
        name: content.decode()
        for name, content in _entries(archive.content).items()
        if ":51823" in content.decode()
    }
    assert files, "the friend received nothing for a transport that was offered to them"

    # The hop's own port and tunnel network appear nowhere in what a friend receives.
    # Asserted on the port and the address rather than on a row count, because the
    # failure that matters is a friend's device holding a configuration that dials the
    # entry node's tunnel.
    everything = "\n".join(files.values())
    assert f":{hop_port}" not in everything, (
        f"a hop end reached a friend's configuration:\n{everything[:2000]}"
    )
    assert "10.55.0." not in everything, (
        f"the hop's tunnel network reached a friend:\n{everything[:2000]}"
    )
