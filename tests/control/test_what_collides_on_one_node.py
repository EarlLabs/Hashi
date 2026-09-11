"""What two transports on one node may and may not share — M15.

WHAT: the uniqueness rule after it moved off ``(node, transport_name)`` and onto the
      listening port and the config file's name.
WHY:  the old rule was enforced in terms of the wrong concept, at the worst moment, with
      no way to undo the state that triggered it. It made the runbook's own advice
      impossible: AmneziaWG is mandated for the entry→leaf hop and recommended for
      friends on the same box, so the first one enabled excluded the other forever.
HOW:  through the real services and a real database. The half that cannot be proven here
      is whether two daemons on one host actually come up — that is the owner's field
      check, and nothing in this file claims it. What IS proven is that the control plane
      writes two rows, renders two configs, places them at two paths and asks for two
      interface names the kernel would accept.
"""

import pytest
from sqlalchemy import text

from control.app.errors import Conflict, NodeOperationFailed
from control.app.models import NodeTransport
from control.app.services import apply, nodes, placement, rotation
from control.app.services import transports as transports_service
from edge.bootstrap import node_stack

HOP_TRANSPORT = "amneziawg"

# Two ports, because one node cannot have one. Neither is a value this codebase would
# ship — they are typed here the way an operator types them into the form.
FRIEND_PORT = 51820
HOP_PORT = 51821


@pytest.fixture
def wg_params() -> dict[str, object]:
    """The operator-supplied half of one wg-quick-family end. Material is minted."""
    return {
        "port": FRIEND_PORT,
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
    """The runbook's Shape A step 2: this transport, offered to friends, on this box."""
    response = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": HOP_TRANSPORT, "params": params},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def a_box_carrying_both(client, wg_params) -> tuple[str, dict, dict]:
    """One node offering the transport to friends AND carrying the hop over it.

    The shape the runbook asks for and the product used to refuse. Returns the entry
    node's id, its friend-facing row and the hop's body.
    """
    entry_id = await a_node(client, "box-1", "192.0.2.90")
    leaf_id = await a_node(client, "far-1", "192.0.2.91")
    friend_row = await offered(client, entry_id, wg_params)

    hop_side = {
        **wg_params,
        "port": HOP_PORT,
        "tunnel_address": "10.71.0.1/24",
        "peer_tunnel_address": "10.71.0.2/24",
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
                "tunnel_address": "10.71.0.2/24",
                "peer_tunnel_address": "10.71.0.1/24",
            },
        },
    )
    assert established.status_code == 201, established.text
    return entry_id, friend_row, established.json()


async def a_leaf_carrying_both(client, wg_params) -> tuple[str, dict, dict]:
    """A node offering the transport to friends AND holding the LEAF end of a hop.

    The same two rows of one transport on one node, on the side of the tunnel that
    WAITS. It is a separate helper because the two sides are not interchangeable: an
    ENTRY node's friends must leave through the hop, and ``edge`` refuses to render a
    kernel tunnel that would have to do that (see the render test below, and M14.3).
    A leaf has no hop of its own, so its friends exit from it as they always have.
    """
    entry_id = await a_node(client, "dialer-1", "192.0.2.80")
    leaf_id = await a_node(client, "landing-1", "192.0.2.81")
    friend_row = await offered(client, leaf_id, wg_params)

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
    return leaf_id, friend_row, established.json()


# --- what is now allowed ------------------------------------------------------

async def test_one_node_carries_a_friend_facing_and_a_hop_end_of_one_transport(
    client, wg_params
) -> None:
    """The sequence that answered 409 in the field, and the row it now writes."""
    entry_id, friend_row, hop = await a_box_carrying_both(client, wg_params)

    assert hop["entry"]["node_id"] == entry_id
    assert hop["entry"]["transport_name"] == friend_row["transport_name"]
    assert hop["entry"]["id"] != friend_row["id"]


