"""Pure rendering for VLESS over WebSocket behind TLS.

The shape is deliberately identical to the first transport's ``render.py``: same
two functions, same signatures, same purity. Nothing here imports the other
transport and nothing here was added to the registry to make it fit — that is the
result the second transport was built to demonstrate.
"""

from collections.abc import Mapping, Sequence
from urllib.parse import quote, urlencode

from edge.egress import Egress, exit_origin, lookup_resolver
from edge.node import Credential, NodeView
from edge.registry import ClientEntry
from edge.templating import environment_for
from edge.transports.vless_ws_tls.meta import META
from edge.transports.vless_ws_tls.params import ws_path

_TEMPLATES = environment_for(__file__)


def render_server(
    node: NodeView,
    params: Mapping[str, object],
    clients: Sequence[Credential] = (),
    *,
    egress: Egress = Egress.NONE,
    exit_via: str | None = None,
) -> str:
    """The node's complete Xray config, authorising exactly ``clients``.

    ``egress`` and ``exit_via`` together say which way out a friend's traffic takes. This
    transport renders no forwarding or NAT rule for either, and that is a statement about
    the protocol rather than an omission: Xray is a userspace proxy — it terminates a
    connection and ORIGINATES a new one from the node itself, so no packet of a friend's
    is ever forwarded by the kernel and there is nothing for a FORWARD or NAT rule to act
    on. What decides where that new connection goes is the address it is opened FROM, and
    that is the outbound's business — M3.

    So on an entry node with a hop (``Egress.HOP`` plus the hop's near address) the config
    carries exactly ONE outbound, bound to that address. There is no second outbound to
    fall back to, which is decision 3 expressed structurally: when the hop is down the
    connection cannot be opened, and a friend gets no exit rather than a Russian one.
    With no hop, nothing changes — the same direct outbound as before, byte for byte.

    M16 is the part of that ``sendThrough`` cannot reach, and it is the first transport's
    reasoning unchanged: a friend's client sends a NAME, the outbound resolves it before it
    dials, and under a hop that lookup goes through the hop to the resolver on the node's
    record (``node.resolver``) — or the node is refused, never given the host's resolver.
    """
    return _TEMPLATES.get_template("server.j2").render(
        node=node,
        params=params,
        # The address every outgoing connection is opened from, or ``None`` for this
        # node's own route. Checked by ``edge/egress.py`` rather than here: that a policy
        # and an address agree is a question about the policy, not about this protocol.
        exit_origin=exit_origin(egress, exit_via),
        # Where the names in those connections are looked up — M16. ``None`` with no hop;
        # refused, never defaulted, on a node with one. See ``edge/egress.py``.
        resolver=lookup_resolver(egress, node.resolver),
        ws_path=ws_path(str(params["ws_path_secret"])),
        clients=[
            # Opaque subject only — see the note in the first transport's renderer.
            {"subject": credential.subject, "label": f"c-{credential.subject[:8]}"}
            for credential in clients
        ],
    )


def render_client(
    node: NodeView,
    params: Mapping[str, object],
    credential: Credential,
) -> ClientEntry:
    """One friend's client entry, as a finished VLESS-over-WebSocket URI."""
    query = urlencode(
        {
            "encryption": "none",
            "security": "tls",
            "type": "ws",
            "sni": params["server_name"],
            # Both the Host header and the path are part of how the endpoint is
            # addressed; a client that omits either reaches the camouflage site
            # instead of the tunnel, which is the intended behaviour for anyone
            # who does not hold this URI.
            "host": params["server_name"],
            "path": ws_path(str(params["ws_path_secret"])),
        },
        quote_via=quote,
    )
    entry = f"vless://{credential.subject}@{node.address}:{params['port']}?{query}"
    return ClientEntry(
        entry=entry,
        display_label=node.display_name,
        country_label=node.location_label,
        node_id=node.id,
    )


__all__ = ["META", "render_client", "render_server"]
