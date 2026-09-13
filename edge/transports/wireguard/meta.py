"""What `control` may know about plain WireGuard.

Three declarations carry the charter's three constraints on this protocol, and each is
a field the code reads rather than a sentence a reader might not: ``hop_capable``,
``blocked_by_inspection``, and a ``config_format`` of its own so the pinned data-plane
image and the upstream checker travel with the transport rather than being borrowed
from its obfuscated cousin.
"""

from edge.registry import (
    ConfigFormat,
    KeyKind,
    KeyScope,
    KeySpec,
    Layer4,
    PeerAddress,
    SubscriptionFormat,
    TransportMeta,
)

META = TransportMeta(
    name="wireguard",
    # UDP, like AmneziaWG. The family drives real decisions elsewhere — a UDP transport
    # needs explicit MTU handling, which the edge rulebook names as the "TLS works,
    # large downloads hang" trap.
    family="udp",
    # No TLS at all, and no impersonation of anything. It must not be given a
    # certificate and must not sit behind our Caddy.
    needs_tls=False,
    # The socket it binds, which is a different question from ``family`` above —
    # `control` reads this one to decide whether two transports on one node may
    # hold the same port number, and reads ``family`` for nothing at all.
    listens_on=frozenset({Layer4.UDP}),
    # 51820 is WireGuard's conventional port and is inside the range, but there is no
    # default: a fleet where every node listens on 51820 is a fleet you can enumerate
    # with one scan, and this protocol is already identifiable by its handshake.
    port_range=(1024, 65535),
    # Its OWN format, not AmneziaWG's. See ConfigFormat.WG_QUICK_PLAIN: sharing one
    # would mean this transport's configs were validated by the wrong binary and run by
    # someone else's daemon, and both would appear to work.
    config_format=ConfigFormat.WG_QUICK_PLAIN,
    key_material=(
        # STANDARD base64, the format `wg genkey` emits — the same encoding rule, and
        # the same reason for a separate KeyKind, as the AmneziaWG package.
        KeySpec(
            name="private_key",
            kind=KeyKind.X25519_KEYPAIR_BASE64,
            scope=KeyScope.NODE,
            public_name="public_key",
        ),
        # WireGuard's optional pre-shared key. Optional in the protocol, required here:
        # it adds a symmetric layer over the handshake, which is what limits the value
        # of traffic recorded now and attacked later.
        KeySpec(
            name="preshared_key",
            kind=KeyKind.SYMMETRIC_32_BASE64,
            scope=KeyScope.NODE,
            # Meaningful only on a hop, and this transport is never on one. Declared
            # False rather than omitted so the reason is on the record: there is no
            # second end to agree with, because there is never a second end.
            shared_between_peers=False,
        ),
        # Per-friend material. Deleting this row is what makes a revocation total for
        # this transport: no copy of it authorises anyone anywhere else.
        KeySpec(
            name="peer_private_key",
            kind=KeyKind.X25519_KEYPAIR_BASE64,
            scope=KeyScope.CLIENT,
            public_name="peer_public_key",
        ),
        # The contract requires a client-scoped identity under the name "subject".
        KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
    ),
    # A config file, never a link — the same answer as AmneziaWG's, for the same reason:
    # this protocol's configuration IS a file. Delivered by the second subscription
    # format (item 27).
    subscription_formats=frozenset({SubscriptionFormat.CLIENT_CONFIG_FILE}),
    # THE constraint this package exists to keep. The entry-to-leaf hop crosses the
    # Russian border, and plain WireGuard is protocol-blocked there — a hop built on it
    # would leave two nodes each holding a valid config and no tunnel between them, with
    # nothing in any log to say why. Refused in edge/relay.py before either end is
    # written.
    hop_capable=False,
    # And the second: identifiable on the wire, by design. It has no camouflage — that
    # is what AmneziaWG exists for — so the panel must never present it to a friend as a
    # working exit from a filtering network.
    blocked_by_inspection=True,
    # Every friend on this transport holds a tunnel address of their own, drawn from the
    # room inside the interface's own address. AllowedIPs is this protocol's
    # authorisation list AND its routing table, so two friends on one address is not a
    # duplicate the daemon merges — it is the second silently taking over the first's
    # return path, which ``render_server`` refuses rather than renders. This transport is
    # never on a hop (``hop_capable`` is False), so its consumers are always people.
    peer_address=PeerAddress(name="peer_tunnel_address", within="tunnel_address"),
)
