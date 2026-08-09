"""What `control` may know about AmneziaWG.

The declaration that matters here is
``subscription_formats={SubscriptionFormat.CLIENT_CONFIG_FILE}`` — a config file and
NOT the v1 URI list, which is why the derived ``subscription_expressible`` is still
False. See the package docstring. Everything else follows the same contract as any
other transport.
"""

from edge.registry import (
    ConfigFormat,
    KeyKind,
    KeyScope,
    KeySpec,
    SubscriptionFormat,
    TransportMeta,
)

META = TransportMeta(
    name="amneziawg",
    # UDP, unlike the two VLESS transports. Recorded because the family drives real
    # decisions elsewhere: a UDP transport needs explicit MTU handling, which the edge
    # rulebook names as the "TLS works, large downloads hang" trap.
    family="udp",
    # No TLS at all — it is obfuscated UDP, not a TLS impersonation. So it must not be
    # given a certificate and must not sit behind our Caddy.
    needs_tls=False,
    # WireGuard's conventional port is 51820; the range stays wide so an operator can
    # place the hop wherever it is least conspicuous on a given host.
    port_range=(1024, 65535),
    # Declared explicitly rather than left to the default: a transport validated
    # by the wrong checker passes for the wrong reason.
    config_format=ConfigFormat.WG_QUICK,
    key_material=(
        # STANDARD base64, not Reality's URL-safe unpadded form. `wg genkey`'s format
        # is the only one this daemon accepts, which is why the vocabulary has two
        # kinds for one primitive — see KeyKind.X25519_KEYPAIR_BASE64.
        KeySpec(
            name="private_key",
            kind=KeyKind.X25519_KEYPAIR_BASE64,
            scope=KeyScope.NODE,
            public_name="public_key",
        ),
        # WireGuard's optional pre-shared key, adding a symmetric layer on top of the
        # handshake. Used here because this hop crosses a border where the adversary
        # records traffic it cannot yet read.
        # Symmetric, so both ends of a hop must carry the SAME value — declared here
        # because `control` mints each end separately and has no way to know which of
        # a transport's values are symmetric without being told. Two independently
        # minted pre-shared keys give two valid files and a handshake that never
        # completes.
        KeySpec(
            name="preshared_key",
            kind=KeyKind.SYMMETRIC_32_BASE64,
            scope=KeyScope.NODE,
            shared_between_peers=True,
        ),
        # Peer-scoped material. "CLIENT" in the contract's vocabulary means "one per
        # consumer of this transport"; for this transport the consumer is another NODE
        # rather than a friend, and the contract does not need to know the difference.
        KeySpec(
            name="peer_private_key",
            kind=KeyKind.X25519_KEYPAIR_BASE64,
            scope=KeyScope.CLIENT,
            public_name="peer_public_key",
        ),
        # The contract requires a client-scoped identity under the name "subject".
        KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
    ),
    # THE declaration this package exists to demonstrate, in its second and honest
    # form. AmneziaWG is a config FILE, not a link — so it declares the file format
    # and NOT the v1 URI list, rather than declaring "nothing".
    #
    # Under the old boolean those two answers were the same answer, and that is what
    # kept item 25 blocked: a transport could say "I am not a URI" and had no way to
    # say what it IS. It says it here. ``subscription_expressible`` is still False
    # (derived — see TransportMeta), so `control` still refuses to offer this to
    # friends until delivery of the second format lands as item 27. The serialiser
    # existing is not the same as the endpoint handing it over, and this declaration
    # does not pretend otherwise.
    subscription_formats=frozenset({SubscriptionFormat.CLIENT_CONFIG_FILE}),
)
