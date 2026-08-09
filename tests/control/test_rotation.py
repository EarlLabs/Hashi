"""Rotating what gets blocked — backlog items 23 and 24.

WHAT: re-minting a node-transport's key material, and replacing an operator-supplied
      parameter (a Reality decoy being the case that motivates it), through the API and
      through the panel.
WHY:  the charter's job for the owner is "rotate anything that gets blocked, all from
      one admin panel". Two properties make that real rather than nominal, and both are
      asserted here: the new material actually reaches what would be pushed, and the
      friend's subscription URL does NOT change — otherwise every rotation would mean
      thirty friends re-importing a link, which is exactly what the product promises
      never to require.
HOW:  no node is contacted. The nodes here have no SSH key, so the push half fails by
      design, and the honest reporting of "rotated in the database, NOT on the node" is
      itself under test — an operator who is told a rotation succeeded when the node
      still runs the blocked decoy is worse off than one told nothing.

      The boundary, stated plainly: nothing here proves a running daemon started
      accepting the new material. It proves the database changed, that a re-render
      carries the change, and that a failed push is reported as incomplete.
"""

import base64
import json

import pytest
from sqlalchemy import select

from control.app.models import Credential, NodeState, NodeTransport
from control.app.services import apply, nodes, rotation


async def fleet(client, session, reality_params):
    """One active node running Reality, and one friend holding a subscription."""
    node_id = (
        await client.post(
            "/api/nodes",
            json={
                "name": "leaf-nl",
                "address": "192.0.2.10",
                "location_label": "Netherlands",
            },
        )
    ).json()["id"]
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend_id = (
        await client.post("/api/friends", json={"nickname": "kolya"})
    ).json()["id"]
    url = (await client.get(f"/api/friends/{friend_id}/subscription")).json()["url"]

    node_transport_id = (
        await session.execute(select(NodeTransport.id))
    ).scalar_one()
    return node_id, node_transport_id, friend_id, url.rsplit("/", 1)[-1]


async def rendered_server_config(session, node_id: str) -> dict:
    """What an apply would push for this node, through the apply path itself."""
    node = await nodes.get_node(session, node_id)
    configs = await apply.render_for_node(session, node)
    return json.loads(next(iter(configs.values())))


# --- item 23: key rotation ---------------------------------------------------

async def test_rotating_keys_changes_what_would_be_pushed(
    client, session, reality_params
) -> None:
    """The point of the operation: the node's own key material is new.

    Asserted against a re-render rather than against the row, because "the database
    changed" is not the claim — the claim is that the next push carries the change.
    """
    node_id, node_transport_id, _, _ = await fleet(client, session, reality_params)
    before = rendered_server_config(session, node_id)
    before = await before

    await client.post(f"/api/transports/{node_transport_id}/rotate-keys")

    after = await rendered_server_config(session, node_id)
    assert after != before, "a key rotation left the rendered config identical"


async def test_rotating_keys_does_not_change_the_friends_subscription_url(
    client, session, reality_params
) -> None:
    """The property the whole feature exists for.

    If rotation changed the token, "swap a protocol in minutes without a user touching
    their device" would be false, and the operator would avoid rotating — which is the
    real failure, since the thing that does not get rotated is a blocked node.
    """
    _, node_transport_id, friend_id, token = await fleet(
        client, session, reality_params
    )

    await client.post(f"/api/transports/{node_transport_id}/rotate-keys")

    assert (await client.get(f"/sub/{token}")).status_code == 200
    reissued = (
        await client.get(f"/api/friends/{friend_id}/subscription")
    ).json()["url"]
    assert reissued.endswith(token), "rotation moved the friend's subscription URL"


async def test_rotating_keys_hands_the_friend_new_material_at_the_same_url(
    client, session, reality_params
) -> None:
    """Same link, different contents — the two halves of the promise together."""
    _, node_transport_id, _, token = await fleet(client, session, reality_params)
    before = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()

    await client.post(f"/api/transports/{node_transport_id}/rotate-keys")

    after = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    assert after != before, "the friend would re-fetch the same link and get the old key"


