"""Rotating what got blocked, without anyone re-importing anything.

WHAT: rotating a node-transport's key material and replacing an operator-supplied
      parameter, through the panel, against the booted stack.
WHY:  "rotate anything that gets blocked, all from one admin panel" is the owner's job
      in the charter, and it is only worth anything if a rotation is invisible to the
      thirty people holding a link. The two halves are asserted together here because
      they are only true together: the URL must not move, and what it serves must
      change.
HOW:  the user's subscription is fetched anonymously before and after, exactly as
      their client would.

Boundary: real control + postgres. No node is contacted, so every rotation here reports
INCOMPLETE — the database changed and the node did not — and that reporting is itself
asserted, because an operator told a rotation succeeded when the blocked decoy is still
running is worse off than one told nothing.
"""

import base64
import re
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# The console asks with htmx. Both operations moved onto the Keys & configs screen in
# M9.4 and became its only home in M9.6, when the pre-redesign node page they used to
# hang off was deleted along with its two routes.
HTMX = {"HX-Request": "true"}


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


async def fleet(operator, unique: str, port: int):
    """A serving node, one user, and the user's token."""
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

    user_id = (await operator.post(
        "/api/users", json={"nickname": f"kolya-{unique}"}
    )).json()["id"]
    token = (await operator.get(f"/api/users/{user_id}/subscription")).json()[
        "url"
    ].rsplit("/", 1)[-1]
    return node_id, enabled.json()["id"], token


async def button_in(operator, dialog_url: str, *, opened_by: str) -> str:
    """Where the control inside one Keys & configs dialog posts.

    Read off the rendered dialog rather than written down here: the operator's route to
    both of these is a button on the Keys & configs row, and a scenario posting to a
    remembered URL would keep passing while the dialog behind that button submitted
    nowhere. The same standard the withdraw walk holds in the criteria scenario.
    """
    dialog = await operator.get(dialog_url)
    assert dialog.status_code == 200, dialog.text
    found = re.search(r'hx-post="([^"]+)"', dialog.text)
    assert found, f"the dialog behind {opened_by!r} confirms nothing"
    return found.group(1)


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

    rotated = await operator.post(
        await button_in(
            operator, f"/panel/keys/{node_transport_id}/rotate", opened_by="rotate keys"
        ),
        headers=HTMX,
    )
    assert rotated.status_code == 200, rotated.text
    # A fragment, not a document: a full page here nests <html> inside the panel.
    assert "<html" not in rotated.text.lower()

    # The push could not land (no reachable node), so the node is now DEGRADED and has
    # correctly dropped out of every subscription. Put it back into service before
    # asserting on what users receive — otherwise "the document changed" would pass
    # for the wrong reason: it changed because the node disappeared from it.
    assert (await operator.post(
        f"/api/nodes/{node_id}/state", json={"state": "active"}
    )).status_code == 200

    after = await mine(client, token, unique)
    assert len(after) == 1, after
    assert after != before, "the user would re-fetch their link and get the old key"
    assert (await client.get(f"/sub/{token}")).status_code == 200


async def test_replacing_a_blocked_decoy_reaches_the_users_entry(
    operator, client, unique: str
) -> None:
    """Item 24's real case, driven the way the owner would drive it."""
    node_id, node_transport_id, token = await fleet(operator, unique, 8448)

    replaced = await operator.post(
        await button_in(
            operator,
            f"/panel/keys/{node_transport_id}/params",
            opened_by="replace params",
        ),
        data={"decoy_host": "www.wikipedia.org", "server_names": "www.wikipedia.org"},
        headers=HTMX,
    )
    # 200 and not 422: this console refuses a replacement with the dialog re-rendered, so
    # the two cannot be confused for one another.
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

    outcome = await operator.post(
        await button_in(
            operator, f"/panel/keys/{node_transport_id}/rotate", opened_by="rotate keys"
        ),
        headers=HTMX,
    )

    assert outcome.status_code == 200
    # A BANNER, drawn in the danger hue, and not a toast: it has to survive the next
    # click, because until the node is applied the old material is what it is running.
    assert "banner-failure" in outcome.text, outcome.text
    assert "the node could not be updated" in outcome.text, outcome.text
    assert "still running the old material" in outcome.text, outcome.text
