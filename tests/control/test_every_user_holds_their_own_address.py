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

import ast
import hashlib
import json
import pathlib
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
from control.app.panel import routes as panel_routes
from control.app.services import (
    addresses,
    apply,
    console,
    friends,
    nodes,
    rotation,
    subscriptions,
)
from edge.addressing import host_of, pool
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


# AT MODULE LEVEL, because that is the only place it can fire. An empty
# ``params`` list makes pytest generate one item skipped with its own generic reason
# ("got empty parameter set") and never run the fixture BODY — so a guard written inside
# the fixture is a sentence that cannot be printed, and an image that shipped no such
# transport would report this whole file as skipped with nothing in its own vocabulary
# saying why the milestone's verification had vanished.
pytestmark = pytest.mark.skipif(
    not POOL_TRANSPORTS,
    reason="this image ships no transport that gives each user an address",
)


@pytest.fixture(params=POOL_TRANSPORTS)
def pool_transport(request) -> str:
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

@pytest.mark.parametrize("people", [2, 3])
async def test_users_on_one_row_are_routed_separately(
    client, session, pool_transport: str, people: int
) -> None:
    """Both shipped members of the family, not only the one another file happens to use.

    ``test_second_subscription_format`` asserts the same property for the first
    file-serialising transport this image ships; the plan's done-when names BOTH — "two
    and three users on one friend-facing amneziawg row, AND on one wireguard row" — and
    a family whose second member was never exercised at three is a family with one
    member tested. The two counts are not the same claim: two is "the second person gets
    a second address", three is "the allocator keeps walking the pool".
    """
    node_id = await a_node(client, name="pair", address="192.0.2.40")
    assert (await enable_pool(client, node_id, pool_transport)).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    for nickname in ("ann", "bob", "cara")[:people]:
        assert (await add_user(client, nickname)).status_code == 201

    config = await as_the_node_sees_it(session, node_id, pool_transport)
    routes = routes_in(config)
    assert len(routes) == people, config
    assert len(set(routes)) == people, (
        f"{people} users share {len(set(routes))} routes — one of them silently takes "
        "over another's return path"
    )
    # Each of them is one host and not a range: AllowedIPs is the authorisation list as
    # well as the routing table, so a wide entry lets that user source traffic as anybody.
    for route in routes:
        assert route.endswith("/32"), route


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
    # AND IT CARRIES NO KEY MATERIAL. This sentence is composed from the peers it could
    # not place apart, each of which holds a private half, and it reaches an operator
    # through the panel's banner and the API's envelope — and, as a degraded node's
    # ``state_detail``, a durable record. Asserted against the stored values rather than
    # against a field name, so it holds for a transport that calls its key something else.
    private = [
        str(value)
        for row in (await session.execute(select(Credential))).scalars().unique()
        for name, value in json.loads(row.secrets).items()
        if "private" in name
    ]
    assert private, "this transport mints no private half, so pick another for this"
    for secret in private:
        assert secret not in str(refused.value), "a render refusal quoted key material"

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

    BOTH NODES SERVE AND A FRIEND EXISTS, which is what gives the second assertion
    anything to be false about: with no friend in the database no credential can exist
    whatever the code does, so "a hop end minted a credential" would have been green
    against any production. With a friend added AFTER both ends are serving, a
    ``serving_transports`` that stopped filtering on purpose — or an
    ``establish_hop`` that minted per end — puts a credential on a relay row and this
    turns red.
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

    for node_id in (entry, leaf):
        await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await add_user(client, "ann")).status_code == 201

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
    on_a_hop_end = (
        await session.execute(
            select(Credential).where(
                Credential.node_transport_id.in_([row.id for row in rows])
            )
        )
    ).scalars().unique().all()
    assert on_a_hop_end == [], "a hop end was granted to a friend"


async def test_a_hop_end_is_offered_no_pool_box_and_refuses_a_size_typed_at_it(
    client, session, pool_transport: str
) -> None:
    """The other half of the promise above: the replace dialog leaves a hop end alone.

    "A hop end has no pool" was asserted at CREATION only, and creation is not where a
    pool size can arrive. The transport the runbook mandates for the hop is the one it
    recommends for friends, so a box decided from the transport's declaration appeared on
    both ends of every hop — hinted "how many users this protocol may hand an address to"
    on a tunnel between two of the owner's own nodes, two lines above this same dialog's
    own "No user holds anything on it: this is one end of a hop".

    BOTH SURFACES, because the box is only half of it: the API takes a ``pool_size`` on
    the same route, so a dialog that stopped offering the control would still leave a
    script able to write the number.
    """
    if not profile(pool_transport).meta.hop_capable:
        pytest.skip(f"{pool_transport} declares it cannot carry a hop")
    entry = await a_node(client, name="hop-box-entry", address="192.0.2.82")
    leaf = await a_node(client, name="hop-box-leaf", address="192.0.2.83")
    established = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry,
            "leaf_node_id": leaf,
            "transport_name": pool_transport,
            "entry_params": params_for(
                pool_transport,
                tunnel_address="10.93.0.1/24",
                peer_tunnel_address="10.93.0.2/24",
            ),
            "leaf_params": params_for(
                pool_transport,
                tunnel_address="10.93.0.2/24",
                peer_tunnel_address="10.93.0.1/24",
            ),
        },
    )
    assert established.status_code == 201, established.text
    end_id = established.json()["entry"]["id"]

    dialog = await client.get(f"/panel/keys/{end_id}/params")
    assert dialog.status_code == 200
    # The dialog itself is there and unchanged — the transport's own boxes are rendered.
    assert 'name="port"' in dialog.text
    assert f'name="{addresses.POOL_BOX}"' not in dialog.text

    refused = await resize(client, end_id, pool_size=5)

    assert refused.status_code == 400, refused.text
    message = refused.json()["error"]["message"]
    assert addresses.POOL_BOX in message, message
    # Named, so a script resizing rows by id is told which of them it was.
    assert "hop-box-entry" in message, message
    session.expire_all()
    assert (await session.get(NodeTransport, end_id)).pool_size is None


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


# --- resizing: a row is sized where its parameters are replaced (M17.1c) ------
#
# There is no resize action and no resize endpoint, on purpose and in writing: migration
# 0006 promises an operator that a row serving since before M17 is sized by replacing
# that row's parameters. These are that promise, and the two things it may not cost —
# an address that moves, and a tunnel that walks out from under the people in it.

async def resize(client, node_transport_id: str, **body):
    """The one surface a pool is resized through: replacing the row's parameters."""
    return await client.post(
        f"/api/transports/{node_transport_id}/params", json={"params": {}, **body}
    )


async def test_a_row_from_before_pools_is_sized_without_moving_the_address_in_use(
    client, session, pool_transport: str
) -> None:
    """The field's own broken row, repaired — and the working device never touched.

    The setup is the upgrade exactly: a row with no pool size, one person who has been
    connected for weeks whose address exists only as the row's own parameter, and a
    second person who was granted a credential and has never had an address that works.
    The node cannot render at all in that state.

    After the resize: the first person's address is the one they already had — asserted
    as the BYTES of their own file, which is the file this project cannot reissue without
    them doing something — and the second person has an address of their own, so the node
    renders two distinct routes.

    WHAT THIS ONE DOES NOT PROVE, said here because the name suggests otherwise: with the
    pool left where it is, ``settle``'s own adoption rule reaches the same answer as
    ``pin_in_use``, so this stays green with the pin deleted. It is the end-to-end claim —
    the field's row, repaired, bytes unchanged. The pin itself is proven by the two tests
    below, which are the shapes where the two answers differ.
    """
    node_id = await a_node(client, name="repaired", address="192.0.2.70")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    assert enabled.status_code == 201, enabled.text
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("early", "later"):
        assert (await add_user(client, nickname)).status_code == 201

    await as_it_was_before_m17(session, row_id)

    async def their_file() -> str:
        # Re-read rather than held across the call: a resize commits, and the assertion
        # below expires every object in this session to make sure it is reading the
        # database rather than what it had in hand.
        early = (
            await session.execute(select(Friend).where(Friend.nickname == "early"))
        ).scalars().one()
        return "\n".join(
            config.content
            for config in await subscriptions.config_files_for(session, early)
        )

    before = await their_file()

    sized = await resize(client, row_id, pool_size=ROOMY)
    assert sized.status_code == 200, sized.text
    # The push that follows every replacement cannot land on a test node with no host
    # behind it, and a failed push degrades the node — which takes it out of every
    # subscription, so the file below would come back empty for a reason that has nothing
    # to do with addresses. Put it back the way the operator does once the node is
    # reachable again.
    #
    # EXPIRED FIRST, and it is not optional: that failure was written by the request's own
    # session and this one still holds the node as it was before it. ``set_node_state``
    # compares the state it is given against the object in hand, so a stale ``active``
    # here makes the call a no-op and leaves the node degraded — which is how this
    # assertion read "the file is empty" on one run and passed on the next.
    session.expire_all()
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    session.expire_all()
    assert (await session.get(NodeTransport, row_id)).pool_size == ROOMY
    assert hashlib.sha256((await their_file()).encode()).hexdigest() == \
        hashlib.sha256(before.encode()).hexdigest(), (
            "the resize moved the address of a device that was already working"
        )

    routes = routes_in(await as_the_node_sees_it(session, node_id, pool_transport))
    assert len(routes) == 2 and len(set(routes)) == 2, routes
    # And the person who was already on it is still authorised for the address their
    # file carries — the two renders of one allocation, after a resize.
    assert host_of(address_in(before)) in {host_of(route) for route in routes}


