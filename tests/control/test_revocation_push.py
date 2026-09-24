"""A revocation whose push SUCCEEDS still reports, rather than 500 — M4.2.

WHAT: the half of ``apply_node`` that runs after the node accepted the new config,
      reached the way an operator reaches it: ``POST /api/users/{id}/revoke``.
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
HOW:  the SSH half is replaced with a node that accepts everything — ``accepting_nodes``,
      which lived here until M23's round 2 and is now in ``conftest.py`` because an apply
      that SUCCEEDS is also the moment a node starts serving, and a second file needed the
      same node. It is the only double in this zone and it is deliberately thin: it stands
      in for the five calls in ``edge.bootstrap.node_stack`` that touch a host, and
      nothing else. ``render_compose`` and ``digest_of`` stay real, so what is asserted
      about the recorded digest is what production would record.

      The boundary, stated plainly: this proves the control plane's bookkeeping after
      a successful push. It proves nothing about a real daemon reloading.

M4.3 extends the same doubles to the FAILING half. An unexpected error — anything
that is not a DomainError — used to escape ``apply_many`` and end the fan-out, so the
operator learned nothing about the nodes after the first one. The two fixtures below
break exactly one node, in the two places that behave differently: inside the push
window, where the node may be half-configured and core invariants §4 requires it to be
marked degraded; and outside it, where the node's recorded state is still true and must
not be touched. Both must leave the other node updated and reported.

M4.6 makes this file able to FAIL, which is the only property a test really has. Two
gaps, one shape: a double whose real counterpart changed goes silently green rather
than red, and the address-leak guard was injecting a ``MissingGreenlet``, which never
carried an address in the first place. So every double goes in through ``pinned`` — in
``conftest.py`` with the fixture now, and still imported here by the two doubles below —
which refuses at setup when the signatures have drifted apart, and the leak has its own
exception that really does name the node — see
``test_an_unexpected_error_never_carries_the_node_address_outward``.
"""

import errno
import logging

import pytest
from sqlalchemy.exc import MissingGreenlet

from control.app.models import NodeState
from edge.bootstrap import node_stack

from .conftest import GENERATED_SSH_KEY, pinned

# A reserved documentation address (RFC 5737), as everywhere else in this zone. It is
# never dialled here — the connection is replaced — but the record has to name
# something, and a routable address in a fixture is an accident waiting to happen.
NODE_ADDRESS = "192.0.2.10"

# A real key, from the conftest. It used to be the string "not-a-real-key", which only
# had to be non-empty because the connection that would parse it is replaced here — but
# ``target_for`` now refuses a record whose key will not load, before any of that, so a
# placeholder never reaches the double. It authenticates nothing.
FAKE_PRIVATE_KEY = GENERATED_SSH_KEY

# The SSH port on the fixture nodes' records. Written into the record rather than left
# to the API's default so that the fake connection error below can quote the address and
# port that WOULD have been dialled without inventing either: what it stands in for is
# the exception asyncio raises, which is built from exactly those two.
NODE_SSH_PORT = 22


def a_refused_connection() -> OSError:
    """The exception a refused TCP connect really produces — address, port and all.

    ``[Errno 111] Connect call failed ('<host>', <port>)`` is what the reviewer of M4.3
    reproduced out of the SSH layer, and it is an ``OSError`` rather than a
    ``NodeUnreachable``, so it reaches ``apply_node``'s broad catch unsanitised.

    Built here rather than inline so the test can name its type without hardcoding the
    class Python picks: ECONNREFUSED is re-classed to ``ConnectionRefusedError``, and
    that name is the whole of what the operator is given.
    """
    return OSError(
        errno.ECONNREFUSED, f"Connect call failed ('{NODE_ADDRESS}', {NODE_SSH_PORT})"
    )


