"""A revocation whose push SUCCEEDS still reports, rather than 500 — M4.2.

WHAT: the half of ``apply_node`` that runs after the node accepted the new config,
      reached the way an operator reaches it: ``POST /api/friends/{id}/revoke``.
WHY:  every other test in this zone drives the apply path to a FAILURE — the fixture
      nodes have no SSH key, so ``target_for`` refuses before anything is dialled.
      That leaves the success half of ``apply_node`` unexercised on the one path it
      matters most on. Revocation commits the database change first and then pushes,
      and the node object reaching the push has arrived through relationships loaded
      by the revocation's own queries; touching an unloaded collection there is lazy
      I/O on an async session, which raises MissingGreenlet rather than querying.
      That escaped ``apply_many`` and the operator got a 500 instead of the
      ``RevocationOutcome`` naming which nodes still carry the credential — charter
      criterion 6's entire reporting obligation.
HOW:  the SSH half is replaced with a node that accepts everything. This is the only
      double in this zone and it is deliberately thin: it stands in for the five
      calls in ``edge.bootstrap.node_stack`` that touch a host, and nothing else.
      ``render_compose`` and ``digest_of`` stay real, so what is asserted about the
      recorded digest is what production would record.

      The boundary, stated plainly: this proves the control plane's bookkeeping after
      a successful push. It proves nothing about a real daemon reloading.

M4.3 extends the same doubles to the FAILING half. An unexpected error — anything
that is not a DomainError — used to escape ``apply_many`` and end the fan-out, so the
operator learned nothing about the nodes after the first one. The two fixtures below
break exactly one node, in the two places that behave differently: inside the push
window, where the node may be half-configured and core invariants §4 requires it to be
marked degraded; and outside it, where the node's recorded state is still true and must
not be touched. Both must leave the other node updated and reported.
"""

import logging

import pytest
from sqlalchemy.exc import MissingGreenlet

from control.app.models import NodeState
from edge.bootstrap import node_stack

# A reserved documentation address (RFC 5737), as everywhere else in this zone. It is
# never dialled here — the connection is replaced — but the record has to name
# something, and a routable address in a fixture is an accident waiting to happen.
NODE_ADDRESS = "192.0.2.10"

# Obviously not a key. It only has to be non-empty: ``target_for`` refuses a node with
# no SSH address, and the connection that would parse this never runs.
FAKE_PRIVATE_KEY = "not-a-real-key"


class AcceptingNode:
    """A node that accepts every step of an apply.

    Records the transports whose config was placed, so ``running_services`` can answer
    with exactly those — which is what makes the "did it come back up serving
    everything" check pass honestly rather than by returning a fixed list.
    """

    # No host key is learned, so the test says nothing about host-key pinning.
    learned_host_key = None

    def __init__(self) -> None:
        self.placed: list[str] = []

    # Untyped return: the class is its own annotation and py314 still needs a string
    # for that, which this repo's ruff rules reject (UP037).
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False