async def test_a_pre_pool_row_cannot_be_moved_off_the_address_it_is_handing_out(
    client, session, pool_transport: str
) -> None:
    """THE PIN AGAIN, from the other side: what it makes VISIBLE to the range check.

    On a row from before pools the address in use is nowhere in the database — it is the
    row's own parameter and a renderer's fallback — so ``stranded_by`` has nothing to
    measure and a tunnel moved out from under it is accepted in silence. ``pin_in_use``
    writes it down first, which is the only reason the refusal below exists.

    The test above it asserts the same setup is sized without moving anybody; it is
    satisfied by ``settle``'s own adoption rule even with the pin absent, because the pool
    does not move there. This one is not: delete the pin and the submission below is
    accepted, with a working device stranded and every screen green.
    """
    node_id = await a_node(client, name="pre-pool-moved", address="192.0.2.84")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("early", "later"):
        assert (await add_user(client, nickname)).status_code == 201
    await as_it_was_before_m17(session, row_id)

    spec = addresses.spec_for(pool_transport)
    refused = await resize(
        client,
        row_id,
        params={spec.within: "10.94.0.1/24", spec.name: "10.94.0.2/24"},
        pool_size=ROOMY,
    )

    assert refused.status_code == 400, refused.text
    assert spec.within in refused.json()["error"]["message"]
    session.expire_all()
    row = await session.get(NodeTransport, row_id)
    assert row.params[spec.within] != "10.94.0.1/24", "a refused move was stored anyway"
    assert row.pool_size is None, "a refused resize sized the row anyway"
    # And the pin itself left nothing behind: the refusal rolled back before it returned.
    assert (
        await session.execute(
            select(Credential.tunnel_address_digest).where(
                Credential.node_transport_id == row_id
            )
        )
    ).scalars().all() == [None, None]


async def test_moving_the_pool_under_an_unwritten_address_leaves_that_device_alone(
    client, session, pool_transport: str
) -> None:
    """THE PIN, and the only shape that can tell whether it is there.

    A row from before pools hands out one address and records it nowhere: it is the row's
    own parameter, and the renderer falls back to it. So an operator who sizes that row
    AND starts the pool somewhere else — reserving the low addresses for something, which
    is an ordinary thing to want — would otherwise have the person who has been connected
    all along allocated the pool's new first address. Their device is configured with the
    old one. Nobody is going to reconfigure it, and nothing on any screen would say so.

    ``pin_in_use`` writes the address down before a parameter moves, so the allocation
    that follows sees it as taken. What proves it is that the address the device holds is
    OUTSIDE the new pool afterwards — which no ordering of the allocator could produce by
    accident, and which is harmless: an address nobody else can be given is a pool slot
    spent, and the alternative is a person cut off.
    """
    node_id = await a_node(client, name="pinned", address="192.0.2.80")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await add_user(client, "connected")).status_code == 201
    await as_it_was_before_m17(session, row_id)

    spec = addresses.spec_for(pool_transport)
    in_use = host_of(str((await session.get(NodeTransport, row_id)).params[spec.name]))

    # Same tunnel, same range — only the pool's first address moves up, and it is sized.
    sized = await resize(
        client, row_id, params={spec.name: "10.90.0.20/24"}, pool_size=ROOMY
    )
    assert sized.status_code == 200, sized.text

    session.expire_all()
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    session.expire_all()
    held = {
        host_of(route)
        for route in routes_in(await as_the_node_sees_it(session, node_id, pool_transport))
    }
    assert held == {in_use}, (
        "the device that was already connected was moved to the pool's new first address"
    )
    assert host_of("10.90.0.20/24") not in held

    # And the next person gets the pool's first address, which is now free of anybody.
    assert (await add_user(client, "newcomer")).status_code == 201
    after = {
        host_of(route)
        for route in routes_in(await as_the_node_sees_it(session, node_id, pool_transport))
    }
    assert after == {in_use, host_of("10.90.0.20/24")}, after


async def test_a_resize_is_audited_as_a_replacement_and_nothing_else(
    client, session, pool_transport: str
) -> None:
    """One operator action, one entry, under the action item 24 already had.

    A resize that invented an audit action of its own would be a second name for one
    operation in the one record the operator reads back — and the entry carries the node
    and the transport, never the size, because a count of people is not a thing this
    trail keeps.
    """
    node_id = await a_node(client, name="audited", address="192.0.2.71")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    row_id = enabled.json()["id"]
    before = await audit_rows(session)

    assert (await resize(client, row_id, pool_size=ROOMY)).status_code == 200

    session.expire_all()
    added = [entry for entry in await audit_rows(session) if entry not in before]
    # ONE entry about the transport. The other entry this leaves is the node going
    # ``degraded``: the push that follows every replacement cannot land on a test node
    # with no host behind it, and that is a fact about the fixture rather than about the
    # resize — asserted here rather than filtered away, so a resize that started writing
    # something else about the node turns this red.
    assert added == [
        ("params-replaced", "audited", pool_transport),
        ("node-state-changed", "audited", "degraded"),
    ], added


async def test_a_resize_below_what_the_row_already_hands_out_is_refused(
    client, session, pool_transport: str
) -> None:
    """A pool cannot be shrunk out from under the people already in it.

    Two users hold the first two addresses; a pool of one would leave the second holding
    an address the row no longer hands out. Refused with nothing written — the row keeps
    its size and both devices keep their addresses.
    """
    node_id = await a_node(client, name="shrunk", address="192.0.2.72")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201
    before = sorted(routes_in(await as_the_node_sees_it(session, node_id, pool_transport)))

    refused = await resize(client, row_id, pool_size=1)

    assert refused.status_code == 400, refused.text
    assert addresses.POOL_BOX in refused.json()["error"]["message"]
    session.expire_all()
    assert (await session.get(NodeTransport, row_id)).pool_size == ROOMY
    after = sorted(routes_in(await as_the_node_sees_it(session, node_id, pool_transport)))
    assert after == before, "a refused resize moved somebody's address"


async def test_moving_the_tunnel_out_from_under_a_held_address_is_refused(
    client, session, pool_transport: str
) -> None:
    """The defect M17.1b left behind: a replaced parameter with no pool re-check.

    ``tunnel_address`` is an ordinary replaceable parameter, so an operator could move
    the row to a different range — or narrow its prefix — while people held addresses
    inside the old one. Nothing moves their addresses, which is the promise; what would
    happen instead is that their addresses stop being carried by the interface, with
    every screen green.

    Refused under the box the RANGE is typed in, not under the pool's size: the size did
    not cause it and a complaint under a number the operator never touched sends them to
    change the wrong thing.
    """
    node_id = await a_node(client, name="moved", address="192.0.2.73")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    assert (await add_user(client, "ann")).status_code == 201
    before = routes_in(await as_the_node_sees_it(session, node_id, pool_transport))

    spec = addresses.spec_for(pool_transport)
    refused = await resize(
        client,
        row_id,
        params={spec.within: "10.99.0.1/24", spec.name: "10.99.0.2/24"},
    )

    assert refused.status_code == 400, refused.text
    message = refused.json()["error"]["message"]
    assert spec.within in message, message
    assert "10.99.0.1/24" in message, message
    # The cause, and the right one of the five: this address is genuinely outside.
    assert "outside the range" in message, message
    # A COUNT and not an address: what is refused is stated without saying who holds what.
    for route in before:
        assert host_of(route) not in message, "a refusal named an address somebody holds"

    session.expire_all()
    assert (await session.get(NodeTransport, row_id)).params[spec.within] != "10.99.0.1/24"
    assert routes_in(await as_the_node_sees_it(session, node_id, pool_transport)) == before


