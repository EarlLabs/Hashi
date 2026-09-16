"""Every knob this transport exposes, validated where it is owned.

WHAT: the Pydantic model for VLESS + Reality node parameters.
WHY:  validation lives beside the template that consumes the values, so a rule
      and its use cannot drift apart. It is also the last line before operator
      text reaches a config file: a decoy hostname with a quote in it, or a port
      outside the declared range, is rejected here rather than producing a config
      the daemon refuses at 3am.
HOW:  ``Params`` is loaded by ``edge.registry.profile()`` and applied by
      ``Transport.validate()``. Nothing outside this package constructs it.
"""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from edge.transports.vless_reality.meta import META

# A hostname, conservatively. Not a full RFC 1123 implementation — the job here
# is to refuse anything that could change the meaning of the config file it is
# interpolated into (quotes, braces, whitespace, control characters), and to
# refuse the shapes that are simply mistakes (a URL, a host:port pair).
HOSTNAME = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
                      r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")

# Reality short ids are hex, and Xray accepts 1–16 hex characters (0–8 bytes).
SHORT_ID = re.compile(r"^[0-9a-f]{2,16}$")

# Xray's uTLS fingerprint names. A closed set because a typo here does not fail
# loudly — Xray falls back and the node's TLS fingerprint silently stops matching
# the browser it was supposed to imitate, which is the one thing this transport
# exists to get right.
FINGERPRINTS = frozenset({"chrome", "firefox", "safari", "ios", "android", "edge", "random"})


class Params(BaseModel):
    """VLESS + Reality parameters for one node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # THE RANGE IS SAID, NOT NAMED — M26's third acceptance walk. This description is
    # rendered verbatim under the box an operator types into (``control``'s tuning hint),
    # and it read *"inside META.port_range"*: an internal symbol quoted at a person, with
    # the numbers it stands for never shown anywhere on the form. The bounds are
    # interpolated from the same declaration the validator below enforces, so they cannot
    # drift from it and no port is written into this file by hand — which is the rule
    # ``CLAUDE.md`` states and the reason the symbol was there in the first place.
    port: int = Field(
        description=(
            f"the port Xray listens on — {META.port_range[0]} to {META.port_range[1]}. "
            "Pick the one least conspicuous on this host; a fleet listening on one "
            "number is a fleet that can be enumerated by probing it."
        )
    )

    # The site whose TLS handshake this node borrows. NO DEFAULT, and there must
    # never be one: a shared decoy means every hashi node presents the same
    # borrowed handshake, and the fleet becomes enumerable by that fact alone.
    # Core invariants §6, and the charter calls it out separately.
    decoy_host: str = Field(description="per-node decoy site; never a project default")
    decoy_port: int = Field(default=443, ge=1, le=65535)

    # The SNI values this node will accept. Normally the decoy host and its
    # relevant subdomains — they have to be names the decoy actually serves, or
    # the borrowed handshake does not verify.
    server_names: tuple[str, ...] = Field(min_length=1)

    # Node-scoped key material, minted by `control` from META.key_material.
    private_key: str = Field(min_length=1, repr=False)
    public_key: str = Field(min_length=1)
    short_id: str

    fingerprint: str = "chrome"

    @field_validator("port")
    @classmethod
    def _port_in_declared_range(cls, value: int) -> int:
        """The range is declared once, in META — not repeated as a literal here."""
        return META.clamp_port(value)

    @field_validator("decoy_host")
    @classmethod
    def _decoy_is_a_hostname(cls, value: str) -> str:
        if not HOSTNAME.match(value):
            raise ValueError(
                f"decoy_host {value!r} is not a bare hostname — no scheme, no port, no path"
            )
        return value

    @field_validator("server_names")
    @classmethod
    def _server_names_are_hostnames(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not HOSTNAME.match(name):
                raise ValueError(f"server name {name!r} is not a bare hostname")
        return value

    @field_validator("short_id")
    @classmethod
    def _short_id_is_hex(cls, value: str) -> str:
        if not SHORT_ID.match(value):
            raise ValueError(f"short_id {value!r} must be 2-16 lowercase hex characters")
        return value

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint_is_known(cls, value: str) -> str:
        if value not in FINGERPRINTS:
            raise ValueError(
                f"fingerprint {value!r} is not one Xray knows: {sorted(FINGERPRINTS)}"
            )
        return value
