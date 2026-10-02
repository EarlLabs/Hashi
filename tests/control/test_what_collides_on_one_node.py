"""What two transports on one node may and may not share — M15, and M17.1c.

WHAT: the uniqueness rule after it moved off ``(node, transport_name)`` and onto the
      listening port, the config file's name — and, since M17.1c, the tunnel's own
      range.
WHY:  the old rule was enforced in terms of the wrong concept, at the worst moment, with
      no way to undo the state that triggered it. It made the runbook's own advice
      impossible: AmneziaWG is mandated for the entry→leaf hop and recommended for
      users on the same box, so the first one enabled excluded the other forever.
HOW:  through the real services and a real database. The half that cannot be proven here
      is whether two daemons on one host actually come up — that is the owner's field
      check, and nothing in this file claims it. What IS proven is that the control plane
      writes two rows, renders two configs, places them at two paths and asks for two
      interface names the kernel would accept.

      THE RANGE RULE IS M17.1c AND LIVES HERE because it is the same question asked of
      the same function: what may two transports on one node share. It is the one of the
      three with a person on the other end of it — two tunnels whose ranges meet can hand
      two users the same address, and the host's single routing table then sends one
      of them the other's traffic. No rendered file shows it, because each file is
      correct on its own.
"""

import pytest
from sqlalchemy import select, text

from control.app.errors import Conflict
from control.app.models import Credential, NodeTransport
from control.app.services import apply, console, nodes, placement, rotation
from control.app.services import transports as transports_service
from edge.bootstrap import node_stack

HOP_TRANSPORT = "amneziawg"

# Two ports, because one node cannot have one. Neither is a value this codebase would
# ship — they are typed here the way an operator types them into the form.
USER_PORT = 51820
HOP_PORT = 51821

# How many users a user-facing row of this transport may hand an address to — M17.
# Far above anything this file creates, and comfortably inside the /24s below: nothing
# here is about the pool, and a size that only just fitted would turn a port test red the
# day somebody adds a user to it. A HOP end takes none of this: a hop is a pair of peers,
# so ``POST /api/hops`` neither asks for a size nor accepts one.
POOL_SIZE = 100


@pytest.fixture
def wg_params() -> dict[str, object]:
    """The operator-supplied half of one wg-quick-family end. Material is minted."""
    return {
        "port": USER_PORT,
        "tunnel_address": "10.70.0.1/24",
        "peer_tunnel_address": "10.70.0.2/24",
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
        "init_packet_magic_header": 1020327352,
        "response_packet_magic_header": 2060487442,
        "underload_packet_magic_header": 3679305607,
        "transport_packet_magic_header": 1436947798,
    }


async def a_node(client, name: str, address: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def offered(client, node_id: str, params: dict) -> dict:
    """The runbook's one-box install: this transport, offered to users, on this box."""
    response = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": params,
            "pool_size": POOL_SIZE,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def the_hop_an_entry_box_would_dial(client, wg_params):
    """A box offering the transport to users, and the hop it then asks to dial.

    The runbook's own sequence, and the whole of what this file was written around: the
    product refused it with a 409 about UNIQUENESS until M15 moved that rule onto the
    port. It is refused again since M25 and for an unrelated reason — an entry node's
    users leave through its hop, and a kernel tunnel cannot carry somebody else's
    packets there — so the response is RETURNED rather than asserted, and the one test
    below that is about the entry side reads it.

    Every other test in this file needs only "one node, two rows of one transport", which
    is the same arrangement on the side of the tunnel that waits: see
    ``a_leaf_carrying_both``.
    """
    entry_id = await a_node(client, "box-1", "192.0.2.90")
    leaf_id = await a_node(client, "far-1", "192.0.2.91")
    await offered(client, entry_id, wg_params)

    hop_side = {
        **wg_params,
        "port": HOP_PORT,
        "tunnel_address": "10.71.0.1/24",
        "peer_tunnel_address": "10.71.0.2/24",
    }
    return await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": hop_side,
            "leaf_params": {
                **hop_side,
                "tunnel_address": "10.71.0.2/24",
                "peer_tunnel_address": "10.71.0.1/24",
            },
        },
    )


async def a_leaf_carrying_both(client, wg_params) -> tuple[str, dict, dict]:
    """A node offering the transport to users AND holding the LEAF end of a hop.

    THE arrangement this file is about: two rows of one transport on one node, two ports,
    two config names and two ranges. It is the side of the tunnel that WAITS, and since
    M25 that is the only side of it there is — an ENTRY node's users must leave through
    the hop, which a kernel tunnel cannot express for them, so the panel now refuses to
    build that pair at either door rather than accepting it and refusing the apply. A
    leaf has no hop of its own, so its users exit from it as they always have, which is
    route B and is what nine field walks were carried on.

    Returns the node holding both rows, its user-facing row and the hop's body — in
    which the end ON THAT NODE is ``hop["leaf"]``.
    """
    entry_id = await a_node(client, "dialer-1", "192.0.2.80")
    leaf_id = await a_node(client, "landing-1", "192.0.2.81")
    user_row = await offered(client, leaf_id, wg_params)

    hop_side = {
        **wg_params,
        "port": HOP_PORT,
        "tunnel_address": "10.76.0.1/24",
        "peer_tunnel_address": "10.76.0.2/24",
    }
    established = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": hop_side,
            "leaf_params": {
                **hop_side,
                "tunnel_address": "10.76.0.2/24",
                "peer_tunnel_address": "10.76.0.1/24",
            },
        },
    )
    assert established.status_code == 201, established.text
    return leaf_id, user_row, established.json()


