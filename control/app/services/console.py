"""What the redesigned console puts on screen, and nothing more.

WHAT: the Overview's four stat cards, the node rows they summarise, the friend rows
      the Users screen lists, the hop rows the Hops screen lists, the capability row
      the Transports screen lists per protocol this image ships, and the key row the
      Keys & configs screen lists per transport enabled on a node, and the offer row
      and state choices the Nodes screen's own actions are built from, the rows
      the Settings screen states this control plane's own configuration in, and the
      rows the Audit log screen lists one per change the operator has made.
WHY:  the design (``design/README.md``) drew four cells that measure PEOPLE —
      "throughput now", "last seen", node "load", and a whole Traffic screen. The
      charter's non-goals forbid every one of them: *"No traffic logging, no DNS
      logs, no per-user analytics. Not 'off by default' — absent, so there is nothing
      to seize or subpoena."* ``docs/decisions.md`` decision 6 replaced them with
      facts the control plane already holds, and this module is where that decision
      becomes code — so there is one file to read to see what the console may know.
HOW:  every figure here is derived from configuration rows: node states, credential
      grants, applied digests. Nothing counts an event, nothing has a clock in it
      except ``created_at`` on a row the operator themselves created — and, since
      M10.4, ``AuditEntry.at``, which is the same kind of clock: the moment a change
      the OPERATOR made committed, never the moment anybody used the service — and no
      function in this module could be extended into a per-connection figure without
      adding a column that ``test_no_model_records_anything_about_a_connection`` would
      refuse.

The one figure that looks like a measurement and is not: ``nodes_served``. It counts
the credentials WE minted for a friend against the node-transports currently serving —
"is this person covered", a property of our own configuration. It does not move when
they connect, it does not move when they do not, and it is identical for a friend whose
device is in a drawer.
"""

import dataclasses
import datetime
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.api import schemas
from control.app.errors import NotFound
from control.app.models import (
    AuditAction,
    Credential,
    Friend,
    Node,
    NodeState,
    NodeTransport,
    Subscription,
    TransportPurpose,
)
from control.app.services import (
    addresses,
    apply,
    audit,
    friends,
    keymaterial,
    nodes,
    relay,
    rotation,
    transports,
)
from control.app.settings import (
    AUDIT_RETENTION_MAX_DAYS,
    AUDIT_RETENTION_MIN_DAYS,
    Settings,
)
from edge.bootstrap import node_stack
from edge.registry import KeyScope, TransportMeta, discover

logger = logging.getLogger(__name__)

# What the drift cell can say. Strings rather than an enum because they are read only
# by a template and by the operator; a state machine here would be ceremony.
# What a hop's state tag can say. The same reasoning as the drift strings below: read
# only by a template and by the operator, so a state machine here would be ceremony.
# ``ESTABLISHED`` is deliberately narrower than "both ends exist" — see ``hop_rows``.
HOP_ESTABLISHED = "established"
HOP_PENDING = "pending"
HOP_INCOMPLETE = "incomplete"

IN_SYNC = "in sync"
NEVER_APPLIED = "never applied"
NOTHING_ENABLED = "nothing enabled"
UNRENDERABLE = "cannot render"

# What the Transports screen may say about a protocol, as the words the operator
# reads. Every one of them is the prose for a DECLARATION a transport makes about
# itself (``edge.registry.TransportMeta``) — never for a protocol's name. That is why
# they are here and not in the template: a template choosing between them by name
# would be the ``if transport ==`` the whole contract exists to prevent, and a template
# writing them inline would put the charter's loudest warning in the one file no zone
# invariant reads.
TRANSPORT_IDENTIFIED = "identified and blocked — do not offer this as a working exit"
TRANSPORT_CAMOUFLAGED = "obfuscated or TLS-shaped"
TRANSPORT_NO_HOP = "never on an entry→leaf hop"
TRANSPORT_NO_DELIVERY = "nothing a user can consume — hop use only"
TRANSPORT_UNDELIVERED = "not in a user's link yet — this panel cannot hand it over"

# What it means, on the screen the operator learns the protocols from, that a transport
# declares each of its consumers needs an address of their own — M17.2. Read from
# ``TransportMeta.peer_address`` through ``addresses.spec_for``, the one place `control`
# asks that question: this sentence appears on a protocol that declares it and on no
# other, and a package added later gets it by declaring, never by being listed.
#
# It says "sized per node" because that is the fact an operator is missing when they meet
# the pool box for the first time: the number is a column on the node-transport record
# and not a property of the protocol, so two nodes running the same protocol can serve
# different numbers of people.
TRANSPORT_ADDRESS_PER_USER = (
    "gives every user their own address inside the tunnel, from a pool sized on each "
    "node that runs it"
)

# The sentence this milestone's acceptance line is about, and the whole reason the
# screen exists: a protocol the panel refuses to offer as an exit, and WHY, in words an
# operator can act on. Written from ``blocked_by_inspection`` alone, so it names no
# country — which networks do the inspecting is the charter's subject, not this file's
# — and no protocol. A transport that stops declaring itself identified stops being
# warned about, with nothing to edit here.
#
# IT STATES A CAPABILITY AND RECOMMENDS NOTHING, deliberately. An earlier draft ended
# "enable it only where nothing is filtering", which is the one clause that did not
# follow from any declaration — and ``docs/decisions.md`` (2026-09-09) contradicts it
# for the only transport it can apply to: on a ufw host the pinned plain-WireGuard
# image lands its forwarding rules on a backend the host's own DROP does not traverse,
# so an operator who took that advice on an unfiltered network would get a handshake
# that completes and traffic that never moves. A table that states what a protocol IS
# only has to be right about the protocol; the moment it tells the operator what to DO
# it has to be right about the whole stack, and here it is not. The gap is background
# in ``docs/tracker/M9/carry-over.md``: no field of ``TransportMeta`` expresses it, and
# closing it is an ``edge``-side declaration rather than a name compared here.
TRANSPORT_WHY_IDENTIFIED = (
    "it has no camouflage. The wire format is fixed and looks like itself, so a "
    "network that inspects traffic can name the protocol and drop it: both ends stay "
    "correctly configured, no tunnel comes up, and nothing on the user's device says "
    "what happened."
)


# What the Keys & configs screen may say about the material a node holds — and every
# one of these is here rather than in a template for the same reason the transport
# sentences above are: they are the console's own words about a DECLARATION, and a
# template choosing between them would be choosing by protocol.
#
# UI-PATTERNS §9 in one table: where key material could appear, the panel prints the
# rule instead. There is no branch anywhere on this screen that could print a value —
# a fingerprint is computed from published material only (``keymaterial.fingerprint``),
# and a transport with none gets the sentence below rather than something invented.
KEY_HELD_NOT_SHOWN = (
    "held, never shown — this transport declares no public half to fingerprint"
)
KEY_NOT_IN_THIS_IMAGE = (
    "not in this image — nothing here can read, re-mint or validate this material"
)

# Who the material on one row is for. A hop end's second holder is the far NODE rather
# than a person, which is a distinction the operator has to be able to make before they
# press rotate: re-keying a hop end takes a tunnel down until both ends are applied,
# and re-keying a friend-facing transport re-mints credentials people are holding.
KEY_SCOPE_NODE = "this node"
KEY_SCOPE_HOP = "this node, and the far end of the hop"

# What a rotation COSTS at one end of a hop, when the transport has declared that some
# of its material is SYMMETRIC (``KeySpec.shared_between_peers``, docs/decisions.md
# 2026-08-09). Written from the DECLARATION, so a transport with no symmetric material
# never says it and no protocol is named to decide.
#
# It was a CONSEQUENCE and is now a cost, which is the change the fix to ``rotate_keys``
# bought: rotating one end used to leave the far end holding a value it could not
# handshake with, and the sentence here said so. Both ends are now re-keyed in one
# transaction and both nodes pushed, so what is left to state is the window between the
# two pushes — the tunnel is down while it is open, and stays down if the second node
# cannot be reached.
KEY_SHARED_WITH_PEER = (
    "This transport declares material that both ends of a hop must hold the same copy "
    "of, so rotating here re-keys the far end with it and pushes both nodes. The tunnel "
    "is down from the moment the first node takes the new material until the second one "
    "does — and if the second cannot be reached, it stays down until you apply it."
)

# THE ONE CLAIM BOTH KEY DIALOGS MAKE ABOUT A HOP END, AND BOTH ANSWERS REPORT BACK.
#
# A rotation and a replacement on a hop end each push TWO nodes, and the operator has to
# know before they press it that a push reaching one of the two is a tunnel that is
# down. Each dialog used to say that in its own prose and each answer said it again in
# more prose, four wordings of one fact in three files — and three times the dialog
# ended up stating the opposite of the answer it produced. A test held them together by
# looking for a phrase in both, which a fourth wording carrying that phrase walked
# straight through.
#
# So it is ONE STRING. The dialogs render ``HOP_PUSH_OUTCOME``; ``_unpushed`` composes
# its answers out of the same two clauses, which are what makes the pair checkable
# rather than merely similar. A divergent wording is not something that can exist here.
#
# Neither clause names material or parameters: one sentence has to be true of a
# rotation, which re-mints, and of a replacement, which does not.
HOP_ONE_END_TOOK_IT = "the tunnel is down until you apply the other"
HOP_NEITHER_END_TOOK_IT = (
    "both are still running what they had and the tunnel is unaffected"
)
HOP_PUSH_OUTCOME = (
    f"Both nodes are pushed: if only one of the two takes it, {HOP_ONE_END_TOOK_IT}; "
    f"if neither does, {HOP_NEITHER_END_TOOK_IT}. This screen says which."
)

