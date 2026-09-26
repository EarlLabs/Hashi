"""The operator's whole path: create a node, enable a transport, add a user.

WHAT: the API-level behaviour of backlog items 5, 6, 6a, 7 and 8, against a real
      database.
WHY:  each of these was specified as an acceptance criterion, and this file is where
      the criterion becomes a falsifiable statement rather than a paragraph.
HOW:  real Postgres, real encryption, real key generation, real rendering. Nothing
      stubbed except SSH — no node is contacted here, and any test that needs one says
      so (see ``test_node_operations.py``).
"""

import base64

import pytest

from control.app.crypto import SecretBox
from control.app.models import NodeState


async def create_active_node(client, *, name="leaf-1", country="Netherlands") -> str:
    """Register a node and mark it serving, without touching a real host.

    State is set directly rather than through ``apply`` because applying needs SSH to
    a real machine. That boundary is deliberate and named: these tests prove the
    database and rendering behaviour, never that a tunnel carries traffic.
    """
    response = await client.post(
        "/api/nodes",
        json={"name": name, "address": "192.0.2.10", "location_label": country},
    )
    assert response.status_code == 201, response.text
    node_id = response.json()["id"]
    assert response.json()["state"] == NodeState.DRAFT, (
        "a new node must not be serving before it is configured"
    )
    return node_id


async def activate(session, node_id: str) -> None:
    from control.app.services import nodes

    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)


# --- auth (item 5) -----------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/api/nodes", "/api/users", "/api/transports"],
)
async def test_api_is_closed_to_anyone_without_a_session(anonymous, path: str) -> None:
    """The operator API answers 401 to a stranger, not data.

    Parametrised over several routes on purpose: the guard is a ROUTER-level
    dependency, and this is what proves the router carries it rather than each
    handler having remembered to.
    """
    response = await anonymous.get(path)
    assert response.status_code == 401
    body = response.text.lower()
    for leak in ("node", "user", "postgres", "traceback"):
        assert leak not in body, f"a 401 leaked {leak!r}: {response.text[:200]}"


async def test_panel_sends_a_stranger_to_the_login_page(anonymous) -> None:
    """A browser gets a redirect, not a JSON 401 it cannot render."""
    response = await anonymous.get("/panel/")
    assert response.status_code == 303
    assert response.headers["location"] == "/panel/login"


async def test_wrong_password_is_refused(anonymous, settings) -> None:
    response = await anonymous.post(
        "/panel/login", data={"username": settings.operator_username, "password": "wrong"}
    )
    assert response.status_code == 401


async def test_wrong_username_is_refused_the_same_way(anonymous) -> None:
    """Identical response to a wrong password, so neither confirms the other."""
    response = await anonymous.post(
        "/panel/login", data={"username": "someone-else", "password": "test-operator-password"}
    )
    assert response.status_code == 401


async def test_logged_in_operator_reaches_the_panel(client) -> None:
    response = await client.get("/panel/")
    assert response.status_code == 200
    assert "hashi" in response.text


# --- transports are discovered, not listed (item 7, criterion 4) -------------

async def test_transports_endpoint_reports_what_the_image_ships(client) -> None:
    """The panel builds its form from this, so a new protocol appears on its own."""
    response = await client.get("/api/transports")
    assert response.status_code == 200

    listed = {entry["name"]: entry for entry in response.json()}
    assert listed, "no transports discovered"

    for entry in listed.values():
        # The operator is asked only for what we cannot generate. If a keypair field
        # showed up here, the panel would be asking the owner to type a private key.
        assert "private_key" not in entry["operator_params"]
        assert "public_key" not in entry["operator_params"]
        assert entry["port_range"][0] <= entry["port_range"][1]


# --- enabling a transport mints its material (items 6, 6a) -------------------

async def test_enabling_a_transport_generates_the_material_it_declared(
    client, session, reality_params
) -> None:
    """The operator supplies no keys; the control plane mints what the transport asked for."""
    node_id = await create_active_node(client)

    response = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # The public half is in plain parameters, because the CLIENT renderer needs it.
    assert body["params"]["public_key"], "no public key was generated"
    assert body["params"]["short_id"], "no short id was generated"

    # The private half must NOT be in an API response at any point.
    assert "private_key" not in body["params"], "a node's private key reached the API"
    assert "secrets" not in body, "the encrypted secrets column is exposed by the API"


