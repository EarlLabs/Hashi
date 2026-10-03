"""What a user actually gets when they refresh against a delivery host — M27.5.

WHAT: the two ways a pushed subscription differs from the one the control plane would
      answer with — it is a SNAPSHOT and it is a SLICE — and what the product decided a
      user gets in each case.
WHY:  M27. A pushed artifact is rendered at an apply and holds only that host's own
      material, so a refresh against a delivery host can be older than the database and
      is narrower than ``/sub/{token}``. The milestone's question is whether either of
      those lies to the person refreshing. The decision (``docs/decisions.md``,
      2026-09-27) is that nothing is written into the artifact on either axis, and it
      rests on facts that are asserted here rather than argued:

      * the SNAPSHOT is the configuration the host is running, because the material and
        the host's own configs are two renders of one row set inside one apply — they go
        out of date together and one apply carries both back;
      * the SLICE is a strictly shorter subscription and never an error, and where one
        host carries every user-facing row it is BYTE FOR BYTE what the control plane
        would have answered — which is also the pin that no marker, note or timestamp
        was added to the artifact.

HOW:  the shared ``accepting_nodes`` harness with a watcher over the delivery calls, the
      way ``test_an_apply_hands_a_node_the_subscriptions_it_serves.py`` does, plus the
      real ``/sub/{token}`` route through the app so the two answers are compared as
      bytes rather than as two renders trusted to agree.

      Nothing here proves a file reached a disk and nothing here serves one: no delivery
      host has a listener yet.
"""

import ipaddress

import pytest
from sqlalchemy import select

from control.app.models import Subscription
from control.app.services import apply, console, delivery, nodes
from control.app.services import transports as transports_service
from edge.bootstrap import delivery as node_delivery
from edge.egress import NOT_THE_INTERNET_IPV4
from edge.registry import SubscriptionFormat, discover

from .conftest import GENERATED_SSH_KEY, a_user_no_node_was_told_about, pinned

# Reserved documentation NAMES, and the name half is the subject since M27.6: a host
# registered by address can hold no certificate, so it serves no delivery and is handed
# no material. Never dialled and never resolved — the connection is replaced — and they
# have to differ because the narrowing is asserted by looking for one of them in the
# other host's material.
FIRST_ADDRESS = "first.example.test"
SECOND_ADDRESS = "second.example.test"

# One transport of each SHAPE, resolved from the registry rather than named: this file
# compares both shapes of a subscription against both shapes of an artifact, and a shape
# with no transport behind it cannot be compared at all.
URI_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.V1_URI_LIST in meta.subscription_formats
    and name in transports_service.offerable_transports()
)
FILE_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
    and name in transports_service.offerable_transports()
)

# The operator half of a transport's parameters, filtered per transport against its own
# model so one literal serves every member. Two ports, because a node here carries one
# transport of each shape and they cannot both hold the same one.
TRANSPORT_PARAMS: dict[str, object] = {
    "port": 8443,
    "decoy_host": "www.example.com",
    "decoy_port": 443,
    "server_names": ["www.example.com"],
    "server_name": "front.example.com",
    "certificate_path": "/etc/hashi/certs/fullchain.pem",
    "certificate_key_path": "/etc/hashi/certs/privkey.pem",
    "tunnel_address": "10.92.0.1/24",
    "peer_tunnel_address": "10.92.0.2/24",
    "mtu": 1280,
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}
SECOND_PORT = 8444


def _a_resolver_the_drops_leave_alone() -> str:
    """A v4 address a user's own tunnel rules do NOT take away — i.e. on the internet.

    Derived from ``edge``'s own list rather than written down, for two reasons. Every
    literal address in this zone's tests is an RFC 5737 documentation one, and the drops
    treat all of those as off the internet — so the state the resolver test below is
    about cannot be reached with one. And asking the list is what keeps this true if the
    list ever gains a range: a written-down address would silently start being the other
    case.
    """
    for first_octet in range(1, 224):
        candidate = ipaddress.ip_address(f"{first_octet}.0.0.53")
        if not any(
            candidate in ipaddress.ip_network(network)
            for network in NOT_THE_INTERNET_IPV4
        ):
            return str(candidate)
    raise AssertionError(
        "edge's drop list holds every v4 address, so no resolver is on the internet"
    )