# The one sentence a refusal may carry in place of a message it will not print, and it
# carries no value. A transport's own complaint can quote what it rejected, and what is
# validated on these paths includes the material the node holds — so a complaint this
# answer has nowhere safe to print is NAMED and the rule is printed instead. Written to
# cover everything that is not a box rather than key material alone: the guard that
# named only material closed two instances and left the class open, which is this
# milestone's recurring shape. See ``ParamsRefused`` and ``_refused_parameters``.
#
# PHRASED ABOUT WHAT WAS WITHHELD, NOT ABOUT A FORM, because both of its callers are not
# the same surface: on the rotation path this is a BANNER with no form on screen at all,
# and on the replacement path it also covers a box that DOES exist whose message came
# back empty. The earlier wording ("the transport also refused something this form has
# no box for") was untrue of both, and its "also" announced a companion message that a
# banner never has.
KEY_MATERIAL_WITHHELD = (
    "the transport's own message is withheld for: {names}. A refusal can quote the "
    "value it rejected, and what is checked here includes material this panel never "
    "displays."
)

# What a refusal with no field to its name is called. A model-level validator reports
# an empty location, which is a complaint about the mapping rather than about any one
# parameter; printing nothing there would leave the operator with a sentence that names
# no subject, and printing the raw empty string reads as a rendering fault.
KEY_UNNAMED_REFUSAL = "the parameters as a whole"


@dataclasses.dataclass(frozen=True, slots=True)
class Stat:
    """One card on the Overview: a kicker, a number, and a line of context."""

    kicker: str
    value: int
    meta: str


def placed_as(transport_name: str, config_name: str) -> str:
    """What to call one transport ON one node, given a node may run two of them — M15.

    The transport's own name while that is the whole truth, which it is for every row
    written before M15 and for every first instance since — so nothing already on a
    screen changes appearance. A second instance is qualified by the name it is placed
    under, because that name is the config file on the host and, for the wg-quick family,
    the network interface: it is the answer to "which of these two am I looking at", and
    it is the same answer ``/api`` gives as ``config_name``.

    Here rather than in a template, like every other sentence this screen shows: a
    template that composed this would be a second definition of it, and the three screens
    that list a node's transports would eventually disagree.
    """
    if config_name == transport_name:
        return transport_name
    return f"{transport_name} ({config_name})"


@dataclasses.dataclass(frozen=True, slots=True)
class TransportChip:
    """One transport enabled on a node, as the Nodes screen tags it.

    ``name`` is whatever the transport declared about itself, qualified by ``placed_as``
    when this node runs more than one of it — the console compares it to nothing, and the
    template that renders these prints it without ever naming one.
    ``offered`` is the operator's own answer to "is this in a subscription", and
    ``for_friends`` distinguishes a friend-facing transport from one end of a hop, so a
    tunnel between two of our own nodes cannot be misread as something a person is
    being offered.
    """

    name: str
    offered: bool
    for_friends: bool