async def test_node_secrets_are_encrypted_at_rest(client, session, reality_params) -> None:
    """Core invariants §3, asserted against the bytes actually in the column.

    Reads the raw column with a driver-level query, bypassing the model's decrypting
    type. Checking through the ORM would only prove that decryption works — the
    question here is what a stolen dump contains.
    """
    node_id = await create_active_node(client)
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )

    from sqlalchemy import text

    raw = (
        await session.execute(text("SELECT secrets FROM node_transports LIMIT 1"))
    ).scalar_one()

    assert raw, "no secrets stored at all"
    # Fernet ciphertext is base64 beginning with a version byte of 0x80 → "gAAAAA".
    assert raw.startswith("gAAAAA"), f"secrets column does not look encrypted: {raw[:40]!r}"
    assert "private_key" not in raw, "the plaintext key name is visible in the column"

    # And it is genuinely the right plaintext underneath.
    import json

    from tests.control.conftest import TEST_SECRET_KEY  # noqa: PLC0415

    box = SecretBox(TEST_SECRET_KEY)
    assert "private_key" in json.loads(box.decrypt(raw))


async def test_a_wrong_key_cannot_read_stored_secrets(client, reality_params) -> None:
    """A dump is useless without HASHI_SECRET_KEY — the point of encrypting here."""
    from control.app.crypto import SecretUnreadable

    box = SecretBox("test-secret-key-not-real-000000000000000000000000")
    other = SecretBox("a-completely-different-key-00000000000000000000000")
    ciphertext = box.encrypt("a node private key")

    with pytest.raises(SecretUnreadable):
        other.decrypt(ciphertext)


async def test_a_second_instance_of_one_transport_is_refused_only_over_the_port(
    client, reality_params
) -> None:
    """What a node refuses is two transports on one port — not two of one transport.

    M15. The rule used to be one row per ``(node, transport_name)``, and it made the
    runbook's own advice impossible to follow: AmneziaWG is mandated for the entry→leaf
    hop and recommended for users on the same box. The refusal moved onto what
    actually collides — the data planes run with ``network_mode: host``, so one port is
    one bind — and the answer is still a 409, so no API caller's envelope moved.

    Both halves are asserted here because either alone is satisfied by a mistake: the
    refusal alone by the old rule, and the acceptance alone by no rule at all.
    """
    node_id = await create_active_node(client)
    payload = {"transport_name": "vless-reality", "params": reality_params}

    assert (await client.post(f"/api/nodes/{node_id}/transports", json=payload)).status_code == 201

    same_port = await client.post(f"/api/nodes/{node_id}/transports", json=payload)
    assert same_port.status_code == 409
    assert same_port.json()["error"]["code"] == "conflict"

    elsewhere = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": "vless-reality",
            "params": {**reality_params, "port": reality_params["port"] + 1},
        },
    )
    assert elsewhere.status_code == 201, elsewhere.text


async def test_an_unknown_transport_is_refused(client) -> None:
    node_id = await create_active_node(client)
    response = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "no-such-protocol", "params": {}},
    )
    assert response.status_code == 404


async def test_invalid_parameters_are_refused_by_the_transports_own_model(
    client, reality_params
) -> None:
    """Validation belongs to the transport, and it reaches the API boundary.

    A port outside the declared range is the clearest case: `control` does not know
    what range this protocol allows, so a rejection here proves the transport's own
    model ran.
    """
    node_id = await create_active_node(client)
    response = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": {**reality_params, "port": 80}},
    )
    assert response.status_code >= 400
    assert "traceback" not in response.text.lower()


# --- users and subscriptions (items 7, 8; criterion 5) ---------------------

async def test_a_new_user_gets_a_subscription_covering_every_serving_node(
    client, session, reality_params
) -> None:
    """Charter criterion 5: onboarding is one link, and it already has the fleet in it."""
    node_id = await create_active_node(client)
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await activate(session, node_id)

    user = await client.post("/api/users", json={"nickname": "kolya"})
    assert user.status_code == 201, user.text
    user_id = user.json()["id"]

    issued = await client.get(f"/api/users/{user_id}/subscription")
    assert issued.status_code == 200
    url = issued.json()["url"]
    assert "/sub/" in url

    # Fetched the way a user's client fetches it: no session, just the token.
    token = url.rsplit("/", 1)[-1]
    delivered = await client.get(f"/sub/{token}")
    assert delivered.status_code == 200

    document = base64.b64decode(delivered.text).decode()
    assert document.strip(), "the subscription is empty"
    assert document.startswith("vless://")
    # The country label is what a user picks an exit by, and it must be in the
    # fragment the client displays.
    assert "Netherlands" in document


