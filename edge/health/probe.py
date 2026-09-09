"""Is this node serving? — and nothing else.

WHAT: an SSH probe that reports whether a node's data plane is up, whether the
      configuration on it matches what we last pushed, and whether the process that
      is running was started from that configuration — three questions, because M1
      proved the first two can both be yes while the node serves something else.
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

from edge.bootstrap.node_stack import config_path_for, digest_of, loaded_digests
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

    # Transport names whose container is running, on a config that is not the one we
    # would push. A SEPARATE field from ``drifted`` on purpose, and M1's second half.
    #
    # The field measurement of 2026-09-09 is what this exists for: a node whose config
    # on disk matched perfectly and whose daemon had never read it reported
    # ``drifted: []`` — a true answer to a question that does not establish the thing an
    # operator reads it as establishing. Nothing anywhere compared either the file or
    # the digest against what the PROCESS loaded.
    #
    # Not folded into ``drifted`` because the two name different faults with different
    # repairs: drift is somebody editing the node, staleness is an apply that did not
    # take. Reporting staleness as drift would make this report say "the file was
    # changed" about a file nobody touched — the same shape of true-but-misleading
    # answer the milestone is about.
    stale: list[str] = field(default_factory=list)

    # Operator-facing reason when the node is not healthy.
    detail: str | None = None

    @property
    def healthy(self) -> bool:
        """Reachable, everything expected is running the config we would push."""
        return self.reachable and not self.missing and not self.drifted and not self.stale


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
        # The digest each running container was CREATED with, not merely which services
        # are up — see ``node_stack.loaded_digests``. The weaker question is what let a
        # stale daemon report healthy for eight minutes on a real node.
        loaded = await loaded_digests(connection)
    except NodeUnreachable as exc:
        # A blocked or seized node accepts and hangs rather than refusing, so this
        # is the common failure rather than the rare one.
        return NodeHealth(reachable=False, detail=str(exc))

    health = NodeHealth(reachable=True, running=sorted(loaded))
    health.missing = sorted(set(expected) - set(loaded))

    for transport_name, config in expected.items():
        wanted = digest_of(config)

        if transport_name in loaded and loaded[transport_name] != wanted:
            # Up, and up on something else. A container from before this label existed
            # reports an empty digest and lands here too, which is correct: it is
            # provably not running the config we would push.
            health.stale.append(transport_name)

        # ``config_path_for``, never ``config_path``: the latter defaults to the Xray
        # JSON extension, so before M2 this looked for every transport's config at a
        # ``.json`` path. Latent only while the one live transport was an Xray one —
        # a WireGuard-family config is written ``.conf``, would never be found here,
        # and the node would be reported as permanently drifted. Carried over from M1
        # (docs/tracker/M1/carry-over.md) and fixed here because M2 is what makes it
        # bite.
        remote = await connection.read_file(config_path_for(transport_name))
        if remote is None:
            # Absent config is reported as drift rather than as "missing service":
            # the container may still be running on a config that is no longer on
            # disk, which is the state that survives a restart as an outage.
            health.drifted.append(transport_name)
        elif digest_of(remote) != wanted:
            health.drifted.append(transport_name)

    health.drifted.sort()
    health.stale.sort()

    if not health.healthy:
        health.detail = "; ".join(
            part
            for part in (
                f"not running: {', '.join(health.missing)}" if health.missing else "",
                f"configuration drifted: {', '.join(health.drifted)}" if health.drifted else "",
                f"still running an older configuration: {', '.join(health.stale)}"
                if health.stale
                else "",
            )
            if part
        )
    return health
