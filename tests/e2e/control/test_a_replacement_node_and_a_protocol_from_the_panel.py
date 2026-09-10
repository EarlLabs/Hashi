"""Replacing a node, and turning a protocol on, without anyone touching a device.

WHAT: charter criteria 2 and 3, driven entirely through the admin panel against the
      booted stack.
WHY:  both were reported closed and neither had a scenario that could fail. That is
      the most expensive kind of gap: the criteria are the two the whole "nodes and
      protocols are data" design exists to deliver, and "closed" was resting on the
      code looking right.

      Criterion 2 — "any node is replaceable in ten minutes and no user touches
      anything". Criterion 3 — "a transport is switched on from the panel and is in
      every friend's subscription at their next refresh".
HOW:  every operator action here is a POST to ``/panel/**``, because "from the panel"
      is part of both criteria — the same operations over ``/api/**`` would prove a
      different, weaker statement. Every assertion is read from ``/sub/{token}``
      anonymously, exactly as a friend's client reads it: the friend's side of both
      criteria is that their link did not move and they did nothing.

Boundary, stated plainly: no real host, no tunnel, no daemon. The replacement node is
a stub record in the e2e stack, so "ten minutes" here means the number of operator
actions and their idempotence, NOT a stopwatch against a live machine. Criterion 1 is
not touched by this file and cannot be.
"""

import base64
import re
import uuid

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# Every action below is the console's, and the console asks with htmx. Sent explicitly
# rather than left off: until M9.6 two of these routes answered a header-less POST with
# a 303 back to the pre-redesign page, and the walk below drove that branch instead of
# the one an operator's browser actually takes.
HTMX = {"HX-Request": "true"}

# Distinct ports per scenario: the stack is shared by the whole run, and two nodes
# listening on one port is a state the transport's own validator has no reason to
# refuse but which would make two scenarios' fleets indistinguishable.
REALITY_PORT_FIRST = 8461
REALITY_PORT_REPLACEMENT = 8462
REALITY_PORT_CRITERION_3 = 8463
WS_PORT = 8464


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, response.text
    return client


async def form_action(operator, dialog_url: str, *, opened_by: str) -> str:
    """Where the form inside one console dialog actually posts.

    Read off the rendered dialog rather than written down here, which is the standard
    ``withdraw_button`` below already held and which M9.6 brought to the rest of this
    file: the operator's route to every one of these actions is a button that opens a
    dialog, and a scenario that posted to a remembered URL would keep passing while the
    button opened a form that submitted nowhere.
    """
    dialog = await operator.get(dialog_url)
    assert dialog.status_code == 200, dialog.text
    found = re.search(r'<form[^>]*\shx-post="([^"]+)"', dialog.text)
    assert found, f"the dialog behind {opened_by!r} carries no form"
    return found.group(1)


async def node_from_the_panel(operator, *, name: str, address: str, country: str) -> str:
    """Register a node the way the owner does — the "add node" dialog, not the JSON API."""
    created = await operator.post(
        await form_action(operator, "/panel/nodes/new", opened_by="add node"),
        data={"name": name, "address": address, "location_label": country},
        headers=HTMX,
    )
    # 200 IS the success assertion: the console refuses this form at 422 with the dialog
    # re-rendered, so the two cannot be confused. Until M9.6 a header-less POST got a 303
    # to the pre-redesign page instead, which is the branch this used to assert.
    assert created.status_code == 200, created.text
    assert "<html" not in created.text.lower()

    # The console's answer is a toast and a table refresh, not the id, so it is read back
    # from the list. Deliberately not created over /api to get the id more cheaply:
    # "from the panel" is the part of the criterion under test.
    listed = (await operator.get("/api/nodes")).json()
    matching = [node for node in listed if node["name"] == name]
    assert len(matching) == 1, matching
    return matching[0]["id"]