# --- what is now allowed ------------------------------------------------------

async def test_one_node_carries_a_user_facing_and_a_hop_end_of_one_transport(
    client, wg_params
) -> None:
    """The sequence that answered 409 in the field, and the rows it now writes.

    On the leaf since M25, which is where this pair can actually stand — the entry side
    of it is refused at the door now, by a rule about the exit rather than about
    uniqueness (see the entry-side test below). Nothing about M15's own answer changed:
    one node, two rows, one transport, two ids.
    """
    node_id, user_row, hop = await a_leaf_carrying_both(client, wg_params)

    assert hop["leaf"]["node_id"] == node_id
    assert hop["leaf"]["transport_name"] == user_row["transport_name"]
    assert hop["leaf"]["id"] != user_row["id"]


async def test_the_two_rows_are_placed_under_two_names(client, wg_params) -> None:
    """The names are what stops them being one file and one network interface.

    The user-facing row keeps the transport's own name, which is what every node
    already in the field has on disk — a scheme that renamed it would take the interface
    down under a running daemon on the next apply.
    """
    _, user_row, hop = await a_leaf_carrying_both(client, wg_params)

    assert user_row["config_name"] == HOP_TRANSPORT
    assert hop["leaf"]["config_name"] != user_row["config_name"]
    # The entry is a fresh node, so it keeps the plain name: the rule is per node.
    assert hop["entry"]["config_name"] == HOP_TRANSPORT


async def test_the_two_rows_render_to_two_files_the_node_can_actually_run(
    client, session, wg_params
) -> None:
    """Two configs, two paths, two compose services, two legal interface names.

    This is the assertion the decision rests on. ``render_for_node`` keys by the placed
    name rather than the transport's, so a node running two of one transport gets two
    entries instead of the second silently replacing the first — and ``services_for``
    then gives each its own file and its own container.

    Driven from the LEAF side, because that is the side of this shape that renders at
    all — and, since M25, the only side the panel will build it on: see the entry-side
    test below.
    """
    leaf_id, _, _ = await a_leaf_carrying_both(client, wg_params)
    node = await nodes.get_node(session, leaf_id)

    configs = await apply.render_for_node(session, node)
    placed = await apply.placed_transports(session, node)
    assert len(configs) == 2, configs.keys()
    assert set(configs) == set(placed)
    assert set(placed.values()) == {HOP_TRANSPORT}

    services = node_stack.services_for(configs, transports=placed)
    paths = {service["config_path"] for service in services}
    assert len(paths) == 2, paths
    # Each daemon is told to load the file that was written for it, and no other.
    for service in services:
        assert service["command"][-1] == service["config_path"]
        assert service["config_path"].endswith(".conf")
        # The stem is the interface name for this family, and the kernel's rule applies
        # to it — asked of ``edge``, which owns that rule.
        stem = service["config_path"].rsplit("/", 1)[-1].removesuffix(".conf")
        assert node_stack.config_name_is_usable(HOP_TRANSPORT, stem), stem

    # And the two files are genuinely different configurations rather than one rendered
    # twice: the hop end dials a peer, the user-facing end waits for devices.
    assert len(set(configs.values())) == 2


async def test_an_entry_box_is_not_given_a_kernel_tunnel_for_its_users_at_all(
    client, wg_params
) -> None:
    """The OTHER refusal on this shape, which M15 does not remove — and which M25 moved.

    It used to be at the APPLY. The two rows were written, the ``409`` about uniqueness
    was gone, and the entry node then could not be rendered: a kernel tunnel hands its
    packets to the node's own routing stack, so an entry node's users cannot be made to
    leave through a hop on a different interface, and ``edge`` refuses that out loud
    rather than writing a file that would send a user in Russia out of the Russian node
    (``edge/egress.py``, M14.3 and decision 3).

    That refusal is correct and is untouched. What M25's walk measured is what it cost to
    arrive so late: the row was accepted, every active user was granted a credential on
    it, and one of them was handed a complete configuration file for a node that could
    never be applied. So the same rule is now asked at both doors, and this file's own
    sequence — offer the transport to users on the entry box, then hop from it — is
    answered where the operator is standing. The 409 is back and it is a different 409:
    not "already configured", which was M15's defect, but "this node's users would have
    no way out", with both moves out of it named.

    What the doors do NOT do is un-write a node that is already in that state. The render
    refusal is therefore still the thing standing between such a node and a user's
    traffic in the wrong country, and it is asserted in
    ``tests/control/test_both_doors_refuse_a_user_with_no_way_out.py`` — on a row put
    there by hand, because no surface of this product will produce one now.
    """
    refused = await the_hop_an_entry_box_would_dial(client, wg_params)

    assert refused.status_code == 409, refused.text
    body = refused.json()["error"]
    assert body["code"] == "no_exit_through_the_hop"
    # The operator is told what to do about it, and both answers are named.
    assert "re-originates" in body["message"], body["message"]
    assert "remove that transport" in body["message"], body["message"]


