"""The Users screen stops saying "no access" over a tunnel that is carrying — M23.

WHAT: what the users table says about somebody whose access was withdrawn here while a
      node could not be updated.
WHY:  measured on the owner's real leaf on 2026-09-15, round 2 of the walk. A revoke was
      pressed, the push to one node failed, and the banner said so correctly — *"access
      withdrawn in the database and on 0 node(s), but 1 node(s) could NOT be updated"* —
      and then went away with the next click. The row the operator came back to read
      ``revoked`` and ``no access``, and at that moment, from inside that person's tunnel,
      ``curl`` answered ``ip=45.151.69.107`` with a handshake 112 seconds old.

      "No access" is a claim about a host this control plane may not have been able to
      reach. What it can always say is what the OPERATOR did, and — separately, from the
      Nodes screen's own readings — which hosts it cannot confirm have stopped serving
      what they were last given.
HOW:  the shared ``accepting_nodes`` harness (``conftest.py``) for the nodes that take a
      push, and one pinned ``restart`` that stops answering for the revocation's own
      fan-out. Nothing here dials a host, and nothing here proves a daemon reloaded.

      THE SENTENCE IS ABOUT THE FLEET AND NOT ABOUT A PERSON, which is forced rather than
      chosen: a revocation DELETES the credential rows, so nothing afterwards records
      which nodes that person was on. See ``console.WITHDRAWAL_UNCONFIRMED``.
"""

import pytest

from control.app.models import NodeState
from control.app.services import console, nodes
from edge.bootstrap import NodeUnreachable, node_stack

from .conftest import GENERATED_SSH_KEY, pinned

# RFC 5737 documentation address, as everywhere in this zone.
NODE_ADDRESS = "192.0.2.75"

# The claim that was measured false. Asserted as absent by its own words, because it is
# the words an operator read.
THE_OLD_CLAIM = "no access"


async def a_reachable_node(client, *, name: str) -> str:
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


async def a_served_fleet(client, reality_params, *, names=("leaf-nl", "leaf-is")) -> list[str]:
    """Nodes that have really been pushed to and are in sync, with one user on them."""
    node_ids = []
    for name in names:
        node_id = await a_reachable_node(client, name=name)
        enabled = await client.post(
            f"/api/nodes/{node_id}/transports",
            json={"transport_name": "vless-reality", "params": reality_params},
        )
        assert enabled.status_code == 201, enabled.text
        applied = await client.post(f"/api/nodes/{node_id}/apply")
        assert applied.status_code == 200, applied.text
        node_ids.append(node_id)

    created = await client.post("/api/friends", json={"nickname": "anna"})
    assert created.status_code == 201, created.text
    return node_ids


@pytest.fixture
def a_node_that_stops_answering(accepting_nodes, monkeypatch: pytest.MonkeyPatch):
    """Turn every later push into a node that cannot be reached.

    Installed by the test rather than by the fixture list, because the setup has to
    SUCCEED first: a node that was never pushed to is serving nobody and is deliberately
    not part of the doubt this screen reports.
    """

    def stop_answering() -> None:
        async def restart(connection) -> None:
            raise NodeUnreachable("the node did not answer")

        # Pinned against the double ``accepting_nodes`` already installed, which was
        # itself pinned against the real ``restart``.
        pinned(monkeypatch, node_stack, "restart", restart)

    return stop_answering


