"""What `control` may know about VLESS + WS + TLS.

Note what is NOT here compared to the first transport: no keypair. This transport
needs a random path and a client id, both of kinds ``control`` already generates —
so it cost `control` zero lines, which is the fourth criterion in one sentence.
"""

from edge.registry import (
    ConfigFormat,
    KeyKind,
    KeyScope,
    KeySpec,
    Layer4,
    SubscriptionFormat,
    TransportMeta,
)

META = TransportMeta(
    name="vless-ws-tls",
    family="tcp-tls",
    # Real TLS with a real certificate, unlike Reality's borrowed handshake. The
    # node stack supplies the certificate; this transport only points at it.
    needs_tls=True,
    # The socket it binds, which is a different question from ``family`` above —
    # `control` reads this one to decide whether two transports on one node may
    # hold the same port number, and reads ``family`` for nothing at all.
    listens_on=frozenset({Layer4.TCP}),
    port_range=(443, 65535),
    # Declared explicitly rather than left to the default: a transport validated
    # by the wrong checker passes for the wrong reason.
    config_format=ConfigFormat.XRAY_JSON,
    key_material=(
        # The WebSocket path. Random, because a guessable path turns the node into
        # something an active prober can confirm: request the path, and a VLESS
        # endpoint answers differently than the camouflage site would.
        KeySpec(name="ws_path_secret", kind=KeyKind.TOKEN_32, scope=KeyScope.NODE),
        KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
    ),
    # A VLESS URI, same as Reality's — one format, and only that one.
    subscription_formats=frozenset({SubscriptionFormat.V1_URI_LIST}),
)
