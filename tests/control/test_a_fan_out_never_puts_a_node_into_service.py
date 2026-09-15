"""A push nobody aimed at a node does not decide that node is back in service — M23.

WHAT: what a revocation's fan-out and a rotation's fan-out do when one of the nodes they
      must re-push is not serving — parked in ``draft`` while its host is rebuilt, or
      sitting ``degraded`` after a failed push.
WHY:  round 4's walk on the real hosts, and it is the same defect class round 7 closed
      for ``retired``, one state over. A node was parked in ``draft`` with the reason
      *"parked, rebuilding the host"*; a new user was added while it was parked and
      correctly given nothing on it; then one unrelated user was revoked. The entire
      visible answer was ``olga revoked — link is dead``. What actually happened was that
      the parked node went ``active``, the new user was minted key material on a host
      they had never been near, and ``docker compose up`` ran on the machine the operator
      had taken out of service to rebuild.

      The state machine is NOT the fix and must not be reached for: ``draft -> active``
      is legal, it is the first apply every node has, and round 7's guard rightly permits
      it. What was wrong is that a revocation was taking a node into service at all.

      So the line is at the DOOR. ``apply_many`` — the only path a revocation or a
      rotation reaches a host by — applies a node only if it is already serving; the
      operator's own apply button is unchanged and still takes a draft or degraded node
      into service, which is the retry every failed apply depends on.
HOW:  the shared ``accepting_nodes`` harness, for the reason the retired-node tests give:
      with the host accepting everything, a missing guard is not a failed push but a
      completed one — active, granted and recorded — which is exactly what was measured.

Boundary: nothing here claims anything about the HOST of a node that was not pushed. Its
daemon may well still be running the last file it was given and may still authorise the
person just withdrawn; that is the cost this fix takes on deliberately, it is said in the
refusal's own words, and no assertion below pretends otherwise.
"""

import pytest
from sqlalchemy import func, select

from control.app.errors import NodeNotInService
from control.app.models import AuditAction, AuditEntry, Credential, NodeState, NodeTransport
from control.app.services import apply, nodes, revocation, rotation

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. Nothing dials it — the
# connection is replaced — but a record has to name something.
NODE_ADDRESS = "192.0.2.80"


