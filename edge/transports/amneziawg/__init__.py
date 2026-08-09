"""AmneziaWG — obfuscated WireGuard, for the entry→leaf hop.

This package settles the debt named in the backlog when AmneziaWG was moved out of
M1 (revision 2, §1.D): does the transport contract survive a protocol family that
CANNOT be expressed as a URI?

It does, and the mechanism is ``subscription_expressible = False``. AmneziaWG is a
config *file*, not a link, so it cannot ride in a base64 list of client-entry URIs.
Rather than letting that be discovered mid-render — which would hand a friend a
subscription quietly missing a node — the transport declares the limitation, and
`control` refuses out loud to enable it on a node it would deliver to friends
(``NotDeliverable``, tested in tests/control/).

Where it IS used is the entry→leaf hop, where the config is consumed by a NODE
rather than by a friend's device. There, the "how does it reach a phone in one
link" question does not arise, and its obfuscation is exactly what the hop needs:
that hop crosses the Russian border, and plain WireGuard is protocol-blocked by
TSPU. See edge/relay.py.

The friend-facing variant remains backlog item 25 and remains blocked on a second
subscription format — this package does not quietly unblock it.
"""
