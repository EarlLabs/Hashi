"""A node's record follows its host onto a new machine — M36.

WHAT: ``services/relocation.py`` (``relocate_node`` and ``host_plan``), the operator
      API's ``POST /api/nodes/{id}/relocate``, and the pieces of ``control/cli.py`` that
      can be checked without a container.
WHY:  on 2026-10-13 the entry box died and its replacement could only be wired back in
      with a raw ``UPDATE nodes`` — the SSH host, account and pinned host key were fixed
      at registration, and nothing in the trail recorded the change. These tests pin the
      operation that replaces that UPDATE: it moves exactly the coordinates, always
      replaces the pin, tells the caller which nodes to apply, and records the node's name
      and nothing else.
HOW:  real Postgres and the real API, as the rest of this zone. No host is dialled: the
      apply that follows a relocation is ``tests/e2e/control``'s and the walk's.
"""

import asyncssh
import pytest
from sqlalchemy import select

from control import cli
from control.app.models import AuditAction, AuditEntry, NodeTransport, TransportPurpose
from control.app.services import apply, nodes, relocation

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation addresses, as everywhere in this zone.
OLD_HOST = "192.0.2.30"
NEW_HOST = "198.51.100.30"
HOST_KEY = (
    asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode().strip()
)

HOP_TRANSPORT = "amneziawg"
HOP_PARAMS = {
    "port": 51820,
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}


async def a_node(client, *, name: str = "entry-1", address: str = OLD_HOST) -> str:
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": address,
            "location_label": "Testland",
            "ssh_user": "old-box-account",
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def moved_to(**overrides) -> dict:
    return {"ssh_host": NEW_HOST, "ssh_user": "hashi", "ssh_port": 22, **overrides}


async def a_hop(client, entry_id: str, leaf_id: str) -> None:
    body = {
        "entry_node_id": entry_id,
        "leaf_node_id": leaf_id,
        "transport_name": HOP_TRANSPORT,
        "entry_params": {**HOP_PARAMS, "tunnel_address": "10.44.0.1/24",
                         "peer_tunnel_address": "10.44.0.2/24"},
        "leaf_params": {**HOP_PARAMS, "tunnel_address": "10.44.0.2/24",
                        "peer_tunnel_address": "10.44.0.1/24"},
    }
    response = await client.post("/api/hops", json=body)
    assert response.status_code == 201, response.text


# --- the move -------------------------------------------------------------------------

async def test_the_record_is_dialled_at_the_new_host_as_the_new_account(
    client, session
) -> None:
    """What the next connection uses, not merely what the columns hold.

    Red without this module: ``/api/nodes/{id}/relocate`` is a 404 and the target is
    still the old host, as the old account, with the old pin.
    """
    node_id = await a_node(client)
    node = await nodes.get_node(session, node_id)
    node.ssh_host_key = HOST_KEY  # the old box's pin, as an apply would have left it
    await session.commit()

    response = await client.post(f"/api/nodes/{node_id}/relocate", json=moved_to(ssh_port=2222))

    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    assert response.json()["needs_apply"] == [node_id]
    await session.refresh(node)
    target = apply.target_for(node, apply.settings())
    assert (target.host, target.port, target.username) == (NEW_HOST, 2222, "hashi")
    # A different machine has a different host key by definition, so the old pin is gone.
    assert target.host_key is None
    assert node.address == OLD_HOST, "an address nobody asked to change was changed"


async def test_a_host_key_read_from_the_new_host_is_what_gets_pinned(client, session) -> None:
    node_id = await a_node(client)

    response = await client.post(
        f"/api/nodes/{node_id}/relocate", json=moved_to(host_key=f"{HOST_KEY} root@new-box")
    )

    assert response.status_code == 200, response.text
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    # Canonical: the same line the connection itself would have learned.
    assert node.ssh_host_key == HOST_KEY
    assert apply.target_for(node, apply.settings()).host_key == HOST_KEY


