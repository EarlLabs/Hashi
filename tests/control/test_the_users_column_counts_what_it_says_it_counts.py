"""The Users table's coverage column names the unit it counts — M23, round 8.

WHAT: the column that reads ``2 / 2`` beside a person, and the word above it.
WHY:  measured on the owner's real hosts. The header said *nodes served* and the figure
      counted node-transports, so a fleet with ONE node in service and two protocols on it
      told the operator a person was served on two nodes. Every other figure on this
      console is a fact about our own configuration stated in the operator's own words;
      this one stated a different fact from the one it named.

      The number is the useful one and it is what stayed: a user's link carries one entry
      per protocol per node, so a person missing the second protocol on the only node in
      the fleet is a fault this column can show. Counting distinct nodes instead would have
      read ``1 / 1`` over exactly that fault, which is why the header moved and the
      arithmetic did not.
HOW:  real Postgres, one node in service running two user-facing transports, one user.
      Nothing is dialled and nothing is rendered onto a host.
"""

from sqlalchemy import select

from control.app.models import Credential, NodeState
from control.app.services import console, nodes

# RFC 5737 documentation address, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.85"

# What the column said about a unit it was not counting.
THE_OLD_HEADER = "nodes served"


async def one_node_two_transports(client, session, reality_params, ws_params) -> str:
    """One serving node running two user-facing protocols, and one user on both."""
    created = await client.post(
        "/api/nodes",
        json={"name": "leaf-nl", "address": NODE_ADDRESS, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    node_id = created.json()["id"]
    for transport, params in (
        ("vless-reality", reality_params),
        ("vless-ws-tls", ws_params),
    ):
        enabled = await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": transport, "params": params},
        )
        assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    user = await client.post("/api/users", json={"nickname": "anna"})
    assert user.status_code == 201, user.text
    return node_id


async def test_the_header_names_the_unit_the_figure_counts(
    client, session, reality_params, ws_params
) -> None:
    """The finding: one node in service, and the column reads two of something.

    Red against the previous commit: the header said *nodes served* over ``2 / 2``, with
    ``GET /api/nodes`` returning a fleet of one.
    """
    await one_node_two_transports(client, session, reality_params, ws_params)

    assert len((await client.get("/api/nodes")).json()) == 1, (
        "the fleet is not one node, so this proves nothing about the word above the column"
    )
    table = await client.get("/panel/users/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert THE_OLD_HEADER not in said, (
        "the column still says nodes over a figure counting node-transports"
    )
    assert "transports served" in said, said
    assert "2 / 2" in said, said


async def test_the_figure_is_still_the_finer_one(
    client, session, reality_params, ws_params
) -> None:
    """And the arithmetic did not move, which is the half this fix must not lose.

    A person holding one of the two protocols on the one node in the fleet is under-served
    — their link is missing an entry — and the column says so: ``1 / 2``. Had the fix been
    to count distinct NODES instead of renaming the header, this row would read ``1 / 1``
    and the fault would be invisible on a fleet of one node, which is most fleets here.

    The missing credential is made by deleting the row, because the product does not
    produce one on purpose: granting covers every serving row and a failure that leaves a
    gap is exactly what this column is for.
    """
    await one_node_two_transports(client, session, reality_params, ws_params)

    covered = await console.user_rows(session)
    assert [(row.transports_served, row.transports_serving) for row in covered] == [(2, 2)]

    held = (await session.execute(select(Credential))).scalars().unique().all()
    assert len(held) == 2, held
    await session.delete(held[0])
    await session.commit()

    session.expire_all()
    after = await console.user_rows(session)
    assert [(row.transports_served, row.transports_serving) for row in after] == [(1, 2)], (
        "a person missing one of the two protocols on the only node in the fleet does not "
        "read as short of one"
    )