async def test_rotating_keys_re_mints_every_friends_credential(
    client, session, reality_params
) -> None:
    """Client material is rotated too, by default.

    A node worth re-keying is a node that may have leaked the credentials it was
    authenticating, so rotating only the server key leaves every friend's identity on
    that node unchanged. This is the assertion that keeps the default honest.
    """
    _, node_transport_id, _, _ = await fleet(client, session, reality_params)
    before = (await session.execute(select(Credential.subject))).scalars().all()
    assert before, "the friend had no credential — the premise failed"

    await client.post(f"/api/transports/{node_transport_id}/rotate-keys")
    session.expire_all()

    after = (await session.execute(select(Credential.subject))).scalars().all()
    assert set(after).isdisjoint(before), "a friend's credential survived a re-key"


async def test_rotation_reports_that_the_node_was_not_updated(
    client, session, reality_params
) -> None:
    """The half that must never be silent.

    These nodes have no SSH key, so the push cannot land. Between the write and a
    successful push the database and the node disagree, and for a decoy rotation that
    means the BLOCKED decoy is still in use. Reporting that as success would be the
    single most expensive lie this panel could tell.
    """
    _, node_transport_id, _, _ = await fleet(client, session, reality_params)

    body = (
        await client.post(f"/api/transports/{node_transport_id}/rotate-keys")
    ).json()

    assert body["complete"] is False
    assert "NOT" in body["summary"] or "could not" in body["summary"]


async def test_rotating_an_unknown_transport_is_a_404(client, session) -> None:
    response = await client.post("/api/transports/does-not-exist/rotate-keys")
    assert response.status_code == 404


# --- item 24: replacing operator-supplied parameters -------------------------

async def test_replacing_a_parameter_reaches_the_rendered_config(
    client, session, reality_params
) -> None:
    """The decoy-rotation case, expressed without naming a decoy in the route."""
    node_id, node_transport_id, _, _ = await fleet(client, session, reality_params)

    response = await client.post(
        f"/api/transports/{node_transport_id}/params",
        json={"params": {"decoy_host": "www.wikipedia.org",
                         "server_names": ["www.wikipedia.org"]}},
    )
    assert response.status_code == 200, response.text
    assert "decoy_host" in response.json()["rotated"]

    config = json.dumps(await rendered_server_config(session, node_id))
    assert "www.wikipedia.org" in config
    assert "www.example.com" not in config


async def test_replacing_a_parameter_preserves_key_material(
    client, session, reality_params
) -> None:
    """Two different operations with two different consequences, kept apart.

    An operator changing a hostname must be able to predict what happens to friends:
    nothing. Silently re-keying here would mean every friend's config is replaced by a
    routine edit.
    """
    _, node_transport_id, _, _ = await fleet(client, session, reality_params)
    before = (
        await session.execute(
            select(NodeTransport.secrets).where(NodeTransport.id == node_transport_id)
        )
    ).scalar_one()

    await client.post(
        f"/api/transports/{node_transport_id}/params",
        json={"params": {"decoy_host": "www.wikipedia.org",
                         "server_names": ["www.wikipedia.org"]}},
    )
    session.expire_all()

    after = (
        await session.execute(
            select(NodeTransport.secrets).where(NodeTransport.id == node_transport_id)
        )
    ).scalar_one()
    assert after == before, "replacing a parameter re-keyed the node"


async def test_an_invalid_replacement_changes_nothing(
    client, session, reality_params
) -> None:
    """Validated before it is written, so a rejected rotation is not a half-rotation."""
    node_id, node_transport_id, _, _ = await fleet(client, session, reality_params)
    before = await rendered_server_config(session, node_id)

    response = await client.post(
        f"/api/transports/{node_transport_id}/params",
        json={"params": {"port": 1}},  # outside the transport's declared range
    )
    assert response.status_code == 400, response.text

    session.expire_all()
    assert await rendered_server_config(session, node_id) == before


