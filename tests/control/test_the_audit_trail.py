"""The audit trail: what it records, and everything it must never be able to.

WHAT: the shape of ``audit_entries``, what each recording point writes, that the
      delivery endpoint writes nothing at all, and that the retention window is
      bounded and actually swept.
WHY:  decision 8 (``docs/decisions.md``, 2026-09-11) grants this table and fixes its
      shape, and the shape IS the guarantee. Two of these tests are the step's real
      product rather than coverage:

      * **the column whitelist** — a ``details`` or ``reason`` column is how a trail
        acquires a token eighteen months from now without anyone deciding to add one,
        and this is the assertion that fails in the change that adds it, which is the
        only moment anybody is thinking about whether it should exist;
      * **the ``/sub/{token}`` scenario** — a friend fetching their subscription must
        leave NO row, not merely no row naming a token. That is the rule whose breach
        turns this table into the record of who connected to what that the charter
        says is absent. Its e2e twin runs the same claim against the real stack.
HOW:  operations are performed through the services that record them, or through the
      API where the claim is about a route not writing. No node is contacted except
      through the fake host at the bottom of this file.

Boundary: nothing here proves anything about a running daemon or a real network. The
claim is about what is in the database afterwards.
"""

import asyncio
import datetime
import pathlib

import pydantic
import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from control.app.errors import DomainError, NotFound
from control.app.models import (
    AuditAction,
    AuditEntry,
    Friend,
    Node,
    NodeState,
    NodeTransport,
)
from control.app.models.audit import LABEL_MAX_LENGTH
from control.app.services import apply, audit, nodes, relay, revocation, rotation
from control.app.settings import (
    AUDIT_RETENTION_DEFAULT_DAYS,
    AUDIT_RETENTION_MAX_DAYS,
    AUDIT_RETENTION_MIN_DAYS,
    Settings,
)
from edge.bootstrap import node_stack

from .conftest import GENERATED_SSH_KEY

APP = pathlib.Path(__file__).resolve().parents[2] / "control" / "app"

NODE_ADDRESS = "192.0.2.10"
TRANSPORT = "vless-reality"
HOP_TRANSPORT = "amneziawg"


