"""The config cell stops reassuring about the one node it can never reconcile — M23.

WHAT: what the Nodes screen's ``config`` column says about a node the state machine will
      not put back into service.
WHY:  measured on the owner's real hosts, round 8. The table read

          ams-leaf | 172.20.0.6 | active  | 2 / 2 drifted
          old-leaf | 172.20.0.7 | retired | in sync

      with five users revoked since ``old-leaf``'s last apply. The cell is not merely
      unaware — a node nothing was ever pushed to reads ``nothing enabled``, and a live
      node with an unapplied change reads ``2 / 2 drifted``. For the one host this control
      plane can never push to again it printed the reassuring answer, on the screen the
      Users banner sends the operator to when a withdrawal cannot be confirmed.

      The arithmetic behind ``in sync`` was correct: nothing had changed the intent for
      that node, because the people revoked since had never been granted on it. What is
      wrong is the sentence. Whatever that host was last given is what it is still
      running, and no press on this panel replaces it.
HOW:  real Postgres, ``accepting_nodes`` for the apply that must land, and the state
      endpoint for the retirement — the way an operator records that a host is gone.
      Nothing is dialled and nothing about a host is proved: the claim is about what one
      cell says.
"""

from control.app.models import NodeState
from control.app.services import console, nodes

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. Never dialled.
NODE_ADDRESS = "192.0.2.80"

USER_TRANSPORT = "vless-reality"

# The answer this cell may not give about a host nothing reaches. Written out rather than
# imported, because it is the word an operator read on the real fleet.
THE_REASSURANCE = "in sync"


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


async def an_applied_node(client, reality_params, *, name: str) -> str:
    """A node that really took a push, so its cell reads ``in sync`` before anything else."""
    node_id = await a_node(client, name=name)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": USER_TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    return node_id


async def retire(client, node_id: str) -> None:
    """Record that the host is gone, the way the operator does — the state endpoint."""
    retired = await client.post(
        f"/api/nodes/{node_id}/state",
        json={"state": "retired", "detail": "the host is gone"},
    )
    assert retired.status_code == 200, retired.text


async def test_a_retired_node_is_not_reported_in_sync(
    client, session, reality_params, accepting_nodes
) -> None:
    """The finding itself, on the service that composes the cell.

    Red against the previous commit: ``in sync``, because the digest it last took is the
    digest this control plane would render for it now — an arithmetic answer to a question
    nobody can act on.
    """
    node_id = await an_applied_node(client, reality_params, name="old-leaf")

    session.expire_all()
    before = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, before) == console.IN_SYNC, (
        "the node did not read in sync before it was retired, so this test would pass "
        "without the change it is about"
    )

    await retire(client, node_id)

    session.expire_all()
    after = await nodes.get_node(session, node_id)
    assert after.state == NodeState.RETIRED
    assert await console.drift_of(session, after) == console.CANNOT_BE_RECONCILED


async def test_the_nodes_screen_says_what_is_left_to_do_about_that_host(
    client, session, reality_params, accepting_nodes
) -> None:
    """And on the screen, which is where the Users banner sends the operator.

    The cell is the only thing on that row that can carry this: the state tag says
    ``retired``, which is what the operator recorded, and the ``why`` line under it is
    their own note. Neither says that nothing will ever be pushed there again.
    """
    await retire(client, await an_applied_node(client, reality_params, name="old-leaf"))

    table = await client.get("/panel/nodes/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert THE_REASSURANCE not in said, (
        "the screen calls a host nothing reaches in sync, over a configuration no press "
        "on this panel can replace"
    )
    assert console.CANNOT_BE_RECONCILED in said, said
    # It ends where the Users screen's own note about the same host ends: the only move
    # left is a new record for it.
    assert "register the host again" in said, said


async def test_the_cells_the_finding_measured_as_correct_do_not_move(
    client, session, reality_params, accepting_nodes
) -> None:
    """The neighbours, held to what they said — so this is a narrower cell, not a wider one.

    The walk named both: a node nothing was ever pushed to reads ``nothing enabled``, and
    a serving node whose configuration has moved since its last apply reads ``N / M
    drifted``. A guard that answered for every node out of service would have taken the
    second one away from a degraded host, which is the one that most needs it.
    """
    never_pushed = await a_node(client, name="fresh-1")
    drifting = await an_applied_node(client, reality_params, name="ams-leaf")

    # One more person, so the applied node's rendered config no longer matches the bytes
    # it was given: a peer block the host has not been told about.
    added = await client.post("/api/users", json={"nickname": "kolya"})
    assert added.status_code == 201, added.text

    session.expire_all()
    assert (
        await console.drift_of(session, await nodes.get_node(session, never_pushed))
        == console.NOTHING_ENABLED
    )
    moved = await console.drift_of(session, await nodes.get_node(session, drifting))
    assert "drifted" in moved, moved

    # And a degraded host — the state a failed push leaves — still reports the comparison,
    # because probe and apply do reach it and the number is what the operator acts on.
    await nodes.set_node_state(
        session, node_id=drifting, state=NodeState.DEGRADED, detail="the push failed"
    )
    session.expire_all()
    assert (
        await console.drift_of(session, await nodes.get_node(session, drifting)) == moved
    )
