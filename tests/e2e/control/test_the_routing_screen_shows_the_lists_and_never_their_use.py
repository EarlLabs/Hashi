"""The Routing screen, from a started control plane — M34.

WHAT: logs in as the operator on the booted stack, opens the Routing screen, adds the
      narrow list from the suggestions the stack was CONFIGURED with, adds one entry to
      each of the owner's lists, asks the lookup about three destinations, and reads the
      Nodes screen's new switch.
WHY:  the suggestions are configuration (deploy/docker-compose.yml), so the only proof that
      they reach the screen is a control plane started from that file — a value set in
      compose and not passed into the container is the M31.2 failure. The same is true of
      the backup's quiet hour, which the screen states. And the screen must show the
      lists and never their use: the page is read for the words a statistic would use.
HOW:  real HTTP against the e2e stand. Nothing here fetches a list from the internet —
      adding a source fetches nothing by design, which this scenario also asserts — and
      no node is contacted.

Boundary: real control, postgres, caddy. Whether a listed site actually opens from the
entry's address is a field observation on real hosts; nothing here stands in for it.
"""

import re
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# The narrow list's name as deploy/docker-compose.yml configures it. Written out rather
# than imported: nothing in this directory imports the application or reads the compose
# file, so the assertion is about what the started stack says.
NARROW = "itdoginfo-russia-outside"


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.status_code
    return client


def visible(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", markup))


async def test_the_routing_screen_offers_the_configured_lists_and_counts_no_use(operator):
    screen = await operator.get("/panel/routing")
    assert screen.status_code == 200
    text = visible(screen.text)
    assert "Every night at" in text and "the backup's hour" in text
    assert NARROW in text, "the configured suggestions did not reach the container"
    for word in ("hits", "visits", "top sites", "requests", "traffic", "users reached"):
        assert word not in text.lower(), f"the Routing screen talks about use: {word!r}"

    added = await operator.post("/panel/routing/suggestions", data={"name": NARROW})
    assert added.status_code == 200, added.text
    body = visible((await operator.get("/panel/routing/body")).text)
    assert "switch off" in body, "the narrow list was not added switched on"
    assert "nothing yet" in body, "adding a source fetched it, or the row is missing"


async def test_the_owner_lists_decide_the_lookup_and_never_wins(operator):
    unique = uuid.uuid4().hex[:8]
    always = f"always-{unique}.example"
    for which, value in (("always", always), ("never", f"x.{always}")):
        added = await operator.post(
            "/panel/routing/entries", data={"which": which, "value": value}
        )
        assert added.status_code == 200, added.text

    async def ask(destination: str) -> str:
        answer = await operator.post("/panel/routing/lookup", data={"destination": destination})
        assert answer.status_code == 200
        return visible(answer.text)

    assert "on your always-direct list" in await ask(f"www.{always}")
    assert "on your never-direct list" in await ask(f"y.x.{always}")
    assert "on no list" in await ask(f"elsewhere-{unique}.example")


async def test_the_nodes_screen_offers_direct_sites_on_every_node(operator):
    unique = uuid.uuid4().hex[:8]
    created = await operator.post(
        "/api/nodes",
        json={"name": f"routing-{unique}", "address": "192.0.2.77", "location_label": "X"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    nodes = await operator.get("/panel/nodes")
    assert f"/panel/nodes/{node_id}/direct" in nodes.text
    dialog = await operator.get(f"/panel/nodes/{node_id}/direct")
    assert "dials no hop" in visible(dialog.text)
    refused = await operator.post(
        f"/panel/nodes/{node_id}/direct", data={"on": "on", "resolver": "198.51.100.53"}
    )
    assert refused.status_code == 422
