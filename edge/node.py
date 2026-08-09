"""What a renderer is allowed to know about a node and a friend.

WHAT: the two immutable value objects every transport renderer takes as input —
      ``NodeView`` (one node, as configuration sees it) and ``Credential`` (one
      friend's material for one node × transport).
WHY:  ``edge`` is a pure library and must never import ``control``, so it cannot
      take a SQLAlchemy model as a parameter. Something has to describe the shape
      of a node, and it has to live on this side of the boundary. These types are
      that description: ``control`` projects its rows into them, and from here
      down there is no database, no session and nothing lazy to load.
      *The second reason is testability:* a golden-file test needs to construct a
      node in one literal, without a database.
HOW:  frozen dataclasses, plain data only. No behaviour, no I/O, no defaults that
      encode a policy — a default country or port here would be exactly the
      hardcoded value core invariants §6 forbids.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeView:
    """One node, reduced to what rendering a config legitimately needs.

    Deliberately does NOT carry: health, state, provider, credentials for other
    transports, or anything about who is connected. A renderer that could read
    those would eventually branch on them.
    """

    # Stable identifier from the control database. Carried through into
    # ``ClientEntry.node_id`` so `control` can order, filter and revoke entries
    # without ever parsing the serialised URI.
    id: str

    # The address a client dials. A hostname or an IP — the renderer does not
    # care which, and must never inspect it (no geo lookup, no "is this an IP"
    # branch). It is data from the node record, nothing more.
    address: str

    # The exit country as the OPERATOR labelled it, e.g. "Netherlands". Used for
    # the subscription's display text. Never derived from ``address``: a geo
    # lookup would make the label a property of the hosting provider's database
    # rather than of the operator's intent, and it would silently change when a
    # provider re-assigns an IP range.
    location_label: str

    # Operator-facing name for the node itself, e.g. "leaf-ams-1". Shown in the
    # panel and used to compose a client-visible label.
    display_name: str


@dataclass(frozen=True)
class Credential:
    """One friend's material for exactly one node × one transport.

    Scoped that narrowly on purpose: the charter's sixth criterion is that
    revoking a friend stops them on *every* node and *every* protocol. That is
    only expressible if each (friend, node, transport) triple has its own
    material, so removing one row cannot leave a working copy elsewhere.
    """

    # Opaque per-friend, per-node, per-transport identity. What it *means* is the
    # transport's business (for VLESS it is the client UUID); `control` stores it
    # and hands it back without interpreting it.
    subject: str

    # The rest of this friend's material for this transport, keyed by the name
    # the transport's own ``Params`` / URI builder expects. Values are already
    # decrypted by `control` at the point of use — a renderer never decrypts,
    # because decryption is I/O and this zone is pure.
    secrets: Mapping[str, str] = field(default_factory=dict)