A_RESOLVER_ON_THE_INTERNET = _a_resolver_the_drops_leave_alone()

pytestmark = pytest.mark.skipif(
    not URI_TRANSPORTS or not FILE_TRANSPORTS,
    reason="this image does not ship a transport of each subscription shape",
)


@pytest.fixture(params=URI_TRANSPORTS)
def uri_transport(request) -> str:
    return request.param


@pytest.fixture(params=FILE_TRANSPORTS)
def file_transport(request) -> str:
    return request.param


class Handed:
    """The artifacts the most recent apply handed a host.

    Replaced per apply rather than appended to, because the real placement replaces the
    host's whole delivery directory: a list that grew across applies would let a test
    read material no longer on the node.
    """

    def __init__(self) -> None:
        self.artifacts: list[node_delivery.Artifact] = []
        self.pushes = 0

    def shape(self, which: SubscriptionFormat) -> dict[str, bytes]:
        """What was pushed in one shape, as raw bytes, by the name it was placed under.

        Bytes and not a decoded document: what this file compares is whether a host's
        answer and the control plane's are the same ANSWER, and a decode either side
        would hide a difference that a user's client would meet.
        """
        return {
            artifact.name: artifact.content
            for artifact in self.artifacts
            if artifact.shape is which
        }


@pytest.fixture
def handed(accepting_nodes, monkeypatch) -> Handed:
    """The accepting node, watched — layered over the shared harness, not replacing it."""
    watched = Handed()
    accepting = node_delivery.place_delivery

    async def place_delivery(connection, *, artifacts) -> None:
        watched.artifacts = list(artifacts)
        watched.pushes += 1
        await accepting(connection, artifacts=artifacts)

    pinned(monkeypatch, node_delivery, "place_delivery", place_delivery)
    return watched


def params_for(transport_name: str, **overrides) -> dict[str, object]:
    """The operator-supplied half, minus knobs this transport does not declare."""
    from edge.registry import profile  # noqa: PLC0415

    declared = set(profile(transport_name).params_model.model_fields)
    supplied = {**TRANSPORT_PARAMS, **overrides}
    return {key: value for key, value in supplied.items() if key in declared}


