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

      **It has been widened eight times since, each deliberately, each recorded
      where it happened.** ``ConfigFormat`` came with the WireGuard family (see its
      own docstring). ``SubscriptionFormat`` came with backlog item 26: a transport
      now declares the SET of subscription shapes it serialises into rather than a
      yes/no about the v1 URI list, and serialises each of them itself.
      ``hop_capable`` and ``blocked_by_inspection`` came with backlog item 28, whose
      text states both charter constraints as "the transport must declare this
      machine-readably" — and a declaration has nowhere else to live.

      ``Egress`` came with M14: a rendered tunnel has to say whether the traffic it
      decrypts may leave the node, because the field answer was that it left nowhere
      and nothing said so. It is a keyword on ``render_server`` with a fail-closed
      default, so it widens the contract without making any existing call wrong.
      ``exit_via`` came with M3 and is that same keyword's missing half: a policy of
      "out through the hop" is unactionable without the address the hop runs through,
      and an address is the largest thing that can be said about a hop without saying
      what it is. Same shape — a keyword, defaulting to the answer every node had before.

      ``PeerAddress`` came with M17, found in the field: a transport whose data plane
      identifies each consumer BY ADDRESS needs one address per user, and had one
      parameter for all of them — so it served exactly one friend against a charter
      scale of ~30-50. A transport now declares that each consumer needs an address of
      its own, and where the room for them comes from; `control` allocates, and
      ``edge/addressing.py`` does the arithmetic. Optional, defaulting to ``None``, so
      not one existing ``META`` changes: a transport that identifies its consumers by
      key material or by a UUID says nothing and is asked for nothing.

      ``Retirement`` came with M20, and is the first of the seven that takes something
      AWAY rather than adding a capability: a transport measured to be unusable on the
      hosts this project builds has to stop being suggested, and the only alternative
      was a name compared in the panel — the exact branch this whole module exists to
      prevent. It subtracts the transport from what `control` PROPOSES and from nothing
      else, so the package stays, discovery stays, and the rows already running it
      render the same bytes. Optional, defaulting to ``None``, so not one existing
      ``META`` changes.

      ``Datapath`` came with M25, and is the one that was already load-bearing before it
      was written down: ``egress.py`` has expressed the same split as two functions since
      M14, and nothing declared which of them a transport uses — so `control` accepted a
      kernel tunnel for the friends of a node that dials a hop, granted every friend a
      credential on it, handed one of them a complete configuration file, and only the
      apply refused. The same shape as ``PeerAddress`` and ``Retirement``, then: a
      property of one package, derived four surfaces away by everything that needed it,
      until the field measured what that cost. Defaulted to the answer that costs a
      refusal rather than to the one that costs a friend a dead tunnel, so no existing
      ``META`` is made wrong by it and the two that re-originate say so out loud.

      None of the eight was a branch on a protocol; each replaced one with a
      vocabulary or a property. None was free either, and a reader deserves to know
      the contract has moved and why rather than to discover it from a diff.