@pytest.fixture
def hop_params() -> dict[str, object]:
    """The operator-supplied half of one hop end — the same shape ``test_relay`` uses.

    Copied rather than shared because a fixture in ``conftest`` is a fixture every file
    in the zone inherits, and these values belong to two scenarios rather than to the
    suite. Key material is minted by the control plane and never typed.
    """
    return {
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


# --- the shape, which is the guarantee ---------------------------------------

def test_the_trail_holds_exactly_these_columns_and_no_others() -> None:
    """The whitelist. A sixth column fails here, in the change that adds it.

    Written as an exact set rather than as "must not contain ``details``", because the
    failure mode is not one known column name — it is ANY place a value can be put.
    ``payload``, ``metadata``, ``context`` and ``notes`` are the same column with four
    spellings, and a test enumerating the bad ones would have to guess the fifth.

    ``id`` is in the set because a row needs a primary key, not because anything reads
    it. Everything else is the decision's own list: a time, an action, and two labels.
    """
    assert set(AuditEntry.__table__.columns.keys()) == {
        "id",
        "at",
        "action",
        "first_label",
        "second_label",
    }, (
        "the audit trail's columns have changed. It may hold a time, an action from a "
        "closed vocabulary and two labels read off inventory rows — no free text, no "
        "JSON, no reason, no actor, no address (docs/decisions.md, 2026-09-11)"
    )


def test_the_trail_has_no_updated_at_because_an_entry_is_never_edited() -> None:
    """No ``TimestampMixin``: an ``updated_at`` invites the idea a row can be changed."""
    assert "updated_at" not in AuditEntry.__table__.columns
    assert "created_at" not in AuditEntry.__table__.columns


def test_both_labels_are_exactly_as_wide_as_the_values_they_may_hold() -> None:
    """64 characters — a node name, a nickname, a transport name, a state.

    The width is a guard rather than a size estimate: ``Node.state_detail`` is 500
    characters of text that can come from a remote host, it sits one attribute away
    from ``state`` (which this table is allowed to record), and a label composed from
    it does not fit here.

    ALL FOUR permitted sources are checked, not the two obvious ones. The guard cuts
    both ways: a source column widened past this one would make ``record`` raise on a
    perfectly legitimate change — a 500 out of ``enable_transport`` for a long
    transport name — and nothing else would fail first. Widening a source means
    widening this column in the same change, or narrowing the source back.
    """
    for column in ("first_label", "second_label"):
        assert AuditEntry.__table__.columns[column].type.length == LABEL_MAX_LENGTH
    for table, column in (
        (Node, "name"),
        (Friend, "nickname"),
        (NodeTransport, "transport_name"),
    ):
        assert table.__table__.columns[column].type.length <= LABEL_MAX_LENGTH, (
            f"{table.__tablename__}.{column} no longer fits in an audit label, so "
            "recording a change about it would raise instead of being recorded"
        )
    assert max(len(state.value) for state in NodeState) <= LABEL_MAX_LENGTH
    assert Node.__table__.columns["state_detail"].type.length > LABEL_MAX_LENGTH


async def test_an_action_nobody_declared_fails_at_the_write(session) -> None:
    """The vocabulary is closed by the DATABASE TYPE, not by authors remembering.

    Over a bare ``String`` this column would accept any text at all and the closed
    vocabulary would be a claim about code review. ``EnumText`` converts on the way in,
    so an undeclared value raises before the statement is sent — which is what makes
    "there is nowhere in this table to put a sentence" true rather than intended.
    """
    session.add(AuditEntry(action="a-value-nobody-declared"))

    with pytest.raises(StatementError) as refused:
        await session.flush()
    assert isinstance(refused.value.__cause__, ValueError)
    assert "not a valid AuditAction" in str(refused.value.__cause__)

    await session.rollback()
    assert (await session.execute(select(AuditEntry))).scalars().all() == []


async def test_a_label_too_long_to_be_an_inventory_value_is_refused(session) -> None:
    """The mechanical half of "a label is copied, never composed".

    ``f"{node.name}: {node.state_detail}"`` satisfies every other rule about this table.
    It does not fit in the column, and the helper says so rather than letting the
    database truncate it into a half-sentence nobody notices.
    """
    with pytest.raises(ValueError, match="read off an inventory row"):
        audit.record(
            session, AuditAction.NODE_ADDED, first_label="x" * (LABEL_MAX_LENGTH + 1)
        )


def test_no_route_writes_the_trail() -> None:
    """Entries come from ``services/``, because both surfaces mutate through them.

    A route that recorded would be a rule that holds for the surface somebody
    remembered — and the delivery endpoint is a route.

    ``AuditEntry`` is searched for as well as the service, and that is not belt and
    braces: the helper is one way to write this table and ``session.add(AuditEntry(…))``
    off ``control.app.models`` is the other, so a sweep for the import alone would be
    an instrument narrower than the rule it states.
    """
    offenders = [
        path.relative_to(APP)
        for directory in ("api", "panel")
        for path in sorted((APP / directory).rglob("*.py"))
        if any(
            marker in path.read_text()
            for marker in ("services import audit", "services.audit", "AuditEntry")
        )
    ]
    assert offenders == [], (
        "a route writes the audit trail — it belongs in the service that makes the "
        f"change, in the same transaction as the change: {offenders}"
    )


# --- what each recording point writes ----------------------------------------

async def trail(session) -> list[AuditEntry]:
    """Every entry, oldest first.

    No ``expire_all()`` here, deliberately: several operations below are performed
    through ``client``, which uses a different session, and expiring this one would
    detach every node and friend the test is still holding — an attribute read after
    that is lazy I/O, which on an async session raises rather than loading. It is not
    needed either, because an entry is append-only: a fresh SELECT sees every row
    another session has committed, and no row it already holds can have changed.
    """
    result = await session.execute(select(AuditEntry).order_by(AuditEntry.at, AuditEntry.id))
    return list(result.scalars().unique())


async def entries_for(session, action: AuditAction) -> list[AuditEntry]:
    return [entry for entry in await trail(session) if entry.action == action]


async def a_node(client, name: str = "leaf-nl", *, with_key: bool = False) -> str:
    body = {
        "name": name,
        "address": NODE_ADDRESS,
        "location_label": "Testland",
    }
    if with_key:
        body |= {"ssh_host": NODE_ADDRESS, "ssh_port": 22,
                 "ssh_private_key": GENERATED_SSH_KEY}
    response = await client.post("/api/nodes", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_adding_a_user_records_the_nickname_and_nothing_else(
    client, session
) -> None:
    """The label is the nickname the operator typed, copied whole.

    What is NOT here is the point: creating a friend also mints a subscription token
    and a URL, and neither may reach a durable record — they are the one artefact of
    this operation that is a live credential.
    """
    response = await client.post("/api/friends", json={"nickname": "kolya"})
    assert response.status_code == 201, response.text
    url = (
        await client.get(f"/api/friends/{response.json()['id']}/subscription")
    ).json()["url"]
    token = url.rsplit("/", 1)[-1]

    entries = await trail(session)
    assert [entry.action for entry in entries] == [AuditAction.FRIEND_ADDED]
    assert entries[0].first_label == "kolya"
    assert entries[0].second_label is None
    for entry in entries:
        for label in (entry.first_label, entry.second_label):
            assert label is None or token not in label
            assert label is None or "http" not in label


async def test_a_refused_nickname_leaves_no_entry(client, session) -> None:
    """Only changes that COMMITTED. A refusal is not a change."""
    assert (await client.post("/api/friends", json={"nickname": "  "})).status_code == 400
    assert await trail(session) == []


async def test_revoking_records_the_nickname_once(client, session) -> None:
    """Recorded in the same transaction as the revocation, and not again on a retry."""
    friend_id = (
        await client.post("/api/friends", json={"nickname": "kolya"})
    ).json()["id"]

    await revocation.revoke_friend(session, friend_id=friend_id)
    await revocation.revoke_friend(session, friend_id=friend_id)

    revoked = await entries_for(session, AuditAction.FRIEND_REVOKED)
    assert len(revoked) == 1, "a second revocation changed nothing and recorded nothing"
    assert revoked[0].first_label == "kolya"
    assert revoked[0].second_label is None


async def test_a_revocation_that_never_happened_records_nothing(client, session) -> None:
    """The entry is pending in the same transaction, so a refusal takes it with it."""
    with pytest.raises(NotFound):
        await revocation.revoke_friend(session, friend_id="no-such-friend")
    await session.rollback()
    assert await entries_for(session, AuditAction.FRIEND_REVOKED) == []


async def test_a_node_a_transport_and_a_state_are_recorded_by_their_own_names(
    client, session, reality_params
) -> None:
    """Four recording points, four labels, every one read off a row.

    The node's ADDRESS is deliberately absent from all of them: an address against a
    time is the record the charter says does not exist here.
    """
    node_id = await a_node(client)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    node_transport_id = enabled.json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=False
    )
    await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=True
    )

    node = await nodes.get_node(session, node_id)
    written = [
        (entry.action, entry.first_label, entry.second_label) for entry in await trail(session)
    ]
    assert written == [
        (AuditAction.NODE_ADDED, node.name, None),
        (AuditAction.TRANSPORT_ENABLED, node.name, TRANSPORT),
        (AuditAction.NODE_STATE_CHANGED, node.name, NodeState.ACTIVE.value),
        (AuditAction.TRANSPORT_WITHDRAWN, node.name, TRANSPORT),
        (AuditAction.TRANSPORT_OFFERED, node.name, TRANSPORT),
    ]
    for _, first, second in written:
        assert NODE_ADDRESS not in (first or "")
        assert NODE_ADDRESS not in (second or "")


