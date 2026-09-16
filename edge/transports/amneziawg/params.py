"""Parameters for AmneziaWG, including the obfuscation knobs that are the point.

The ``j*`` and ``s*``/``h*`` fields are what make this AmneziaWG rather than
WireGuard: they pad and reshape the handshake so it does not match WireGuard's
fixed, trivially fingerprinted packet signature. They are validated here rather
than defaulted silently, because a set of values shared across every node would
itself become the fingerprint — the same reasoning as a shared Reality decoy.
"""

import ipaddress
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from edge.egress import client_resolver_problem
from edge.transports.amneziawg.meta import META

BASE64_32 = re.compile(r"^[A-Za-z0-9+/]{42}[A-Za-z0-9+/=]{2}$")

# What every one of the four magic-header boxes says, written once because they are four
# instances of one decision rather than four fields — see the fields themselves for why
# they need a sentence at all, and why the example set is not quoted in it.
MAGIC_HEADER_HINT = (
    "one of four numbers that replace WireGuard's fixed message types. Pick a value for "
    "THIS node and never the protocol documentation's example set: four numbers shared "
    "across the fleet are themselves the signature that identifies it. All four must "
    "differ from each other."
)

# The four, IN DECLARATION ORDER, which is the order Pydantic validates them in and
# therefore the order the distinctness rule reads them in. A tuple rather than something
# derived from the model because the validator below is applied at class-body time, when
# ``model_fields`` does not exist yet — so the one thing that could drift is this list
# against the fields themselves, and ``tests/edge/test_a_repeated_obfuscation_header_
# names_the_one_it_repeats.py`` compares the two rather than trusting them to agree.
MAGIC_HEADERS = (
    "init_packet_magic_header",
    "response_packet_magic_header",
    "underload_packet_magic_header",
    "transport_packet_magic_header",
)


