"""Putting a node into service gives the people who are already here something on it — M23.

WHAT: what ``apply.apply_node`` does for existing users on the push that moves a node
      from draft (or degraded) into service.
WHY:  measured on the owner's own control plane on 2026-09-15, round 2 of the real-host
      walk. A node was registered, given a transport and applied; it went active, it was
      in sync, and the Keys screen read ``0 of 4`` on its row. One user existed from
      before it and held nothing on it; the two added afterwards held everything.

      The Nodes screen says the opposite in its own words, and that sentence is the
      product's central promise rather than a nicety:

          "Users hold one link covering whichever nodes are serving at the moment they
          refresh, so adding or replacing one asks nothing of them."

      Three other places already grant on this event — ``nodes.set_node_state``,
      ``nodes.enable_and_grant`` and ``nodes.set_transport_enabled`` — and this one did
      not, because ``apply_node`` sets the state itself rather than calling the function
      that carries the fan-out. It self-heals on the next unrelated mint, which is why it
      survived eleven milestones; what it costs is the charter's central case, an owner
      rotating away from a blocked node in a hurry and seeing nothing happen on it.
HOW:  the shared ``accepting_nodes`` harness (``conftest.py``), which stands in for the
      five ``edge.bootstrap.node_stack`` calls that touch a host and for nothing else. So
      what is proven here is this control plane's own bookkeeping after a push the host
      accepted — never that a daemon reloaded, and never that a tunnel carries.
"""

import pytest

from control.app.models import NodeState
from control.app.services import console, friends, nodes, subscriptions

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. It is never dialled — the
# connection is replaced — but a record has to name something and a routable address in a
# fixture is an accident waiting to happen.
NODE_ADDRESS = "192.0.2.70"

# The sentence on the Nodes screen this milestone had to make true. Written out rather
# than imported, because what is asserted is that the SCREEN still says it: importing it
# would make this agree with a rename instead of with the words an operator reads.
# It wraps in the markup, so it is compared as words rather than as one run — the
# template's line breaks are not part of what an operator reads.
THE_PROMISE = "so adding or replacing one asks nothing of them."


async def a_reachable_node(client, *, name: str) -> str:
    """A node with an SSH key on its record, so the push half runs to the end."""
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


async def holders_on(session, row_id: str) -> int:
    """How many users hold material on one row — the Keys screen's own count."""
    for row in await console.key_rows(session):
        if row.id == row_id:
            return row.holders
    raise AssertionError(f"no row {row_id} on the Keys screen")


@pytest.fixture
async def a_user_who_was_here_first(client) -> str:
    """One active user, registered before any node serves anything.

    Which is the ordinary order for the case this file is about: the fleet exists, the
    people exist, and a REPLACEMENT node arrives afterwards.
    """
    created = await client.post("/api/friends", json={"nickname": "boris"})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_the_nodes_screen_still_makes_this_promise(client) -> None:
    """The premise, stated first: this file exists to keep a sentence true.

    If the screen ever stops saying it, the behaviour below is a choice somebody should
    make deliberately rather than a promise this test is defending.
    """
    screen = await client.get("/panel/nodes")

    assert screen.status_code == 200, screen.text
    assert THE_PROMISE in " ".join(screen.text.split()), (
        "the Nodes screen no longer promises that adding a node asks nothing of a user — "
        "decide what the behaviour should be before deleting this file"
    )


async def test_an_apply_that_puts_a_node_into_service_grants_every_active_user(
    client, session, reality_params, accepting_nodes, a_user_who_was_here_first: str
) -> None:
    """The finding itself, on the surface the walk pressed.

    Red against the previous commit: the node goes active, the row is in sync, and the
    Keys screen reads ``0 of 1`` — the user who was here first holds nothing on the node
    that just went into service.
    """
    node_id = await a_reachable_node(client, name="bare")
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    row_id = enabled.json()["id"]
    # Nothing yet, and correctly: the node is a draft, so it serves nobody and there is
    # nothing to hold on it.
    assert await holders_on(session, row_id) == 0

    applied = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert applied.status_code == 200, applied.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.ACTIVE, node.state_detail
    assert await holders_on(session, row_id) == 1, (
        "the node is serving and the user who was here first holds nothing on it"
    )

    # And the half a person actually receives: their one link now resolves to this node.
    friend = await friends.get_friend(session, a_user_who_was_here_first)
    assert await subscriptions.entries_for(session, friend), (
        "the user's subscription is still empty over a node that is serving"
    )


async def test_the_same_apply_on_a_node_already_serving_changes_nothing(
    client, session, reality_params, accepting_nodes, a_user_who_was_here_first: str
) -> None:
    """A re-apply is not a second grant, and must not become one.

    The fan-out is idempotent by construction (``friends.grant_everywhere`` skips a row a
    user already holds), and the guard above it asks whether this apply is what put the
    node into service. Both matter: the guard is what keeps an ordinary re-push from
    walking the whole fleet, and the idempotence is what makes it safe when it does.
    """
    node_id = await a_reachable_node(client, name="already-serving")
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    row_id = enabled.json()["id"]
    first = await client.post(f"/api/nodes/{node_id}/apply")
    assert first.status_code == 200, first.text
    assert await holders_on(session, row_id) == 1

    again = await client.post(f"/api/nodes/{node_id}/apply")

    assert again.status_code == 200, again.text
    session.expire_all()
    assert await holders_on(session, row_id) == 1, (
        "a second apply minted a second credential for the same person on one row"
    )


async def test_an_apply_that_fails_grants_nobody(
    client, session, reality_params, a_user_who_was_here_first: str
) -> None:
    """The fail-closed half, without which the fix would be worse than the finding.

    A node whose push failed is degraded and is in nobody's subscription, so material
    minted for it would be a credential for a host that was never configured — and, on a
    transport that hands out addresses, an allocation nobody can use.

    No ``accepting_nodes`` here: the node has no SSH key, so ``target_for`` refuses before
    anything is dialled, which is the cheapest real failure this suite has.
    """
    created = await client.post(
        "/api/nodes",
        json={"name": "unreachable", "address": NODE_ADDRESS, "location_label": "Testland"},
    )
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    row_id = enabled.json()["id"]

    failed = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert failed.status_code == 200, failed.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DEGRADED, node.state
    assert await holders_on(session, row_id) == 0, (
        "a node that could not be configured minted material for somebody anyway"
    )
