"""Transport profile registry — the contract `control` is allowed to know.

WHAT: discovers the transport packages under ``edge/transports/`` at runtime, and
      declares the four types that make up the transport profile contract:
      ``TransportMeta``, ``KeySpec``, ``ClientEntry`` and the ``profile()``
      accessor for a transport's rendering functions.
WHY:  the charter's fourth success criterion is that a brand-new protocol is one
      package and not surgery. Discovery is what makes that true: a hardcoded
      list here would mean every new transport edits this file, and then two
      developers edit it at once.

      Everything in this module exists so that `control` can create nodes, mint
      key material, render subscriptions and revoke friends **without ever
      learning a protocol's name**. Every value `control` reads from here is
      either opaque text it passes through, or a member of a small closed
      vocabulary (``KeyKind``) that says nothing about which protocol asked.
HOW:  each ``edge/transports/<name>/`` package exposes ``META`` in ``meta.py``
      and ``render_server`` / ``render_client`` in ``render.py``. ``discover()``
      imports them and returns their metadata by name; ``profile()`` returns the
      callables for one of them.

      **This file is frozen.** Its shape was completed once, in M1 item 1, under
      the single authorisation recorded in ``.claude/projects/02-edge-rulebook.md``
      (*Completing the contract*). From the second transport onward, a transport
      that needs an edit here is a contract failure to raise with the architect,
      not a special case to add.
"""

import importlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import ModuleType
from typing import Protocol

import edge.transports
from edge.node import Credential, NodeView


class KeyKind(StrEnum):
    """The kinds of key material `control` knows how to generate.

    This vocabulary is the whole trick behind "a new protocol is one package".
    A transport does not ask `control` for "a Reality keypair"; it asks for an
    ``X25519_KEYPAIR``, and `control` has one generator per *kind*. So the
    generator table is keyed by cryptographic shape, never by protocol name, and
    a new transport that needs only existing kinds requires **zero** lines in
    `control`.

    Adding a kind is therefore the one thing a new transport may legitimately
    need from outside its own directory — and it is a new generator, not a branch
    on a protocol.
    """

    # An X25519 keypair, base64-URL encoded without padding — the format
    # ``xray x25519`` emits, and the only one Reality accepts.
    X25519_KEYPAIR = "x25519-keypair"

    # The same cryptographic shape, STANDARD base64 with padding — the format
    # ``wg genkey`` emits and the WireGuard family requires.
    #
    # Two kinds for one primitive looks redundant and is not. The encoding is not a
    # presentation detail here: a Reality-encoded key in a WireGuard config is
    # rejected by the daemon, and vice versa. Making it one kind would push the
    # choice back into `control`, which would then need to know which protocol
    # asked — the exact branch this vocabulary exists to prevent. Splitting it keeps
    # the decision where it belongs: in the transport's own declaration.
    X25519_KEYPAIR_BASE64 = "x25519-keypair-base64"

    # A random UUID, as the canonical 8-4-4-4-12 string. VLESS client ids.
    UUID4 = "uuid4"

    # 32 bytes of URL-safe randomness. Bearer-shaped secrets.
    TOKEN_32 = "token-32"

    # 32 random bytes in STANDARD base64 with padding — what ``wg genkey`` emits and
    # the only form the WireGuard family's pre-shared key accepts. The same split, and
    # the same reasoning, as the two X25519 kinds above: a URL-safe token here is the
    # right number of bytes in the wrong alphabet, and the daemon rejects it with a
    # message about the config rather than about the encoding.
    SYMMETRIC_32_BASE64 = "symmetric-32-base64"

    # A short lowercase hex string (8 hex chars = 4 bytes). Reality short ids.
    SHORT_ID = "short-id"