# --- what is refused instead --------------------------------------------------

async def test_two_transports_on_one_node_may_not_share_a_port(
    client, wg_params
) -> None:
    """One port, one bind: the data planes run with ``network_mode: host``."""
    node_id = await a_node(client, "port-1", "192.0.2.92")
    await offered(client, node_id, wg_params)

    collided = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": {
                **wg_params,
                "tunnel_address": "10.72.0.1/24",
                "peer_tunnel_address": "10.72.0.2/24",
            },
            "pool_size": POOL_SIZE,
        },
    )

    assert collided.status_code == 409, collided.text
    assert collided.json()["error"]["code"] == "conflict"
    message = collided.json()["error"]["message"]
    assert str(USER_PORT) in message, message
    assert "port-1" in message, message


async def test_a_hop_end_is_refused_over_the_port_the_node_already_listens_on(
    client, wg_params
) -> None:
    """The same rule at the other creation path, so the two cannot disagree.

    ON THE LEAF END SINCE M25, and the move is not a weakening: the node that already
    offers the transport to users has to be the one that WAITS, because a node that
    DIALS a hop is refused this transport for its users before any port is looked at
    (see the entry-side test above). The rule under test is unchanged — a hop end may not
    take a port its own node already binds — and it is asked of the same call on the same
    path. What changed is which of two refusals a submission with both faults meets
    first, and the order is deliberate: a port can be retyped, and an arrangement that
    cannot carry traffic cannot.
    """
    entry_id = await a_node(client, "port-2", "192.0.2.93")
    leaf_id = await a_node(client, "far-2", "192.0.2.94")
    await offered(client, leaf_id, wg_params)

    hop_side = {
        **wg_params,
        "tunnel_address": "10.73.0.1/24",
        "peer_tunnel_address": "10.73.0.2/24",
    }
    collided = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": hop_side,
            # The port the leaf node already offers to users.
            "leaf_params": {
                **hop_side,
                "tunnel_address": "10.73.0.2/24",
                "peer_tunnel_address": "10.73.0.1/24",
            },
        },
    )

    assert collided.status_code == 409, collided.text
    assert collided.json()["error"]["code"] == "conflict"
    assert str(USER_PORT) in collided.json()["error"]["message"]


async def test_a_switched_off_transport_still_holds_its_port(
    client, session, wg_params
) -> None:
    """Disabled is not removed, and its port is still spoken for.

    Freeing the port when a row is switched off would move the collision to the moment
    it is switched back on — the same "found months later" failure M15 exists to close.
    Removing a row is what frees it, and the removal is asserted below
    (``test_removing_a_transport_frees_the_port_and_the_name_it_held``).
    """
    node_id = await a_node(client, "off-1", "192.0.2.95")
    row = await offered(client, node_id, wg_params)
    await nodes.set_transport_enabled(session, node_transport_id=row["id"], enabled=False)
    await session.commit()

    with pytest.raises(Conflict):
        await nodes.enable_transport(
            session,
            node_id=node_id,
            transport_name=HOP_TRANSPORT,
            params={
                **wg_params,
                "tunnel_address": "10.74.0.1/24",
                "peer_tunnel_address": "10.74.0.2/24",
            },
        )


async def test_retyping_a_port_onto_one_the_node_already_uses_is_refused(
    client, session, wg_params
) -> None:
    """The third path that writes a port, held to the same rule.

    A row may still be given back the port it already has — it is excluded from its own
    check — which is what a form resubmitted unaltered does.
    """
    _, _, hop = await a_leaf_carrying_both(client, wg_params)

    with pytest.raises(Conflict):
        await rotation.replace_params(
            session,
            node_transport_id=hop["leaf"]["id"],
            params={transports_service.PORT_FIELD: USER_PORT},
        )


# --- and the range the tunnel hands addresses out of (M17.1c) -----------------
#
# The third thing that collides, and the only one whose failure has a victim: the port
# rule stops a container that will not start, the name rule stops two files at one path,
# and this one stops one user's return traffic arriving at another user's device.
# Everything here goes through the same ``placement`` call as the two above.

async def test_two_tunnels_on_one_node_may_not_share_a_range(
    client, session, wg_params
) -> None:
    """A second tunnel over the first one's addresses, refused before the row exists.

    Its own port, so the older refusal is not what answers — this is the range and
    nothing else. What the operator is told names both ranges and the transport already
    holding one, all three of which are already on their own screens, and no address any
    person holds.
    """
    node_id = await a_node(client, "range-1", "192.0.2.110")
    await offered(client, node_id, wg_params)

    collided = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": {**wg_params, "port": HOP_PORT},
            "pool_size": POOL_SIZE,
        },
    )

    assert collided.status_code == 409, collided.text
    assert collided.json()["error"]["code"] == "conflict"
    message = collided.json()["error"]["message"]
    assert "range-1" in message and HOP_TRANSPORT in message, message
    assert wg_params["tunnel_address"] in message, message

    # And the row was not written: the refusal is before the placement, not after it.
    session.expire_all()
    rows = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().all()
    assert len(rows) == 1, rows


