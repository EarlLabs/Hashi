"""Pressing revoke again after a failure must not turn it into a success — M23.

WHAT: what the second press of the revoke button says, on the service and on the
      screen, when the first press could not update a node.
WHY:  measured on the owner's real hosts. The first press said, correctly, *"failed —
      access withdrawn in the database and on 0 node(s), but 1 node(s) could NOT be
      updated and the credential is still live on each until it is"*. The second press,
      with nothing changed on the node between them, said *"kolya revoked — link is
      dead"*.

      The mechanism is that a revocation deletes the credential rows, so the second
      fan-out has nothing to push and therefore nothing to fail on — and ``complete``,
      which means "every affected node accepted", is vacuously true with no affected
      node. Pressing again after a failure is the natural gesture of an operator cutting
      somebody off in a hurry, and the panel answered it with the one reassurance that
      moment must never produce by accident.
HOW:  real Postgres, real rendering, a real revocation through the service and through
      the panel route. Nothing is dialled: the node that cannot be updated has no SSH
      key, which is how this zone's other revocation tests make one.
"""

import html

from control.app.models import NodeState
from control.app.services import nodes, revocation

FRIEND_TRANSPORT = "vless-reality"

# RFC 5737 documentation addresses. Never dialled — the node below is refused before a
# connection is attempted, because its record carries no key.
UNREACHABLE = "192.0.2.70"

# What the FIRST press says and the second one may not. The panel composes it itself
# (``panel/routes.py``), so it is written out here rather than imported.
THE_REASSURANCE = "revoked — link is dead"


async def a_friend_on_a_node_that_cannot_be_updated(client, session, reality_params) -> str:
    """One active friend holding one credential on one serving, unpushable node."""
    created = await client.post(
        "/api/nodes",
        json={"name": "quiet-1", "address": UNREACHABLE, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": FRIEND_TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend = await client.post("/api/friends", json={"nickname": "kolya"})
    assert friend.status_code < 300, friend.text
    return friend.json()["id"]


async def test_the_second_press_does_not_claim_the_link_is_dead(
    client, session, reality_params
) -> None:
    """The finding itself: two presses, nothing changed between them, two answers.

    The first is a banner naming the node that kept the credential. The second must not
    be the toast — and the assertion is on the reassurance rather than only on the
    element, because a banner that happened to carry the same sentence would be the
    same lie in quieter type.

    Red against the previous commit: the second press answered with the toast.
    """
    friend_id = await a_friend_on_a_node_that_cannot_be_updated(
        client, session, reality_params
    )

    first = await client.post(
        f"/panel/friends/{friend_id}/revoke", headers={"HX-Request": "true"}
    )
    assert first.status_code == 200, first.text
    assert "could NOT be updated" in html.unescape(first.text), first.text

    second = await client.post(
        f"/panel/friends/{friend_id}/revoke", headers={"HX-Request": "true"}
    )

    assert second.status_code == 200, second.text
    seen = html.unescape(second.text)
    assert THE_REASSURANCE not in seen, (
        "the second press told the operator the link is dead, with nothing changed on "
        "the node since the first press said it was not"
    )
    assert "nothing changed — this access was already withdrawn" in seen, seen
    assert "probe it on the Nodes screen" in seen, seen


async def test_the_outcome_says_it_withdrew_nothing_while_complete_stays_true(
    client, session, reality_params
) -> None:
    """The trap, asserted as a trap — so nobody restores ``complete`` as the test.

    ``complete`` is true on the second press and is not wrong: no affected node failed,
    because no node was affected. It is simply not the question a surface reassures on,
    and asserting that it stays true is what stops a later change from "fixing" this by
    making it false and breaking every caller that reads it for what it says.
    """
    friend_id = await a_friend_on_a_node_that_cannot_be_updated(
        client, session, reality_params
    )

    first = await revocation.revoke_friend(session, friend_id=friend_id)
    assert first.withdrew is True
    assert first.complete is False
    assert first.confirmed is False

    second = await revocation.revoke_friend(session, friend_id=friend_id)

    assert second.withdrew is False
    assert second.complete is True, "the vacuous answer this milestone is about"
    assert second.confirmed is False
    assert second.summary() == (
        "nothing changed — this access was already withdrawn, so nothing was pushed to "
        "any node and this press cannot tell you that any node has stopped serving it. "
        "A node still running an older configuration goes on serving anyone withdrawn "
        "while it was in that state: probe it on the Nodes screen, and apply it there — "
        "unless its record says its host is gone, which is the one state a node is "
        "neither probed nor applied in, and nothing pushed from here reaches such a host "
        "at all."
    )


async def test_the_api_says_it_withdrew_nothing_too(
    client, session, reality_params
) -> None:
    """A script re-issuing a failed revocation reads the same fact the console does.

    ``complete`` alone is what a caller would poll, and on the second call it is true —
    so the field that separates the two is on the response as well as on the screen.
    """
    friend_id = await a_friend_on_a_node_that_cannot_be_updated(
        client, session, reality_params
    )

    assert (await client.post(f"/api/friends/{friend_id}/revoke")).json()["withdrew"] is True
    second = (await client.post(f"/api/friends/{friend_id}/revoke")).json()

    assert second["withdrew"] is False
    assert second["complete"] is True
    assert "already withdrawn" in second["summary"], second["summary"]


async def test_a_revocation_that_really_did_finish_still_gets_its_toast(
    client, session
) -> None:
    """The other half, so the fix is not "never reassure anybody".

    A friend who holds no credential on any node is withdrawn completely by the database
    half alone: their subscription stops resolving and there is nothing on any host that
    could still authorise them. That is the case the toast is FOR, and it still happens.
    """
    friend = await client.post("/api/friends", json={"nickname": "masha"})
    assert friend.status_code < 300, friend.text

    response = await client.post(
        f"/panel/friends/{friend.json()['id']}/revoke", headers={"HX-Request": "true"}
    )

    assert response.status_code == 200, response.text
    assert THE_REASSURANCE in html.unescape(response.text), response.text
