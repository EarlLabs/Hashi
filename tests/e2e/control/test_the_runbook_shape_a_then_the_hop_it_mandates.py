"""Following the runbook's own Shape A advice, then adding the hop it mandates.

WHAT: one box registered as its own node, the transport the runbook names for users
      enabled on it, and then the entry→leaf hop the runbook requires — over the SAME
      transport, which is what the runbook says to use for it. The box becomes the end of
      that hop which WAITS, because since M25 it is the only end it can be.
WHY:  this is the sequence that was refused in the field with
      ``409 'amneziawg' is already configured on node 'entry-ru'`` (M15). The old rule
      was one ``NodeTransport`` row per ``(node, transport_name)`` whatever the row was
      FOR, so the user-facing transport and the hop end were the same pair and
      whichever came first excluded the other — with no delete for a node transport, and
      nothing anywhere saying so. Every existing scenario reached for a THIRD node to
      sidestep it, which is how a product-level contradiction stayed invisible to a
      green suite.

      M25 added the other half of the same story, from the field again: the box may carry
      both rows, and the node that DIALS the hop may not — its users' packets would be
      handed to its own routing table, which has no way to send them through the hop.
      That was accepted at both doors and refused at the apply, after a user had been
      handed a configuration file for it; it is refused at the doors now, and this
      scenario walks both sides so the runbook's advice and the product cannot drift
      apart again.
HOW:  the runbook's own order, over HTTP, as an operator following it would: register,
      offer, register the other box, hop. Then the two refusals that DO survive — one
      port per node, and no users on a kernel tunnel behind a hop — and the one guarantee
      that must survive two rows of one transport on one node: the hop end still reaches
      no user.

Boundary: real control + postgres. No node exists, so nothing here proves a tunnel comes
up; what is proven is that the control plane accepts the configuration the runbook asks
for and still refuses what a host would.
"""

import io
import re
import uuid
import zipfile

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# The transport the runbook names TWICE — "enable a transport: amneziawg (or wireguard)
# on UDP 51820" for Shape A's users, and "transport = amneziawg" for the hop in Shape
# B. Naming it here is the point of the scenario rather than a shortcut: the collision
# exists because one protocol is the right answer to both questions.
RUNBOOK_TRANSPORT = "amneziawg"

# The runbook's own number for the user-facing side, and a second one for the hop.
# Two ports because two daemons on one host cannot share one — which is the rule this
# milestone moved the uniqueness onto.
USER_PORT = 51820
HOP_PORT = 51821

# How many users a user-facing row of this transport may hand an address to — M17. The
# stand is WARM: every scenario in this directory adds users to one control plane and
# none of them are removed, so a pool is measured against a fleet that only grows. Sized
# in the low thousands against a /20 tunnel for that reason — the number is an upper
# bound on people, not a resource, and a pool that only just fitted would turn this file
# red on the day an unrelated scenario adds a user.
POOL_SIZE = 2000


