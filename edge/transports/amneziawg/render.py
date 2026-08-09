"""Pure rendering for AmneziaWG.

``render_server`` behaves exactly like every other transport's. ``render_client`` is
the interesting one: it REFUSES, because this transport has no URI form, and the
contract requires that refusal to be explicit rather than a quietly malformed entry.
"""

import ipaddress
from collections.abc import Mapping, Sequence

from edge.node import Credential, NodeView
from edge.registry import ClientEntry
from edge.templating import environment_for
from edge.transports.amneziawg.meta import META

_TEMPLATES = environment_for(__file__)


class AmbiguousPeerRoute(Exception):
    """Two peers claim the same tunnel address, so one would silently lose its route."""


class NotExpressibleAsUri(Exception):
    """This transport cannot be serialised into the v1 subscription format.

    A distinct exception rather than returning a broken ``ClientEntry``: a caller that
    reached this point has already ignored ``META.subscription_expressible``, and the
    failure must be loud. `control` checks the declaration up front and never gets
    here — this is the backstop, not the mechanism.
    """


def peer_allowed_ips(peer_tunnel_address: str) -> str:
    """The single host route this peer is allowed to send us.

    A /32 (or /128) derived from the peer's tunnel address, never the operator's whole
    prefix and never a default route. Narrow on purpose: AllowedIPs is WireGuard's
    authorisation list as well as its routing table, so a wide entry here lets the far
    end source traffic as any address in the range.
    """
    interface = ipaddress.ip_interface(peer_tunnel_address)
    return f"{interface.ip}/{interface.ip.max_prefixlen}"


def render_server(
    node: NodeView,
    params: Mapping[str, object],
    clients: Sequence[Credential] = (),
) -> str:
    """This end of the hop, authorising exactly ``clients`` as peers."""
    peers = []
    seen_routes: set[str] = set()
    for credential in clients:
        secrets = credential.secrets

        # Each peer's own tunnel address when it has one, falling back to the single
        # address in params for the point-to-point case (one entry node, one leaf),
        # which is the common shape.
        address = str(
            secrets.get("peer_tunnel_address") or params["peer_tunnel_address"]
        )
        route = peer_allowed_ips(address)

        # AllowedIPs is WireGuard's authorisation list AND its routing table, so two
        # peers claiming one address is not a duplicate that the daemon merges — the
        # later peer silently takes over the route, and the earlier one stops receiving
        # traffic while still looking configured. Refused rather than rendered.
        if route in seen_routes:
            raise AmbiguousPeerRoute(
                f"two peers are configured with the tunnel address {address!r}. "
                "AllowedIPs is both the authorisation list and the routing table, so "
                "the second would silently take over the first's route. Give each peer "
                "its own tunnel address."
            )
        seen_routes.add(route)

        peers.append(
            {
                # Opaque subject only, never a nickname — this is a comment in a file
                # on a node, and it must not become a record of who is on the far end.
                "label": f"peer-{credential.subject[:8]}",
                "public_key": secrets["peer_public_key"],
                "allowed_ips": route,
                # Present only on the end that DIALS. On a node-to-node hop exactly
                # one end can dial — the other is behind a carrier NAT — so this is
                # set for one peer and absent for the other. See edge/relay.py.
                "endpoint": secrets.get("peer_endpoint"),
            }
        )

    return _TEMPLATES.get_template("server.j2").render(
        node=node, params=params, peers=peers
    )


def render_client(
    node: NodeView,
    params: Mapping[str, object],
    credential: Credential,
) -> ClientEntry:
    """Always raises. AmneziaWG is a config file, not a link.

    This is the honest answer to the charter's open question rather than a workaround
    for it. Producing something URI-shaped here would put a line in a friend's
    subscription that their client cannot parse — and the symptom would be "the whole
    subscription is broken", not "one entry is unsupported".
    """
    raise NotExpressibleAsUri(
        f"{META.name} has no client-entry URI form, so it cannot appear in a v1 "
        "subscription. It is used on the entry-to-leaf hop, where the config is "
        "consumed by a node rather than by a friend's device. A friend-facing variant "
        "needs a second subscription format — backlog item 25."
    )


__all__ = [
    "META",
    "AmbiguousPeerRoute",
    "NotExpressibleAsUri",
    "render_client",
    "render_server",
]
