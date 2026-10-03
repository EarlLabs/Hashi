"""Adding a user reaches the nodes by itself — M32.

WHAT: that an add — through the API, through the API's batch, and through the panel's
      dialog and the per-node requests it makes — applies every serving node the new
      users were given, each node once; that a node it could not reach is named with a
      reason a person can act on and a retry, and stays in every user's link; that the
      not-applied block on every screen applies exactly the node it names; and that a
      fan-out never takes a serving node out of service over a record that dialled nothing.
WHY:  on 2026-10-03 the owner added a user, imported the link into a phone client and got
      a timeout: the user's credential was not on the entry, because adding a user wrote
      only to the database while revoking one already applied every node by itself. The
      panel did say so — in a grey paragraph under the link, which the owner did not see.
HOW:  ``accepting_nodes`` for a node where every step of an apply works, wrapped by
      ``some_hosts_unreachable`` so a chosen address raises ``NodeUnreachable`` before any
      session opens — the shape of a host the control plane cannot reach. Restarts are
      counted per host to hold "each node once". Every test here is red on the commit
      before M32: the add touched no host, the API answered no per-node outcome, there
      was no batch, no ``/panel/reach`` and no block.
"""

import pytest

from control.app.models import AuditAction, AuditEntry, NodeState
from control.app.services import apply, console, nodes
from edge.bootstrap.ssh import NodeUnreachable

from .conftest import GENERATED_SSH_KEY, AcceptingNode, a_user_no_node_was_told_about

# RFC 5737 documentation addresses — the connection is replaced, nothing is dialled. IP
# literals, so neither node is a delivery host in this suite (a host registered by name
# would be, with ``delivery_certificate`` configured), which would be a different apply.
ENTRY_ADDRESS = "192.0.2.71"
LEAF_ADDRESS = "192.0.2.72"


class UnreachableNode:
    """A host the control plane cannot open a session to: refused before anything is sent."""

    learned_host_key = None

    async def __aenter__(self):
        raise NodeUnreachable("could not connect to the node: connection timed out")

    async def __aexit__(self, *_exc_info) -> bool:
        return False


@pytest.fixture
def some_hosts_unreachable(accepting_nodes, monkeypatch):
    """``accepting_nodes``, except for the addresses a test puts in the returned set.

    Also counts the sessions opened per address — one apply opens one — which is how
    "each node is applied once" is held without reading the apply's internals.
    """
    down: set[str] = set()
    opened: dict[str, int] = {}

    def connection_for(target):
        opened[target.host] = opened.get(target.host, 0) + 1
        return UnreachableNode() if target.host in down else AcceptingNode()

    monkeypatch.setattr(apply, "NodeConnection", connection_for)
    return down, opened


async def a_serving_node(client, reality_params, *, name: str, address: str) -> str:
    """One node with one transport, applied and in service."""
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
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    return node_id


async def in_sync(session, node_id: str) -> bool:
    session.expire_all()
    return await console.drift_of(session, await nodes.get_node(session, node_id)) == (
        console.IN_SYNC
    )


async def link_names(client, anonymous, user_id: str) -> str:
    """The user's subscription document, as text — what their app imports."""
    import base64

    url = (await client.get(f"/api/users/{user_id}/subscription")).json()["url"]
    fetched = await anonymous.get("/sub/" + url.rsplit("/", 1)[-1])
    assert fetched.status_code == 200, fetched.text
    return base64.b64decode(fetched.content).decode()


# --- the API ---------------------------------------------------------------------------


async def test_an_api_add_applies_the_node_and_says_so(
    client, session, reality_params, some_hosts_unreachable
) -> None:
    """The owner's finding, through the API: the node holds the user once the add returns."""
    node_id = await a_serving_node(
        client, reality_params, name="entry-ru", address=ENTRY_ADDRESS
    )

    created = await client.post("/api/users", json={"nickname": "mira"})

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["nickname"] == "mira"
    assert body["complete"] is True, body
    assert body["nodes_updated"] == [node_id], body
    assert body["nodes_failed"] == {}, body
    assert "pushed to every node" in body["summary"], body
    assert await in_sync(session, node_id), "the add returned and the node is still behind"


