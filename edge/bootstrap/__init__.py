"""SSH to a node: install, place configuration, start, verify.

One of the two packages in this zone permitted to do I/O, and every operation in
it is initiated by the control plane — a node never dials us (core invariants §1).
"""

from edge.bootstrap.ssh import NodeConnection, NodeTarget, NodeUnreachable

__all__ = ["NodeConnection", "NodeTarget", "NodeUnreachable"]