async def test_a_second_transport_appears_in_the_subscription_with_no_code_change(
    client, session, reality_params, ws_params
) -> None:
    """Charter criterion 3, stated as arithmetic.

    Two transports on one node produce two entries. The subscription renderer was not
    modified to make the second one work — it does not know either protocol's name.
    """
    node_id = await create_active_node(client)
    for name, params in (("vless-reality", reality_params), ("vless-ws-tls", ws_params)):
        response = await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": name, "params": params},
        )
        assert response.status_code == 201, response.text
    await activate(session, node_id)

    user_id = (await client.post("/api/users", json={"nickname": "kolya"})).json()["id"]
    url = (await client.get(f"/api/users/{user_id}/subscription")).json()["url"]
    document = base64.b64decode(
        (await client.get(f"/sub/{url.rsplit('/', 1)[-1]}")).text
    ).decode()

    lines = document.splitlines()
    assert len(lines) == 2, f"expected one entry per transport, got: {lines}"
    # Distinguishable by their transport-specific query, which only the transports
    # know how to write.
    assert any("security=reality" in line for line in lines)
    assert any("type=ws" in line for line in lines)


async def test_a_user_added_before_a_node_still_reaches_it(
    client, session, reality_params
) -> None:
    """Charter criterion 2's user-facing half: a replacement node needs no user action.

    The user existed first, the node came later, and their EXISTING subscription URL
    resolves to it — nothing was re-issued and nothing was re-imported.
    """
    user_id = (await client.post("/api/users", json={"nickname": "kolya"})).json()["id"]
    url = (await client.get(f"/api/users/{user_id}/subscription")).json()["url"]
    token = url.rsplit("/", 1)[-1]

    # Nothing to reach yet.
    empty = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    assert empty == ""

    node_id = await create_active_node(client, name="leaf-new", country="Iceland")
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await activate(session, node_id)

    # The SAME url, unchanged, now carries the new node.
    document = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    assert "Iceland" in document, "the user's existing link did not pick up the new node"


async def test_a_draft_or_degraded_node_reaches_nobody(
    client, session, reality_params
) -> None:
    """Being routed onto a half-configured node produces a bug report about the client."""
    from control.app.services import nodes

    node_id = await create_active_node(client)
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await activate(session, node_id)

    user_id = (await client.post("/api/users", json={"nickname": "kolya"})).json()["id"]
    url = (await client.get(f"/api/users/{user_id}/subscription")).json()["url"]
    token = url.rsplit("/", 1)[-1]

    assert base64.b64decode((await client.get(f"/sub/{token}")).text).decode().strip()

    await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="test"
    )
    after = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    assert after == "", "a degraded node was still offered to a user"


async def test_two_users_never_share_an_entry(client, session, reality_params) -> None:
    """Shared credentials would make individual revocation impossible."""
    node_id = await create_active_node(client)
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await activate(session, node_id)

    documents = []
    for nickname in ("kolya", "masha"):
        user_id = (await client.post("/api/users", json={"nickname": nickname})).json()["id"]
        url = (await client.get(f"/api/users/{user_id}/subscription")).json()["url"]
        documents.append(
            base64.b64decode((await client.get(f"/sub/{url.rsplit('/', 1)[-1]}")).text).decode()
        )

    assert documents[0] != documents[1]
    assert documents[0].strip() and documents[1].strip()


async def test_an_unknown_token_is_a_404_that_says_nothing(client) -> None:
    """Unknown and revoked are indistinguishable — a 403 would confirm existence."""
    response = await client.get("/sub/" + "z" * 43)
    assert response.status_code == 404
    assert response.text == ""


async def test_the_delivery_response_is_never_cacheable(
    client, session, reality_params
) -> None:
    """The body is a bearer credential; a cached copy is a leaked one."""
    node_id = await create_active_node(client)
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await activate(session, node_id)
    user_id = (await client.post("/api/users", json={"nickname": "kolya"})).json()["id"]
    url = (await client.get(f"/api/users/{user_id}/subscription")).json()["url"]

    response = await client.get(f"/sub/{url.rsplit('/', 1)[-1]}")
    assert "no-store" in response.headers["cache-control"]


async def test_a_duplicate_nickname_is_refused(client) -> None:
    """Revoking "the right one" must be unambiguous at the moment it matters."""
    assert (await client.post("/api/users", json={"nickname": "kolya"})).status_code == 201
    assert (await client.post("/api/users", json={"nickname": "kolya"})).status_code == 409