async def fleet_with_user(client, session, reality_params, ws_params):
    """Two reachable nodes, three transports between them, one user on all of them.

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
                "ssh_port": NODE_SSH_PORT,
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

    user_id = (await client.post("/api/users", json={"nickname": "kolya"})).json()["id"]
    return node_ids, user_id


# READ THIS BEFORE ADDING A TEST HERE — M28.16. ``fleet_with_user`` calls
# ``set_node_state`` through the test's OWN session, and ``Node.transports`` is
# ``lazy="selectin"``, so every node and every node-transport above lands in that
# session's identity map as it was BEFORE the revocation ran. The revocation writes
# through the request's own session, and with ``expire_on_commit=False`` a later ``get``
# or ``select`` here hands back the copy in the map instead of the row — so an assertion
# about what the push recorded is answered by a snapshot taken before it. The map holds
# WEAK references and ``Node``↔``NodeTransport`` back-populate each other into a
# reference cycle, so whether the stale copy is still there comes down to whether the
# cyclic collector has run: the same read passes alone and fails under the suite. Expire
# first, always — it costs one line and it is the difference between a test that can fail
# and one that cannot.


async def test_revoking_a_user_reports_instead_of_failing(
    client, session, reality_params, ws_params, accepting_nodes
) -> None:
    """The operator gets the outcome, on the operation whose whole purpose is reporting.

    Driven through the HTTP endpoint rather than through ``apply_node`` directly,
    because the defect this covers only exists on the path where the session has
    already committed a revocation — calling ``apply_node`` on a freshly selected node
    would not reproduce it.
    """
    node_ids, user_id = await fleet_with_user(client, session, reality_params, ws_params)

    response = await client.post(f"/api/users/{user_id}/revoke")

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

    node_ids, user_id = await fleet_with_user(client, session, reality_params, ws_params)

    await client.post(f"/api/users/{user_id}/revoke")

    # The note under ``fleet_with_user`` says why this line is not optional.
    session.expire_all()
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

    node_ids, user_id = await fleet_with_user(client, session, reality_params, ws_params)

    await client.post(f"/api/users/{user_id}/revoke")

    # The note under ``fleet_with_user`` says why this line is not optional. Without it
    # this test cannot fail: the copy in the map already says ``active``, so a revocation
    # that degraded every node it pushed to would still be read back as untouched.
    session.expire_all()
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

    # Pinned against the double ``accepting_nodes`` already installed, which was itself
    # pinned against the real ``restart`` — so the chain still reaches the real one.
    pinned(monkeypatch, node_stack, "restart", restart)


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

    pinned(monkeypatch, node_stack, "digest_of", digest_of)


async def test_an_unexpected_error_mid_push_is_reported_and_the_fan_out_continues(
    client, session, reality_params, ws_params, push_interrupted_on_one_node, caplog
) -> None:
    """One node's crash must not cost the operator the outcome of the others.

    This is criterion 6's reporting obligation: a fan-out that aborts on the first node
    says nothing about the rest, and the revoked user stays connected to every one of
    them with nobody aware of it.
    """
    caplog.set_level(logging.ERROR)
    node_ids, user_id = await fleet_with_user(client, session, reality_params, ws_params)

    response = await client.post(f"/api/users/{user_id}/revoke")

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

    # The note under ``fleet_with_user`` says why this line is not optional.
    session.expire_all()
    failed_node = await nodes.get_node(session, failed_id)
    assert failed_node.state == NodeState.DEGRADED
    assert "MissingGreenlet" in (failed_node.state_detail or "")


async def test_an_unexpected_error_after_the_push_leaves_the_node_alone(
    client, session, reality_params, ws_params, bookkeeping_fails_on_one_node, caplog
) -> None:
    """A node that WAS configured is reported as not updated, but not degraded.

    The distinction is the whole reason the widened catch lives in two places: degrading
    a node that is serving perfectly well would take it out of every user's
    subscription over a bug in our own bookkeeping.
    """
    caplog.set_level(logging.ERROR)
    node_ids, user_id = await fleet_with_user(client, session, reality_params, ws_params)

    response = await client.post(f"/api/users/{user_id}/revoke")

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

    # The note under ``fleet_with_user`` says why this line is not optional.
    session.expire_all()
    failed_node = await nodes.get_node(session, failed_id)
    assert failed_node.state == NodeState.ACTIVE
    assert failed_node.state_detail is None


@pytest.fixture
def a_connection_error_naming_the_node(accepting_nodes, monkeypatch: pytest.MonkeyPatch) -> None:
    """The FIRST node fails inside the push window with an error that CARRIES its address.

    The point of this fixture, and the reason it exists next to
    ``push_interrupted_on_one_node`` rather than replacing it: that one injects a
    ``MissingGreenlet``, whose message is about greenlets and has never named a host. So
    the guard asserting the node's address does not reach the operator was asserting the
    absence of something that was never present, and a later step "harmonising" the
    broad catch's message by putting ``{exc}`` back would reintroduce the leak with this
    suite still green.

    This is the real shape. A TCP-level failure out of the SSH layer is an ``OSError``
    whose ``str()`` is ``[Errno 111] Connect call failed ('<host>', <port>)`` — the
    reviewer of M4.3 reproduced exactly that — and ``OSError`` is not ``NodeUnreachable``,
    so it reaches the broad catch unsanitised. Raised from ``restart`` because that is
    inside the connection block; where in the window it comes from is not the point.
    """
    restarts = {"count": 0}

    async def restart(connection) -> None:
        restarts["count"] += 1
        if restarts["count"] == 1:
            raise a_refused_connection()

    pinned(monkeypatch, node_stack, "restart", restart)


async def test_an_unexpected_error_never_carries_the_node_address_outward(
    client, session, reality_params, ws_params, a_connection_error_naming_the_node, caplog
) -> None:
    """A node's address must not travel with the failure — M4.3's rule, now testable.

    The broad catch reports ``type(exc).__name__`` and never ``str(exc)``, deliberately
    and unlike its neighbouring arms, whose messages are written by us or by ``edge``
    and name no host. This string is BOTH an API response and a stored ``state_detail``,
    so both are checked: a node's address in the panel is a step towards the one record
    the charter forbids (core invariants §4 and §6), and the database keeps it until
    someone re-applies.
    """
    # The guard has teeth only if what is injected really carries the address. Asserted
    # rather than assumed, because the version of this test that did assume it spent a
    # milestone proving nothing.
    assert NODE_ADDRESS in str(a_refused_connection())

    caplog.set_level(logging.ERROR)
    node_ids, user_id = await fleet_with_user(client, session, reality_params, ws_params)

    response = await client.post(f"/api/users/{user_id}/revoke")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["nodes_failed"]) == 1, body
    failed_id, reason = next(iter(body["nodes_failed"].items()))

    # The type name has to be there, or the operator is told nothing at all. It is the
    # whole of what they get, which is why the rest of this test is about what they must
    # not get.
    assert type(a_refused_connection()).__name__ in reason, reason
    assert NODE_ADDRESS not in response.text, (
        "the node's address reached the operator inside the failure message"
    )

    from control.app.services import nodes

    # The note under ``fleet_with_user`` says why this line is not optional.
    session.expire_all()
    failed_node = await nodes.get_node(session, failed_id)
    assert failed_node.state == NodeState.DEGRADED
    assert NODE_ADDRESS not in (failed_node.state_detail or ""), (
        "the node's address was written into the database as its state detail"
    )
    # The full text is not lost, only kept out of operator-facing strings.
    assert any(record.exc_info for record in caplog.records), "no traceback was logged"