async def enabled_from_the_panel(operator, node_id: str, transport: dict) -> None:
    """Switch one protocol on, from the dialog the row's "transports" button opens.

    The console renders a GROUP of boxes per transport and hides all but the chosen one,
    so every box is named ``<transport>-<field>`` — a hidden input is still submitted,
    and without the prefix a second transport's ``port`` would arrive under the same
    name. M9.6 deleted the bare-name fallback along with the page that sent bare names,
    so a bare one is now refused rather than quietly read as an empty box.
    """
    chosen = transport["transport_name"]
    enabled = await operator.post(
        await form_action(
            operator, f"/panel/nodes/{node_id}/transports", opened_by="transports"
        ),
        data={
            key if key == "transport_name" else f"{chosen}-{key}": value
            for key, value in transport.items()
        },
        headers=HTMX,
    )
    assert enabled.status_code == 200, enabled.text
    assert "<html" not in enabled.text.lower()


async def reality_from_the_panel(operator, node_id: str, *, port: int) -> None:
    await enabled_from_the_panel(
        operator,
        node_id,
        {
            "transport_name": "vless-reality",
            "port": str(port),
            "decoy_host": "www.example.com",
            "decoy_port": "443",
            "server_names": "www.example.com",
        },
    )


async def state_from_the_panel(operator, node_id: str, state: str) -> str:
    """Move a node's state on the screen the criteria are written about.

    Through the dialog the row's "set state" button opens, which is the operator's only
    route to it since M9.5 homed the action there and M9.6 deleted the page that used to
    carry it. A state this node may not move into is refused at 422 with the dialog back,
    so 200 still means the move happened — and the fragment assertion is unchanged.
    """
    response = await operator.post(
        await form_action(
            operator, f"/panel/nodes/{node_id}/state", opened_by="set state"
        ),
        data={"state": state},
        headers=HTMX,
    )
    assert response.status_code == 200, response.text
    # A fragment, never a document — the control rulebook's HTMX trap.
    assert "<html" not in response.text.lower()
    return response.text


async def withdraw_button(operator, node_id: str, transport_name: str) -> str:
    """The URL the panel's own withdraw button leads to, for one protocol on one node.

    Read off the panel rather than out of a JSON API on purpose: the operator's route to
    this action is the button, and a scenario that discovered the id some other way could
    pass while the button pointed nowhere.

    REPOINTED BY M9.5, which moved this action off the pre-redesign node page and onto
    the Nodes screen — the button now lives in the dialog that row's "transports" action
    opens. The property is the same one and it is asserted harder: the button still
    carries the transport's name as DATA rather than only as text beside it, and what
    comes back is the URL the button itself carries, so a button pointing nowhere fails
    here rather than being routed around. What follows it is the confirmation dialog,
    which is where the POST that actually withdraws is.
    """
    dialog = await operator.get(f"/panel/nodes/{node_id}/transports")
    assert dialog.status_code == 200, dialog.text
    found = re.search(
        rf'data-transport="{re.escape(transport_name)}"\s+'
        r'hx-get="(/panel/transports/[^"]+/withdraw)"',
        dialog.text,
    )
    assert found, f"no withdraw button for {transport_name} on the Nodes screen"

    # The confirmation the operator reads before they press it, and the POST behind it —
    # taken from the dialog rather than assumed, for the same reason as the button.
    confirmation = await operator.get(found.group(1))
    assert confirmation.status_code == 200, confirmation.text
    posts_to = re.search(
        r'hx-post="(/panel/transports/[^"]+/withdraw)"', confirmation.text
    )
    assert posts_to, "the withdraw confirmation confirms nothing"
    return posts_to.group(1)


async def friend_token(operator, nickname: str) -> str:
    friend_id = (
        await operator.post("/api/friends", json={"nickname": nickname})
    ).json()["id"]
    url = (await operator.get(f"/api/friends/{friend_id}/subscription")).json()["url"]
    return url.rsplit("/", 1)[-1]


async def mine(client, token: str, marker: str) -> list[str]:
    """This scenario's own entries in a friend's subscription.

    The stack is shared by every scenario in the run, so "the subscription" is only a
    meaningful subject when narrowed to the lines this scenario's fleet produced. The
    marker is in the node's country label, which rides in every entry's fragment.
    """
    response = await client.get(f"/sub/{token}")
    assert response.status_code == 200, response.text
    decoded = base64.b64decode(response.text).decode()
    return [line for line in decoded.splitlines() if marker in line]


