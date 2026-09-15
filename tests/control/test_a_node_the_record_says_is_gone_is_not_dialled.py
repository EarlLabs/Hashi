"""Two buttons on one row, one answer about one address — M23, round 12.

WHAT: what the PROBE does on a node the state machine will not put back into service,
      and what it still does on one that is merely parked.
WHY:  round 12's walk found the two buttons disagreeing. Apply on a retired node is
      refused because its address *"may now answer for somebody else"*; the probe beside
      it on the same row opened an SSH session to that exact address — measured,
      ``GET /api/nodes/{id}/health`` answered 200 having dialled it.

      A probe is a read, and it is still a connection: it offers this control plane's key
      to whoever is at that address and asks them what they are running. So the one
      address this product refuses to push to was the one address it went on dialling,
      and a retired record is precisely where "whoever is there" is most likely not to be
      the operator.

      The probe is the one that yields. Apply's refusal closes a hole nothing else closes
      — a written-off host back in every friend's subscription with key material minted
      for the whole fleet — while the probe's answer is not lost, only moved behind the
      step the operator has to take anyway: register the host again as a new node, and
      probe that one. The cost is named in ``apply.CANNOT_BE_DIALLED`` rather than
      discovered later.
HOW:  the connection class ``services/health.py`` reaches for is replaced, so "nothing was
      dialled" is a fact about this test rather than a hope about a timeout. Nothing here
      opens a socket.

Boundary: nothing here says what a retired HOST is doing. That is the point of the
refusal — this control plane stops claiming to know.
"""

import pytest

from control.app.models import NodeState
from control.app.services import apply
from edge.bootstrap import NodeUnreachable

from .conftest import GENERATED_SSH_KEY

# RFC 5737 documentation address, as everywhere in this zone. It is never dialled here —
# the connection class is replaced — but a record has to name something and a routable
# address in a fixture is an accident waiting to happen.
NODE_ADDRESS = "192.0.2.90"


class DialledIt(Exception):
    """Raised by the double below, so a dial that should not happen is unmissable."""


@pytest.fixture
def nothing_may_be_dialled(monkeypatch: pytest.MonkeyPatch):
    """A probe that reaches the connection layer raises instead of waiting on a socket.

    The assertion this file is built on is a NEGATIVE — that nothing was dialled — and a
    negative proved by a timeout is a negative that also passes when the guard is gone and
    the host simply does not answer. Which is what the walk measured: the refusal was
    absent, the probe dialled a documentation address, and the operator was told the node
    did not answer within a second. Indistinguishable from the fix, from the outside.
    """
    from control.app.services import health

    def connection_for(target):
        raise DialledIt(f"the probe opened a connection to {target.host}")

    monkeypatch.setattr(health, "NodeConnection", connection_for)


