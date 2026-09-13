"""Offering a protocol to friends, and moving a node's state — backlog item 29.

WHAT: the branchy half of the two operations item 29 added — ``set_transport_enabled``
      (what a withdrawal does to a subscription, what re-offering grants, what is
      refused) and the panel's own node-state route.
WHY:  charter criterion 3 is "a transport is enabled from the panel and arrives in
      every friend's subscription at the next refresh". Until this operation existed,
      ``NodeTransport.enabled`` was written ``True`` at creation and changed by no
      route, so only the positive half of the criterion could be stated. A criterion
      whose negative half is inexpressible is not a criterion — it says "enabling
      added something", not "enabling controls what friends receive".
HOW:  the acceptance scenarios for criterion 3 live in
      ``tests/e2e/control/test_a_replacement_node_and_a_protocol_from_the_panel.py``,
      driven through the panel against the booted stack. This file covers what a
      scenario cannot see: the refusal on a hop end, and that a re-offer grants the
      friends who arrived while the transport was withdrawn.
"""

import base64

import pytest
from sqlalchemy import select

from control.app.errors import Conflict
from control.app.models import Credential, NodeState, NodeTransport
from control.app.services import nodes

# Helpers are local rather than imported from a sibling test module. Under
# ``--import-mode=importlib`` (see pyproject.toml) and with no ``__init__.py`` under
# tests/, a top-level ``from tests.control.test_relay import ...`` imports that module
# a SECOND time under a different name — and the duplicate breaks an unrelated
# scenario in another file, which is a diagnosis nobody should have to repeat.

