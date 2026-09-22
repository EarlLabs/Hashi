"""The push that puts a node into service carries the people it just granted — M23, r3.

WHAT: the order inside ``apply.apply_node`` between granting every active user a
      credential on a node that is becoming serving and rendering the bytes that go to
      the host, and what an apply does when the pool on such a node cannot hold the
      fleet.
WHY:  both are regressions from round 2's own fix, and both were measured on the real
      hosts on 2026-09-15.

      **The draft node.** One press of apply on a draft node took it into service, handed
      every user a credential at that instant and pushed a file with no peer entries in
      it — because ``render_for_node`` ran first. A user's archive then held a config for
      a node holding none of their key material: a link that is live immediately and
      cannot work. A second apply, which nothing asks for, repaired it. Whether the
      product worked came down to the order the operator pressed two buttons in.

      **The short pool.** Apply on a degraded node with a two-address pool and three
      users answered ``500 internal_error`` on the console and 409 on the API — and the
      host had already changed: config digest moved, peer count moved, ``docker compose
      up -d`` ran, which restarts a daemon on a real host. The record rolled back while
      the node did not, under a message saying "Nothing has been changed", and every
      repeat press pushed and restarted again. The state dialog correctly withholds
      ``active`` for that pool, so apply was the only door left open.
HOW:  the shared ``accepting_nodes`` harness (``conftest.py``) with one more double over
      it, so this file can see WHAT was placed on the host rather than only that the
      apply succeeded. So what is proven here is this control plane's own bookkeeping and
      the bytes it hands to a host — never that a daemon reloaded, and never that a
      tunnel carries.

Nothing here prints who holds which address. The allocation is read back out of the
render, which is what the node actually receives.
"""

import re

import pytest
from sqlalchemy import select

from control.app.models import (
    AuditAction,
    AuditEntry,
    Credential,
    NodeState,
    NodeTransport,
)
from control.app.services import apply, console, nodes
from control.app.services import transports as transports_service
from edge.addressing import host_of
from edge.bootstrap import node_stack
from edge.registry import discover

from .conftest import GENERATED_SSH_KEY, pinned

# RFC 5737 documentation addresses, as everywhere in this zone. Never dialled — the
# connection is replaced — but a record has to name something.
NODE_ADDRESS = "192.0.2.71"

# Every transport this image both OFFERS and gives each consumer an address of its own.
# The declaration, never a name: the finding is about a node whose pool can run out, and
# a transport added later is exercised here by arriving.
POOL_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if meta.peer_address is not None and name in transports_service.offerable_transports()
)

# The operator half of such a transport's parameters, filtered per transport against its
# own model so one literal serves every member.
POOL_PARAMS: dict[str, object] = {
    "port": 51820,
    "tunnel_address": "10.91.0.1/24",
    "peer_tunnel_address": "10.91.0.2/24",
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}

# AT MODULE LEVEL, because that is the only place it can fire: an empty parameter set
# makes pytest skip with its own generic reason and never run a fixture body, so a guard
# written inside one is a sentence nobody can read.
pytestmark = pytest.mark.skipif(
    not POOL_TRANSPORTS,
    reason="this image offers no transport that gives each user an address of their own",
)


@pytest.fixture(params=POOL_TRANSPORTS)
def pool_transport(request) -> str:
    return request.param


class OnTheHost:
    """What an apply actually did to a host, as this suite can see it.

    ``placed`` is every config handed to ``place_config`` — the bytes, not a digest, so a
    test can read who the file authorises. ``dialled`` counts connections opened, which is
    what makes "nothing was pushed" provable rather than inferred: a refusal that fires
    before the connection leaves both empty, and one that fires after leaves ``dialled``
    non-empty even when nothing was written.
    """

    def __init__(self) -> None:
        self.placed: list[tuple[str, str]] = []
        self.dialled = 0


@pytest.fixture
def on_the_host(accepting_nodes, monkeypatch) -> OnTheHost:
    """The accepting node, watched.

    Layered over ``accepting_nodes`` rather than replacing it, so the five calls that
    touch a host are still the shared harness's and this file adds no second simulation of
    a node. ``pinned`` still runs: it compares this double against the one already
    installed, which is itself pinned to the real function, so a renamed keyword anywhere
    in that chain is still a failure at fixture setup.
    """
    watched = OnTheHost()

    accepting_connection = apply.NodeConnection
    accepting_place = node_stack.place_config

    def connection_for(target):
        watched.dialled += 1
        return accepting_connection(target)

    async def place_config(
        connection, *, transport_name: str, config: str, path: str | None = None
    ) -> None:
        watched.placed.append((transport_name, config))
        await accepting_place(
            connection, transport_name=transport_name, config=config, path=path
        )

    monkeypatch.setattr(apply, "NodeConnection", connection_for)
    pinned(monkeypatch, node_stack, "place_config", place_config)
    return watched


