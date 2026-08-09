"""Parameters for VLESS over WebSocket behind TLS."""

import re

from pydantic import BaseModel, ConfigDict, field_validator

from edge.transports.vless_ws_tls.meta import META

HOSTNAME = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
                      r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")

# A path segment safe to place in both a JSON config and a URI query value.
WS_PATH_SECRET = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# An absolute container path. Validated only for shape: this transport does not
# check the file exists, because that would be filesystem I/O in a pure zone —
# and the file lives on the NODE, not on the machine doing the rendering.
ABSOLUTE_PATH = re.compile(r"^/[A-Za-z0-9._/-]{1,200}$")


def ws_path(secret: str) -> str:
    """The full WebSocket path, derived from the secret in exactly one place.

    A module-level function rather than only a model property because rendering
    receives validated parameters as a plain mapping, and the server template and
    the client URI must not each derive the path their own way — a mismatch there
    is a node where every TLS handshake succeeds and every connection then fails,
    which reads like blocking rather than like a typo.
    """
    return f"/{secret}"


class Params(BaseModel):
    """VLESS + WS + TLS parameters for one node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    port: int

    # The name on the certificate and in the client's SNI and Host header. A real
    # name this node actually serves, unlike Reality's decoy.
    server_name: str

    # Certificate and key, by path on the node. Required with no default: a
    # default path is a convention this file cannot enforce, and a wrong one
    # produces a node that boots and fails every handshake.
    certificate_path: str
    certificate_key_path: str

    # Node-scoped material from META.key_material.
    ws_path_secret: str

    @field_validator("port")
    @classmethod
    def _port_in_declared_range(cls, value: int) -> int:
        return META.clamp_port(value)

    @field_validator("server_name")
    @classmethod
    def _server_name_is_a_hostname(cls, value: str) -> str:
        if not HOSTNAME.match(value):
            raise ValueError(f"server_name {value!r} is not a bare hostname")
        return value

    @field_validator("ws_path_secret")
    @classmethod
    def _ws_path_is_url_safe(cls, value: str) -> str:
        if not WS_PATH_SECRET.match(value):
            raise ValueError("ws_path_secret must be 8-64 URL-safe characters")
        return value

    @field_validator("certificate_path", "certificate_key_path")
    @classmethod
    def _is_absolute_path(cls, value: str) -> str:
        if not ABSOLUTE_PATH.match(value):
            raise ValueError(f"{value!r} is not a plain absolute path")
        return value

    @property
    def ws_path(self) -> str:
        """This node's WebSocket path. Delegates, so there is one derivation."""
        return ws_path(self.ws_path_secret)
