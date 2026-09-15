"""Polling a node's health — backlog item 13, control side.

WHAT: renders what a node SHOULD be running, probes it, and reports the difference.
WHY:  the control plane polls; a node never dials us. And health is deliberately
      narrow: whether the node serves, not who used it. There is no code path in this
      module or the one it calls that could produce a per-user figure.
HOW:  renders through the same function the apply path uses, so "drifted" means the
      node differs from what we would push — not from a second, separately written
      idea of what should be there. "stale" is the same comparison against what the
      running PROCESS was started from, which is a different question and was the one
      nothing asked until M1.

      AND WHERE EACH CONFIG SHOULD ANSWER — M22, the same division of labour one field
      over. The port is the operator's own parameter and the protocols are the
      transport's own declaration, so `control` resolves both and passes them in;
      `edge` reads the node's socket table and compares. What comes back is three
      answers per transport rather than two — listening, not listening, and nobody
      could ask — because collapsing the third into the second reports a host whose
      socket table could not be read as a fleet-wide outage.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from control.app.api import schemas
from control.app.errors import NodeCannotServe
from control.app.services import apply, nodes
from edge.bootstrap import NodeConnection, NodeUnreachable
from edge.health import probe

logger = logging.getLogger(__name__)


async def check_node(session: AsyncSession, *, node_id: str) -> schemas.HealthResponse:
    """Probe one node and report what it is actually doing.

    A node that cannot be reached is reported as unreachable rather than raising: the
    panel must be able to show a dead node's row, and an exception here would make one
    unreachable host break the whole nodes page.

    A node the state machine will not put back into service is REFUSED rather than dialled
    — M23, round 12, and the reasoning is at ``apply.CANNOT_BE_DIALLED``. It raises rather
    than answering ``reachable=False``, which would have been the smaller change and a
    lie: that field means this control plane tried and could not, and every list beside it
    is composed on the same promise. Nothing was tried here.
    """
    node = await nodes.get_node(session, node_id)

    # BEFORE anything is rendered, decrypted or dialled — the same place the apply door
    # asks it, through the same predicate, so the two buttons on one row cannot come to
    # different answers about one address.
    if apply.cannot_serve_again(node.state):
        raise NodeCannotServe(apply.CANNOT_BE_DIALLED.format(state=node.state))

    expected = await apply.render_for_node(session, node)
    # Which transport each placed config came from — the probe needs it to know which
    # EXTENSION the file on the node carries, and since M15 a config's name and its
    # transport's name are two strings (see ``apply.placed_transports``).
    placed = await apply.placed_transports(session, node)
    # And where each of them should be answering — the port off the row, the protocols
    # off the transport's declaration. A row neither can be resolved for is absent here,
    # and the probe then says its port was not checked rather than that it is silent.
    listeners = await apply.placed_listeners(session, node)

    try:
        async with NodeConnection(apply.target_for(node, apply.settings())) as connection:
            health = await probe(
                connection, expected=expected, transports=placed, listeners=listeners
            )
    except NodeUnreachable as exc:
        return schemas.HealthResponse(
            node_id=node.id,
            reachable=False,
            healthy=False,
            running=[],
            restarting=[],
            missing=sorted(expected),
            drifted=[],
            # Empty rather than "everything": a node we could not reach has told us
            # nothing about what its containers are running, and reporting a guess as
            # a finding is the fault this milestone is about, one field over. The same
            # reasoning covers the two port answers: an unreachable node was never asked
            # what it is listening on, so neither list may name anything.
            stale=[],
            listening=[],
            not_listening=[],
            detail=str(exc),
        )

    return schemas.HealthResponse(
        node_id=node.id,
        reachable=health.reachable,
        healthy=health.healthy,
        running=health.running,
        restarting=health.restarting,
        missing=health.missing,
        drifted=health.drifted,
        stale=health.stale,
        listening=health.listening,
        not_listening=health.not_listening,
        detail=health.detail,
    )