async def test_the_two_rows_are_placed_under_two_names(client, wg_params) -> None:
    """The names are what stops them being one file and one network interface.

    The friend-facing row keeps the transport's own name, which is what every node
    already in the field has on disk — a scheme that renamed it would take the interface
    down under a running daemon on the next apply.
    """
    _, friend_row, hop = await a_box_carrying_both(client, wg_params)

    assert friend_row["config_name"] == HOP_TRANSPORT
    assert hop["entry"]["config_name"] != friend_row["config_name"]
    # The leaf is a fresh node, so it keeps the plain name: the rule is per node.
    assert hop["leaf"]["config_name"] == HOP_TRANSPORT


async def test_the_two_rows_render_to_two_files_the_node_can_actually_run(
    client, session, wg_params
) -> None:
    """Two configs, two paths, two compose services, two legal interface names.

    This is the assertion the decision rests on. ``render_for_node`` keys by the placed
    name rather than the transport's, so a node running two of one transport gets two
    entries instead of the second silently replacing the first — and ``services_for``
    then gives each its own file and its own container.

    Driven from the LEAF side, because that is the side of this shape that renders at
    all: see the entry-side test below, which is about an older rule this milestone does
    not touch.
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
    # twice: the hop end dials a peer, the friend-facing end waits for devices.
    assert len(set(configs.values())) == 2


async def test_an_entry_node_with_a_kernel_tunnel_for_friends_still_will_not_render(
    client, session, wg_params
) -> None:
    """The OTHER refusal on this shape, which M15 does not remove and must not hide.

    The two rows are written — the ``409`` is gone — and the ENTRY node still cannot be
    applied, for a reason that has nothing to do with uniqueness and is not new: a kernel
    tunnel hands its packets to the node's own routing stack, so an entry node's friends
    cannot be made to leave through a hop on a different interface. ``edge`` refuses that
    out loud rather than rendering a file that would send a friend in Russia out of the
    Russian node (``edge/egress.py``, M14.3 and decision 3).

    So the runbook's own sequence — offer AmneziaWG to friends on the entry box, then hop
    from it over AmneziaWG — is refused TWICE, and only the first refusal was M15's. This
    is asserted here so the second one is a documented fact with a sentence attached
    rather than a surprise at the operator's next apply; M15.3 is where the runbook stops
    recommending it.
    """
    entry_id, _, _ = await a_box_carrying_both(client, wg_params)
    node = await nodes.get_node(session, entry_id)

    with pytest.raises(NodeOperationFailed) as refusal:
        await apply.render_for_node(session, node)

    # The operator is told what to do about it, and both answers are named.
    assert "terminates their connection" in str(refusal.value), refusal.value


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
        },
    )

    assert collided.status_code == 409, collided.text
    assert collided.json()["error"]["code"] == "conflict"
    message = collided.json()["error"]["message"]
    assert str(FRIEND_PORT) in message, message
    assert "port-1" in message, message


async def test_a_hop_end_is_refused_over_the_port_the_node_already_listens_on(
    client, wg_params
) -> None:
    """The same rule at the other creation path, so the two cannot disagree."""
    entry_id = await a_node(client, "port-2", "192.0.2.93")
    leaf_id = await a_node(client, "far-2", "192.0.2.94")
    await offered(client, entry_id, wg_params)

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
            # The port the entry node already offers to friends.
            "entry_params": hop_side,
            "leaf_params": {
                **hop_side,
                "tunnel_address": "10.73.0.2/24",
                "peer_tunnel_address": "10.73.0.1/24",
            },
        },
    )

    assert collided.status_code == 409, collided.text
    assert str(FRIEND_PORT) in collided.json()["error"]["message"]


async def test_a_switched_off_transport_still_holds_its_port(
    client, session, wg_params
) -> None:
    """Disabled is not removed, and its port is still spoken for.

    Freeing the port when a row is switched off would move the collision to the moment
    it is switched back on — the same "found months later" failure M15 exists to close.
    Removing a row is what frees it, and making a row removable is M15.2.
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
    entry_id, friend_row, hop = await a_box_carrying_both(client, wg_params)

    with pytest.raises(Conflict):
        await rotation.replace_params(
            session,
            node_transport_id=hop["entry"]["id"],
            params={transports_service.PORT_FIELD: FRIEND_PORT},
        )


