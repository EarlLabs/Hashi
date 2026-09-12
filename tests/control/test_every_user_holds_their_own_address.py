"""One address per user on a transport that routes by address — M17.1b.

WHAT: the allocator and its refusals, end to end through the real services: who gets
      which address, what happens when the pool has no room, what a row that pre-dates
      this milestone renders, and what survives a rotation, a revocation and a removal.
WHY:  the field found a WireGuard-family transport that served exactly one friend. The
      renderers' refusal to put two peers on one address is right and stays; what this
      file pins is the two things that had to become true around it — that a second user
      gets a second address, and that a pool with no room refuses BEFORE anything is
      committed. The second half is the one worth a file of its own: four of the five
      paths that grant a credential used to commit first and grant afterwards, so a
      refusal arrived with the change already made.
HOW:  real Postgres, real encryption, real rendering, no node contacted. Every transport
      question is asked of the registry — ``TransportMeta.peer_address`` for "does this
      hand out addresses" and ``config_format`` for "is this the wg-quick family" — so
      nothing here names a protocol and a third family member is covered by arriving.

Nothing in this file asserts on a person against an address in any durable record: the
allocation is read back through a RENDER, which is what the node and the device actually
receive, rather than by printing who holds what.
"""

import hashlib
import json
import re

import pytest
from sqlalchemy import select

from control.app.errors import Conflict, NodeOperationFailed
from control.app.models import (
    AuditEntry,
    Credential,
    Friend,
    NodeState,
    NodeTransport,
    TransportPurpose,
)
from control.app.models.base import secret_box
from control.app.services import addresses, apply, friends, nodes, rotation, subscriptions
from edge.addressing import host_of
from edge.registry import ConfigFormat, discover, profile

# Every transport in this image that declares each of its consumers needs an address of
# its own. THE DECLARATION, not a name and not a family: that is what `control` reads,
# so a transport added later is exercised here by arriving rather than by being listed.
POOL_TRANSPORTS = sorted(
    name for name, meta in discover().items() if meta.peer_address is not None
)

# The wg-quick family, derived from the config FORMAT — the same way ``edge`` derives it.
# Used only where an assertion is about the file's own shape (``AllowedIPs``, ``Address``),
# which is a property of that format and of nothing else.
WG_FAMILY = sorted(
    name
    for name, meta in discover().items()
    if meta.config_format in {ConfigFormat.WG_QUICK, ConfigFormat.WG_QUICK_PLAIN}
)

# A transport that hands out no address at all, for the tests that need one of each.
PLAIN_TRANSPORTS = sorted(
    name for name, meta in discover().items()
    if meta.peer_address is None and meta.subscription_formats
)

# The operator half of a wg-quick family transport's parameters. Filtered per transport
# against its own model below, so one literal serves every member of the family.
WG_PARAMS: dict[str, object] = {
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

# Room for far more users than any test here creates. A pool sized to exactly what a test
# needs is one that turns red when somebody adds a user to an unrelated assertion.
ROOMY = 50


def params_for(transport_name: str, **overrides) -> dict[str, object]:
    """The operator-supplied half, minus knobs this transport does not declare."""
    declared = set(profile(transport_name).params_model.model_fields)
    supplied = {**WG_PARAMS, **overrides}
    return {key: value for key, value in supplied.items() if key in declared}


@pytest.fixture(params=POOL_TRANSPORTS)
def pool_transport(request) -> str:
    if not POOL_TRANSPORTS:
        pytest.skip("this image ships no transport that gives each user an address")
    return request.param


async def a_node(client, *, name: str, address: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def enable_pool(
    client,
    node_id: str,
    transport_name: str,
    *,
    pool_size: int = ROOMY,
    tunnel: str = "10.90.0.1/24",
    peer: str = "10.90.0.2/24",
    port: int = 51820,
):
    """Enable an address-handing transport on a node, and hand back the response."""
    return await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": transport_name,
            "params": params_for(
                transport_name, port=port, tunnel_address=tunnel, peer_tunnel_address=peer
            ),
            "pool_size": pool_size,
        },
    )


async def add_user(client, nickname: str):
    return await client.post("/api/friends", json={"nickname": nickname})