# A hop's operator-supplied parameters. Obfuscation knobs included because the
# transport requires them; the values are arbitrary and distinct.
HOP_PARAMS: dict[str, object] = {
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


async def create_node(client, *, name: str, address: str, country: str) -> str:
    response = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": country},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def one_node_one_friend(client, session, reality_params) -> tuple[str, str]:
    """A serving node with one transport, and one friend holding a token."""
    node_id = await create_node(
        client, name="leaf-1", address="192.0.2.10", country="Netherlands"
    )
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend_id = (await client.post("/api/friends", json={"nickname": "kolya"})).json()["id"]
    url = (await client.get(f"/api/friends/{friend_id}/subscription")).json()["url"]
    return enabled.json()["id"], url.rsplit("/", 1)[-1]


async def lines(anonymous, token: str) -> list[str]:
    """The friend's subscription, decoded, exactly as their client reads it."""
    response = await anonymous.get(f"/sub/{token}")
    assert response.status_code == 200, response.text
    return base64.b64decode(response.text).decode().splitlines()


async def test_withdrawing_empties_the_subscription_and_offering_refills_it(
    client, anonymous, session, reality_params
) -> None:
    """The round trip, asserted on the friend's document rather than on the row.

    Asserting on ``enabled`` would prove only that a boolean was written. What the
    criterion promises is about the document a friend's client fetches from a URL
    that never changed, so that is what is read here — before, after, and after again.
    """
    node_transport_id, token = await one_node_one_friend(client, session, reality_params)
    assert len(await lines(anonymous, token)) == 1

    withdrawn = await client.post(
        f"/api/transports/{node_transport_id}/state", json={"enabled": False}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["enabled"] is False
    assert await lines(anonymous, token) == [], "a withdrawn transport is still delivered"

    # Still a 200 with an empty document rather than a 404: an empty offer is not a
    # revoked link, and a client that got a 404 would report the friend's access as
    # broken instead of momentarily empty.
    assert (await anonymous.get(f"/sub/{token}")).status_code == 200

    offered = await client.post(
        f"/api/transports/{node_transport_id}/state", json={"enabled": True}
    )
    assert offered.status_code == 200, offered.text
    assert len(await lines(anonymous, token)) == 1


async def test_a_friend_who_arrived_while_it_was_withdrawn_gets_it_on_the_re_offer(
    client, anonymous, session, reality_params
) -> None:
    """The bug this would otherwise have: the offer comes back for everyone but them.

    A friend created while the only transport is withdrawn has no credential on it —
    there was nothing serving to grant. If re-offering did not grant, their
    subscription would stay empty forever while every older friend's refilled, and
    the operator would see a working fleet.
    """
    node_transport_id, _ = await one_node_one_friend(client, session, reality_params)
    await client.post(f"/api/transports/{node_transport_id}/state", json={"enabled": False})

    latecomer = (await client.post("/api/friends", json={"nickname": "masha"})).json()["id"]
    token = (
        await client.get(f"/api/friends/{latecomer}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]
    assert await lines(anonymous, token) == []

    await client.post(f"/api/transports/{node_transport_id}/state", json={"enabled": True})
    assert len(await lines(anonymous, token)) == 1


async def test_setting_the_value_it_already_has_grants_nothing_new(
    client, session, reality_params
) -> None:
    """Idempotent. A retried click is not an event."""
    node_transport_id, _ = await one_node_one_friend(client, session, reality_params)

    before = len((await session.execute(select(Credential))).scalars().all())
    assert (
        await client.post(
            f"/api/transports/{node_transport_id}/state", json={"enabled": True}
        )
    ).status_code == 200
    session.expire_all()
    after = len((await session.execute(select(Credential))).scalars().all())
    assert after == before, "a no-op re-offer minted material"


async def test_withdrawing_one_end_of_a_hop_is_refused(client, session) -> None:
    """Half a tunnel is the failure this refusal exists for.

    A hop end is not an offer to friends, so switching it off is not a delivery
    change: it is a tunnel that stops completing while both ends still look
    configured, and nothing in the panel would say so.
    """
    entry_id = await create_node(
        client, name="entry-ru", address="192.0.2.20", country="Russia"
    )
    leaf_id = await create_node(
        client, name="leaf-nl", address="192.0.2.10", country="Netherlands"
    )
    hop = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": "amneziawg",
            "entry_params": {
                **HOP_PARAMS,
                "tunnel_address": "10.44.0.1/24",
                "peer_tunnel_address": "10.44.0.2/24",
            },
            "leaf_params": {
                **HOP_PARAMS,
                "tunnel_address": "10.44.0.2/24",
                "peer_tunnel_address": "10.44.0.1/24",
            },
        },
    )
    assert hop.status_code == 201, hop.text
    entry_end = hop.json()["entry"]["id"]

    with pytest.raises(Conflict) as refused:
        await nodes.set_transport_enabled(session, node_transport_id=entry_end, enabled=False)
    assert "hop" in str(refused.value)

    # And the row is untouched — a refusal that had already written would be worse
    # than one that had not been made.
    session.expire_all()
    row = await session.get(NodeTransport, entry_end)
    assert row.enabled is True


async def test_an_unknown_node_transport_is_a_404(client) -> None:
    response = await client.post(
        "/api/transports/00000000-0000-0000-0000-000000000000/state",
        json={"enabled": False},
    )
    assert response.status_code == 404


async def test_the_panel_returns_a_fragment_not_a_page(
    client, session, reality_params
) -> None:
    """The rulebook's HTMX trap: a full document here nests <html> in the panel.

    The route took this path back in M9.6 from the pre-redesign page's one toggle; it is
    two routes now, the destructive one confirming first. Same claim, same subject.
    """
    node_transport_id, _ = await one_node_one_friend(client, session, reality_params)

    response = await client.post(
        f"/panel/transports/{node_transport_id}/withdraw",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200, response.text
    assert "<html" not in response.text.lower()
    # The operator is told what a withdrawal does NOT do. Silence here would let them
    # read it as a revocation, and the node is still serving what it was given. This node
    # has one transport, so it is the form that does not end on an apply: since M18.1 an
    # apply with nothing enabled is refused, and the two forms are pinned against each
    # other in tests/control/test_the_console.py.
    assert "the node keeps serving it" in response.text


# --- the panel's node-state route ---------------------------------------------
#
# The API has had this since item 17. The panel had not, and both criteria 2 and 3 are
# phrased "from the panel" — so until now the last step of raising a replacement node
# was the one step the owner could not take on a screen.

async def test_the_panel_can_put_a_node_into_service(client, session, reality_params) -> None:
    """Criterion 2's last step, on the screen the criterion is written about."""
    node_id = await create_node(
        client, name="leaf-1", address="192.0.2.10", country="Netherlands"
    )
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )

    response = await client.post(
        f"/panel/nodes/{node_id}/state",
        data={"state": "active"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200, response.text
    assert "<html" not in response.text.lower()
    assert "active" in response.text

    assert (await client.get(f"/api/nodes/{node_id}")).json()["state"] == "active"


async def test_an_illegal_transition_from_the_panel_says_what_is_allowed(client) -> None:
    """A refusal an operator can act on, rather than a red box.

    ``retired -> active`` is the transition that matters: a retired node's host is
    usually gone, and re-activating the record would put an address that may now belong
    to a stranger back into every friend's subscription.
    """
    node_id = await create_node(
        client, name="leaf-1", address="192.0.2.10", country="Netherlands"
    )
    assert (
        await client.post(
            f"/panel/nodes/{node_id}/state",
            data={"state": "retired"},
            headers={"HX-Request": "true"},
        )
    ).status_code == 200

    response = await client.post(
        f"/panel/nodes/{node_id}/state",
        data={"state": "active"},
        headers={"HX-Request": "true"},
    )
    # 422 with the dialog back, the console's one swappable refusal status, and the
    # sentence under the control it is about rather than in a banner.
    assert response.status_code == 422, response.status_code
    assert "cannot go from" in response.text


async def test_a_state_that_does_not_exist_is_refused_beside_the_ones_that_do(
    client,
) -> None:
    """A typed form value, so the answer must not be a traceback or a bare 422 body.

    The console does NOT echo the word that arrived and does not list the vocabulary in
    the sentence — that changed with M9.5 deliberately, because the dialog this refusal
    re-renders already carries the states this node may actually move to, each with what
    it does to a user's link. So the claim is unchanged in substance and stronger in
    shape: the operator is told which states exist FOR THIS NODE, not which exist.
    """
    node_id = await create_node(
        client, name="leaf-1", address="192.0.2.10", country="Netherlands"
    )
    response = await client.post(
        f"/panel/nodes/{node_id}/state",
        data={"state": "hibernating"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 422, response.status_code
    assert "hibernating" not in response.text, "the panel echoed a typed value back"
    assert 'id="node-state-error"' in response.text
    assert "active" in response.text and "retired" in response.text