async def test_setting_a_state_or_a_switch_to_the_one_it_already_has_records_nothing(
    client, session, reality_params
) -> None:
    """A retried click is not an event, on either of the two idempotent operations."""
    node_id = await a_node(client)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )
    node_transport_id = enabled.json()["id"]

    await nodes.set_node_state(session, node_id=node_id, state=NodeState.DRAFT)
    await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=True
    )

    assert await entries_for(session, AuditAction.NODE_STATE_CHANGED) == []
    assert await entries_for(session, AuditAction.TRANSPORT_OFFERED) == []


async def test_setting_a_resolver_records_the_nodes_name_and_never_the_address(
    client, session
) -> None:
    """M16's recording point. The resolver is an address, and an address against a time
    is the record this trail was shaped to refuse — so the entry is the node's name and
    nothing else. Setting the value the node already holds is a retried click, not an
    event, and records nothing."""
    resolver = "192.0.2.53"
    node_id = await a_node(client)

    await nodes.set_resolver(session, node_id=node_id, resolver=resolver)
    await nodes.set_resolver(session, node_id=node_id, resolver=resolver)

    node = await nodes.get_node(session, node_id)
    written = [
        (entry.first_label, entry.second_label)
        for entry in await entries_for(session, AuditAction.NODE_RESOLVER_SET)
    ]
    assert written == [(node.name, None)]


