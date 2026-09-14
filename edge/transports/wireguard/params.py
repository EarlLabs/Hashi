"""Parameters for plain WireGuard.

Deliberately shorter than AmneziaWG's: everything that package validates and this one
does not is obfuscation, and obfuscation is exactly what plain WireGuard does not have.
The absence is the difference between the two protocols, so it is left visible here
rather than papered over with defaults.
"""

import ipaddress
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from edge.transports.wireguard.meta import META

# 32 bytes in STANDARD base64: 43 characters of payload plus one '='.
BASE64_32 = re.compile(r"^[A-Za-z0-9+/]{42}[A-Za-z0-9+/=]{2}$")


class Params(BaseModel):
    """One node's WireGuard interface, plus what a friend's device needs to reach it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    port: int

    # The tunnel's own address range. A private range, operator-chosen and never
    # defaulted: two tunnels on one host must not collide.
    tunnel_address: str = Field(description="this node's tunnel address, e.g. 10.x.y.1/24")
    peer_tunnel_address: str = Field(description="the address given to a peer")

    # Node-scoped material from META.key_material.
    private_key: str = Field(repr=False)
    public_key: str
    preshared_key: str = Field(repr=False)

    # Explicit and required, never defaulted — the same trap as on the hop: the default
    # fragments, and the symptom is "TLS works, large downloads hang", which nobody
    # debugs as MTU on the first day.
    mtu: int = Field(ge=1200, le=1500)

    # Resolvers written into a friend's config. Empty by default and never defaulted to
    # an address: a hardcoded resolver is an address this fleet could never rotate away
    # from. Empty falls back to the NODE's own resolver (``egress.client_resolvers``), and
    # only with neither does the client template say — truthfully, since M23 — that the
    # device is left asking a resolver the tunnel's route has put out of its reach.
    client_dns: tuple[str, ...] = Field(
        default=(),
        description=(
            "the resolver a FRIEND's device is told to use inside the tunnel. Not used "
            "at a hop end. An address, not a name. Left empty this node's own resolver "
            "is written instead; with neither, a friend's device keeps asking a "
            "resolver it can no longer reach and no name resolves."
        ),
    )

    @field_validator("port")
    @classmethod
    def _port_in_declared_range(cls, value: int) -> int:
        return META.clamp_port(value)

    @field_validator("tunnel_address", "peer_tunnel_address")
    @classmethod
    def _is_a_private_interface_address(cls, value: str) -> str:
        """Must parse as an address with a prefix, and must be private.

        Private is enforced rather than suggested: a public range here would route the
        node's own traffic into the tunnel and take the host off the network — a mistake
        only fixable with console access.
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

    @field_validator("private_key", "public_key", "preshared_key")
    @classmethod
    def _is_wireguard_base64(cls, value: str) -> str:
        """32 bytes in STANDARD base64, which is what the daemon accepts.

        Catches the encoding mistake this project can actually make: a Reality-style
        URL-safe unpadded key is the same 32 bytes and is rejected by this daemon with a
        message about the config rather than about the encoding.
        """
        if not BASE64_32.match(value):
            raise ValueError(
                "expected 32 bytes in standard base64 (44 chars, padded) — a URL-safe "
                "unpadded key is the wrong encoding for this transport"
            )
        return value

    @field_validator("client_dns")
    @classmethod
    def _resolvers_are_addresses(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Each entry must be a bare IP address.

        A hostname cannot work: resolving it is the very thing this setting is for, so
        the device would need to resolve in order to learn how to resolve.
        """
        for entry in value:
            try:
                ipaddress.ip_address(entry)
            except ValueError as exc:
                raise ValueError(
                    f"{entry!r} is not an IP address — a resolver written into a "
                    "tunnel's DNS setting cannot be a name"
                ) from exc
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