# --- criterion 2 --------------------------------------------------------------

async def test_a_destroyed_node_is_replaced_and_the_same_link_follows(
    operator, client, unique: str
) -> None:
    """S1. The friend does nothing, and their link resolves to the new host.

    The whole point of the criterion is the friend's inaction, so their token is
    captured BEFORE the replacement and never re-issued or re-read from the panel
    afterwards. If anything in the replacement path had to touch their access, this
    scenario would be reading a stale token and would fail.

    Asserted against the subscription document rather than the database: what the
    database holds is not the promise. The promise is what their client fetches.
    """
    country = f"Testland-{unique}"
    original = await node_from_the_panel(
        operator, name=f"leaf-{unique}", address="192.0.2.71", country=country
    )
    await reality_from_the_panel(operator, original, port=REALITY_PORT_FIRST)
    await state_from_the_panel(operator, original, "active")

    token = await friend_token(operator, f"kolya-{unique}")
    before = await mine(client, token, country)
    assert len(before) == 1, before
    assert "192.0.2.71" in before[0]

    # The host is gone. Retiring the record is how the operator says so, and it is
    # what a real "the provider took the machine" looks like from here.
    await state_from_the_panel(operator, original, "retired")
    assert await mine(client, token, country) == [], (
        "a retired node is still in a friend's subscription"
    )

    # The replacement: a new host, a new record, three actions on one screen.
    replacement = await node_from_the_panel(
        operator, name=f"leaf-{unique}-b", address="192.0.2.72", country=country
    )
    await reality_from_the_panel(operator, replacement, port=REALITY_PORT_REPLACEMENT)
    await state_from_the_panel(operator, replacement, "active")

    after = await mine(client, token, country)
    assert len(after) == 1, after
    assert "192.0.2.72" in after[0], "the same link did not follow the replacement"
    assert "192.0.2.71" not in after[0]

    # Idempotence is the honest half of "ten minutes": the operator who re-clicks
    # "active" because the page scrolled must not double anything.
    await state_from_the_panel(operator, replacement, "active")
    assert await mine(client, token, country) == after


# --- criterion 3 --------------------------------------------------------------

