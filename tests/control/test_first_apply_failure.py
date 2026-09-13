"""A node's FIRST apply can record its own failure — M4.1.

WHAT: that an apply which fails on a node still in ``draft`` leaves the node
      degraded, carrying the reason it actually failed for, and that the reason
      reaches a log as well.
WHY:  this is a field defect, not a hypothetical. On 2026-09-08 a real host was
      registered, given a transport and applied. It answered
      ``409: a node cannot go from draft to degraded`` — the state machine refused
      the transition INSIDE the failure path, so the recording's own error replaced
      the failure being recorded. The control plane's entire log of it was one line,
      ``domain error: conflict``. The real cause was a permission error on the host
      and recovering it took a health probe, an inspection of the host and rerunning
      the command by hand.
HOW:  the same cheap unreachable-node pattern the rest of this zone uses (M4.4), with
      the connect ceiling at one second from the ``settings`` fixture. No mock, no stub
      — a real SSH attempt that really fails, which is the only kind of failure worth
      asserting on.

M4.5 extends the same file to the SECOND apply, because M4.1 only ever proved the
first one. A node that is already ``degraded`` and fails again for a different reason
must show the operator the NEW reason: ``set_node_state`` compared states by identity,
which was always true on a column that hands back a plain ``str``, so the refused
``degraded -> degraded`` transition raised a Conflict, ``_record_failure`` swallowed it
by design, and ``state_detail`` kept the first failure's text. The operator retried,
got a new error, and the panel showed them the old one.

M21.2 changed WHERE the node is. It used to be a reserved documentation address, on the
assumption that nothing routes to it — an assumption about the host, which is how this
file came to answer differently on different machines. The node is now reached at
``refusing_ssh``: a loopback port this suite holds bound and never listens on, so every
connect is refused by the local kernel, in a millisecond, identically on every host and
without consulting a routing table. This file only ever needed "could not be reached";
the one test that needs a connect to actually WAIT lives in ``test_node_timeouts.py``
and uses the other fixture.

M18.1 added the file's counterpart at the bottom: the first apply that must NOT record
a failure, because a node with nothing enabled has nothing to serve and never reaches a
host at all. It is here rather than in a file of its own because it is the same button,
the same fixtures and the same moment — and because the contrast is the point.

M21.1 changed what these assertions are ABOUT. They used to pin the exact sentence a
timed-out connect produces, which made them fail on any machine where an unroutable
address is refused fast instead of dropped silently — the same fact, a different
sentence. What is asserted now is the property the operator depends on: the failure was
about the NODE (an exception chain ending in ``NodeUnreachable``, never the state
machine's complaint and never this control plane's own), the reason is words rather
than a class name or a traceback (``assert_plain_reason``), and the reason stored,
logged and answered are the same one.
"""

import logging

import pytest

from control.app.errors import Conflict, NodeOperationFailed, NothingToApply
from control.app.models import NodeState
from control.app.services import apply, nodes
from edge.bootstrap import NodeUnreachable

from .conftest import assert_plain_reason

# What a FRIEND would dial, and the only thing this address is here: RFC 5737
# TEST-NET-1, the same one every other fixture in this zone uses. Nothing in this file
# dials it — the control plane reaches a node at its ``ssh_host`` — so nothing here
# depends on what a documentation address does. It is still checked for below: a node
# has two addresses now, and a reason must not carry either of them.
ADVERTISED_ADDRESS = "192.0.2.10"

# The transition complaint that used to be handed to the operator instead of the real
# reason. Asserted against by fragment, so a reworded 409 cannot quietly come back.
TRANSITION_COMPLAINT = "cannot go from"

# The other way the operator can be told the wrong thing: ``apply_node``'s broad catch,
# which reports a bug in this control plane rather than a fact about the node. Named
# here — M21.1 — because the assertions below no longer pin the unreachable sentence,
# and without this fragment a genuine internal error would satisfy "a plain reason" and
# these tests would stop distinguishing the two. Asserted against by fragment for the
# same reason as above.
INTERNAL_ERROR_COMPLAINT = "unexpected internal error"

# Obviously not a key, and never used to authenticate: it is refused before anything is
# dialled. That is the point — it is a genuinely DIFFERENT failure from a node that
# cannot be reached, arriving through a different arm of ``apply_node``, and M4.5 is
# about two consecutive failures with two different causes.
#
# WHICH arm changed with M9's acceptance fixes and the difference is worth knowing: the
# SSH layer used to be the thing that refused it, from outside the block that turns a
# connection failure into ``NodeUnreachable``, so it arrived as an exception class
# through the broad catch — a probe answering 500 and a push telling the operator that
# "what reached the node is unknown", which was untrue of a key that never loaded.
# ``target_for`` refuses it now, and the recording below is what keeps M4.5 true of that
# arm as well.
UNIMPORTABLE_PRIVATE_KEY = "not-a-real-key"


