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
HOW:  the same cheap unreachable-node pattern the rest of this zone uses (M4.4): a
      reserved documentation address that nothing routes to, with the connect ceiling
      at one second from the ``settings`` fixture. No mock, no stub — a real SSH
      attempt that really fails, which is the only kind of failure worth asserting on.

M4.5 extends the same file to the SECOND apply, because M4.1 only ever proved the
first one. A node that is already ``degraded`` and fails again for a different reason
must show the operator the NEW reason: ``set_node_state`` compared states by identity,
which was always true on a column that hands back a plain ``str``, so the refused
``degraded -> degraded`` transition raised a Conflict, ``_record_failure`` swallowed it
by design, and ``state_detail`` kept the first failure's text. The operator retried,
got a new error, and the panel showed them the old one.

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

from control.app.errors import Conflict, NodeOperationFailed
from control.app.models import NodeState
from control.app.services import apply, nodes
from edge.bootstrap import NodeUnreachable

from .conftest import assert_plain_reason

# RFC 5737 TEST-NET-1, reserved for documentation. Nothing routes to it, which is the
# property under test — the same address every other fixture in this zone uses.
UNREACHABLE_ADDRESS = "192.0.2.10"

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

# Obviously not a key, and never used to authenticate: asyncssh refuses to import it
# before anything is dialled. That is the point — it is a genuinely DIFFERENT failure
# from a node that never answers, arriving through a different arm of ``apply_node``,
# and M4.5 is about two consecutive failures with two different causes.
UNIMPORTABLE_PRIVATE_KEY = "not-a-real-key"


async def a_drafted_node(client, reality_params) -> str:
    """A node exactly as an operator leaves it before their first apply: draft."""
    node_id = (await client.post(
        "/api/nodes",
        json={
            "name": "first-apply",
            "address": UNREACHABLE_ADDRESS,
            "location_label": "Testland",
        },
    )).json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    return node_id


async def test_a_draft_node_may_become_degraded(client, session, reality_params) -> None:
    """The transition itself, stated once, so the decision has a test of its own."""
    node_id = await a_drafted_node(client, reality_params)

    node = await nodes.set_node_state(
        session, node_id=node_id, state=NodeState.DEGRADED, detail="a reason"
    )

    assert node.state == NodeState.DEGRADED
    assert node.state_detail == "a reason"


async def test_a_first_apply_that_fails_records_the_real_reason(
    client, session, reality_params
) -> None:
    """The whole defect, in one test: the node was never active, and it failed."""
    node_id = await a_drafted_node(client, reality_params)
    assert (await nodes.get_node(session, node_id)).state == NodeState.DRAFT

    with pytest.raises(NodeOperationFailed) as raised:
        await apply.apply_node(session, node_id=node_id)

    # WHY it failed, from the exception chain rather than from its wording: the apply
    # gave up because the node could not be reached, which is the only arm of
    # ``apply_node`` that raises ``from`` a ``NodeUnreachable``. Whether that node was
    # slow or refused outright is the network's business, not this test's — M21.1.
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
    assert_plain_reason(node.state_detail, address=UNREACHABLE_ADDRESS)
    assert node.state_detail in raised.value.message


async def test_the_real_reason_reaches_a_log(
    client, session, reality_params, caplog
) -> None:
    """One line saying ``domain error: conflict`` is the failure mode being fixed.

    The log matters independently of the response: ``domain_error_handler`` logs the
    error CODE and never the message, on purpose, so a failure that is only reported
    through the envelope leaves nothing behind for whoever reads the logs afterwards.
    """
    node_id = await a_drafted_node(client, reality_params)

    with caplog.at_level(logging.ERROR, logger="control.app.services.apply"):
        with pytest.raises(NodeOperationFailed) as raised:
            await apply.apply_node(session, node_id=node_id)

    assert isinstance(raised.value.__cause__, NodeUnreachable), raised.value.message
    # Read back rather than written out here, so this asserts that the log carries the
    # reason the operator was actually given — a stronger claim than the one it
    # replaced, which only checked that the log contained a sentence this file also
    # knew how to spell.
    reason = (await nodes.get_node(session, node_id)).state_detail
    assert_plain_reason(reason, address=UNREACHABLE_ADDRESS)

    logged = [record.getMessage() for record in caplog.records]
    assert any(reason in line for line in logged), logged
    assert any(node_id in line for line in logged), (
        "a fleet's log needs to say WHICH node failed, or the reason names nothing"
    )