def routes_in(config: str) -> list[str]:
    return re.findall(r"AllowedIPs\s*=\s*(\S+)", config)


def address_in(config: str) -> str:
    return re.search(r"Address\s*=\s*(\S+)", config).group(1)


async def as_the_node_sees_it(session, node_id: str, config_name: str) -> str:
    node = await nodes.get_node(session, node_id)
    return (await apply.render_for_node(session, node))[config_name]


# --- what the milestone is for ------------------------------------------------

async def test_two_users_on_one_row_are_routed_separately(
    client, session, pool_transport: str
) -> None:
    """Both shipped members of the family, not only the one another file happens to use.

    ``test_second_subscription_format`` asserts the same property for the first
    file-serialising transport this image ships; the plan's done-when names BOTH, and a
    family whose second member was never exercised is a family with one member tested.
    """
    node_id = await a_node(client, name="pair", address="192.0.2.40")
    assert (await enable_pool(client, node_id, pool_transport)).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    config = await as_the_node_sees_it(session, node_id, pool_transport)
    routes = routes_in(config)
    assert len(routes) == 2 and len(set(routes)) == 2, config


async def test_the_address_a_device_holds_is_the_one_its_node_routes(
    client, session, pool_transport: str
) -> None:
    """The two renders of one allocation agree — for every member of the family.

    Asserted through both builders, because they are two services: the node's config
    comes from ``apply.render_for_node`` and the user's file from
    ``subscriptions.config_files_for``. A disagreement is a tunnel that comes up and
    carries nothing, with every screen green.
    """
    if pool_transport not in WG_FAMILY:
        pytest.skip(f"{pool_transport} is not a wg-quick config, so it has no Address line")

    node_id = await a_node(client, name="agree", address="192.0.2.41")
    assert (await enable_pool(client, node_id, pool_transport)).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("cara", "dima"):
        assert (await add_user(client, nickname)).status_code == 201

    config = await as_the_node_sees_it(session, node_id, pool_transport)
    authorised = {host_of(route) for route in routes_in(config)}

    held = set()
    for nickname in ("cara", "dima"):
        friend = (
            await session.execute(select(Friend).where(Friend.nickname == nickname))
        ).scalars().one()
        files = await subscriptions.config_files_for(session, friend)
        assert len(files) == 1, files
        held.add(host_of(address_in(files[0].content)))

    assert len(held) == 2, "two users were handed one address"
    assert held == authorised


# --- a row that pre-dates this milestone --------------------------------------

async def as_it_was_before_m17(session, node_transport_id: str) -> None:
    """Put a row into the exact state migration 0006 leaves an existing one in.

    No pool size, and no address on any credential — which is every row in the field the
    day this ships. Written by hand rather than by an API call because no surface can
    produce it any more, which is the point: this is the upgrade path, not a state the
    product still creates.
    """
    row = await session.get(NodeTransport, node_transport_id)
    row.pool_size = None
    held = (
        await session.execute(
            select(Credential).where(Credential.node_transport_id == node_transport_id)
        )
    ).scalars().unique()
    for credential in held:
        credential.tunnel_address = None
        credential.tunnel_address_digest = None
    await session.commit()


async def test_a_row_enabled_before_this_milestone_renders_the_same_bytes(
    client, session, pool_transport: str
) -> None:
    """BYTE-IDENTICAL, and that is the promise the upgrade rests on.

    A transport enabled before M17 has one typed address and one user holding it. After
    the upgrade that row has no pool size and its credential no address — and it must
    render exactly what it rendered yesterday, because the file on the node and the file
    on the person's device are already configured with that address and neither is
    touched by a migration.

    Compared as a DIGEST of the whole of BOTH files, not as a substring and not on the
    node's side alone: the two halves fail differently and only one of them is visible
    from the node. A node config renders an allocation as a ``/32`` route whatever form
    the address was stored in, so a stored address that had lost its prefix would look
    perfect there and arrive in the user's own ``Address`` line as a different string —
    the one file this project cannot reissue without the person doing something.
    """
    node_id = await a_node(client, name="legacy", address="192.0.2.42")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=1)
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await add_user(client, "solo")).status_code == 201
    solo = (
        await session.execute(select(Friend).where(Friend.nickname == "solo"))
    ).scalars().one()

    async def both_files() -> str:
        node = await as_the_node_sees_it(session, node_id, pool_transport)
        theirs = [
            config.content for config in await subscriptions.config_files_for(session, solo)
        ]
        return "\n".join([node, *theirs])

    after = await both_files()

    await as_it_was_before_m17(session, enabled.json()["id"])
    before = await both_files()

    assert hashlib.sha256(before.encode()).hexdigest() == \
        hashlib.sha256(after.encode()).hexdigest(), (
            "a row upgraded from before M17 renders different bytes, so every device on "
            "it would have to be reconfigured"
        )