# --- the schema holds the same rule -------------------------------------------

async def test_the_database_holds_both_rules_itself(session) -> None:
    """A rule nobody can bypass is a constraint, and both of these are.

    Read out of Postgres rather than off the model, because the claim is about the
    database an operator's script talks to: a rule that lives only in Python is one a
    fixture, a migration or a future service walks around, and the failure mode is a node
    whose second container cannot start.
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
    assert "uq_node_transport_port" in names
    # The rule that was replaced is gone rather than left beside the new one: two rules
    # about the same thing is how one of them stops being true.
    assert "uq_node_transport" not in names


async def test_the_schema_and_the_console_agree_about_the_port_field(session) -> None:
    """``PORT_FIELD`` is one string in two places, and they must not drift.

    ``NodeTransport``'s unique index is written over ``params ->> 'port'`` because a
    model cannot import a service, so the literal is in the schema and the name the rest
    of `control` knows is ``transports.PORT_FIELD``. This is the join between them: the
    index's own definition, read back out of Postgres, has to name the same field.
    """
    definition = (
        await session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'node_transports' "
                "AND indexname = 'uq_node_transport_port'"
            )
        )
    ).scalar_one()

    assert f"'{transports_service.PORT_FIELD}'" in definition, definition
    assert "node_id" in definition


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
    client, session, wg_params
) -> None:
    """A row with no port in its parameters is not constrained by the port rule.

    Asked of the service rather than through a transport, because every transport this
    image ships declares a port. The behaviour has to be right anyway: the database's own
    index leaves such a row NULL, and Postgres treats NULLs as distinct.
    """
    node_id = await a_node(client, "noport-1", "192.0.2.98")
    node = await nodes.get_node(session, node_id)
    await offered(client, node_id, wg_params)

    assert placement.port_of({}) is None
    # No refusal, and the name offered is still the free one.
    assert await placement.claim(
        session, node=node, transport_name="vless-reality", params={}
    ) == "vless-reality"


async def test_the_second_instance_takes_a_name_the_kernel_would_accept(
    client, session, wg_params
) -> None:
    """The suffixed name is ours to choose, so it is measured against the tool's rule."""
    node_id = await a_node(client, "name-1", "192.0.2.99")
    node = await nodes.get_node(session, node_id)
    await offered(client, node_id, wg_params)

    chosen = await placement.claim(
        session,
        node=node,
        transport_name=HOP_TRANSPORT,
        params={**wg_params, "port": HOP_PORT},
    )

    assert chosen != HOP_TRANSPORT
    assert node_stack.config_name_is_usable(HOP_TRANSPORT, chosen), chosen


async def test_every_row_this_control_plane_writes_carries_a_placed_name(
    client, session, wg_params
) -> None:
    """No path may write a row without one — it is what the node's file is called."""
    await a_box_carrying_both(client, wg_params)

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
    entry_id, _, hop = await a_box_carrying_both(client, wg_params)

    assert (await client.delete(f"/api/hops/{hop['entry']['id']}")).status_code == 200

    reused = await client.post(
        f"/api/nodes/{entry_id}/transports",
        json={
            "transport_name": HOP_TRANSPORT,
            "params": {
                **wg_params,
                "port": HOP_PORT,
                "tunnel_address": "10.75.0.1/24",
                "peer_tunnel_address": "10.75.0.2/24",
            },
        },
    )

    assert reused.status_code == 201, reused.text
    assert reused.json()["config_name"] != HOP_TRANSPORT