async def a_drafted_node(client, reality_params, ssh) -> str:
    """A node exactly as an operator leaves it before their first apply: draft.

    ``ssh`` is the endpoint the control plane will dial — the ``refusing_ssh`` socket,
    so the apply fails because the test said it would, not because of a route.
    """
    node_id = (await client.post(
        "/api/nodes",
        json={
            "name": "first-apply",
            "address": ADVERTISED_ADDRESS,
            "location_label": "Testland",
            "ssh_host": ssh.host,
            "ssh_port": ssh.port,
        },
    )).json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    return node_id


async def test_a_draft_node_may_become_degraded(
    client, session, reality_params, refusing_ssh
) -> None:
    """The transition itself, stated once, so the decision has a test of its own."""
    node_id = await a_drafted_node(client, reality_params, refusing_ssh)

    node = await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="a reason"
    )

    assert node.state == NodeState.DEGRADED
    assert node.state_detail == "a reason"


async def test_a_first_apply_that_fails_records_the_real_reason(
    client, session, reality_params, refusing_ssh
) -> None:
    """The whole defect, in one test: the node was never active, and it failed."""
    node_id = await a_drafted_node(client, reality_params, refusing_ssh)
    assert (await nodes.get_node(session, node_id)).state == NodeState.DRAFT

    with pytest.raises(NodeOperationFailed) as raised:
        await apply.apply_node(session, node_id=node_id)

    # WHY it failed, from the exception chain rather than from its wording: the apply
    # gave up because the node could not be reached, which is the only arm of
    # ``apply_node`` that raises ``from`` a ``NodeUnreachable``. Whether that node was
    # slow or refused outright is not something this file asserts on — M21.1 — even now
    # that M21.2 has made it always the same one.
    assert isinstance(raised.value.__cause__, NodeUnreachable), raised.value.message
    assert TRANSITION_COMPLAINT not in raised.value.message, (
        "the operator was told about the state machine instead of about the node"
    )
    assert INTERNAL_ERROR_COMPLAINT not in raised.value.message, (
        "the operator was told this control plane broke instead of that the node did"
    )

    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DEGRADED, (
        "a node that was written to and failed is still a draft"
    )
    # What was RECORDED is a reason a person can act on (words, no traceback, no bare
    # class name, no address — see ``assert_plain_reason``), and it is the same reason
    # the operator was handed rather than a second, separately written one.
    assert_plain_reason(node.state_detail, refusing_ssh.host, ADVERTISED_ADDRESS)
    assert node.state_detail in raised.value.message


async def test_the_real_reason_reaches_a_log(
    client, session, reality_params, caplog, refusing_ssh
) -> None:
    """One line saying ``domain error: conflict`` is the failure mode being fixed.

    The log matters independently of the response: ``domain_error_handler`` logs the
    error CODE and never the message, on purpose, so a failure that is only reported
    through the envelope leaves nothing behind for whoever reads the logs afterwards.
    """
    node_id = await a_drafted_node(client, reality_params, refusing_ssh)

    with caplog.at_level(logging.ERROR, logger="control.app.services.apply"):
        with pytest.raises(NodeOperationFailed) as raised:
            await apply.apply_node(session, node_id=node_id)

    assert isinstance(raised.value.__cause__, NodeUnreachable), raised.value.message
    # Read back rather than written out here, so this asserts that the log carries the
    # reason the operator was actually given — a stronger claim than the one it
    # replaced, which only checked that the log contained a sentence this file also
    # knew how to spell.
    reason = (await nodes.get_node(session, node_id)).state_detail
    assert_plain_reason(reason, refusing_ssh.host, ADVERTISED_ADDRESS)

    logged = [record.getMessage() for record in caplog.records]
    assert any(reason in line for line in logged), logged
    assert any(node_id in line for line in logged), (
        "a fleet's log needs to say WHICH node failed, or the reason names nothing"
    )


async def test_the_api_reports_the_node_rather_than_the_state_machine(
    client, reality_params, refusing_ssh
) -> None:
    """End to end through the route, because the field report was an HTTP response."""
    node_id = await a_drafted_node(client, reality_params, refusing_ssh)

    outcome = await client.post(f"/api/nodes/{node_id}/apply")

    assert outcome.status_code == 502, outcome.text
    body = outcome.json()["error"]
    assert body["code"] == "node_operation_failed"
    assert_plain_reason(body["message"], refusing_ssh.host, ADVERTISED_ADDRESS)
    assert TRANSITION_COMPLAINT not in body["message"]
    assert INTERNAL_ERROR_COMPLAINT not in body["message"]

    node = (await client.get(f"/api/nodes/{node_id}")).json()
    assert node["state"] == "degraded"
    # Tied to the response rather than to a wording: the row the panel renders and the
    # answer the operator just got must be the same failure, whichever sentence the
    # connect attempt produced.
    assert_plain_reason(node["state_detail"], refusing_ssh.host, ADVERTISED_ADDRESS)
    assert node["state_detail"] in body["message"]