"""

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import ModuleType
from typing import Protocol

import edge.transports
from edge.egress import Egress
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


class Layer4(StrEnum):
    """A transport-layer protocol a transport's listening socket binds.

    Declared because `control` has to answer one question the node's kernel would
    otherwise answer for it at three in the morning: may these two transports sit on
    one node's one port? Two sockets on one number are a collision only when they are
    the same protocol — a TCP proxy on 8443 and an obfuscated UDP tunnel on 8443 are
    two sockets and no conflict, and the data planes run with ``network_mode: host``,
    so this is a real question about a real bind.

    NOT ``TransportMeta.family``, which is the answer to a different question and says
    so: its contract check states that `control` reads it *"to decide nothing at all —
    an operator reads it to tell UDP from TCP"*. It is free text (``"tcp-tls" | "udp" |
    …``), so a transport declaring ``"quic"`` or ``"udp-obfuscated"`` would be sorted
    into a bucket of its own and would collide with nothing. A rule keyed on it would
    be a rule expressed in terms of the wrong concept, which is the exact defect M15
    exists to close, pointed the other way.
    """

    TCP = "tcp"
    UDP = "udp"


class Datapath(StrEnum):
    """How a transport's data plane moves what it decrypts, and therefore whose traffic
    it can send out through a hop.

    The only respect in which `control` has to know: a node that dials one gives its
    friends ``Egress.HOP``, and one kind of data plane can honour that for somebody
    else's packets while the other cannot.

    M25, measured on the owner's real Amsterdam leaf. A node that dials a hop gives its
    friends ``Egress.HOP`` — out through the hop and nowhere else — and the two data
    planes this image ships obey that in two incompatible ways. One hands what it
    decrypts to the node's own kernel, and the only way out a kernel tunnel can express
    is a SOURCE ROUTE from the node's own address (``egress.wg_quick_egress``): a
    friend's packets do not carry that address, so they match no such rule and leave by
    the node's own route instead. The other terminates the friend's connection and opens
    its own, which it binds to that same address (``egress.exit_origin``) — and that one
    works, which is what M25's walk proved end to end.

    So it is a property OF THE TRANSPORT, declared here, and never a family or a name
    compared in `control` — the rule the whole of this module exists to keep. `control`
    reads one derived answer, ``TransportMeta.serves_friends_through_a_hop``, and refuses
    both doors that would otherwise produce a node whose configuration cannot be rendered:
    enabling such a transport for friends on a node that dials a hop, and giving a hop to
    a node that already offers one.

    Two members and not a boolean, because these are two KINDS of data plane rather than
    one capability a transport does or does not have — and the answer a reader needs from
    a ``meta.py`` is what the thing IS, not which of two refusals it escapes. It is also
    the split ``edge/egress.py`` is already written around: its two expressions of one
    policy are exactly these two members, one function each.
    """

    # The node's kernel routes what this tunnel decrypts. It cannot carry a friend's
    # traffic out through a hop — see the class docstring, and ``wg_quick_egress``, which
    # refuses to render exactly that rather than emitting a file whose tunnel comes up
    # and whose traffic surfaces in the country the hop exists to leave.
    #
    # THE DEFAULT, and fail-closed on purpose. A package that says nothing is held to the
    # answer that costs a refusal an operator can read, rather than to the one that is
    # accepted at three surfaces and refused at the apply — which is the defect this
    # declaration was added to close, so defaulting to the other member would rebuild it
    # for the next transport. A proxy declares itself; a forgetful one is told to.
    KERNEL_ROUTED = "kernel-routed"

    # The transport terminates the consumer's connection and opens its own, which it can
    # bind to whatever address the policy names. That is what makes a hop expressible for
    # somebody else's traffic, and it is also what makes the hop fail CLOSED: while the
    # hop is down the new connection cannot be opened at all.
    RE_ORIGINATING = "re-originating"


# Why a kernel-routed data plane cannot be a friend's way into a hop, in the words an
# operator reads. Declared beside the vocabulary it explains rather than written in
# `control`, for ``Retirement.reason``'s reason: the fact is about a DATA PLANE, `control`
# has no way to know it, and the sentence a render refuses with
# (``egress.wg_quick_egress``) and the sentence a door refuses with have to be one rule
# said once. Each door composes its own remedy around it — "take the hop away" is advice
# only where a hop already exists.
#
# It names no protocol and no node, so both doors and both surfaces can print it whole.
NOT_THROUGH_A_HOP = (
    "its data plane hands what it decrypts to this node's own kernel, and the way out "
    "through a hop is a source route from the node's OWN address — a friend's packets do "
    "not carry it, so they would leave by the node's own route instead: an exit in the "
    "country the hop exists to leave, with every screen green."
)


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
class PeerAddress:
    """A transport declaring that each of its consumers needs an address of its own.

    Two field names and nothing else, which is the whole of what `control` needs in
    order to give thirty people thirty addresses without learning a protocol:

    * ``name`` is the parameter a consumer's own address is read from — the same name
      the renderers already look for in ``Credential.secrets`` and fall back to in
      ``params``. In ``params`` it is the pool's FIRST address, which is what makes a
      transport enabled before M17 render the same bytes afterwards.
    * ``within`` is the parameter whose network bounds the pool. It is declared rather
      than derived because "the range these addresses come out of" is the transport's
      own fact: a kernel tunnel's interface address carries it, and another data plane
      might carry it somewhere else entirely.

    The address is ALLOCATED, never minted, and that is the difference from ``KeySpec``:
    `control` generates key material from a kind, and hands out an address by taking the
    lowest one nobody holds. So ``name`` may not also be a ``KeySpec`` name — a
    generator would overwrite an allocation — and ``_check_declaration`` refuses a
    package that says both.

    Declaring this is what makes the scale expressible. Without it, a data plane that
    routes by address has one address for everybody, and its own renderer refuses the
    second friend rather than hijacking the first's return path.
    """

    name: str
    within: str


@dataclass(frozen=True)
class Retirement:
    """A transport declaring that it must no longer be OFFERED, and why.

    The narrowest possible statement, and note what it does NOT say: nothing here
    removes the package, stops it being discovered, stops ``profile()`` loading it, or
    stops a node that already runs it rendering exactly the bytes it rendered before.
    A retired transport is one that must not be PROPOSED — it is subtracted from the
    lists `control` builds when it asks an operator to choose a transport, and from
    nothing else. That split is the whole design: the fleet's existing rows keep
    working, and nobody is offered the thing anew.

    ``reason`` is required, and it is carried here rather than written in `control`
    because it is a fact about this protocol on the hosts this project builds — the
    panel has no way to know it, and a reader who finds a package in the tree that is
    never offered deserves the answer without going to ``git log``. It is the only
    field, which is also why this is a dataclass rather than a bare ``str | None``: an
    empty string in a nullable field reads as "not retired", so a package could retire
    itself and say nothing, or fail to retire itself and look as though it had.
    ``_check_declaration`` refuses the empty reason, which a plain string could not
    distinguish from the ordinary case.

    Retiring a future transport is therefore one line in its own ``meta.py`` and no edit
    anywhere else — the same property ``hop_capable`` and ``blocked_by_inspection``
    have, and the reason none of the three is a name compared in `control`.
    """

    reason: str


@dataclass(frozen=True)
class TransportMeta:
    """What the control plane may know about a transport without knowing which."""

    name: str
    family: str          # "tcp-tls" | "udp" | ...
    needs_tls: bool

    # Which transport-layer protocols this transport's listener actually binds, on the
    # port below. A SET because a transport may legitimately bind both, and because the
    # question asked of it is "do these two overlap" rather than "are these two equal".
    #
    # Read by `control` to decide whether two transports on one node may hold the same
    # port number (``control/app/services/placement.py``). It is the one thing in this
    # declaration that is about the SOCKET rather than about the protocol's shape, which
    # is why it is not ``family``: see ``Layer4``.
    listens_on: frozenset[Layer4]

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

    # Which of this transport's PARAMETERS both ends of a hop must carry identically —
    # M26's first acceptance walk, and the same shape as ``KeySpec.shared_between_peers``
    # one field over: that one says which minted MATERIAL is symmetric, and this says
    # which operator-typed values are.
    #
    # Declared by the package rather than known here, because what has to match is a fact
    # about a protocol's wire format and this module recognises none. Empty by default:
    # most parameters are properly per-end — a port, an address, an MTU — and a transport
    # that needs none of this should not have to say so.
    #
    # It exists because the walk counted the boxes. Establishing one hop is 22 empty
    # fields, 11 per end, and four of them per end are values that must be typed
    # identically at both ends by hand or the tunnel comes up and carries nothing: two
    # valid configuration files, a daemon happy at each end, and no packet ever arriving.
    # That is the failure this project keeps producing, so it is refused before either end
    # is written (``edge.relay``) rather than left to be discovered on a live node.
    hop_matched_params: tuple[str, ...] = ()

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

    # Whether each consumer of this transport needs a tunnel address of its own, and
    # where that address is read from — see ``PeerAddress``.
    #
    # Optional, and defaulting to "no", because most transports do not: a VLESS client
    # is identified by a UUID and two of them on one node share everything but that.
    # A default of None is therefore the right answer rather than a silent wrong one,
    # which is the opposite of ``listens_on``'s case for being required — and it means
    # no shipped ``META`` had to change when this field arrived.
    peer_address: PeerAddress | None = None

    # What this transport's data plane does with the traffic it decrypts, and therefore
    # whether a friend on it can be carried out through their node's hop — see
    # ``Datapath``, including why the default is the restrictive member.
    #
    # Declared rather than inferred, and that is M25's whole finding: the fact existed
    # already — it is which of ``egress.py``'s two expressions a renderer calls — and
    # `control` had no way to ask, so it accepted the one combination that cannot be
    # rendered and found out at the apply, three surfaces and one delivered file later.
    datapath: Datapath = Datapath.KERNEL_ROUTED

    # Whether this transport has been withdrawn from every list `control` builds when it
    # asks an operator to choose a transport — and, if so, why. See ``Retirement``.
    #
    # Optional and defaulting to "no" for the same reason ``peer_address`` is: the
    # ordinary answer is that a shipped transport is offered, and no existing ``META``
    # should have to say so. A package says this only when it has stopped being an
    # honest suggestion.
    #
    # It is deliberately NOT a refusal. Discovery, ``profile()``, rendering, key
    # material, an existing node's row and an existing consumer's configuration are all
    # untouched — a fleet does not break because a protocol stopped being recommended.
    # `control` reads it once per chooser; see ``control/app/services/transports.py``.
    retired: Retirement | None = None

    @property
    def subscription_expressible(self) -> bool:
        """Whether this transport rides in the v1 subscription — a base64 URI list.

        Kept as a name of its own, derived rather than stored, because it is the
        question `control` has been asking since item 7 and the answer has not
        changed shape: an entry in the v1 document, or not. What changed is that "not"
        no longer means "nothing a friend can consume" — see ``subscription_formats``.

        NOT "can a friend receive this", which this paragraph used to say it was: delivery
        of the second format was backlog item 27 and it has LANDED —
        ``GET /sub/{token}?format=client-config-file`` answers the same bearer token with
        an archive of that friend's configuration files. The distinction survived the
        wording that described the world before it: a transport can be undeliverable-by-
        link and perfectly deliverable, and `control` still needs this answer because the
        base64 document is assembled from URIs and nothing else can go in it.

        Two surfaces in `control` went on reading it as "cannot be handed over" and said
        so to the operator, in opposite directions, until M20's acceptance found one of
        them. Anything asking this question is asking about the LINK.
        """
        return SubscriptionFormat.V1_URI_LIST in self.subscription_formats

    @property
    def hop_expressible(self) -> bool:
        """Whether an entry→leaf hop can actually be BUILT out of this transport.

        Derived for the same reason ``subscription_expressible`` is, and it answers the
        question every chooser and every hop form has really been asking. ``hop_capable``
        alone does not: it is a permission and says so — *"a charter constraint rather
        than a capability"* — so it defaults to True and a transport that has simply
        never been shaped like a hop end says nothing and reads as able.

        The second half is the ability, and it is ``peer_address``. A hop is two ends of
        one tunnel network, each holding an address of its own and naming the other as
        its single authorised peer: ``edge/relay.py`` is written in those terms from end
        to end — the two addresses are compared for collision and for a common network,
        each is handed to the far end as ``peer_tunnel_address``, and the entry's way out
        is a source route from its own one (``exit_via``). A transport that hands its
        consumers no address of their own has nothing to put in any of those places. That
        is a real difference between protocol families rather than a gap in this module:
        a userspace proxy terminates a connection and originates a new one from the node,
        so it has no second end to agree with about anything.

        Asked HERE, once, because the alternative is each surface deriving it again from
        two fields and one of them getting it wrong — which is how a control plane came
        to advertise a capability whose renderer raised ``HopNotRenderable`` on the first
        press. ``edge/relay.py`` refuses on this, the panel's hop chooser is built from
        it, and ``GET /api/transports`` reports it.
        """
        return self.hop_capable and self.peer_address is not None

    @property
    def serves_friends_through_a_hop(self) -> bool:
        """Whether friends on a node whose own way out is a HOP may be offered this.

        Derived here, once, for ``hop_expressible``'s reason and with a sharper edge: the
        two surfaces that need it are two different services in `control`, and the
        combination they are asked about is one neither of them can render — so each
        deriving it again from ``datapath`` is each of them holding an opinion about what
        a data plane can do. They read this instead, and the opinion stays in this file.

        NOT the same question as ``hop_expressible``, and the difference is whose traffic
        is being asked about. That one is "can this transport BE the hop" — two ends of
        one tunnel network, each with an address of its own — and the WireGuard family is
        the only thing in this image that can. This one is "can a friend's traffic be
        carried THROUGH a hop by this transport", and the answer is the exact opposite
        pair: the proxies can, the kernel tunnels cannot. A transport can be either, both
        or neither, which is why they are two properties and not one.

        Says nothing about a node with NO hop. There every shipped transport exits by the
        node's own route, which is what a leaf and a single box have always done and must
        keep doing — the caller pairs this answer with its own node's topology.
        """
        return self.datapath is Datapath.RE_ORIGINATING

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

    def render_server(
        self,
        node: NodeView,
        params: Mapping[str, object],
        clients: Sequence[Credential] = (),
        *,
        egress: Egress = Egress.NONE,
        exit_via: str | None = None,
    ) -> str:
        """The node's complete config file for this transport. Deterministic.

        ``clients`` is every consumer this node authorises on this transport — friends
        on a friend-facing transport, the single far node on a hop end.

        ``egress`` says which way out packets this transport decrypts take
        (``edge/egress.py``, M14.3 and M3). It is a keyword with a fail-closed default so
        that a caller which has not thought about it gets the answer that fails loudly: a
        tunnel with no exit produces a friend who reports at once that nothing loads,
        while a tunnel that exits where it should not produces a friend who reports
        nothing at all.

        ``exit_via`` is the other half of the same answer and nothing more: the ADDRESS on
        this node that the way out runs through, when the policy is ``Egress.HOP``.
        ``None`` means this node's own route, which is what a node without a hop has
        always had. It is an address and never a protocol, a name or an interface — which
        is precisely what lets an entry node route friend traffic into a hop without any
        transport learning what the hop is made of.

        Every transport takes both, including those whose data plane forwards no packet in
        the kernel and therefore renders no rule for either. That is what keeps `control`
        from having to know which is which.
        """
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


def _check_declaration(package: str, meta: object) -> TransportMeta:
    """Refuse a package whose METADATA does not meet the contract — at DISCOVERY.

    Everything checkable from ``meta.py`` alone is checked here, which is what makes the
    failure land at the right moment. ``discover()`` is called by every screen in the
    panel and by every subscription render, so a malformed package found here is one
    error message on the fleet page; the same package found later is an exception inside
    one friend's refresh, or a node configured with a transport that cannot mint a
    credential. Backlog item 30, S2.

    What is NOT checked here is anything requiring ``render.py``: importing a renderer
    for every discovery call would make listing transports as expensive as rendering
    them. That half is ``_check_contract``, run by ``profile()``.
    """
    if not isinstance(meta, TransportMeta):
        raise ContractViolation(
            f"edge.transports.{package}.meta.META is {type(meta).__name__}, not a "
            "TransportMeta. Every transport declares itself through that type; nothing "
            "else can be read by `control`."
        )

    if not meta.name:
        raise ContractViolation(f"the transport in {package!r} declares no name")
    if not meta.family:
        raise ContractViolation(
            f"transport {meta.name!r} declares no protocol family. `control` reads it to "
            "decide nothing at all — but an operator reads it to tell UDP from TCP, and "
            "an empty one is a blank column on the fleet page."
        )

    if not meta.listens_on or not all(
        isinstance(layer, Layer4) for layer in meta.listens_on
    ):
        raise ContractViolation(
            f"transport {meta.name!r} does not declare which transport-layer protocols "
            "its listener binds. `control` reads it to decide whether two transports may "
            "share one node's port number, and a transport that declares none would be "
            "treated as colliding with nothing — so the first pair on one port would be "
            "found by a container that cannot bind. Declare `listens_on`, as a frozenset "
            "of Layer4."
        )

    low, high = meta.port_range
    if not 1 <= low <= high <= 65535:
        raise ContractViolation(
            f"transport {meta.name!r} declares the nonsensical port range "
            f"{meta.port_range}. Nothing would ever validate against it."
        )

    # A per-client identity is what makes the charter's sixth criterion expressible: with
    # nothing scoped to one consumer, a friend cannot be revoked without affecting the
    # others, because there is no row that belongs only to them.
    client_scoped = {
        spec.name for spec in meta.key_material if spec.scope is KeyScope.CLIENT
    }
    if "subject" not in client_scoped:
        raise ContractViolation(
            f"transport {meta.name!r} declares no client-scoped KeySpec named 'subject', "
            "so no friend can be given access to it individually — and therefore no "
            "friend could be revoked from it without affecting the others."
        )

    unknown = meta.subscription_formats - set(SERIALISERS)
    if unknown:
        raise ContractViolation(
            f"transport {meta.name!r} declares subscription format(s) "
            f"{sorted(str(u) for u in unknown)} that delivery has no serialiser for."
        )

    if meta.peer_address is not None:
        pooled = meta.peer_address
        if not pooled.name or not pooled.within:
            raise ContractViolation(
                f"transport {meta.name!r} declares that each consumer needs an address of "
                "its own, and leaves one half of that declaration empty. Both are needed: "
                "the parameter a consumer's own address is read from, and the parameter "
                "whose network says how much room there is for them."
            )

        # An address is ALLOCATED, never minted — so the name it is filed under must not
        # also be a name `control` generates a value for. A package that declared both
        # would have every user's address overwritten by a fresh key at the moment their
        # credential was minted, which reads as "everyone got the same address" and is
        # refused by the renderer one step later, for the wrong reason.
        minted = {spec.name for spec in meta.key_material}
        minted |= {spec.public_name for spec in meta.key_material if spec.public_name}
        if pooled.name in minted:
            raise ContractViolation(
                f"transport {meta.name!r} declares that each consumer's own address is "
                f"read from {pooled.name!r}, and also declares key material under that "
                "name. An address is allocated from a pool, never generated: `control` "
                "would mint a value over the address it had just handed out."
            )

    # A retirement with nothing in it is the one shape this declaration can take that
    # says less than saying nothing. The field is what removes the transport from every
    # chooser, so an empty reason leaves a package in the tree that the panel never
    # offers and no file explains — which is exactly the reader the reason exists for.
    if meta.retired is not None and not meta.retired.reason.strip():
        raise ContractViolation(
            f"transport {meta.name!r} declares itself retired and gives no reason. The "
            "reason is the declaration's whole value to a reader: without it the panel "
            "stops offering a package that is still in the tree, and nothing on disk "
            "says why."
        )

    # The one implication between the two declarations item 28 added. A package with both
    # True compiles and reads plausibly and hands the fleet a hop that cannot come up.
    if meta.blocked_by_inspection and meta.hop_capable:
        raise ContractViolation(
            f"transport {meta.name!r} declares both that a filtering network identifies "
            "it and that it may carry an entry-to-leaf hop. That hop crosses such a "
            "network by definition, so this combination configures both nodes correctly "
            "and never forms a tunnel."
        )

    return meta


def _check_contract(meta: TransportMeta, render: ModuleType, params_model: type) -> None:
    """Refuse a package whose declaration its own code does not keep.

    Load time rather than render time, and that is the whole value: the failure this
    prevents is a transport that looks deliverable in the panel and raises deep inside
    one friend's subscription render at refresh time — visible to the operator as
    "hashi is broken for Masha", days later.

    ``params_model`` is here for the same reason ``render`` is: ``PeerAddress`` names two
    PARAMETERS, and a declaration naming a parameter the model does not have is a pool
    `control` can neither size nor read the first address of. That cannot be checked from
    ``meta.py`` alone, so it belongs on this side of the split rather than in
    ``_check_declaration``.
    """
    pooled = meta.peer_address
    if pooled is not None:
        fields = params_model.model_fields
        for named, what_it_is in (
            (pooled.name, "the parameter each consumer's own address is read from"),
            (pooled.within, "the parameter whose network the pool is drawn from"),
        ):
            if named not in fields:
                raise ContractViolation(
                    f"transport {meta.name!r} declares {named!r} as {what_it_is}, and its "
                    f"params.py has no such field. Nothing would validate the operator's "
                    "range, and every user would be allocated an address out of a pool "
                    "whose bounds cannot be read."
                )

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
        module = importlib.import_module(f"edge.transports.{name}.meta")
        meta = _check_declaration(name, getattr(module, "META", None))
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
        module = importlib.import_module(f"edge.transports.{package}.meta")
        meta = _check_declaration(package, getattr(module, "META", None))
        if meta.name != name:
            continue
        render = importlib.import_module(f"edge.transports.{package}.render")
        params_model = importlib.import_module(f"edge.transports.{package}.params").Params
        _check_contract(meta, render, params_model)
        return Transport(meta=meta, profile=render, params_model=params_model)
    raise KeyError(f"no transport named {name!r} is installed")
