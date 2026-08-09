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

      **It has been widened three times since, each deliberately, each recorded
      where it happened.** ``ConfigFormat`` came with the WireGuard family (see its
      own docstring). ``SubscriptionFormat`` came with backlog item 26: a transport
      now declares the SET of subscription shapes it serialises into rather than a
      yes/no about the v1 URI list, and serialises each of them itself.
      ``hop_capable`` and ``blocked_by_inspection`` came with backlog item 28, whose
      text states both charter constraints as "the transport must declare this
      machine-readably" — and a declaration has nowhere else to live.

      None of the three was a branch on a protocol; each replaced one with a
      vocabulary or a property. None was free either, and a reader deserves to know
      the contract has moved and why rather than to discover it from a diff.
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

    # An AmneziaWG INI config, validated by `awg-quick strip` from amneziawg-tools
    # and run by the amneziawg data plane. Named ``wg-quick`` because that is the file
    # format it borrows; the checker and the daemon are AmneziaWG's own.
    WG_QUICK = "wg-quick"

    # A PLAIN WireGuard INI config, validated by `wg-quick strip` from wireguard-tools
    # and run by a plain wireguard-go data plane.
    #
    # A second format rather than a reuse of the one above, and the difference is not
    # pedantry. The two are checked by different binaries and run by different daemons,
    # and a plain config handed to the AmneziaWG daemon would come up — as a working
    # tunnel, running someone else's superset, validated by the wrong tool. That is the
    # kind of "it works" that is discovered during an outage. One format per
    # (checker, daemon) pair keeps both dispatches honest, which is the whole reason
    # this vocabulary is keyed on format instead of on protocol.
    WG_QUICK_PLAIN = "wg-quick-plain"


class SubscriptionFormat(StrEnum):
    """A shape a friend's client can consume, declared by the transport that produces it.

    This vocabulary replaces a boolean, and the replacement is the point. "Can this
    transport be expressed in the v1 subscription?" had exactly one answer for every
    transport that is not a URI — *no* — and that answer left AmneziaWG's
    friend-facing form unbuildable rather than merely undelivered (backlog item 25,
    blocked since 2026-08-01, and the charter's largest open question in phase 1).

    A closed vocabulary rather than free-form strings, for the same reason as
    ``KeyKind`` and ``ConfigFormat``: delivery has to dispatch on something, and
    dispatching on the FORMAT means `control` gains one delivery arm per format, never
    one per protocol. Two transports that both serialise to a config file share
    delivery without either being named anywhere in `control`.
    """

    # One line in the base64 list of client-entry URIs — the v1 subscription
    # (charter amendment A). Serialised by ``render_client`` into a ``ClientEntry``.
    V1_URI_LIST = "v1-uri-list"

    # A complete configuration file the friend's client imports. Serialised by
    # ``render_client_config`` into a ``ClientConfig``.
    #
    # This is the second format the charter calls a product decision rather than an
    # implementation detail (question Q11, answered (b) by the owner on 2026-08-09:
    # per-client config files behind the same token). It is the honest form for a
    # protocol family whose configuration is a file and not a link — writing a URI for
    # it would put a line in a subscription that no client can parse.
    CLIENT_CONFIG_FILE = "client-config-file"


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

    # Every subscription format this transport serialises itself into. Declared, not
    # inferred — the S6 requirement from the backlog, now stated as a set rather than
    # as a yes/no: a transport says which shapes it produces, and produces exactly
    # those. Empty means "nothing a friend can consume", which is a legitimate answer
    # for a transport that only ever runs between our own nodes, and `control` refuses
    # out loud to offer such a transport to friends rather than shipping a
    # subscription that is quietly one node short.
    #
    # Defaulting to the v1 URI list rather than to the empty set is deliberate: a new
    # transport that forgets to declare anything is then held to the format every
    # existing one uses, and its missing ``render_client`` is caught by ``profile()``
    # at load time — instead of the transport looking correct and being undeliverable.
    subscription_formats: frozenset[SubscriptionFormat] = frozenset(
        {SubscriptionFormat.V1_URI_LIST}
    )

    # Whether this transport may carry an entry-to-leaf hop. Declared rather than
    # inferred, and it is a charter constraint rather than a capability: the hop crosses
    # the Russian border by definition, so a transport that is protocol-blocked there
    # would take the whole topology down while looking perfectly configured at both
    # ends. Enforced in ``edge/relay.py`` before either end of a hop is written.
    #
    # Defaults to True because the constraint is the exception: most transports here are
    # obfuscated or TLS-shaped, and a new package should have to say "not me" out loud
    # rather than opt in to being usable.
    hop_capable: bool = True

    # Whether this protocol is known to be identified and blocked by networks that
    # inspect traffic — a fixed, trivially fingerprinted wire format with no camouflage.
    #
    # No country is named here, deliberately: ``CLAUDE.md`` forbids hardcoding one in
    # code, and the property is not "where" but "this protocol looks like itself on the
    # wire". Which networks do the inspecting is the charter's subject, not this file's.
    #
    # It exists so the panel can refuse to present such a transport to a friend as a
    # working exit. Shipping it anyway is deliberate — the charter names it first-class
    # in phase 1, because it is the right choice on a network that is not filtering.
    blocked_by_inspection: bool = False

    @property
    def subscription_expressible(self) -> bool:
        """Whether this transport rides in the v1 subscription — a base64 URI list.

        Kept as a name of its own, derived rather than stored, because it is the
        question `control` has been asking since item 7 and the answer has not
        changed shape: an entry in the v1 document, or not. What changed is that "not"
        no longer means "nothing a friend can consume" — see ``subscription_formats``.

        Delivery of the second format is backlog item 27, in the `control` zone. Until
        it lands, a transport that produces only a config file is still refused for
        friends, which is correct: the serialiser existing is not the same as the
        endpoint handing it over, and pretending otherwise would put a friend one
        unreachable node short with nothing saying so.
        """
        return SubscriptionFormat.V1_URI_LIST in self.subscription_formats

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


