"""Two revocations of one person withdraw once, and only one of them says it did — M23.

WHAT: what ``revocation.revoke_friend`` answers when the access it is withdrawing has
      already been withdrawn by something else that is still in flight.
WHY:  round 8, on the owner's real hosts: two revocations of one friend at the same
      instant both answered ``withdrew: true``. Only one of them withdrew anything — the
      other pushed nothing, could confirm nothing, and told its caller it had cut somebody
      off. Whether a request withdrew access was read off ``friend.is_active``, which is
      the copy the caller's session is holding and not the row, and these sessions keep
      what they loaded (``expire_on_commit=False``).

      That is ``nodes._node_to_write``'s finding one table over, and it costs more here:
      ``withdrew`` is the field both surfaces decide on. False on a second call is what
      turns the retry's answer from a reassurance into "this press pushed nothing"; true
      on a second call is the reassurance the whole round is removing.
HOW:  two sessions against one real Postgres, which is what a race here is. The test's own
      session holds the friend, the other revocation arrives through the API in the
      request's own session, and the claim is asserted against the ROW — read as a column,
      because a session holding the object would answer from its own copy and agree with
      the defect.

      A genuinely simultaneous pair needs no test of its own: the claim is one conditional
      ``UPDATE``, so the second one blocks on the row the first holds and matches nothing
      once it commits. What could not be written deterministically is the interleaving;
      what this file pins is the decision.
"""

from sqlalchemy import select

from control.app.models import AuditAction, AuditEntry, Friend, NodeState
from control.app.services import friends, nodes, revocation

# RFC 5737 documentation address, as everywhere in this zone. Never dialled: the node
# below has no SSH key, so every push is refused before a connection is attempted.
NODE_ADDRESS = "192.0.2.95"

FRIEND_TRANSPORT = "vless-reality"


async def a_friend_on_a_node(client, session, reality_params) -> str:
    """One active friend holding one credential on one serving node."""
    created = await client.post(
        "/api/nodes",
        json={"name": "leaf-1", "address": NODE_ADDRESS, "location_label": "Testland"},
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
    assert friend.status_code == 201, friend.text
    return friend.json()["id"]


async def withdrawn_at(session, friend_id: str):
    """The withdrawal time as the database holds it, whatever this session is holding."""
    return (
        await session.execute(select(Friend.revoked_at).where(Friend.id == friend_id))
    ).scalar_one()


async def revocations_recorded(session) -> int:
    """How many times the trail says this operator withdrew somebody's access."""
    entries = await session.execute(
        select(AuditEntry.action).where(AuditEntry.action == AuditAction.FRIEND_REVOKED)
    )
    return len(list(entries.scalars().all()))


async def test_the_second_of_two_revocations_does_not_claim_to_have_withdrawn_anything(
    client, session, reality_params
) -> None:
    """The finding: one withdrawal, two callers, and only one of them did it.

    Red against the previous commit: the second outcome read ``withdrew=True`` — and with
    it ``summary()`` composed the incomplete-revocation sentence about a push this call
    never made, instead of saying that this press changed nothing.
    """
    friend_id = await a_friend_on_a_node(client, session, reality_params)
    # Bound, and it has to be: the identity map holds its objects WEAKLY, so an
    # unreferenced friend is collected and the next read goes to the database by accident.
    # A test that does not hold the copy proves nothing about a session holding one.
    held = await friends.get_friend(session, friend_id)
    assert held.is_active

    first = await client.post(f"/api/friends/{friend_id}/revoke")
    assert first.status_code == 200, first.text
    assert first.json()["withdrew"] is True, first.text

    second = await revocation.revoke_friend(session, friend_id=friend_id)

    assert second.withdrew is False, (
        "a revocation that arrived after the access was already withdrawn reported that "
        "it had withdrawn it"
    )
    assert second.confirmed is False
    assert "already withdrawn" in second.summary(), second.summary()


async def test_the_withdrawal_keeps_the_time_it_actually_happened(
    client, session, reality_params
) -> None:
    """And the loser does not stamp its own time over the winner's.

    The same stale copy that decided ``withdrew`` also decided the timestamp: reading
    ``revoked_at`` as NULL, the second call wrote its own. The column would then say the
    access was withdrawn at the moment of the press that withdrew nothing.
    """
    friend_id = await a_friend_on_a_node(client, session, reality_params)
    held = await friends.get_friend(session, friend_id)
    assert held.is_active

    assert (await client.post(f"/api/friends/{friend_id}/revoke")).status_code == 200
    when = await withdrawn_at(session, friend_id)
    assert when is not None

    await revocation.revoke_friend(session, friend_id=friend_id)

    assert await withdrawn_at(session, friend_id) == when


async def test_the_trail_records_one_withdrawal_and_not_two(
    client, session, reality_params
) -> None:
    """One thing happened, so the audit log says it once.

    ``revoke_friend`` records the entry only for the call that withdrew access, which was
    already the intent — "a trail that grows on a retried request is a trail that says a
    thing happened twice". It was a stale read away from doing it anyway.
    """
    friend_id = await a_friend_on_a_node(client, session, reality_params)
    held = await friends.get_friend(session, friend_id)
    assert held.is_active

    assert (await client.post(f"/api/friends/{friend_id}/revoke")).status_code == 200
    await revocation.revoke_friend(session, friend_id=friend_id)

    assert await revocations_recorded(session) == 1
