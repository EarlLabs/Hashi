"""Pure rendering for AmneziaWG — the node's end, and now a friend's device.

``render_server`` behaves exactly like every other transport's. The other two are the
interesting pair, and they are two rather than one on purpose:

* ``render_client`` REFUSES. There is no URI form of this protocol, and the contract
  requires that refusal to be explicit rather than a quietly malformed entry.
* ``render_client_config`` produces the friend-facing form that DOES exist: a complete
  wg-quick file. This is the serialisation backlog item 25 was blocked on, and item 26
  is where the contract grew the vocabulary to express it (``SubscriptionFormat``).

Together they are the honest answer to the charter's open question: not "this protocol
cannot reach a friend", but "it reaches them as a file, and here it is".
"""

import ipaddress
from collections.abc import Mapping, Sequence

from edge.egress import CLIENT_ROUTES, Egress, client_resolvers, wg_quick_egress
from edge.node import Credential, NodeView
from edge.registry import ClientConfig, ClientEntry
from edge.templating import environment_for
from edge.transports.amneziawg.meta import META

_TEMPLATES = environment_for(__file__)


class AmbiguousPeerRoute(Exception):
    """Two peers claim the same tunnel address, so one would silently lose its route."""


class MissingPeerMaterial(Exception):
    """A credential arrived without the client-scoped key material this transport needs."""


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
    *,
    egress: Egress = Egress.NONE,
    exit_via: str | None = None,
) -> str:
    """This end of the hop, authorising exactly ``clients`` as peers.

    ``egress`` says which way out packets decrypted onto this interface take — see
    ``edge/egress.py``. It defaults to ``NONE`` because the failure it guards is silent in
    exactly one direction: a hop end that masquerades locally is a friend in Russia
    exiting in Russia with every screen showing green, while a friend-facing tunnel with
    no exit is a friend who tells you at once that nothing loads.

    ``exit_via`` names the address that way out runs through, and this transport can
    honour it only when it is this interface's own — a kernel tunnel hands its packets to
    the node's routing stack and cannot re-originate them somewhere else. Anything else is
    refused rather than rendered, which is ``wg_quick_egress``'s decision and not a branch
    here.
    """
    plan = wg_quick_egress(
        egress,
        str(params["tunnel_address"]),
        exit_via,
        # What a FRIEND's own file tells their device to ask, so this node's rules can let
        # exactly that through and nothing else that is not on the internet — M23. The
        # same two sources ``render_client_config`` reads, passed to one function
        # (``egress.client_resolvers``) so the file and the firewall cannot disagree.
        client_dns=[str(entry) for entry in params.get("client_dns", ())],
        node_resolver=node.resolver,
    )

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
        # The peer's own address, unless this tunnel IS the node's way out — in which case
        # the far end is where everything goes and everything comes back from, and a
        # narrower route would have the interface drop a friend's traffic with nothing
        # logging it. The policy decides, not this renderer: see ``edge/egress.py``.
        route = plan.peer_route or peer_allowed_ips(address)

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
                # THIS PEER's pre-shared key, which is what a pre-shared key is: an
                # attribute of a pair. Rendering the node's own for every peer — which is
                # what this file did until M23 — put one symmetric key in every friend's
                # config on the node, so one leaked file exposed the layer protecting
                # everyone else's handshake and revoking that friend rotated nothing.
                #
                # The fallback has two consumers and neither is a friend issued today.
                # One is the ENTRY-TO-LEAF HOP: its peer is a node, its pre-shared key is
                # node-scoped and declared ``shared_between_peers``, and ``relay.py``
                # synthesises the peer from parameters alone — so the hop renders the
                # bytes it always rendered and this line is why. The other is a
                # credential minted before the per-pair declaration existed: that
                # friend's device already holds a file naming the node's key, and
                # refusing here would cut them off at the next apply rather than at the
                # next issue. ``render_client_config`` refuses for them instead, which
                # stops the shared key being handed out again.
                "preshared_key": secrets.get("peer_preshared_key")
                or params["preshared_key"],
                "allowed_ips": route,
                # Present only on the end that DIALS. On a node-to-node hop exactly
                # one end can dial — the other is behind a carrier NAT — so this is
                # set for one peer and absent for the other. See edge/relay.py.
                "endpoint": secrets.get("peer_endpoint"),
            }
        )

    return _TEMPLATES.get_template("server.j2").render(
        node=node,
        params=params,
        peers=peers,
        # The tunnel's own address decides the masqueraded source range and the source the
        # way out is routed from, so both come out of the node's record rather than out of
        # a constant.
        hooks=plan.hooks,
        table=plan.table,
    )


