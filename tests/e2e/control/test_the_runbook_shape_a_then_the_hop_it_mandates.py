"""Following the runbook's own Shape A advice, then adding the hop it mandates.

WHAT: one box registered as its own node, the transport the runbook names for friends
      enabled on it, and then the entry→leaf hop the runbook requires — over the SAME
      transport, which is what the runbook says to use for it.
WHY:  this is the sequence that was refused in the field with
      ``409 'amneziawg' is already configured on node 'entry-ru'`` (M15). The old rule
      was one ``NodeTransport`` row per ``(node, transport_name)`` whatever the row was
      FOR, so the friend-facing transport and the hop end were the same pair and
      whichever came first excluded the other — with no delete for a node transport, and
      nothing anywhere saying so. Every existing scenario reached for a THIRD node to
      sidestep it, which is how a product-level contradiction stayed invisible to a
      green suite.
HOW:  the runbook's own order, over HTTP, as an operator following it would: register,
      offer, register the leaf, hop. Then the two refusals that DO survive — one port
      per node — and the one guarantee that must survive two rows of one transport on
      one node: the hop end still reaches no friend.

Boundary: real control + postgres. No node exists, so nothing here proves a tunnel comes
up; what is proven is that the control plane accepts the configuration the runbook asks
for and still refuses what a host would.
"""

import io
import uuid
import zipfile

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# The transport the runbook names TWICE — "enable a transport: amneziawg (or wireguard)
# on UDP 51820" for Shape A's friends, and "transport = amneziawg" for the hop in Shape
# B. Naming it here is the point of the scenario rather than a shortcut: the collision
# exists because one protocol is the right answer to both questions.
RUNBOOK_TRANSPORT = "amneziawg"

# The runbook's own number for the friend-facing side, and a second one for the hop.
# Two ports because two daemons on one host cannot share one — which is the rule this
# milestone moved the uniqueness onto.
FRIEND_PORT = 51820
HOP_PORT = 51821


def _entries(archive: bytes) -> dict[str, bytes]:
    """Every file in a config archive, by name.

    Read with the stdlib rather than by shelling out: this asserts what a friend's
    client will find in the response body, and nothing about our own tooling.
    """
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


def side(address: str, peer: str, port: int) -> dict:
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


async def a_node(operator, name: str, address: str, label: str) -> str:
    created = await operator.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": label},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def shape_a_box(operator, unique: str) -> tuple[str, str]:
    """The runbook's Shape A, as far as it goes: one box, one friend-facing transport.

    Returns the node's id and its friend-facing row's id. Steps 1 and 2 of *Register the
    box as its own node* — the apply in step 3 needs a real host and is the owner's field
    check, never this suite's.
    """
    node_id = await a_node(operator, f"box-{unique}", "192.0.2.30", f"Boxland-{unique}")
    offered = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": RUNBOOK_TRANSPORT,
            "params": side("10.60.0.1/24", "10.60.0.2/24", FRIEND_PORT),
        },
    )
    assert offered.status_code == 201, offered.text
    return node_id, offered.json()["id"]


async def test_the_box_the_runbook_describes_can_also_carry_the_hop_it_requires(
    operator, unique: str
) -> None:
    """The whole milestone in one sequence: offer it to friends, then hop over it.

    The assertion that was red before M15 is the status code — this answered 409 with
    *"'amneziawg' is already configured on node ..."*, and there was no way back from it
    short of editing the database by hand.
    """
    entry_id, friend_row = await shape_a_box(operator, unique)
    leaf_id = await a_node(operator, f"leaf-{unique}", "192.0.2.31", f"Leafland-{unique}")

    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": RUNBOOK_TRANSPORT,
            "entry_params": side("10.61.0.1/24", "10.61.0.2/24", HOP_PORT),
            "leaf_params": side("10.61.0.2/24", "10.61.0.1/24", HOP_PORT),
        },
    )

    assert established.status_code == 201, established.text
    hop = established.json()
    assert hop["entry"]["node_id"] == entry_id
    assert hop["entry"]["transport_name"] == RUNBOOK_TRANSPORT

    # And it is a real pair rather than half a hop: the leaf end exists and points back.
    assert hop["leaf"] is not None, hop
    assert hop["leaf"]["node_id"] == leaf_id
    # The friend-facing row this box already had is untouched and is still its own row.
    assert hop["entry"]["id"] != friend_row