async def test_a_range_that_merely_contains_the_other_is_the_same_collision(
    client, wg_params
) -> None:
    """The comparison is of NETWORKS, not of the two addresses.

    ``10.70.0.1/24`` and ``10.70.9.1/16`` are two addresses that look nothing alike and
    two ranges that overlap completely — the second's prefix swallows the first. This is
    the case a string comparison, or a comparison of the two addresses, would let
    through, and it is the one an operator writes by accident: a prefix typed wide.
    """
    node_id = await a_node(client, "range-2", "192.0.2.111")
    await offered(client, node_id, wg_params)

    collided = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": {
                **wg_params,
                "port": HOP_PORT,
                "tunnel_address": "10.70.9.1/16",
                "peer_tunnel_address": "10.70.9.2/16",
            },
            "pool_size": POOL_SIZE,
        },
    )

    assert collided.status_code == 409, collided.text
    assert "10.70.9.1/16" in collided.json()["error"]["message"]


async def test_a_hop_end_may_not_be_laid_over_a_tunnel_the_node_already_carries(
    client, session, wg_params
) -> None:
    """The same rule at the other creation path, so the two cannot disagree.

    The runbook puts a user-facing tunnel and a hop end on ONE entry box, which is the
    shape M15 unlocked — and it is exactly the shape this rule matters in: both data
    planes are on that host, writing into one routing table.
    """
    entry_id = await a_node(client, "range-3", "192.0.2.112")
    leaf_id = await a_node(client, "far-3", "192.0.2.113")
    await offered(client, entry_id, wg_params)

    hop_side = {**wg_params, "port": HOP_PORT}
    collided = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": HOP_TRANSPORT,
            "entry_params": hop_side,
            "leaf_params": {
                **hop_side,
                "tunnel_address": "10.70.0.2/24",
                "peer_tunnel_address": "10.70.0.1/24",
            },
        },
    )

    assert collided.status_code == 409, collided.text
    assert "range-3" in collided.json()["error"]["message"]
    session.expire_all()
    on_the_entry = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == entry_id)
        )
    ).scalars().unique().all()
    assert len(on_the_entry) == 1, "a refused hop wrote an end anyway"


async def test_retyping_a_tunnel_onto_one_the_node_already_carries_is_refused(
    client, session, wg_params
) -> None:
    """The third path that writes a range, held to the same rule — M17.1c.

    A hop end moved onto the user-facing tunnel's own range. It is the path that had
    nothing at all: enabling and establishing both went through ``placement.claim``, and
    replacing a parameter went through neither, so a range that could not be typed into
    the form could still be typed into this one.
    """
    _, _, hop = await a_leaf_carrying_both(client, wg_params)

    with pytest.raises(Conflict) as refused:
        await rotation.replace_params(
            session,
            node_transport_id=hop["leaf"]["id"],
            params={"tunnel_address": "10.70.0.9/24"},
        )
    assert HOP_TRANSPORT in str(refused.value)

    # And the row still holds what it held: a refusal here changes nothing.
    session.expire_all()
    moved = await session.get(NodeTransport, hop["leaf"]["id"])
    assert moved.params["tunnel_address"] == "10.76.0.2/24"


async def test_a_node_whose_two_ranges_already_meet_can_still_be_rotated(
    client, session, wg_params
) -> None:
    """The rule refuses new overlaps — it does not seal a node that already has one.

    Every node in the field pre-dates this rule, so the state it forbids can exist
    already. Re-asking it of a parameter the operator did not touch made every
    replacement on either row answer with a sentence about a RANGE to somebody who
    retyped a PORT — and that is not a cosmetic loss: rotating away from a blocked value
    is the charter's first job for the operator, and sizing a pre-M17 row through this
    same call is what migration 0006 promises them in writing. The refusal's own remedy
    ("give this tunnel a range of its own") is refused in turn by the addresses in hand,
    so the only exit left was deleting a row, with its credentials or the mandated hop
    end inside it.

    The overlap is written by hand because no surface can produce one any more, which is
    the point: this is the upgrade path, not a state the product still creates.
    """
    _, user_row, hop = await a_leaf_carrying_both(client, wg_params)
    end = await session.get(NodeTransport, hop["leaf"]["id"])
    end.params = {
        **end.params,
        "tunnel_address": "10.70.5.1/16",
        "peer_tunnel_address": "10.70.5.2/16",
    }
    await session.commit()

    replaced = await rotation.replace_params(
        session, node_transport_id=user_row["id"], params={"port": 51999}
    )

    assert replaced.rotated == ["port"]
    session.expire_all()
    assert (await session.get(NodeTransport, user_row["id"])).params["port"] == 51999

    # And the rule itself is untouched: a range that MOVES is still measured against
    # every other tunnel on the node, overlap already present or not.
    with pytest.raises(Conflict):
        await rotation.replace_params(
            session,
            node_transport_id=user_row["id"],
            params={"tunnel_address": "10.70.0.1/23"},
        )


