"""Apply is not a way back from ``retired`` — M23.

WHAT: what ``POST /api/nodes/{id}/apply`` and the console's apply button do on a node
      whose state is ``retired``, and what the revocation fan-out does when one of the
      nodes it must re-push is retired.
WHY:  ``apply_node`` writes ``node.state = ACTIVE`` itself instead of going through
      ``nodes.set_node_state``, so ``NodeState.allowed_from`` — which has refused
      ``retired -> active`` since backlog item 17 — was never asked on this door.
      Measured: apply on a retired node answered 200 and left it ``active``.

      Retired is the state an operator moves a node to when its host is gone:
      decommissioned, handed back, or seized. Bringing the record back put an address
      that may now answer for a stranger into every friend's subscription at their next
      fetch — and since this milestone's fan-out it did so having first minted key
      material for every active friend on it, because an apply that puts a node into
      service grants everybody BEFORE it renders.

      So one button, pressed on a row an operator has already written off, put the whole
      fleet back onto it.
HOW:  the shared ``accepting_nodes`` harness (``conftest.py``) is installed in the tests
      that must not push. That is deliberate and it is what makes them able to fail: with
      the host accepting everything, a missing guard is not a failed apply — it is a
      completed one, active, granted and recorded, which is exactly what was measured.

Boundary: nothing here says anything about the HOST. A retired node's daemon may well
still be running the last file it was given; this control plane cannot know that from
here and none of these assertions pretend to.
"""

import pytest
from sqlalchemy import func, select

from control.app.errors import NodeCannotServe
from control.app.models import Credential, NodeState, NodeTransport
from control.app.panel import wording
from control.app.services import apply, friends, nodes, revocation, subscriptions

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. It is never dialled — the
# connection is replaced — but a record has to name something and a routable address in
# a fixture is an accident waiting to happen.
NODE_ADDRESS = "192.0.2.70"


async def a_node_with_something_to_serve(client, reality_params, *, name: str) -> tuple[str, str]:
    """A node with an SSH key and one transport enabled. Returns both ids.

    Enabled but not applied: every test below decides for itself whether this node ever
    reaches a host, and a transport is what makes an apply reach one at all — without it
    the refusal under test would be ``NothingToApply`` instead.
    """
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
    node_id = created.json()["id"]

    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    return node_id, enabled.json()["id"]


async def retire(client, node_id: str) -> None:
    """Take the node out the way an operator does: the state endpoint, which allows it."""
    retired = await client.post(
        f"/api/nodes/{node_id}/state",
        json={"state": "retired", "detail": "the host is gone"},
    )
    assert retired.status_code == 200, retired.text


async def credentials_on(session, node_id: str) -> int:
    """How many credentials exist on any transport of this node.

    Counted in the database rather than read off a screen: what a refusal must not do is
    mint material, and that is a row whether or not any surface is showing it.
    """
    return (
        await session.execute(
            select(func.count())
            .select_from(Credential)
            .join(NodeTransport)
            .where(NodeTransport.node_id == node_id)
        )
    ).scalar_one()


async def applied_at(session, node_transport_id: str):
    """When a config last actually landed on this row — NULL until one did."""
    return (
        await session.execute(
            select(NodeTransport.applied_at).where(NodeTransport.id == node_transport_id)
        )
    ).scalar_one()


@pytest.fixture
async def a_user_who_is_still_here(client) -> str:
    """One active user, who must not be granted anything on a node that is gone."""
    created = await client.post("/api/friends", json={"nickname": "boris"})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_apply_on_a_retired_node_is_refused_and_it_stays_retired(
    client, session, reality_params, accepting_nodes
) -> None:
    """The finding itself, on the surface it was measured on.

    Red against the previous commit in the strongest way a test can be: the node comes
    back ``active``, because the host accepts everything and nothing asked the machine.
    """
    node_id, row_id = await a_node_with_something_to_serve(
        client, reality_params, name="seized"
    )
    await retire(client, node_id)

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    # Its own code, so a script can tell this from the other 409 this endpoint answers —
    # a node with nothing enabled — whose next action is the opposite of this one's.
    assert refused.json()["error"]["code"] == "node_cannot_serve", refused.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.RETIRED, (
        "apply brought a node back from retired — the one transition the state machine "
        "exists to refuse"
    )
    # And nothing was pushed: this row has never carried a config, and a refusal that
    # dialled the host would have given it one.
    assert await applied_at(session, row_id) is None


async def test_the_refusal_mints_nothing_for_anybody(
    client, session, reality_params, accepting_nodes, a_user_who_is_still_here: str
) -> None:
    """The half that made this worse than a wrong state column.

    An apply that puts a node into service hands every active friend a credential on it
    before it renders. On a retired node that is the fleet being moved onto a host the
    operator has written off — so the refusal has to happen above the fan-out, not beside
    it, and the proof is that nobody holds anything afterwards.
    """
    node_id, _ = await a_node_with_something_to_serve(
        client, reality_params, name="written-off"
    )
    await retire(client, node_id)

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    session.expire_all()
    assert await credentials_on(session, node_id) == 0, (
        "a refused apply minted material for somebody on a node that is gone"
    )
    # And the half a person actually receives: their link still resolves to nothing,
    # which is the honest answer while no node serves.
    friend = await friends.get_friend(session, a_user_who_is_still_here)
    assert not await subscriptions.entries_for(session, friend), (
        "a retired node is back in a user's subscription"
    )