async def test_a_row_from_before_this_milestone_with_two_users_still_refuses(
    client, session, pool_transport: str
) -> None:
    """The field's own broken row, and both halves of what the product now says about it.

    It still cannot render — that refusal is ``edge``'s and is not weakened by anything
    here — and, the part that is new, the next user is refused BEFORE anything is written,
    with the node and the transport named. Repairing such a row is a resize, which is a
    later step; what this pins is that the product neither renders it wrongly nor lets it
    grow.
    """
    node_id = await a_node(client, name="the-field", address="192.0.2.43")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("first", "second"):
        assert (await add_user(client, nickname)).status_code == 201

    await as_it_was_before_m17(session, enabled.json()["id"])

    node = await nodes.get_node(session, node_id)
    with pytest.raises(NodeOperationFailed) as refused:
        await apply.render_for_node(session, node)
    assert "tunnel address" in str(refused.value).lower()

    third = await add_user(client, "third")
    assert third.status_code == 409, third.text
    message = third.json()["error"]["message"]
    assert "the-field" in message and pool_transport in message

    # And nothing of that third person exists.
    assert (
        await session.execute(select(Friend).where(Friend.nickname == "third"))
    ).scalars().first() is None


# --- a pool with no room refuses before anything commits ----------------------

async def audit_rows(session) -> list[tuple]:
    entries = (
        await session.execute(select(AuditEntry).order_by(AuditEntry.at, AuditEntry.id))
    ).scalars().all()
    return [(entry.action, entry.first_label, entry.second_label) for entry in entries]


async def test_enabling_a_pool_smaller_than_the_fleet_writes_nothing(
    client, session, pool_transport: str
) -> None:
    """The size is refused under its own box, and the row is not created.

    The count is the fleet's, not the node's: every active user is granted a credential
    on this transport the moment the node serves, so a pool that cannot hold them is one
    that would refuse the first person to be granted — after the row had been committed.
    """
    node_id = await a_node(client, name="too-small", address="192.0.2.44")
    for nickname in ("ann", "bob", "cara"):
        assert (await add_user(client, nickname)).status_code == 201
    before = await audit_rows(session)

    refused = await enable_pool(client, node_id, pool_transport, pool_size=2)
    assert refused.status_code == 400, refused.text

    session.expire_all()
    rows = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().all()
    assert rows == [], "a transport was enabled by a request that was refused"
    assert await audit_rows(session) == before, "a refusal reached the audit trail"


async def test_a_transport_that_hands_out_no_address_refuses_a_pool_size(
    client, session, reality_params
) -> None:
    """A number that would mean nothing is refused rather than stored and ignored.

    The pool size is read off the transport's own declaration in both directions: one
    that says each consumer needs an address must be told how many, and one that says
    nothing must not be given a count nobody would ever use.
    """
    if not PLAIN_TRANSPORTS:
        pytest.skip("this image ships no transport that identifies its users by material")
    node_id = await a_node(client, name="no-pool", address="192.0.2.45")

    refused = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": PLAIN_TRANSPORTS[0],
            "params": reality_params,
            "pool_size": 10,
        },
    )
    assert refused.status_code == 400, refused.text
    assert addresses.POOL_BOX in refused.json()["error"]["message"]


