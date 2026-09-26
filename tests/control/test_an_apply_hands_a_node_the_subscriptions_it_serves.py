"""What an apply places on a host so a user can refresh against it — M27.2.

WHAT: the artifacts ``apply.apply_node`` hands a node: which subscriptions are in them,
      what is NOT in them, what they are named, and what happens to the ones a later
      apply no longer renders.
WHY:  M27. The refresh endpoint lives wherever the control plane lives, so a user
      inside Russia loses it at exactly the moment a node is blocked. What moves to the
      node is the rendered result, pushed on apply over the channel that already
      exists — and the whole question the milestone turns on is what a seized host then
      holds. Two answers are asserted here rather than argued: no other node's address,
      and no user's token.
HOW:  the shared ``accepting_nodes`` harness with one more double over it, so this file
      can read what was handed to the host. Nothing here proves a file reached a disk,
      and nothing here proves anything serves it — nothing does yet.
"""

import base64
import io
import zipfile

import pytest
from sqlalchemy import select

from control.app.models import NodeTransport, Subscription
from control.app.services import apply, delivery, nodes
from control.app.services import transports as transports_service
from edge.bootstrap import delivery as node_delivery
from edge.bootstrap.delivery import ARTIFACT_NAME
from edge.bootstrap.ssh import NodeUnreachable
from edge.registry import SubscriptionFormat, discover

from .conftest import GENERATED_SSH_KEY, pinned

# RFC 5737 documentation addresses, as everywhere in this zone. Never dialled — the
# connection is replaced — but a node record has to name something, and these two have
# to differ because the narrowing is asserted by looking for one of them.
FIRST_ADDRESS = "192.0.2.81"
SECOND_ADDRESS = "192.0.2.82"

# Every transport this image both OFFERS and serialises into the v1 URI list. The
# declaration, never a name: a transport added later is exercised here by arriving, and
# one that only produces a file is covered by the archive assertions below.
URI_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.V1_URI_LIST in meta.subscription_formats
    and name in transports_service.offerable_transports()
)

# The operator half of such a transport's parameters, filtered per transport against its
# own model so one literal serves every member.
URI_PARAMS: dict[str, object] = {
    "port": 8443,
    "decoy_host": "www.example.com",
    "decoy_port": 443,
    "server_names": ["www.example.com"],
    "server_name": "front.example.com",
    "certificate_path": "/etc/hashi/certs/fullchain.pem",
    "certificate_key_path": "/etc/hashi/certs/privkey.pem",
}

pytestmark = pytest.mark.skipif(
    not URI_TRANSPORTS,
    reason="this image offers no transport that serialises into the v1 URI list",
)


@pytest.fixture(params=URI_TRANSPORTS)
def uri_transport(request) -> str:
    return request.param


class Handed:
    """Every artifact the most recent apply handed a host.

    Replaced per apply rather than appended to, because the real placement replaces the
    host's whole delivery directory: a list that grew across applies would let a test
    see material that is no longer on the node.
    """

    def __init__(self) -> None:
        self.artifacts: list[node_delivery.Artifact] = []
        self.pushes = 0
        # And the other call an apply can make — M27.4. A host that is not a delivery
        # host is not pushed an empty set, it is stripped: the two are different states
        # on the host and have to be different facts here.
        self.removals = 0


@pytest.fixture
def handed(accepting_nodes, monkeypatch) -> Handed:
    """The accepting node, watched — layered over the shared harness, not replacing it.

    ``pinned`` still runs, comparing this double against the one already installed,
    which is itself pinned to the real function.
    """
    watched = Handed()
    accepting = node_delivery.place_delivery
    stripping = node_delivery.remove_delivery

    async def place_delivery(connection, *, artifacts) -> None:
        watched.artifacts = list(artifacts)
        watched.pushes += 1
        await accepting(connection, artifacts=artifacts)

    async def remove_delivery(connection) -> bool:
        watched.removals += 1
        return await stripping(connection)

    pinned(monkeypatch, node_delivery, "place_delivery", place_delivery)
    pinned(monkeypatch, node_delivery, "remove_delivery", remove_delivery)
    return watched


def params_for(transport_name: str, **overrides) -> dict[str, object]:
    """The operator-supplied half, minus knobs this transport does not declare."""
    from edge.registry import profile  # noqa: PLC0415

    declared = set(profile(transport_name).params_model.model_fields)
    supplied = {**URI_PARAMS, **overrides}
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