async def test_a_confirmed_fleet_says_only_what_the_operator_did(
    client, session, reality_params, accepting_nodes
) -> None:
    """The ordinary case: every host took the push, so there is nothing to hedge.

    The cell still stops claiming the person has no access — that claim is about a host —
    but no note appears, because a warning that is always on screen is one nobody reads on
    the day it means something.
    """
    await a_served_fleet(client, reality_params)
    friend_id = (await client.get("/api/friends")).json()[0]["id"]

    revoked = await client.post(f"/api/friends/{friend_id}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["complete"] is True, revoked.text

    table = await client.get("/panel/friends/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert console.ACCESS_WITHDRAWN in said, said
    assert THE_OLD_CLAIM not in said, said
    assert "Withdrawn access is not confirmed" not in said, (
        "a fleet that took every push is warning about hosts it did confirm"
    )


async def test_a_withdrawal_that_could_not_be_pushed_is_not_reported_as_no_access(
    client, session, reality_params, a_node_that_stops_answering
) -> None:
    """The finding, on the screen the operator returns to.

    Red against the previous commit: the row reads "no access" and the screen carries
    nothing at all about the node that kept the credential — the only true sentence was
    in a banner that had already gone.
    """
    node_ids = await a_served_fleet(client, reality_params)
    friend_id = (await client.get("/api/friends")).json()[0]["id"]
    a_node_that_stops_answering()

    revoked = await client.post(f"/api/friends/{friend_id}/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["complete"] is False, revoked.text

    table = await client.get("/panel/friends/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    assert THE_OLD_CLAIM not in said, (
        "the screen still says a person has no access while a host it could not update "
        "may still be serving them"
    )
    # AND THE CELL SAYS NOTHING AT ALL — M23, round 3. Round 2 replaced "no access" with
    # a sentence about what the operator did, which is always true of the database; the
    # walk then read it on the row of somebody who downloaded a megabyte through the real
    # leaf while it was on screen, directly under the note saying the withdrawal was not
    # confirmed. The cell was the sentence contradicting the note.
    assert console.ACCESS_WITHDRAWN not in said, (
        "the row still states the withdrawal while the note above it says that cannot be "
        "confirmed, so the screen contradicts itself about a tunnel that may be carrying"
    )
    assert "Withdrawn access is not confirmed" in said, said
    # It names the hosts, because that is the text the operator acts on — and sends them
    # to the one screen where the state is read and changed.
    session.expire_all()
    for node_id in node_ids:
        node = await nodes.get_node(session, node_id)
        assert node.state == NodeState.DEGRADED, node.state
        assert node.name in said, said
    assert "Nodes screen" in said, said


async def test_a_node_nothing_was_ever_pushed_to_raises_no_doubt(
    client, session, reality_params
) -> None:
    """A first-run panel carries no standing warning, which is what makes it readable.

    A node that has never been applied is serving nobody: it cannot be carrying a
    withdrawn credential, whatever state its record is in. Without this, every fleet with
    a draft or a failed first apply in it would show the note for ever, and the note would
    mean nothing on the day it was true.
    """
    node_id = await a_reachable_node(client, name="never-pushed")
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="never reached"
    )

    assert await console.unconfirmed_nodes(session) == []
    assert console.withdrawal_doubt([]) is None


async def retire(client, node_id: str) -> None:
    """Take a node out the way an operator does: the state endpoint, which allows it."""
    retired = await client.post(
        f"/api/nodes/{node_id}/state",
        json={"state": "retired", "detail": "the host is gone"},
    )
    assert retired.status_code == 200, retired.text


async def test_a_node_no_press_can_finish_is_not_sent_to_probe_and_apply(
    client, session, reality_params, accepting_nodes
) -> None:
    """The finding of M23's thirteenth round: one fix that landed on one surface of two.

    Round 12 taught the revoke dialog that a node the state machine will not put back into
    service cannot be finished from this panel. This banner went on saying the opposite
    about the same host — *"Probe it on the Nodes screen and apply it; that is where this
    state is read and the only place it changes"* — while both of those buttons answer
    that they refuse a node in that state. The banner appears exactly when it matters, so
    the sentence the operator acts on at the worst moment was the one that sent them
    nowhere.

    Both halves in one test, as round 12 wrote its own: the words, and then the two
    presses that say the words and the product still agree. Pressing them is the walk's
    own gesture.
    """
    node_ids = await a_served_fleet(client, reality_params, names=("old-leaf",))
    friend_id = (await client.get("/api/friends")).json()[0]["id"]
    await retire(client, node_ids[0])

    revoked = await client.post(f"/api/friends/{friend_id}/revoke")
    assert revoked.status_code == 200, revoked.text

    table = await client.get("/panel/friends/table")

    assert table.status_code == 200, table.text
    said = " ".join(table.text.split())
    # The doubt is still stated — that is the whole reason this banner exists.
    assert "Withdrawn access is not confirmed" in said, said
    assert "old-leaf" in said, said
    assert "no screen in this panel finishes it" in said, said
    # And the instruction that refuses is gone from it.
    assert "Probe it on the Nodes screen and apply it" not in said, (
        "the banner still sends the operator to two buttons that refuse this node"
    )

    # The gesture the old sentence asked for, on the two buttons it named — pressed on
    # the console, because the console is where the banner said they were.
    for button in ("probe", "apply"):
        pressed = await client.post(
            f"/panel/nodes/{node_ids[0]}/{button}", headers={"HX-Request": "true"}
        )
        assert pressed.status_code == 200, (button, pressed.text)
        assert '<span class="banner-label">refused</span>' in pressed.text, (
            button,
            pressed.text,
        )


async def test_a_fleet_with_both_kinds_of_doubt_says_which_node_is_which(
    client, session, reality_params, a_node_that_stops_answering
) -> None:
    """Two sentences, because the operator's next move differs per host.

    The reason the fix is a split and not a rewrite: a fleet can hold a host that probe
    and apply WILL finish and a host no press finishes at all, and the banner names the
    nodes because naming them is the text the operator acts on. One sentence covering both
    would send them to a button that refuses half the list — the defect — or drop the
    instruction from the half where it works.
    """
    node_ids = await a_served_fleet(client, reality_params)
    friend_id = (await client.get("/api/friends")).json()[0]["id"]
    await retire(client, node_ids[1])
    a_node_that_stops_answering()

    revoked = await client.post(f"/api/friends/{friend_id}/revoke")
    assert revoked.status_code == 200, revoked.text

    session.expire_all()
    still_pushable = (await nodes.get_node(session, node_ids[0])).name
    written_off = (await nodes.get_node(session, node_ids[1])).name
    said = " ".join((await client.get("/panel/friends/table")).text.split())

    # Each host under the sentence whose instruction is true of it, asserted by the join
    # between the two rather than by both merely being on the page.
    assert said.count("Withdrawn access is not confirmed") == 2, said
    assert f"not confirmed on {still_pushable}: " in said, said
    assert (
        f"not confirmed on {written_off}, and no screen in this panel finishes it" in said
    ), said
    assert "Probe it on the Nodes screen and apply it" in said, said


def test_the_cell_and_the_note_are_two_readings_of_one_answer() -> None:
    """They are composed from the same list, so they cannot disagree — M23, round 3.

    The screen has one question to answer about a withdrawal — can this panel confirm it
    stopped — and two places that answer it. Asked twice they drift, which is exactly the
    state the walk found: a standing note saying the withdrawal is not confirmed, over
    rows each asserting it is. So the cell is a function of the same list the note is, and
    it says nothing whenever the note has something to say.

    NOTHING, and not a per-row hedge of its own: a sentence about THIS person would have
    to name the nodes they were on, and a revocation deletes exactly the rows that would
    say. Round 2 got that right and this does not reopen it.
    """
    assert console.withdrawn_cell([]) == console.ACCESS_WITHDRAWN
    assert (
        console.withdrawn_cell([console.UnconfirmedNode(name="leaf-nl", can_be_finished=True)])
        is None
    )
    # And for the kind of doubt no press resolves, which is a different sentence above the
    # table and must be the same silence in the cell — M23, round 13.
    assert (
        console.withdrawn_cell([console.UnconfirmedNode(name="old-leaf", can_be_finished=False)])
        is None
    )
    assert console.withdrawn_cell(["leaf-nl", "leaf-is"]) is None