async def test_the_refusal_names_which_of_the_causes_stranded_somebody(
    client, session, pool_transport: str
) -> None:
    """The case with a victim, and the one the first wording sent round a loop.

    Moving the node's own address onto an address somebody holds is the hazard this whole
    milestone exists for: that person would be authorised to send as the node, and
    everything the node is sent on the tunnel would be routed to them. It is refused —
    and it used to be refused with "would fall outside", about an address that is INSIDE
    the range. The operator's obvious answer to "outside" is a wider prefix, which leaves
    the node's own address exactly where it is, so the identical sentence comes back.

    Not asserted here: that no held address appears in the message. In this shape the
    range the operator typed IS that address — it is their own submission coming back —
    and the neighbour above pins the general rule.
    """
    node_id = await a_node(client, name="renumbered", address="192.0.2.85")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    spec = addresses.spec_for(pool_transport)
    # The range stays; the node moves onto the second person's address, and the pool's
    # first address moves out of the way so the SIZE is not what refuses this.
    refused = await resize(
        client,
        row_id,
        params={spec.within: "10.90.0.3/24", spec.name: "10.90.0.20/24"},
    )

    assert refused.status_code == 400, refused.text
    message = refused.json()["error"]["message"]
    assert "node's own address" in message, message
    assert "outside" not in message, message
    assert "renumbered" in message, message
    # One person, not both: ann at .2 is still carried by this tunnel and is not counted.
    assert "1 is" in message, message
    session.expire_all()
    assert (await session.get(NodeTransport, row_id)).params[spec.within] != "10.90.0.3/24"


async def test_a_resize_a_transport_hands_out_no_address_for_is_refused(
    client, session, reality_params
) -> None:
    """A number that would mean nothing is refused here exactly as it is at enable.

    Same sentence, same box, from the same function — the two paths that can set a size
    must not be able to disagree about what a size means.
    """
    if not PLAIN_TRANSPORTS:
        pytest.skip("this image ships no transport that identifies its users by material")
    node_id = await a_node(client, name="sizeless", address="192.0.2.74")
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": PLAIN_TRANSPORTS[0], "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text

    refused = await resize(client, enabled.json()["id"], pool_size=10)

    assert refused.status_code == 400, refused.text
    assert addresses.POOL_BOX in refused.json()["error"]["message"]


async def test_replacing_a_parameter_on_a_short_pool_is_not_refused_by_the_fleet(
    client, session, pool_transport: str
) -> None:
    """Rotating away from a blocked value must not be blocked by an unrelated shortfall.

    A row whose pool is already smaller than the fleet is a row with a problem — and
    refusing every parameter replacement on it would take away the operator's first job
    in the charter, which is rotating what gets blocked. The fleet question is asked when
    somebody is SIZING a pool; it is not asked of somebody replacing a range.
    """
    node_id = await a_node(client, name="short-but-rotatable", address="192.0.2.75")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=1)
    row_id = enabled.json()["id"]
    for nickname in ("ann", "bob", "cara"):
        assert (await add_user(client, nickname)).status_code == 201

    spec = addresses.spec_for(pool_transport)
    replaced = await resize(
        client,
        row_id,
        params={spec.within: "10.95.0.1/24", spec.name: "10.95.0.2/24"},
    )

    assert replaced.status_code == 200, replaced.text
    session.expire_all()
    assert (await session.get(NodeTransport, row_id)).params[spec.within] == "10.95.0.1/24"


async def test_a_serving_row_whose_pool_is_short_can_still_be_rotated(
    client, session, pool_transport: str
) -> None:
    """The same carve-out on the row it was written for — the field's own, after 0006.

    The test above it takes a node that never became serving, so nobody holds a credential
    on that row and the allocator has nothing to refuse. On a SERVING row the two
    conditions are one: every active friend is granted there, so a pool smaller than the
    fleet means credentials with no address, and ``settle`` raised ``PoolFull`` a few
    lines after ``sized_pool`` had deliberately let the rotation through — rolling back the
    whole thing. The escape hatch was dead in exactly the state it names.

    What must NOT happen is that the swallowed refusal hides the shortfall: the pool is
    as short afterwards as it was before, nobody's address moves, and the operator is told
    by the push — which cannot render a row whose users have no address of their own, and
    reports that node as not updated. Sizing the row afterwards still repairs it.
    """
    node_id = await a_node(client, name="short-and-serving", address="192.0.2.79")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201
    # After migration 0006: no size, and nobody's address written down.
    await as_it_was_before_m17(session, row_id)

    rotated = await resize(client, row_id, params={"port": 51999})

    assert rotated.status_code == 200, rotated.text
    # Told, and by the honest channel: the database took the new port and the node did not.
    assert rotated.json()["complete"] is False
    assert "short-and-serving" in rotated.json()["summary"]
    session.expire_all()
    row = await session.get(NodeTransport, row_id)
    assert row.params["port"] == 51999
    assert row.pool_size is None, "a rotation that asked for no size gave the row one"
    # One address written down — the one the row was ALREADY handing out, which the pin
    # records and never moves — and the person who arrived second still waiting, exactly
    # as they were before this call.
    written = (
        await session.execute(
            select(Credential.tunnel_address_digest).where(
                Credential.node_transport_id == row_id
            )
        )
    ).scalars().all()
    assert sorted(held is None for held in written) == [False, True], written

    # And the repair is still available: sizing the row places everybody who was waiting.
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    sized = await resize(client, row_id, pool_size=ROOMY)
    assert sized.status_code == 200, sized.text
    session.expire_all()
    routes = routes_in(await as_the_node_sees_it(session, node_id, pool_transport))
    assert len(routes) == 2 and len(set(routes)) == 2, routes


async def test_a_resize_that_loses_a_race_for_an_address_is_a_refusal(
    client, session, app, pool_transport: str, monkeypatch
) -> None:
    """The constraint closes this window too, and the operator gets a sentence for it.

    A resize allocates: everybody on the row who has no address of their own is given one
    inside the transaction that widens the pool. So it meets the same race adding a user
    does — nothing serialises the read of who holds what against the write that follows —
    and the same backstop, ``uq_credential_tunnel_address``, refuses the loser rather than
    letting two people hold one address.

    Made stale on purpose rather than raced, exactly as
    ``test_two_changes_reaching_one_address_end_in_a_refusal`` does it and for the same
    reason: a timing test proves nothing about a window. What this adds is that the loss
    arrives as a REFUSAL — the same words the add-a-user path uses — rather than as the
    database error underneath it, which would be a 500 the console never swaps.
    """
    node_id = await a_node(client, name="raced-resize", address="192.0.2.81")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("first", "second"):
        assert (await add_user(client, nickname)).status_code == 201
    await as_it_was_before_m17(session, row_id)

    # The two addresses this resize will place: the first is the one the pin writes down
    # for the person who has been on this row all along, and the second is the one the
    # person beside them would be settled onto.
    row = await session.get(NodeTransport, row_id)
    box = secret_box()
    spec = addresses.spec_for(pool_transport)
    pinned, contested = list(pool(str(row.params[spec.name]), 2))

    # Taken by somebody else first, committed from a session of its own — so the
    # allocator's read is genuinely against data another transaction wrote.
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

    # What the allocator would have read a moment earlier: the pinned address taken and
    # nothing else. The PIN itself is told the truth — it runs first, and staling it would
    # make this a test about the pin colliding with its own row rather than about two
    # changes reaching one address.
    truthfully = addresses.held_digests
    asked = []

    async def a_stale_answer(session_, node_transport):
        asked.append(node_transport.id)
        if len(asked) == 1:
            return await truthfully(session_, node_transport)
        monkeypatch.undo()
        return {box.address_digest(row_id, pinned)}

    monkeypatch.setattr(addresses, "held_digests", a_stale_answer)

    refused = await resize(client, row_id, pool_size=ROOMY)

    assert refused.status_code == 409, refused.text
    assert "same moment" in refused.json()["error"]["message"]

    # And nothing of the resize survived: not the size, not a second address.
    session.expire_all()
    assert (await session.get(NodeTransport, row_id)).pool_size is None
    # NULLs included in the query and dropped here: the two people this resize would have
    # placed are back to holding nothing, which is the rollback, and a NULL is not an
    # allocation — Postgres lets any number of them sit under the unique constraint, which
    # is what lets a row that pre-dates M17 exist at all.
    digests = [
        digest
        for digest in (
            await session.execute(
                select(Credential.tunnel_address_digest).where(
                    Credential.node_transport_id == row_id
                )
            )
        ).scalars().all()
        if digest is not None
    ]
    assert len(digests) == 1, "the resize placed somebody after all"