async def enable(client, node_id: str, transport_name: str):
    return await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": transport_name, "params": params_for(transport_name)},
    )


async def add_user(client, nickname: str) -> str:
    created = await client.post("/api/users", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def a_served_node(client, transport_name: str, *, name: str, address: str) -> str:
    """A node in service, carrying one user-facing transport."""
    node_id = await a_reachable_node(client, name=name, address=address)
    assert (await enable(client, node_id, transport_name)).status_code == 201
    assert (await client.post(f"/api/nodes/{node_id}/apply")).status_code == 200
    return node_id


def documents(handed: Handed) -> dict[str, str]:
    """The v1 documents that were pushed, decoded, by the name they were placed under."""
    return {
        artifact.name: base64.b64decode(artifact.content).decode()
        for artifact in handed.artifacts
        if artifact.shape is SubscriptionFormat.V1_URI_LIST
    }


def archives(handed: Handed) -> dict[str, list[str]]:
    """The archives that were pushed, as their entry names, by artifact name."""
    return {
        artifact.name: zipfile.ZipFile(io.BytesIO(artifact.content)).namelist()
        for artifact in handed.artifacts
        if artifact.shape is SubscriptionFormat.CLIENT_CONFIG_FILE
    }


async def the_token(session, user_id: str) -> str:
    found = await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    live = [row for row in found.scalars().unique() if row.is_active]
    assert live, "the user has no live subscription, so there is nothing to push for them"
    return live[0].token


# --- what is handed over -----------------------------------------------------------


async def test_an_apply_hands_the_host_both_shapes_of_its_own_users_subscription(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """The step itself: the material a user would fetch is on the node after an apply."""
    boris = await add_user(client, "boris")
    node_id = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)

    session.expire_all()
    token = await the_token(session, boris)
    name = delivery.artifact_name(node_id, token)

    assert set(documents(handed)) == {name}, handed.artifacts
    assert set(archives(handed)) == {name}, (
        "only one of the two shapes was pushed, so a refresh against this host answers "
        "one of them with nothing"
    )
    assert FIRST_ADDRESS in documents(handed)[name], (
        "the document pushed to the host does not name the host, so a user refreshing "
        "against it gets a subscription that reaches nothing"
    )


async def test_the_pushed_document_names_no_other_node(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """The narrowing, asserted on the bytes — ``docs/decisions.md``, 2026-09-26.

    A subscription names every node a user may use, and pushing it whole would put the
    fleet's leaf addresses on the machine the arrangement this milestone is for treats
    as the expendable one.
    """
    await add_user(client, "boris")
    entry = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)
    await a_served_node(client, uri_transport, name="leaf", address=SECOND_ADDRESS)

    # The second node's apply granted the user material on it too, so re-applying the
    # first is the moment a whole subscription would carry both addresses.
    assert (await client.post(f"/api/nodes/{entry}/apply")).status_code == 200

    pushed = "\n".join(documents(handed).values())
    assert FIRST_ADDRESS in pushed, pushed
    assert SECOND_ADDRESS not in pushed, (
        "the artifact pushed to one host names another node — a seized delivery host "
        "now yields the address of a node its users were never told about"
    )


async def test_what_is_pushed_is_named_by_a_digest_and_never_by_the_token(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """The store decision, asserted where it can be checked: no token reaches a node.

    A seized delivery host must not yield the live bearer credential of every user it
    serves — those tokens also open the un-narrowed document on the control plane, they
    have no expiry, and the URL is the only artefact a user holds.
    """
    boris = await add_user(client, "boris")
    await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)

    session.expire_all()
    token = await the_token(session, boris)

    for artifact in handed.artifacts:
        assert token not in artifact.name, (
            "a user's token is the name of a file on the node: seizing the host hands "
            "over every live subscription URL"
        )
        assert token.encode() not in artifact.content, (
            "a user's token is inside the material placed on the node"
        )
    assert handed.artifacts, "nothing was pushed, so this proves nothing"


async def test_the_material_on_a_host_names_nobody(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """Who a host serves is not something the host is told in words.

    The labels in a subscription are the node's own — a country and a display name —
    and the nickname an operator types is theirs, not the fleet's.
    """
    await add_user(client, "a-nickname-nothing-else-would-produce")
    await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)

    for artifact in handed.artifacts:
        assert b"a-nickname-nothing-else-would-produce" not in artifact.content, (
            "a user's nickname is in the material on the node"
        )


# --- and what stops being handed over ------------------------------------------------


async def test_a_user_who_stops_being_served_here_is_gone_from_the_next_push(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """The stop case, at the one scale an apply can close it.

    ``docs/decisions.md`` (2026-09-13) records that an apply never removes what an
    earlier one wrote. It is not true of this directory, and this is why: an artifact
    is a rendered subscription, and one left behind after its holder was revoked is a
    document that keeps being served to whoever can still fetch it.
    """
    boris = await add_user(client, "boris")
    kolya = await add_user(client, "kolya")
    node_id = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)

    session.expire_all()
    gone = delivery.artifact_name(node_id, await the_token(session, boris))
    stays = delivery.artifact_name(node_id, await the_token(session, kolya))
    assert {gone, stays} <= set(documents(handed)), handed.artifacts

    # Revocation, which re-pushes every node the user was on — so the removal is
    # reached the way an operator reaches it rather than by applying by hand.
    revoked = await client.post(f"/api/users/{boris}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["complete"] is True, revoked.json()

    assert node_id
    assert set(documents(handed)) == {stays}, (
        "a revoked user's rendered subscription is still on the host after an apply "
        "that no longer renders it"
    )


async def test_a_node_carrying_nobody_is_pushed_an_empty_set(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """A host with no users still gets a push, and the push is empty.

    That is what makes the directory a replacement rather than an accumulation: the
    empty set is the only way a host that stopped carrying anybody stops holding their
    material.
    """
    node_id = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)

    assert handed.pushes == 1, "the apply did not reach the delivery push at all"
    assert handed.artifacts == [], (
        f"a node with no users was handed material anyway: {handed.artifacts}"
    )
    assert node_id


# --- the seam itself -----------------------------------------------------------------


async def test_material_is_never_rendered_over_another_nodes_rows(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """The narrowing held at the seam, not assumed of the caller.

    Rows from another node would put that node's address into this host's artifact, and
    nothing downstream could see it.
    """
    await add_user(client, "boris")
    entry = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)
    second = await a_served_node(client, uri_transport, name="leaf", address=SECOND_ADDRESS)

    session.expire_all()
    listed = await session.execute(
        select(NodeTransport).where(NodeTransport.node_id == second)
    )
    theirs = list(listed.scalars().unique())
    mine = await nodes.get_node(session, entry)

    with pytest.raises(ValueError):
        await delivery.artifacts_for_node(session, mine, theirs)


def test_a_derived_name_is_one_this_node_package_will_place() -> None:
    """The two zones' halves of one name, pinned against each other.

    ``control`` derives it and ``edge`` decides what a name may be. A derivation that
    outgrew that rule would be refused on the node, per artifact, on every apply.
    """
    name = delivery.artifact_name("node-1", "a" * 43)
    assert ARTIFACT_NAME.match(name), name
    assert delivery.artifact_name("node-1", "a" * 43) == name, "the same token named two files"
    assert delivery.artifact_name("node-1", "b" * 43) != name


def test_one_subscription_is_a_different_name_on_every_host() -> None:
    """M27.3's decision, asserted where it is derived.

    The listener a delivery host runs serves the file its path names and hashes nothing,
    so the name IS the credential that fetches the artifact. Without the node's own id
    in the derivation, the names on a seized host would fetch the same users' artifacts
    from every other delivery host — which is the cross-host narrowing this milestone is
    for. See ``docs/decisions.md``, 2026-09-26.
    """
    token = "a" * 43
    assert delivery.artifact_name("node-1", token) != delivery.artifact_name("node-2", token)


async def test_a_node_with_nothing_enabled_is_refused_and_stripped(
    client, session, uri_transport: str, handed: Handed
) -> None:
    """The stop case, CLOSED — M27.4, and this test used to pin it open.

    Withdraw a node's only transport and press apply: ``apply_node`` still answers
    "nothing to apply" and still pushes nothing, and it now reaches the host for one
    thing before it does — the delivery material an earlier apply left there, which is
    its ex-users' rendered subscriptions and the client halves in them, on a host this
    control plane will never push to again.

    What is unchanged is everything else about the refusal: 409, no state written, and a
    node still running whatever it was last given.
    """
    await add_user(client, "boris")
    node_id = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)
    assert handed.pushes == 1 and handed.artifacts, "the first apply pushed nothing"

    rows = await session.execute(select(NodeTransport).where(NodeTransport.node_id == node_id))
    only = next(iter(rows.scalars().unique()))
    withdrawn = await client.post(
        f"/api/transports/{only.id}/state", json={"enabled": False}
    )
    assert withdrawn.status_code == 200, withdrawn.text

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    said = refused.json()["error"]["message"]
    assert handed.pushes == 1, (
        f"the refused apply pushed material to a host it refuses to configure: {said}"
    )
    assert handed.removals == 1, (
        "the refused apply left the host holding its ex-users' subscriptions, which is "
        f"the state M27.4 closes: {said}"
    )
    # WHICH 409, not merely a 409: a future change refusing this apply for another
    # reason would keep a status assertion green while the path under test stopped
    # being reachable.
    assert apply.DELIVERY_TAKEN_BACK in said, said
    assert apply.NOTHING_CHANGED_ON_THE_NODE not in said, (
        "the refusal tells the operator nothing on the node was changed, in the one "
        f"case where something was: {said}"
    )


async def test_a_refused_apply_on_a_host_holding_nothing_says_what_it_always_said(
    client, session, uri_transport: str, handed: Handed, monkeypatch
) -> None:
    """The common case, and the one M18.1's sentence was written for.

    Almost every host this refusal is read on never held delivery material — every host
    in this product did not, until M27.2 — so the removal finds nothing and the operator
    reads exactly the sentence they read before. A clause that appeared on every refusal
    would be a change to the one screen M18's acceptance walked.
    """

    async def remove_delivery(connection) -> bool:
        handed.removals += 1
        return False

    pinned(monkeypatch, node_delivery, "remove_delivery", remove_delivery)
    await add_user(client, "boris")
    node_id = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)
    rows = await session.execute(select(NodeTransport).where(NodeTransport.node_id == node_id))
    only = next(iter(rows.scalars().unique()))
    assert (
        await client.post(f"/api/transports/{only.id}/state", json={"enabled": False})
    ).status_code == 200

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    said = refused.json()["error"]["message"]
    assert handed.removals == 1, "the host was not even asked whether it held any"
    assert apply.NOTHING_CHANGED_ON_THE_NODE in said, said
    assert apply.DELIVERY_TAKEN_BACK not in said, (
        f"the operator is told material was removed from a host that held none: {said}"
    )


