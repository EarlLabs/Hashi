"""What `control` may know about plain WireGuard.

Four declarations carry the constraints on this protocol, and each is a field the code
reads rather than a sentence a reader might not: ``hop_capable``,
``blocked_by_inspection``, a ``config_format`` of its own so the pinned data-plane image
and the upstream checker travel with the transport rather than being borrowed from its
obfuscated cousin — and, since M20, ``retired``, which is why the panel no longer offers
this one at all.

**It is still here, and that is deliberate.** The rendered config is correct and this
package is the second member of the WireGuard family; having two is what proves the
charter's rule that transports are data, because a family with one member cannot catch
`control` learning its name. What stopped is being suggested, and nothing else: a node
that already runs it renders exactly the bytes it rendered before, and the friend whose
device holds that configuration keeps it.
"""

from edge.registry import (
    ConfigFormat,
    Datapath,
    KeyKind,
    KeyScope,
    KeySpec,
    Layer4,
    PeerAddress,
    Retirement,
    SubscriptionFormat,
    TransportMeta,
)
from edge.transports.wireguard import serving

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
        # WireGuard's pre-shared key is a property of a PAIR, and until M23 this transport
        # declared only the node-scoped one above — so every friend on a node was handed
        # the identical value. Read off the real leaf: two PresharedKey lines in the node's
        # config, one distinct value. One friend's leaked file therefore exposed the
        # symmetric layer protecting every other friend's handshake on that node, and
        # revoking that friend rotated nothing.
        #
        # The same shape M17 gave the tunnel address one field over: CLIENT scope means
        # "one per consumer", so `control` mints it per (friend, node, transport) with no
        # knowledge of what it is for, and dropping that row is what makes a revocation
        # total.
        #
        # The node-scoped key above stays rather than being deleted, and on this transport
        # it now has exactly one job: it is what ``render_server`` falls back to for a
        # credential minted before this declaration existed, so a node whose friends hold
        # older files keeps authorising them until they are re-issued. Removing it would
        # cut those friends off at the next apply.
        KeySpec(
            name="peer_preshared_key",
            kind=KeyKind.SYMMETRIC_32_BASE64,
            scope=KeyScope.CLIENT,
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
    # The same kernel data plane as its obfuscated cousin, and the same consequence: its
    # ``render_server`` expresses egress through ``egress.wg_quick_egress``, so friends on
    # a node that dials a hop may not be on this transport either (M25). Declared here as
    # well as there, rather than shared between the two: a family is two packages that
    # agree separately, and a fact stated once for both would be the branch on a family
    # this contract exists to prevent.
    datapath=Datapath.KERNEL_ROUTED,
    # THE DECLARATION THAT RETIRES IT — M20, and the only one of the four that was
    # measured rather than reasoned about. The two rule sets were read off a live node
    # on 2026-09-13 and again during the field run before that; the plan carries both
    # readings. It is a fact about ONE PINNED IMAGE and not about this code, so the way
    # out is an image on the other backend, or rules rendered per backend — either of
    # which deletes these lines and nothing else.
    #
    # Written here rather than in the panel because the panel may not know this
    # protocol's name, and because a reason kept in `control` would be a reason the next
    # retired transport has to write again somewhere else.
    retired=Retirement(
        reason=(
            "on the hosts this project prepares, a user's handshake completes and "
            "nothing is carried. Its pinned data plane writes forwarding rules on one "
            "netfilter backend while the firewall this project's own bootstrap enables "
            "writes its default-deny policy on the other, and both are traversed — so "
            "the accept never front-runs the drop, and neither end reports anything. "
            "Measured twice on a live node."
        )
    ),
    # WHAT SERVING MEANS FOR THIS PROTOCOL, asked of the node and judged here — M26's
    # fourth acceptance walk. ``wg show <interface> peers``, compared against the peers
    # the configuration we pushed authorises; see ``serving.py`` for why that subcommand
    # and not the one an operator would type, and for what the walk did to earn it.
    #
    # Declared rather than inferred, like every other line in this file: the code that
    # runs this command recognises no protocol, so a transport that can be asked a
    # sharper question than "is your port held" says so here and one that cannot says
    # nothing.
    serving_question=serving.QUESTION,
)