async def test_a_failed_apply_records_the_state_change_and_never_its_reason(
    client, session, reality_params, refusing_ssh
) -> None:
    """THE line this table's shape was written against.

    An apply that cannot reach the node marks it degraded with a reason in
    ``state_detail`` — 500 characters that came from the attempt, and on a real host
    from the host. The trail records the STATE and not the reason, and the two are one
    line apart in ``set_node_state``. There is also no ``node-applied`` entry: the push
    did not happen, so nothing about it committed.
    """
    node_id = (
        await client.post(
            "/api/nodes",
            json={
                "name": "leaf-nl",
                "address": NODE_ADDRESS,
                "location_label": "Testland",
                "ssh_host": refusing_ssh.host,
                "ssh_port": refusing_ssh.port,
                "ssh_private_key": GENERATED_SSH_KEY,
            },
        )
    ).json()["id"]
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )

    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code >= 400

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DEGRADED
    assert node.state_detail, "the premise: the node carries a reason nobody may copy"

    assert await entries_for(session, AuditAction.NODE_APPLIED) == []
    degraded = await entries_for(session, AuditAction.NODE_STATE_CHANGED)
    assert [(entry.first_label, entry.second_label) for entry in degraded] == [
        (node.name, NodeState.DEGRADED.value)
    ]
    # And no part of that reason travelled with it. The first words of a failure are
    # the ones a composed label would carry — and on a real host they are the host's.
    opening = node.state_detail[:24]
    for entry in await trail(session):
        for label in (entry.first_label, entry.second_label):
            assert label is None or opening not in label


async def test_a_successful_apply_is_recorded_by_the_nodes_name(
    client, session, reality_params, monkeypatch
) -> None:
    """Success only, and the whole entry is the node's name.

    Not which transports were pushed, not their digests, not how long it took: the
    node-transport rows carry all of that already, and a record of what was on a node
    at a time is a different thing from a record that it was configured.
    """
    host = _FakeHost()
    monkeypatch.setattr(apply, "NodeConnection", lambda target: host)
    node_id = await a_node(client, with_key=True)
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )

    await apply.apply_node(session, node_id=node_id)

    node = await nodes.get_node(session, node_id)
    applied = await entries_for(session, AuditAction.NODE_APPLIED)
    assert [(entry.first_label, entry.second_label) for entry in applied] == [
        (node.name, None)
    ]


async def test_a_hop_records_both_node_names_and_dissolving_it_records_them_again(
    client, session, hop_params
) -> None:
    """Two labels, entry first — the way the tunnel runs, whichever end is torn down.

    A hop is twenty-two typed parameters and two minted keypairs. None of that is in
    the entry, because the table has no column it could go in.
    """
    entry_id = await a_node(client, "entry-ru")
    leaf_id = await a_node(client, "leaf-nl")
    ends = await relay.establish_hop(
        session,
        entry_node_id=entry_id,
        leaf_node_id=leaf_id,
        transport_name=HOP_TRANSPORT,
        entry_params={**hop_params, "tunnel_address": "10.44.0.1/24",
                      "peer_tunnel_address": "10.44.0.2/24"},
        leaf_params={**hop_params, "tunnel_address": "10.44.0.2/24",
                     "peer_tunnel_address": "10.44.0.1/24"},
    )
    established = await entries_for(session, AuditAction.HOP_ESTABLISHED)
    assert [(e.first_label, e.second_label) for e in established] == [
        ("entry-ru", "leaf-nl")
    ]

    # Torn down from the LEAF end, which is the order that would read backwards if the
    # labels were written in the order the rows happened to be visited.
    await relay.dissolve_hop(session, node_transport_id=ends[1].id)
    dissolved = await entries_for(session, AuditAction.HOP_DISSOLVED)
    assert [(e.first_label, e.second_label) for e in dissolved] == [
        ("entry-ru", "leaf-nl")
    ]

    for entry in await trail(session):
        for label in (entry.first_label, entry.second_label):
            assert label is None or "10.44.0" not in label