@pytest.fixture
def every_node_answers_nothing(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A probe that reaches the connection layer records the host and finds nobody.

    The other direction, for the nodes that must still be probed: ``NodeUnreachable`` is
    the honest end of a real probe against a host that is not there, and the list it
    returns is what says the dial happened at all.
    """
    from control.app.services import health

    dialled: list[str] = []

    def connection_for(target):
        dialled.append(target.host)
        raise NodeUnreachable("the node did not answer")

    monkeypatch.setattr(health, "NodeConnection", connection_for)
    return dialled


async def a_node_with_something_to_serve(client, reality_params, *, name: str) -> str:
    """A node with an SSH key and one transport, so a probe has something to ask about."""
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
    return node_id


async def move(client, node_id: str, state: str, detail: str) -> None:
    moved = await client.post(
        f"/api/nodes/{node_id}/state", json={"state": state, "detail": detail}
    )
    assert moved.status_code == 200, moved.text


async def test_the_probe_does_not_dial_a_node_the_record_says_is_gone(
    client, reality_params, nothing_may_be_dialled
) -> None:
    """The finding itself, on the surface it was measured on."""
    node_id = await a_node_with_something_to_serve(client, reality_params, name="seized")
    await move(client, node_id, "retired", "the host was seized")

    refused = await client.get(f"/api/nodes/{node_id}/health")

    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "node_cannot_serve", refused.text


async def test_the_refusal_says_what_a_probe_would_have_done(
    client, reality_params, nothing_may_be_dialled
) -> None:
    """The sentence, which is what tells the operator this is a decision and not a fault.

    It has to say more than "no": a probe answering nothing on a node whose host may still
    be serving a withdrawn friend is the uncomfortable state this product is most careful
    about, and an operator who reads only a refusal will press it again.
    """
    node_id = await a_node_with_something_to_serve(client, reality_params, name="written-off")
    await move(client, node_id, "retired", "returned to the provider")

    message = (await client.get(f"/api/nodes/{node_id}/health")).json()["error"]["message"]

    # What was not done, why, and where the operator goes instead.
    assert "Nothing was dialled." in message, message
    assert "may now answer for somebody else" in message, message
    assert "register it again as a new node" in message, message
    # And it names no screen: this sentence is a JSON body as well as a console banner.
    assert "screen" not in message.lower(), message


async def test_a_parked_node_is_still_probed(
    client, reality_params, every_node_answers_nothing: list[str]
) -> None:
    """The oracle the guard must not take with it, and the reason it asks the machine.

    ``draft`` is where an operator parks a host they are rebuilding and ``degraded`` is
    where a failed apply leaves one, and both are exactly when "what is that host actually
    running" is the question. A guard written against every state but ``active`` would
    close the finding and take the only answer to that question with it.
    """
    for state in ("draft", "degraded"):
        node_id = await a_node_with_something_to_serve(
            client, reality_params, name=f"parked-{state}"
        )
        await move(client, node_id, state, "rebuilding the host")

        probed = await client.get(f"/api/nodes/{node_id}/health")

        assert probed.status_code == 200, probed.text
        assert probed.json()["reachable"] is False, probed.text

    assert every_node_answers_nothing == [NODE_ADDRESS, NODE_ADDRESS], (
        "a parked node was not dialled, so this console has lost its only oracle for "
        "what the host it is about to rebuild is running"
    )


async def test_both_buttons_on_one_row_give_one_answer_about_one_address(
    client, reality_params, nothing_may_be_dialled
) -> None:
    """The claim this round is actually about, asserted as one fact rather than two.

    The two buttons sit side by side on the node's row and are pressed about the same
    host. Before this round one refused and the other dialled, and nothing in the suite
    compared them — which is how the disagreement survived a walk that looked at both.
    """
    node_id = await a_node_with_something_to_serve(client, reality_params, name="gone")
    await move(client, node_id, "retired", "the host is gone")

    probed = await client.get(f"/api/nodes/{node_id}/health")
    applied = await client.post(f"/api/nodes/{node_id}/apply")

    assert probed.status_code == applied.status_code == 409
    assert (
        probed.json()["error"]["code"] == applied.json()["error"]["code"]
    ), (probed.text, applied.text)
    # The sentences differ, and must: the two buttons would have done different things,
    # and an operator who pressed probe must not be answered about apply.
    assert probed.json()["error"]["message"] != applied.json()["error"]["message"]


async def test_the_console_reads_the_refusal_instead_of_an_internal_error(
    client, reality_params, nothing_may_be_dialled
) -> None:
    """The console's half, which is a 200 with a banner and not an error page.

    The probe button already drew a refusal as a banner — the keyless-node arm does — so
    what this round added to the route is one word: `refused` above it instead of
    `failed`, which is the distinction M18.1 drew on the apply button beside it. The rest
    of what is asserted here the console was already doing, and asserting it is what says
    so rather than assuming it.
    """
    node_id = await a_node_with_something_to_serve(client, reality_params, name="on-screen")
    await move(client, node_id, "retired", "the host is gone")

    answered = await client.post(
        f"/panel/nodes/{node_id}/probe", headers={"HX-Request": "true"}
    )

    assert answered.status_code == 200, answered.status_code
    assert "not dialled by this control plane" in answered.text, answered.text
    # ``refused`` and not ``failed``, which is the same distinction the apply button was
    # given in M18.1: `failed` on either of these buttons reads as "that node is broken",
    # and this node is in a state the operator set deliberately and which has not moved.
    assert ">refused<" in answered.text, answered.text
    assert ">failed<" not in answered.text, answered.text
    # The console's own words for where the operator goes, not the service's — the same
    # translation ``REGISTER_IT_AGAIN`` already carries for the apply button. Asserted by
    # the SCREEN it names and by the service's clause being absent, because the control's
    # name is quoted and Jinja escapes the quotes.
    assert "on the Nodes screen and apply that one" in answered.text, answered.text
    assert apply.REGISTER_IT_AGAIN not in answered.text, (
        "the console drew the API's version of the direction, which names no control"
    )


async def test_the_guard_asks_the_machine_rather_than_naming_a_state(client) -> None:
    """Why widening ``NodeState.allowed_from`` widens both doors and neither is edited.

    A state added later that cannot become active would be refused here too — and a guard
    comparing against the literal ``retired`` would let the probe dial it while apply
    turned it away, which is the shape this round is closing.
    """
    assert apply.cannot_serve_again(NodeState.RETIRED)
    for state in NodeState:
        if state is NodeState.RETIRED:
            continue
        assert not apply.cannot_serve_again(state), (
            f"{state} cannot come back into service, so the probe now refuses it too — "
            "which may be right, and the sentence it is answered with was written for a "
            "host that is gone. Whoever added this state decides."
        )