@dataclasses.dataclass(frozen=True, slots=True)
class NodeRow:
    """A node as the console lists it."""

    id: str
    name: str
    location_label: str
    address: str
    state: str
    state_detail: str | None
    # Decision 6's replacement for the design's "load" column. A node's load is a
    # measurement of the people on it; this is a measurement of US — whether what the
    # node was last given still matches what we would give it now.
    drift: str
    # What this node runs. A configuration fact and nothing else: it moves when the
    # OPERATOR enables or withdraws a protocol and never when a friend connects, which
    # is the test docs/decisions.md sets for whether a cell may be on a screen at all.
    transports: tuple[TransportChip, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class FriendRow:
    """A friend as the console lists them. The visible label is "user" — decision 9."""

    id: str
    nickname: str
    is_active: bool
    added: datetime.datetime
    nodes_served: int
    nodes_serving: int


@dataclasses.dataclass(frozen=True, slots=True)
class HopRow:
    """One entry→leaf hop as the console lists it.

    ``id`` is the ENTRY end's node-transport id, which is what both the API and
    ``relay.dissolve_hop`` address a hop by — the leaf end is reached through it, so a
    row carries one id and not two.

    ``leaf_node`` is ``None`` for half a hop, which is a state the operator has to be
    able to see: the foreign key between the two ends is SET NULL rather than CASCADE
    precisely so that removing one end leaves the other visible instead of silently
    disappearing with it.

    Nothing here moves when a friend connects. A hop's state moves when the operator
    establishes it, applies it or tears it down, which is the test docs/decisions.md
    sets for whether a cell may be on a screen at all.
    """

    id: str
    entry_node: str
    leaf_node: str | None
    transport: str
    state: str
    since: datetime.datetime | None


@dataclasses.dataclass(frozen=True, slots=True)
class TransportRow:
    """One installed transport, as the read-only capability table lists it.

    Every field is the transport's OWN declaration, turned into the words an operator
    reads. Nothing on this row is a fact about the fleet and nothing on it is a fact
    about a person: it moves when the image ships a different set of packages and at no
    other time — which is the test ``docs/decisions.md`` sets for whether a cell may be
    on a screen at all, passed the easy way.

    ``why`` is the one that matters. It is present exactly when the transport declares
    itself identified on the wire, and it is the sentence M9's acceptance line demands:
    a protocol the panel refuses to offer as an exit, with the reason in words. It is
    ``None`` for every other transport, so the screen warns about what the image
    declares rather than about what anybody wrote down.

    What is deliberately NOT here, because no transport declares it: whether a protocol
    has been proven on real hardware, and whether the image this project pins can carry
    it to a user without failing silently. Both are recorded in prose (see
    ``docs/decisions.md``, 2026-09-09) and neither is machine-readable, so putting
    either on the screen would mean `control` recognising a protocol by name.
    """

    name: str
    family: str
    # The transport's declared listening range as ``low–high``. Read from
    # ``TransportMeta.port_range``: a port written here would be a node we could not
    # rotate away from (CLAUDE.md), and a port written in the template would be one no
    # zone invariant reads.
    ports: str
    # Which subscription shapes this transport serialises into, and — separately —
    # whether this panel can actually hand any of them over yet. The two are kept apart
    # because they are different answers: a transport can serialise a shape that
    # delivery does not carry, and a column that collapsed them would tell the operator
    # a user has something they have never been sent.
    delivery: str
    delivery_note: str | None
    # ``blocked_by_inspection``, in words and as the flag the screen reads to decide how
    # loud to be.
    exposure: str
    identified: bool
    # ``hop_capable``, but only when it is False: a transport that may carry a hop needs
    # no sentence about it, and a column that says "may carry a hop" on three rows out
    # of four teaches nothing.
    hop_note: str | None
    # ``peer_address``, and only when it is declared — M17.2. Present on the transports
    # that hand each user an address out of a pool, absent on the ones that identify a
    # user by their material, for the same reason ``hop_note`` is one-sided: the row
    # that needs a sentence is the one with a consequence for the operator, which here
    # is a number they will be asked for on every node they enable it on.
    address_note: str | None
    why: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class KeyRow:
    """The material one transport holds on one node, as the Keys screen lists it.

    ``id`` is the node-transport's own id, which is what every rotation route addresses.

    ``fingerprint`` is a short one-way name for what the node holds, or ``None`` when
    the transport declares no published half — in which case ``held`` carries the rule
    instead. Nothing else on this row is derived from key material at all: not the
    scope, not the date, not the count. See ``keymaterial.fingerprint`` for what may be
    fed into that function and what may never be.

    ``pushed`` is when a configuration carrying this material last reached the host.
    It is deliberately the row's own ``applied_at`` and not a comparison against a fresh
    render: whether a node is running what we would give it NOW is the Nodes screen's
    ``config`` cell (``drift_of``), and two screens answering that question in two ways
    is how an operator ends up trusting the wrong one.

    ``holders`` counts credentials WE minted on this transport — the blast radius of
    rotating it, since every one of them is re-minted with the node's own material. It
    passes the test ``docs/decisions.md`` sets: it moves when the operator adds or
    revokes a user, and not when anybody connects.

    ``holders_of_pool`` is that same count as the screen reads it — "2 of 10" where the
    transport hands every user an address from a pool, and the bare count where it hands
    out none. Two numbers and no address: how full a pool is, is the one thing about the
    allocation an operator has to see, and WHO HOLDS WHAT is the record this project
    does not produce. Composed here rather than in the template for the reason every
    other sentence on this screen is — and because the pool's size is a column the
    template has no business knowing about.
    """

    id: str
    node: str
    transport: str
    scope: str
    fingerprint: str | None
    held: str | None
    pushed: datetime.datetime | None
    holders: int
    holders_of_pool: str
    for_friends: bool
    # Whether rotating THIS row also re-keys the far end of the hop, because the
    # transport declared material both ends must hold the same copy of. It used to mean
    # that rotating BROKE that value at the far end; the rotation now carries it across
    # in the same transaction, so what the flag selects is a cost to state
    # (``KEY_SHARED_WITH_PEER``) rather than a consequence to warn about. Read from the
    # transport's own ``shared_between_peers`` declaration and only meaningful on a hop
    # end, which is where both halves of this flag come from.
    shared_with_peer: bool
    # Whether this image still ships the transport this row runs. False means the
    # material cannot be fingerprinted, re-minted or validated here — so the screen
    # offers neither action rather than offering one that is certain to be refused.
    installed: bool
    # Whether the transport declares anything an operator may retype. A transport whose
    # every parameter is minted has nothing for the replace form to hold.
    replaceable: bool


# What one transport on one node is doing for the people this fleet exists for, as the
# words the Nodes screen's own actions are read beside. Every one of them is composed
# from two facts about OUR configuration — the row's purpose and its ``enabled`` flag —
# and never from which protocol it is, which is the same rule the chips on the table
# follow.
#
# The withdrawn sentence carries the thing ``nodes.set_transport_enabled`` insists on
# and that a panel is most likely to blur: switching a transport off changes what the
# control plane DELIVERS, not what the host is running. An operator who reads
# "withdrawn" as "stopped" has been told the opposite of what happened.
OFFER_IN_EVERY_LINK = "offered — in every user's link at their next refresh"
OFFER_WITHDRAWN = (
    "withdrawn — out of every user's link. The node is still configured to serve it "
    "until you re-apply it."
)
OFFER_HOP_END = (
    "one end of a hop — not something a user is offered. Tear the hop down from the "
    "Hops screen; switching one end off would leave a tunnel that no longer completes "
    "while both ends still look configured."
)

# Why a withdrawn row's offer button is not drawn at all — M17.2. Offering a transport
# hands every active user a credential on it IN THE SAME TRANSACTION (M17 moved the
# fan-out inside it), and on a transport that gives each of them an address of their own
# a pool this small refuses the whole thing. That refusal is correct and arrives with
# nothing committed; what it cannot be is the operator's first hint, because they have
# already told thirty people the protocol is coming.
#
# The pool is NAMED — node, transport and both counts, in ``addresses.named``'s words, so
# the sentence here and the refusal the API returns describe the same pool the same way.
# It also names the one screen that can fix it: there is no resize action in this console,
# the size is a box on the replace-parameters dialog, and an operator who does not know
# that has nowhere to go from here.
POOL_SHORT_TO_OFFER = (
    "not offered — {pools}. Offering it gives every active user an address here in the "
    "same change, so it would be refused. Make the pool bigger first: Keys & configs, "
    "replace params."
)

# The same row, answering the other action — M15.2. Its own sentence rather than the one
# above, because what the operator asked for is different and so is the reason it cannot
# be done here: withdrawing one end would stop a handshake, removing one end would leave
# a node holding a tunnel to an exit that is gone. Both name the screen that does the
# whole job, so neither is a dead end.
#
# Reachable only by a typed URL — the dialog draws no remove button on a hop end — which
# is why it is a banner's worth of words and not a tooltip.
REMOVE_HOP_END = (
    "one end of a hop — not something a user is offered, and not something to remove on "
    "its own. Tear the hop down from the Hops screen: that takes both ends, where "
    "removing this one would leave the other holding a tunnel to an exit that is no "
    "longer configured."
)

# What each state a node may be moved into MEANS, in the one place that decides it.
# Keyed on this project's own topology enum rather than on prose in a template, so the
# dialog offering a transition and the sentence explaining it cannot drift — and so a
# fifth state is one line here rather than a template nobody remembers to edit.
#
# Every one of these is a fact about DELIVERY: which link a state puts this node into
# and which it takes it out of. That is what the operator is actually choosing between,
# and it is what ``NodeState`` itself documents at each member.
NODE_STATE_MEANS = {
    NodeState.ACTIVE: (
        "serving — in every user's link at their next refresh, on whatever this node "
        "has enabled and applied"
    ),
    NodeState.DRAFT: (
        "out of every user's link, with its configuration kept — how a node is taken "
        "out of rotation without being retired"
    ),
    NodeState.DEGRADED: (
        "out of every user's link until you put it back, so nobody is routed onto a "
        "half-configured node"
    ),
    NodeState.RETIRED: (
        "final. The record is kept so its address is not quietly reused, and a retired "
        "node cannot be brought back — you register its replacement instead"
    ),
}

# Why the serving state is listed and not offered — M17.2, and the same event as
# ``POOL_SHORT_TO_OFFER`` from the other side. A node that starts serving grants every
# active user a credential on each transport it offers, inside the transaction that moves
# it, so one short pool on the node refuses the move. The refusal itself is M17's and is
# already tested; what this adds is that the operator reads it before pressing, with the
# pool named rather than "this node cannot be granted".
POOL_SHORT_TO_SERVE = (
    "not offered — {pools}. A node that starts serving gives every active user an "
    "address on each transport it offers, so this move would be refused. Make the pool "
    "bigger first: Keys & configs, replace params."
)


@dataclasses.dataclass(frozen=True, slots=True)
class OfferRow:
    """One transport on one node, as the Nodes screen's own actions address it.

    ``id`` is the node-transport's own id, which is what the withdraw and offer routes
    address — the same id the Keys screen's rotations use, because it is the same row.

    ``offered`` is the operator's own answer to "is this in a subscription" and
    ``for_friends`` is whether it could ever be: a hop end's consumer is the far NODE,
    so it has no offer to withdraw and the screen says so rather than showing a button
    whose only outcome is a refusal.

    ``transport`` is qualified by ``placed_as`` where a node runs two instances of one
    transport, which M15 permits — without it the two are the same word twice on every
    screen that lists them.

    Nothing here moves when a user connects. Both flags move when the operator acts,
    which is the test ``docs/decisions.md`` sets for whether a cell may be on a screen.
    """

    id: str
    node: str
    transport: str
    offered: bool
    for_friends: bool
    # Which of the three sentences above this row is in, composed here so no template
    # chooses between them and no route writes one.
    standing: str
    # Why the offer button is not drawn at all — M17.2, and ``None`` on nearly every row.
    # An action the service would refuse is withheld rather than offered, with the pool
    # it is about named: see ``POOL_SHORT_TO_OFFER``.
    withheld: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class StateChoice:
    """One state this node may be moved into, and what that does to a user's link.

    ``withheld`` is why it is listed but not offered — M17.2. The state machine still
    allows the move; this control plane would refuse it, and the dialog says so instead
    of drawing a control whose only outcome is a refusal. It is kept in the list rather
    than dropped so the operator still reads where their node could go and what is in
    the way of it.
    """

    state: str
    means: str
    withheld: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Overview:
    stats: list[Stat]
    nodes: list[NodeRow]
    friends: list[FriendRow]


async def drift_of(session: AsyncSession, node: Node) -> str:
    """How far a node's applied configuration is from what we would push now.

    Decision 6, and it is a better cell than the "load" it replaces: it answers "is
    this node serving what I told it to", which M1 proved is the question that matters.

    NOT the same thing as the health probe's ``drifted``/``stale``, and the difference
    is worth keeping straight (see ``docs/tracker/M1/step-notes.md``):

    * this compares a fresh render against ``applied_digest`` — what WE last pushed.
      It needs no network, which is why it can sit on a screen that must paint
      instantly and must work with every node unreachable;
    * the probe compares against the file on the node (``drifted``) and against what
      the running container was started from (``stale``). Those need SSH and are the
      Nodes screen's business.

    So a node reading "in sync" here means "nobody has changed the intent since we
    pushed", not "the host is running it". Both questions are real; conflating them is
    how an operator concludes a node is fine.
    """
    try:
        rendered = await apply.render_for_node(session, node)
    except Exception:
        # A node whose configuration cannot be rendered at all — a transport this
        # image no longer ships, most likely. Reported rather than raised: one
        # un-renderable node must not blank the whole Overview.
        logger.warning("could not render node %s for the drift cell", node.id)
        return UNRENDERABLE

    # Keyed by ``config_name``, which is what ``render_for_node`` keys its answer by
    # since M15: a node running two instances of one transport has two digests, and
    # keying on the transport's name would have kept one of them and called the node
    # in sync on the strength of the other.
    applied = {
        row.config_name: row.applied_digest
        for row in node.transports
        if row.enabled
    }
    if not rendered:
        # A node with nothing switched on has nothing to be out of sync ABOUT, and
        # saying "in sync" here would read as a clean bill of health for a machine
        # serving nobody. Named for what it is instead.
        return NOTHING_ENABLED if not applied else NEVER_APPLIED

    behind = sum(
        1
        for name, config in rendered.items()
        if applied.get(name) != node_stack.digest_of(config)
    )
    if behind == len(rendered) and not any(applied.values()):
        return NEVER_APPLIED
    if behind == 0:
        return IN_SYNC
    return f"{behind} / {len(rendered)} drifted"


async def node_rows(session: AsyncSession) -> list[NodeRow]:
    """Every node, with its drift cell computed.

    One render per node per screen load, which is the cost of the drift cell being
    honest rather than cached. It is bounded by the size of the fleet — this product
    is one owner and a handful of nodes — and it touches no network, so a fleet with
    every host unreachable paints exactly as fast as a healthy one. If a fleet ever
    grows past that, the answer is a stored digest of the last render, not a probe.
    """
    return [
        NodeRow(
            id=node.id,
            name=node.name,
            location_label=node.location_label,
            address=node.address,
            state=str(node.state),
            state_detail=node.state_detail,
            drift=await drift_of(session, node),
            transports=tuple(
                TransportChip(
                    name=placed_as(row.transport_name, row.config_name),
                    offered=row.enabled,
                    for_friends=row.purpose == TransportPurpose.FRIENDS,
                )
                # Sorted by name: this is a relationship load, and a column that
                # reshuffles itself between reloads reads as the fleet changing.
                for row in sorted(node.transports, key=lambda row: row.transport_name)
            ),
        )
        for node in await nodes.list_nodes(session)
    ]


async def friend_rows(session: AsyncSession) -> list[FriendRow]:
    """Every friend, with how much of the fleet they are covered on.

    ``nodes_serving`` is the denominator every active friend shares, so a row reading
    ``2 / 3`` says "this person is missing a node", which is an actionable fault in OUR
    configuration and the reason the column exists.
    """
    serving = await nodes.serving_transports(session)
    serving_ids = {row.id for row in serving}
    return [
        FriendRow(
            id=friend.id,
            nickname=friend.nickname,
            is_active=friend.is_active,
            added=friend.created_at,
            nodes_served=sum(
                1
                for credential in friend.credentials
                if credential.node_transport_id in serving_ids
            ),
            nodes_serving=len(serving_ids),
        )
        for friend in await friends.list_friends(session)
    ]


async def hop_rows(session: AsyncSession) -> list[HopRow]:
    """Every hop, in the words the Hops screen uses.

    ``established`` means both ends exist AND both have had a configuration applied —
    the same judgement the Overview's third stat card makes, and for the same reason:
    a pair that exists only in the database is a tunnel that has not been brought up,
    and calling it established is the panel telling the operator that traffic is
    flowing through something nothing has pushed.
    """
    rows = []
    for entry, leaf in await relay.list_hops(session):
        if leaf is None:
            state, since = HOP_INCOMPLETE, None
        elif entry.applied_at and leaf.applied_at:
            # The LATER of the two: a hop is only as applied as its least recently
            # applied end, and the earlier timestamp would date it from before the
            # tunnel could have come up.
            state, since = HOP_ESTABLISHED, max(entry.applied_at, leaf.applied_at)
        else:
            state, since = HOP_PENDING, None
        rows.append(
            HopRow(
                id=entry.id,
                entry_node=entry.node.name,
                leaf_node=leaf.node.name if leaf else None,
                transport=entry.transport_name,
                state=state,
                since=since,
            )
        )
    return rows


async def hop_row(session: AsyncSession, node_transport_id: str) -> HopRow:
    """One hop, projected exactly as the table projects it.

    Found in the list rather than fetched on its own so that the tear-down dialog and
    the row behind it cannot disagree about what the hop is called. The fleet is a
    handful of nodes, and the alternative — a second query with its own joins — is the
    shape that drifts.
    """
    for row in await hop_rows(session):
        if row.id == node_transport_id:
            return row
    raise NotFound("no such hop")


async def offers_on(session: AsyncSession, node_id: str) -> list[OfferRow]:
    """Every transport enabled on one node, with what each is doing for a user.

    The Nodes screen's own dialog is built from this, so what the row SAYS and which
    button it gets come from one projection rather than from a template working it out
    twice. Sorted by name for the reason the table's chips are: a list that reshuffles
    itself between reloads reads as the fleet changing.
    """
    node = await nodes.get_node(session, node_id)
    rows = await _transports_on(session, node)
    # Which of them could not be offered right now, measured once for the whole dialog —
    # M17.2. Keyed by the row's own id, which is what a ``Shortfall`` carries so that the
    # sentence lands on the line the operator is looking at.
    short = {
        row.row: row for row in await addresses.shortfalls_among(session, rows)
    }
    return [
        OfferRow(
            id=row.id,
            node=node.name,
            transport=placed_as(row.transport_name, row.config_name),
            offered=row.enabled,
            for_friends=row.purpose == TransportPurpose.FRIENDS,
            standing=_standing(row.purpose, row.enabled),
            # Only on a row that is WITHDRAWN, because offering is the action being
            # withheld: a row already in every link is one this pool has already been
            # measured for, and its button is the withdraw the operator may always press.
            withheld=(
                POOL_SHORT_TO_OFFER.format(pools=addresses.named(short[row.id]))
                if not row.enabled and row.id in short
                else None
            ),
        )
        for row in rows
    ]


async def _transports_on(session: AsyncSession, node: Node) -> list[NodeTransport]:
    """Every transport row on one node, in a stable order.

    QUERIED rather than read off ``node.transports``, and that is not a style choice:
    the callers are reached from routes that already loaded a node-transport, whose own
    ``node`` relationship hands back the same Node instance out of the identity map —
    with its ``transports`` collection never loaded, so touching it is lazy IO on an
    async session and raises ``MissingGreenlet`` at runtime rather than in a query. One
    select, ordered in SQL, works from either direction. (``key_rows`` reads the
    relationship safely because it comes from ``list_nodes``, which issues the query that
    populates it.)

    Sorted for the reason every other collection here is: an unordered list reshuffles
    itself between reloads and reads as the fleet changing.
    """
    result = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .order_by(NodeTransport.transport_name)
    )
    return list(result.scalars().unique())