async def test_a_degraded_node_still_comes_back_with_an_apply(
    client, session, reality_params, accepting_nodes, a_user_who_is_still_here: str
) -> None:
    """The transition the guard must not take with it — and the one every retry needs.

    ``degraded -> active`` is in the machine and is what an operator does after fixing
    whatever the failure was. A guard that refused every state but ``active`` would close
    the finding and take the retry with it, which is the fix this round rejected.
    """
    node_id, row_id = await a_node_with_something_to_serve(
        client, reality_params, name="recovered"
    )
    degraded = await client.post(
        f"/api/nodes/{node_id}/state",
        json={"state": "degraded", "detail": "the push never reached the host"},
    )
    assert degraded.status_code == 200, degraded.text

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.ACTIVE, node.state_detail
    # The reason it carried is gone with the state, and the user who was here first holds
    # material on it: a node coming back into service grants everybody, retry or not.
    assert node.state_detail is None
    assert await credentials_on(session, node_id) == 1
    assert await applied_at(session, row_id) is not None


async def test_a_revocation_does_not_bring_a_retired_node_back(
    client, session, reality_params, accepting_nodes, a_user_who_is_still_here: str
) -> None:
    """The sibling door, which pushes without anybody pressing apply.

    A retired node keeps the credentials minted on it, so revoking somebody who holds one
    fans out to it through ``apply_many``. That fan-out went through the same missing
    guard: withdrawing one person's access re-activated a node the operator had retired
    and re-granted the whole fleet on it.

    What the operator is told instead is that the node was NOT updated and that retrying
    will not change it — which is the truth, and the more urgent half of it is that a host
    the record says is gone may still be running the file that authorises the person just
    revoked.
    """
    node_id, _ = await a_node_with_something_to_serve(client, reality_params, name="gone")
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    assert await credentials_on(session, node_id) == 1
    await retire(client, node_id)

    outcome = await revocation.revoke_friend(
        session, friend_id=a_user_who_is_still_here
    )

    assert not outcome.complete, "the fan-out reported a retired node as updated"
    assert outcome.why_failed[node_id] is apply.NotUpdated.REFUSED, (
        "the operator is sent to retry a push that will be refused for ever"
    )
    session.expire_all()
    assert (await nodes.get_node(session, node_id)).state == NodeState.RETIRED


async def test_a_node_another_session_retired_is_not_applied_by_a_session_holding_it(
    client, session, reality_params, accepting_nodes
) -> None:
    """The guard decides by the ROW, because the copy in hand is a photograph — M23.

    Sessions here keep what they loaded (``expire_on_commit=False``), so a node retired
    by the request that retired it still reads ``draft`` to everything that loaded it
    earlier. ``nodes._node_to_write`` closed this on the three node-record writes and
    named this exact harm in its docstring; the apply door asks the same question and had
    to make the same read, or the guard above would wave through the one transition the
    machine exists to refuse while believing it was a draft.

    Two sessions against one real Postgres, as in
    ``test_a_stale_node_cannot_make_a_write_a_no_op.py``: the test's own session holds
    the node, and the retirement arrives through the API in the request's own session,
    which is how a second surface reaches it in the field.
    """
    node_id, _ = await a_node_with_something_to_serve(
        client, reality_params, name="held-elsewhere"
    )
    # BOUND, and it has to be: the identity map holds its objects weakly, so an
    # unreferenced node is collected and the next read goes to the database by accident —
    # which would make this pass against the defect it is about.
    held = await nodes.get_node(session, node_id)
    assert held.state == NodeState.DRAFT

    await retire(client, node_id)

    with pytest.raises(NodeCannotServe):
        await apply.apply_node(session, node_id=node_id)

    session.expire_all()
    assert (await nodes.get_node(session, node_id)).state == NodeState.RETIRED
    assert await credentials_on(session, node_id) == 0


async def test_the_console_calls_it_a_refusal_and_not_a_failure(
    client, session, reality_params, accepting_nodes
) -> None:
    """The word above the banner, which is the difference between two situations.

    On this button ``failed`` additionally means "the node is now degraded". Here nothing
    was attempted and the node's state is the one the operator set themselves, so the
    label is ``refused`` — the same distinction M18.1 drew for a node with nothing
    enabled.
    """
    node_id, _ = await a_node_with_something_to_serve(
        client, reality_params, name="retired-row"
    )
    await retire(client, node_id)

    pressed = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert pressed.status_code == 200, pressed.text
    assert '<span class="banner-label">refused</span>' in pressed.text, pressed.text
    session.expire_all()
    assert (await nodes.get_node(session, node_id)).state == NodeState.RETIRED


def test_the_refusal_sends_a_script_nowhere_and_an_operator_somewhere() -> None:
    """One sentence, two readers — the seam ``wording.for_the_page`` exists for.

    The service's version is also the body of a 409, where naming a screen is the one
    thing a message must not do; the console's version has to name the control that makes
    a new record, because "register it again" with nowhere to do it is not a direction.
    """
    written = apply.CANNOT_SERVE_AGAIN.format(state=NodeState.RETIRED)

    assert "panel" not in written.lower(), written
    assert "screen" not in written.lower(), written

    on_the_console = wording.for_the_page(written)

    assert apply.WHERE_TO_RETRY in on_the_console, on_the_console
    # Decision 9's half of the same seam: the code says friend, the page says user.
    assert "friend" not in on_the_console.lower(), on_the_console
    # What does NOT move between the two: the substance is one fact for both readers.
    for held in ("Nothing was pushed, nobody was granted anything",):
        assert held in written and held in on_the_console, on_the_console