async def test_removing_a_transport_is_its_own_entry_and_outlives_the_row(
    client, session, reality_params
) -> None:
    """M15.2's recording point: the one entry whose subject no longer exists.

    A removal and a withdrawal are different changes and the trail has to tell them
    apart — one leaves the row holding its port, the other frees it and destroys every
    credential minted under it. After the fact the row is gone, so the entry is the only
    place that distinction survives, which is exactly what the journal names as the
    trail's whole marginal disclosure and what retention bounds.

    Both labels are still values read off inventory rows: they are read BEFORE the
    delete, which is the same rule ``dissolve_hop`` follows and the reason a label
    looked up afterwards would be a label that cannot be read.
    """
    node_id = await a_node(client)
    node_transport_id = (
        await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": TRANSPORT, "params": reality_params},
        )
    ).json()["id"]

    await nodes.remove_transport(session, node_transport_id=node_transport_id)

    node = await nodes.get_node(session, node_id)
    written = await entries_for(session, AuditAction.TRANSPORT_REMOVED)
    assert [(e.first_label, e.second_label) for e in written] == [(node.name, TRANSPORT)]
    # Not confusable with the switch-off next to it, which did not happen here.
    assert await entries_for(session, AuditAction.TRANSPORT_WITHDRAWN) == []
    # The row it describes is gone, and the entry says nothing the row held: no port, no
    # config name, no parameter value.
    assert await session.get(NodeTransport, node_transport_id) is None
    for entry in await trail(session):
        for label in (entry.first_label, entry.second_label):
            assert label is None or str(reality_params["port"]) not in label


async def test_removing_one_end_of_a_hop_is_refused_and_records_nothing(
    client, session, hop_params
) -> None:
    """A refusal is not a change, so the trail gains no row for it.

    The rule is "only changes that committed", and this is the one refusal M15.2 adds —
    worth asserting because the refusal happens after the row has been fetched and one
    line before the recording point.
    """
    entry_id = await a_node(client, "entry-ru")
    leaf_id = await a_node(client, "leaf-nl")
    ends = await relay.establish_hop(
        session,
        entry_node_id=entry_id,
        leaf_node_id=leaf_id,
        transport_name=HOP_TRANSPORT,
        entry_params={**hop_params, "tunnel_address": "10.46.0.1/24",
                      "peer_tunnel_address": "10.46.0.2/24"},
        leaf_params={**hop_params, "tunnel_address": "10.46.0.2/24",
                     "peer_tunnel_address": "10.46.0.1/24"},
    )

    with pytest.raises(DomainError):
        await nodes.remove_transport(session, node_transport_id=ends[0].id)

    assert await entries_for(session, AuditAction.TRANSPORT_REMOVED) == []


async def test_rotating_and_replacing_record_the_node_and_the_transport(
    client, session, reality_params
) -> None:
    """Neither the fields that were rotated nor the values that were typed.

    ``rotated`` and the new parameters are what the operator standing there is shown;
    a list of which material a transport holds, kept for days, is a map.
    """
    node_id = await a_node(client)
    node_transport_id = (
        await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": TRANSPORT, "params": reality_params},
        )
    ).json()["id"]

    await rotation.rotate_keys(session, node_transport_id=node_transport_id)
    await rotation.replace_params(
        session,
        node_transport_id=node_transport_id,
        params={"decoy_host": "www.example.net", "server_names": ["www.example.net"]},
    )

    node = await nodes.get_node(session, node_id)
    for action in (AuditAction.KEYS_ROTATED, AuditAction.PARAMS_REPLACED):
        written = await entries_for(session, action)
        assert [(e.first_label, e.second_label) for e in written] == [
            (node.name, TRANSPORT)
        ], action
    for entry in await trail(session):
        for label in (entry.first_label, entry.second_label):
            assert label is None or "example" not in label


async def test_replacing_nothing_records_nothing(client, session, reality_params) -> None:
    """A form submitted unaltered is refused before the commit, so no entry."""
    node_id = await a_node(client)
    node_transport_id = (
        await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": TRANSPORT, "params": reality_params},
        )
    ).json()["id"]

    with pytest.raises(DomainError):
        await rotation.replace_params(
            session,
            node_transport_id=node_transport_id,
            params={"decoy_host": reality_params["decoy_host"]},
        )
    assert await entries_for(session, AuditAction.PARAMS_REPLACED) == []