# --- the box the operator types the size into ---------------------------------

# The form the console submits, and the id its dialog wires an error to. The panel names
# every box for its transport's GROUP — one group is rendered per transport and the
# hidden ones still submit — so the prefix belongs here rather than in each test.
ENABLE_ERROR = re.compile(r'id="enable-(.+?)-error"[^>]*>(.*?)</div>', re.S)
HTMX = {"HX-Request": "true"}


def enable_form(transport_name: str, *, pool_size: str | None = str(ROOMY)) -> dict:
    """The enable dialog's own submission, with every box filled and named for its group.

    ``pool_size=None`` leaves the box out entirely, which is what an operator who tabbed
    past it sends — a form control submits its name with an empty value, and the route
    treats both the same way.
    """
    typed = {
        f"{transport_name}-{name}": str(value)
        for name, value in params_for(
            transport_name,
            port=51820,
            tunnel_address="10.90.0.1/24",
            peer_tunnel_address="10.90.0.2/24",
        ).items()
    }
    if pool_size is not None:
        typed[f"{transport_name}-{addresses.POOL_BOX}"] = pool_size
    return {"transport_name": transport_name, **typed}


def field_errors(response) -> dict[str, str]:
    """Each complaint by the box it was wired to, read off ``aria-describedby``'s id."""
    return {
        name: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()
        for name, text in ENABLE_ERROR.findall(response.text)
    }


async def test_the_panel_refuses_an_empty_pool_box_under_the_box(
    client, session, pool_transport: str
) -> None:
    """Nothing defaults the size, and the console says so where the number goes.

    A default pool size would be a number this project chose for somebody else's node,
    which is the same rule that keeps a range out of the tree. So the empty box gets the
    answer every other empty box on this form gets, under itself rather than as a
    sentence above the form the operator has to map back onto a control.
    """
    node_id = await a_node(client, name="panel-empty", address="192.0.2.60")

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=enable_form(pool_transport, pool_size=""),
        headers=HTMX,
    )

    assert refused.status_code == 422, refused.text
    errors = field_errors(refused)
    assert errors.get(f"{pool_transport}-{addresses.POOL_BOX}") == panel_routes.NO_DEFAULT
    session.expire_all()
    assert (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().all() == [], "a refused form enabled a transport"


async def test_the_panel_refuses_a_pool_box_that_is_not_a_count(
    client, session, pool_transport: str
) -> None:
    """Text where a count goes is a refusal, not a 500 and not a silent zero.

    The service's parameter is an integer and a form gives it text, so the conversion is
    the panel's and so is its failure. The SENTENCE quotes nothing back — what arrived is
    not a number and repeating it inside the complaint tells the operator nothing — while
    the BOX keeps it, like every other refusal on this form, so nothing has to be retyped.
    """
    node_id = await a_node(client, name="panel-text", address="192.0.2.61")

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=enable_form(pool_transport, pool_size="lots"),
        headers=HTMX,
    )

    assert refused.status_code == 422, refused.text
    errors = field_errors(refused)
    assert (
        errors.get(f"{pool_transport}-{addresses.POOL_BOX}")
        == panel_routes.POOL_NOT_A_NUMBER
    )
    assert "lots" not in errors[f"{pool_transport}-{addresses.POOL_BOX}"]
    # And it is still in the box: a refused form this operator has to retype is one they
    # retype wrongly.
    assert 'value="lots"' in refused.text


async def test_a_refused_box_is_also_stated_where_the_dialog_reopens(
    client, session, pool_transport: str
) -> None:
    """A refusal below the fold is a refusal nobody reads — M17.2's acceptance.

    This dialog is taller than a laptop's window (a line per transport the node already
    runs, then a group of boxes per transport this image ships) and a 422 re-renders it
    scrolled back to its own TOP, because the swap replaced the scrolling element. The
    pool box is the last field on the form, so its refusal was correctly worded,
    correctly styled and entirely off screen: the operator pressed again and got the
    same nothing. The project has met this before — M9's banner slot, cleared on
    ``htmx:afterRequest``, silently ate every banner the panel ever sent.

    What is asserted is the POSITION as well as the words: above the list of what the
    node already runs, which is the thing that pushed it down. ``app.js`` also moves
    focus to the refused control, which scrolls it into view; this is the half a test
    without a browser can hold.
    """
    node_id = await a_node(client, name="panel-top", address="192.0.2.62")
    # A list for the refusal to be pushed below, which is the condition of the finding.
    assert (await enable_pool(client, node_id, pool_transport)).status_code == 201

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=enable_form(pool_transport, pool_size=""),
        headers=HTMX,
    )

    assert refused.status_code == 422, refused.text
    said = _text_of(refused)
    assert f"The reason is under {addresses.POOL_BOX}" in said, said
    # Above the list, not after it. ``stack-6`` is the wrapper around the node's own rows.
    assert "stack-6" in refused.text, "no list, so this proves nothing"
    assert refused.text.index("Nothing was enabled.") < refused.text.index("stack-6")
    # …and the sentence itself has NOT moved up here: it is still under the box, which is
    # the only place it can be corrected from.
    assert (
        field_errors(refused)[f"{pool_transport}-{addresses.POOL_BOX}"]
        == panel_routes.NO_DEFAULT
    )
    # The box is marked, which is what ``app.js`` focuses and what a screen reader reads.
    assert 'aria-invalid="true"' in refused.text