@pytest.fixture
def accepting_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the five node_stack calls that touch a host, and nothing else."""
    from control.app.services import apply

    monkeypatch.setattr(apply, "NodeConnection", lambda target: AcceptingNode())

    async def prepare(connection) -> None:
        return None

    async def place_config(connection, *, transport_name: str, config: str, path: str) -> None:
        connection.placed.append(transport_name)

    async def place_compose(connection, *, compose: str) -> None:
        return None

    async def restart(connection) -> None:
        return None

    async def running_services(connection) -> list[str]:
        return list(connection.placed)

    monkeypatch.setattr(node_stack, "prepare", prepare)
    monkeypatch.setattr(node_stack, "place_config", place_config)
    monkeypatch.setattr(node_stack, "place_compose", place_compose)
    monkeypatch.setattr(node_stack, "restart", restart)
    monkeypatch.setattr(node_stack, "running_services", running_services)


async def fleet_with_friend(client, session, reality_params, ws_params):
    """Two reachable nodes, three transports between them, one friend on all of them.

    Deliberately close to ``test_revocation.py``'s fixture, with one difference that is
    the whole point: these nodes carry an SSH address and key, so the push half runs to
    the end instead of refusing at the first step.
    """
    from control.app.services import nodes

    node_ids = []
    for name, country in (("leaf-nl", "Netherlands"), ("leaf-is", "Iceland")):
        response = await client.post(
            "/api/nodes",
            json={
                "name": name,
                "address": NODE_ADDRESS,
                "location_label": country,
                "ssh_host": NODE_ADDRESS,
                "ssh_private_key": FAKE_PRIVATE_KEY,
            },
        )
        node_ids.append(response.json()["id"])

    await client.post(
        f"/api/nodes/{node_ids[0]}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await client.post(
        f"/api/nodes/{node_ids[0]}/transports",
        json={"transport_name": "vless-ws-tls", "params": ws_params},
    )
    await client.post(
        f"/api/nodes/{node_ids[1]}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )

    for node_id in node_ids:
        await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend_id = (await client.post("/api/friends", json={"nickname": "kolya"})).json()["id"]
    return node_ids, friend_id


async def test_revoking_a_friend_reports_instead_of_failing(
    client, session, reality_params, ws_params, accepting_nodes
) -> None:
    """The operator gets the outcome, on the operation whose whole purpose is reporting.

    Driven through the HTTP endpoint rather than through ``apply_node`` directly,
    because the defect this covers only exists on the path where the session has
    already committed a revocation — calling ``apply_node`` on a freshly selected node
    would not reproduce it.
    """
    node_ids, friend_id = await fleet_with_friend(client, session, reality_params, ws_params)

    response = await client.post(f"/api/friends/{friend_id}/revoke")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is True, body
    assert sorted(body["nodes_updated"]) == sorted(node_ids)
    assert not body["nodes_failed"]


async def test_a_successful_revocation_push_records_what_was_applied(
    client, session, reality_params, ws_params, accepting_nodes
) -> None:
    """The digest is the drift signal, so a push that skipped recording it is a defect.

    Guards the fix as well as the bug: dropping the bookkeeping would make the first
    test pass while leaving every re-pushed node looking as though it had never been
    configured.
    """
    from sqlalchemy import select

    from control.app.models import NodeTransport

    node_ids, friend_id = await fleet_with_friend(client, session, reality_params, ws_params)

    await client.post(f"/api/friends/{friend_id}/revoke")

    rows = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id.in_(node_ids))
        )
    ).scalars().unique()
    recorded = [(row.transport_name, row.applied_at, row.applied_digest) for row in rows]
    assert len(recorded) == 3
    for transport_name, applied_at, applied_digest in recorded:
        assert applied_at is not None, f"{transport_name} was pushed but not recorded"
        assert applied_digest, f"{transport_name} has no digest to detect drift against"


async def test_a_pushed_node_is_left_active(
    client, session, reality_params, ws_params, accepting_nodes
) -> None:
    """A node that accepted the new config must not be left degraded.

    ``==`` rather than ``is``: ``NodeState`` is a StrEnum on a String column, so a
    freshly loaded row gives a plain str and an identity check would fail.
    """
    from control.app.services import nodes

    node_ids, friend_id = await fleet_with_friend(client, session, reality_params, ws_params)

    await client.post(f"/api/friends/{friend_id}/revoke")

    for node_id in node_ids:
        node = await nodes.get_node(session, node_id)
        assert node.state == NodeState.ACTIVE
        assert node.state_detail is None


@pytest.fixture
def push_interrupted_on_one_node(accepting_nodes, monkeypatch: pytest.MonkeyPatch) -> None:
    """The FIRST node's restart raises a non-DomainError; every later node is fine.

    ``MissingGreenlet`` rather than a bespoke exception because it is the error this
    actually happened with — lazy I/O on an async session — and because it is a
    reminder that the escaping error is usually a bug in this codebase rather than a
    node misbehaving. Raised from ``restart`` only as a place to stand: what matters is
    that it comes from inside the connection block, which is the one window where a node
    can be left half-configured.

    Counted rather than matched on the node, because both fixture nodes carry the same
    (reserved) address and the fan-out's order is the revocation query's, not ours. One
    failure and one success is all the assertions need.
    """
    restarts = {"count": 0}

    async def restart(connection) -> None:
        restarts["count"] += 1
        if restarts["count"] == 1:
            raise MissingGreenlet("greenlet_spawn has not been called")

    monkeypatch.setattr(node_stack, "restart", restart)


@pytest.fixture
def bookkeeping_fails_on_one_node(accepting_nodes, monkeypatch: pytest.MonkeyPatch) -> None:
    """The FIRST node fails AFTER a completely successful push.

    ``digest_of`` runs in the loop that records what was applied — the same statement
    the historical MissingGreenlet came out of. Unlike the fixture above, this node was
    configured successfully, so nothing about its state is wrong and the fan-out must
    leave it alone.
    """
    digests = {"count": 0}
    real_digest_of = node_stack.digest_of

    def digest_of(config: str) -> str:
        digests["count"] += 1
        if digests["count"] == 1:
            raise MissingGreenlet("greenlet_spawn has not been called")
        return real_digest_of(config)

    monkeypatch.setattr(node_stack, "digest_of", digest_of)


async def test_an_unexpected_error_mid_push_is_reported_and_the_fan_out_continues(
    client, session, reality_params, ws_params, push_interrupted_on_one_node, caplog
) -> None:
    """One node's crash must not cost the operator the outcome of the others.

    This is criterion 6's reporting obligation: a fan-out that aborts on the first node
    says nothing about the rest, and the revoked friend stays connected to every one of
    them with nobody aware of it.
    """
    caplog.set_level(logging.ERROR)
    node_ids, friend_id = await fleet_with_friend(client, session, reality_params, ws_params)

    response = await client.post(f"/api/friends/{friend_id}/revoke")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False, body
    assert len(body["nodes_failed"]) == 1, body
    assert len(body["nodes_updated"]) == 1, body
    assert set(body["nodes_failed"]) | set(body["nodes_updated"]) == set(node_ids)

    failed_id, reason = next(iter(body["nodes_failed"].items()))
    assert "MissingGreenlet" in reason, reason
    # The operator gets the failure, not the internals: no address, no stack.
    assert NODE_ADDRESS not in response.text
    assert "Traceback" not in reason

    # The traceback itself is not lost — without it an unexpected error becomes an
    # unreproducible line in a panel.
    assert any(record.exc_info for record in caplog.records), "no traceback was logged"

    # Core invariants §4: the push was interrupted, so this node may be half-configured
    # and must not stay in anyone's subscription. ``==`` not ``is`` — String column.
    from control.app.services import nodes

    failed_node = await nodes.get_node(session, failed_id)
    assert failed_node.state == NodeState.DEGRADED
    assert "MissingGreenlet" in (failed_node.state_detail or "")


async def test_an_unexpected_error_after_the_push_leaves_the_node_alone(
    client, session, reality_params, ws_params, bookkeeping_fails_on_one_node, caplog
) -> None:
    """A node that WAS configured is reported as not updated, but not degraded.

    The distinction is the whole reason the widened catch lives in two places: degrading
    a node that is serving perfectly well would take it out of every friend's
    subscription over a bug in our own bookkeeping.
    """
    caplog.set_level(logging.ERROR)
    node_ids, friend_id = await fleet_with_friend(client, session, reality_params, ws_params)

    response = await client.post(f"/api/friends/{friend_id}/revoke")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is False, body
    assert set(body["nodes_failed"]) | set(body["nodes_updated"]) == set(node_ids)
    assert len(body["nodes_updated"]) == 1, body

    failed_id, reason = next(iter(body["nodes_failed"].items()))
    assert "MissingGreenlet" in reason, reason
    assert "state is unchanged" in reason, reason
    assert any(record.exc_info for record in caplog.records), "no traceback was logged"

    from control.app.services import nodes

    failed_node = await nodes.get_node(session, failed_id)
    assert failed_node.state == NodeState.ACTIVE
    assert failed_node.state_detail is None