async def test_a_host_key_that_is_not_one_is_refused_and_nothing_moves(
    client, session
) -> None:
    node_id = await a_node(client)

    response = await client.post(
        f"/api/nodes/{node_id}/relocate", json=moved_to(host_key="ssh-ed25519 not-base64")
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["message"] == relocation.HOST_KEY_UNUSABLE
    node = await nodes.get_node(session, node_id)
    await session.refresh(node)
    assert (node.ssh_host, node.ssh_user) == (OLD_HOST, "old-box-account")


@pytest.mark.parametrize(
    "wrong",
    [
        {"ssh_host": ""},
        {"ssh_user": ""},
        {"ssh_port": 0},
        {"ssh_port": 65536},
        {"ssh_user": "u" * 33},
        {"address": ""},
    ],
)
async def test_coordinates_the_record_cannot_hold_are_refused(client, wrong) -> None:
    node_id = await a_node(client)
    response = await client.post(f"/api/nodes/{node_id}/relocate", json=moved_to(**wrong))
    assert response.status_code == 422, response.text


async def test_a_blank_host_is_refused_by_the_service_too(client, session) -> None:
    """The CLI does not go through the API's schema, so the service holds the rule."""
    node_id = await a_node(client)
    with pytest.raises(relocation.DomainError):
        await relocation.relocate_node(
            session, node_id=node_id, ssh_host="   ", ssh_user="hashi", ssh_port=22
        )


async def test_an_unknown_node_is_a_404(client) -> None:
    response = await client.post("/api/nodes/no-such-node/relocate", json=moved_to())
    assert response.status_code == 404, response.text


async def test_the_trail_records_the_name_once_and_never_an_address(client, session) -> None:
    """A retried move onto the same coordinates and the same pin is not an event."""
    node_id = await a_node(client)

    for _ in range(2):
        response = await client.post(
            f"/api/nodes/{node_id}/relocate", json=moved_to(host_key=HOST_KEY)
        )
        assert response.status_code == 200, response.text
    assert response.json()["changed"] is False

    entries = (
        await session.execute(
            select(AuditEntry).where(AuditEntry.action == AuditAction.NODE_RELOCATED)
        )
    ).scalars().all()
    assert [(e.first_label, e.second_label) for e in entries] == [("entry-1", None)]


async def test_the_same_coordinates_without_a_key_still_clear_a_pin(client, session) -> None:
    """A box reinstalled at its old address: same coordinates, a new machine."""
    node_id = await a_node(client)
    node = await nodes.get_node(session, node_id)
    node.ssh_host = NEW_HOST
    node.ssh_user = "hashi"
    node.ssh_host_key = HOST_KEY
    await session.commit()

    response = await client.post(f"/api/nodes/{node_id}/relocate", json=moved_to())

    assert response.json()["changed"] is True
    await session.refresh(node)
    assert node.ssh_host_key is None


# --- which nodes the apply has to include ---------------------------------------------

async def test_a_leaf_that_moves_address_takes_the_entry_that_dials_it_along(
    client, session
) -> None:
    """The dialling end's config carries the far end's address, and only that end's."""
    entry_id = await a_node(client, name="entry-1", address="192.0.2.31")
    leaf_id = await a_node(client, name="leaf-1", address="192.0.2.32")
    await a_hop(client, entry_id, leaf_id)

    leaf_moved = await client.post(
        f"/api/nodes/{leaf_id}/relocate", json=moved_to(address=NEW_HOST)
    )
    entry_moved = await client.post(
        f"/api/nodes/{entry_id}/relocate", json=moved_to(address="198.51.100.31")
    )

    assert leaf_moved.json()["needs_apply"] == [leaf_id, entry_id]
    assert entry_moved.json()["needs_apply"] == [entry_id]
    assert (await nodes.get_node(session, leaf_id)).address == NEW_HOST


async def test_a_move_that_keeps_the_address_applies_only_the_node(client) -> None:
    entry_id = await a_node(client, name="entry-1", address="192.0.2.31")
    leaf_id = await a_node(client, name="leaf-1", address="192.0.2.32")
    await a_hop(client, entry_id, leaf_id)

    response = await client.post(f"/api/nodes/{leaf_id}/relocate", json=moved_to())

    assert response.json()["needs_apply"] == [leaf_id]


# --- what a fresh host needs ------------------------------------------------------------

async def test_the_plan_opens_what_users_and_a_dialling_entry_reach_and_nothing_else(
    client, session, settings, reality_params
) -> None:
    """Users' ports and the waiting hop end's — never the dialling end's."""
    entry_id = await a_node(client, name="entry-1", address="192.0.2.31")
    leaf_id = await a_node(client, name="leaf-1", address="192.0.2.32")
    enabled = await client.post(
        f"/api/nodes/{entry_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await a_hop(client, entry_id, leaf_id)

    entry_plan = await relocation.host_plan(
        session, await nodes.get_node(session, entry_id), settings
    )
    leaf_plan = await relocation.host_plan(
        session, await nodes.get_node(session, leaf_id), settings
    )

    assert entry_plan.ports == (f"{reality_params['port']}/tcp",)
    assert leaf_plan.ports == (f"{HOP_PARAMS['port']}/udp",)


async def test_a_host_users_reach_by_name_also_opens_the_delivery_socket(
    client, session, settings, reality_params
) -> None:
    """A named host with users gets the delivery listener (this suite holds a certificate)."""
    node_id = await a_node(client, address="entry.example.net")
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text

    plan = await relocation.host_plan(session, await nodes.get_node(session, node_id), settings)

    assert "443/tcp" in plan.ports, plan.ports


async def test_the_plan_carries_the_public_half_of_the_records_key_only(
    client, session, settings
) -> None:
    node_id = await a_node(client)

    plan = await relocation.host_plan(session, await nodes.get_node(session, node_id), settings)

    expected = asyncssh.import_private_key(GENERATED_SSH_KEY).export_public_key().decode().strip()
    assert plan.public_key == expected
    assert "PRIVATE" not in (plan.public_key or "")


async def test_a_disabled_transport_opens_nothing(client, session, settings, reality_params):
    node_id = await a_node(client)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    row = await session.get(NodeTransport, enabled.json()["id"])
    row.enabled = False
    await session.commit()

    plan = await relocation.host_plan(session, await nodes.get_node(session, node_id), settings)

    assert plan.ports == ()
    assert row.purpose == TransportPurpose.USERS


# --- the shell side ---------------------------------------------------------------------

def test_a_value_with_a_line_break_is_refused_rather_than_split(capsys) -> None:
    """``key=value`` lines are read line by line; a newline in a value would forge a key."""
    with pytest.raises(cli.DomainError):
        cli._say(address="host\nssh_host=elsewhere")
    assert "ssh_host=elsewhere" not in capsys.readouterr().out


def test_relocate_requires_every_coordinate() -> None:
    with pytest.raises(SystemExit):
        cli.main(["relocate-node", "entry-1", "--ssh-host", NEW_HOST, "--ssh-user", "hashi"])