async def offer_row(session: AsyncSession, node_transport_id: str) -> OfferRow:
    """One row, projected exactly as the list projects it.

    Found in its node's list rather than fetched on its own, for the reason ``key_row``
    and ``hop_row`` are: the confirmation dialog and the row behind it must not disagree
    about what they are addressing.
    """
    node_transport = await nodes.get_node_transport(session, node_transport_id)
    for row in await offers_on(session, node_transport.node_id):
        if row.id == node_transport_id:
            return row
    raise NotFound("no such transport on any node")


def _standing(purpose: TransportPurpose, enabled: bool) -> str:
    """Which of the three sentences this row is in.

    A branch on our own topology and on the operator's own flag — never on a protocol.
    A hop end is answered first because ``enabled`` means something different there: it
    says the tunnel should be running, not that anybody is being offered anything.
    """
    if purpose != TransportPurpose.FRIENDS:
        return OFFER_HOP_END
    return OFFER_IN_EVERY_LINK if enabled else OFFER_WITHDRAWN


async def state_choices(session: AsyncSession, node: Node) -> tuple[StateChoice, ...]:
    """The states this node may move to, each with what it does to a user's link.

    ``NodeState.allowed_from`` is the machine and this does not restate it — a dialog
    that offered a transition the service refuses would be a button whose only outcome
    is a 409, which is why the pre-redesign page read the same list before M9.6 deleted
    it, and why nothing may restate it here either. What is added is
    the sentence, from ``NODE_STATE_MEANS``, so the operator chooses between
    consequences rather than between four words.

    A state with no sentence yet comes back with an empty one rather than raising: this
    is a dialog, and a missing line of prose must not be a 500 on the screen the
    operator uses to fix things. ``test_every_state_a_node_may_move_to_says_what_it
    _means`` is what keeps that branch unreachable.

    ASYNC SINCE M17.2, and that is the whole reason the signature changed: a node
    becoming serving hands every active user an address on each transport it offers, so
    a short pool anywhere on this node refuses the move — inside the transaction, with
    nothing committed, but only after the operator has pressed. The measurement is
    ``addresses.shortfalls_among``, over this node's own ENABLED rows, which are exactly
    the ones that become serving with it. A node that is already serving is asked
    nothing: it grants nobody anything by staying where it is.
    """
    withheld = None
    if node.state not in NodeState.serving():
        short = await addresses.shortfalls_among(
            session, [row for row in await _transports_on(session, node) if row.enabled]
        )
        if short:
            withheld = POOL_SHORT_TO_SERVE.format(
                pools="; ".join(addresses.named(row) for row in short)
            )
    return tuple(
        StateChoice(
            state=str(state),
            means=NODE_STATE_MEANS.get(state, ""),
            withheld=withheld if state in NodeState.serving() else None,
        )
        for state in NodeState.allowed_from(node.state)
    )


def transport_rows() -> list[TransportRow]:
    """Every transport this image ships, as the capability table lists them.

    No session and no ``await``: this screen is a projection of the image, not of the
    fleet. ``discover()`` imports the packages under ``edge/transports/`` — a new
    protocol appears here on its own, and one that fails to import does not appear at
    all, which is the honest answer rather than a row that lies about being available.

    Sorted by name for the reason every other collection in this module is: an
    unordered list reshuffles itself between reloads and reads as the fleet changing.
    """
    return [
        _transport_row(meta)
        for meta in sorted(discover().values(), key=lambda meta: meta.name)
    ]


def _transport_row(meta: TransportMeta) -> TransportRow:
    """One transport's declaration, projected into the words the screen shows.

    This is the whole of M9.3's hard rule. Four of the strings below are chosen by
    something the TRANSPORT declares about itself, and none of them is chosen by which
    protocol it is — there is no name compared to anything here, in the template, or
    anywhere on the path between them. Ship a fifth protocol and its row writes itself;
    ship one that declares itself identified and the warning appears with no edit.

    The two conditions in ``delivery_note`` are not the same condition. A transport
    with no declared format serialises into nothing a user could consume at all; a
    transport with one this panel does not yet deliver serialises fine and is simply not
    handed over (``subscription_expressible``, and its own docstring in
    ``edge/registry.py``, say why). Reporting the second as the first would tell the
    operator a protocol is unusable when it is merely undelivered.
    """
    low, high = meta.port_range
    formats = sorted(str(shape) for shape in meta.subscription_formats)
    return TransportRow(
        name=meta.name,
        family=meta.family,
        ports=f"{low}–{high}",
        delivery=", ".join(formats) if formats else TRANSPORT_NO_DELIVERY,
        delivery_note=(
            None
            if not formats or meta.subscription_expressible
            else TRANSPORT_UNDELIVERED
        ),
        exposure=(
            TRANSPORT_IDENTIFIED
            if meta.blocked_by_inspection
            else TRANSPORT_CAMOUFLAGED
        ),
        identified=meta.blocked_by_inspection,
        hop_note=None if meta.hop_capable else TRANSPORT_NO_HOP,
        # THE REGISTRY'S OWN DECLARATION, asked through the one function in this zone
        # that asks it — no name is compared here, in the template, or anywhere between
        # them, which is the same rule the three strings above follow.
        address_note=(
            TRANSPORT_ADDRESS_PER_USER
            if addresses.spec_for(meta.name) is not None
            else None
        ),
        why=TRANSPORT_WHY_IDENTIFIED if meta.blocked_by_inspection else None,
    )


def _holders_of_pool(holders: int, pool: int | None) -> str:
    """"2 of 10" where there is a pool, and the bare count where there is not — M17.2.

    Two numbers, and neither of them is about a person: how many addresses this row has
    handed out and how many it may. That is the whole of what the console may know about
    an allocation — WHICH address is whose is the record the charter says is absent, so
    it is not on this screen, not behind a hover, and not in the dialog this row opens.

    The bare count for a transport that hands out no address at all, because "2 of None"
    would invent a limit that does not exist there: a VLESS row identifies each user by
    their own material and has no pool to be full.
    """
    return f"{holders} of {pool}" if pool is not None else str(holders)


