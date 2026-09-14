"""Pure rendering for plain WireGuard.

Three functions, and the middle one is the interesting one:

* ``render_server`` — this node's interface, authorising exactly the given friends.
* ``render_client`` — REFUSES. There is no URI form of this protocol, and the contract
  requires that refusal to be explicit rather than a quietly malformed entry.
* ``render_client_config`` — the friend-facing form that does exist: a complete
  wg-quick file, delivered by the second subscription format (items 26 and 27).

Deliberately close to the AmneziaWG package in shape and deliberately NOT shared with
it. The two protocols agree on a file format and disagree on everything that matters
here — one has obfuscation and may cross the border, the other has neither — and a
shared renderer would be one `if` away from rendering the wrong one of them.
"""

import ipaddress
from collections.abc import Mapping, Sequence

from edge.egress import CLIENT_ROUTES, Egress, client_resolvers, wg_quick_egress
from edge.node import Credential, NodeView
from edge.registry import ClientConfig, ClientEntry
from edge.templating import environment_for
from edge.transports.wireguard.meta import META

_TEMPLATES = environment_for(__file__)


class AmbiguousPeerRoute(Exception):
    """Two peers claim one tunnel address, so one would silently lose its route."""


class MissingPeerMaterial(Exception):
    """A credential arrived without the client-scoped key material this transport needs."""


class NotExpressibleAsUri(Exception):
    """This transport has no client-entry URI form.

    A distinct exception rather than a broken ``ClientEntry``: a caller that reached
    here has already ignored ``META.subscription_formats``, and the failure must be loud.
    """


def peer_allowed_ips(peer_tunnel_address: str) -> str:
    """The single host route this peer is allowed to send us.

    A /32 (or /128) derived from the peer's own tunnel address — never the operator's
    whole prefix and never a default route. AllowedIPs is WireGuard's authorisation list
    as well as its routing table, so a wide entry lets that peer source traffic as any
    address in the range.
    """
    interface = ipaddress.ip_interface(peer_tunnel_address)
    return f"{interface.ip}/{interface.ip.max_prefixlen}"


def _endpoint(address: str, port: object) -> str:
    """``address:port``, with an IPv6 literal bracketed.

    Unbracketed, an IPv6 endpoint is ambiguous with the port separator and the parser
    rejects the whole file. A node's address is operator-supplied and may be either
    family, so this is a real case rather than a hypothetical one.
    """
    try:
        if ipaddress.ip_address(address).version == 6:
            return f"[{address}]:{port}"
    except ValueError:
        pass  # a hostname, which needs no bracketing
    return f"{address}:{port}"


def _interface_name(display_name: str) -> str:
    """A wg-quick interface name derived from the node's operator-chosen name.

    ``wg-quick`` takes the interface name from the FILENAME and refuses a name it
    considers invalid before it ever reads the contents, so this is part of the
    serialisation rather than cosmetics. Linux caps an interface name at 15 characters,
    and a node's name is free text, so it is slugged and truncated.

    Derived from the node, never from the friend: a friend holding three files needs to
    tell the exits apart, and nothing about which person this is belongs in a filename.
    """
    slug = "".join(
        character if character.isalnum() else "-" for character in display_name.lower()
    ).strip("-")
    return f"wg-{slug[:12]}" if slug else "wg-node"


