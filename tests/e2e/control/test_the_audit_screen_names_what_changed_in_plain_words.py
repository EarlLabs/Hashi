"""The audit screen names two changes in plain words, with no link in sight.

WHAT: changes two things about the fleet through the real control plane — adds a node
      and adds a user — then opens the audit screen as the operator and requires both
      to be named in words a person reads, with no subscription URL, no token and
      nothing about a connection anywhere on the page.
WHY:  M10's acceptance line, verbatim: *"change two things about the fleet, then open
      it: both must be named in plain words, with no token and no subscription link
      anywhere in sight."* The trail stores a machine key and two labels, so "in plain
      words" is a property of the RENDERED page and of nothing else — the unit suite
      proves the sentence table, and this proves the sentence reaches a browser from a
      control plane that was started rather than constructed.
HOW:  over real HTTP against the booted stack, as the operator, with a session cookie
      from the real login form. The subscription URL the screen must not carry is
      fetched first, so the assertion is about the actual live credential this fleet
      issued rather than about a pattern that resembles one.

      Its twin reads the database rather than the page
      (``test_the_audit_trail_never_learns_who_connected``): one says what is on disk,
      this says what a person sees. Neither is the other's superset — a screen can
      render something the table does not hold, which is exactly what a link on this
      page would be.

Boundary: real control, postgres, caddy. No node is contacted, no tunnel exists, and
nothing here says anything about a real network.
"""

import re
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# Every stored action value. Written out rather than imported for the reason the
# sibling scenario gives: nothing in this directory imports the application. None of
# them may appear on the screen — the sentence is rendered, and a machine key in front
# of the operator is the design's own failure mode.
STORED_KEYS = (
    "friend-added",
    "friend-revoked",
    "node-added",
    "node-state-changed",
    "node-applied",
    "transport-enabled",
    "transport-offered",
    "transport-withdrawn",
    "hop-established",
    "hop-dissolved",
    "keys-rotated",
    "params-replaced",
    # M15.2's. The newest key is the one most likely to reach the screen unrendered,
    # so it joins the list in the change that adds it rather than the first time
    # somebody sees it printed.
    "transport-removed",
    # M16's, in the change that adds it, for the same reason as the one above.
    "node-resolver-set",
)


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, (
        f"the operator could not log in ({response.status_code}) — check "
        "deploy/e2e.env against deploy/docker-compose.e2e.yml"
    )
    return client


def visible(markup: str) -> str:
    """The page with its tags removed — what a person actually reads."""
    return re.sub(r"<[^>]*>", " ", markup)


async def test_two_changes_are_named_in_plain_words_and_nothing_else_is(
    operator, unique: str
) -> None:
    """M10's acceptance walk, as a scenario."""
    node_name = f"leaf-{unique}"
    nickname = f"kolya-{unique}"

    node = await operator.post(
        "/api/nodes",
        json={
            "name": node_name,
            "address": "192.0.2.20",
            "location_label": f"Testland-{unique}",
        },
    )
    assert node.status_code == 201, node.text
    user = await operator.post("/api/users", json={"nickname": nickname})
    assert user.status_code == 201, user.text
    url = (
        await operator.get(f"/api/users/{user.json()['id']}/subscription")
    ).json()["url"]
    token = url.rsplit("/", 1)[-1]
    assert len(token) > 16, "the premise: a real bearer token was issued"

    screen = await operator.get("/panel/audit")
    assert screen.status_code == 200, screen.text
    reads = visible(screen.text)

    # Both changes, in words, with the names the operator themselves chose.
    assert f"node {node_name} added" in reads, (
        "the audit screen does not name the node that was just added in plain words"
    )
    assert f"user {nickname} added" in reads, (
        "the audit screen does not name the user that was just added in plain words"
    )
    # And it says "user", never the word this product stopped using (M29) — asserted
    # on the sentence this panel composed, above, rather than by sweeping the page for
    # the word. A blanket sweep is WRONG here and was proven wrong by this stack:
    # another scenario adds a user nicknamed ``hopuser-…``, and that name is the
    # operator's own text, handed back untouched on purpose. The panel composes its own
    # words, never theirs.
    assert f"friend {nickname}" not in reads.lower()
    for key in STORED_KEYS:
        assert key not in reads, f"the screen printed the stored key {key!r}"

    # Nothing in sight that is, or is part of, a credential. The failure messages name
    # what was found and never the text — a scenario that put a live token into a CI
    # log would be a worse defect than the one it closes.
    if token in screen.text:
        pytest.fail("a live subscription token is rendered on the audit screen")
    if url in screen.text:
        pytest.fail("a live subscription URL is rendered on the audit screen")
    assert "/sub/" not in screen.text, "the audit screen links into the delivery path"
    assert "192.0.2.20" not in reads, "a node address reached the audit screen"

    # And the delivery endpoint changes nothing a reader of this screen can see: the
    # page is the same page after a real client fetched a real subscription.
    before = (await operator.get("/panel/audit")).text
    assert (await operator.get(f"/sub/{token}")).status_code == 200
    assert (await operator.get("/panel/audit")).text == before, (
        "the audit screen moved because somebody fetched their subscription — a record "
        "that moves when a person uses the service is the one this project must not keep"
    )