class Params(BaseModel):
    """AmneziaWG parameters for one node's end of a hop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    port: int

    # The tunnel's own address range. A private range, and NOT hardcoded anywhere in
    # code — the operator picks it, because two hops on one host must not collide.
    tunnel_address: str = Field(description="this end's tunnel address, e.g. 10.x.y.1/24")
    # Dual-use, and the description says so because the establish-hop dialog and the
    # enable dialog both show it: on a hop this is the single far end's address, and on
    # a transport offered to friends it is the FIRST address given out — the pool starts
    # here and runs as far as the operator sized it.
    #
    # IT ALSO SAYS WHAT THE VALUE LOOKS LIKE, since M25. The field is required, declares
    # no default, and has no bounds for a placeholder to show — so the box beside it is
    # empty, and the sentence under it explained what the value MEANT to a reader who
    # already knew what to type. The walk met it on the enable dialog with nothing to
    # type, got the refusal, and learned only which box it was about. The example is a
    # SHAPE and not an address, exactly as ``tunnel_address``'s is: a real range written
    # here is a range every node would borrow, and two tunnels whose ranges meet hand two
    # people the same address.
    peer_tunnel_address: str = Field(
        description=(
            "the far end's tunnel address on a hop; the FIRST address given out when "
            "this transport is offered to friends, the pool counting up from it one per "
            "person. An address with its prefix, in the same range as this end's own "
            "tunnel address and never that address itself — e.g. 10.x.y.2/24 where this "
            "end is 10.x.y.1/24."
        )
    )

    # Node-scoped material from META.key_material.
    private_key: str = Field(repr=False)
    public_key: str
    preshared_key: str = Field(repr=False)

    # Resolvers to write into a FRIEND's config file. Empty by default and never
    # defaulted to an address: a hardcoded resolver is an address this fleet could
    # never rotate away from, which `CLAUDE.md` forbids for exactly that reason.
    #
    # Empty is a real state rather than a missing feature, but it is NOT the state the
    # comment in ``client.j2`` used to describe. A friend's config routes every address
    # into the tunnel, their own resolver included, so "the device keeps its own resolver
    # and its queries do not enter the tunnel" was false for every destination — M23,
    # measured. Empty now falls back to the NODE's own resolver
    # (``egress.client_resolvers``), and only with neither does the file say, truthfully,
    # that nothing here answers a lookup. Unused by the hop, where the consumer is a node
    # with its own resolver — which is why the field carries a ``description`` saying so:
    # the establish-hop dialog renders it, and until M23 that box explained nothing
    # (``docs/decisions.md``, 2026-09-10).
    client_dns: tuple[str, ...] = Field(
        default=(),
        description=(
            "the resolver a FRIEND's device is told to use inside the tunnel. Not used "
            "at a hop end. An address, not a name. Left empty this node's own resolver "
            "is written instead; with neither, a friend's device keeps asking a "
            "resolver it can no longer reach and no name resolves."
        ),
    )

    # MTU. Explicit and required, never defaulted: this hop is a tunnel inside a
    # tunnel, and the default fragments. The symptom is "TLS works, large downloads
    # hang", which nobody debugs as MTU on the first day — the edge rulebook lists it
    # as a trap for exactly that reason.
    mtu: int = Field(ge=1200, le=1500)

    # --- AmneziaWG obfuscation ------------------------------------------------
    # Junk packet counts and sizes. Per-node values, no project-wide default: if every
    # hashi hop sent the same junk, the junk would be the signature.
    junk_packet_count: int = Field(ge=0, le=128)
    junk_packet_min_size: int = Field(ge=0, le=1280)
    junk_packet_max_size: int = Field(ge=0, le=1280)

    # Magic headers, which replace WireGuard's four fixed message-type constants.
    # Distinct values required — two equal headers make two message types
    # indistinguishable to the peer, and the tunnel simply never comes up.
    #
    # EACH ONE CARRIES ITS OWN WARNING SINCE M23, for the reason ``decoy_host`` has
    # carried one since M1: these four numbers ARE this fleet's fingerprint, and the
    # hazard is not a value the panel might default — it declares none — but a value an
    # operator copies out of the protocol's own documentation. The real hop was found
    # carrying the upstream project's published example set, typed by hand, directly
    # beneath a comment in the rendered file saying that shared values would themselves
    # be the fingerprint. A box that says nothing is where that happens; the sentence
    # belongs on the box, which is the one place it is read at the moment it is chosen.
    #
    # The example values are deliberately NOT quoted here. Naming them would put the
    # very set a node must not use into this file, where the next operator reads it as
    # the suggestion the field is careful not to make.
    init_packet_magic_header: int = Field(ge=1, description=MAGIC_HEADER_HINT)
    response_packet_magic_header: int = Field(ge=1, description=MAGIC_HEADER_HINT)
    underload_packet_magic_header: int = Field(ge=1, description=MAGIC_HEADER_HINT)
    transport_packet_magic_header: int = Field(ge=1, description=MAGIC_HEADER_HINT)

    @field_validator("port")
    @classmethod
    def _port_in_declared_range(cls, value: int) -> int:
        return META.clamp_port(value)

    @field_validator("tunnel_address", "peer_tunnel_address")
    @classmethod
    def _is_an_interface_address(cls, value: str) -> str:
        """Must parse as an address with a prefix, and must be private.

        Private is enforced rather than suggested: a public range here would route the
        node's own traffic into the tunnel and take the host off the network — a
        mistake that is only fixable with console access.
        """
        try:
            interface = ipaddress.ip_interface(value)
        except ValueError as exc:
            raise ValueError(f"{value!r} is not an address with a prefix, e.g. 10.0.0.1/24") \
                from exc
        if not interface.ip.is_private:
            raise ValueError(
                f"{value!r} is not a private address — a public range here would route "
                "the node's own traffic into the tunnel"
            )
        return str(interface)

    @field_validator("client_dns")
    @classmethod
    def _each_resolver_is_one_a_device_could_reach(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Each entry must be an address a friend's device can actually ask — M23.

        ``egress.client_resolver_problem`` decides, and this validator only raises what it
        answers. The rule is not a property of this protocol — what makes a resolver
        unreachable is the tunnel's own egress, which is why it lives beside the routes
        the tunnel carries and is asked here rather than copied here. Asking it at
        VALIDATION is what makes the refusal arrive while the operator is still looking
        at the box: the renderer asked the same question and nobody reached it until a
        user downloaded their configuration, which is one 500 for every node they hold.

        It covers a name (resolving it is the very thing the setting is for) and an IPv6
        address (this tunnel carries IPv4 only, so the device would ask and never hear
        back). The tunnel's own range is the validator below, because that one needs the
        tunnel as well as the value.
        """
        for entry in value:
            problem = client_resolver_problem(entry)
            if problem:
                raise ValueError(problem)
        return value

    @field_validator("client_dns")
    @classmethod
    def _resolvers_are_not_inside_the_tunnel(cls, value: tuple[str, ...], info):
        """No resolver may be an address out of this tunnel's own range.

        With a pool, every address in that range is one a USER's device holds — so a
        resolver set to one of them points every user's lookups at whichever person was
        given it, which is the one record this project must never create. The
        interface's own address is refused by the same rule and for a second reason:
        nothing on the node answers a query there, so every name would simply fail.

        Read out of ``info.data`` and skipped quietly when ``tunnel_address`` is absent,
        which means the tunnel address itself failed validation a moment ago. That is
        the error worth reading; a second complaint about the resolver would bury it.
        """
        tunnel = info.data.get("tunnel_address")
        if not tunnel:
            return value
        network = ipaddress.ip_interface(tunnel).network
        for entry in value:
            if ipaddress.ip_address(entry) in network:
                raise ValueError(
                    f"{entry!r} is inside {network}, which is this tunnel's own range. "
                    "Every address in it is one a user's device is given, so a resolver "
                    "there would send every user's lookups to whoever holds it — and the "
                    "node's own address in that range answers no lookups at all. Give a "
                    "resolver outside the tunnel."
                )
        return value

    @field_validator("private_key", "public_key", "preshared_key")
    @classmethod
    def _is_wireguard_base64(cls, value: str) -> str:
        """32 bytes in STANDARD base64, which is what the daemon accepts.

        Catches the encoding mistake this project can actually make: passing a
        Reality-style URL-safe unpadded key, which is the same 32 bytes and is rejected
        by this daemon with a message about the config rather than the encoding.
        """
        if not BASE64_32.match(value):
            raise ValueError(
                "expected 32 bytes in standard base64 (44 chars, padded) — a URL-safe "
                "unpadded key is the wrong encoding for this transport"
            )
        return value

    @field_validator("junk_packet_max_size")
    @classmethod
    def _max_is_not_below_min(cls, value: int, info) -> int:
        minimum = info.data.get("junk_packet_min_size")
        if minimum is not None and value < minimum:
            raise ValueError("junk_packet_max_size is below junk_packet_min_size")
        return value

    @field_validator(*MAGIC_HEADERS[1:])
    @classmethod
    def _magic_headers_are_distinct(cls, value: int, info) -> int:
        """No header may repeat one declared before it, and the refusal names which.

        ON EVERY HEADER BUT THE FIRST, which is the whole of M23 round 3's small
        finding. It used to sit on ``transport_packet_magic_header`` alone and compare
        all four there — correct about WHETHER the set collides and useless about
        WHICH pair does, because Pydantic attributes an error to the field whose
        validator raised it. An operator who typed the same number into the init and
        response boxes was sent to the transport box, which was the one value they had
        got right; the walk provoked all three pairs and read the same field name back
        every time.

        Pydantic validates fields in declaration order, so ``info.data`` holds the
        headers ABOVE this one and none below. Running here therefore lands the refusal
        on the later of the two boxes — the one the operator reached most recently —
        and the sentence names the earlier one, so both ends of the collision are on
        screen. ``MAGIC_HEADERS[1:]`` is every header but the first, which is the one
        with nothing above it to repeat.

        THE VALUE IS NOT QUOTED. A field's own refusal is rendered by surfaces that did
        not choose to render it (``control.errors.ParamsRefused``), and these four
        numbers are this node's fingerprint rather than a detail — naming the two boxes
        says everything the operator needs and echoes nothing back.
        """
        repeated = next(
            (
                earlier
                for earlier in MAGIC_HEADERS[: MAGIC_HEADERS.index(info.field_name)]
                if info.data.get(earlier) == value
            ),
            None,
        )
        if repeated is not None:
            raise ValueError(
                f"this repeats {repeated} — the four magic headers must be distinct, "
                "because two equal values make two message types indistinguishable and "
                "the tunnel never comes up"
            )
        return value
