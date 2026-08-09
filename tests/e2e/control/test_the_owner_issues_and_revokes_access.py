"""The product, end to end: the owner builds a fleet and a friend gets a link.

WHAT: one scenario that walks the whole main path over real HTTP against the booted
      stack — log in, add a node, enable a protocol, add a friend, fetch the
      subscription exactly as their client would, add a second protocol, and revoke.
WHY:  every step of this exists in a unit test somewhere. What no unit test can say is
      that the steps compose through the real application, the real database and the
      real delivery endpoint — which is the difference between "the services work" and
      "the owner can issue access". Charter criteria 3, 5 (the half that is a link a
      client can parse) and 6 are what this walks.
HOW:  through the PANEL where the criterion says "from the panel", and through the
      delivery endpoint as an anonymous client for the subscription itself. Names are
      unique per run so a re-run against a warm stack cannot collide with itself.

Boundary, stated plainly: real control, postgres, caddy. NO node is contacted and no
tunnel exists, so nothing here proves traffic flows — it proves the control plane
issues, changes and withdraws access. Charter criterion 1 is not touched by this file.
"""

import base64
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}


@pytest.fixture
def unique() -> str:
    """A per-run suffix, so a second run against a warm stack does not collide."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    """A client holding a real operator session, obtained through the login form."""
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, (
        f"the operator could not log in ({response.status_code}) — check "
        "deploy/e2e.env against deploy/docker-compose.e2e.yml"
    )
    return client


def reality_params(port: int) -> dict:
    """Only what an operator types. Reserved names (RFC 2606), never a real decoy."""
    return {
        "port": port,
        "decoy_host": "www.example.com",
        "decoy_port": 443,
        "server_names": ["www.example.com"],
    }


def ws_params(port: int) -> dict:
    return {
        "port": port,
        "server_name": "front.example.com",
        "certificate_path": "/etc/hashi/certs/fullchain.pem",
        "certificate_key_path": "/etc/hashi/certs/privkey.pem",
    }


async def make_serving_node(operator, unique: str, *, port: int) -> str:
    """A node with one protocol enabled, moved into the only state friends can see."""
    node = await operator.post(
        "/api/nodes",
        json={
            "name": f"leaf-{unique}",
            "address": "192.0.2.10",
            "location_label": f"Testland-{unique}",
        },
    )
    assert node.status_code == 201, node.text
    node_id = node.json()["id"]

    enabled = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params(port)},
    )
    assert enabled.status_code == 201, enabled.text

    active = await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
    assert active.status_code == 200, active.text
    return node_id


def entries_in(document: str, unique: str | None = None) -> list[str]:
    """A subscription as a client reads it: base64 of one entry per line.

    Filtered to one run's own nodes when ``unique`` is given. The e2e database is
    shared by every scenario in a run, so an absolute count would assert on whatever
    else happened to be in the fleet — a test that fails when a NEW scenario is added
    beside it teaches nothing.
    """
    lines = [line for line in base64.b64decode(document).decode().splitlines() if line]
    return [line for line in lines if unique is None or unique in line]


async def test_the_whole_path_from_an_empty_fleet_to_a_revoked_friend(
    operator, client, unique: str
) -> None:
    """One scenario, in the order the owner actually performs it."""
    # --- the owner adds a node and a protocol, from the panel -----------------
    node_id = await make_serving_node(operator, unique, port=8443)

    page = (await operator.get("/panel/")).text
    assert f"leaf-{unique}" in page, "a node the owner added is not on their screen"

    # --- a friend, and the one artefact they ever hold ------------------------
    friend = await operator.post("/api/friends", json={"nickname": f"kolya-{unique}"})
    assert friend.status_code == 201, friend.text
    friend_id = friend.json()["id"]

    issued = await operator.get(f"/api/friends/{friend_id}/subscription")
    assert issued.status_code == 200, issued.text
    url = issued.json()["url"]
    token = url.rsplit("/", 1)[-1]

    # Fetched with NO session: the token in the path is the entire credential, which
    # is what makes the link usable by a standard client with nothing configured.
    delivered = await client.get(f"/sub/{token}")
    assert delivered.status_code == 200, delivered.text
    entries = entries_in(delivered.text, unique)
    assert len(entries) == 1, entries
    assert entries[0].startswith("vless://"), entries[0]
    # The label the client shows carries the operator's country wording, not a geo
    # lookup — "pick an exit country" has to mean what the owner wrote.
    assert unique in entries[0]

    # --- a second protocol reaches them with no action on their part ----------
    second = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-ws-tls", "params": ws_params(8444)},
    )
    assert second.status_code == 201, second.text

    refetched = await client.get(f"/sub/{token}")
    assert len(entries_in(refetched.text, unique)) == 2, (
        "enabling a protocol did not reach an existing friend's SAME link — this is "
        "the promise that makes a rotation invisible to them"
    )

    # --- revocation is total -------------------------------------------------
    revoked = await operator.post(f"/api/friends/{friend_id}/revoke")
    assert revoked.status_code == 200, revoked.text

    gone = await client.get(f"/sub/{token}")
    # 404 rather than an empty 200: an empty document is a valid subscription meaning
    # "no nodes right now", and a client keeps its old configuration for that.
    assert gone.status_code == 404, gone.text


async def test_a_draft_node_reaches_nobody(operator, client, unique: str) -> None:
    """The state filter, proven through the delivery endpoint rather than a query.

    A node is a record before it is a working host. If drafts leaked into
    subscriptions, friends would be routed onto a host that has never been configured
    and would report a broken client.
    """
    await make_serving_node(operator, unique, port=8445)

    draft = await operator.post(
        "/api/nodes",
        json={
            "name": f"draft-{unique}",
            "address": "192.0.2.99",
            "location_label": f"Nowhere-{unique}",
        },
    )
    await operator.post(
        f"/api/nodes/{draft.json()['id']}/transports",
        json={"transport_name": "vless-reality", "params": reality_params(8446)},
    )

    friend = await operator.post("/api/friends", json={"nickname": f"masha-{unique}"})
    token = (
        await operator.get(f"/api/friends/{friend.json()['id']}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    entries = entries_in((await client.get(f"/sub/{token}")).text, unique)
    assert not any(f"Nowhere-{unique}" in entry for entry in entries), entries


async def test_an_unknown_token_is_a_plain_404(client) -> None:
    """No hint about whether a token ever existed, and no body worth probing."""
    response = await client.get(f"/sub/{uuid.uuid4().hex}")
    assert response.status_code == 404
    assert "revoked" not in response.text.lower()