def _endpoint(address: str, port: object) -> str:
    """``address:port``, with an IPv6 literal bracketed.

    Unbracketed, an IPv6 endpoint is ambiguous with the port separator and the parser
    rejects the whole file. The node's address is operator-supplied and may be either
    family, so this is a real case rather than a hypothetical one.
    """
    try:
        if ipaddress.ip_address(address).version == 6:
            return f"[{address}]:{port}"
    except ValueError:
        # A hostname. Nothing to bracket.
        pass
    return f"{address}:{port}"


def _interface_name(display_name: str) -> str:
    """A wg-quick interface name derived from the node's operator-chosen name.

    ``awg-quick`` takes the interface name from the FILENAME and refuses a name it
    considers invalid before it ever reads the contents — so this is part of the
    serialisation, not cosmetics. Linux caps an interface name at 15 characters, and
    the operator's node name is free text, so it is slugged and truncated here.

    Derived from the node rather than from the friend, deliberately: a friend holding
    three files needs to tell the exits apart, and the file lands on their own device
    where the node's name is the useful label. Nothing about which person this is goes
    into the name.
    """
    slug = "".join(
        character if character.isalnum() else "-" for character in display_name.lower()
    ).strip("-")
    # 4 for the prefix leaves 11, and "hashi-" would leave too little to tell two
    # nodes apart.
    return f"awg-{slug[:11]}" if slug else "awg-node"


def render_client_config(
    node: NodeView,
    params: Mapping[str, object],
    credential: Credential,
) -> ClientConfig:
    """One friend's complete AmneziaWG configuration file.

    The serialisation this transport declares (``SubscriptionFormat.CLIENT_CONFIG_FILE``)
    and the thing backlog item 25 was blocked on. It is a file rather than a line
    because that is what this protocol family's configuration IS — see the package
    docstring and ``client.j2``.

    Pure, like every renderer here: the friend's own keypair arrives in ``credential``,
    the node's public half in ``params``, and nothing is generated inside.
    """
    secrets = credential.secrets
    private_key = secrets.get("peer_private_key")
    if not private_key:
        # Named rather than rendered blank. A file with an empty PrivateKey is
        # syntactically fine and produces a tunnel that never comes up, which a friend
        # reports as "your VPN does not work" with nothing to go on.
        raise MissingPeerMaterial(
            f"this credential carries no 'peer_private_key', so no {META.name} config "
            "can be built for it. The transport declares that material at CLIENT "
            "scope; a credential minted without it is the bug to fix, not this render."
        )

    preshared_key = secrets.get("peer_preshared_key")
    if not preshared_key:
        # Named rather than filled in from the node's own key. That fallback is what
        # ``render_server`` still does for this credential — deliberately, so the file
        # this friend already holds keeps working — but handing the shared key out AGAIN
        # is the defect itself, and a download is the moment to stop doing it. M23.
        raise MissingPeerMaterial(
            f"this credential carries no 'peer_preshared_key', so no {META.name} config "
            "can be built for it. The transport declares that material at CLIENT scope "
            "because a pre-shared key belongs to a PAIR; a credential minted before that "
            "declaration carries the node's own key, which is shared with every other "
            "friend on it. Rotate this credential's material rather than reissuing that."
        )

    # The friend's own address when they have one, falling back to the single address in
    # params for the point-to-point case — the same rule, and the same reason, as
    # render_server's peer loop.
    tunnel_address = str(secrets.get("peer_tunnel_address") or params["peer_tunnel_address"])

    content = _TEMPLATES.get_template("client.j2").render(
        params=params,
        peer={
            "private_key": private_key,
            "tunnel_address": tunnel_address,
            "preshared_key": preshared_key,
        },
        # Which resolver this device is told to ask, decided in one place shared by both
        # members of this family — ``edge/egress.py``, beside the node's own lookup
        # policy, because it is the same question asked one consumer further out.
        resolvers=client_resolvers(
            [str(entry) for entry in params.get("client_dns", ())],
            node.resolver,
            str(params["tunnel_address"]),
        ),
        # Which addresses this device sends into the tunnel, decided in the same
        # place as the resolver above and for the same reason — it is the node's own
        # egress policy, read from the friend's end. See ``CLIENT_ROUTES``: the IPv6
        # half names a family this node cannot carry, on purpose.
        routes=CLIENT_ROUTES,
        endpoint=_endpoint(node.address, params["port"]),
    )
    return ClientConfig(
        content=content,
        filename=f"{_interface_name(node.display_name)}.conf",
        # Plain text, not an invented type: no registered media type exists for a
        # wg-quick config, and a made-up one makes some clients offer to download the
        # file rather than import it.
        media_type="text/plain; charset=utf-8",
        display_label=node.display_name,
        country_label=node.location_label,
        node_id=node.id,
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
    "MissingPeerMaterial",
    "NotExpressibleAsUri",
    "render_client",
    "render_client_config",
    "render_server",
]