class ConfigFormat(StrEnum):
    """The shape of a rendered server config, and therefore which checker validates it.

    A closed vocabulary for the same reason as ``KeyKind``: validation has to dispatch
    on something, and dispatching on the FORMAT means one checker per format rather
    than one per protocol. Two transports that both render Xray JSON share a checker
    without either being named anywhere in ``edge/checker.py``.

    **This field was added after the contract was first frozen, and that is worth
    recording rather than glossing.** The backlog predicted the bill: moving AmneziaWG
    to M4 left the named debt "does the contract survive a family that is not
    expressible as a URI" (revision 2, §1.D — "счёт придёт в M4"). It came due here.
    The contract's first implementation assumed every config was Xray JSON, because
    both transports it was drawn from were. Adding a WireGuard-family transport needed
    one new field and one new dispatch arm — not a branch on a protocol, but not free
    either. Recorded so the next reader knows the contract widened once, deliberately,
    and why.
    """

    # An Xray-core JSON config, validated by `xray run -test`.
    XRAY_JSON = "xray-json"

    # A wg-quick INI config, validated by `awg-quick strip` from amneziawg-tools.
    WG_QUICK = "wg-quick"


class KeyScope(StrEnum):
    """Whether a piece of material belongs to a node or to one friend."""

    # Generated once per node × transport, shared by every friend on that node —
    # a server private key, for instance.
    NODE = "node"

    # Generated per friend, per node, per transport. This is what makes total
    # revocation expressible: drop the row, and nothing elsewhere still works.
    CLIENT = "client"


@dataclass(frozen=True)
class KeySpec:
    """One piece of key material a transport needs, declared by the transport.

    The declaration exists so that `control` never generates material *for a
    protocol it can name*. It reads ``kind``, calls the matching generator, and
    stores the result under ``name`` — all without knowing what the value is for.
    """

    # The parameter name the transport's own ``Params`` (for NODE scope) or
    # ``Credential.secrets`` / ``Credential.subject`` (for CLIENT scope) expects.
    name: str

    kind: KeyKind
    scope: KeyScope

    # For asymmetric kinds, the parameter name the PUBLIC half is delivered under.
    # Declared by the transport because only the transport knows what its template
    # and its client URI call it — `control` generates a keypair, stores the
    # private half encrypted and the public half in plain parameters, and never
    # needs to know that "public_key" means a Reality `pbk`.
    public_name: str | None = None

    # Whether the generated value itself must be encrypted at rest.
    #
    # Not every generated value is a secret, and treating them alike is wrong in
    # both directions. A Reality short id is minted randomly but travels to every
    # friend inside their subscription URI, so encrypting it buys nothing and
    # makes it unavailable to the client renderer. A WebSocket path secret IS a
    # secret even though it is not a key. So the transport says which, and
    # `control` files each value accordingly.
    secret: bool = True

    # Whether BOTH ends of a node-to-node hop must carry the identical value.
    #
    # Declared rather than inferred, and this is the S6 question again in a second
    # form: a symmetric pre-shared key minted independently at each end produces two
    # configuration files that are individually valid and never complete a handshake.
    # `control` cannot know which of a transport's values are symmetric without being
    # told — knowing would mean recognising the field by name, which is exactly the
    # protocol knowledge the contract keeps out of the control plane.
    #
    # Meaningful only at NODE scope and only on a hop (see ``edge/relay.py``); a
    # friend-facing transport never has a second end to agree with.
    shared_between_peers: bool = False


@dataclass(frozen=True)
class TransportMeta:
    """What the control plane may know about a transport without knowing which."""

    name: str
    family: str          # "tcp-tls" | "udp" | ...
    needs_tls: bool

    # The ports this transport may legitimately listen on, inclusive. A range
    # rather than a single number because the operator picks within it per node —
    # a fleet where every node listens on one port is a fleet you can scan for.
    # No project-wide default: it is a property of the protocol, declared by the
    # protocol's own package.
    port_range: tuple[int, int]

    # Every piece of key material this transport needs, at either scope. `control`
    # walks this list to mint material; see ``KeySpec``.
    key_material: tuple[KeySpec, ...] = ()

    # Which checker validates this transport's rendered server config. See
    # ``ConfigFormat`` — including the note on when and why this field was added.
    config_format: ConfigFormat = ConfigFormat.XRAY_JSON

    # Whether this transport can be serialised into the v1 subscription format —
    # a base64 list of client-entry URIs with an appended display fragment
    # (charter amendment A). Declared, not inferred, and this is the S6
    # requirement from the backlog: AmneziaWG is a config *file*, not a link, so
    # it must be able to say "not me" rather than be discovered mid-render.
    #
    # `control` refuses out loud to enable a transport with False on a node it
    # would deliver to a friend, instead of shipping a quietly short
    # subscription. See ``control/app/services/transports.py``.
    subscription_expressible: bool = True

    def clamp_port(self, port: int) -> int:
        """Raise unless ``port`` is inside this transport's declared range."""
        low, high = self.port_range
        if not low <= port <= high:
            raise ValueError(
                f"port {port} is outside the range {low}-{high} declared by "
                f"transport {self.name!r}"
            )
        return port


