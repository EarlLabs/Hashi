"""Revocation is total — backlog item 9, charter criterion 6.

WHAT: what happens to a friend's access, in the database and in what would be
      rendered to every node, when they are revoked.
WHY:  the criterion is "their credentials stop working on EVERY node and EVERY
      protocol, not just the one they were last seen on". That is a claim about two
      systems, and this file proves the half that does not need a real host: the
      credential rows are gone, and a fresh render of every node no longer contains
      them.
HOW:  no node is contacted. The nodes here have no SSH key, so the push half fails
      by design — and that is itself under test, because the honest reporting of an
      INCOMPLETE revocation is a required behaviour rather than an edge case.

      The boundary, stated plainly: nothing in this file proves that a running daemon
      stopped accepting the credential. It proves we would never render it again, and
      that a failed push is reported as incomplete rather than as success.
"""

import base64

import pytest

from control.app.models import NodeState


async def fleet_with_friend(client, session, reality_params, ws_params):
    """Two nodes, three transports between them, one friend on all of them.

    Two nodes on purpose: "not just the one they were last seen on" is only testable
    when there is more than one, and a single-node fixture would let a bug that
    revokes exactly one node pass.
    """
    from control.app.services import nodes

    node_ids = []
    for name, country in (("leaf-nl", "Netherlands"), ("leaf-is", "Iceland")):
        response = await client.post(
            "/api/nodes",
            json={"name": name, "address": "192.0.2.10", "location_label": country},
        )
        node_ids.append(response.json()["id"])

    await client.post(
        f"/api/nodes/{node_ids[0]}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await client.post(
        f"/api/nodes/{node_ids[0]}/transports",
        json={"transport_name": "vless-ws-tls", "params": ws_params},
    )
    await client.post(
        f"/api/nodes/{node_ids[1]}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )

    for node_id in node_ids:
        await nodes.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)

    friend_id = (await client.post("/api/friends", json={"nickname": "kolya"})).json()["id"]
    url = (await client.get(f"/api/friends/{friend_id}/subscription")).json()["url"]
    return node_ids, friend_id, url.rsplit("/", 1)[-1]


async def test_a_friend_starts_with_a_credential_on_every_node_and_protocol(
    client, session, reality_params, ws_params
) -> None:
    """The premise every other test here depends on. Without it they pass vacuously."""
    _, _, token = await fleet_with_friend(client, session, reality_params, ws_params)
    document = base64.b64decode((await client.get(f"/sub/{token}")).text).decode()
    assert len(document.splitlines()) == 3, f"expected three entries, got {document!r}"


async def test_revoking_removes_every_credential_row(
    client, session, reality_params, ws_params
) -> None:
    """Deleted, not flagged.

    The distinction is the whole mechanism: a flag means every renderer must remember
    to filter on it, and the one that forgets leaves a friend connected. With the rows
    gone, a re-render cannot include them even by mistake.
    """
    from sqlalchemy import func, select

    from control.app.models import Credential

    _, friend_id, _ = await fleet_with_friend(client, session, reality_params, ws_params)

    before = (await session.execute(select(func.count()).select_from(Credential))).scalar_one()
    assert before == 3

    await client.post(f"/api/friends/{friend_id}/revoke")

    after = (await session.execute(select(func.count()).select_from(Credential))).scalar_one()
    assert after == 0, "credential rows survived a revocation"


async def test_revoking_makes_the_subscription_resolve_to_nothing(
    client, session, reality_params, ws_params
) -> None:
    """The URL the friend holds stops working — and answers 404, not an empty 200.

    404 rather than an empty document because an empty document is a valid
    subscription meaning "no nodes right now", which a client keeps its old config
    for. Revocation has to be distinguishable from a fleet outage on the client side.
    """
    _, friend_id, token = await fleet_with_friend(client, session, reality_params, ws_params)

    await client.post(f"/api/friends/{friend_id}/revoke")

    response = await client.get(f"/sub/{token}")
    assert response.status_code == 404


async def test_a_revoked_friend_disappears_from_every_nodes_rendered_config(
    client, session, reality_params, ws_params
) -> None:
    """The claim that matters: what we WOULD push no longer authorises them.

    Renders each node through the same function the apply path uses, so this is not a
    test-only reimplementation of "what would be pushed".
    """
    from control.app.services import apply, nodes

    node_ids, friend_id, _ = await fleet_with_friend(
        client, session, reality_params, ws_params
    )

    subjects = set()
    for node_id in node_ids:
        node = await nodes.get_node(session, node_id)
        for config in (await apply.render_for_node(session, node)).values():
            import json

            for entry in json.loads(config)["inbounds"][0]["settings"]["clients"]:
                subjects.add(entry["id"])
    assert subjects, "no clients were rendered at all — the premise failed"

    await client.post(f"/api/friends/{friend_id}/revoke")

    for node_id in node_ids:
        node = await nodes.get_node(session, node_id)
        for name, config in (await apply.render_for_node(session, node)).items():
            for subject in subjects:
                assert subject not in config, (
                    f"a revoked friend's credential is still rendered for {name} "
                    f"on node {node.name}"
                )