def _entries(archive: bytes) -> dict[str, bytes]:
    """Every file in a config archive, by name.

    Read with the stdlib rather than by shelling out: this asserts what a user's
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
    """The runbook's Shape A, as far as it goes: one box, one user-facing transport.

    Returns the node's id and its user-facing row's id. Steps 1 and 2 of *Register the
    box as its own node* — the apply in step 3 needs a real host and is the owner's field
    check, never this suite's.
    """
    node_id = await a_node(operator, f"box-{unique}", "192.0.2.30", f"Boxland-{unique}")
    offered = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": RUNBOOK_TRANSPORT,
            "pool_size": POOL_SIZE,
            "params": side("10.60.0.1/20", "10.60.0.2/20", USER_PORT),
        },
    )
    assert offered.status_code == 201, offered.text
    return node_id, offered.json()["id"]


async def test_the_box_the_runbook_describes_can_also_carry_the_hop_it_requires(
    operator, unique: str
) -> None:
    """The whole milestone in one sequence: offer it to users, then hop over it.

    The assertion that was red before M15 is the status code — this answered 409 with
    *"'amneziawg' is already configured on node ..."*, and there was no way back from it
    short of editing the database by hand.

    The box is the end that WAITS, which is what an operator growing out of Shape A
    actually has: the box they already run abroad keeps its users and becomes the far end
    of the hop a new Russian entry dials. Making it the DIALLING end is the other half of
    this file — refused, and asserted two tests down.
    """
    box_id, user_row = await shape_a_box(operator, unique)
    entry_id = await a_node(operator, f"ru-{unique}", "192.0.2.41", f"Entryland-{unique}")

    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": box_id,
            "transport_name": RUNBOOK_TRANSPORT,
            "entry_params": side("10.61.0.1/24", "10.61.0.2/24", HOP_PORT),
            "leaf_params": side("10.61.0.2/24", "10.61.0.1/24", HOP_PORT),
        },
    )

    assert established.status_code == 201, established.text
    hop = established.json()
    assert hop["leaf"]["node_id"] == box_id
    assert hop["leaf"]["transport_name"] == RUNBOOK_TRANSPORT

    # And it is a real pair rather than half a hop: the entry end exists and points back.
    assert hop["entry"] is not None, hop
    assert hop["entry"]["node_id"] == entry_id
    # The user-facing row this box already had is untouched and is still its own row.
    assert hop["leaf"]["id"] != user_row


async def test_the_same_box_is_refused_the_hop_it_would_dial(
    operator, unique: str
) -> None:
    """The other order, and the one the runbook used to recommend — M25.

    A box already offering its users a kernel tunnel cannot become the end that DIALS: on
    such a node a user's traffic must leave through the hop, and a data plane whose
    packets the node's own kernel routes has no way to put somebody else's there. It was
    taken without a word until M25, and the apply refused it afterwards — with a user
    already holding a configuration file for it.

    Both facts are asserted, because the second is the one the walk measured: the answer
    is a refusal, and the fleet is exactly as it was.
    """
    box_id, _ = await shape_a_box(operator, unique)
    far_id = await a_node(operator, f"far-{unique}", "192.0.2.42", f"Farland-{unique}")

    refused = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": box_id,
            "leaf_node_id": far_id,
            "transport_name": RUNBOOK_TRANSPORT,
            "entry_params": side("10.67.0.1/24", "10.67.0.2/24", HOP_PORT),
            "leaf_params": side("10.67.0.2/24", "10.67.0.1/24", HOP_PORT),
        },
    )

    assert refused.status_code == 409, refused.text
    body = refused.json()["error"]
    assert body["code"] == "no_exit_through_the_hop"
    assert RUNBOOK_TRANSPORT in body["message"], body["message"]
    # Scoped to this run's own node, because the stand is shared by every scenario in it.
    hops = (await operator.get("/api/hops")).json()
    assert not [hop for hop in hops if hop["entry"]["node_id"] == box_id]


async def test_the_two_rows_on_one_node_take_two_names(operator, unique: str) -> None:
    """The user-facing row keeps the transport's own name; the hop end takes another.

    Asserted separately from the status code because it is the half a green 201 does not
    prove. The first instance keeping the plain name is deliberate and load-bearing: every
    node already in the field has ``/opt/hashi/conf/<transport>.conf`` on disk, and a
    scheme that renamed it would take the interface down under a running daemon.
    """
    box_id, _ = await shape_a_box(operator, unique)
    entry_id = await a_node(operator, f"ru2-{unique}", "192.0.2.43", f"Entryland-{unique}")

    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": box_id,
            "transport_name": RUNBOOK_TRANSPORT,
            "entry_params": side("10.62.0.1/24", "10.62.0.2/24", HOP_PORT),
            "leaf_params": side("10.62.0.2/24", "10.62.0.1/24", HOP_PORT),
        },
    )
    assert established.status_code == 201, established.text

    entry_end = established.json()["entry"]
    leaf_end = established.json()["leaf"]
    assert leaf_end["config_name"] != RUNBOOK_TRANSPORT, (
        "the hop end took the name the user-facing row already holds on this node"
    )
    # The entry is a fresh node and runs one of this transport, so it keeps the plain
    # name — the difference is per node, never fleet-wide.
    assert entry_end["config_name"] == RUNBOOK_TRANSPORT


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
            "pool_size": POOL_SIZE,
            "params": side("10.63.0.1/20", "10.63.0.2/20", USER_PORT),
        },
    )

    assert collided.status_code == 409, collided.text
    body = collided.json()["error"]
    assert body["code"] == "conflict"
    assert str(USER_PORT) in body["message"], body["message"]
    assert RUNBOOK_TRANSPORT in body["message"], body["message"]


async def test_a_hop_end_on_the_same_node_still_reaches_no_user(
    operator, client, unique: str
) -> None:
    """The guarantee two rows of one transport on one node must not weaken.

    Before M15 the purpose column was one of TWO things separating a user's offer from
    a hop end, the other being that they could never be the same transport on the same
    node. That second one is gone by design, so the filter in
    ``nodes.serving_transports`` is now the only thing standing between a user and the
    entry↔leaf tunnel — which is why this is asserted here and not left to the scenario
    that proves it for two different nodes.
    """
    box_id, _ = await shape_a_box(operator, unique)
    entry_id = await a_node(operator, f"ru3-{unique}", "192.0.2.44", f"Entryland-{unique}")

    established = await operator.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": box_id,
            "transport_name": RUNBOOK_TRANSPORT,
            "entry_params": side("10.64.0.1/24", "10.64.0.2/24", HOP_PORT),
            "leaf_params": side("10.64.0.2/24", "10.64.0.1/24", HOP_PORT),
        },
    )
    assert established.status_code == 201, established.text

    for node_id in (entry_id, box_id):
        assert (
            await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
        ).status_code == 200

    user_id = (
        await operator.post("/api/users", json={"nickname": f"boxuser-{unique}"})
    ).json()["id"]
    token = (
        await operator.get(f"/api/users/{user_id}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    archive = await client.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert archive.status_code == 200, archive.text
    received = "\n".join(
        content.decode() for content in _entries(archive.content).values()
    )

    # The user-facing row on this box DID arrive, so the two refusals below are not
    # passing because the subscription is empty. Its endpoint is this scenario's own
    # address and port, which no other scenario in the run uses.
    assert f"192.0.2.30:{USER_PORT}" in received, received[:2000]

    # The hop end on the SAME node did not. Its port and its tunnel network are the two
    # markers a user's device must not hold — the port because it would dial the
    # entry↔leaf tunnel directly, the network because it is the topology itself.
    assert f":{HOP_PORT}" not in received, "a hop end reached a user's configuration"
    assert "10.64.0." not in received, "the hop's tunnel network reached a user"


# --- the way back out (M15.2) -------------------------------------------------
#
# Everything above is about what the box may now carry. This is about what it can stop
# carrying: since uniqueness moved onto the port and the config name, and ``enabled`` is
# deliberately not consulted, a row switched off still holds both — so removal is the only
# exit from a collision, and it is the operator's own route out of the state this
# milestone was found in.

# This scenario's own node, and a port band nothing else in this suite uses. Its own
# rather than ``shape_a_box``'s because the assertion below is an ABSENCE: every other
# scenario in this file registers a box at the same address, and a user is granted
# every SERVING node, so a shared endpoint would make "it is gone" depend on what else
# ran.
#
# THE STAND IS NOT RESET BETWEEN RUNS, and that is the harder half. A second
# ``make test-e2e`` against one stack leaves this scenario's own earlier box active at
# whatever endpoint it used, and a user created by the second run is granted it too —
# so the endpoint is derived per run, and the assertion is a DELTA rather than a plain
# absence. Either alone would pass on a cold stand and go red on a warm one, which is the
# failure that reaches nobody until the day somebody re-runs the suite.
REMOVAL_ADDRESS = "192.0.2.34"
REMOVAL_PORT_BAND = (52000, 4000)


def removal_port(unique: str) -> int:
    """This run's listening port, inside a band no other scenario in this suite uses."""
    first, width = REMOVAL_PORT_BAND
    return first + int(unique[:4], 16) % width