def params_for(transport_name: str, **overrides) -> dict[str, object]:
    """The operator-supplied half, minus knobs this transport does not declare."""
    from edge.registry import profile  # noqa: PLC0415

    declared = set(profile(transport_name).params_model.model_fields)
    supplied = {**POOL_PARAMS, **overrides}
    return {key: value for key, value in supplied.items() if key in declared}


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


async def enable_pool(client, node_id: str, transport_name: str, *, pool_size: int):
    return await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": transport_name,
            "params": params_for(transport_name),
            "pool_size": pool_size,
        },
    )


async def add_user(client, nickname: str) -> str:
    created = await client.post("/api/users", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def routes_in(config: str) -> list[str]:
    """Every address this config authorises, as the wg-quick family writes them."""
    return re.findall(r"AllowedIPs\s*=\s*(\S+)", config)


async def held_addresses(session, node_id: str) -> set[str]:
    """Every address this node's rows have handed out, read off the credentials.

    Read here so a test can assert the pushed file authorises them, which is the whole
    question. Not printed against anybody: the set is compared, never attributed.

    Queried rather than read off ``row.credentials``, for the reason every service in this
    zone gives: the relationship is unloaded on a row this session created moments ago, so
    touching it is lazy IO — which on an async session is a MissingGreenlet, not a query.
    """
    held = await session.execute(
        select(Credential)
        .join(NodeTransport)
        .where(NodeTransport.node_id == node_id)
    )
    return {
        credential.tunnel_address
        for credential in held.scalars().unique()
        if credential.tunnel_address
    }


# --- B: the bytes carry the people ------------------------------------------------


async def test_the_first_apply_pushes_a_config_that_holds_the_users_it_granted(
    client, session, pool_transport: str, on_the_host: OnTheHost
) -> None:
    """The finding itself, on the surface the walk pressed.

    Red against the previous commit: the file placed on the host authorises nobody, while
    the user's own archive already carries a config for this node.
    """
    boris = await add_user(client, "boris")
    assert boris
    node_id = await a_reachable_node(client, name="tiny")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=4)).status_code == 201

    applied = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert applied.status_code == 200, applied.text
    assert len(on_the_host.placed) == 1, on_the_host.placed
    _, pushed = on_the_host.placed[0]
    session.expire_all()
    addresses_held = await held_addresses(session, node_id)
    assert addresses_held, "the user was granted nothing at all on a node now serving"
    assert set(routes_in(pushed)) == {
        f"{host_of(address)}/32" for address in addresses_held
    }, (
        "the configuration pushed to the host does not authorise the people this apply "
        f"granted — the user's link is live and cannot work: {pushed}"
    )


async def test_the_first_apply_needs_no_second_one(
    client, session, pool_transport: str, on_the_host: OnTheHost
) -> None:
    """"A second apply, which nothing asks for, fixes it" — stated as the assertion.

    The two pushes must be byte-identical. They were not: the first predated the grant in
    its own transaction, so the operator's only signal that the fleet was broken was a
    user reporting a tunnel that comes up and carries nothing.
    """
    await add_user(client, "boris")
    await add_user(client, "kolya")
    node_id = await a_reachable_node(client, name="twice")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=4)).status_code == 201

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    first, second = (config for _, config in on_the_host.placed)
    assert first == second, (
        "the second apply pushed different bytes from the first, so the first one left "
        "the host serving a configuration nobody asked it to serve"
    )


async def test_a_node_reads_in_sync_on_the_first_apply(
    client, session, pool_transport: str, on_the_host: OnTheHost
) -> None:
    """The operator's own reading of the same fault.

    ``drift_of`` compares what was applied against what would be pushed now, so a config
    that predates its own grant reads as drifted the instant it lands — which is what the
    walk saw as ``1 / 1 drifted`` on a node it had just applied.
    """
    await add_user(client, "boris")
    node_id = await a_reachable_node(client, name="sync")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=4)).status_code == 201

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) == console.IN_SYNC, (
        "a node reads as drifted immediately after being applied, which means the bytes "
        "it was given are not the bytes this control plane would give it now"
    )