async def test_a_value_too_long_for_a_box_is_refused_without_being_repeated(
    client, session, pool_transport: str
) -> None:
    """A thousand characters pasted into an address box came back as a thousand — M16, M17.

    A transport's validator quotes the value it rejected, so the refusal was the paste
    again, in a dialog, pushing every control below it off the screen. Two bounds close
    it: the box says no first, in its own sentence, and ``relay.refused_fields`` strikes
    an over-long value out of any complaint that still reaches one.

    WHAT IS STILL IN THE BOX is the paste, deliberately — every other refusal on this
    form keeps what was typed, and an operator who has to find a long value again finds a
    different one. An ``<input>`` does not grow with its value; a sentence does.
    """
    node_id = await a_node(client, name="panel-long", address="192.0.2.63")
    spec = addresses.spec_for(pool_transport)
    huge = "9" * 1000
    typed = enable_form(pool_transport)
    typed[f"{pool_transport}-{spec.name}"] = huge

    refused = await client.post(
        f"/panel/nodes/{node_id}/transports", data=typed, headers=HTMX
    )

    assert refused.status_code == 422, refused.text
    assert (
        field_errors(refused)[f"{pool_transport}-{spec.name}"]
        == panel_routes.VALUE_TOO_LONG
    )
    assert huge not in _text_of(refused), "the refusal repeated the value"
    assert f'value="{huge}"' in refused.text, "the paste has to be found again"
    session.expire_all()
    assert (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().all() == [], "a refused form enabled a transport"


async def test_the_size_typed_in_the_panel_is_the_size_the_row_is_given(
    client, session, pool_transport: str
) -> None:
    """The box reaches the column, and two users on the row get two addresses.

    The end the API half of this milestone cannot reach: the size is a column on the
    node-transport record and not a parameter of the transport, so it travels beside the
    transport's own mapping the whole way. Dropped anywhere on that journey, the enable
    is refused as unsized — or, worse, the row is created at a size nobody typed.
    """
    node_id = await a_node(client, name="panel-sized", address="192.0.2.62")

    enabled = await client.post(
        f"/panel/nodes/{node_id}/transports",
        data=enable_form(pool_transport, pool_size="7"),
        headers=HTMX,
    )

    assert enabled.status_code == 200, enabled.text
    session.expire_all()
    row = (
        await session.execute(
            select(NodeTransport).where(NodeTransport.node_id == node_id)
        )
    ).scalars().unique().one()
    assert row.pool_size == 7

    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201
    routes = routes_in(await as_the_node_sees_it(session, node_id, pool_transport))
    assert len(set(routes)) == 2, "the panel's own row hands two users one address"


# --- and the box it is resized in, on the dialog that replaces parameters ------

# The replace-parameters dialog names its boxes bare, with no group prefix: one row is
# being changed, so there is no second group to tell apart. Its error ids follow.
PARAM_ERROR = re.compile(r'id="param-(.+?)-error"[^>]*>(.*?)</div>', re.S)


def param_errors(response) -> dict[str, str]:
    """Each complaint on the replace dialog, by the box it was wired to."""
    return {
        name: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()
        for name, text in PARAM_ERROR.findall(response.text)
    }


async def test_the_console_offers_a_pool_box_only_where_there_is_a_pool(
    client, session, pool_transport: str, reality_params
) -> None:
    """The dialog an operator resizes from, and the one that must not offer to.

    There is no resize action anywhere in this console — this box is the whole surface,
    which is what "no new action and no new endpoint" means from the operator's side.
    """
    node_id = await a_node(client, name="dialog-pool", address="192.0.2.76")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    assert enabled.status_code == 201, enabled.text

    dialog = await client.get(f"/panel/keys/{enabled.json()['id']}/params")
    assert dialog.status_code == 200
    assert f'name="{addresses.POOL_BOX}"' in dialog.text
    # The size in place now, as its placeholder, exactly like every other box here: what
    # this form means by an empty box is "keep what is there".
    assert f'placeholder="{ROOMY}"' in dialog.text

    if not PLAIN_TRANSPORTS:
        return
    plain = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": PLAIN_TRANSPORTS[0], "params": reality_params},
    )
    assert plain.status_code == 201, plain.text
    without = await client.get(f"/panel/keys/{plain.json()['id']}/params")
    assert without.status_code == 200
    assert f'name="{addresses.POOL_BOX}"' not in without.text


async def test_the_size_typed_in_the_replace_dialog_reaches_the_row(
    client, session, pool_transport: str
) -> None:
    """The console's own path to sizing a row that has served since before pools.

    The box travels beside the transport's mapping and never inside it — a transport's
    model forbids what it did not declare, so a size that leaked into ``params`` would
    come back as a refusal about an unknown parameter rather than as a resize.
    """
    node_id = await a_node(client, name="panel-resize", address="192.0.2.77")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    row_id = enabled.json()["id"]
    await as_it_was_before_m17(session, row_id)

    resized = await client.post(
        f"/panel/keys/{row_id}/params",
        data={addresses.POOL_BOX: "9"},
        headers=HTMX,
    )

    assert resized.status_code == 200, resized.text
    session.expire_all()
    assert (await session.get(NodeTransport, row_id)).pool_size == 9


async def test_the_replace_dialog_refuses_a_pool_box_that_is_not_a_count(
    client, session, pool_transport: str
) -> None:
    """Text where a count goes, refused under the box — the enable form's own rule.

    The same sentence as the enable dialog's, because it is the same box answering the
    same question, and a second wording for one refusal is how the two screens start
    teaching different things.
    """
    node_id = await a_node(client, name="panel-resize-text", address="192.0.2.78")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)

    refused = await client.post(
        f"/panel/keys/{enabled.json()['id']}/params",
        data={addresses.POOL_BOX: "plenty"},
        headers=HTMX,
    )

    assert refused.status_code == 422, refused.text
    assert param_errors(refused).get(addresses.POOL_BOX) == panel_routes.POOL_NOT_A_NUMBER
    session.expire_all()
    assert (await session.get(NodeTransport, enabled.json()["id"])).pool_size == 2


async def test_the_console_puts_a_refused_resize_under_the_box_it_is_about(
    client, session, pool_transport: str
) -> None:
    """The service's own refusal, landing on the number the operator typed.

    Without the pool box in this form's allow-list the sentence would be withheld as a
    complaint with nowhere to go — which is the right default for a name this form does
    not render, and wrong for the one it does. The dialog is re-rendered at 422, which is
    the only status the console swaps.
    """
    node_id = await a_node(client, name="panel-too-small", address="192.0.2.79")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    refused = await client.post(
        f"/panel/keys/{enabled.json()['id']}/params",
        data={addresses.POOL_BOX: "1"},
        headers=HTMX,
    )

    assert refused.status_code == 422, refused.text
    said = param_errors(refused).get(addresses.POOL_BOX, "")
    assert "1" in said and said, said
    # In the page's words, like every other sentence a service composes (decision 9).
    assert "friend" not in said.lower(), said


STATE_ERROR = re.compile(r'id="node-state-error"[^>]*>(.*?)</div>', re.S)


async def test_a_node_that_cannot_be_granted_says_so_in_the_dialog_it_was_moved_from(
    client, session, pool_transport: str
) -> None:
    """The refusal reaches the operator on the path where the session was rolled back.

    THE SETUP IS REACHABLE FROM THE CONSOLE AND FROM NOWHERE ELSE IN THIS FILE: a pool
    sized while the node is still a DRAFT is measured against the fleet of that moment,
    and every friend added afterwards is accepted, because ``create_friend`` asks only
    about rows that are SERVING. Move the node to serving later and the fan-out meets a
    pool that cannot hold everybody.

    Nothing commits, which was already true. What this pins is the other half: the
    operator is TOLD. ``friends.grant_everywhere`` rolls the session back before raising,
    and a rollback expires every object in the identity map — so a ``Node`` this route
    had fetched before the call cannot be read afterwards without lazy I/O, which on an
    async session raises ``MissingGreenlet``, which is not a ``DomainError`` and leaves
    as a 500. The console swaps 422 and nothing else, so the operator saw a spinner stop
    and no sentence at all.
    """
    node_id = await a_node(client, name="late-fleet", address="192.0.2.63")
    assert (await add_user(client, "ann")).status_code == 201
    assert (
        await enable_pool(client, node_id, pool_transport, pool_size=1)
    ).status_code == 201
    # Accepted, and correctly: this node serves nobody yet.
    assert (await add_user(client, "bob")).status_code == 201

    refused = await client.post(
        f"/panel/nodes/{node_id}/state", data={"state": "active"}, headers=HTMX
    )

    assert refused.status_code == 422, refused.text
    said = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", STATE_ERROR.search(refused.text).group(1)))
    assert "late-fleet" in said and pool_transport in said, said
    # In the page's words, like every other sentence a service composes (decision 9).
    assert "friend" not in said.lower(), said

    # And the node did not move, on the screen behind the dialog as well as in the record.
    session.expire_all()
    assert (await nodes.get_node(session, node_id)).state == NodeState.DRAFT
    assert (
        await session.execute(select(Credential))
    ).scalars().unique().all() == [], "a refused state change minted a credential"


# --- no surface grants outside the transaction that commits it ----------------

APP = pathlib.Path(__file__).resolve().parents[2] / "control" / "app"
ROUTE_MODULES = (APP / "api" / "routes.py", APP / "panel" / "routes.py")


def calls_in(module: pathlib.Path) -> set[str]:
    """Every ``module.function(...)`` this file calls, as ``"module.function"``."""
    return {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }


def test_no_surface_enables_a_transport_without_granting_it() -> None:
    """Neither route grants after a commit, and neither enables without granting — M17.

    The defect this is written against is a real one and it survived a review: the panel
    kept the fan-out loop the API route had deleted, sitting after
    ``nodes.enable_and_grant`` had already granted everybody and COMMITTED, and outside
    the route's own try/except. In the window where a friend is created between the two,
    the second pass raises ``Conflict`` — a bare 409 the console does not swap — for an
    enable that had already succeeded.

    Asserted as an absence in the SOURCE rather than by driving the window, because the
    window needs two concurrent writes and the thing that must not come back is a call,
    not a timing. ``nodes.enable_transport`` is the other half of the same rule: it
    commits without granting, has no production caller, and a route drifting back onto it
    would put the enable and the grant in two transactions again.
    """
    for module in ROUTE_MODULES:
        called = calls_in(module)
        assert "friends.grant_everywhere" not in called, (
            f"{module} grants outside the service transaction that commits the change"
        )
        assert "nodes.enable_transport" not in called, (
            f"{module} enables a transport without granting it in the same transaction"
        )


def test_no_transport_declares_a_parameter_the_pool_box_would_shadow() -> None:
    """``pool_size`` is `control`'s own field name, and nothing else may claim it — M17.1c.

    Both forms that can carry a size strip it from the submission BY NAME before the rest
    reaches the transport's model, because the size is a column on the node-transport
    record and a model forbids what it did not declare. A transport declaring a required
    parameter of the same name would therefore have two boxes rendered under one name,
    have its own value lifted out of the mapping and fed to ``int()``, and be refused as a
    count — or, worse, have a numeric value of its own silently accepted as a pool size.

    The registry is the one place `control` learns field names from, so this is the place
    to say that one of them is spoken for. It is a guard on a transport package that does
    not exist yet, which is exactly when it is cheap to meet.
    """
    for name in sorted(discover()):
        declared = profile(name).params_model.model_fields
        assert addresses.POOL_BOX not in declared, (
            f"{name} declares a parameter called {addresses.POOL_BOX!r}, which is the "
            "name the pool box already uses on the enable and replace forms"
        )


# --- M17.2: the panel says it before the operator commits ---------------------