def endpoints_carrying(archive: bytes, marker: str) -> int:
    """How many files in a user's archive point at one endpoint.

    A count rather than a membership test, because what is being proven is that ONE row
    left this user's configuration — true whether or not a warm stand is holding another
    box at the same address and port.
    """
    return sum(1 for content in _entries(archive).values() if marker in content.decode())


# Every panel action is htmx's, and nothing answers a header-less POST with a redirect
# any more (M9.6).
HTMX = {"HX-Request": "true"}


async def remove_from_the_panel(operator, node_id: str, transport: str) -> str:
    """Remove one transport the way the owner does: the button, then the confirmation.

    Both URLs are READ off the rendered markup rather than written down here, which is
    this suite's standard since M9.6: the operator's route to this action is a button, and
    a scenario that posted to a remembered URL would keep passing while the button opened
    a dialog that removed nothing.
    """
    dialog = await operator.get(f"/panel/nodes/{node_id}/transports")
    assert dialog.status_code == 200, dialog.text
    button = re.search(
        rf'data-transport="{re.escape(transport)}"[^>]*?'
        r'hx-get="(/panel/transports/[^"]+/remove)"',
        dialog.text,
        re.S,
    )
    assert button, f"no remove button for {transport} on the Nodes screen"

    confirmation = await operator.get(button.group(1))
    assert confirmation.status_code == 200, confirmation.text
    posts_to = re.search(r'hx-post="(/panel/transports/[^"]+/remove)"', confirmation.text)
    assert posts_to, "the remove confirmation confirms nothing"

    removed = await operator.post(posts_to.group(1), headers=HTMX)
    assert removed.status_code == 200, removed.text
    # A fragment, never a document — the control rulebook's HTMX trap.
    assert "<html" not in removed.text.lower()
    return removed.text