async def test_a_node_the_add_cannot_reach_is_named_and_stays_in_every_link(
    client, anonymous, session, reality_params, some_hosts_unreachable
) -> None:
    """A failed node is reported per node, and is not taken out of anybody's link.

    The owner's rule of 2026-10-02 (a serving host an apply could not reach stays in
    users' links), held on the path M32 adds: the add's own fan-out.
    """
    down, _ = some_hosts_unreachable
    entry = await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    leaf = await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    before = (await client.post("/api/users", json={"nickname": "old-user"})).json()
    down.add(LEAF_ADDRESS)

    created = await client.post("/api/users", json={"nickname": "mira"})

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["complete"] is False, body
    assert body["nodes_updated"] == [entry], body
    assert list(body["nodes_failed"]) == [leaf], body
    assert "'leaf-ams'" in body["summary"] and "could not be reached" in body["summary"]
    session.expire_all()
    assert (await nodes.get_node(session, leaf)).state == NodeState.ACTIVE
    assert await in_sync(session, entry)
    # Both nodes are still in the old user's link and in the new one's.
    for user_id in (before["id"], body["id"]):
        document = await link_names(client, anonymous, user_id)
        assert document.count("vless://") == 2, document


async def test_a_batch_applies_each_node_once_for_everybody(
    client, session, reality_params, some_hosts_unreachable
) -> None:
    """Five people, one apply per node — every apply drops whoever is connected there."""
    _, opened = some_hosts_unreachable
    entry = await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    leaf = await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    opened.clear()

    added = await client.post(
        "/api/users/batch", json={"nicknames": ["a1", "a2", "a3", "a4", "a5"]}
    )

    assert added.status_code == 201, added.text
    body = added.json()
    assert [user["nickname"] for user in body["users"]] == ["a1", "a2", "a3", "a4", "a5"]
    assert sorted(body["nodes_updated"]) == sorted([entry, leaf]), body
    assert body["complete"] is True, body
    assert opened == {ENTRY_ADDRESS: 1, LEAF_ADDRESS: 1}, opened
    assert await in_sync(session, entry) and await in_sync(session, leaf)
    entries = (await session.execute(
        AuditEntry.__table__.select().where(
            AuditEntry.__table__.c.action == AuditAction.USER_ADDED
        )
    )).all()
    assert len(entries) == 5, "one trail entry per person added"


async def test_a_batch_with_one_refused_name_writes_nothing(
    client, reality_params, some_hosts_unreachable
) -> None:
    """All or none: a refusal on one line is not "lines one and two were added"."""
    _, opened = some_hosts_unreachable
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    await client.post("/api/users", json={"nickname": "taken"})
    opened.clear()

    refused = await client.post(
        "/api/users/batch", json={"nicknames": ["new-one", "taken", "new-two"]}
    )

    assert refused.status_code == 409, refused.text
    assert "'taken'" in refused.text
    assert [user["nickname"] for user in (await client.get("/api/users")).json()] == [
        "taken"
    ]
    assert opened == {}, "a refused add dialled a node"


# --- the panel -------------------------------------------------------------------------


async def test_the_panel_add_hands_the_links_over_and_starts_reaching_the_nodes(
    client, session, reality_params, some_hosts_unreachable
) -> None:
    """One per line; the links come back at once and the first node asks for itself."""
    entry = await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    leaf = await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)

    added = await client.post("/panel/users", data={"nicknames": "mira\n\n  kolya  \n"})

    assert added.status_code == 200, added.text
    said = " ".join(added.text.split())
    assert "2 users added" in said
    assert said.count("copy link") == 2, "each person's link is handed over"
    # The node rows: the first asks for itself on load, carrying every node still to do.
    assert 'hx-post="/panel/reach" hx-trigger="load"' in said
    assert f'name="node" value="{entry}"' in said and f'name="node" value="{leaf}"' in said
    assert "applying" in said and "then leaf-ams" in said
    # And until the rows have run, the honest line says the link does not work yet.
    assert "It does not work through entry-ru, leaf-ams yet" in said, said
    assert not await in_sync(session, entry), "this request was meant to push nothing"
    names = sorted(user["nickname"] for user in (await client.get("/api/users")).json())
    assert names == ["kolya", "mira"]


async def test_each_reach_applies_one_node_and_brings_the_next(
    client, session, reality_params, some_hosts_unreachable
) -> None:
    entry = await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    leaf = await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    user_id = await a_user_no_node_was_told_about(session, "mira")

    first = await client.post("/panel/reach", data={"node": [entry, leaf], "user": [user_id]})

    assert first.status_code == 200, first.text
    said = " ".join(first.text.split())
    assert "entry-ru</strong> — took the new configuration" in said, said
    assert 'hx-trigger="load"' in said and f'value="{leaf}"' in said, "no next node"
    assert "Their link works through entry-ru now." in said
    assert "does not work through leaf-ams yet" in said
    assert "nodes-changed" in first.headers.get("HX-Trigger", "")
    assert await in_sync(session, entry) and not await in_sync(session, leaf)

    last = await client.post("/panel/reach", data={"node": [leaf], "user": [user_id]})

    said = " ".join(last.text.split())
    assert 'hx-trigger="load"' not in said, "the chain did not end"
    assert "Their link works through entry-ru, leaf-ams now." in said, said
    assert await in_sync(session, leaf)