async def test_a_refused_apply_that_could_not_reach_the_host_says_so(
    client, session, uri_transport: str, handed: Handed, monkeypatch
) -> None:
    """And the third outcome, which is the one that leaves something behind.

    The refusal itself is unchanged — a node with nothing enabled is not a failed node,
    whatever the host did — but "nothing on the node was changed" is now the whole of
    what this control plane can say about a box it could not dial, and the material it
    went there to take back is still sitting on it.
    """

    async def remove_delivery(connection) -> bool:
        handed.removals += 1
        raise NodeUnreachable("the node did not answer")

    pinned(monkeypatch, node_delivery, "remove_delivery", remove_delivery)
    await add_user(client, "boris")
    node_id = await a_served_node(client, uri_transport, name="entry", address=FIRST_ADDRESS)
    rows = await session.execute(select(NodeTransport).where(NodeTransport.node_id == node_id))
    only = next(iter(rows.scalars().unique()))
    assert (
        await client.post(f"/api/transports/{only.id}/state", json={"enabled": False})
    ).status_code == 200

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    said = refused.json()["error"]["message"]
    assert apply.DELIVERY_MAY_STILL_BE_THERE.strip() in said, said
    assert apply.NOTHING_CHANGED_ON_THE_NODE in said, (
        f"nothing was changed on this host, and the refusal no longer says so: {said}"
    )
    node = await client.get(f"/api/nodes/{node_id}")
    assert node.json()["state"] == "active", (
        "a host that could not be reached to strip delivery material marked the node "
        "degraded — a node with nothing enabled is not a failed node (M18.1)"
    )


def test_every_refusal_carries_the_clause_the_removal_corrects() -> None:
    """The substitution is by text, so this is what keeps it from quietly doing nothing.

    ``_nothing_to_apply`` swaps one named clause for another. A refusal reworded so that
    it no longer contains the first one would go on being returned unchanged — telling an
    operator nothing on the node was changed, on the host this control plane has just
    stripped — and every assertion about the other two outcomes would stay green.
    """
    for refusal in (
        apply.NOTHING_TO_APPLY_YET,
        apply.NOTHING_LEFT_TO_APPLY,
        apply.NOTHING_LEFT_TO_APPLY_UNPUSHED,
    ):
        assert apply.NOTHING_CHANGED_ON_THE_NODE in refusal, refusal