async def test_a_switched_off_transport_still_holds_its_range(
    client, session, wg_params
) -> None:
    """Disabled is not removed — its range is still spoken for, exactly as its port is.

    Freeing it when a row is switched off would move the collision to the moment the row
    is switched back on, which for this rule is the moment two people are holding one
    address with nothing red anywhere.
    """
    node_id = await a_node(client, "range-off", "192.0.2.114")
    row = await offered(client, node_id, wg_params)
    await nodes.set_transport_enabled(session, node_transport_id=row["id"], enabled=False)
    await session.commit()

    with pytest.raises(Conflict):
        await nodes.enable_transport(
            session,
            node_id=node_id,
            transport_name=HOP_TRANSPORT,
            params={**wg_params, "port": HOP_PORT},
            pool_size=POOL_SIZE,
        )


# --- the schema holds the same rule -------------------------------------------

async def test_the_database_holds_the_half_of_the_rule_it_can_hold(session) -> None:
    """The config name is a constraint. The port is not, and that is the decision.

    Read out of Postgres rather than off the model, because the claim is about the
    database an operator's script talks to: a rule that lives only in Python is one a
    fixture, a migration or a future service walks around.

    The absent one is asserted too. A unique index over ``(node_id, params ->> 'port')``
    would be WRONG rather than merely strict — it cannot see which transport-layer
    protocol a row binds, so it refuses a TCP transport and a UDP transport sharing a
    port number, which collide over nothing. A pre-M15 database is free to hold exactly
    that pair, and ``deploy/docker/entrypoint.sh`` runs ``alembic upgrade head`` on every
    boot, so such an index would have turned sound data into a control plane that does
    not start.
    """
    names = set(
        (
            await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'node_transports'"
                )
            )
        ).scalars()
    )

    assert "uq_node_transport_config_name" in names
    # The rule that was replaced is gone rather than left beside the new one: two rules
    # about the same thing is how one of them stops being true.
    assert "uq_node_transport" not in names
    assert "uq_node_transport_port" not in names


async def test_a_tcp_and_a_udp_transport_may_share_one_port_number(
    client, wg_params, reality_params
) -> None:
    """A port number is not a port, and the runbook puts this pair within reach.

    ``docs/deploy/runbook.md`` names 8443 as a port Reality validates on, and the
    obfuscated UDP transport's own range covers it. Two sockets, no bind conflict — and
    a refusal here would be the M15 defect pointed the other way: a rule expressed in
    terms of the wrong concept, namely the number rather than the number AND the
    protocol.
    """
    node_id = await a_node(client, "layers-1", "192.0.2.85")
    shared = reality_params[transports_service.PORT_FIELD]

    tcp = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert tcp.status_code == 201, tcp.text

    udp = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": {**wg_params, "port": shared},
            "pool_size": POOL_SIZE,
        },
    )

    assert udp.status_code == 201, udp.text
    # And the two declarations that make it true are what was consulted, not a name.
    assert placement.binds_of("vless-reality").isdisjoint(
        placement.binds_of(HOP_TRANSPORT)
    )


async def test_the_port_a_row_holds_is_compared_as_the_database_would(
    client, session, wg_params
) -> None:
    """``8443`` and ``"8443"`` are one port, whatever a transport stored it as.

    Every shipped transport declares an ``int`` and pydantic coerces, so this is a
    property of ``params`` being a document the transport owns rather than a live bug —
    which is exactly why it is asserted rather than assumed.
    """
    assert placement.port_of({transports_service.PORT_FIELD: 8443}) == "8443"
    assert placement.port_of({transports_service.PORT_FIELD: "8443"}) == "8443"
    assert placement.port_of({}) is None


async def test_the_port_constraint_is_per_node_and_not_fleet_wide(
    client, wg_params
) -> None:
    """Two nodes listening on one port is the ordinary case, not a collision."""
    first = await a_node(client, "same-1", "192.0.2.96")
    second = await a_node(client, "same-2", "192.0.2.97")

    await offered(client, first, wg_params)
    await offered(client, second, wg_params)


# --- the name allocation ------------------------------------------------------

async def test_a_transport_that_names_no_port_collides_over_nothing(
    client, session, wg_params, settings
) -> None:
    """A row with no port in its parameters is not constrained by the port rule.

    Asked of the service rather than through a transport, because every transport this
    image ships declares a port. The behaviour has to be right anyway: a transport whose
    listener takes its address some other way has nothing to collide over, and refusing
    it would be this zone inventing a property its packages never declared.
    """
    node_id = await a_node(client, "noport-1", "192.0.2.98")
    node = await nodes.get_node(session, node_id)
    await offered(client, node_id, wg_params)

    assert placement.port_of({}) is None
    # No refusal, and the name offered is still the free one.
    assert await placement.claim(
        session, settings=settings, node=node, transport_name="vless-reality", params={}
    ) == "vless-reality"