async def test_adding_a_user_a_pool_cannot_hold_writes_nothing(
    client, session, pool_transport: str
) -> None:
    """Not the friend, not their subscription, not a credential, not an audit entry.

    The refusal is asked for before the first write rather than discovered when the
    address is allocated, so what the operator is told — nothing has been changed — is
    true of a transaction that never started rather than of one that was rolled back.
    """
    node_id = await a_node(client, name="full", address="192.0.2.46")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=1)).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await add_user(client, "only")).status_code == 201

    before = await audit_rows(session)
    refused = await add_user(client, "one-too-many")
    assert refused.status_code == 409, refused.text
    assert "full" in refused.json()["error"]["message"]

    session.expire_all()
    assert (
        await session.execute(select(Friend).where(Friend.nickname == "one-too-many"))
    ).scalars().first() is None
    assert len(
        (await session.execute(select(Credential))).scalars().unique().all()
    ) == 1, "a credential was minted for a user who was refused"
    assert await audit_rows(session) == before


async def test_offering_a_transport_the_pool_cannot_cover_leaves_it_withdrawn(
    client, session, pool_transport: str
) -> None:
    """The offer path, which used to commit the flag and grant afterwards.

    Reachable exactly as an operator would reach it: a transport withdrawn while the
    fleet was small, users added while it was out of everybody's link (which is
    legitimate — a withdrawn row is in nobody's subscription and is not measured), then
    offered again. Before M17 the second half of that ran in its own transaction, so the
    row came back into every link and the failure arrived afterwards.
    """
    node_id = await a_node(client, name="offer-back", address="192.0.2.47")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=1)
    assert enabled.status_code == 201, enabled.text
    node_transport_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    withdrawn = await client.post(
        f"/api/transports/{node_transport_id}/state", json={"enabled": False}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    before = await audit_rows(session)
    refused = await client.post(
        f"/api/transports/{node_transport_id}/state", json={"enabled": True}
    )
    assert refused.status_code == 409, refused.text

    session.expire_all()
    row = await session.get(NodeTransport, node_transport_id)
    assert row.enabled is False, "the transport was offered by a request that was refused"
    assert (
        await session.execute(
            select(Credential).where(Credential.node_transport_id == node_transport_id)
        )
    ).scalars().unique().all() == [], "credentials were minted on a refused offer"
    assert await audit_rows(session) == before


async def test_a_node_cannot_become_serving_while_its_pool_is_short(
    client, session, pool_transport: str
) -> None:
    """SET ACTIVE, refused with the node still a draft — the fourth granting path.

    A node becoming serving hands every active user a credential on every serving
    transport, which is what charter criterion 2 rests on. Since M17 that fan-out
    allocates an address per person, so it can refuse — and the state change and the
    fan-out are ONE transaction: before, the node went active in its own commit and the
    refusal arrived with the fleet already changed, on a node every screen now called
    serving.

    Two nodes, because the fan-out is fleet-wide and the first one's users must not be
    disturbed by the second one's refusal. Reached the way an operator reaches it: both
    rows are enabled while their nodes are drafts, which is the ordinary order — a node
    is configured before it is put into service — and users are added in between, which a
    draft node's pool is not measured against because nobody is being granted on it yet.

    Note what this does NOT claim: that a short row on a node nobody is touching blocks
    an unrelated node. It does not, because nothing is granted on it — that row refuses
    the next ADD USER instead, which is asserted above.
    """
    roomy = await a_node(client, name="the-roomy-one", address="192.0.2.48")
    assert (await enable_pool(client, roomy, pool_transport)).status_code == 201

    cramped = await a_node(client, name="the-cramped-one", address="192.0.2.49")
    assert (
        await enable_pool(
            client,
            cramped,
            pool_transport,
            pool_size=1,
            tunnel="10.91.0.1/24",
            peer="10.91.0.2/24",
        )
    ).status_code == 201

    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    await nodes.set_node_state(session, node_id=roomy, state=NodeState.ACTIVE)
    covered = (
        await session.execute(select(Credential))
    ).scalars().unique().all()
    assert len(covered) == 2, "the first node did not cover both users"

    before = await audit_rows(session)
    with pytest.raises(Conflict) as refused:
        await nodes.set_node_state(session, node_id=cramped, state=NodeState.ACTIVE)
    assert "the-cramped-one" in str(refused.value)
    assert pool_transport in str(refused.value)

    session.expire_all()
    node = await nodes.get_node(session, cramped)
    assert node.state == NodeState.DRAFT, "the node went serving on a refused request"
    assert await audit_rows(session) == before, "a refusal reached the audit trail"
    # And the other node's users are exactly as they were: a refusal on one node's
    # activation must not roll back what another node had already committed.
    assert len(
        (await session.execute(select(Credential))).scalars().unique().all()
    ) == len(covered)


# --- the race the constraint exists for ---------------------------------------

async def test_two_changes_reaching_one_address_end_in_a_refusal(
    client, session, app, pool_transport: str, monkeypatch
) -> None:
    """Deterministic, and it has to be: a timing test proves nothing about a window.

    The allocator reads which addresses are held and then writes; nothing serialises two
    of them, by decision (no lock is taken — see ``services/placement.py`` for the same
    call about ports). What closes the window is the unique constraint, and the only
    honest way to exercise it is to make one reader's answer STALE on purpose: another
    session commits the address first, and this one is told it is still free.

    Never two loops racing. That would be a test that passes because a machine was slow.
    """
    node_id = await a_node(client, name="contended", address="192.0.2.50")
    enabled = await enable_pool(client, node_id, pool_transport)
    assert enabled.status_code == 201, enabled.text
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await add_user(client, "first")).status_code == 201

    # The address the next user would be given, taken by somebody else first — committed
    # from a session of its own, so the allocator's read is genuinely against data another
    # transaction wrote.
    row = await session.get(NodeTransport, row_id)
    stale = await addresses.held_digests(session, row)
    box = secret_box()
    contested = next(
        address
        for address in addresses.pool_of(row)
        if box.address_digest(row.id, address) not in stale
    )
    async for other in app.state.database.session():
        rival = Friend(nickname="rival")
        other.add(rival)
        await other.flush()
        other.add(
            Credential(
                friend_id=rival.id,
                node_transport_id=row_id,
                subject="rival-subject",
                secrets=json.dumps({}),
                tunnel_address=contested,
                tunnel_address_digest=box.address_digest(row_id, contested),
            )
        )
        await other.commit()
        break

    # And the allocator is told what it would have read a moment earlier.
    async def a_stale_answer(session_, node_transport):
        monkeypatch.undo()
        return stale

    monkeypatch.setattr(addresses, "held_digests", a_stale_answer)

    refused = await add_user(client, "second")
    assert refused.status_code == 409, refused.text
    assert "same moment" in refused.json()["error"]["message"]

    session.expire_all()
    digests = (
        await session.execute(
            select(Credential.tunnel_address_digest).where(
                Credential.node_transport_id == row_id
            )
        )
    ).scalars().all()
    assert len(digests) == len(set(digests)), "two credentials hold one address"
    assert (
        await session.execute(select(Friend).where(Friend.nickname == "second"))
    ).scalars().first() is None, "the losing change was committed after all"