async def test_going_into_service_is_recorded_the_way_a_state_change_is(
    client, session, pool_transport: str, on_the_host: OnTheHost
) -> None:
    """A node going into service is an audited event however it was reached — M23, r3.

    The walk watched a node go draft -> active with every user granted on it and nothing
    in the trail saying so, because ``apply_node`` writes the state itself instead of
    going through ``set_node_state``. The entry is written on the success path only, so a
    push that failed leaves no record claiming the node went into service — which is what
    ``test_a_failed_apply_records_no_state_change`` holds from the other side.
    """
    node_id = await a_reachable_node(client, name="recorded")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=4)).status_code == 201

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    entries = (
        await session.execute(
            select(AuditEntry).where(AuditEntry.action == AuditAction.NODE_STATE_CHANGED)
        )
    ).scalars().all()
    assert [entry.second_label for entry in entries] == [str(NodeState.ACTIVE)], (
        "an apply took a node into service and recorded no state change, so the one "
        "record of the fleet's history is missing the moment it started carrying people"
    )
    assert [entry.first_label for entry in entries] == ["recorded"]


async def test_a_re_apply_of_a_serving_node_records_nothing_and_grants_nobody(
    client, session, pool_transport: str, on_the_host: OnTheHost
) -> None:
    """The guard above the fan-out, from the other side.

    A node that is already serving is not going into service, so there is no event: no
    second credential for anybody, and no second entry in the trail. Both matter — the
    guard is what keeps an ordinary re-push from walking the whole fleet, and the
    idempotence under it is what makes it safe when it does.
    """
    await add_user(client, "boris")
    node_id = await a_reachable_node(client, name="again")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=4)).status_code == 201
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    session.expire_all()
    before = await held_addresses(session, node_id)

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200

    session.expire_all()
    assert await held_addresses(session, node_id) == before, (
        "a re-apply handed somebody a second address on a row they were already on"
    )
    changes = (
        await session.execute(
            select(AuditEntry).where(AuditEntry.action == AuditAction.NODE_STATE_CHANGED)
        )
    ).scalars().all()
    assert len(changes) == 1, (
        "a re-apply of a node that was already serving recorded it going into service "
        "again"
    )


async def test_a_failed_apply_records_no_state_change_and_grants_nobody(
    client, session, pool_transport: str
) -> None:
    """The fail-closed half, without which the fix would be worse than the finding.

    A node whose push failed is degraded and is in nobody's subscription, so material
    minted for it would be a credential for a host that was never configured — and, on a
    transport that hands out addresses, an allocation nobody can use. Since the grant now
    runs BEFORE the push, keeping that true is ``apply._record_failure``'s job: it deletes
    what this apply minted on its way in, explicitly, rather than rolling the session back
    — a rollback would take the learned SSH host key with it.

    No ``accepting_nodes`` here: the node has no SSH key, so ``target_for`` refuses before
    anything is dialled, which is the cheapest real failure this suite has.
    """
    await add_user(client, "boris")
    created = await client.post(
        "/api/nodes",
        json={"name": "keyless", "address": NODE_ADDRESS, "location_label": "Testland"},
    )
    node_id = created.json()["id"]
    assert (await enable_pool(client, node_id, pool_transport, pool_size=4)).status_code == 201

    failed = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert failed.status_code == 200, failed.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DEGRADED, node.state
    assert not await held_addresses(session, node_id), (
        "a node that could not be configured minted material for somebody anyway"
    )
    changes = (
        await session.execute(
            select(AuditEntry).where(AuditEntry.action == AuditAction.NODE_STATE_CHANGED)
        )
    ).scalars().all()
    assert [entry.second_label for entry in changes] == [str(NodeState.DEGRADED)], (
        "a failed apply recorded the node going into service"
    )


# --- A: the short pool is refused before anything is pushed -----------------------


@pytest.fixture
async def a_node_whose_pool_is_too_small(client, session, pool_transport: str) -> str:
    """A serving node with two addresses and three users, then taken out of service.

    The walk's own shape: the third user arrives after the node is degraded, so the pool
    is short of the fleet and the only control left that would put the node back into
    service is apply — the state dialog withholds ``active`` over exactly this.
    """
    node_id = await a_reachable_node(client, name="tiny")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=2)).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    await add_user(client, "ann")
    await add_user(client, "bob")
    await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="taken out for the test"
    )
    await add_user(client, "cara")
    return node_id


async def test_the_short_pool_is_refused_before_the_node_is_dialled(
    client, session, a_node_whose_pool_is_too_small: str, on_the_host: OnTheHost
) -> None:
    """The half of the finding that matters most: the refusal is one, not a rollback.

    Red against the previous commit — the host was reached, both files were replaced and
    the daemon was restarted before the fan-out refused, and every repeat press did it
    again.
    """
    node_id = a_node_whose_pool_is_too_small

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    assert on_the_host.dialled == 0, (
        "the node was dialled by an apply that was going to refuse, so a message saying "
        "nothing has been changed is false about the host"
    )
    assert on_the_host.placed == [], on_the_host.placed
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DEGRADED, node.state