async def test_the_second_instance_takes_a_name_the_kernel_would_accept(
    client, session, wg_params, settings
) -> None:
    """The suffixed name is ours to choose, so it is measured against the tool's rule."""
    node_id = await a_node(client, "name-1", "192.0.2.99")
    node = await nodes.get_node(session, node_id)
    await offered(client, node_id, wg_params)

    chosen = await placement.claim(
        session,
        settings=settings,
        node=node,
        transport_name=HOP_TRANSPORT,
        # ITS OWN RANGE as well as its own port, since M17.1c: a second tunnel on this
        # node may not be laid over the first one's addresses, and the refusals below say
        # why. Nothing about the NAME under test changes with it.
        params={
            **wg_params,
            "port": HOP_PORT,
            "tunnel_address": "10.78.0.1/24",
            "peer_tunnel_address": "10.78.0.2/24",
        },
    )

    assert chosen != HOP_TRANSPORT
    assert node_stack.config_name_is_usable(HOP_TRANSPORT, chosen), chosen


async def test_every_row_this_control_plane_writes_carries_a_placed_name(
    client, session, wg_params
) -> None:
    """No path may write a row without one — it is what the node's file is called."""
    await a_leaf_carrying_both(client, wg_params)

    rows = (await session.execute(NodeTransport.__table__.select())).all()
    assert rows
    for row in rows:
        assert row.config_name, row

    # And nothing was quietly renamed: a row's name is either its transport's or a
    # suffixed form of it, never something unrelated.
    for row in rows:
        assert row.config_name.startswith(row.transport_name), row


async def test_dissolving_a_hop_frees_what_it_held(client, session, wg_params) -> None:
    """Removal is what frees a port and a name, which is why M15.2 exists.

    Asserted on the path that already HAS a delete, so the rule is proven rather than
    assumed: after a hop is torn down its port is available on that node again.
    """
    node_id, _, hop = await a_leaf_carrying_both(client, wg_params)

    assert (await client.delete(f"/api/hops/{hop['leaf']['id']}")).status_code == 200

    reused = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": {
                **wg_params,
                "port": HOP_PORT,
                "tunnel_address": "10.75.0.1/24",
                "peer_tunnel_address": "10.75.0.2/24",
            },
            "pool_size": POOL_SIZE,
        },
    )

    assert reused.status_code == 201, reused.text
    assert reused.json()["config_name"] != HOP_TRANSPORT


# --- the operator can create it, read it back and reach it --------------------

async def test_the_console_tells_the_two_instances_apart(
    client, session, wg_params
) -> None:
    """Two rows of one transport must not be the same word twice on every screen.

    The whole complaint M15 makes about the old rule is that it was invisible. Unlocking
    the shape and then drawing it as two identical chips would be the same failure one
    screen over — so the placed name qualifies the label, and only where it differs, so
    nothing that existed before this milestone changes appearance.
    """
    leaf_id, _, _ = await a_leaf_carrying_both(client, wg_params)

    rows = await console.offers_on(session, leaf_id)
    labels = sorted(row.transport for row in rows)

    assert len(labels) == 2, labels
    assert len(set(labels)) == 2, labels
    assert HOP_TRANSPORT in labels, labels
    # The qualified one names the file on the host, which is the answer to "which of
    # these two am I looking at".
    qualified = next(label for label in labels if label != HOP_TRANSPORT)
    assert qualified.startswith(f"{HOP_TRANSPORT} ("), qualified

    # A node running ONE of a transport is untouched: no parentheses, no change.
    plain = await console.offers_on(session, await a_node(client, "solo-1", "192.0.2.86"))
    assert plain == []
    assert console.placed_as(HOP_TRANSPORT, HOP_TRANSPORT) == HOP_TRANSPORT


async def test_a_list_retyped_on_the_second_instance_is_still_read_as_a_list(
    client, session, reality_params
) -> None:
    """The replace dialog looks a transport up by ITS name, not by what the screen calls it.

    ``console.placed_as`` qualifies the second instance on a node as
    "vless-reality (vless-reality-2)", which is the right label for a person and is not a
    name the registry can resolve. Handed to ``transports.parse_form`` it fell through to
    an empty field map — silently, since that fallback exists for a transport this image
    does not ship — and the comma-split for sequence parameters stopped happening. The
    only replaceable sequence parameter in this image is Reality's accepted SNIs, and the
    rotation that needs them is the one that matters most: a blocked decoy is replaced by
    changing the decoy AND the names it serves, together, or the borrowed handshake stops
    verifying.
    """
    node_id = await a_node(client, "two-reality", "192.0.2.120")
    for port in (8443, 8444):
        enabled = await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": "vless-reality", "params": {**reality_params, "port": port}},
        )
        assert enabled.status_code == 201, enabled.text
    second = enabled.json()
    assert second["config_name"] != "vless-reality", second

    answer = await client.post(
        f"/panel/keys/{second['id']}/params",
        data={"server_names": "one.example.com, two.example.com"},
        headers={"HX-Request": "true"},
    )

    assert answer.status_code == 200, answer.text
    session.expire_all()
    row = await session.get(NodeTransport, second["id"])
    assert row.params["server_names"] == ["one.example.com", "two.example.com"], row.params