async def key_rows(session: AsyncSession) -> list[KeyRow]:
    """Every transport enabled on every node, as the material each one holds.

    One query for the credential counts rather than one per row, and never through
    ``NodeTransport.credentials``: that relationship loads lazily, and lazy I/O on an
    async session raises at runtime rather than in a test.

    Nothing here decrypts anything. The row's ``secrets`` column is not read on this
    path at all — the fingerprint is computed from ``params``, which is the clear one —
    so the screen cannot show key material even by accident.
    """
    installed = discover()
    counted = dict(
        (
            await session.execute(
                select(Credential.node_transport_id, func.count(Credential.id)).group_by(
                    Credential.node_transport_id
                )
            )
        ).all()
    )

    rows = []
    for node in await nodes.list_nodes(session):
        # Sorted by name for the reason every other collection here is: an unordered
        # list reshuffles itself between reloads and reads as the fleet changing.
        for row in sorted(node.transports, key=lambda row: row.transport_name):
            meta = installed.get(row.transport_name)
            # ``params`` and never ``secrets``: the clear column is the only one this
            # screen reads, and the specs decide which of its values may be hashed.
            fingerprint = (
                keymaterial.fingerprint(meta.key_material, row.params) if meta else None
            )
            for_friends = row.purpose == TransportPurpose.FRIENDS
            rows.append(
                KeyRow(
                    id=row.id,
                    node=node.name,
                    transport=placed_as(row.transport_name, row.config_name),
                    scope=KEY_SCOPE_NODE if for_friends else KEY_SCOPE_HOP,
                    fingerprint=fingerprint,
                    # The rule, printed exactly where a value could otherwise have gone.
                    held=(
                        None
                        if fingerprint
                        else (KEY_HELD_NOT_SHOWN if meta else KEY_NOT_IN_THIS_IMAGE)
                    ),
                    pushed=row.applied_at,
                    holders=counted.get(row.id, 0),
                    # The pool from the row's own column, and whether there IS one from
                    # the transport's own declaration — never from its name. A row
                    # enabled before pools existed has no size and hands out exactly one
                    # address, which is what ``pool_of`` renders from, so it reads
                    # "1 of 1" rather than as though it had no pool at all.
                    holders_of_pool=_holders_of_pool(
                        counted.get(row.id, 0),
                        (row.pool_size or 1)
                        if addresses.spec_for(row.transport_name) is not None
                        else None,
                    ),
                    for_friends=for_friends,
                    shared_with_peer=bool(
                        meta
                        and not for_friends
                        and any(
                            spec.shared_between_peers and spec.scope is KeyScope.NODE
                            for spec in meta.key_material
                        )
                    ),
                    installed=meta is not None,
                    replaceable=bool(
                        meta and transports.operator_params(row.transport_name)
                    ),
                )
            )
    return rows


async def key_row(session: AsyncSession, node_transport_id: str) -> KeyRow:
    """One row, projected exactly as the table projects it.

    Found in the list rather than fetched on its own, for the reason ``hop_row`` is:
    the dialog and the row behind it must not disagree about what they are addressing.
    """
    for row in await key_rows(session):
        if row.id == node_transport_id:
            return row
    raise NotFound("no such transport on any node")


def rotation_summary(row: KeyRow, outcome: rotation.RotationOutcome) -> str:
    """What a key rotation means for the people holding a link, in one sentence.

    Its own sentence rather than ``RotationOutcome.summary()``, which enumerates the
    parameters it re-minted: a console that lists ``private_key`` beside a fingerprint
    invites the reader to look for the value. What changed is visible as the fingerprint
    on the row behind this message; what the operator needs in words is what it costs the
    people on that node. (That summary also used to end "retry from the node's page",
    naming a page M9.6 deleted. It now ends at ``apply.WHERE_TO_RETRY``, the same
    constant ``_unpushed`` below uses, so the envelope and the console cannot drift about
    where an operator finishes a push.)

    A HOP END COSTS NOBODY A LINK, and now says so. Every other string on this screen
    branches on ``for_friends``, including the confirmation the operator just read —
    *"No user holds anything on it: this is a tunnel between two of our own nodes"* — so
    an answer that then reports what users will pick up contradicts the sentence they
    confirmed. The far end is named instead, because that is the only holder a hop end
    has.

    WHAT IT SAYS ABOUT THE FAR END CHANGED WITH THE ROTATION ITSELF. It used to say the
    far end was still holding the material it was given — true then, and the whole
    defect: the two ends no longer matched. A rotation now writes both ends in one
    transaction and pushes both nodes, so on a complete one they match and both have
    taken it, and telling the operator to do something about the far end would be
    telling them to fix what is not broken. When the push did NOT land everywhere,
    ``_unpushed`` says which node has to be applied and what is true until it is.
    """
    if not outcome.complete:
        return _unpushed(row, outcome, "its keys were re-minted here")
    if not row.for_friends:
        return (
            f"keys rotated on {row.node} — {row.transport} and at the far end of the "
            "hop; no user holds anything on it, and both nodes have taken the new "
            "material"
        )
    return (
        f"keys rotated on {row.node} — {row.transport}; users keep the same link and "
        "pick this up the next time their client refreshes it"
    )


def replacement_summary(row: KeyRow, outcome: rotation.RotationOutcome) -> str:
    """What was replaced, named, and what happens to the people on it.

    The field names ARE listed here, unlike a key rotation's: these are values the
    operator typed themselves, so naming them back is how they confirm the right box
    landed. Nothing minted can be in this list — the form has no box for one.

    Branched on ``for_friends`` for the reason ``rotation_summary`` above is: a hop end
    has no user on it to be told about, and the dialog behind this answer says so.
    """
    changed = ", ".join(outcome.rotated)
    if not outcome.complete:
        return _unpushed(row, outcome, f"{changed} replaced here")
    if not row.for_friends:
        return (
            f"replaced {changed} on {row.node} — {row.transport}, at this end of the "
            "hop; no user holds anything on it, and the far end has been applied with "
            "it so the two still match"
        )
    return (
        f"replaced {changed} on {row.node} — {row.transport}; users keep the same link "
        "and pick this up the next time their client refreshes it"
    )


def _unpushed(row: KeyRow, outcome: rotation.RotationOutcome, what: str) -> str:
    """The half-done state, which is why these two are banners and not toasts.

    Between the write and a successful push the database and the nodes disagree, and for
    a decoy rotation that means the blocked value is still what the node is serving.
    Written in the present tense, naming what is still TRUE rather than reporting that
    a request failed — an operator who reads "failed" and walks away has been told the
    opposite of what happened.

    Whose problem it is NOT differs by row, and on a hop it differs by HOW MUCH landed,
    which is the fail-safe an operator has to be able to read: a hop rotation writes
    both ends and pushes two nodes, so one node taking it and the other not is a tunnel
    that is down, while neither taking it is a tunnel that is untouched. Reporting both
    as "the node is still running the old material" would be right about one of them and
    a false reassurance about the other. A friend-facing row has one node and people on
    the old material, who are unaffected.

    THE TWO HOP CLAUSES ARE NOT WRITTEN HERE. They are ``HOP_ONE_END_TOOK_IT`` and
    ``HOP_NEITHER_END_TOOK_IT``, and the same two make up ``HOP_PUSH_OUTCOME``, which is
    what both confirmation dialogs render. That is the whole point of them being
    constants: the dialog states the two outcomes as possibilities and this states one
    of them as fact, in the same words, so the pair cannot drift into contradicting each
    other again.
    """
    if row.for_friends:
        standing = (
            "the node is still running the old material and users on it are unaffected"
        )
    elif outcome.nodes_updated:
        standing = (
            f"one end of the hop has taken it and the other has not, so "
            f"{HOP_ONE_END_TOOK_IT} — no user holds anything on it either way"
        )
    else:
        standing = (
            f"neither end took it, so {HOP_NEITHER_END_TOOK_IT} — no user holds "
            "anything on it either way"
        )
    unreached = sorted(outcome.nodes_failed)
    many = len(unreached) > 1
    return (
        f"{row.node} — {row.transport}: {what}, but "
        f"{'these nodes' if many else 'the node'} could not be updated: "
        f"{rotation.reasons(outcome.nodes_failed)}. "
        f"Until {'they are' if many else 'it is'}, {standing}. Apply "
        f"{'them' if many else 'it'} again from {apply.WHERE_TO_RETRY} once "
        f"{'they can' if many else 'it can'} be reached."
    )


def withheld_note(names: list[str]) -> str:
    """UI-PATTERNS §9 wherever a refusal could otherwise have printed a value.

    A name with no field in it — Pydantic's empty location, which a model-level
    validator produces — is given the words for what it actually is. Names are sorted so
    two refusals about the same parameters read identically.
    """
    return KEY_MATERIAL_WITHHELD.format(
        names=", ".join(sorted(name or KEY_UNNAMED_REFUSAL for name in names))
    )


def withdrawal_summary(node: str, transport: str) -> str:
    """What withdrawing a transport does, and — as loudly — what it does not do.

    Here rather than in the route for the reason ``tear_down_summary`` is: this is a
    judgement about what is still true of the fleet, and routes in this codebase do
    wiring. The second sentence is ``nodes.set_transport_enabled``'s own warning made
    operator-facing: disabling changes what the control plane DELIVERS, not what the
    host is running. A person who already holds a fetched configuration keeps
    connecting until the node is applied without them, and an operator who reads
    "withdrawn" as "stopped" has been told the opposite of what happened.
    """
    return (
        f"{transport} withdrawn on {node} — out of every user's link at their next "
        "refresh. The node is still configured to serve it: apply it to stop that."
    )


