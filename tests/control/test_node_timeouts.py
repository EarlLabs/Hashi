"""A node that never answers is reported, not waited on — M4.4.

WHAT: that the ceiling on reaching a node comes from settings and reaches the
      connection, and that a node which accepts no packets produces a per-node
      failure with a plain reason instead of a hang.
WHY:  a blackholed address is not a contrived condition for this project — it is
      what a BLOCKED node looks like from outside, which is the scenario the product
      exists for. The operator opens the panel during a block, presses apply or
      revoke, and must be told something. Revocation in particular is the operation
      whose whole point is being fast.
HOW:  the ceiling itself is asserted on, rather than wall-clock time, because
      "the suite got slower" is not a failure any assertion can state honestly.
      One elapsed-time assertion exists, with a very wide margin, and it is there
      only to catch the ceiling being configured but not honoured.
"""

import time

import pytest

from control.app.services import apply, health, nodes

# A reserved documentation address (RFC 5737), the same one the rest of this zone's
# fixtures use. Nothing routes to it, which is exactly the property under test.
UNANSWERING_ADDRESS = "192.0.2.10"


async def a_node(client) -> str:
    response = await client.post(
        "/api/nodes",
        json={
            "name": "unanswering",
            "address": UNANSWERING_ADDRESS,
            "location_label": "Testland",
        },
    )
    return response.json()["id"]


async def test_the_configured_connect_ceiling_reaches_the_node_target(
    client, session, settings
) -> None:
    """The knob is not decoration: ``target_for`` carries it to the connection.

    Asserted here rather than by timing an apply, because a timing assertion is a
    statement about the machine the suite runs on and this is a statement about the
    code.
    """
    node = await nodes.get_node(session, await a_node(client))

    target = apply.target_for(node, settings)

    assert target.connect_timeout == settings.node_connect_timeout
    assert target.connect_timeout < target.timeout, (
        "reaching a node must be bounded more tightly than an operation on a node "
        "that already answered — otherwise a blocked host costs a full command budget"
    )


async def test_a_node_that_never_answers_is_reported_with_a_plain_reason(
    client, session, settings
) -> None:
    """The operator gets a sentence naming how long we waited, not a class name.

    ``check_node`` is the path used here because it reports without changing the
    node's state, so this test says nothing about the state machine — which is a
    separate defect in this same milestone.
    """
    node_id = await a_node(client)

    started = time.monotonic()
    report = await health.check_node(session, node_id=node_id)
    elapsed = time.monotonic() - started

    assert report.reachable is False
    assert report.detail == f"the node did not answer within {settings.node_connect_timeout}s"
    # The address must not travel with the reason: it reaches the panel, and a node's
    # address in operator-facing text is a step towards a connection record.
    assert UNANSWERING_ADDRESS not in report.detail

    # Ten times the configured ceiling. Wide enough that a loaded machine cannot fail
    # it, tight enough that a ceiling which is configured but not honoured — the
    # baseline behaviour, where every such probe cost the full command budget — does.
    assert elapsed < settings.node_connect_timeout * 10, (
        f"reaching an address that never answers took {elapsed:.1f}s despite a "
        f"{settings.node_connect_timeout}s ceiling"
    )


@pytest.mark.parametrize("ceiling", [1, 2])
async def test_the_ceiling_is_the_one_configured_and_not_a_constant(
    client, session, settings, ceiling
) -> None:
    """Two values, so a hardcoded number cannot satisfy both.

    A copy rather than an assignment: the application under test was built from the
    fixture's own instance, and a test that edits it changes the app underneath the
    next assertion.
    """
    node = await nodes.get_node(session, await a_node(client))
    configured = settings.model_copy(update={"node_connect_timeout": ceiling})

    assert apply.target_for(node, configured).connect_timeout == ceiling
