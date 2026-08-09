"""What `control` may know about VLESS + Reality without knowing it is Reality.

WHAT: this transport's ``TransportMeta`` — name, family, TLS need, legal port
      range and the key material it wants minted for it.
WHY:  the declaration is how the charter's fourth criterion is kept. `control`
      reads ``key_material`` and generates an X25519 keypair and a short id
      because the *kinds* say so, never because it recognised this protocol.
HOW:  one module-level ``META``. ``edge.registry.discover()`` imports exactly this.
"""

from edge.registry import KeyKind, KeyScope, KeySpec, TransportMeta

META = TransportMeta(
    name="vless-reality",
    # Reality is a TLS-shaped TCP transport: it borrows a real site's handshake.
    family="tcp-tls",
    # It terminates TLS itself, from the decoy's certificate chain — it must NOT
    # be given one of ours, and it must not sit behind our Caddy.
    needs_tls=True,
    # 443 is included deliberately (Reality is *supposed* to look like HTTPS) but
    # is not a default: a fleet where every node listens on 443 is still a fleet
    # you can enumerate by probing 443. The operator picks per node.
    port_range=(443, 65535),
    key_material=(
        # The server's Reality private key. Its public half goes into every
        # client entry as `pbk`, so the generator yields both.
        KeySpec(name="private_key", kind=KeyKind.X25519_KEYPAIR, scope=KeyScope.NODE),
        # Reality's short id: a client that presents an unknown one is served the
        # decoy site, which is exactly the behaviour that makes probing useless.
        KeySpec(name="short_id", kind=KeyKind.SHORT_ID, scope=KeyScope.NODE),
        # One VLESS client id per friend, per node. Client-scoped, which is what
        # makes the charter's sixth criterion (total revocation) expressible:
        # deleting this row cannot leave a working copy on another node.
        KeySpec(name="subject", kind=KeyKind.UUID4, scope=KeyScope.CLIENT),
    ),
    # A VLESS URI carries a fragment, so an externally appended display label
    # survives — this transport is deliverable in the v1 subscription format.
    subscription_expressible=True,
)