async def a_reachable_node(client, *, name: str, address: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": address,
            "location_label": "Testland",
            "ssh_host": address,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def enable(client, node_id: str, transport_name: str, **overrides):
    from edge.registry import profile  # noqa: PLC0415

    asked: dict[str, object] = {
        "transport_name": transport_name,
        "params": params_for(transport_name, **overrides),
    }
    # A pool only where the transport DECLARES that each user gets an address of their
    # own — never on the transport's name. The others refuse the key rather than
    # ignoring it. Sized past the two users below rather than to them, so nothing here
    # is ever about a pool that ran out.
    if profile(transport_name).meta.peer_address is not None:
        asked["pool_size"] = 8
    enabled = await client.post(f"/api/nodes/{node_id}/transports", json=asked)
    assert enabled.status_code == 201, enabled.text
    return enabled


async def add_user(client, nickname: str) -> str:
    created = await client.post("/api/users", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def apply_node(client, node_id: str) -> None:
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text


async def the_token(session, user_id: str) -> str:
    found = await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    live = [row for row in found.scalars().unique() if row.is_active]
    assert live, "the user has no live subscription, so there is nothing to push for them"
    return live[0].token


async def fetched(anonymous, token: str, which: SubscriptionFormat) -> bytes:
    """What the control plane itself answers this token with, in one shape."""
    answer = await anonymous.get(f"/sub/{token}", params={"format": which})
    assert answer.status_code == 200, answer.text
    return answer.content


# --- the slice, where there is nothing to slice ----------------------------------------


async def test_one_user_facing_host_hands_over_what_the_control_plane_would(
    client, anonymous, session, uri_transport: str, file_transport: str, handed: Handed
) -> None:
    """Byte for byte, in both shapes — the arrangement this milestone was asked for.

    Where exactly one host carries user-facing transports, the narrowed artifact and the
    whole subscription are the same document, so narrowing costs that fleet nothing.

    It is also the pin on the answer M27.5 gave: no marker naming when the artifact was
    rendered, no entry saying what is missing, no note beside the entries. Any of those
    would make these bytes differ, and each of them would be one more thing a seized
    delivery host yields.
    """
    boris = await add_user(client, "boris")
    node_id = await a_reachable_node(client, name="entry", address=FIRST_ADDRESS)
    await enable(client, node_id, uri_transport)
    await enable(client, node_id, file_transport, port=SECOND_PORT)
    await apply_node(client, node_id)

    session.expire_all()
    token = await the_token(session, boris)
    name = delivery.artifact_name(node_id, token)

    for shape in (SubscriptionFormat.V1_URI_LIST, SubscriptionFormat.CLIENT_CONFIG_FILE):
        pushed = handed.shape(shape)
        assert set(pushed) == {name}, (pushed, name)
        assert pushed[name] == await fetched(anonymous, token, shape), (
            f"the {shape} a user fetches from this host is not the one the control "
            "plane would have answered, on a fleet where the two are the same set of "
            "rows — so something was added to the artifact"
        )


# --- the slice, where there is something to slice --------------------------------------


async def test_a_second_user_facing_host_answers_a_shorter_list_and_never_an_error(
    client, anonymous, session, uri_transport: str, handed: Handed
) -> None:
    """The partial axis: what a user gets from each host is a subscription, not a refusal.

    From the second user-facing node onward each host answers strictly less than the
    control plane would — that is the narrowing working, and it is the direction a user
    cannot tell apart from a revocation. What this pins is the product's answer to it:
    each host's document is a VALID shorter subscription, the two together are the whole
    one, and neither host says anything about the other.
    """
    boris = await add_user(client, "boris")
    entry = await a_reachable_node(client, name="entry", address=FIRST_ADDRESS)
    await enable(client, entry, uri_transport)
    await apply_node(client, entry)

    second = await a_reachable_node(client, name="second", address=SECOND_ADDRESS)
    await enable(client, second, uri_transport)
    await apply_node(client, second)
    from_second = handed.shape(SubscriptionFormat.V1_URI_LIST)

    # Re-applied so the first host holds material rendered after the second exists,
    # which is the moment a whole subscription would start carrying both addresses.
    await apply_node(client, entry)
    from_entry = handed.shape(SubscriptionFormat.V1_URI_LIST)

    session.expire_all()
    token = await the_token(session, boris)
    whole = await fetched(anonymous, token, SubscriptionFormat.V1_URI_LIST)

    slices = [
        from_entry[delivery.artifact_name(entry, token)],
        from_second[delivery.artifact_name(second, token)],
    ]
    for one in slices:
        assert one, (
            "a host answered a user with nothing rather than with the part of their "
            "subscription it can serve"
        )
        assert one != whole, "this fleet's second host was handed an unnarrowed document"

    lines = [set(_entries(one)) for one in slices]
    assert lines[0].isdisjoint(lines[1]), (from_entry, from_second)
    assert set().union(*lines) == set(_entries(whole)), (
        "the two hosts' documents are not a partition of the subscription, so a slice "
        "is a different document rather than a shorter one"
    )


def _entries(document: bytes) -> list[str]:
    """The client entries in a v1 document, as a client reads them."""
    import base64  # noqa: PLC0415

    decoded = base64.b64decode(document).decode()
    return [line for line in decoded.splitlines() if line]


# --- the snapshot ----------------------------------------------------------------------


async def test_a_host_and_its_material_go_out_of_date_together_and_come_back_together(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """The stale axis, and the reason nothing is said about it to the user.

    The artifact is rendered over the rows the same apply is placing, so what a host
    serves describes the configuration that host is RUNNING. The panel already has the
    sentence for the state where that is behind the database (``drift_of``), and this
    holds the two readings together: the moment the panel reports drift is the moment
    the host's material stopped matching the database, and one apply carries both back.
    """
    await add_user(client, "boris")
    node_id = await a_reachable_node(client, name="entry", address=FIRST_ADDRESS)
    await enable(client, node_id, uri_transport)
    await apply_node(client, node_id)

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) == console.IN_SYNC
    after_apply = list(handed.artifacts)
    pushes = handed.pushes

    # A change this panel knows about and no apply has carried — the state M25 named.
    # The database half of an add only, since an add through the API applies (M32).
    await a_user_no_node_was_told_about(session, "kolya")

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) != console.IN_SYNC, (
        "the panel says this host is running what we would give it while a user was "
        "added since the last apply"
    )
    assert handed.pushes == pushes, "something pushed to the host outside an apply"
    assert handed.artifacts == after_apply, (
        "the host's material changed without an apply, so what it serves is no longer "
        "the configuration it is running"
    )

    await apply_node(client, node_id)

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) == console.IN_SYNC
    assert handed.pushes == pushes + 1, "the apply that re-synced the host pushed nothing"
    assert len(handed.artifacts) > len(after_apply), (
        "one apply brought the host's configuration back into sync and left its "
        "material behind"
    )