async def test_a_transport_switched_on_reaches_every_friend_and_off_again_leaves_nobody(
    operator, client, unique: str
) -> None:
    """S2, both halves. Enabling adds it for everyone; withdrawing removes it.

    The negative half is what makes this a criterion rather than an observation.
    "Enabling added a line" is also true of a system that can never take one away —
    and a protocol that cannot be withdrawn is a protocol the operator cannot rotate
    away from once it is blocked, which is the charter's whole reason for existing.
    """
    country = f"Fanout-{unique}"
    node_id = await node_from_the_panel(
        operator, name=f"fanout-{unique}", address="192.0.2.73", country=country
    )
    await reality_from_the_panel(operator, node_id, port=REALITY_PORT_CRITERION_3)
    await state_from_the_panel(operator, node_id, "active")

    tokens = [
        await friend_token(operator, f"{name}-{unique}") for name in ("anya", "boris")
    ]
    for token in tokens:
        assert len(await mine(client, token, country)) == 1

    # A SECOND protocol on the same node, enabled from the panel. No redeploy, no
    # code change, and nothing asked of any friend.
    await enabled_from_the_panel(
        operator,
        node_id,
        {
            "transport_name": "vless-ws-tls",
            "port": str(WS_PORT),
            "server_name": f"front-{unique}.example.com",
            "certificate_path": "/etc/hashi/certs/fullchain.pem",
            "certificate_key_path": "/etc/hashi/certs/privkey.pem",
        },
    )

    for token in tokens:
        lines = await mine(client, token, country)
        assert len(lines) == 2, lines
        assert any(f"front-{unique}.example.com" in line for line in lines), lines

    # Withdraw it again. This is the red half performed as an operation rather than
    # as an edit: the assertion below is the same one that would have caught a
    # withdrawal that only changed a row.
    withdrawn = await operator.post(
        await withdraw_button(operator, node_id, "vless-ws-tls"), headers=HTMX
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert "<html" not in withdrawn.text.lower()

    for token in tokens:
        lines = await mine(client, token, country)
        assert len(lines) == 1, lines
        assert all(f"front-{unique}.example.com" not in line for line in lines), lines


async def test_offering_a_protocol_does_not_reach_a_friend_who_was_not_given_the_node(
    operator, client, unique: str
) -> None:
    """S3. The fan-out has a boundary, and it is worth stating what the boundary is.

    In this control plane every ACTIVE friend is granted every serving node on
    purpose — that IS criterion 2, so among active friends there is nobody a node was
    "not given". The requirement therefore splits into the two true statements that
    remain, and both are asserted here:

    * a REVOKED friend is not handed the new protocol, and their link stays a 404
      rather than becoming valid-but-empty;
    * every entry the operator did not touch is unchanged — same lines, not merely the
      same number of them. That is what "does not touch" has to mean, because a client
      re-reading a rewritten entry for an untouched node is a friend whose working
      exit stopped working during someone else's change.
    """
    country = f"Boundary-{unique}"
    node_id = await node_from_the_panel(
        operator, name=f"boundary-{unique}", address="192.0.2.74", country=country
    )
    await reality_from_the_panel(operator, node_id, port=8465)
    await state_from_the_panel(operator, node_id, "active")

    # A second node, which this scenario never touches again. It is the "everything
    # else" the enabling below must leave alone, byte for byte.
    untouched = await node_from_the_panel(
        operator, name=f"bystander-{unique}", address="192.0.2.75", country=country
    )
    await reality_from_the_panel(operator, untouched, port=8467)
    await state_from_the_panel(operator, untouched, "active")

    staying = await friend_token(operator, f"stays-{unique}")
    leaving_id = (
        await operator.post("/api/friends", json={"nickname": f"leaves-{unique}"})
    ).json()["id"]
    leaving = (
        await operator.get(f"/api/friends/{leaving_id}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    assert len(await mine(client, leaving, country)) == 2
    assert (await operator.post(f"/panel/friends/{leaving_id}/revoke")).status_code == 200
    assert (await client.get(f"/sub/{leaving}")).status_code == 404

    # A revocation re-pushes every node the friend was on, and these nodes have no SSH
    # key — so the push failed and the node is now DEGRADED and correctly out of
    # everyone's subscription. Put it back into service before asserting on what the
    # remaining friend receives; otherwise the assertion below would pass or fail for
    # the wrong reason entirely. That the failed push reports itself is asserted in
    # test_the_owner_issues_and_revokes_access.py, not re-litigated here.
    for node in (node_id, untouched):
        await state_from_the_panel(operator, node, "active")
    before = await mine(client, staying, country)
    assert len(before) == 2, before
    assert (await client.get(f"/sub/{leaving}")).status_code == 404, (
        "putting a node back into service handed access to a revoked friend"
    )

    # Now switch a second protocol on, on ONE of the two nodes.
    await enabled_from_the_panel(
        operator,
        node_id,
        {
            "transport_name": "vless-ws-tls",
            "port": "8466",
            "server_name": f"edge-{unique}.example.com",
            "certificate_path": "/etc/hashi/certs/fullchain.pem",
            "certificate_key_path": "/etc/hashi/certs/privkey.pem",
        },
    )

    after = await mine(client, staying, country)
    added = [line for line in after if line not in before]
    assert len(added) == 1, added
    assert f"edge-{unique}.example.com" in added[0]
    # Everything the operator did not touch is untouched — the same lines, not merely
    # the same count. A grant that re-minted material the friend already held, or
    # handed them a second credential on a node-transport they were already on, would
    # rewrite or duplicate entries here while the count still looked plausible.
    assert [line for line in after if line in before] == before, after
    assert "192.0.2.75" in "\n".join(before), "the bystander node was never delivered"

    # Still gone, and still a 404 rather than an empty document: the revoked link must
    # not come back to life as "valid but empty" either.
    assert (await client.get(f"/sub/{leaving}")).status_code == 404