async def test_the_enable_dialog_still_offers_a_transport_the_node_already_runs(
    client, wg_params
) -> None:
    """The new freedom has to work in both directions, from the only surface there is.

    The dialog used to subtract every transport the node already had a row for, hop ends
    included — so users-then-hop worked and hop-then-users did not, and the second is
    the shape a leaf legitimately takes. Whether a second instance is legal is
    ``placement``'s single answer; the form no longer pre-empts it.
    """
    node_id = await a_node(client, "dialog-1", "192.0.2.87")
    await offered(client, node_id, wg_params)

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")

    assert dialog.status_code == 200
    assert f'data-transport-group="{HOP_TRANSPORT}"' in dialog.text


# --- removing a row is the exit (M15.2) ---------------------------------------
#
# The rule above only holds together if a row can be taken away: ``enabled`` is
# deliberately not consulted, so a switched-off transport keeps its port and its name
# forever and the operator who typed the wrong one has nowhere to go. These assert what
# removal frees, what it destroys, and what it refuses — the same three questions
# ``test_dissolving_a_hop_frees_what_it_held`` asks of the path that already had a
# delete.

async def a_user_on(client, node_id: str, nickname: str) -> str:
    """One person holding material on this node, which is what removal must destroy.

    The node is put into service first: a user is granted every SERVING node at the
    moment they are created, so the order is what puts a credential on the row.
    """
    activated = await client.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
    assert activated.status_code == 200, activated.text
    created = await client.post("/api/users", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_removing_a_transport_frees_the_port_and_the_name_it_held(
    client, session, wg_params
) -> None:
    """The whole point of M15.2, asserted the way the hop path is.

    Both halves, because they are two different rules with two different holders: the
    port lives in ``services.placement`` and nowhere else, and the config name is a
    database constraint. A removal that freed only one of them would be found by an
    operator, months later, in exactly the shape M15 was found in.
    """
    node_id = await a_node(client, "gone-1", "192.0.2.100")
    row = await offered(client, node_id, wg_params)
    assert row["config_name"] == HOP_TRANSPORT

    removed = await client.delete(f"/api/transports/{row['id']}")
    assert removed.status_code == 200, removed.text
    # The same shape ``DELETE /api/hops/{id}`` answers in: what the caller still owes.
    assert removed.json() == {"needs_apply": [node_id]}

    reused = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": wg_params,
            "pool_size": POOL_SIZE,
        },
    )

    assert reused.status_code == 201, reused.text
    # The PORT is free: this is the same number the removed row listened on.
    assert reused.json()["params"][transports_service.PORT_FIELD] == USER_PORT
    # …and so is the NAME: a second instance would have been placed under a suffix.
    assert reused.json()["config_name"] == HOP_TRANSPORT


async def test_removing_a_transport_takes_every_credential_minted_under_it(
    client, session, wg_params
) -> None:
    """"Taking its credentials with it" is the step's own phrase, and this is it.

    The difference from withdrawing, which is one button away and leaves every credential
    minted against a row that is merely switched off. Asserted on the rows themselves
    rather than on a count, and on what the delivery path would hand out afterwards:
    a credential whose node-transport is gone is material nobody can be routed onto, and
    leaving one behind would be a row referencing a transport that no longer exists.
    """
    node_id = await a_node(client, "creds-1", "192.0.2.101")
    row = await offered(client, node_id, wg_params)
    await a_user_on(client, node_id, "removed-from-under-them")

    held = await session.execute(
        select(Credential).where(Credential.node_transport_id == row["id"])
    )
    assert len(list(held.scalars().unique())) == 1, "the fixture minted nothing to destroy"

    assert (await client.delete(f"/api/transports/{row['id']}")).status_code == 200

    session.expire_all()
    left = await session.execute(select(Credential))
    assert list(left.scalars().unique()) == [], "a user's material outlived its transport"
    assert await session.get(NodeTransport, row["id"]) is None
    # And the person is untouched: removing a protocol is not revoking anybody.
    users = (await client.get("/api/users")).json()
    assert [user["nickname"] for user in users] == ["removed-from-under-them"]
    assert users[0]["revoked_at"] is None


async def test_a_hop_end_is_not_removed_this_way_and_the_refusal_names_what_is(
    client, session, wg_params
) -> None:
    """A hop is a pair, so the refusal points at the operation that takes the pair.

    The mirror of ``dissolve_hop`` refusing anything that is not already a hop end — the
    refusal that made a user-facing row unclearable in the first place. Neither path
    silently does half the other's job, and each names the other.
    """
    _, user_row, hop = await a_leaf_carrying_both(client, wg_params)

    refused = await client.delete(f"/api/transports/{hop['leaf']['id']}")

    assert refused.status_code == 409, refused.text
    message = refused.json()["error"]["message"]
    assert "hop" in message, message
    assert "/api/hops/" in message, message
    # Still there, and still half of a pair that points at itself.
    assert await session.get(NodeTransport, hop["leaf"]["id"]) is not None

    # …and the operation the refusal names does work, on the same row.
    assert (await client.delete(f"/api/hops/{hop['leaf']['id']}")).status_code == 200
    # The user-facing row on that node is untouched by either operation.
    assert await session.get(NodeTransport, user_row["id"]) is not None