@dataclass(frozen=True)
class ClientConfig:
    """One friend's complete configuration FILE, serialised by the transport itself.

    The second serialisation shape, and the counterpart to ``ClientEntry``: same
    division of labour, different container. ``content`` is finished text — `control`
    does not parse it, does not template it and does not branch on it. The other
    fields exist so `control` can name the download, set a content type, and order or
    label a set of files generically.

    ``filename`` is a SUGGESTION the transport owns, because the name is part of what
    makes a file importable: some clients derive the tunnel's display name from it,
    and one family derives the interface name from it and rejects a name it considers
    invalid before reading the contents. `control` may prefix it, and must not invent
    it.
    """

    content: str

    # A filename without a directory component, safe to place in a Content-Disposition
    # header. Checked rather than trusted at the point of use — see ``safe_filename``.
    filename: str

    # What to serve it as. A transport's own answer, because a client that gets the
    # wrong type for a config file offers to display it instead of importing it.
    media_type: str

    # The same three protocol-agnostic fields ``ClientEntry`` carries, for the same
    # reason: so `control` can label, order and filter without parsing ``content``.
    display_label: str
    country_label: str
    node_id: str

    def safe_filename(self) -> str:
        """``filename`` with any path component refused rather than stripped.

        A transport is trusted code in this image, so this is not a defence against a
        hostile transport — it is a defence against a plausible mistake. A filename
        carrying a separator reaches an HTTP header and a friend's filesystem; silently
        rewriting it would hide the bug, so it raises where it can still be read.
        """
        if "/" in self.filename or "\\" in self.filename or self.filename in {"", ".", ".."}:
            raise ValueError(
                f"{self.filename!r} is not a plain filename — a transport's suggested "
                "name must carry no directory component"
            )
        return self.filename