def _text_of(response) -> str:
    """One rendered fragment as the operator reads it: no markup, no Jinja comments.

    The same stripping ``field_errors`` does above, over the whole document rather than
    over one box — these assertions are about a sentence the console composed, and a
    sentence that is right but split across three tags is still right.
    """
    without_comments = re.sub(r"\{#.*?#\}", " ", response.text, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", without_comments)).strip()


# Every panel URL that renders markup for a fleet with one node, one transport and some
# users. The same list ``tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py``
# keeps for its own sweep, minus what needs a hop — the point here is not that it is
# exhaustive of the console but that it is exhaustive of the surfaces an ADDRESS could
# reach: the screens that list transports and users, and every dialog opened from one.
#
# SPLIT FROM THE PER-FRIEND ONES BELOW, because those have to be walked for EVERY friend
# rather than for one. The sweep excludes the pool's first address (it is the row's own
# typed parameter — see the test), and that address belongs to the first friend created;
# walking only that friend's dialogs would leave the two surfaces most likely to grow a
# per-person address checked against the one set of bytes they could print freely.
def panel_surfaces(node_id: str, row_id: str) -> list[str]:
    return [
        "/panel/",
        "/panel/overview/body",
        "/panel/friends",
        "/panel/friends/table",
        "/panel/friends/new",
        "/panel/nodes",
        "/panel/nodes/table",
        "/panel/hops",
        "/panel/hops/table",
        "/panel/hops/new",
        "/panel/transports",
        "/panel/keys",
        "/panel/keys/table",
        "/panel/audit",
        "/panel/settings",
        f"/panel/nodes/{node_id}/transports",
        f"/panel/nodes/{node_id}/state",
        f"/panel/nodes/{node_id}/resolver",
        f"/panel/keys/{row_id}/rotate",
        f"/panel/keys/{row_id}/params",
        f"/panel/transports/{row_id}/withdraw",
        f"/panel/transports/{row_id}/remove",
    ]


def friend_surfaces(friend_id: str) -> list[str]:
    """The surfaces opened for ONE person, walked once per person."""
    return [
        f"/panel/friends/{friend_id}/subscription",
        f"/panel/friends/{friend_id}/revoke",
    ]


async def test_no_user_address_reaches_any_panel_surface(
    client, session, pool_transport: str
) -> None:
    """THE LINE THAT GOVERNS THE WHOLE SCREEN. Counts, yes; an address, never.

    An address against a person is exactly the record the charter says is absent — there
    is to be nothing to seize or subpoena — and a console that prints one has created it
    on every screenshot the operator takes. So this walks every surface that could hold
    one and asserts the allocation is nowhere in the bytes.

    EVERY FRIEND'S OWN DIALOGS ARE WALKED, not only the first one's. ``settle`` hands
    ``pool[0]`` to the earliest credential, and ``pool[0]`` is the one address excluded
    below — so a sweep that opened the subscription and revoke dialogs for that friend
    alone would be asking the two surfaces most likely to grow a per-person address about
    the one value they are allowed to print.

    THE FIRST ADDRESS IN THE POOL IS EXCLUDED, and that exclusion is the honest part of
    this test rather than a hole in it. ``pool[0]`` is byte-identical to the row's own
    ``peer_tunnel_address`` parameter (``edge.addressing.pool``, which is what lets a row
    enabled before M17 keep rendering the same bytes), and that parameter is operator
    configuration: it is on the replace-parameters dialog as the placeholder for the box
    it is typed in, exactly like the port. What may never appear is an address that
    exists ONLY as per-credential state — the second person's and the third's — because
    that is the one that says something about a person.

    WHAT THAT EXCLUSION LEAVES, WRITTEN DOWN HERE RATHER THAN REDISCOVERED. ``settle``
    adopts ``pool[0]`` to the earliest credential by ``(created_at, id)``, and the Users
    screen orders by the same key — so an operator holding two screenshots, the replace-
    parameters dialog showing that parameter and the Users table showing who is first,
    can infer that the first person holds it. Nothing is stored that says so: the column
    is encrypted, no log names it, and no screen puts the two together. It is unavoidable
    while a row enabled before M17 must keep rendering the same bytes, and it is one
    address — but "no user's address appears anywhere" is that much short of literal, and
    a later reader should meet the qualification where the exclusion is made.

    The allocation is read back through the RENDER, like everything else in this file:
    what the node is authorised to route is the ground truth, and printing who holds what
    to build an assertion would be the record this test exists to keep out of existence.
    """
    node_id = await a_node(client, name="no-addresses", address="192.0.2.80")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    friends_made = []
    for nickname in ("ann", "bob", "cat"):
        created = await add_user(client, nickname)
        assert created.status_code == 201, created.text
        friends_made.append(created.json()["id"])

    held = [
        host_of(route)
        for route in routes_in(await as_the_node_sees_it(session, node_id, pool_transport))
    ]
    assert len(set(held)) == 3, held
    # Everything except the row's own parameter, which the pool's first element equals.
    per_credential = sorted(set(held) - {host_of("10.90.0.2/24")})
    assert len(per_credential) == 2, per_credential

    walked = panel_surfaces(node_id, enabled.json()["id"])
    for friend_id in friends_made:
        walked += friend_surfaces(friend_id)
    for url in walked:
        rendered = await client.get(url, headers=HTMX)
        assert rendered.status_code == 200, f"{url} -> {rendered.status_code}"
        for address in per_credential:
            assert address not in rendered.text, (
                f"{url} put a user's own address on the screen: {address}"
            )


async def test_the_keys_screen_says_how_many_hold_an_address_out_of_how_many(
    client, session, pool_transport: str
) -> None:
    """``<holders> of <pool>`` — the one thing about an allocation a screen may say.

    Two counts and no address, and it is on the screen an operator already reads before
    every rotation, so "is this pool nearly full" stops being a question only the refusal
    can answer.

    A transport that hands out no address has no pool and gets the bare count instead: a
    row reading "2 of None" would invent a limit that does not exist on it.
    """
    node_id = await a_node(client, name="pool-counts", address="192.0.2.81")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    screen = await client.get("/panel/keys/table", headers=HTMX)

    assert screen.status_code == 200
    assert f"2 of {ROOMY}" in screen.text, screen.text
    row = await console.key_row(session, enabled.json()["id"])
    assert row.holders_of_pool == f"2 of {ROOMY}"


async def test_the_enable_dialog_says_how_many_users_will_each_take_an_address(
    client, session, pool_transport: str
) -> None:
    """The count the box is about to be measured against, where the number is typed.

    The refusal for a pool below the fleet has existed since M17.1b and is right; what it
    could not be is the first time the operator hears the number. The floor is already in
    the placeholder ("N or more"); this is the sentence that says WHY it is that number.
    """
    node_id = await a_node(client, name="enable-count", address="192.0.2.82")
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201

    dialog = await client.get(f"/panel/nodes/{node_id}/transports", headers=HTMX)

    assert dialog.status_code == 200
    assert console.pool_takers(2) in dialog.text, dialog.text
    assert "2 active users each take an address" in dialog.text
    # And the placeholder still offers the same floor, from the same count.
    assert 'placeholder="2 or more"' in dialog.text


async def test_a_transport_whose_pool_is_short_is_not_offered_at_all(
    client, session, pool_transport: str
) -> None:
    """Offering a withdrawn row grants everybody on it, so a short pool withholds it.

    The withholding is deliberately wider than the service's refusal
    (``docs/decisions.md``, 2026-09-13), and this node shows why the sentence had to stop
    claiming one: the node is still a draft, so ``grant_everywhere`` reaches nothing and
    the press would COMMIT, granting nobody. What would then be refused is putting the
    node into service. The button is not drawn either way, because a pool below the fleet
    is a row nobody can be served on — with the pool named and the screen that resizes it
    named too, there being no resize action in this console.
    """
    node_id = await a_node(client, name="short-offer", address="192.0.2.83")
    assert (await add_user(client, "ann")).status_code == 201
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=1)
    assert enabled.status_code == 201, enabled.text
    row_id = enabled.json()["id"]
    withdrawn = await client.post(
        f"/api/transports/{row_id}/state", json={"enabled": False}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    # The fleet outgrows the pool, which is the only way a short row can exist: every
    # path that SETS a size refuses one below the fleet of that moment.
    assert (await add_user(client, "bob")).status_code == 201

    dialog = await client.get(f"/panel/nodes/{node_id}/transports", headers=HTMX)

    assert dialog.status_code == 200
    assert f"/panel/transports/{row_id}/offer" not in dialog.text, "the button is drawn"
    said = _text_of(dialog)
    assert f"{pool_transport} on short-offer is sized for 1 and would need 2" in said, said
    assert "replace params" in said, said
    # In the page's words, like every other sentence a service composes (decision 9).
    assert "friend" not in said.lower(), said


async def test_a_node_whose_pool_is_short_is_not_offered_the_serving_state(
    client, session, pool_transport: str
) -> None:
    """The same event from the other side, on the dialog that moves a node into service.

    ``test_a_node_that_cannot_be_granted_says_so_in_the_dialog_it_was_moved_from`` pins
    that the refusal is renderable; this pins that the operator never reaches it, because
    the option is not on the select. The state machine still allows the move — the list
    still says where this node may go — so what is withheld is the control and not the
    knowledge.
    """
    node_id = await a_node(client, name="short-state", address="192.0.2.84")
    assert (await add_user(client, "ann")).status_code == 201
    assert (
        await enable_pool(client, node_id, pool_transport, pool_size=1)
    ).status_code == 201
    assert (await add_user(client, "bob")).status_code == 201

    dialog = await client.get(f"/panel/nodes/{node_id}/state", headers=HTMX)

    assert dialog.status_code == 200
    assert '<option value="active"' not in dialog.text, "the state is on offer"
    said = _text_of(dialog)
    assert f"{pool_transport} on short-state is sized for 1 and would need 2" in said, said
    # Every other state this node may move to is still offered.
    assert '<option value="retired"' in dialog.text, dialog.text


async def test_a_transport_whose_pool_covers_the_fleet_is_offered(
    client, session, pool_transport: str
) -> None:
    """The other half of the pair, and the reason the negative above can fail at all.

    An implementation that withheld the offer button from every withdrawn row would pass
    that test and take away the console's only route to offering a transport — on the
    milestone's own main path, and on the shape the runbook mandates. Same fixture, same
    withdrawal, one number different.
    """
    node_id = await a_node(client, name="roomy-offer", address="192.0.2.87")
    assert (await add_user(client, "ann")).status_code == 201
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    assert enabled.status_code == 201, enabled.text
    row_id = enabled.json()["id"]
    withdrawn = await client.post(
        f"/api/transports/{row_id}/state", json={"enabled": False}
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert (await add_user(client, "bob")).status_code == 201

    dialog = await client.get(f"/panel/nodes/{node_id}/transports", headers=HTMX)

    assert dialog.status_code == 200
    assert f"/panel/transports/{row_id}/offer" in dialog.text, "the button is not drawn"
    said = _text_of(dialog)
    assert "not offered —" not in said, said
    assert "replace params" not in said, said


async def test_the_offer_a_stale_page_still_draws_is_refused_before_anything_commits(
    client, session, pool_transport: str
) -> None:
    """The withheld button is the courtesy; this is the rule — M17.2's acceptance.

    Reached with buttons only, exactly as the walk reached it. Withdraw a row whose pool
    still covers the fleet, open the transports dialog — the offer button is drawn, which
    is CORRECT at that moment — then add a user somewhere else and press the button the
    open page is still showing. Whether a control is drawn is decided when the page is
    rendered, and a page can go stale.

    THE NODE IS NOT SERVING, which is where the gap was. ``grant_everywhere`` grants on
    serving rows only, so the fan-out inside the offer allocated nothing, refused nothing,
    and the row came back into every user's link at a size that cannot hold the fleet —
    the one state M17's done-when says may not be committed.

    Both surfaces, because the done-when is about the control plane and not about the
    console: the panel gets the sentence in a banner with nothing changed behind it, and
    a script pressing the API gets the refusal envelope.
    """
    node_id = await a_node(client, name="stale-offer", address="192.0.2.89")
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=2)
    assert enabled.status_code == 201, enabled.text
    row_id = enabled.json()["id"]
    assert (
        await client.post(f"/api/transports/{row_id}/state", json={"enabled": False})
    ).status_code == 200

    # The page the operator is looking at. The button is here, and that is not the defect.
    open_page = await client.get(f"/panel/nodes/{node_id}/transports", headers=HTMX)
    assert f"/panel/transports/{row_id}/offer" in open_page.text, "nothing went stale"

    # …and now it is stale. A withdrawn row is not counted toward pool pressure, so this
    # is allowed and the dialog is never told.
    assert (await add_user(client, "cyd")).status_code == 201

    before = await audit_rows(session)
    pressed = await client.post(f"/panel/transports/{row_id}/offer", headers=HTMX)

    assert pressed.status_code == 200, pressed.text
    said = _text_of(pressed)
    assert f"{pool_transport} on stale-offer is sized for 2 and would need 3" in said, said
    assert "Nothing has been changed" in said, said
    # In the page's words, like every other sentence a service composes (decision 9).
    assert "friend" not in said.lower(), said

    session.expire_all()
    row = await session.get(NodeTransport, row_id)
    assert row.enabled is False, "a refused offer put the transport back in every link"
    assert (
        await session.execute(select(Credential).where(Credential.node_transport_id == row_id))
    ).scalars().unique().all() == [], "a refused offer minted material"
    assert await audit_rows(session) == before, "a refused offer reached the audit trail"

    # The same refusal to a caller that never saw a button.
    refused = await client.post(f"/api/transports/{row_id}/state", json={"enabled": True})
    assert refused.status_code == 409, refused.text
    assert "stale-offer" in refused.text and pool_transport in refused.text, refused.text


async def test_a_node_whose_pool_covers_the_fleet_is_offered_the_serving_state(
    client, session, pool_transport: str
) -> None:
    """The same pairing on the state dialog: withheld for a reason, not withheld always.

    Without this, dropping the ``active`` option unconditionally passes the gate — and a
    node carrying a WireGuard-family row could never be put into service from this
    console again.
    """
    node_id = await a_node(client, name="roomy-state", address="192.0.2.88")
    assert (await add_user(client, "ann")).status_code == 201
    assert (
        await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    ).status_code == 201
    assert (await add_user(client, "bob")).status_code == 201

    dialog = await client.get(f"/panel/nodes/{node_id}/state", headers=HTMX)

    assert dialog.status_code == 200
    assert '<option value="active"' in dialog.text, "the state is withheld anyway"
    said = _text_of(dialog)
    assert "not offered —" not in said, said


async def test_two_pools_of_one_transport_on_one_node_are_named_apart(
    client, session, pool_transport: str
) -> None:
    """M15 lets a node run one transport twice, and this sentence is read without the row.

    The state dialog and the add-user dialog both list pools from across the fleet, with
    no line beside them saying which row is which. Named by the transport alone, two
    instances on one node produce two byte-identical sentences: the operator resizes one,
    reopens, sees the same line, and cannot tell whether anything changed. So the pool is
    named the way every screen that lists a node's rows names them — ``placed_as``.
    """
    node_id = await a_node(client, name="two-rows", address="192.0.2.89")
    assert (await add_user(client, "ann")).status_code == 201
    first = await enable_pool(client, node_id, pool_transport, pool_size=1)
    assert first.status_code == 201, first.text
    # Its own port AND its own tunnel range: two rows on one node may share neither.
    second = await enable_pool(
        client,
        node_id,
        pool_transport,
        pool_size=1,
        tunnel="10.91.0.1/24",
        peer="10.91.0.2/24",
        port=51821,
    )
    assert second.status_code == 201, second.text
    assert (await add_user(client, "bob")).status_code == 201

    dialog = await client.get(f"/panel/nodes/{node_id}/state", headers=HTMX)

    assert dialog.status_code == 200
    said = _text_of(dialog)
    placed = {
        console.placed_as(pool_transport, row.json()["config_name"])
        for row in (first, second)
    }
    assert len(placed) == 2, placed
    for name in placed:
        assert f"{name} on two-rows is sized for 1 and would need 2" in said, said


async def test_the_add_user_dialog_names_every_full_pool_and_offers_no_submit(
    client, session, pool_transport: str
) -> None:
    """A form whose every submission is refused is worse than a sentence saying so.

    Adding a user gives them an address on every serving transport that hands one out, so
    a pool with no room refuses this form always rather than sometimes. The dialog asks
    the same question the service asks — ``addresses.shortfalls(extra=1)`` — so it cannot
    withhold a button the service would have accepted.

    And the refusal still holds behind it: the button being absent is a courtesy, not the
    enforcement.
    """
    node_id = await a_node(client, name="full-pool", address="192.0.2.85")
    assert (await add_user(client, "ann")).status_code == 201
    # The ordinary branch first, while there is still room, so the two assertions below
    # about the refusal branch are a pair rather than a description nothing can lose.
    ordinary = await client.get("/panel/friends/new", headers=HTMX)
    assert 'name="nickname"' in ordinary.text, ordinary.text
    assert "add-user-no-room" not in ordinary.text, ordinary.text
    assert (
        await enable_pool(client, node_id, pool_transport, pool_size=1)
    ).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    dialog = await client.get("/panel/friends/new", headers=HTMX)

    assert dialog.status_code == 200
    assert "add user</button>" not in dialog.text, "a button whose every outcome is 409"
    assert 'name="nickname"' not in dialog.text, "a field nothing can submit"
    # And the answer is ANNOUNCED: focus lands on `close`, the only control in this
    # branch, so a dialog that did not describe itself would leave a screen-reader
    # operator to navigate backwards for the reason there is no form.
    assert 'aria-describedby="add-user-no-room"' in dialog.text, dialog.text
    assert 'id="add-user-no-room"' in dialog.text, dialog.text
    said = _text_of(dialog)
    assert f"{pool_transport} on full-pool is sized for 1 and would need 2" in said, said
    assert "friend" not in said.lower(), said

    # The service has not been relaxed: the refusal is still what enforces this.
    refused = await client.post("/panel/friends", data={"nickname": "bob"}, headers=HTMX)
    assert refused.status_code == 422, refused.text
    session.expire_all()
    assert (
        await session.execute(select(Friend).where(Friend.nickname == "bob"))
    ).scalars().first() is None


async def test_the_add_user_refusal_counts_its_list_and_wears_the_danger_hue(
    client, session, pool_transport: str
) -> None:
    """Two findings from one walk, on the same three lines — M17.2's acceptance.

    The sentence above the list said *"one of those pools is full:"* whatever followed
    it, and two serving rows with no room printed two. A count is the one thing this
    sentence can get wrong and the operator can check, directly beneath it.

    And the whole answer was drawn in ``.dialog-body`` — the muted grey the "they get one
    subscription URL" consequence line under the ordinary form wears — so the one thing
    the operator opened this dialog to be told read as ordinary copy. Same defect M8's
    acceptance found in the primary button's slate blue and M9 answered with the danger
    hue, wearing a third colour.
    """
    node_id = await a_node(client, name="counted", address="192.0.2.91")
    assert (await add_user(client, "ann")).status_code == 201
    assert (
        await enable_pool(client, node_id, pool_transport, pool_size=1)
    ).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    one = await client.get("/panel/friends/new", headers=HTMX)

    assert one.status_code == 200
    assert "one of those pools is full:" in _text_of(one), _text_of(one)
    # The hue, on the block that carries the whole answer.
    assert 'class="dialog-refusal" id="add-user-no-room"' in one.text, one.text
    assert 'class="dialog-body" id="add-user-no-room"' not in one.text, one.text

    # A second row with no room, on the same node: one sentence, two pools under it. Its
    # own port AND its own tunnel range, which two rows on one node may never share.
    assert (
        await enable_pool(
            client,
            node_id,
            pool_transport,
            pool_size=1,
            tunnel="10.91.0.1/24",
            peer="10.91.0.2/24",
            port=51821,
        )
    ).status_code == 201

    two = await client.get("/panel/friends/new", headers=HTMX)

    assert two.status_code == 200
    said = _text_of(two)
    assert "2 of those pools are full:" in said, said
    assert "one of those pools" not in said, said
    assert said.count("is sized for 1 and would need 2") == 2, said


async def test_the_transports_screen_reads_the_registry_about_addresses(
    client, pool_transport: str
) -> None:
    """One row per transport that DECLARES it, and no name compared anywhere.

    The screen is a projection of the image, so the assertion is arithmetic on the
    registry rather than a list of protocols: the sentence appears exactly as many times
    as there are transports declaring ``peer_address``. A package added later gets the
    row by declaring; one that stops declaring loses it, with nothing to edit.
    """
    screen = await client.get("/panel/transports", headers=HTMX)

    assert screen.status_code == 200
    assert screen.text.count(console.TRANSPORT_ADDRESS_PER_USER) == len(POOL_TRANSPORTS)
    assert PLAIN_TRANSPORTS, "this image ships no transport that hands out no address"
    # Read back through the projection as well, so the claim is about the row and not
    # only about how many times a string occurs in a document.
    rows = {row.name: row for row in console.transport_rows()}
    assert rows[pool_transport].address_note == console.TRANSPORT_ADDRESS_PER_USER
    for name in PLAIN_TRANSPORTS:
        assert rows[name].address_note is None, name


async def test_the_field_s_own_row_says_two_users_hold_one_address(
    client, session, pool_transport: str
) -> None:
    """The screen this milestone exists for: a pool of one with two people on it.

    This is the Amsterdam leaf after migration ``0006`` — a row enabled before pools,
    serving two users, handing out one address. Every refusal about it is already right
    and every one of them arrives at a different moment; what the operator had nowhere to
    read was the state itself. "2 of 1" is that state in three characters, on the screen
    they open before every rotation.
    """
    node_id = await a_node(client, name="as-in-the-field", address="192.0.2.86")
    enabled = await enable_pool(client, node_id, pool_transport, pool_size=ROOMY)
    row_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    for nickname in ("ann", "bob"):
        assert (await add_user(client, nickname)).status_code == 201
    await as_it_was_before_m17(session, row_id)

    assert (await console.key_row(session, row_id)).holders_of_pool == "2 of 1"
    screen = await client.get("/panel/keys/table", headers=HTMX)
    assert screen.status_code == 200
    assert "2 of 1" in screen.text, screen.text
