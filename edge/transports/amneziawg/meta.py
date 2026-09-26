"""What `control` may know about AmneziaWG.

The declaration that matters here is
``subscription_formats={SubscriptionFormat.CLIENT_CONFIG_FILE}`` — a config file and
NOT the v1 URI list, which is why the derived ``subscription_expressible`` is still
False. See the package docstring. Everything else follows the same contract as any
other transport.
"""

from edge.registry import (
    ConfigFormat,
    Datapath,
    KeyKind,
    KeyScope,
    KeySpec,
    Layer4,
    PeerAddress,
    SubscriptionFormat,
    TransportMeta,
)
from edge.transports.amneziawg import serving

META = TransportMeta(
    name="amneziawg",
    # UDP, unlike the two VLESS transports. Recorded because the family drives real
    # decisions elsewhere: a UDP transport needs explicit MTU handling, which the edge
    # rulebook names as the "TLS works, large downloads hang" trap.
    family="udp",
    # No TLS at all — it is obfuscated UDP, not a TLS impersonation. So it must not be
    # given a certificate and must not sit behind our Caddy.
    needs_tls=False,
    # The socket it binds, which is a different question from ``family`` above —
    # `control` reads this one to decide whether two transports on one node may
    # hold the same port number, and reads ``family`` for nothing at all.
    listens_on=frozenset({Layer4.UDP}),
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
        # rather than a user, and the contract does not need to know the difference.
        KeySpec(
            name="peer_private_key",
            kind=KeyKind.X25519_KEYPAIR_BASE64,
            scope=KeyScope.CLIENT,
            public_name="peer_public_key",
        ),
        # WireGuard's pre-shared key is a property of a PAIR, and until M23 this transport
        # declared only the node-scoped one above — so every user on a node was handed
        # the identical value. Read off the real leaf: two PresharedKey lines in the node's
        # config, one distinct value. One user's leaked file therefore exposed the
        # symmetric layer protecting every other user's handshake on that node, and
        # revoking that user rotated nothing.
        #
        # The same shape M17 gave the tunnel address one field over: CLIENT scope means
        # "one per consumer", so `control` mints it per (user, node, transport) with no
        # knowledge of what it is for, and dropping that row is what makes a revocation
        # total. ``shared_between_peers`` is left False and means nothing here — it is a
        # NODE-scope question about a hop, and a hop's two ends agree through the
        # node-scoped key above, which is why that one stays. It has a second job as well:
        # ``render_server`` falls back to it for a credential minted before this
        # declaration existed, so a node whose users hold older files keeps authorising
        # them until they are re-issued.
        KeySpec(
            name="peer_preshared_key",
            kind=KeyKind.SYMMETRIC_32_BASE64,
            scope=KeyScope.CLIENT,
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
    # users until delivery of the second format lands as item 27. The serialiser
    # existing is not the same as the endpoint handing it over, and this declaration
    # does not pretend otherwise.
    subscription_formats=frozenset({SubscriptionFormat.CLIENT_CONFIG_FILE}),
    # The four magic headers, and nothing else — M26's first acceptance walk. They
    # replace WireGuard's fixed message-type constants, so two ends that disagree about
    # them cannot recognise each other's message types: both files are valid, both daemons
    # start, and the handshake never completes.
    #
    # The junk-packet knobs are deliberately NOT here even though they look like the same
    # kind of value. Junk is prepended by whichever end is sending, and the receiver skips
    # whatever arrives — so two ends may legitimately send different amounts, and refusing
    # that would refuse a working hop. Matching is a claim about the wire format, not a
    # tidiness rule, and only these four make it.
    hop_matched_params=(
        "init_packet_magic_header",
        "response_packet_magic_header",
        "underload_packet_magic_header",
        "transport_packet_magic_header",
    ),
    # Each consumer holds an address of its own, and the interface's own address says
    # how much room there is for them. A kernel tunnel authorises and routes by address
    # — AllowedIPs is both lists at once — so two consumers on one address is a silent
    # hijack of the first one's return path, which ``render_server`` refuses outright.
    # On a hop the consumer is a single far node and the pool is one address long; when
    # the transport is offered to users instead, it is as long as the operator sizes
    # it. The renderer cannot tell the two apart and does not need to.
    peer_address=PeerAddress(name="peer_tunnel_address", within="tunnel_address"),
    # A kernel tunnel: wg-quick hands what this interface decrypts to the host's routing
    # table, which is why ``render_server`` expresses its egress through
    # ``egress.wg_quick_egress`` and not through ``exit_origin``. Stated out loud rather
    # than left to the default, because it is the declaration that decides one real
    # answer for an operator — users on a node that dials a hop may not be on this
    # transport (M25), and a reader who meets that refusal deserves to find the fact in
    # the package it is about.
    #
    # It says nothing about the HOP ITSELF, which this transport carries and is today the
    # only one that can: there the tunnel being configured IS the way out, so the source
    # route is from its own address and there is nobody else's traffic in it.
    datapath=Datapath.KERNEL_ROUTED,
    # WHAT SERVING MEANS FOR THIS PROTOCOL, asked of the node and judged here — M26's
    # fourth acceptance walk. ``awg show <interface> peers``, compared against the peers
    # the configuration we pushed authorises; see ``serving.py`` for why that subcommand
    # and not the one an operator would type, and for what the walk did to earn it.
    #
    # Declared rather than inferred, like every other line in this file: the code that
    # runs this command recognises no protocol, so a transport that can be asked a
    # sharper question than "is your port held" says so here and one that cannot says
    # nothing.
    serving_question=serving.QUESTION,
)