@dataclass(frozen=True)
class ClientEntry:
    """One node × one transport × one friend, serialised by the transport itself.

    ``entry`` is finished text. `control` does not parse it, does not rebuild it
    and does not branch on it — see the edge rulebook's *What ``render_client``
    returns, and why it is not a dict of parts*. The other three fields exist so
    `control` can do its half (order, label, join, base64) generically.
    """

    # The complete client-entry URI, WITHOUT a display label. The label is a
    # property of the subscription format rather than of any one protocol, so it
    # is appended once by `control` instead of once per transport.
    entry: str

    # Human-readable name for this entry, from the transport's point of view.
    display_label: str

    # The exit country, taken verbatim from ``NodeView.location_label``.
    country_label: str

    # Which node this entry points at.
    node_id: str


class TransportProfile(Protocol):
    """The two pure functions every transport package provides in ``render.py``."""

    def render_server(self, node: NodeView, params: Mapping[str, object]) -> str:
        """The node's complete config file for this transport. Deterministic."""
        ...

    def render_client(
        self,
        node: NodeView,
        params: Mapping[str, object],
        credential: Credential,
    ) -> ClientEntry:
        """One friend's entry for this node.

        Takes ``params`` as well as ``credential`` because a client entry needs
        the node-scoped public half of the configuration — the listening port,
        the Reality public key, the SNI. The edge rulebook's table once wrote
        this as ``render_client(node, credential)``; that signature cannot build
        a URI, and it was corrected when the contract was first implemented.
        """
        ...


@dataclass(frozen=True)
class Transport:
    """A discovered transport: its metadata and its renderers, together."""

    meta: TransportMeta
    profile: TransportProfile
    params_model: type = field(repr=False)

    def validate(self, params: Mapping[str, object]) -> Mapping[str, object]:
        """Validate raw parameters through the transport's own Pydantic model.

        `control` calls this instead of trusting operator input: every knob a
        transport exposes is validated by the package that owns it, so validation
        rules cannot drift away from the template that consumes them.
        """
        return self.params_model(**dict(params)).model_dump()


def _package(name: str) -> ModuleType:
    return importlib.import_module(f"edge.transports.{name}")


def _iter_packages() -> list[str]:
    """Every transport package name under ``edge/transports/``.

    Uses ``importlib.resources`` rather than ``pkgutil.iter_modules`` over
    ``__path__``: the installed distribution in the container has no source
    directory to walk in some layouts, and a registry that finds transports on a
    laptop and not in the image is the failure mode
    ``tests/e2e/edge/test_shipped_image_discovers_transports.py`` exists to catch.
    """
    import pkgutil

    return sorted(m.name for m in pkgutil.iter_modules(edge.transports.__path__) if m.ispkg)


def discover() -> dict[str, TransportMeta]:
    """Return every installed transport profile's metadata, keyed by name."""
    found: dict[str, TransportMeta] = {}
    for name in _iter_packages():
        meta = importlib.import_module(f"edge.transports.{name}.meta").META
        if meta.name in found:
            raise ValueError(f"duplicate transport name: {meta.name!r}")
        found[meta.name] = meta
    return found


def profile(name: str) -> Transport:
    """Load one transport's metadata, renderers and parameter model.

    Looked up by the name the transport itself declared in ``META``, which is not
    necessarily its directory name — so a rename of either cannot silently point
    `control` at the wrong package.
    """
    for package in _iter_packages():
        meta = importlib.import_module(f"edge.transports.{package}.meta").META
        if meta.name != name:
            continue
        return Transport(
            meta=meta,
            profile=importlib.import_module(f"edge.transports.{package}.render"),
            params_model=importlib.import_module(f"edge.transports.{package}.params").Params,
        )
    raise KeyError(f"no transport named {name!r} is installed")