async def test_replacing_nothing_is_refused_rather_than_pushed(
    client, session, reality_params
) -> None:
    """A no-op rotation would push a node for no reason and report success for no change."""
    _, node_transport_id, _, _ = await fleet(client, session, reality_params)

    response = await client.post(
        f"/api/transports/{node_transport_id}/params",
        json={"params": {"decoy_host": reality_params["decoy_host"]}},
    )
    assert response.status_code == 400


# --- the same two operations, from the panel (criteria 2 and 3 are "from the panel")

async def test_the_node_page_offers_rotation_for_each_enabled_transport(
    client, session, reality_params
) -> None:
    """The form is built from the transport's own declaration, so it names no protocol."""
    node_id, node_transport_id, _, _ = await fleet(client, session, reality_params)

    page = (await client.get(f"/panel/nodes/{node_id}")).text

    assert f"/panel/transports/{node_transport_id}/rotate-keys" in page
    assert f"/panel/transports/{node_transport_id}/params" in page
    # A field the transport declared, offered without this template knowing it exists.
    assert 'name="decoy_host"' in page


async def test_the_panel_rotates_keys_and_returns_a_fragment(
    client, session, reality_params
) -> None:
    """A fragment, not a document: the control rulebook's trap is a nested <html>."""
    _, node_transport_id, _, token = await fleet(client, session, reality_params)
    before = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()

    response = await client.post(f"/panel/transports/{node_transport_id}/rotate-keys")

    assert response.status_code == 200
    assert "<html" not in response.text.lower()
    after = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    assert after != before


async def test_the_panel_leaves_blank_fields_alone(
    client, session, reality_params
) -> None:
    """Blank means "keep", not "set to empty".

    A rotation form that round-tripped every parameter would rewrite fields the
    operator never looked at — and on this form one of those fields is the port every
    friend is currently connected to.
    """
    node_id, node_transport_id, _, _ = await fleet(client, session, reality_params)

    response = await client.post(
        f"/panel/transports/{node_transport_id}/params",
        data={"decoy_host": "www.wikipedia.org", "server_names": "www.wikipedia.org",
              "port": "", "decoy_port": ""},
    )
    assert response.status_code == 200

    session.expire_all()
    config = json.dumps(await rendered_server_config(session, node_id))
    assert "www.wikipedia.org" in config
    assert str(reality_params["port"]) in config, "a blank box overwrote the port"


async def test_the_panel_reports_a_rejected_rotation_as_a_failure_fragment(
    client, session, reality_params
) -> None:
    """A refusal has to be readable on the page, not a 500 the operator never sees."""
    _, node_transport_id, _, _ = await fleet(client, session, reality_params)

    response = await client.post(
        f"/panel/transports/{node_transport_id}/params", data={"port": "1"}
    )

    assert response.status_code == 200
    assert "bad" in response.text, response.text


@pytest.mark.parametrize(
    "path",
    ["/panel/transports/whatever/rotate-keys", "/panel/transports/whatever/params"],
)
async def test_rotation_from_the_panel_needs_an_operator_session(
    anonymous, path: str
) -> None:
    """Every new panel route is a new way in if its guard was forgotten."""
    response = await anonymous.post(path)
    assert response.status_code in (302, 303, 401, 403), response.status_code


async def test_rotation_service_refuses_a_transport_this_image_does_not_ship(
    client, session, reality_params
) -> None:
    """A node may run a transport a later image dropped; we say so instead of guessing."""
    from control.app.errors import DomainError

    _, node_transport_id, _, _ = await fleet(client, session, reality_params)
    node_transport = await session.get(NodeTransport, node_transport_id)
    node_transport.transport_name = "not-installed-here"
    await session.commit()

    with pytest.raises(DomainError):
        await rotation.rotate_keys(session, node_transport_id=node_transport_id)