async def test_the_rows_the_material_is_rendered_over_are_the_rows_that_are_placed(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """Why the reading above holds, said as the structure rather than as an outcome.

    ``drift_of`` compares a fresh ``render_for_node`` against what was last pushed, and
    the artifact is rendered over ``enabled_transports`` inside the same apply. Same
    node, same filter, same transaction — so there is no change to a ROW that can reach
    one and not the other.
    """
    await add_user(client, "boris")
    node_id = await a_reachable_node(client, name="entry", address=FIRST_ADDRESS)
    await enable(client, node_id, uri_transport)
    await apply_node(client, node_id)
    assert handed.pushes == 1

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    rows = await apply.enabled_transports(session, node)
    # Name, SHAPE and CONTENT. Names alone would be the weaker claim this docstring does
    # not make: a change reaching one render and not the other is a change to the bytes,
    # and every artifact for one subscription is named the same in both shapes.
    assert _identified(handed.artifacts) == _identified(
        await delivery.artifacts_for_node(session, node, rows)
    ), "re-rendering over this node's enabled rows does not reproduce what was pushed"


def _identified(artifacts) -> set[tuple[str, SubscriptionFormat, bytes]]:
    """Artifacts as the three things that make one distinguishable from another."""
    return {
        (artifact.name, artifact.shape, artifact.content) for artifact in artifacts
    }


async def test_the_one_record_field_that_reaches_rendered_material_parts_them(
    client, session, file_transport: str, handed: Handed
) -> None:
    """The one exception to the reading above, measured rather than assumed.

    Two fields on a node record can change after registration — ``nodes.set_resolver``
    and ``nodes.set_ssh_key`` — and ``resolver`` is the only one that reaches rendered
    material at all, because an SSH key is an input to no render. It is not on a row
    either: it reaches a user's own configuration file through
    ``client_resolvers``, while it reaches the node's own config only as a firewall
    exception, and only for a resolver the user's tunnel rules would otherwise DROP.
    Point a node at a resolver on the internet and the host's configuration is
    unchanged, so the panel goes on reading "in sync" while the archive on the host
    still names the old one.

    A user is not misled by it — they get the resolver this host was applied with, which
    is the one its rules were rendered for — and the toast that sets the field already
    tells the operator to apply the node. It is pinned because it is the only way the
    two readings part, and a later step reading the sentence above would otherwise take
    it as exceptionless.
    """
    await add_user(client, "boris")
    node_id = await a_reachable_node(client, name="entry", address=FIRST_ADDRESS)
    await enable(client, node_id, file_transport)
    await apply_node(client, node_id)
    before = list(handed.artifacts)

    changed = await client.post(
        f"/api/nodes/{node_id}/resolver", json={"resolver": A_RESOLVER_ON_THE_INTERNET}
    )
    assert changed.status_code == 200, changed.text

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) == console.IN_SYNC, (
        "a resolver on the internet reached this node's own configuration after all — "
        "if that is now true, the sentence about the two readings has no exception and "
        "this test should say so"
    )
    rows = await apply.enabled_transports(session, node)
    assert await delivery.artifacts_for_node(session, node, rows) != before, (
        "changing the node's resolver did not change what a user would fetch, so this "
        "file records an exception that does not exist"
    )