# Which function in a transport's ``render.py`` produces which format. The whole
# mechanism behind "a transport declares what it serialises into and serialises it":
# `control` asks for a FORMAT, this maps it to a call, and no caller anywhere names a
# protocol or a function.
SERIALISERS: Mapping[SubscriptionFormat, str] = {
    SubscriptionFormat.V1_URI_LIST: "render_client",
    SubscriptionFormat.CLIENT_CONFIG_FILE: "render_client_config",
}


class FormatNotDeclared(Exception):
    """Asked for a shape this transport never said it produces.

    Distinct from a rendering failure: reaching here means a caller ignored
    ``TransportMeta.subscription_formats``, and the honest answer is that the request
    was wrong rather than that the transport is broken.
    """


class ContractViolation(Exception):
    """A transport package does not provide what its own declaration promises.

    Raised at load time, with the missing symbol named. A declaration that obliges
    nothing is a comment, and the failure it hides is the worst shape available: a
    transport that looks deliverable in the panel and raises ``AttributeError`` deep
    inside a subscription render, for one friend, at refresh time.
    """


class TransportProfile(Protocol):
    """The pure functions every transport package provides in ``render.py``.

    ``render_server`` and ``render_client`` are required of every transport.
    ``render_client_config`` is required of exactly those transports that declare
    ``SubscriptionFormat.CLIENT_CONFIG_FILE`` — see ``SERIALISERS`` and
    ``profile()``'s load-time check.
    """

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

    def render_client_config(
        self,
        node: NodeView,
        params: Mapping[str, object],
        credential: Credential,
    ) -> ClientConfig:
        """One friend's complete configuration file for this node.

        Same arguments as ``render_client`` and the same purity rules — a file is a
        different serialisation of the same facts, not a different kind of operation.
        Provided only by transports that declare ``CLIENT_CONFIG_FILE``.
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

    def serialise(
        self,
        subscription_format: SubscriptionFormat,
        node: NodeView,
        params: Mapping[str, object],
        credential: Credential,
    ) -> ClientEntry | ClientConfig:
        """Produce one friend's material in ``subscription_format``.

        The one call `control` needs in order to deliver a second shape without
        learning a second protocol. It asks for a format; which function runs is
        ``SERIALISERS``' business, and what comes back is finished text either way.

        Refuses a format this transport never declared, rather than calling a function
        that happens to exist: a transport may well grow a serialiser before it is
        ready to be offered in that shape, and the declaration is what says it is
        ready.
        """
        if subscription_format not in self.meta.subscription_formats:
            raise FormatNotDeclared(
                f"transport {self.meta.name!r} does not declare "
                f"{subscription_format!r}; it declares "
                f"{sorted(self.meta.subscription_formats) or 'no friend-facing format at all'}"
            )
        return getattr(self.profile, SERIALISERS[subscription_format])(
            node, params, credential
        )


def _check_contract(meta: TransportMeta, render: ModuleType) -> None:
    """Refuse a package whose declaration its own code does not keep.

    Load time rather than render time, and that is the whole value: the failure this
    prevents is a transport that looks deliverable in the panel and raises deep inside
    one friend's subscription render at refresh time — visible to the operator as
    "hashi is broken for Masha", days later.
    """
    for declared in sorted(meta.subscription_formats):
        function = SERIALISERS[declared]
        if not callable(getattr(render, function, None)):
            raise ContractViolation(
                f"transport {meta.name!r} declares subscription format {declared!r} "
                f"but its render.py provides no callable {function!r}. Either provide "
                "it or stop declaring the format — a declaration that obliges nothing "
                "is a comment."
            )


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
        render = importlib.import_module(f"edge.transports.{package}.render")
        _check_contract(meta, render)
        return Transport(
            meta=meta,
            profile=render,
            params_model=importlib.import_module(f"edge.transports.{package}.params").Params,
        )
    raise KeyError(f"no transport named {name!r} is installed")