def removal_summary(node: str, transport: str) -> str:
    """What removing a transport took with it, and what it did not — M15.2.

    Beside ``withdrawal_summary`` and deliberately not a louder version of it: the two
    actions differ in what survives them. A withdrawal leaves every credential minted and
    the row holding its port; a removal destroys the material and frees the port and the
    config name for something else on this node. Saying so here is what stops the
    operator reading the two toasts as the same event with different words.

    The half they share is the half both are most likely to be read wrongly: the host is
    still running it. The row is gone from every screen in this panel and the daemon on
    the node is not, until the node is applied — which is why the sentence ends on the
    one action that is still owed.
    """
    return (
        f"{transport} removed from {node} — out of every user's link at their next "
        "refresh, and the material minted for it is gone with it. Its listening port "
        "and its config name on this node are free again. The node is still configured "
        "to serve it: apply it to stop that."
    )


def offer_summary(node: str, transport: str) -> str:
    """What offering a transport again costs the people on it: nothing.

    The other half of criterion 3, and the half that has to say "nobody does anything":
    every active user is granted material on it here, and their link does not move.
    """
    return (
        f"{transport} offered again on {node} — in every user's link at their next "
        "refresh, and nobody re-imports anything."
    )


def tear_down_summary(affected: list[str]) -> str:
    """What tearing a hop down leaves the operator to do, as one sentence.

    Here rather than in the route for the same reason as ``health_summary``: prose
    composed from a count is a judgement about the fleet, and routes in this codebase
    do wiring. The count is nodes that still hold a tunnel to an exit that is now gone
    — one of them when the hop was already half missing.
    """
    count = len(affected)
    noun = "node" if count == 1 else "nodes"
    verb = "it stops" if count == 1 else "they stop"
    return (
        f"hop torn down — re-apply {count} {noun} so {verb} holding a tunnel to an "
        "exit that is no longer configured"
    )


async def overview(session: AsyncSession) -> Overview:
    """The Overview screen's whole content, in one call.

    The four stat cards are decision 6's replacements, in the design's own order:
    nodes online, active users, hops established, transports enabled. Each is a fact
    about the FLEET. How many friends exist is not a record of what any of them did.
    """
    rows = await node_rows(session)
    people = await friend_rows(session)
    hops = await relay.list_hops(session)

    online = [row for row in rows if row.state == NodeState.ACTIVE]
    active = [row for row in people if row.is_active]
    # A hop is established once both ends exist AND both have had a config applied.
    # A pair that exists only in the database is still pending — the tunnel does not
    # come up until the nodes are applied, and saying "established" before that is
    # the panel telling the operator a tunnel is up when nothing has been pushed.
    established = [
        (entry, leaf)
        for entry, leaf in hops
        if leaf is not None and entry.applied_at and leaf.applied_at
    ]
    offered = {
        row.transport_name
        for row in await nodes.serving_transports(session)
        if row.purpose == TransportPurpose.FRIENDS
    }
    installed = discover()

    return Overview(
        stats=[
            Stat(
                kicker="nodes online",
                value=len(online),
                meta=_plural(len(rows), "node", "in the fleet"),
            ),
            Stat(
                kicker="active users",
                value=len(active),
                meta=(
                    f"{len(people) - len(active)} revoked"
                    if len(people) != len(active)
                    else "nobody revoked"
                ),
            ),
            Stat(
                kicker="hops established",
                value=len(established),
                meta=(
                    f"{len(hops) - len(established)} awaiting apply"
                    if len(hops) != len(established)
                    else _plural(len(hops), "hop", "configured")
                ),
            ),
            Stat(
                kicker="transports enabled",
                value=len(offered),
                meta=f"of {len(installed)} this image ships",
            ),
        ],
        nodes=rows,
        friends=people,
    )


def health_summary(name: str, health: schemas.HealthResponse) -> str:
    """One node's probe result as a sentence the console can put on screen.

    Composed here rather than in the route because it is the same judgement the
    pre-redesign panel's ``panel/health.html`` made in markup, and the console needs it
    as TEXT: a probe answers into a toast when the node is fine and into a persistent
    banner when it is not, and neither carries a template. That fragment went with the
    page in M9.6; this function is what carried its reading across.

    Note what it cannot say, because the value does not exist upstream: no client
    count, no address, no traffic figure. Health means "is this node serving what we
    told it to", and the charter's no-logging rule covers this screen like every other.

    ``drifted`` and ``stale`` get their own sentences and are not collapsed into one:
    they are different faults with different repairs, and M1 found a node in the field
    reporting no drift while its daemon had never read the file it was reporting about.
    """
    if health.healthy:
        running = ", ".join(health.running)
        return (
            f"{name} is serving {running}"
            if running
            else f"{name} answered, and has no transport enabled to serve"
        )

    reason = health.detail or "no reason was reported"
    if not health.reachable:
        return f"{name} could not be reached — {reason}"

    parts = [f"{name} answered but is not serving — {reason}."]
    if health.drifted:
        parts.append(
            "Its configuration differs from the one we would push; applying again "
            "replaces it."
        )
    if health.stale:
        parts.append(
            "Something is running on a configuration older than the file on the node "
            "— the file was replaced but the daemon was never restarted onto it. "
            "Anyone revoked while it was in this state is still being served. Applying "
            "again recreates the container."
        )
    return " ".join(parts)


def _plural(count: int, noun: str, tail: str) -> str:
    """"1 node in the fleet" / "3 nodes in the fleet"."""
    return f"{count} {noun}{'' if count == 1 else 's'} {tail}"


async def subscription_url(
    session: AsyncSession, base_url: str, friend: Friend
) -> str | None:
    """The one URL a friend holds, or ``None`` if they have no live subscription.

    Built here rather than in a route so there is a single place that composes a
    bearer credential into a string. Every caller of this function is displaying it
    inside a dialog and nowhere else: it must not reach a query string, a log line,
    an error message or a ``title`` attribute (CLAUDE.md).

    Queried rather than read off ``friend.subscriptions``, and that is not a style
    choice. The add-user flow calls this with a friend created moments ago in the same
    transaction, whose relationship has never been LOADED — so touching the collection
    triggers lazy I/O, which in async SQLAlchemy is not a slow query but an immediate
    MissingGreenlet crash. The same trap is documented in services/friends.py.
    """
    result = await session.execute(
        select(Subscription).where(Subscription.friend_id == friend.id)
    )
    live = [row for row in result.scalars().unique() if row.is_active]
    return f"{base_url}/sub/{live[0].token}" if live else None


# --- Settings (M10.2) ---------------------------------------------------------
#
# What the Settings screen says, in one place, for the same reason every other
# sentence on every other screen is here: a template choosing between them would be
# a template deciding what this control plane is running with.
#
# The screen is a STATEMENT and not a form (docs/decisions.md, 2026-09-11). Every
# value below is read off the live ``Settings`` object this process was built with —
# never the environment, never a file — which is what makes it true of the control
# plane the operator is signed into rather than of an env file that may have been
# edited since boot. It is also what keeps it honest by construction: a variable this
# process does not read has no attribute to render, so it would first have to be
# declared in ``control/app/settings.py``, which is the same act as making the process
# actually read it.

# What a secret is shown as, and the only form it may ever take on this screen. Not
# redacted, not a prefix, not a length, not a digest: ``settings.py`` goes out of its
# way not to disclose the operator hash — ``OperatorHashMalformed`` exists so pydantic
# cannot put it into a ``ValidationError`` on every failed boot — and one cell
# rendering eight characters of it would undo that. A length or a digest is not a
# compromise, only a smaller offline target.
SETTING_CONFIGURED = "configured"

# The one line the milestone's "done when" asks for: where a value is changed, when
# the panel cannot change it. Phrased about the ENVIRONMENT this process was started
# with rather than about a particular file, because how the container is started is
# not something this code knows.
SETTINGS_READ_AT_BOOT = (
    "Nothing here can be edited, and nothing on this screen is stored in the "
    "database. Each value is read from the environment variable beside it when this "
    "control plane starts, so a change means setting that variable in the environment "
    "this process is actually handed — and a value still at its default is usually one "
    "nothing passes in yet, so it has to be added there rather than edited somewhere "
    "the process never reads. Then restart this control plane; until it restarts, what "
    "is printed here is what the running process is using."
)

# The footnote under the table, stating the rule the screen keeps in every secret cell
# — the same shape as the Keys & configs lead paragraph, and for the same reason:
# where a value may never appear, the panel prints the rule instead.
SETTINGS_SECRETS_WITHHELD = (
    "A secret reads “configured” and never anything else — not its first characters, "
    "not how long it is, not a digest of it. This panel will tell you that the process "
    "has one; it cannot show you any part of one, and there is nowhere on this screen "
    "to type one in."
)

# The single Admins row. It is not a table waiting for a second row: “one operator,
# one fleet” is the charter's non-goal of multi-tenancy, so there is no add-admin
# control here and there is not going to be one.
OPERATOR_ROLE = "operator"
ONE_OPERATOR = (
    "One operator, one fleet. There is no second account and no control here to add "
    "one — this row is not a database table, it is the variable named beside it and "
    "the password hash in the table above, so the panel can no more add an operator "
    "than it can rename this one."
)

# Where the password itself is set. Named because the hash is the one value on this
# screen an operator regularly has to replace, and “edit HASHI_OPERATOR_PASSWORD_HASH”
# is not actionable on its own: the hash has to be generated, and generating it by
# hand is how a panel ends up with a hash nobody can match.
OPERATOR_PASSWORD_CHANGED_WITH = (
    "The password itself is never stored and never shown. To change it: generate a "
    "new hash with python -m control.cli hash-password, put that line in this "
    "variable, and restart."
)