async def test_every_label_in_the_trail_is_a_value_read_off_an_inventory_row(
    client, session, reality_params, refusing_ssh
) -> None:
    """The rule a column whitelist cannot express: what the permitted columns HOLD.

    A walk that produces every kind of entry a fleet can produce, including a node
    degraded with a reason on it, checked against the set of values that actually exist
    in the inventory. ``f"{node.name}: {node.state_detail}"`` is inside the whitelist,
    inside the action vocabulary, and fails here.
    """
    node_id = (
        await client.post(
            "/api/nodes",
            json={
                "name": "leaf-nl",
                "address": NODE_ADDRESS,
                "location_label": "Testland",
                "ssh_host": refusing_ssh.host,
                "ssh_port": refusing_ssh.port,
                "ssh_private_key": GENERATED_SSH_KEY,
            },
        )
    ).json()["id"]
    node_transport_id = (
        await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": TRANSPORT, "params": reality_params},
        )
    ).json()["id"]
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "kolya"})
    ).json()["id"]
    await client.post(f"/api/nodes/{node_id}/apply")  # fails; degrades the node
    await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=False
    )
    await revocation.revoke_friend(session, friend_id=friend_id)

    session.expire_all()
    inventory = {
        *(await session.execute(select(Node.name))).scalars(),
        *(await session.execute(select(Friend.nickname))).scalars(),
        *(await session.execute(select(NodeTransport.transport_name))).scalars(),
        *(state.value for state in NodeState),
    }
    entries = await trail(session)
    assert len(entries) >= 6, "the walk did not produce a trail worth checking"
    for entry in entries:
        for label in (entry.first_label, entry.second_label):
            if label is None:
                continue
            assert label in inventory, (
                f"{label!r} is not a value this fleet holds — an audit label is COPIED "
                "off an inventory row (a node name, a nickname, a transport name, a "
                "state), never composed from one"
            )


# --- the rule the whole table stands or falls on -----------------------------

async def test_fetching_a_subscription_writes_nothing_to_the_trail(
    client, anonymous, session, reality_params
) -> None:
    """The delivery endpoint writes NO ROW — not merely no row naming a token.

    The e2e scenario of the same name is the named deliverable and runs this against
    the real stack; this is its fast twin, and it is the one that runs on every commit.
    Asserted as "the trail did not grow at all", because a row saying only
    ``friend-added`` against a time would still be a record that somebody fetched their
    subscription at that moment.
    """
    node_id = await a_node(client)
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": TRANSPORT, "params": reality_params},
    )
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "kolya"})
    ).json()["id"]
    url = (
        await client.get(f"/api/friends/{friend_id}/subscription")
    ).json()["url"]
    token = url.rsplit("/", 1)[-1]

    before = await trail(session)
    assert before, "the premise: this session can see entries at all"

    served = await anonymous.get(f"/sub/{token}")
    assert served.status_code == 200, "the premise: a real subscription was served"
    assert (await anonymous.get("/sub/not-a-token-that-exists-at-all")).status_code == 404

    after = await trail(session)
    assert [entry.id for entry in after] == [entry.id for entry in before], (
        "the delivery endpoint wrote to the audit trail. It writes nothing there, "
        "ever: a row against a time is a record that a person used the service, which "
        "is the record this project exists not to keep"
    )


# --- retention ---------------------------------------------------------------

def test_the_window_is_bounded_and_no_value_means_forever() -> None:
    """1–365 days, and nothing outside it — including 0, which would mean "keep none".

    A record with no end is what the charter objects to, so the absence of an off
    switch is the decision rather than a missing feature.
    """
    assert (
        Settings.model_fields["audit_retention_days"].default
        == AUDIT_RETENTION_DEFAULT_DAYS
        == 30
    )
    # Driven off the same constants the Settings screen composes its sentence from, so
    # a bound that moves moves both, and the screen cannot come to state a window this
    # field would refuse.
    for refused in (
        AUDIT_RETENTION_MIN_DAYS - 1,
        -1,
        AUDIT_RETENTION_MAX_DAYS + 1,
        10_000,
    ):
        with pytest.raises(pydantic.ValidationError):
            Settings(
                secret_key="x" * 32,
                database_url="postgresql+asyncpg://x/y",
                operator_password_hash="scrypt$32768$8$1$c2FsdA==$aGFzaA==",
                audit_retention_days=refused,
            )
    for accepted in (
        AUDIT_RETENTION_MIN_DAYS,
        AUDIT_RETENTION_DEFAULT_DAYS,
        AUDIT_RETENTION_MAX_DAYS,
    ):
        assert (
            Settings(
                secret_key="x" * 32,
                database_url="postgresql+asyncpg://x/y",
                operator_password_hash="scrypt$32768$8$1$c2FsdA==$aGFzaA==",
                audit_retention_days=accepted,
            ).audit_retention_days
            == accepted
        )


