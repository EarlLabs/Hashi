"""What `control` may know about VLESS + WS + TLS.

Note what is NOT here compared to the first transport: no keypair. This transport
needs a random path and a client id, both of kinds ``control`` already generates —
so it cost `control` zero lines, which is the fourth criterion in one sentence.
"""

from edge.registry import KeyKind, KeyScope, KeySpec, TransportMeta

META = TransportMeta(
    name="vless-ws-tls",
    family="tcp-tls",
    # Real TLS with a real certificate, unlike Reality's borrowed handshake. The
    # node stack supplies the certificate; this transport only points at it.
    needs_tls=True,
    port_range=(443, 65535),
    key_material=(
        # The WebSocket path. Random, because a guessable path turns the node into
        # something an active prober can confirm: request the path, and a VLESS
        # endpoint answers differently than the camouflage site would.
        KeySpec(name="ws_path_secret", kind=KeyKind.TOKEN_32, scope=KeyScope.NODE),
        KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
    ),
    subscription_expressible=True,
)