@dataclasses.dataclass(frozen=True, slots=True)
class SettingRow:
    """One thing this control plane is configured with, as the screen states it.

    ``value`` is either what the process holds or — for a secret — the single word
    ``SETTING_CONFIGURED``. There is deliberately no third possibility and no field
    carrying a redacted form: a row that could hold a masked value is a row a later
    edit unmasks.

    ``variables`` is every ``HASHI_*`` name the value is read from, which is usually
    one and is two for the subscription base URL — it is composed from a host and a
    scheme flag, and naming only one of them would send the operator to edit the
    variable that is not the reason the URL reads the way it does.
    """

    label: str
    value: str
    variables: tuple[str, ...]
    # A second, muted line under the label: what the value does, or what changing it
    # costs. ``None`` where the label is already the whole story.
    note: str | None = None
    # Whether ``value`` is the withheld word. The template reads this to decide how
    # loud the cell is; the TEST reads it to decide which cells must equal that word,
    # which is what makes "a secret is shown one way" mechanical rather than watched.
    secret: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class AdminRow:
    """The one account that can sign into this panel.

    The design drew user / role / last login. There is no ``last_login`` column here
    and there is not going to be one: it is a per-person temporal record, the person
    being the owner, on the machine the charter calls most worth seizing — and it is
    dropped rather than rendered blank, for the reason decision 6 dropped the Traffic
    screen. A cell that exists to say "we do not keep this" is where somebody later
    keeps it. ``docs/decisions.md`` (2026-09-11) has the full argument.
    """

    username: str
    role: str
    variables: tuple[str, ...]


def _seconds(value: int) -> str:
    """A ceiling in the unit it is configured in, with the human reading beside it.

    The variable holds seconds, so seconds is what the screen prints — an operator
    editing ``HASHI_SESSION_MAX_AGE`` types a number of them, and a cell reading only
    "8 hours" would be a cell they cannot copy. The parenthetical is DERIVED and
    appears only when the division is exact: "480 minutes" beside 28800 is help, and
    "0.08 hours" beside 300 would be noise.
    """
    spelled = _plural(value, "second", "").strip()
    for size, noun in ((3600, "hour"), (60, "minute")):
        if value >= size and value % size == 0:
            return f"{spelled} ({_plural(value // size, noun, '').strip()})"
    return spelled


# How a frequency is said: the unit, the article that goes in front of it when there is
# exactly one, and the unit's own size. The ARTICLE is in the table rather than in the
# sentence below, and that is the whole reason this is a table: hardcoding "an" made
# a one-minute sweep read "once an minute", and sixty seconds is the most likely value
# anybody moves this to.
_FREQUENCIES = ((3600, "an", "hour"), (60, "a", "minute"), (1, "a", "second"))


def _how_often(seconds: int) -> str:
    """"once an hour" / "every 20 minutes" — the sweep's real interval, in words.

    Derived rather than written, the same rule ``_seconds`` follows above: the screen
    tells the operator how often their trail is swept, and a sentence that repeated the
    number would go false the day ``audit.SWEEP_INTERVAL_SECONDS`` moved, with nothing
    going red. This one is prose rather than a value cell, so it reads as a frequency.

    The largest unit the interval divides exactly, which is what makes 3600 read as an
    hour and 3601 fall all the way to seconds — an interval that is not a round number
    of minutes is better stated awkwardly than rounded, since the screen is telling the
    operator how long a deleted entry can still be on disk.
    """
    for size, article, noun in _FREQUENCIES:
        if seconds >= size and seconds % size == 0:
            count = seconds // size
            return f"once {article} {noun}" if count == 1 else f"every {count} {noun}s"
    # Only reachable for a non-positive interval, which is not a frequency at all. It
    # cannot come from an operator — this is a constant in this repository, not a
    # setting — so the honest answer is to print the number rather than invent a word
    # for it, and the sweeper would be spinning either way.
    return f"every {seconds} seconds"


def settings_rows(settings: Settings) -> list[SettingRow]:
    """Everything the Settings screen states, read off the live configuration object.

    ``settings`` is the object the application was built with
    (``request.app.state.settings``), not a fresh read of anything. That is the whole
    guarantee the screen rests on: what is printed is what this process is using, so a
    value cannot go stale between boot and now, and an env file edited since boot
    cannot make the screen lie about the running service.

    No row is a form field and none of them is written anywhere. The design's Panel
    form — mesh name, subscription base URL, log retention days — is dropped whole:
    nothing in this process reads a mesh name, and a control that saved the base URL
    would be saving a value the process only reads at boot, which is the lie M10's
    prose is written about. The retention row is the one value from that form which
    survived, and only because M10.3 built the trail it bounds and the hourly sweep
    that enforces it — a retention figure with no sweep behind it would be the same
    lie in a different field. It is still a statement and not a field.
    """
    return [
        SettingRow(
            label="subscription base URL",
            value=settings.public_base_url,
            variables=("HASHI_PUBLIC_HOST", "HASHI_PUBLIC_HTTPS"),
            note=(
                "Every subscription URL this panel hands out is built on it. Change it "
                "and the links already handed out still point at the old one, so a user "
                "whose link stops resolving has to be given the new one."
            ),
        ),
        SettingRow(
            label="how long a panel session lasts",
            value=_seconds(settings.session_max_age),
            variables=("HASHI_SESSION_MAX_AGE",),
            note=(
                "How long this sign-in stays valid. There is deliberately no "
                "“remember me”: a forgotten tab should stop being a way in."
            ),
        ),
        SettingRow(
            label="ceiling on one operation over an open node session",
            value=_seconds(settings.node_ssh_timeout),
            variables=("HASHI_NODE_SSH_TIMEOUT",),
            note=(
                "A command or a file transfer on a session that is already open. "
                "Generous, because pulling an image legitimately takes time."
            ),
        ),
        SettingRow(
            label="ceiling on reaching a node at all",
            value=_seconds(settings.node_connect_timeout),
            variables=("HASHI_NODE_CONNECT_TIMEOUT",),
            note=(
                "Much shorter, and separate, because a node that is blocked or seized "
                "does not refuse the connection — it hangs, and you need an answer "
                "rather than a spinner. Raise it for a node on a link so lossy that "
                "the default is not enough."
            ),
        ),
        SettingRow(
            label="how long the audit log keeps an entry",
            value=_plural(settings.audit_retention_days, "day", "").strip(),
            variables=("HASHI_AUDIT_RETENTION_DAYS",),
            note=(
                "The audit log records what you changed — who you added, which node "
                "you applied — and an entry older than this is deleted, swept "
                f"{_how_often(audit.SWEEP_INTERVAL_SECONDS)}. Anything from "
                f"{AUDIT_RETENTION_MIN_DAYS} to {AUDIT_RETENTION_MAX_DAYS} days is "
                "accepted, and no value means forever: a record with no end is the "
                "thing this project is built not to keep. Nothing is swept while this "
                "control plane is off."
            ),
        ),
        SettingRow(
            label="key that encrypts stored node credentials",
            value=SETTING_CONFIGURED,
            variables=("HASHI_SECRET_KEY",),
            note=(
                "Everything this control plane stores encrypted is encrypted with it. "
                "Replacing it does not re-encrypt anything: every credential already "
                "stored, and every backup of them, becomes unreadable."
            ),
            secret=True,
        ),
        SettingRow(
            label="operator password hash",
            value=SETTING_CONFIGURED,
            variables=("HASHI_OPERATOR_PASSWORD_HASH",),
            note=OPERATOR_PASSWORD_CHANGED_WITH,
            secret=True,
        ),
        SettingRow(
            label="database this control plane runs on",
            value=SETTING_CONFIGURED,
            variables=("HASHI_DATABASE_URL",),
            note=(
                "Withheld whole rather than trimmed, because the value carries the "
                "database password — and the rest of it is the sort of thing a "
                "screenshot should not be carrying either."
            ),
            secret=True,
        ),
    ]


def admin_rows(settings: Settings) -> list[AdminRow]:
    """Who can sign into this panel — one row, and a list only so the table has a loop.

    A list rather than a single object on purpose: the template then draws a table the
    same way every other screen does, and the fact that there is exactly one row is a
    property of the product rather than a shape the markup assumes. It still cannot
    grow — there is no query here and no second account to find.
    """
    return [
        AdminRow(
            username=settings.operator_username,
            role=OPERATOR_ROLE,
            variables=("HASHI_OPERATOR_USERNAME",),
        )
    ]


# --- the audit log screen (M10.4) --------------------------------------------

# How many entries one navigation renders. The screen has no paging and is not going to
# grow one: the trail is bounded by retention already, and a second page is a second
# place a record of what the operator did can be read from. The cap is what keeps a busy
# month from rendering as one enormous table, and the screen states the number rather
# than silently truncating — an audit log that quietly hides rows is worse than one that
# says it is showing the most recent two hundred.
TRAIL_LIMIT = 200

# What this screen is, said once, at the top — and what it is NOT, which is the half
# worth the words. The charter's argument is that a record of who used the service is
# absent rather than withheld, and this is the screen where a reader would otherwise
# reasonably assume they were looking at one.
TRAIL_WHAT_IT_HOLDS = (
    "Every change made to the fleet from this panel or its API, newest first. What it "
    "does not hold is the point of it: nothing here is about anybody using the service. "
    "There is no link, no token, no address and no record of a connection — not "
    "withheld from this screen, but never written down anywhere."
)

# The empty state, which is what the stand and a fresh install open on — and what an
# operator sees again on a quiet fleet, since an entry older than the window is deleted
# rather than kept. It names the two reasons the screen can be empty, because "nothing
# here" reading as "nothing is being recorded" is how an operator stops trusting a trail
# they may later need. The second half is the same refusal the lead note makes: this is
# the screen where a reader would otherwise assume the fleet keeps a connection log.
TRAIL_NOTHING_YET = (
    "Nothing has been changed on this control plane yet — or every change that was is "
    "older than the window this trail keeps, and has been deleted. Add a user, apply a "
    "node or rotate a key and it is named here. What is never named here is anybody "
    "using the service: no link, no token, no address and no record of a connection, "
    "because none of that is written down anywhere."
)


