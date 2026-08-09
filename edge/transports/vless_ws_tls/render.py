"""Pure rendering for VLESS over WebSocket behind TLS.

The shape is deliberately identical to the first transport's ``render.py``: same
two functions, same signatures, same purity. Nothing here imports the other
transport and nothing here was added to the registry to make it fit — that is the
result the second transport was built to demonstrate.
"""

from collections.abc import Mapping, Sequence
from urllib.parse import quote, urlencode

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
) -> str:
    """The node's complete Xray config, authorising exactly ``clients``."""
    return _TEMPLATES.get_template("server.j2").render(
        node=node,
        params=params,
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
