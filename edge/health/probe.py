"""Is this node serving? — and nothing else.

WHAT: an SSH probe that reports whether a node's data plane is up and whether its
      configuration matches what we last pushed.
WHY:  backlog item 13. The control plane polls; a node never reports in (core
      invariants §1) — an outbound connection from a node to a fixed endpoint is
      both a fingerprint for a censor and a path back to the control plane if the
      node is seized.
HOW:  every field of ``NodeHealth`` is about the NODE. There is deliberately no
      field, and no code path that could produce one, for how many clients are
      connected, which addresses reached it, or how much traffic it carried. The
      charter's no-logging rule covers health: health means "is this node serving",
      never "who used it".
"""

import logging
from dataclasses import dataclass, field

from edge.bootstrap.node_stack import config_path, digest_of, running_services
from edge.bootstrap.ssh import NodeConnection, NodeUnreachable

logger = logging.getLogger(__name__)


@dataclass
class NodeHealth:
    """What a probe can truthfully say about a node."""

    reachable: bool

    # Transport names whose container is running on the node.
    running: list[str] = field(default_factory=list)

    # Transport names we expected to be running and which are not.
    missing: list[str] = field(default_factory=list)

    # Transport names whose config on the node differs from a fresh render.
    #
    # Only meaningful because rendering is deterministic: a differing digest means
    # someone or something changed the node, not that we rendered differently.
    drifted: list[str] = field(default_factory=list)

    # Operator-facing reason when the node is not healthy.
    detail: str | None = None

    @property
    def healthy(self) -> bool:
        """Reachable, everything expected is running, and nothing has drifted."""
        return self.reachable and not self.missing and not self.drifted


async def probe(
    connection: NodeConnection, *, expected: dict[str, str]
) -> NodeHealth:
    """Probe one node.

    ``expected`` maps transport name to the config we believe is on the node, so
    this function does no rendering and needs no database — the caller renders and
    passes the result in, which keeps the comparison honest and this module pure of
    everything but SSH.
    """
    try:
        running = await running_services(connection)
    except NodeUnreachable as exc:
        # A blocked or seized node accepts and hangs rather than refusing, so this
        # is the common failure rather than the rare one.
        return NodeHealth(reachable=False, detail=str(exc))

    health = NodeHealth(reachable=True, running=running)
    health.missing = sorted(set(expected) - set(running))

    for transport_name, config in expected.items():
        remote = await connection.read_file(config_path(transport_name))
        if remote is None:
            # Absent config is reported as drift rather than as "missing service":
            # the container may still be running on a config that is no longer on
            # disk, which is the state that survives a restart as an outage.
            health.drifted.append(transport_name)
        elif digest_of(remote) != digest_of(config):
            health.drifted.append(transport_name)

    health.drifted.sort()

    if not health.healthy:
        health.detail = "; ".join(
            part
            for part in (
                f"not running: {', '.join(health.missing)}" if health.missing else "",
                f"configuration drifted: {', '.join(health.drifted)}" if health.drifted else "",
            )
            if part
        )
    return health