async def a_node_that_serves(client, reality_params, *, name: str) -> tuple[str, str]:
    """A node with a key and one enabled transport, applied once so it is really serving.

    Applied rather than moved to ``active`` by hand: a node parked later has to have been
    pushed at least once for the situation to be the one the walk found, where a file
    carrying somebody's peer entry is sitting on a host that is now out of service.
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

    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    return node_id, enabled.json()["id"]


async def park(client, node_id: str, *, state: str, why: str) -> None:
    """Take the node out of service the way an operator does: the state endpoint."""
    moved = await client.post(
        f"/api/nodes/{node_id}/state", json={"state": state, "detail": why}
    )
    assert moved.status_code == 200, moved.text


async def add_user(client, nickname: str) -> str:
    created = await client.post("/api/friends", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def credentials_on(session, node_id: str) -> int:
    """How many credentials exist on any transport of this node."""
    return (
        await session.execute(
            select(func.count())
            .select_from(Credential)
            .join(NodeTransport)
            .where(NodeTransport.node_id == node_id)
        )
    ).scalar_one()


async def applied_at(session, node_transport_id: str):
    """When a config last actually landed on this row — NULL until one did.

    The stamp rather than the digest, because the digest answers a different question:
    this project's configs do not change when the only friend on a node is withdrawn
    from a transport that carries its clients elsewhere, so an unchanged digest is not
    evidence that nothing was pushed. The stamp moves on every push that landed.
    """
    return (
        await session.execute(
            select(NodeTransport.applied_at).where(NodeTransport.id == node_transport_id)
        )
    ).scalar_one()


async def actions(session) -> list[AuditAction]:
    """Every recorded change, oldest first."""
    return list(
        (
            await session.execute(
                select(AuditEntry.action).order_by(AuditEntry.at, AuditEntry.id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.parametrize("state", ["draft", "degraded"])
async def test_a_revocation_does_not_take_a_node_out_of_service_back_into_it(
    client, session, reality_params, accepting_nodes, state: str
) -> None:
    """The walk's own sequence, on both states an operator can park a node in.

    Red against the previous commit in the strongest way a test can be: the host accepts
    everything, so without the guard the node comes back ``active`` with the whole fleet
    granted on it — which is what was measured on the real host, down to the md5 of the
    file changing and a full ``docker compose up``.
    """
    node_id, row_id = await a_node_that_serves(client, reality_params, name="parked")
    olga = await add_user(client, "olga")
    assert await credentials_on(session, node_id) == 1
    landed = await applied_at(session, row_id)
    await park(client, node_id, state=state, why="parked, rebuilding the host")
    # Added WHILE parked, and granted nothing on this node — which is correct and is the
    # premise: nobody is routed onto a node that is not serving.
    await add_user(client, "pavel")
    session.expire_all()
    assert await credentials_on(session, node_id) == 1

    await revocation.revoke_friend(session, friend_id=olga)

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState(state), (
        "a revocation took a node the operator had taken out of service back into it"
    )
    # Nobody was minted anything: olga's row is gone with the revocation and pavel never
    # had one here, so the count is zero rather than one.
    assert await credentials_on(session, node_id) == 0, (
        "a revocation handed somebody key material on a node nobody applied"
    )
    # And nothing was pushed: the digest on the row is still the one the apply before the
    # parking left there.
    assert await applied_at(session, row_id) == landed


async def test_the_operator_is_told_the_node_was_not_updated_and_why(
    client, session, reality_params, accepting_nodes
) -> None:
    """The other half of the fix, and the half the operator actually reads.

    Refusing to push is only honest if the node is reported as NOT updated — a silent
    skip would be the reassuring answer the walk was given, arrived at by a different
    route. Its own kind rather than ``REFUSED``, because that one says "retrying will not
    change that", which is true of a retired node and false of a parked one.
    """
    node_id, _ = await a_node_that_serves(client, reality_params, name="rebuilding")
    olga = await add_user(client, "olga")
    await park(client, node_id, state="draft", why="parked, rebuilding the host")

    outcome = await revocation.revoke_friend(session, friend_id=olga)

    assert not outcome.confirmed, "a node that was not pushed was reported as updated"
    assert outcome.why_failed[node_id] is apply.NotUpdated.OUT_OF_SERVICE, (
        outcome.why_failed
    )
    said = outcome.summary()
    assert "rebuilding" in said, f"the banner does not name the node: {said}"
    assert apply.WHERE_TO_RETRY in said, said


async def test_nothing_about_the_node_is_recorded_as_having_happened(
    client, session, reality_params, accepting_nodes
) -> None:
    """The trail, which is where the walk saw the damage after the fact.

    ``node-applied`` and a second ``node-state-changed`` were written for a node nobody
    had pressed anything on. A refusal above every write leaves the trail saying exactly
    what the operator did: they parked a node, and they revoked somebody.
    """
    node_id, _ = await a_node_that_serves(client, reality_params, name="untouched")
    olga = await add_user(client, "olga")
    await park(client, node_id, state="draft", why="parked, rebuilding the host")
    before = await actions(session)

    await revocation.revoke_friend(session, friend_id=olga)

    session.expire_all()
    assert await actions(session) == [*before, AuditAction.FRIEND_REVOKED]


async def test_a_rotation_does_not_take_a_node_out_of_service_back_into_it(
    client, session, reality_params, accepting_nodes
) -> None:
    """The sibling door, which pushes through the same fan-out — M23, round 4.

    Rotation is aimed at one transport's material, not at the node's place in the fleet,
    and until this fix rotating keys on a parked node applied it: back into service, with
    every active user granted on it. The material is still rotated in the database, which
    is the operation that was actually asked for; what does not follow it is a push.
    """
    node_id, row_id = await a_node_that_serves(client, reality_params, name="parked-row")
    await add_user(client, "olga")
    await park(client, node_id, state="draft", why="parked, rebuilding the host")

    outcome = await rotation.rotate_keys(session, node_transport_id=row_id)

    assert outcome.rotated, "nothing was rotated, so this proves nothing about the push"
    assert not outcome.complete
    assert "parked-row" in outcome.nodes_failed, outcome.nodes_failed
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DRAFT, (
        "a key rotation took a node the operator had parked back into service"
    )


async def test_a_node_that_is_serving_is_still_pushed_by_a_fan_out(
    client, session, reality_params, accepting_nodes
) -> None:
    """The behaviour the guard must not take with it — charter criterion 6 itself.

    A revocation exists to make the withdrawal true on every node the person was on, and
    a guard that stopped the fan-out reaching a node that IS serving would close the
    finding by breaking the criterion it was written under.
    """
    node_id, row_id = await a_node_that_serves(client, reality_params, name="serving")
    olga = await add_user(client, "olga")
    landed = await applied_at(session, row_id)

    outcome = await revocation.revoke_friend(session, friend_id=olga)

    assert outcome.confirmed, outcome.summary()
    assert outcome.nodes_updated == [node_id]
    session.expire_all()
    assert (await nodes.get_node(session, node_id)).state == NodeState.ACTIVE
    # And pushed: the stamp on the row moved, which is what says a config landed.
    assert await applied_at(session, row_id) > landed


async def test_the_operators_own_apply_still_takes_a_parked_node_back(
    client, session, reality_params, accepting_nodes
) -> None:
    """The door that IS allowed to decide this, and the one the refusal sends them to.

    ``draft -> active`` from the apply button is the whole way a node enters service, and
    a fix that reached for the state machine would have taken it away. Pressed after the
    revocation above, it is also what actually ends the situation: the file on the host
    is replaced with one that carries only who still holds a credential.
    """
    node_id, row_id = await a_node_that_serves(client, reality_params, name="coming-back")
    olga = await add_user(client, "olga")
    await park(client, node_id, state="draft", why="parked, rebuilding the host")
    await revocation.revoke_friend(session, friend_id=olga)
    await add_user(client, "pavel")

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.ACTIVE, node.state_detail
    # The reason the operator parked it with is gone with the state, and the user added
    # while it was parked holds material on it now — a node going into service grants
    # everybody, and that has not changed.
    assert node.state_detail is None
    assert await credentials_on(session, node_id) == 1
    assert await applied_at(session, row_id) is not None


async def test_the_refusal_is_raised_before_anything_is_dialled_or_minted(
    client, session, reality_params, accepting_nodes
) -> None:
    """The guard's position, asserted directly on the service rather than through a door.

    Above the render, above the connection and above the fan-out that mints — the same
    place the retired guard sits, and for the same reason: a refusal that fires after the
    grant has to undo it, and undoing it is what leaves material on a host.
    """
    node_id, row_id = await a_node_that_serves(client, reality_params, name="not-serving")
    await add_user(client, "olga")
    landed = await applied_at(session, row_id)
    await park(client, node_id, state="draft", why="parked, rebuilding the host")

    with pytest.raises(NodeNotInService) as refused:
        await apply.apply_node(session, node_id=node_id, only_if_serving=True)

    written = refused.value.message
    # It says what did NOT happen, because that is the part the operator cannot see.
    assert "nothing was pushed to it" in written, written
    assert "nobody was granted anything" in written, written
    # And it names no screen: this sentence travels in a revocation's and a rotation's
    # outcome, both of which are answered to an API caller as well as to the console.
    assert "screen" not in written.lower() and "panel" not in written.lower(), written
    session.expire_all()
    assert await applied_at(session, row_id) == landed
    assert (await nodes.get_node(session, node_id)).state == NodeState.DRAFT