async def test_the_two_rows_on_one_node_take_two_names(operator, unique: str) -> None:
    """The friend-facing row keeps the transport's own name; the hop end takes another.

    Asserted separately from the status code because it is the half a green 201 does not
    prove. The first instance keeping the plain name is deliberate and load-bearing: every
    node already in the field has ``/opt/hashi/conf/<transport>.conf`` on disk, and a
    scheme that renamed it would take the interface down under a running daemon.
    """
    entry_id, _ = await shape_a_box(operator, unique)
    leaf_id = await a_node(operator, f"leaf2-{unique}", "192.0.2.32", f"Leafland-{unique}")

    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": RUNBOOK_TRANSPORT,
            "entry_params": side("10.62.0.1/24", "10.62.0.2/24", HOP_PORT),
            "leaf_params": side("10.62.0.2/24", "10.62.0.1/24", HOP_PORT),
        },
    )
    assert established.status_code == 201, established.text

    entry_end = established.json()["entry"]
    leaf_end = established.json()["leaf"]
    assert entry_end["config_name"] != RUNBOOK_TRANSPORT, (
        "the hop end took the name the friend-facing row already holds on this node"
    )
    # The leaf is a fresh node and runs one of this transport, so it keeps the plain
    # name — the difference is per node, never fleet-wide.
    assert leaf_end["config_name"] == RUNBOOK_TRANSPORT


async def test_two_transports_on_one_node_may_not_share_a_port(
    operator, unique: str
) -> None:
    """What a host actually refuses, and the refusal an operator can act on.

    The data planes run with ``network_mode: host``, so two of them asking for one port
    is one bind and one container that dies. Refused when the second is created rather
    than discovered at apply, and the sentence names the port and what already holds it.
    """
    node_id, _ = await shape_a_box(operator, unique)

    collided = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": RUNBOOK_TRANSPORT,
            "params": side("10.63.0.1/24", "10.63.0.2/24", FRIEND_PORT),
        },
    )

    assert collided.status_code == 409, collided.text
    body = collided.json()["error"]
    assert body["code"] == "conflict"
    assert str(FRIEND_PORT) in body["message"], body["message"]
    assert RUNBOOK_TRANSPORT in body["message"], body["message"]


async def test_a_hop_end_on_the_same_node_still_reaches_no_friend(
    operator, client, unique: str
) -> None:
    """The guarantee two rows of one transport on one node must not weaken.

    Before M15 the purpose column was one of TWO things separating a friend's offer from
    a hop end, the other being that they could never be the same transport on the same
    node. That second one is gone by design, so the filter in
    ``nodes.serving_transports`` is now the only thing standing between a friend and the
    entry↔leaf tunnel — which is why this is asserted here and not left to the scenario
    that proves it for two different nodes.
    """
    entry_id, _ = await shape_a_box(operator, unique)
    leaf_id = await a_node(operator, f"leaf3-{unique}", "192.0.2.33", f"Leafland-{unique}")

    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": RUNBOOK_TRANSPORT,
            "entry_params": side("10.64.0.1/24", "10.64.0.2/24", HOP_PORT),
            "leaf_params": side("10.64.0.2/24", "10.64.0.1/24", HOP_PORT),
        },
    )
    assert established.status_code == 201, established.text

    for node_id in (entry_id, leaf_id):
        assert (
            await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
        ).status_code == 200

    friend_id = (
        await operator.post("/api/friends", json={"nickname": f"boxfriend-{unique}"})
    ).json()["id"]
    token = (
        await operator.get(f"/api/friends/{friend_id}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    archive = await client.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert archive.status_code == 200, archive.text
    received = "\n".join(
        content.decode() for content in _entries(archive.content).values()
    )

    # The friend-facing row on this box DID arrive, so the two refusals below are not
    # passing because the subscription is empty. Its endpoint is this scenario's own
    # address and port, which no other scenario in the run uses.
    assert f"192.0.2.30:{FRIEND_PORT}" in received, received[:2000]

    # The hop end on the SAME node did not. Its port and its tunnel network are the two
    # markers a friend's device must not hold — the port because it would dial the
    # entry↔leaf tunnel directly, the network because it is the topology itself.
    assert f":{HOP_PORT}" not in received, "a hop end reached a friend's configuration"
    assert "10.64.0." not in received, "the hop's tunnel network reached a friend"
