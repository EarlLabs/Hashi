"""A node behind what this panel would give it is said, on every surface — M26, then M32.

WHAT: that the surfaces an operator meets around adding somebody — the Users screen, the
      dialog that hands their link over, and the same dialog opened later — say that a
      serving node is not running what this panel would give it; and that all of them go
      quiet once the fleet has been applied.
WHY:  M26's first walk added ``acc-user`` and fetched ``…/sub/<token>?format=client-config-
      file``. What came back was complete and correct while on the host ``awg show``
      listed no peers; only a second apply put the peer there, and no screen had asked for
      it. M26 answered with a sentence. On 2026-10-03 the owner read past it — a grey
      paragraph under the link — and imported a link that timed out, which is M32: an add
      now applies the nodes itself (``services/onboarding.py``), and a node still behind is
      said as one block with an Apply button (``panel/not_pushed.html``).
HOW:  the shared ``accepting_nodes`` harness, so an apply really succeeds and the node
      really is in sync before the user arrives. SINCE M32 the user who leaves the node
      behind is registered through the database half of an add only
      (``a_user_no_node_was_told_about``): an add through the API or the panel applies, so
      it no longer leaves a node behind — which is what
      ``test_adding_a_user_reaches_the_nodes.py`` holds — and the state this file is about
      is now reached by everything an apply has not followed yet. The SENTENCE asserted is
      ``console.NOT_PUSHED``'s, read off the constant, so a rewording is one place.
"""

from control.app.services import console, nodes

from .conftest import GENERATED_SSH_KEY, a_user_no_node_was_told_about

# RFC 5737 documentation address, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.41"

# The other standing note on the same screen, asserted as ABSENT where this one belongs.
# The walk's finding is not that nothing was on screen — it is that what was on screen was
# about the opposite thing.
THE_OTHER_NOTE = "Withdrawn access is not confirmed"

# What every surface says about a node behind, since M32 — the short line of the one block.
BEHIND = "leaf-acc is still on the old configuration: your changes have not reached it."


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
    assert console.not_pushed(behind) is None


async def test_a_user_nobody_pushed_takes_the_node_out_of_in_sync(
    client, session, reality_params, accepting_nodes
) -> None:
    """The fact the surfaces are composed from, asserted where it is measured.

    A user granted material on a serving node changes what this panel would push to it —
    that is what a granted credential IS — so until something applies it the node's own
    config cell stops reading ``in sync``. Since M32 the add applies it; the database half
    on its own is what still leaves this state behind.
    """
    node_id = await a_serving_node(client, reality_params)
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) == console.IN_SYNC

    await a_user_no_node_was_told_about(session, "acc-user")

    session.expire_all()
    node = await nodes.get_node(session, node_id)
    assert await console.drift_of(session, node) != console.IN_SYNC, (
        "a user was granted material on this node and the panel still calls it in sync"
    )
    assert await console.nodes_missing_what_they_would_be_given(session) == [
        console.BehindNode(id=node_id, name="leaf-acc")
    ]


async def test_the_dialog_that_hands_the_link_over_says_it_will_not_carry_yet(
    client, session, reality_params, accepting_nodes
) -> None:
    """The moment the promise is delivered — the dialog opened on a user nobody pushed.

    Red against M26's dialog in the way that matters: the sentence was there, in grey,
    under the link. Since M32 it is the block, ABOVE the link, with a button that applies
    the node from inside the dialog (``/panel/reach``) rather than one that sends the
    operator to another screen and closes the dialog holding the link.
    """
    node_id = await a_serving_node(client, reality_params)
    user_id = await a_user_no_node_was_told_about(session, "acc-user")

    dialog = await client.get(f"/panel/users/{user_id}/subscription")

    assert dialog.status_code == 200, dialog.text
    said = " ".join(dialog.text.split())
    assert "copy link" in said, "this is no longer the dialog that hands the link over"
    assert BEHIND in said, said
    assert said.index(BEHIND) < said.index("copy link"), (
        "the warning is under the link again, where the owner did not see it"
    )
    assert 'hx-post="/panel/reach"' in said and f'value="{node_id}"' in said, (
        "the block in the dialog has no button applying the node it names"
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

    SOMEBODY IS REVOKED FIRST since M26's fix round 5, which is what makes the withdrawal
    note true of this fleet at all: it is about access taken away, and a panel with no
    revoked user has nobody it could be about (the test below). The revocation's own
    fan-out applies the node, so the user added afterwards is what leaves it behind.
    """
    await a_serving_node(client, reality_params)
    gone = await client.post("/api/users", json={"nickname": "gone-user"})
    assert gone.status_code == 201, gone.text
    revoked = await client.post(f"/api/users/{gone.json()['id']}/revoke")
    assert revoked.status_code == 200, revoked.text
    await a_user_no_node_was_told_about(session, "acc-user")

    table = await client.get("/panel/users/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert BEHIND in said, said
    assert THE_OTHER_NOTE in said, (
        "the withdrawal note has gone from a fleet it is still true of — this milestone "
        "adds a sentence beside it and takes none away"
    )


async def test_no_withdrawal_note_when_nobody_was_withdrawn(
    client, session, reality_params, accepting_nodes
) -> None:
    """Walk 4's low finding: the note fired with ZERO revoked users.

    Three walks tripped on it. The node is behind — a user was added since its last apply
    — and that is all the old condition asked; but the note is about access WITHDRAWN and
    not confirmed gone, and on a panel where nobody has been withdrawn it is a warning
    about nobody. The added-user sentence, which IS about this fleet, stays.

    Red on the commit before fix round 5: the note was on this screen.
    """
    await a_serving_node(client, reality_params)
    await a_user_no_node_was_told_about(session, "acc-user")

    table = await client.get("/panel/users/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert BEHIND in said, said
    assert THE_OTHER_NOTE not in said, (
        "the Users screen warns about withdrawn access on a panel where nobody's access "
        "was withdrawn"
    )


async def test_the_link_dialog_opened_later_asks_the_question_again(
    client, session, reality_params, accepting_nodes
) -> None:
    """A link shown an hour later is a link to a fleet that may have moved since."""
    node_id = await a_serving_node(client, reality_params)
    user_id = await a_user_no_node_was_told_about(session, "acc-user")
    first = await client.get(f"/panel/users/{user_id}/subscription")
    assert BEHIND in " ".join(first.text.split()), first.text

    # Somebody applies the node from elsewhere; the same dialog, opened again, reads anew.
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    dialog = await client.get(f"/panel/users/{user_id}/subscription")

    assert dialog.status_code == 200, dialog.text
    assert BEHIND not in " ".join(dialog.text.split()), dialog.text


async def test_applying_afterwards_takes_the_sentence_away_everywhere(
    client, session, reality_params, accepting_nodes
) -> None:
    """The second apply the walk had to work out for itself, and what it settles.

    Every surface goes quiet together, because all three read one answer. A sentence that
    survived the press that fixes it would be the same defect as one that never appeared.
    """
    node_id = await a_serving_node(client, reality_params)
    user_id = await a_user_no_node_was_told_about(session, "acc-user")

    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text

    session.expire_all()
    assert await console.nodes_missing_what_they_would_be_given(session) == []
    for response in (
        await client.get("/panel/users/table"),
        await client.get("/panel/nodes/table"),
        await client.get("/panel/overview/body"),
        await client.get(f"/panel/users/{user_id}/subscription"),
    ):
        assert BEHIND not in " ".join(response.text.split()), response.text