# --- what must not move an address --------------------------------------------

async def test_rotating_material_leaves_every_address_where_it_was(
    client, session, pool_transport: str
) -> None:
    """A rotation replaces key material. It must not move a device's address.

    This is the whole reason the address is a column of its own rather than a value
    inside the credential's ``secrets`` mapping, which ``rotate_keys`` overwrites whole.
    """
    node_id = await a_node(client, name="rotated", address="192.0.2.51")
    enabled = await enable_pool(client, node_id, pool_transport)
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    before = sorted(routes_in(await as_the_node_sees_it(session, node_id, pool_transport)))

    # ``include_clients`` is the half that re-mints every user's own material, which is
    # the half that would take an address with it if the address lived in that mapping.
    # The push it then attempts reaches no node here and is not what is under test.
    await rotation.rotate_keys(
        session, node_transport_id=enabled.json()["id"], include_clients=True
    )

    after = sorted(routes_in(await as_the_node_sees_it(session, node_id, pool_transport)))
    assert after == before, "a rotation moved somebody's address"


async def test_revoking_a_user_frees_their_address_for_the_next_one(
    client, session, pool_transport: str
) -> None:
    """The lowest free address wins, so a revoked person's address is reused.

    Not merely tidiness: without it a pool would be consumed by people who have left, and
    an operator with thirty friends and a pool of thirty would run out by attrition.
    """
    node_id = await a_node(client, name="reused", address="192.0.2.52")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=2)).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    both = set(routes_in(await as_the_node_sees_it(session, node_id, pool_transport)))

    ann = (
        await session.execute(select(Friend).where(Friend.nickname == "ann"))
    ).scalars().one()
    await friends.revoke(session, friend_id=ann.id)

    assert (await add_user(client, "cara")).status_code == 201
    again = set(routes_in(await as_the_node_sees_it(session, node_id, pool_transport)))
    assert again == both, (
        "the address the revoked user held was not given to the next one, so the pool "
        "leaks a place per departure"
    )