async def test_a_user_facing_transport_is_removed_and_its_port_comes_back(
    operator, client, unique: str
) -> None:
    """The milestone's second done-when, end to end, from the only surface there is.

    Three claims, and the last one is the one the field needed: what a user receives loses
    it, the material minted for them goes with the row rather than being orphaned, and the
    PORT is free again — so the box that was locked out of the hop it was supposed to
    carry can be typed back into a working shape without touching the database.
    """
    port = removal_port(unique)
    marker = f"{REMOVAL_ADDRESS}:{port}"
    node_id = await a_node(
        operator, f"removal-{unique}", REMOVAL_ADDRESS, f"Removeland-{unique}"
    )
    offered = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": RUNBOOK_TRANSPORT,
            "pool_size": POOL_SIZE,
            "params": side("10.65.0.1/20", "10.65.0.2/20", port),
        },
    )
    assert offered.status_code == 201, offered.text
    assert (
        await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
    ).status_code == 200

    user_id = (
        await operator.post("/api/users", json={"nickname": f"removed-{unique}"})
    ).json()["id"]
    token = (
        await operator.get(f"/api/users/{user_id}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    archive = await client.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert archive.status_code == 200, archive.text
    before = endpoints_carrying(archive.content, marker)
    assert before >= 1, (
        "the fixture never reached this user, so its absence below would prove nothing"
    )

    toast = await remove_from_the_panel(operator, node_id, RUNBOOK_TRANSPORT)

    # What the operator is told, and the half of it they are most likely to get wrong:
    # the row is gone from this panel and the HOST is still serving it. This node's only
    # transport has just gone, so the sentence is the one that does NOT end on an apply —
    # since M18.1 an apply with nothing enabled is refused, and sending the operator to it
    # here would be sending them to the one button that cannot help.
    assert "removed from" in toast, toast
    assert "the node keeps serving it" in toast, toast
    assert "apply it to stop that" not in toast, toast

    after = await client.get(f"/sub/{token}", params={"format": "client-config-file"})
    assert after.status_code == 200, after.text
    assert endpoints_carrying(after.content, marker) == before - 1, (
        "a removed transport is still in a user's configuration"
    )

    # And the port it held is free on that node — the whole reason removal exists.
    reused = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": RUNBOOK_TRANSPORT,
            "pool_size": POOL_SIZE,
            "params": side("10.66.0.1/20", "10.66.0.2/20", port),
        },
    )
    assert reused.status_code == 201, reused.text
    # Under the plain name, too: nothing is left holding the first instance's name.
    assert reused.json()["config_name"] == RUNBOOK_TRANSPORT