async def test_a_refused_transition_never_replaces_the_reason(
    client, session, reality_params, refusing_ssh
) -> None:
    """A retired node still has nowhere to go, and must not hijack the message.

    ``draft -> degraded`` is legal now; ``retired -> degraded`` is not, and never will
    be — retired is terminal by design. That leaves one path where recording the
    failure can still fail, and it must behave the way the draft path now does: the
    operator is told what went wrong with the node, not what went wrong with the
    bookkeeping.
    """
    node_id = await a_drafted_node(client, reality_params, refusing_ssh)
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.RETIRED)

    with pytest.raises(NodeOperationFailed) as raised:
        await apply.apply_node(session, node_id=node_id)

    assert isinstance(raised.value.__cause__, NodeUnreachable), raised.value.message
    assert_plain_reason(raised.value.message, refusing_ssh.host, ADVERTISED_ADDRESS)
    assert TRANSITION_COMPLAINT not in raised.value.message, (
        "the bookkeeping's own failure replaced the node's"
    )
    assert not isinstance(raised.value, Conflict)
    assert (await nodes.get_node(session, node_id)).state == NodeState.RETIRED


async def test_a_second_failure_replaces_the_first_ones_reason(
    client, session, reality_params, refusing_ssh
) -> None:
    """The operator retries, fails differently, and must be told the NEW reason — M4.5.

    Two real applies with two real and different causes: nothing answers at the address,
    then a key on the record that cannot be imported. The second is refused by
    ``target_for`` before a connection is attempted, rather than arriving as
    ``NodeUnreachable``, so this also covers the case where the two failures do not even
    share an arm of ``apply_node`` — and it is the arm where nothing was written to the
    host, which still has to leave the row's reason current.

    Driven through the ROUTE, not through ``apply_node``, and that is load-bearing. Each
    request gets its own session, so the second apply loads the node from the database
    — which is the only way ``node.state`` is what the database hands back rather than
    the enum member the previous call assigned in memory. Calling the service twice on
    one session never reproduced this, and that is exactly why it survived a review.

    Editing the record between the two is what an operator does between retries: they
    change something and try again. What must not survive that is the previous reason.
    """
    node_id = await a_drafted_node(client, reality_params, refusing_ssh)

    first = await client.post(f"/api/nodes/{node_id}/apply")
    assert first.status_code == 502, first.text

    # The first reason is READ, not spelled out: this test is about the second failure
    # replacing the first, and which sentence the first one produced is not this test's
    # subject (M21.1). Spelling it out is also how this assertion could pass while
    # proving nothing — a wrong guess makes ``not in`` below trivially true.
    first_reason = (await client.get(f"/api/nodes/{node_id}")).json()["state_detail"]
    assert_plain_reason(first_reason, refusing_ssh.host, ADVERTISED_ADDRESS)

    node = await nodes.get_node(session, node_id)
    node.ssh_private_key = UNIMPORTABLE_PRIVATE_KEY
    await session.commit()

    second = await client.post(f"/api/nodes/{node_id}/apply")
    assert second.status_code == 502, second.text
    message = second.json()["error"]["message"]
    assert first_reason not in message, "the second apply reported the first one's failure"

    # Read back through the API, because "what the operator sees" is the panel and the
    # node endpoint, not the exception. A degraded node whose reason is one retry old is
    # worse than no reason: it sends them to fix something they already fixed.
    shown = (await client.get(f"/api/nodes/{node_id}")).json()
    assert shown["state"] == "degraded", shown
    assert first_reason not in shown["state_detail"], (
        "the panel is still showing the reason the PREVIOUS apply failed"
    )
    # Tied to the failure that was just reported rather than to a wording, so this stays
    # true if the message for an unexpected error is ever rewritten.
    assert shown["state_detail"] in message, shown


# --- M18.1: the first apply of a node that has nothing enabled ----------------
#
# The other half of this file's subject, found in the field on 2026-09-09 and the exact
# inverse of everything above: an apply that must NOT record a failure, because there is
# no failure to record.
#
# What the operator did was the most ordinary thing there is — register a node, press the
# button its row invites — and what came back was
#
#     502  the node could not be configured and has been marked degraded: command failed
#          (1): 'cd /opt/hashi && docker compose up -d --remove-orphans': services must
#          be a mapping
#
# with the node left ``degraded``. Every layer was working as designed, which is why this
# survived: no enabled transport renders no config, no config makes an empty ``services:``
# block, and M4 hands the node's own stderr back verbatim rather than losing it the way
# the tests above exist to prevent. The defect is that this is not a failure at all.