async def test_the_api_reports_the_node_rather_than_the_state_machine(
    client, reality_params
) -> None:
    """End to end through the route, because the field report was an HTTP response."""
    node_id = await a_drafted_node(client, reality_params)

    outcome = await client.post(f"/api/nodes/{node_id}/apply")

    assert outcome.status_code == 502, outcome.text
    body = outcome.json()["error"]
    assert body["code"] == "node_operation_failed"
    assert_plain_reason(body["message"], address=UNREACHABLE_ADDRESS)
    assert TRANSITION_COMPLAINT not in body["message"]
    assert INTERNAL_ERROR_COMPLAINT not in body["message"]

    node = (await client.get(f"/api/nodes/{node_id}")).json()
    assert node["state"] == "degraded"
    # Tied to the response rather than to a wording: the row the panel renders and the
    # answer the operator just got must be the same failure, whichever sentence the
    # connect attempt produced.
    assert_plain_reason(node["state_detail"], address=UNREACHABLE_ADDRESS)
    assert node["state_detail"] in body["message"]


async def test_a_refused_transition_never_replaces_the_reason(
    client, session, reality_params
) -> None:
    """A retired node still has nowhere to go, and must not hijack the message.

    ``draft -> degraded`` is legal now; ``retired -> degraded`` is not, and never will
    be — retired is terminal by design. That leaves one path where recording the
    failure can still fail, and it must behave the way the draft path now does: the
    operator is told what went wrong with the node, not what went wrong with the
    bookkeeping.
    """
    node_id = await a_drafted_node(client, reality_params)
    await nodes.set_node_state(session, node_id=node_id, state=NodeState.RETIRED)

    with pytest.raises(NodeOperationFailed) as raised:
        await apply.apply_node(session, node_id=node_id)

    assert isinstance(raised.value.__cause__, NodeUnreachable), raised.value.message
    assert_plain_reason(raised.value.message, address=UNREACHABLE_ADDRESS)
    assert TRANSITION_COMPLAINT not in raised.value.message, (
        "the bookkeeping's own failure replaced the node's"
    )
    assert not isinstance(raised.value, Conflict)
    assert (await nodes.get_node(session, node_id)).state == NodeState.RETIRED


async def test_a_second_failure_replaces_the_first_ones_reason(
    client, session, reality_params
) -> None:
    """The operator retries, fails differently, and must be told the NEW reason — M4.5.

    Two real applies with two real and different causes: nothing answers at the address,
    then a key on the record that cannot be imported. The second arrives through the
    broad catch rather than through ``NodeUnreachable``, so this also covers the case
    where the two failures do not even share an arm of ``apply_node``.

    Driven through the ROUTE, not through ``apply_node``, and that is load-bearing. Each
    request gets its own session, so the second apply loads the node from the database
    — which is the only way ``node.state`` is what the database hands back rather than
    the enum member the previous call assigned in memory. Calling the service twice on
    one session never reproduced this, and that is exactly why it survived a review.

    Editing the record between the two is what an operator does between retries: they
    change something and try again. What must not survive that is the previous reason.
    """
    node_id = await a_drafted_node(client, reality_params)

    first = await client.post(f"/api/nodes/{node_id}/apply")
    assert first.status_code == 502, first.text

    # The first reason is READ, not spelled out: this test is about the second failure
    # replacing the first, and which sentence the first one produced is the network's
    # business (M21.1). Spelling it out is also how this assertion could pass while
    # proving nothing — a wrong guess makes ``not in`` below trivially true.
    first_reason = (await client.get(f"/api/nodes/{node_id}")).json()["state_detail"]
    assert_plain_reason(first_reason, address=UNREACHABLE_ADDRESS)

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