async def test_removing_from_the_console_says_what_the_node_is_still_running(
    client, session, wg_params
) -> None:
    """The operator's own route to it: the button, the confirmation, the toast.

    Driven through the panel rather than the API because that is the only surface the
    owner has, and the sentence is what the milestone is judged on: the row is gone from
    this panel and the HOST is not, until it is applied. An operator who reads a removal
    as "stopped" has been told the opposite of what happened — the same trap the
    withdrawal toast is written against, and sharper here because the row has just
    vanished from the screen.
    """
    node_id = await a_node(client, "console-1", "192.0.2.102")
    row = await offered(client, node_id, wg_params)

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")
    assert dialog.status_code == 200
    assert f'hx-get="/panel/transports/{row["id"]}/remove"' in dialog.text

    confirmation = await client.get(f"/panel/transports/{row['id']}/remove")
    assert confirmation.status_code == 200
    assert f'hx-post="/panel/transports/{row["id"]}/remove"' in confirmation.text
    # It states the reach before the press: what goes, and what stays running. This node
    # has one transport, so it is the arm that says no apply will stop the host — M18's
    # acceptance; both arms are pinned in tests/control/test_the_console.py.
    assert "is refused" in confirmation.text
    # What stays running, said for a node nothing was ever pushed to — which is what this
    # suite can build, there being no host in it. The applied form of the same sentence is
    # pinned in tests/control/test_the_console.py. Flattened, because the dialog's prose is
    # wrapped at the template's own width and where it wraps is allowed to move.
    assert "whatever it was last given it keeps running" in " ".join(
        confirmation.text.split()
    )
    assert "withdraw it instead" in confirmation.text

    removed = await client.post(f"/panel/transports/{row['id']}/remove")

    assert removed.status_code == 200, removed.text
    assert "<html" not in removed.text.lower()
    # The last transport on this node, so the toast says the apply it would otherwise send
    # the operator to has nothing to push — M18.1's review. The other form, where the node
    # still has something enabled and "apply it to stop that" is true, is pinned in
    # tests/control/test_the_console.py.
    assert "the node keeps serving it" in removed.text
    assert "apply it to stop that" not in removed.text
    # Three collections move when a row leaves, and the tables refresh themselves.
    assert removed.headers["HX-Trigger"] == "nodes-changed, keys-changed, users-changed"
    assert await console.offers_on(session, node_id) == []


async def test_the_console_will_not_remove_a_hop_end_and_says_so_in_its_own_words(
    client, session, wg_params
) -> None:
    """Reachable only by a typed URL, because the dialog draws no button on that row.

    Both halves are asserted: the dialog offers nothing, and the route behind it still
    refuses — in the console's sentence rather than the service's, which ends by naming a
    raw API path on the one panel whose promise is that no URL is typed by hand.
    """
    node_id, _, hop = await a_leaf_carrying_both(client, wg_params)

    dialog = await client.get(f"/panel/nodes/{node_id}/transports")
    assert f'/panel/transports/{hop["leaf"]["id"]}/remove' not in dialog.text

    refused = await client.post(f"/panel/transports/{hop['leaf']['id']}/remove")

    assert refused.status_code == 200, refused.text
    assert "Hops screen" in refused.text
    assert "/api/hops/" not in refused.text
    assert await session.get(NodeTransport, hop["leaf"]["id"]) is not None


async def test_the_removal_confirmation_names_which_of_two_instances_it_is(
    client, session, wg_params
) -> None:
    """A node may run two of one transport, so "remove amneziawg?" is not a question.

    The dialog's subject is ``console.offer_row``, whose label is ``placed_as`` — the one
    place a transport is named on a node. Without it this confirmation asks about one of
    two identical words and the operator cannot tell which row they are destroying.
    """
    node_id = await a_node(client, "twice-1", "192.0.2.103")
    first = await offered(client, node_id, wg_params)
    # A second instance takes its own port AND its own range — M17.1c.
    second = await offered(
        client,
        node_id,
        {
            **wg_params,
            "port": HOP_PORT,
            "tunnel_address": "10.79.0.1/24",
            "peer_tunnel_address": "10.79.0.2/24",
        },
    )
    assert second["config_name"] != first["config_name"]

    confirmation = await client.get(f"/panel/transports/{second['id']}/remove")

    assert confirmation.status_code == 200
    assert console.placed_as(HOP_TRANSPORT, second["config_name"]) in confirmation.text
    # The first instance keeps the plain name, so the two dialogs cannot read alike.
    plain = await client.get(f"/panel/transports/{first['id']}/remove")
    assert console.placed_as(HOP_TRANSPORT, second["config_name"]) not in plain.text