@dataclasses.dataclass(frozen=True, slots=True)
class TrailEntry:
    """One recorded change, as the screen needs it and no wider.

    The ORM row is deliberately not what the panel is handed. Two of its five columns —
    the id, and the raw action value — are machine values the screen has no use for, and
    the sentence an operator reads is composed from ``action`` and the labels at render
    time (``panel/wording.py``) rather than stored. Handing over the model would put the
    table itself in the template's reach, which is how a screen acquires a cell nobody
    decided to show.

    There is no ``actor`` field, and that is decision 8: the trail stores no actor
    because there is exactly one, so the column is RENDERED from
    ``settings.operator_username`` — the screen's own ``operator``, which every console
    screen already has. A stored actor would be a per-person record on the one machine
    the charter calls most worth seizing, for a value that cannot vary.
    """

    at: datetime.datetime
    action: AuditAction
    first_label: str | None
    second_label: str | None


async def trail_entries(session: AsyncSession, *, limit: int = TRAIL_LIMIT) -> list[TrailEntry]:
    """The audit screen's rows, newest first.

    Every field here moves when the OPERATOR acts and none of them moves when a person
    uses the service (``docs/decisions.md``, 2026-09-09): the time is when a change
    committed, the action is one of the declared changes, and a label is a name the
    operator chose or the registry holds. The delivery endpoint writes no row at all, so
    there is nothing on this screen for a friend's client to move — asserted in
    ``tests/control/test_the_audit_trail.py`` and again against the real stack.

    The timestamp is normalised to UTC here rather than in the template, because the
    screen says once that it prints UTC and that sentence has to be true of every cell:
    Postgres hands back an aware datetime, and a value that ever arrived naive would
    otherwise be printed under a claim nothing checked.
    """
    return [
        TrailEntry(
            at=_in_utc(entry.at),
            action=entry.action,
            first_label=entry.first_label,
            second_label=entry.second_label,
        )
        for entry in await audit.recent(session, limit=limit)
    ]


def _in_utc(value: datetime.datetime) -> datetime.datetime:
    """An aware timestamp in UTC, whatever the driver handed back."""
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC)


def trail_window(settings: Settings, *, shown: int, limit: int = TRAIL_LIMIT) -> str:
    """How long an entry survives and how much of the trail is on screen, derived.

    Three readings, because the sentence has to be true of the screen it sits under: an
    empty screen has no times to explain, a full one has older entries it is not showing,
    and the ordinary one has neither.

    Every number in it is read from what this process is actually using — the operator's
    retention setting, the sweeper's own interval, and the cap above — for the reason
    the Settings screen's retention row is derived: a sentence that repeated a number
    would go false the day one moved, with nothing going red. The last clause is the gap
    stated rather than hidden, in the same words the Settings row uses.
    """
    kept = (
        f"An entry is deleted {_plural(settings.audit_retention_days, 'day', '').strip()} after "
        f"it was written, swept {_how_often(audit.SWEEP_INTERVAL_SECONDS)}; nothing is "
        "swept while this control plane is off."
    )
    # With no rows on the screen there is no clock to explain, and the empty state needs
    # this sentence most: "older than the window this trail keeps" is what it says above,
    # and this is the only place on the screen that says how long that window is.
    if shown == 0:
        return kept
    if shown < limit:
        return f"Times are UTC. {kept}"
    # Said as "anything older is not on it" rather than "there are older ones": at
    # exactly the cap there may be nothing older at all, and a screen that asserts
    # hidden rows which do not exist is as wrong as one that hides rows silently.
    return (
        f"Times are UTC, and this screen shows the most recent {limit} changes — "
        f"anything older than that is not on it. {kept}"
    )


# --- M16: a node's resolver, set after registration ---------------------------

# The refusal for an empty resolver box, the panel's own: the service is never asked about
# nothing, and "not an IPv4 address" would be a strange answer to a box left blank.
RESOLVER_REQUIRED = "required — the address this node's lookups are sent to through its hop"


def resolver_set(node_name: str) -> str:
    """The toast for a resolver that was set — naming the step the operator still owes.

    Setting it changes the record and never the host, and on a node that dials a hop it is
    the apply that finally takes its lookups through the hop. Said at the moment the
    operator is most likely to believe they are done.
    """
    return f"resolver set for {node_name} — apply it for the change to reach the node"


# --- M17: the box an operator sizes a pool of addresses in --------------------

# What the pool box says under itself, and the whole of what it has to teach: that one
# person takes one address, and that the number is a ceiling on how many people this
# transport can serve on this node. Written here rather than in the template for the
# reason every other sentence on that dialog is — a screen's words are this module's, and
# a count composed in markup is a number nobody can find when it has to change.
#
# In the panel's vocabulary (``user``), like every other constant in this file, because
# these are read straight onto the page rather than passed through ``wording``.
POOL_BOX_HINT = (
    "This protocol gives every user their own address inside the tunnel, so it has to be "
    "told how many it may hand out. One address is one user, counted upwards from the "
    "first one this transport is given above; a pool smaller than the users you already "
    "have is refused before anything is saved."
)


# What the SAME box says on the replace-parameters dialog, where the rules are the other
# way round: the row already has a size (or, on a row older than pools, has none), and an
# empty box keeps whatever that is. The enable dialog's hint says "it has to be told how
# many", which is true there and false here, so the two are separate strings rather than
# one stretched over both.
#
# It states the invariant rather than only the mechanism, because this is the one box in
# the console whose whole danger is invisible: a number that looks like it only ADDS room
# can also be a number that takes an address away from somebody who is using it. The
# product refuses that, and the operator should know it will before they type.
POOL_BOX_RESIZE_HINT = (
    "How many users this protocol may hand an address to, counted upwards from the first "
    "address above. Empty keeps what it has now; a row enabled before pools existed has "
    "no size and hands out exactly the one address it renders today. No address a device "
    "already holds is ever moved — a size or a range that would move one is refused and "
    "nothing is saved."
)


async def pool_boxes(
    session: AsyncSession, offered: list[str]
) -> dict[str, transports.TuningField]:
    """The pool box for each offered transport that gives every user their own address.

    Keyed by transport and absent for the rest, so the dialog renders it in exactly the
    group it belongs to and nowhere else — the same shape ``tuning`` already has, and
    reusing ``TuningField`` because the box behaves like every other one on that form: an
    empty one is refused, and its placeholder states what it will take rather than a value
    the form would assume.

    The placeholder is the floor and is composed HERE, in ``_declared_bounds``' own
    vocabulary ("N or more"), so no number is written into the markup. The floor is the
    number of people this control plane already has, because every one of them is granted
    a credential on this transport the moment the node serves — read from
    ``addresses.fleet_size``, which is the same call ``nodes.sized_pool`` refuses below
    and the same one the add-a-friend refusal measures against, so the box and the two
    refusals cannot disagree about who is in the fleet.

    Asked of the transport's own declaration (``TransportMeta.peer_address``) rather than
    of its name, so a protocol added later gets this box with no edit here and one that
    identifies its users by material never sees it.
    """
    boxed = [name for name in offered if addresses.spec_for(name) is not None]
    if not boxed:
        return {}
    people = await addresses.fleet_size(session)
    floor = max(people, 1)
    return {
        name: transports.TuningField(
            name=addresses.POOL_BOX,
            placeholder=f"{floor} or more",
            # The rule, and then how many people it is about to be measured against —
            # M17.2. The count is the same ``fleet_size`` the refusal below uses, said
            # where the number is typed rather than after it is refused.
            hint=f"{POOL_BOX_HINT} {pool_takers(people)}",
            default=None,
        )
        for name in boxed
    }


def pool_takers(people: int) -> str:
    """How many people this pool is about to be measured against — M17.2.

    The half of the enable dialog that the hint above cannot carry, because it is a fact
    about the fleet rather than about the box: every active user is granted a credential
    on this transport the moment the node serves, so the number they must each be given
    an address from is knowable before the operator types anything. Said here, the
    refusal for a pool below it becomes something they were warned about rather than
    something they discovered.

    Singular at one, and its own sentence at zero: "0 active users each take an address"
    is both ungrammatical and misleading on a first-run panel, where the honest thing to
    say is that the size is a ceiling for the people who are not here yet.

    It does not repeat that a smaller pool is refused — ``POOL_BOX_HINT``, which this is
    appended to, has already said so.
    """
    if people == 0:
        return (
            "No user is active yet, so nothing takes an address from it today — the "
            "size is the ceiling on how many this node can ever serve on this protocol."
        )
    if people == 1:
        return "1 active user takes an address from it the moment this node serves."
    return (
        f"{people} active users each take an address from it the moment this node serves."
    )


# What the add-a-user dialog says when a pool that is already serving could not hold one
# more person — M17.2. The dialog offers no submit button at all in that state: creating
# a user grants them a credential on every serving row, so this is not a form that might
# be refused, it is a form whose every submission is refused. A control whose only
# outcome is a refusal is worse than a sentence saying why there is no control.
#
# It names the fix rather than only the problem, and the fix is a screen: the pool is
# sized where parameters are replaced, and nothing else in this console can change it.
NO_ROOM_FOR_ANOTHER_USER = (
    "There is no room for another user yet. A user is given an address on every "
    "transport that serves them, and one of those pools is full:"
)
NO_ROOM_WHAT_TO_DO = (
    "Make the pool bigger on Keys & configs, under replace params — then add them. "
    "Nothing about this user has been stored."
)


async def full_pools(session: AsyncSession) -> list[str]:
    """Every serving pool that could not hold one more person, named — M17.2.

    ``extra=1`` is the person the operator is about to add, which is exactly the question
    ``friends.create_friend`` asks before it writes anything — the same call, so the
    dialog cannot offer a button the service is certain to refuse, and cannot withhold
    one the service would have accepted.

    Names and counts only, in ``addresses.named``'s words: the operator reads the same
    phrase here, in the API's refusal and beside the two actions this console withholds
    over a short pool.
    """
    return [addresses.named(row) for row in await addresses.shortfalls(session, extra=1)]
