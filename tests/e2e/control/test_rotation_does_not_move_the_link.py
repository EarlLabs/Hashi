"""Rotating what got blocked, without anyone re-importing anything.

WHAT: rotating a node-transport's key material and replacing an operator-supplied
      parameter, through the panel, against the booted stack.
WHY:  "rotate anything that gets blocked, all from one admin panel" is the owner's job
      in the charter, and it is only worth anything if a rotation is invisible to the
      thirty people holding a link. The two halves are asserted together here because
      they are only true together: the URL must not move, and what it serves must
      change.
HOW:  the friend's subscription is fetched anonymously before and after, exactly as
      their client would.

Boundary: real control + postgres. No node is contacted, so every rotation here reports
INCOMPLETE — the database changed and the node did not — and that reporting is itself
asserted, because an operator told a rotation succeeded when the blocked decoy is still
running is worse off than one told nothing.
"""

import base64
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


async def fleet(operator, unique: str, port: int):
    """A serving node, one friend, and the friend's token."""
    node_id = (await operator.post(
        "/api/nodes",
        json={"name": f"leaf-{unique}", "address": "192.0.2.10",
              "location_label": f"Testland-{unique}"},
    )).json()["id"]
    enabled = await operator.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": "vless-reality",
            "params": {
                "port": port,
                "decoy_host": "www.example.com",
                "decoy_port": 443,
                "server_names": ["www.example.com"],
            },
        },
    )
    assert enabled.status_code == 201, enabled.text
    await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})

    friend_id = (await operator.post(
        "/api/friends", json={"nickname": f"kolya-{unique}"}
    )).json()["id"]
    token = (await operator.get(f"/api/friends/{friend_id}/subscription")).json()[
        "url"
    ].rsplit("/", 1)[-1]
    return node_id, enabled.json()["id"], token


async def mine(client, token: str, unique: str) -> list[str]:
    """This run's own entries in a subscription.

    Every scenario in a run shares one fleet, so an assertion about "the subscription"
    has to be an assertion about the lines this test's node produced.
    """
    lines = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    return [line for line in lines.splitlines() if unique in line]


async def test_a_key_rotation_changes_the_config_behind_the_same_link(
    operator, client, unique: str
) -> None:
    """Same URL, different material — the whole point of the operation."""
    node_id, node_transport_id, token = await fleet(operator, unique, 8447)
    before = await mine(client, token, unique)
    assert len(before) == 1, before

    rotated = await operator.post(f"/panel/transports/{node_transport_id}/rotate-keys")
    assert rotated.status_code == 200, rotated.text
    # A fragment, not a document: a full page here nests <html> inside the panel.
    assert "<html" not in rotated.text.lower()

    # The push could not land (no reachable node), so the node is now DEGRADED and has
    # correctly dropped out of every subscription. Put it back into service before
    # asserting on what friends receive — otherwise "the document changed" would pass
    # for the wrong reason: it changed because the node disappeared from it.
    assert (await operator.post(
        f"/api/nodes/{node_id}/state", json={"state": "active"}
    )).status_code == 200

    after = await mine(client, token, unique)
    assert len(after) == 1, after
    assert after != before, "the friend would re-fetch their link and get the old key"
    assert (await client.get(f"/sub/{token}")).status_code == 200


async def test_replacing_a_blocked_decoy_reaches_the_friends_entry(
    operator, client, unique: str
) -> None:
    """Item 24's real case, driven the way the owner would drive it."""
    node_id, node_transport_id, token = await fleet(operator, unique, 8448)

    replaced = await operator.post(
        f"/panel/transports/{node_transport_id}/params",
        data={"decoy_host": "www.wikipedia.org", "server_names": "www.wikipedia.org"},
    )
    assert replaced.status_code == 200, replaced.text

    # Same as above: the unreachable node was marked degraded by the failed push, so it
    # is out of every subscription until an operator puts it back.
    await operator.post(f"/api/nodes/{node_id}/state", json={"state": "active"})

    after = await mine(client, token, unique)
    assert len(after) == 1, after
    assert "www.wikipedia.org" in after[0]
    assert "www.example.com" not in after[0]


async def test_a_rotation_that_could_not_reach_the_node_says_so(
    operator, unique: str
) -> None:
    """The failure that must never be reported as success.

    These nodes have no SSH key, so the push cannot land. Between the write and a
    successful push, the database and the node disagree — and for a decoy rotation
    that means the blocked decoy is still what the node is running.
    """
    _, node_transport_id, _ = await fleet(operator, unique, 8449)

    outcome = await operator.post(f"/panel/transports/{node_transport_id}/rotate-keys")

    assert outcome.status_code == 200
    assert "bad" in outcome.text, outcome.text
    assert "NOT" in outcome.text or "could not" in outcome.text
