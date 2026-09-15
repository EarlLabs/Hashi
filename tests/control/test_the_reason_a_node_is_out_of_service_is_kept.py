"""The "why" an operator types when they take a node out of service is kept — M23.

WHAT: what ``POST /api/nodes/{id}/state`` and the console's state dialog do with the
      ``detail`` field, on each of the four states.
WHY:  round 4's walk retired a node with *"host was returned to the provider"* and got a
      200 and a NULL column. ``degraded`` kept its reason; ``draft`` and ``retired``
      dropped theirs with no message anywhere. Retirement is where that costs most: the
      state is terminal, the row is kept precisely so the operator can see later what the
      fleet used to be, and the note they typed is the only part of that a record cannot
      reconstruct. ``draft`` is the same question one state earlier — *"parked, rebuilding
      the host"* is what tells them a week later whether the host is coming back.
HOW:  through the API for the column and through the console for the promise, because the
      dialog's own hint said the reason was ignored — true at the time, and the thing that
      has to move with the behaviour or the next operator is told the opposite.

``active`` is the exception and it is not an oversight: this column answers why a node is
NOT serving, and a node that serves has no such reason. Clearing it there is also what
keeps a stale push failure from being read under a healthy row.
"""

from control.app.models import NodeState
from control.app.services import nodes

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.81"


async def a_node(client, *, name: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": NODE_ADDRESS,
            "location_label": "Testland",
            "ssh_host": NODE_ADDRESS,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def move(client, node_id: str, state: str, detail: str):
    return await client.post(
        f"/api/nodes/{node_id}/state", json={"state": state, "detail": detail}
    )


async def test_a_retired_node_keeps_the_reason_it_was_retired_for(client) -> None:
    """The finding itself, on the state where it is least recoverable.

    ``retired -> anything`` is refused, so this row will never be moved again and this
    sentence will never be rewritten by a later state change. It was silently discarded.
    """
    node_id = await a_node(client, name="returned")
    why = "host was returned to the provider"

    retired = await move(client, node_id, "retired", why)

    assert retired.status_code == 200, retired.text
    assert retired.json()["state_detail"] == why, retired.text
    shown = await client.get(f"/api/nodes/{node_id}")
    assert shown.json()["state_detail"] == why, shown.text


async def test_a_parked_node_keeps_the_reason_it_was_parked_for(client) -> None:
    """``draft``, which is the state an operator uses while rebuilding a host."""
    node_id = await a_node(client, name="parked")
    why = "parked, rebuilding the host"

    await move(client, node_id, "active", "")
    parked = await move(client, node_id, "draft", why)

    assert parked.status_code == 200, parked.text
    assert parked.json()["state_detail"] == why, parked.text


async def test_a_degraded_node_still_keeps_its_reason(client) -> None:
    """The state this column was written for, unchanged — a node nobody fixes."""
    node_id = await a_node(client, name="broken")
    why = "the push never reached the host"

    degraded = await move(client, node_id, "degraded", why)

    assert degraded.status_code == 200, degraded.text
    assert degraded.json()["state_detail"] == why, degraded.text


async def test_a_node_that_goes_back_into_service_carries_no_reason(
    client, session
) -> None:
    """The one state that clears it, and why it must.

    A row reading ``active`` with a push failure still written on it is what the Nodes
    screen would then show under a node that is serving everybody perfectly well.
    """
    node_id = await a_node(client, name="recovered")
    await move(client, node_id, "degraded", "the push never reached the host")

    back = await move(client, node_id, "active", "")

    assert back.status_code == 200, back.text
    assert back.json()["state_detail"] is None, back.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.ACTIVE
    assert node.state_detail is None


async def test_the_dialog_no_longer_promises_the_reason_is_dropped(client) -> None:
    """The console's own words, which are what an operator decides by.

    The hint read "kept only when you mark it degraded … Ignored for every other state".
    That was true, and a fix that changed the behaviour and left the sentence would leave
    the operator believing the note they just typed had gone nowhere.
    """
    node_id = await a_node(client, name="dialog")

    dialog = await client.get(
        f"/panel/nodes/{node_id}/state", headers={"HX-Request": "true"}
    )

    assert dialog.status_code == 200, dialog.text
    assert "Ignored for every other state" not in dialog.text, dialog.text
    assert "kept on every state" in dialog.text, dialog.text
