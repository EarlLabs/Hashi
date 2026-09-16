"""Adding a user does not reach a node, and the panel says so — M26, first walk.

WHAT: that the three surfaces an operator meets while adding somebody — the Users
      screen, the dialog that hands their link over, and the same dialog opened later —
      say that the nodes are not yet holding what this panel would give them; and that
      all three go quiet once the fleet has been applied.
WHY:  the walk added ``acc-friend`` and fetched ``…/sub/<token>?format=client-config-
      file``. What came back was complete and correct — ``Address = 10.77.13.2/24``, the
      node's real public key — while on the host ``grep -c "\\[Peer\\]"
      /opt/hashi/conf/amneziawg.conf`` was 0 and ``awg show`` listed no peers. That
      friend's client would have handshaked into nothing. Only a second apply, three
      minutes later by the audit trail, put the peer on the node and made the traffic
      flow, and no screen had asked for it: the Users screen's one standing note is about
      access WITHDRAWN and not confirmed gone, which is the other direction entirely.
HOW:  the shared ``accepting_nodes`` harness, so an apply really succeeds and the node
      really is in sync before the user arrives — otherwise the sentence under test would
      be true for a reason that has nothing to do with the user. Both directions: the
      accept case applies again and asserts every surface goes quiet, because a panel
      that always warns is a panel nobody reads on the day it matters.
"""

from control.app.services import console, nodes

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.41"

# The other standing note on the same screen, asserted as ABSENT where this one belongs.
# The walk's finding is not that nothing was on screen — it is that what was on screen was
# about the opposite thing.
THE_OTHER_NOTE = "Withdrawn access is not confirmed"


async def a_serving_node(client, reality_params, *, name: str = "leaf-acc") -> str:
    """One node, applied and in service, with nobody on it yet."""
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
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    return node_id


async def test_a_node_holding_everything_is_not_warned_about(
    client, session, reality_params, accepting_nodes
) -> None:
    """The accept direction, first: a fleet in sync says nothing at all.

    Without it every assertion below could pass on a panel that hedges permanently, which
    is the same silence one step further on.
    """
    await a_serving_node(client, reality_params)

    behind = await console.nodes_missing_what_they_would_be_given(session)

    assert behind == []
    assert console.material_doubt(behind) is None


async def test_adding_a_user_takes_the_node_out_of_in_sync(
    client, session, reality_params, accepting_nodes
) -> None:
    """The fact the two screens are composed from, asserted where it is measured.

    Adding a user changes what this panel would push to every serving node — that is what
    a granted credential IS — so the node's own config cell stops reading ``in sync`` the
    moment the user exists. That reading was already right; nothing carried it to the
    person who had just pressed the button.
    """
    node_id = await a_serving_node(client, reality_params)
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) == console.IN_SYNC

    created = await client.post("/api/friends", json={"nickname": "acc-friend"})
    assert created.status_code == 201, created.text

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) != console.IN_SYNC, (
        "a user was granted material on this node and the panel still calls it in sync"
    )
    assert await console.nodes_missing_what_they_would_be_given(session) == ["leaf-acc"]


async def test_the_dialog_that_hands_the_link_over_says_it_will_not_carry_yet(
    client, session, reality_params, accepting_nodes
) -> None:
    """The exchange the walk actually made, and the moment the promise is delivered.

    Red against the previous commit: the response to "add user" is the subscription
    dialog, and it said the link "keeps working when nodes or protocols change" and
    nothing whatever about the node that had never heard of this person.
    """
    await a_serving_node(client, reality_params)

    added = await client.post("/panel/friends", data={"nickname": "acc-friend"})

    assert added.status_code == 200, added.text
    said = " ".join(added.text.split())
    assert "copy link" in said, "this is no longer the dialog that hands the link over"
    assert "A user added here is not on leaf-acc yet" in said, said
    assert "Apply it on the Nodes screen" in said, (
        "the sentence does not end where the press that fixes it is"
    )


async def test_the_users_screen_says_it_too_and_not_only_about_a_withdrawal(
    client, session, reality_params, accepting_nodes
) -> None:
    """The screen the operator lands on afterwards, and the note that was already there.

    The finding is not that the screen was silent — it carried M23's standing note about
    withdrawn access being unconfirmable on exactly these hosts. It is that a reader who
    had just added somebody had no reason to read that note as being about them: it is
    about access taken AWAY and not confirmed gone, which is the other direction.

    So the assertion is that this screen now says BOTH, and that the added-user sentence
    is a sentence of its own rather than a clause spliced into the other. The two are
    about one fact — a host that is not running what we would give it — and about two
    different consequences of it, and M23's own reasoning for splitting its pair applies
    unchanged: one sentence covering both would have to drop the instruction from one of
    them.
    """
    await a_serving_node(client, reality_params)
    created = await client.post("/api/friends", json={"nickname": "acc-friend"})
    assert created.status_code == 201, created.text

    table = await client.get("/panel/friends/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert "A user added here is not on leaf-acc yet" in said, said
    assert THE_OTHER_NOTE in said, (
        "the withdrawal note has gone from a fleet it is still true of — this milestone "
        "adds a sentence beside it and takes none away"
    )


async def test_the_link_dialog_opened_later_asks_the_question_again(
    client, session, reality_params, accepting_nodes
) -> None:
    """A link shown an hour later is a link to a fleet that may have moved since."""
    await a_serving_node(client, reality_params)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "acc-friend"})
    ).json()["id"]

    dialog = await client.get(f"/panel/friends/{friend_id}/subscription")

    assert dialog.status_code == 200, dialog.text
    assert "A user added here is not on leaf-acc yet" in " ".join(
        dialog.text.split()
    ), dialog.text


async def test_applying_afterwards_takes_the_sentence_away_everywhere(
    client, session, reality_params, accepting_nodes
) -> None:
    """The second apply the walk had to work out for itself, and what it settles.

    Every surface goes quiet together, because all three read one answer. A sentence that
    survived the press that fixes it would be the same defect as one that never appeared.
    """
    node_id = await a_serving_node(client, reality_params)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "acc-friend"})
    ).json()["id"]

    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text

    session.expire_all()
    assert await console.nodes_missing_what_they_would_be_given(session) == []
    for response in (
        await client.get("/panel/friends/table"),
        await client.get(f"/panel/friends/{friend_id}/subscription"),
    ):
        assert "A user added here is not on" not in " ".join(
            response.text.split()
        ), response.text