async def test_the_console_is_answered_with_a_refusal_and_not_an_internal_error(
    client, session, a_node_whose_pool_is_too_small: str, on_the_host: OnTheHost
) -> None:
    """The other half: the panel drops a refusal the API states correctly.

    Red against the previous commit with ``500 {"code": "internal_error"}`` — the fan-out
    rolls the session back before it raises, which expires every object in the identity
    map, and the route then read the node's name off a husk. Every other refusal on this
    button is shaped; this one was not.
    """
    node_id = a_node_whose_pool_is_too_small

    refused = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert refused.status_code == 200, refused.text
    assert "internal error" not in refused.text.lower(), refused.text
    said = " ".join(refused.text.split())
    assert "refused" in said, (
        "the pool refusal is drawn as a failure, which on this button additionally means "
        "the node is now degraded — and nothing was attempted"
    )
    assert "Nothing was pushed and nothing on the node was changed" in said, said
    assert "tiny" in said, said


async def test_the_refusal_names_the_pool_and_where_its_size_is_changed(
    client, session, a_node_whose_pool_is_too_small: str, on_the_host: OnTheHost
) -> None:
    """The operator has to be able to act on it, and the two readers act differently.

    The service's own sentence names no screen — it is also the body of a 409 to a caller
    who is not looking at one — and the console's version names the one screen a pool's
    size is actually changed on, which is not the screen this banner is read on.
    """
    node_id = a_node_whose_pool_is_too_small

    api = await client.post(f"/api/nodes/{node_id}/apply")
    console_answer = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    message = api.json()["error"]["message"]
    assert "is sized for 2 and would need 3" in message, message
    assert "screen" not in message.lower(), (
        f"the refusal sends an API caller to a screen: {message}"
    )
    assert "panel" not in message.lower(), message
    assert "Keys &amp; configs, replace params" in console_answer.text, console_answer.text


async def test_a_refusal_that_rolled_the_session_back_still_reaches_the_operator(
    client, session, pool_transport: str, monkeypatch, on_the_host: OnTheHost
) -> None:
    """The 500 itself, provoked rather than inferred — M23, round 3.

    The pre-flight above is what the operator meets in practice, and it leaves the session
    whole. Underneath it the fan-out is still the backstop — for a pool that is big enough
    on paper and full in fact, and for the address race the unique constraint settles —
    and every one of those refusals ROLLS THE SESSION BACK before raising. A rollback
    expires every object in the identity map whatever ``expire_on_commit`` says, so the
    route reading the node's name off the object it fetched before the call emits a SELECT
    from a plain frame on an async session: ``MissingGreenlet``, which is not a
    ``DomainError``, so it escapes as ``500 internal_error`` and the console swaps nothing.

    That is what the walk measured, and nothing about it is specific to a pool — so it is
    pinned here against the shape rather than against the one refusal that used to reach
    it. ``_refuse_state`` carries the same lesson one screen over.
    """
    from control.app.errors import Conflict  # noqa: PLC0415
    from control.app.services import users  # noqa: PLC0415

    await add_user(client, "boris")
    node_id = await a_reachable_node(client, name="husk")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=4)).status_code == 201

    async def grant_on(session, user, rows):
        await session.rollback()
        raise Conflict("this pool has no room")

    pinned(monkeypatch, users, "grant_on", grant_on)

    refused = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert refused.status_code == 200, refused.text
    assert "internal error" not in refused.text.lower(), refused.text
    assert "this pool has no room" in refused.text, refused.text
    assert on_the_host.placed == [], (
        "a refusal from the fan-out arrived after the config had already been pushed"
    )


async def test_a_pool_with_room_still_takes_the_node_back_into_service(
    client, session, pool_transport: str, on_the_host: OnTheHost
) -> None:
    """Non-vacuity: the refusal is about the size, not about applying a degraded node.

    ``degraded -> active`` through apply is the retry every failed push depends on, and a
    check that refused it whatever the pool held would be worse than the fault it fixes.
    """
    node_id = await a_reachable_node(client, name="roomy")
    assert (await enable_pool(client, node_id, pool_transport, pool_size=8)).status_code == 201
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    await add_user(client, "ann")
    await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="taken out for the test"
    )
    await add_user(client, "bob")

    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert applied.status_code == 200, applied.text
    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.ACTIVE, node.state_detail
    assert len(await held_addresses(session, node_id)) == 2, (
        "the node went back into service without giving the user added while it was out "
        "an address on it"
    )
