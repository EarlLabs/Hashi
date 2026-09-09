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
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from control.app.api import schemas
from control.app.services import apply, nodes
from edge.bootstrap import NodeConnection, NodeUnreachable
from edge.health import probe

logger = logging.getLogger(__name__)


async def check_node(session: AsyncSession, *, node_id: str) -> schemas.HealthResponse:
    """Probe one node and report what it is actually doing.

    A node that cannot be reached is reported as unreachable rather than raising: the
    panel must be able to show a dead node's row, and an exception here would make one
    unreachable host break the whole nodes page.
    """
    node = await nodes.get_node(session, node_id)
    expected = await apply.render_for_node(session, node)

    try:
        async with NodeConnection(apply.target_for(node, apply.settings())) as connection:
            health = await probe(connection, expected=expected)
    except NodeUnreachable as exc:
        return schemas.HealthResponse(
            node_id=node.id,
            reachable=False,
            healthy=False,
            running=[],
            missing=sorted(expected),
            drifted=[],
            # Empty rather than "everything": a node we could not reach has told us
            # nothing about what its containers are running, and reporting a guess as
            # a finding is the fault this milestone is about, one field over.
            stale=[],
            detail=str(exc),
        )

    return schemas.HealthResponse(
        node_id=node.id,
        reachable=health.reachable,
        healthy=health.healthy,
        running=health.running,
        missing=health.missing,
        drifted=health.drifted,
        stale=health.stale,
        detail=health.detail,
    )