async def test_a_node_that_fails_is_named_with_a_reason_and_a_retry(
    client, session, reality_params, some_hosts_unreachable
) -> None:
    """The row names the node and what to do, offers a retry, and carries no raw text."""
    down, _ = some_hosts_unreachable
    leaf = await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    user_id = await a_user_no_node_was_told_about(session, "mira")
    down.add(LEAF_ADDRESS)

    failed = await client.post("/panel/reach", data={"node": [leaf], "user": [user_id]})

    assert failed.status_code == 200, failed.text
    said = " ".join(failed.text.split())
    assert "reach-failed" in said
    assert "leaf-ams" in said and "could not be reached" in said, said
    assert ">retry<" in said.replace(" ", "") or "retry</span>" in said
    assert LEAF_ADDRESS not in said, "the node's address reached the page"
    assert "connection timed out" not in said, "the failure's own text reached the page"
    assert "does not work through leaf-ams yet" in said
    session.expire_all()
    assert (await nodes.get_node(session, leaf)).state == NodeState.ACTIVE

    # The retry, once the host answers again, is the same request for that one node.
    down.clear()
    retried = await client.post("/panel/reach", data={"node": [leaf], "user": [user_id]})
    said = " ".join(retried.text.split())
    assert "took the new configuration" in said and "works through leaf-ams now" in said


# --- the block -------------------------------------------------------------------------


async def test_the_not_applied_block_is_on_every_screen_with_a_button_for_its_node(
    client, session, reality_params, some_hosts_unreachable
) -> None:
    """One short coloured line, an Apply button per node, the long text behind details."""
    node_id = await a_serving_node(
        client, reality_params, name="entry-ru", address=ENTRY_ADDRESS
    )
    user_id = await a_user_no_node_was_told_about(session, "mira")
    short = console.NOT_PUSHED.format(nodes="entry-ru", is_="is", it="it")

    screens = {
        "overview": await client.get("/panel/overview/body"),
        "users": await client.get("/panel/users/table"),
        "nodes": await client.get("/panel/nodes/table"),
    }
    for where, page in screens.items():
        said = " ".join(page.text.split())
        assert "banner-pending" in said, where
        assert short in said, where
        assert f'hx-post="/panel/nodes/{node_id}/apply"' in said, where
        assert "Apply entry-ru" in said, where
        assert "<summary>details</summary>" in said, where

    dialog = " ".join((await client.get(f"/panel/users/{user_id}/subscription")).text.split())
    assert short in dialog and "Apply entry-ru" in dialog
    assert 'hx-post="/panel/reach"' in dialog, "the dialog's button would close the dialog"

    # The screens' button applies exactly that node, and the block goes.
    pressed = await client.post(f"/panel/nodes/{node_id}/apply")
    assert pressed.status_code == 200, pressed.text
    assert short not in " ".join((await client.get("/panel/overview/body")).text.split())


async def test_the_screens_reread_the_block_when_a_node_changes(client) -> None:
    """The Overview and the Users table listen for ``nodes-changed`` since M32.

    Without it, an Apply pressed in the block answers with a toast and the block it was
    pressed in stays on screen saying the node is behind.
    """
    for path in ("/panel/overview/body", "/panel/users/table"):
        page = await client.get(path)
        assert "nodes-changed from:body" in page.text, path


# --- the fan-out never takes a serving node out over a record that dialled nothing -----


async def test_an_add_never_takes_a_serving_node_out_of_the_links(
    client, anonymous, session, reality_params, accepting_nodes
) -> None:
    """A serving node whose record cannot produce a session stays in service.

    Before M32 only revocation fanned out, and it degraded such a node; with adds applying
    too, the same branch would empty every user's link because somebody was added.
    """
    node_id = await a_serving_node(
        client, reality_params, name="entry-ru", address=ENTRY_ADDRESS
    )
    old = (await client.post("/api/users", json={"nickname": "old-user"})).json()["id"]
    # The record loses the key it was applied with — the shape of a node made serving by
    # hand. Nothing on the host changes.
    node = await nodes.get_node(session, node_id)
    node.ssh_private_key = None
    await session.commit()

    created = await client.post("/api/users", json={"nickname": "mira"})
    revoked = await client.post(f"/api/users/{old}/revoke")

    assert created.status_code == 201 and created.json()["complete"] is False
    assert revoked.status_code == 200 and revoked.json()["complete"] is False
    session.expire_all()
    assert (await nodes.get_node(session, node_id)).state == NodeState.ACTIVE
    assert "vless://" in await link_names(client, anonymous, created.json()["id"])