async def test_the_sweep_deletes_what_is_past_the_window_and_keeps_the_rest(
    session,
) -> None:
    """Retention, asserted rather than promised on the Settings screen."""
    now = datetime.datetime.now(datetime.UTC)
    kept = AuditEntry(
        action=AuditAction.NODE_ADDED,
        first_label="leaf-new",
        at=now - datetime.timedelta(days=29, hours=23),
    )
    gone = AuditEntry(
        action=AuditAction.NODE_ADDED,
        first_label="leaf-old",
        at=now - datetime.timedelta(days=31),
    )
    session.add_all([kept, gone])
    await session.commit()

    assert await audit.sweep(session, retention_days=30) == 1

    remaining = [entry.first_label for entry in await trail(session)]
    assert remaining == ["leaf-new"]


async def test_a_sweep_that_fails_does_not_end_the_sweeper(app, monkeypatch) -> None:
    """A database blip must not stop retention for the lifetime of the process.

    That failure would be invisible — nothing would look wrong except a trail that
    never shrinks — so the loop's survival is asserted rather than assumed.
    """
    passes = []

    async def failing_then_fine(session, *, retention_days):
        passes.append(retention_days)
        if len(passes) == 1:
            raise RuntimeError("the database went away")
        return 0

    monkeypatch.setattr(audit, "sweep", failing_then_fine)
    monkeypatch.setattr(audit, "SWEEP_INTERVAL_SECONDS", 0)

    task = audit.start_sweeper(app.state.database, retention_days=7)
    # Bounded rather than `while len(passes) < 3`: a sweeper that died at the first
    # failure is exactly what this test is about, and waiting forever for it reports as
    # a hung suite instead of as a failed assertion.
    for _ in range(2000):
        if len(passes) >= 3 or task.done():
            break
        await asyncio.sleep(0)
    await audit.stop_sweeper(task)

    assert passes[:3] == [7, 7, 7], "the sweeper stopped at the first failure"
    assert task.done()


async def test_the_application_runs_the_sweep_for_as_long_as_it_is_up(app) -> None:
    """Started in the lifespan and cancelled with it — not on write.

    A trail that expires only when the operator acts is not retention on an idle
    machine, and an idle machine is the one this matters on.
    """
    async with app.router.lifespan_context(app):
        sweeper = app.state.audit_sweeper
        assert not sweeper.done(), "nothing is sweeping the trail"
    assert sweeper.done(), "the sweeper outlived the application that started it"


# --- a node that answers, for the one test that needs an apply to succeed -----

class _FakeHost:
    """Docker on a node, in as few lines as a successful apply needs.

    Deliberately not imported from ``test_apply_must_reach_the_daemon``: that file's
    fake exists to model the ONE rule of Compose that M1 is about (a container is not
    recreated when its definition is unchanged), and nothing here depends on that rule.
    Importing it would couple two suites so that tightening M1's fake breaks this file
    for a reason that has nothing to do with the audit trail.
    """

    learned_host_key = None

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.digests: dict[str, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        return False

    async def run(self, command: str, *, check: bool = True):
        from edge.bootstrap.ssh import CommandResult

        if "docker compose up -d" in command:
            services = yaml.safe_load(self.files[node_stack.COMPOSE_PATH])["services"]
            self.digests = {
                name: definition.get("labels", {}).get(node_stack.CONFIG_DIGEST_LABEL, "")
                for name, definition in services.items()
            }
            return CommandResult(exit_status=0, stdout="", stderr="")
        if "docker inspect" in command:
            lines = [f"{name}|{digest}|true" for name, digest in self.digests.items()]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")
        if "docker version" in command:
            return CommandResult(exit_status=0, stdout="27.1.1\n", stderr="")
        return CommandResult(exit_status=0, stdout="", stderr="")

    async def write_file(self, path: str, content: str, *, mode: int = 0o600) -> None:
        self.files[path] = content

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)