async def test_removing_a_transport_takes_every_address_with_it(
    client, session, pool_transport: str
) -> None:
    """The cascade already destroys the credentials; the addresses go with them.

    Asserted because the addresses are a second column on that row: a cascade that left
    digests behind would refuse the next person to be granted on a transport re-enabled
    under the same parameters, with nothing on any screen to explain it.
    """
    node_id = await a_node(client, name="removed", address="192.0.2.53")
    enabled = await enable_pool(client, node_id, pool_transport)
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await add_user(client, "ann")).status_code == 201

    await nodes.remove_transport(session, node_transport_id=enabled.json()["id"])

    session.expire_all()
    assert (
        await session.execute(select(Credential.tunnel_address_digest))
    ).scalars().all() == []


async def test_a_hop_end_is_given_no_address_and_no_pool(
    client, session, pool_transport: str
) -> None:
    """A hop is a pair of peers, not a fleet — so neither end has a pool at all.

    The establish-hop dialog is untouched by this milestone, and this is the assertion
    that says so from the other side: the rows it writes carry no pool size, and nothing
    allocates against them.
    """
    entry = await a_node(client, name="entry-node", address="192.0.2.54")
    leaf = await a_node(client, name="leaf-node", address="192.0.2.55")
    if not profile(pool_transport).meta.hop_capable:
        pytest.skip(f"{pool_transport} declares it cannot carry a hop")

    established = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry,
            "leaf_node_id": leaf,
            "transport_name": pool_transport,
            # No pool size at either end, and the endpoint takes none: a hop is a pair of
            # peers and the far end's single address is what ``peer_tunnel_address``
            # already means there.
            "entry_params": params_for(
                pool_transport,
                tunnel_address="10.92.0.1/24",
                peer_tunnel_address="10.92.0.2/24",
            ),
            "leaf_params": params_for(
                pool_transport,
                tunnel_address="10.92.0.2/24",
                peer_tunnel_address="10.92.0.1/24",
            ),
        },
    )
    assert established.status_code == 201, established.text

    rows = (
        await session.execute(
            select(NodeTransport).where(
                NodeTransport.purpose.in_(TransportPurpose.relays())
            )
        )
    ).scalars().unique().all()
    assert len(rows) == 2
    for row in rows:
        assert row.pool_size is None, "a hop end was given a pool of addresses"
    assert (
        await session.execute(select(Credential))
    ).scalars().unique().all() == [], "a hop end minted a credential"


async def test_a_node_with_two_users_on_one_tunnel_renders_through_a_revocation(
    client, session, pool_transport: str, reality_params
) -> None:
    """Revocation re-renders every node the person was on — including this one.

    The path this milestone's own defect travelled: an unrelated node that could not be
    rendered made "remove this person's access" answer with an internal error, and
    nobody could tell whether the removal had happened. With an address each, the render
    the revocation depends on is one the node accepts.
    """
    if not PLAIN_TRANSPORTS:
        pytest.skip("this image ships no second kind of transport to revoke from")

    node_id = await a_node(client, name="mixed", address="192.0.2.56")
    assert (await enable_pool(client, node_id, pool_transport)).status_code == 201
    assert (
        await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": PLAIN_TRANSPORTS[0], "params": reality_params},
        )
    ).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob", "cara"):
        assert (await add_user(client, nickname)).status_code == 201

    cara = (
        await session.execute(select(Friend).where(Friend.nickname == "cara"))
    ).scalars().one()
    affected = await friends.revoke(session, friend_id=cara.id)
    assert affected, "the revocation found nothing to re-push"

    config = await as_the_node_sees_it(session, node_id, pool_transport)
    routes = routes_in(config)
    assert len(routes) == 2 and len(set(routes)) == 2, config