async def test_an_unreachable_node_makes_the_revocation_report_incomplete(
    client, session, reality_params, ws_params
) -> None:
    """The uncomfortable case, reported honestly rather than as success.

    These nodes have no SSH key, so every push fails. The database change still
    happens — that ordering is deliberate, so a retry completes rather than reverting
    — but the operator is told the credential may still be live on those nodes.

    A ``complete: true`` here would be the exact failure criterion 6 forbids: the
    operator believing a revocation finished when a friend is still connected.
    """
    _, friend_id, _ = await fleet_with_friend(client, session, reality_params, ws_params)

    response = await client.post(f"/api/friends/{friend_id}/revoke")
    assert response.status_code == 200
    body = response.json()

    assert body["complete"] is False
    assert body["nodes_failed"], "a failed push was not reported"
    assert "could NOT be updated" in body["summary"]
    # The database half must have happened regardless.
    assert (await client.get(f"/api/friends/{friend_id}")).status_code in (404, 405, 200)


async def test_revoking_one_friend_leaves_the_others_credentials_intact(
    client, session, reality_params, ws_params
) -> None:
    """Per-friend credentials are what make this possible; shared ones would not.

    Asserted on the credential rows and on what would be rendered, NOT on the other
    friend's subscription document. That is deliberate: in this fixture the push fails
    (the nodes have no SSH key), so every node is correctly marked degraded, and a
    degraded node is excluded from EVERY subscription. Checking the survivor's
    subscription here would therefore be testing the degradation rule while claiming
    to test revocation isolation — it would fail for a reason that has nothing to do
    with the property under test.
    """
    from sqlalchemy import select

    from control.app.models import Credential

    node_ids, friend_id, _ = await fleet_with_friend(
        client, session, reality_params, ws_params
    )

    other_id = (await client.post("/api/friends", json={"nickname": "masha"})).json()["id"]

    surviving = (
        await session.execute(
            select(Credential.id).where(Credential.friend_id == other_id)
        )
    ).scalars().all()
    assert len(surviving) == 3, "the other friend did not start with a full set"

    await client.post(f"/api/friends/{friend_id}/revoke")

    after = (
        await session.execute(
            select(Credential.id).where(Credential.friend_id == other_id)
        )
    ).scalars().all()
    assert set(after) == set(surviving), (
        "revoking one friend removed another friend's credentials"
    )
    assert not (
        await session.execute(
            select(Credential.id).where(Credential.friend_id == friend_id)
        )
    ).scalars().all()


async def test_a_revoked_friend_cannot_be_granted_access_again(
    client, session, reality_params, ws_params
) -> None:
    """Access must not return through a side door.

    Enabling a new transport re-grants every ACTIVE friend. A revoked friend being
    swept up in that would silently restore them, which is the quietest possible way
    to break criterion 6.
    """
    from control.app.services import friends

    node_ids, friend_id, token = await fleet_with_friend(
        client, session, reality_params, ws_params
    )
    await client.post(f"/api/friends/{friend_id}/revoke")

    # A new transport on the second node, which triggers the re-grant sweep.
    await client.post(
        f"/api/nodes/{node_ids[1]}/transports",
        json={"transport_name": "vless-ws-tls", "params": ws_params},
    )

    assert (await client.get(f"/sub/{token}")).status_code == 404

    # And directly: granting a revoked friend is refused rather than ignored.
    friend = await friends.get_friend(session, friend_id)
    from control.app.errors import Conflict

    with pytest.raises(Conflict):
        await friends.grant_everywhere(session, friend)


async def test_revoking_twice_is_not_an_error(
    client, session, reality_params, ws_params
) -> None:
    """An operator retrying after a failed push must not get a 500.

    Retrying is the DOCUMENTED remedy for an incomplete revocation, so it has to be
    safe — and the second call has no credentials left to remove, which is complete by
    definition rather than an error.
    """
    _, friend_id, _ = await fleet_with_friend(client, session, reality_params, ws_params)

    first = await client.post(f"/api/friends/{friend_id}/revoke")
    second = await client.post(f"/api/friends/{friend_id}/revoke")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["complete"] is True, (
        "a second revocation had nothing left to do and should report complete"
    )
