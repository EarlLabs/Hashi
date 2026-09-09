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
"""

import pytest

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