async def an_empty_node(client, ssh) -> str:
    """A node exactly as registration leaves it: a record, and nothing enabled on it.

    Deliberately given a reachable-looking ``ssh_host`` — the ``refusing_ssh`` socket the
    rest of this file uses — so that a regression cannot pass by failing for the other
    reason. If the refusal below is ever removed, this node gets as far as a real connect
    and the assertions see a degraded node, which is the field's own outcome.
    """
    return (await client.post(
        "/api/nodes",
        json={
            "name": "nothing-enabled",
            "address": ADVERTISED_ADDRESS,
            "location_label": "Testland",
            "ssh_host": ssh.host,
            "ssh_port": ssh.port,
        },
    )).json()["id"]


async def test_applying_a_node_with_nothing_enabled_is_refused_not_failed(
    client, session, refusing_ssh
) -> None:
    """The sentence is about transports, and the node is left exactly as it was."""
    node_id = await an_empty_node(client, refusing_ssh)

    with pytest.raises(NothingToApply) as raised:
        await apply.apply_node(session, node_id=node_id)

    assert not isinstance(raised.value, NodeOperationFailed), (
        "the operator is told a node operation failed, when nothing was attempted"
    )
    # The sentence names what is missing and what to do about it. Asserted on the two
    # things it must contain rather than on the whole string, so it can be reworded.
    assert "no transports enabled" in raised.value.message
    assert apply.WHERE_TO_RETRY in raised.value.message, (
        "the refusal does not say where to go and offer the node a transport"
    )
    # And it is not the old answer: nothing about YAML, the compose file, or the daemon.
    for leaked in ("mapping", "compose", "docker", "yml"):
        assert leaked not in raised.value.message.lower(), (
            f"the refusal still talks about {leaked!r} — the operator is being shown the "
            f"node's parser instead of being told to enable a transport"
        )

    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DRAFT, (
        "a node that was never dialled has been marked degraded"
    )
    assert node.state_detail is None, node.state_detail


async def test_a_serving_node_whose_last_transport_was_withdrawn_keeps_serving(
    client, session, reality_params, refusing_ssh
) -> None:
    """The case that decides where the refusal is raised, rather than merely that it is.

    An ``active`` node that is applied after its only transport is withdrawn renders
    nothing. Marking it degraded would take it out of ``nodes.serving_transports`` and so
    out of every subscription — for a mistake at the console, on a host that is still up
    and still serving the config it was last given. The refusal therefore lives where a
    render failure already did, outside ``apply_node``'s try blocks, and the property
    worth pinning is that the node's recorded state does not move.
    """
    node_id = (await client.post(
        "/api/nodes",
        json={
            "name": "withdrawn-everything",
            "address": ADVERTISED_ADDRESS,
            "location_label": "Testland",
            "ssh_host": refusing_ssh.host,
            "ssh_port": refusing_ssh.port,
        },
    )).json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    assert (await client.post(
        f"/api/nodes/{node_id}/state", json={"state": "active"}
    )).status_code == 200
    withdrawn = await client.post(
        f"/api/transports/{enabled.json()['id']}/state", json={"enabled": False}
    )
    assert withdrawn.status_code == 200, withdrawn.text

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    shown = (await client.get(f"/api/nodes/{node_id}")).json()
    assert shown["state"] == "active", (
        "a node still serving its last config was degraded by an apply that pushed nothing"
    )
    assert shown["state_detail"] is None, shown


async def test_the_api_says_nothing_to_apply_rather_than_a_bad_gateway(
    client, refusing_ssh
) -> None:
    """A script has to tell "you have not enabled anything" from "this node is broken".

    502 is the answer to the second and was the answer to both. The code is its own
    value rather than one of the node state machine's conflicts, because every other 409
    this API gives about a node is a refused transition and this one is not.
    """
    node_id = await an_empty_node(client, refusing_ssh)

    refused = await client.post(f"/api/nodes/{node_id}/apply")

    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "nothing_to_apply", refused.text


async def test_the_console_shows_the_refusal_and_leaves_the_row_undegraded(
    client, refusing_ssh
) -> None:
    """The operator's actual path — the apply button on the Nodes screen.

    A banner rather than a toast, because the next thing they do is go and offer the node
    a transport and the sentence has to still be there when they come back.
    """
    node_id = await an_empty_node(client, refusing_ssh)

    pressed = await client.post(
        f"/panel/nodes/{node_id}/apply", headers={"HX-Request": "true"}
    )

    assert pressed.status_code == 200, pressed.text
    assert "no transports enabled" in pressed.text, pressed.text
    assert "config applied" not in pressed.text, (
        "the console reported an apply that never happened"
    )
    assert "degraded" not in (await client.get("/panel/nodes/table")).text
