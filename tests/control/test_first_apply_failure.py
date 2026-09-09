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
"""

import logging

import pytest

from control.app.errors import Conflict, NodeOperationFailed
from control.app.models import NodeState
from control.app.services import apply, nodes

# RFC 5737 TEST-NET-1, reserved for documentation. Nothing routes to it, which is the
# property under test — the same address every other fixture in this zone uses.
UNREACHABLE_ADDRESS = "192.0.2.10"

# The transition complaint that used to be handed to the operator instead of the real
# reason. Asserted against by fragment, so a reworded 409 cannot quietly come back.
TRANSITION_COMPLAINT = "cannot go from"


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
    client, session, settings, reality_params
) -> None:
    """The whole defect, in one test: the node was never active, and it failed."""
    node_id = await a_drafted_node(client, reality_params)
    assert (await nodes.get_node(session, node_id)).state == NodeState.DRAFT

    with pytest.raises(NodeOperationFailed) as raised:
        await apply.apply_node(session, node_id=node_id)

    reason = f"the node did not answer within {settings.node_connect_timeout}s"
    assert reason in raised.value.message
    assert TRANSITION_COMPLAINT not in raised.value.message, (
        "the operator was told about the state machine instead of about the node"
    )

    node = await nodes.get_node(session, node_id)
    assert node.state == NodeState.DEGRADED, (
        "a node that was written to and failed is still a draft"
    )
    assert node.state_detail == reason
    # The address must not travel with the reason: it reaches the panel and the
    # database, and a node's address in operator-facing text is a step towards a
    # connection record (core invariants §6).
    assert UNREACHABLE_ADDRESS not in node.state_detail


async def test_the_real_reason_reaches_a_log(
    client, session, settings, reality_params, caplog
) -> None:
    """One line saying ``domain error: conflict`` is the failure mode being fixed.

    The log matters independently of the response: ``domain_error_handler`` logs the
    error CODE and never the message, on purpose, so a failure that is only reported
    through the envelope leaves nothing behind for whoever reads the logs afterwards.
    """
    node_id = await a_drafted_node(client, reality_params)

    with caplog.at_level(logging.ERROR, logger="control.app.services.apply"):
        with pytest.raises(NodeOperationFailed):
            await apply.apply_node(session, node_id=node_id)

    reason = f"the node did not answer within {settings.node_connect_timeout}s"
    logged = [record.getMessage() for record in caplog.records]
    assert any(reason in line for line in logged), logged
    assert any(node_id in line for line in logged), (
        "a fleet's log needs to say WHICH node failed, or the reason names nothing"
    )


async def test_the_api_reports_the_node_rather_than_the_state_machine(
    client, settings, reality_params
) -> None:
    """End to end through the route, because the field report was an HTTP response."""
    node_id = await a_drafted_node(client, reality_params)

    outcome = await client.post(f"/api/nodes/{node_id}/apply")

    assert outcome.status_code == 502, outcome.text
    body = outcome.json()["error"]
    assert body["code"] == "node_operation_failed"
    assert f"the node did not answer within {settings.node_connect_timeout}s" in body["message"]
    assert TRANSITION_COMPLAINT not in body["message"]

    node = (await client.get(f"/api/nodes/{node_id}")).json()
    assert node["state"] == "degraded"
    assert node["state_detail"]


async def test_a_refused_transition_never_replaces_the_reason(
    client, session, settings, reality_params
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

    reason = f"the node did not answer within {settings.node_connect_timeout}s"
    assert reason in raised.value.message
    assert not isinstance(raised.value, Conflict)
    assert (await nodes.get_node(session, node_id)).state == NodeState.RETIRED
