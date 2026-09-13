"""A node that never answers is reported, not waited on — M4.4.

WHAT: that the ceiling on reaching a node comes from settings and reaches the
      connection, and that a node which never answers produces a per-node
      failure with a plain reason instead of a hang.
WHY:  a blackholed node is not a contrived condition for this project — it is
      what a BLOCKED node looks like from outside, which is the scenario the product
      exists for. The operator opens the panel during a block, presses apply or
      revoke, and must be told something. Revocation in particular is the operation
      whose whole point is being fast.
HOW:  the ceiling itself is asserted on, rather than wall-clock time, because
      "the suite got slower" is not a failure any assertion can state honestly.
      Elapsed time is bounded on both sides and nowhere else: an upper bound with a
      very wide margin, there only to catch the ceiling being configured but not
      honoured, and a lower one that catches the target itself going wrong.

M21.1 loosened one assertion here and tightened the rest. The reason the operator is
shown is no longer compared to the timeout sentence, because which sentence they get
depends on whether the connect timed out or was refused first — a property of the
machine and the network, not of this code. The fact "the node could not be reached" is
now asserted where it is actually recorded, on ``reachable``, and what is asserted
about the sentence is that it IS one: see ``assert_plain_reason`` in conftest.

M21.2 removed the reason those two outcomes were ever in play. The node is no longer
reached at an address whose behaviour belongs to the routing table; it is reached at
the ``unanswering_ssh`` socket, on loopback, which accepts and then says nothing
because this suite decided it says nothing. That is what makes the elapsed-time
assertion below mean something again — a target that refuses fast satisfies an upper
bound without ever waiting, so there is now a lower bound too.
"""

import time

import pytest

from control.app.services import apply, health, nodes

from .conftest import assert_plain_reason

# What a FRIEND would dial: a reserved documentation address (RFC 5737), as everywhere
# else in this zone. Nothing in this file dials it — the control plane reaches a node at
# its ``ssh_host``, which is the separate column below — so its routability is no longer
# load-bearing anywhere here. It is still checked for below: a node has two addresses
# now, and a reason must not carry either of them.
ADVERTISED_ADDRESS = "192.0.2.10"


async def a_node(client, ssh) -> str:
    """A registered node whose SSH endpoint is the socket the test is holding open."""
    response = await client.post(
        "/api/nodes",
        json={
            "name": "unanswering",
            "address": ADVERTISED_ADDRESS,
            "location_label": "Testland",
            "ssh_host": ssh.host,
            "ssh_port": ssh.port,
        },
    )
    return response.json()["id"]


async def test_the_configured_connect_ceiling_reaches_the_node_target(
    client, session, settings, unanswering_ssh
) -> None:
    """The knob is not decoration: ``target_for`` carries it to the connection.

    Asserted here rather than by timing an apply, because a timing assertion is a
    statement about the machine the suite runs on and this is a statement about the
    code.
    """
    node = await nodes.get_node(session, await a_node(client, unanswering_ssh))

    target = apply.target_for(node, settings)

    assert target.connect_timeout == settings.node_connect_timeout
    assert target.connect_timeout < target.timeout, (
        "reaching a node must be bounded more tightly than an operation on a node "
        "that already answered — otherwise a blocked host costs a full command budget"
    )


async def test_a_node_that_never_answers_is_reported_with_a_plain_reason(
    client, session, settings, unanswering_ssh
) -> None:
    """The operator gets a sentence, not a class name and not a traceback.

    ``check_node`` is the path used here because it reports without changing the
    node's state, so this test says nothing about the state machine — which is a
    separate defect in this same milestone.
    """
    node_id = await a_node(client, unanswering_ssh)

    started = time.monotonic()
    report = await health.check_node(session, node_id=node_id)
    elapsed = time.monotonic() - started

    # The FACT that the node could not be reached is a flag, not a sentence, and this
    # is where it is recorded — ``check_node`` sets it only for ``NodeUnreachable``.
    assert report.reachable is False
    # And this is the part the operator reads. Asserted as a property (words, one
    # line, no traceback, no bare class name, no address travelling with it) rather
    # than as the particular sentence the timeout arm happens to write — M21.1.
    assert_plain_reason(report.detail, unanswering_ssh.host, ADVERTISED_ADDRESS)

    # Ten times the configured ceiling. Wide enough that a loaded machine cannot fail
    # it, tight enough that a ceiling which is configured but not honoured — the
    # baseline behaviour, where every such probe cost the full command budget — does.
    assert elapsed < settings.node_connect_timeout * 10, (
        f"reaching an endpoint that never answers took {elapsed:.1f}s despite a "
        f"{settings.node_connect_timeout}s ceiling"
    )
    # And a floor, which is what stops the ceiling above from being satisfied by an
    # endpoint that never waited at all. A refusal comes back in under a millisecond
    # and would pass the assertion above while proving nothing about the timeout; only
    # a target that really blackholes can spend the ceiling. Half of it, because the
    # claim is "it waited" and not "it waited precisely" — and load can only push
    # elapsed UP, so unlike the ceiling this bound cannot be lost to a busy machine.
    assert elapsed >= settings.node_connect_timeout / 2, (
        f"the connect came back in {elapsed:.3f}s, so nothing waited for the "
        f"{settings.node_connect_timeout}s ceiling — is the target still one that "
        "accepts and stays silent?"
    )


@pytest.mark.parametrize("ceiling", [1, 2])
async def test_the_ceiling_is_the_one_configured_and_not_a_constant(
    client, session, settings, ceiling, unanswering_ssh
) -> None:
    """Two values, so a hardcoded number cannot satisfy both.

    A copy rather than an assignment: the application under test was built from the
    fixture's own instance, and a test that edits it changes the app underneath the
    next assertion.
    """
    node = await nodes.get_node(session, await a_node(client, unanswering_ssh))
    configured = settings.model_copy(update={"node_connect_timeout": ceiling})

    assert apply.target_for(node, configured).connect_timeout == ceiling
