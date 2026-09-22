"""Plain WireGuard — first-class, shipped, and deliberately not everywhere.

The charter names WireGuard and AmneziaWG both first-class in phase 1's data plane.
AmneziaWG has been here since item 16; plain WireGuard was missing from the tree
entirely, which is the gap backlog item 28 closes.

It is here because it is the right choice on a network that is not filtering: it is
the fastest and best-supported of the three, every platform has a first-party client,
and most of the fleet's exits are abroad. It is NOT here because it is safe from
inspection — it is the opposite, and this package says so twice, in the only two ways
that cannot be ignored:

* ``hop_capable=False`` — never on the entry-to-leaf hop, in any phase. That hop
  crosses the Russian border by definition, and a protocol-blocked transport there
  takes the whole topology down while both ends look perfectly configured. Enforced in
  ``edge/relay.py`` before either end of a hop is written, not by this comment.
* ``blocked_by_inspection=True`` — WireGuard's handshake has a fixed, trivially
  fingerprinted shape with no camouflage at all. A network that inspects traffic
  identifies it on the first packet. Declared machine-readably so the panel can refuse
  to offer it to a user as a working exit, rather than leaving that to whoever
  remembers the charter.

Where it is used is a user's link to an exit abroad, over a network that is not
filtering — and, being a WireGuard-family transport, it reaches them as a config FILE
rather than a URI, through the second subscription format (items 26 and 27).
"""