def render_server(
    node: NodeView,
    params: Mapping[str, object],
    clients: Sequence[Credential] = (),
    *,
    egress: Egress = Egress.NONE,
    exit_via: str | None = None,
) -> str:
    """This node's interface, authorising exactly ``clients``.

    ``egress`` says which way out packets decrypted onto this interface take — see
    ``edge/egress.py``. It defaults to ``NONE``: no exit at all beats a quiet local one,
    and a caller that has not thought about it should get the answer that fails loudly
    rather than the one that fails silently.

    ``exit_via`` names the address that way out runs through. This transport can honour it
    only for its own interface — a kernel tunnel hands its packets to the node's routing
    stack and cannot re-originate them somewhere else — and this one never carries a hop
    at all (``hop_capable`` is False, because the border it would cross identifies it). So
    on an entry node whose exit is a hop it refuses, which is ``wg_quick_egress``'s
    decision and not a branch here.

    An empty sequence renders a valid interface that authorises nobody — the correct
    state for a node whose last friend was just revoked, and not an error. If it were,
    the final revocation would produce a config the daemon refuses and the node would
    fail to restart, taking out everyone still on its other transports.
    """
    plan = wg_quick_egress(egress, str(params["tunnel_address"]), exit_via)

    peers = []
    seen_routes: set[str] = set()
    for credential in clients:
        secrets = credential.secrets
        address = str(secrets.get("peer_tunnel_address") or params["peer_tunnel_address"])
        # The peer's own address, unless this tunnel IS the node's way out — see the same
        # line, and the same reasoning, in the obfuscated member of this family.
        route = plan.peer_route or peer_allowed_ips(address)

        # Two peers on one address is not a duplicate the daemon merges: the later peer
        # silently takes over the route and the earlier one stops receiving traffic while
        # still looking configured. Refused rather than rendered.
        if route in seen_routes:
            raise AmbiguousPeerRoute(
                f"two peers are configured with the tunnel address {address!r}. "
                "AllowedIPs is both the authorisation list and the routing table, so the "
                "second would silently take over the first's route. Give each peer its "
                "own tunnel address."
            )
        seen_routes.add(route)

        public_key = secrets.get("peer_public_key")
        if not public_key:
            raise MissingPeerMaterial(
                "a credential for this transport carries no 'peer_public_key', so the "
                "node cannot authorise it. The transport declares that material at "
                "CLIENT scope; a credential minted without it is the bug to fix."
            )

        peers.append(
            {
                # Opaque subject only, never a nickname: this is a comment in a file on a
                # node, and it must not become a record of who is on the far end.
                "label": f"peer-{credential.subject[:8]}",
                "public_key": public_key,
                # THIS PEER's pre-shared key. A pre-shared key is an attribute of a pair,
                # and rendering the node's own for every peer — which is what this file did
                # until M23 — gave every friend on a node the same symmetric key, so one
                # leaked config exposed the layer protecting everyone else's handshake and
                # revoking that friend rotated nothing. Measured on the real leaf, on the
                # obfuscated member of this family, from this identical line.
                #
                # The fallback is for a credential minted before the per-pair declaration
                # existed and nothing else: that friend's device already holds a file
                # naming the node's key, so refusing here would cut them off at the next
                # apply rather than at the next issue. ``render_client_config`` refuses
                # for them instead, which stops the shared key being handed out again.
                "preshared_key": secrets.get("peer_preshared_key")
                or params["preshared_key"],
                "allowed_ips": route,
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


def render_client_config(
    node: NodeView,
    params: Mapping[str, object],
    credential: Credential,
) -> ClientConfig:
    """One friend's complete WireGuard configuration file.

    Pure, like every renderer here: the friend's own keypair arrives in ``credential``,
    the node's public half in ``params``, and nothing is generated inside.
    """
    secrets = credential.secrets
    private_key = secrets.get("peer_private_key")
    if not private_key:
        # Named rather than rendered blank: a file with an empty PrivateKey is
        # syntactically fine and produces a tunnel that never comes up, which a friend
        # reports as "your VPN does not work" with nothing to go on.
        raise MissingPeerMaterial(
            f"this credential carries no 'peer_private_key', so no {META.name} config "
            "can be built for it. The transport declares that material at CLIENT scope; "
            "a credential minted without it is the bug to fix, not this render."
        )

    preshared_key = secrets.get("peer_preshared_key")
    if not preshared_key:
        # Named rather than filled in from the node's own key. ``render_server`` still
        # does fall back for this credential, so the file the friend already holds keeps
        # working — but handing the shared key out AGAIN is the defect itself, and a
        # download is the moment to stop doing it. M23.
        raise MissingPeerMaterial(
            f"this credential carries no 'peer_preshared_key', so no {META.name} config "
            "can be built for it. The transport declares that material at CLIENT scope "
            "because a pre-shared key belongs to a PAIR; a credential minted before that "
            "declaration carries the node's own key, which is shared with every other "
            "friend on it. Rotate this credential's material rather than reissuing that."
        )

    tunnel_address = str(secrets.get("peer_tunnel_address") or params["peer_tunnel_address"])

    return ClientConfig(
        content=_TEMPLATES.get_template("client.j2").render(
            params=params,
            peer={
                "private_key": private_key,
                "tunnel_address": tunnel_address,
                "preshared_key": preshared_key,
            },
            # Which resolver this device is told to ask, decided in one place shared by
            # both members of this family — ``edge/egress.py``, beside the node's own
            # lookup policy, because it is the same question one consumer further out.
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
        ),
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
    """Always raises. WireGuard is a config file, not a link."""
    raise NotExpressibleAsUri(
        f"{META.name} has no client-entry URI form, so it cannot appear in a v1 "
        "subscription. It is delivered as a configuration file instead — see "
        "render_client_config and the second subscription format."
    )


__all__ = [
    "META",
    "AmbiguousPeerRoute",
    "MissingPeerMaterial",
    "NotExpressibleAsUri",
    "peer_allowed_ips",
    "render_client",
    "render_client_config",
    "render_server",
]
