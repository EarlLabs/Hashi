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

The one figure that looks like a measurement and is not: ``transports_served``. It counts
the credentials WE minted for a friend against the node-transports currently serving —
"is this person covered", a property of our own configuration. It does not move when
they connect, it does not move when they do not, and it is identical for a friend whose
device is in a drawer. It was called ``nodes_served`` and the column above it read
*nodes served* until M23's eighth round, which found the two disagreeing on the real
hosts: one node serving two protocols reads ``2 / 2``, and what is being counted is the
node-transport — the unit a friend's link actually carries an entry for.
"""

import dataclasses
import datetime
import json
import logging
from collections.abc import Sequence

from sqlalchemy import select
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

# And what the cell says about a node this control plane will never push to again — M23,
# round 8, which read ``retired`` beside ``in sync`` on the real hosts with five friends
# revoked since that node's last apply.
#
# The comparison the other four answers come from is arithmetic on two digests, and for
# this one node the arithmetic is sound and the SENTENCE is not: what "in sync" means to a
# reader is "nothing to do here", and the one host where that is false in the way that
# costs a person something is the host nothing can be pushed to. Whatever it was last
# given is what it is still running, including the credentials of everyone withdrawn since
# — which is exactly what the Users screen's standing note says about the same node
# (``WITHDRAWAL_UNCONFIRMABLE``), and that note sends the operator to this screen.
#
# ASKED THROUGH ``apply.cannot_serve_again``, which is the predicate the apply door, the
# probe door and that note already ask, so a state added later that cannot serve again
# lands here without this module being found and edited. It names no literal state: what
# may serve again is the machine's to say.
#
# It ends in the one move that is left, in ``apply.REGISTER_IT_AGAIN``'s words rather than
# in new ones — every other sentence this console says about such a host ends there, and a
# cell that invented its own would be a fifth wording of one answer.
CANNOT_BE_RECONCILED = "cannot be reconciled — register the host again as a new node"

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
# THIS SAID "not in a user's link yet — this panel cannot hand it over" AND THAT WAS NOT
# TRUE — found while fixing M20's acceptance finding about the sentence one screen over.
# It was written before item 27 landed and describes the world it was written in. Item 27
# landed: ``GET /sub/{token}?format=client-config-file`` answers the same bearer token
# with an archive of this friend's configuration files (``control/app/api/delivery.py``,
# which says so in its own docstring), and the delivery endpoint is this same
# application. So the product hands it over; what is true is only that it is not IN the
# base64 link, which is exactly what ``subscription_expressible`` measures and all this
# cell may therefore claim.
#
# It does not name the query parameter, and that is deliberate rather than coy: the
# format is the one already printed in this row's own delivery column, so the sentence
# stays one arm per FORMAT and gains nothing to edit when a third shape arrives.
TRANSPORT_NOT_IN_THE_LINK = (
    "not in the subscription link itself — a user's client gets it from that same link "
    "by asking for the shape above"
)

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
# it has to be right about the whole stack, and here it is not. The gap was background
# in ``docs/tracker/M9/carry-over.md`` — no field of ``TransportMeta`` expressed it, so
# the only way to show it was for `control` to recognise a protocol by name — AND M20
# CLOSED IT the way that note said it had to be: an ``edge``-side declaration,
# ``TransportMeta.retired``, measured twice on a live node. This sentence is unchanged by
# that, because the two say different things: this one is what a protocol IS on any
# network, and the declaration is what this image can carry on the hosts this project
# builds. ``TRANSPORT_RETIRED`` below is the second one's words.
TRANSPORT_WHY_IDENTIFIED = (
    "it has no camouflage. The wire format is fixed and looks like itself, so a "
    "network that inspects traffic can name the protocol and drop it: both ends stay "
    "correctly configured, no tunnel comes up, and nothing on the user's device says "
    "what happened."
)

# What retirement MEANS to the operator, in front of the transport's own reason for it
# — M20. Two sentences deliberately: the first is the consequence on this panel and is
# the same for every retired transport, so it is written once here; the second is the
# fact that caused it, which only the transport can know and which is read straight out
# of ``TransportMeta.retired``.
#
# It says what still works as well as what stopped, because the operator reading this
# most likely has a node running the transport already — the leaf did when this was
# written — and a row that said only "retired" would read as "your node has stopped".
TRANSPORT_RETIRED = (
    "no longer offered when enabling a transport, and a node already running it keeps "
    "serving it —"
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
    # What the last probe of this host found, as the row says it — or ``None`` when the
    # last probe found nothing wrong and when nobody has probed at all. M26's first
    # acceptance walk: the finding used to live as long as the banner carrying it, so a
    # dead daemon was a green row one reload later. ``drift`` beside it is the other
    # question and stays the other question — that one is about what WE have pushed and
    # needs no network; this one is what the HOST last said, and only a press gets it.
    probe: str | None = None
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

    # NAMED FOR WHAT THEY COUNT since M23's eighth round, which read ``2 / 2`` under a
    # column headed *nodes served* on a fleet with one node in service. The unit is the
    # NODE-TRANSPORT, and it is the right unit rather than the convenient one: it is what
    # a friend's link carries one entry per, so a person missing the second protocol on
    # the only node in the fleet is a fault this column can show. Counting distinct nodes
    # instead would have read ``1 / 1`` over exactly that fault.
    transports_served: int
    transports_serving: int


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

    ``retired_note`` CLOSED THE GAP THIS DOCSTRING USED TO RECORD. It said that whether
    the image this project pins can carry a protocol to a user without failing silently
    was recorded in prose alone, not machine-readable, and therefore unshowable without
    `control` recognising a protocol by name. M20 made it a declaration
    (``TransportMeta.retired``), measured twice on a live node, so the screen now says
    it — from the same place every other cell comes from, and still with no name compared
    anywhere on the path.
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
    # ``hop_expressible``, but only when it is False: a transport a hop can be built out
    # of needs no sentence about it, and a column that says "may carry a hop" on every
    # row that can teaches nothing.
    #
    # THE DERIVED ANSWER AND NOT THE RAW ``hop_capable`` PERMISSION — M20's acceptance,
    # which found ``GET /api/transports`` advertising a capability whose renderer refuses
    # it. Both surfaces answer that one question and they read one value, because two
    # readings of it is how the JSON came to disagree with the renderer in the first
    # place. It puts the sentence on more rows than before, and that is the correction:
    # the rows it appears on now are exactly the ones the hop dialog will not offer.
    hop_note: str | None
    # ``peer_address``, and only when it is declared — M17.2. Present on the transports
    # that hand each user an address out of a pool, absent on the ones that identify a
    # user by their material, for the same reason ``hop_note`` is one-sided: the row
    # that needs a sentence is the one with a consequence for the operator, which here
    # is a number they will be asked for on every node they enable it on.
    address_note: str | None
    # ``retired``, and only when it is declared: what the panel will no longer do with
    # this transport, followed by the transport's own reason. One-sided like
    # ``hop_note`` — a transport that is offered needs no sentence saying so.
    retired_note: str | None
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
    # What the operator has to do about the users on this row whose material predates
    # what the transport now declares, or ``None`` when there are none — M23. A sentence
    # and never a list: which person is affected is a fact about a person, and the repair
    # is the same one button for all of them.
    stale_material: str | None


# What one transport on one node is doing for the people this fleet exists for, as the
# words the Nodes screen's own actions are read beside. Every one of them is composed
# from facts about OUR configuration — the row's purpose, its ``enabled`` flag, and what
# the transport DECLARES it serialises into — and never from which protocol it is, which
# is the same rule the chips on the table follow.
#
# The withdrawn sentence carries the thing ``nodes.set_transport_enabled`` insists on
# and that a panel is most likely to blur: switching a transport off changes what the
# control plane DELIVERS, not what the host is running. An operator who reads
# "withdrawn" as "stopped" has been told the opposite of what happened.
#
# THERE ARE TWO WITHDRAWN SENTENCES because "apply it" stops being true — M18.1's review.
# Applying a node with nothing enabled renders no config and is REFUSED
# (``apply.NOTHING_TO_APPLY_YET`` and ``apply.NOTHING_LEFT_TO_APPLY``), so on a node
# whose last enabled row this is, "until you re-apply it" sent the operator to a button
# that answers "nothing to push". The distinction is the node's, not the row's: one enabled row
# anywhere on it — a hop end counts, it renders too — and the apply goes through without
# the withdrawn one, which is exactly what stops the container serving it.
#
# AND THERE ARE TWO OFFERED SENTENCES because "in every user's link" is not true of every
# transport — M20's acceptance. It was said of every enabled row, including the rows whose
# protocol is not a link at all: the ``/sub/`` document is the v1 URI list and holds
# nothing else, so a config-file transport was promised a delivery that document does not
# make. The walk read a real subscription to settle it — the URI entries and nothing else.
#
# WHAT THE SECOND SENTENCE MAY NOT SAY IS THAT IT IS UNDELIVERED, which is where the
# obvious wording would have gone and would have been the same defect pointed the other
# way. The same bearer token answers ``?format=`` with an archive of this friend's
# configuration files (``control/app/api/delivery.py``, item 27), so "this panel cannot
# hand it over" is false about this product — see ``TRANSPORT_NOT_IN_THE_LINK``, which
# said exactly that and has been corrected with it.
#
# NOR MAY IT SAY THE FRIEND SIMPLY GETS IT, which is the other way to be wrong here and
# the more dangerous one: nothing in this panel hands the operator the URL that asks for
# the file shape, so an operator told "delivered from that same link" would tell a friend
# to open the link they already have and the friend would meet an empty page. That gap is
# its own milestone and is not closed here. So the sentence says ONLY BY ASKING for the
# shape — three facts, all true today, and none of them a decision that milestone has to
# make: the host is told to serve it, it is not in the link itself, and the shape it
# arrives in is a file.
#
# Chosen by the transport's own derived declaration and never by a name, like every other
# string in this module.
OFFER_IN_EVERY_LINK = "offered — in every user's link at their next refresh"
OFFER_NOT_IN_THE_LINK = (
    "offered — the node serves it once applied, but it is not in the subscription link "
    "itself: this transport is a config file, and a user's client gets it from that same "
    "link only by asking for that shape"
)
OFFER_WITHDRAWN = (
    "withdrawn — out of every user's link. The node is still configured to serve it "
    "until you apply the node without it."
)
OFFER_WITHDRAWN_LAST_ON_THE_NODE = (
    "withdrawn — out of every user's link. The node is still configured to serve it, and "
    "this was the last transport enabled here: an apply now has nothing to push and is "
    "refused, so it keeps serving this one until a transport on this node is offered "
    "again and applied."
)
OFFER_HOP_END = (
    "one end of a hop — not something a user is offered. Tear the hop down from the "
    "Hops screen; switching one end off would leave a tunnel that no longer completes "
    "while both ends still look configured."
)

# Why a withdrawn row's offer button is not drawn at all — M17.2. Offering a transport
# hands every active user a credential on it IN THE SAME TRANSACTION (M17 moved the
# fan-out inside it), and on a transport that gives each of them an address of their own
# a pool this small has nowhere to put them. What the operator cannot be left with is a
# row they offered believing it would carry the fleet, because by then they have already
# told thirty people the protocol is coming.
#
# WHAT THE SENTENCE MAY CLAIM. This used to be careful to say only what was true on both
# kinds of node, because the press was refused on a serving one and COMMITTED on one that
# was not: the withholding was wider than the service's refusal, and the sentence had to
# state the ceiling rather than a refusal that would not arrive. That gap was the blocking
# finding of M17.2's acceptance and it is closed — ``nodes.POOL_SHORT_TO_OFFER`` refuses
# the press on every node, before anything is written — so the sentence can now say the
# plain thing. The withholding itself is unchanged and its decision is not reopened
# (``docs/decisions.md``, 2026-09-13); what changed is that the button's absence is now a
# courtesy in front of a rule rather than the only thing in the way.
#
# The pool is NAMED — node, transport and both counts, in ``addresses.named``'s words, so
# the sentence here and the refusal the API returns describe the same pool the same way.
# It also names the one screen that can fix it: there is no resize action in this console,
# the size is a box on the replace-parameters dialog, and an operator who does not know
# that has nowhere to go from here.
POOL_SHORT_TO_OFFER = (
    "not offered — {pools}. Every active user is given an address here the moment this "
    "row serves, so as it stands nobody can be, and offering it is refused whatever "
    "state the node is in. Make the pool bigger first: Keys & configs, replace params."
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
# it, so a short pool on the node usually refuses the move.
#
# USUALLY, and the sentence is written for the case where it does not. ``grant_everywhere``
# skips a row a friend already holds a credential on, so on the field's own row — a
# pre-pool row counted as one address with two people already on it — nothing is minted,
# nothing is refused, and the node would go into service carrying a transport with no room
# for the fleet. Withholding is still right there, and is the only reason that row gets
# repaired before it is served; what must not be right is a sentence claiming a refusal
# that would not arrive. So this states the ceiling and the next thing that WILL be
# refused, both of which are true in every state it is shown in.
POOL_SHORT_TO_SERVE = (
    "not offered — {pools}. A node that serves gives every active user an address on "
    "each transport it offers, and this pool cannot hold the fleet: serving it would "
    "leave a transport with no room for the people it is meant to carry, and the next "
    "user you add would be refused on it. Make the pool bigger first: Keys & configs, "
    "replace params."
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
    # The node the row is on, carried because a route that has just DELETED the row still
    # has to ask the node a question afterwards — whether anything is left enabled on it
    # — and ``node`` is the operator's name for it, not a key.
    node_id: str
    node: str
    transport: str
    offered: bool
    for_friends: bool
    # Which of the three sentences above this row is in, composed here so no template
    # chooses between them and no route writes one.
    standing: str
    # Whether this is the only row still enabled on its node — M18's acceptance, and the
    # question BOTH confirmation dialogs turn on. It is asked about the OTHER rows on
    # purpose: what each dialog has to say is whether an apply will still have something
    # to push AFTER the action, and withdrawing or removing this row takes it out of that
    # count either way. True means the apply the confirmation would otherwise send the
    # operator to is refused, so it will never be the thing that stops the host.
    #
    # A flag rather than a composed sentence, unlike ``standing`` beside it: the two
    # dialogs say DIFFERENT things about the same fact — a withdrawn row can be offered
    # back and a removed one cannot — and their prose is where the rest of each dialog's
    # prose already lives.
    nothing_else_enabled: bool
    # Whether ANY row on this node has ever been pushed to its host — M18's acceptance,
    # round 2, and the other half of what both confirmation dialogs say. Their sentence
    # about what the host keeps serving was byte-for-byte the same on a node really
    # serving the transport and on one whose address does not resolve; the product knows
    # the difference, because ``applied_at`` is set by a successful push and by nothing
    # else, and said it on one surface and not on this one.
    #
    # TRUE IS THE ABSENCE OF EVIDENCE, NOT EVIDENCE OF ABSENCE, and the dialogs' prose is
    # written to that: a removed row takes its stamp with it, so a node whose only applied
    # transport was removed reads as never-applied here. What TRUE licenses is therefore
    # "nothing this panel holds has ever been pushed" — a fact about the rows — and never
    # "the host is running nothing", which this control plane cannot know from here.
    never_applied_here: bool
    # Whether this row's transport reaches a user's link at all — M20's acceptance. The
    # transport's own derived declaration (``subscription_expressible``), carried on the
    # row because ``standing`` above is not the only sentence that turns on it: the toast
    # this row's own button raises makes the same promise, and the two were both making
    # it of a protocol this panel cannot hand over.
    #
    # A flag rather than a composed sentence, like ``nothing_else_enabled``: the row and
    # the toast say different things about the same fact, and each keeps its own words.
    deliverable: bool
    # Whether this panel would let the operator enable this transport here again — M20's
    # acceptance. The remove confirmation promises that "enabling it here again mints new
    # material", and on a RETIRED transport there is no form on this panel that would:
    # the walk removed such a row and the enable dialog went on offering three. The
    # destructive half of that sentence was right and only the promise was stale.
    #
    # ``transports.offerable_transports`` and not ``meta.retired``, because it is the same
    # list the enable dialog is built from and the enable route reads a submission
    # against — so what this claims and what that would do cannot drift. It also answers
    # correctly for a row whose package has left the image, which retirement alone would
    # not.
    offerable_again: bool
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
    # What the four counts above do not know — M26's first acceptance walk. Up to two
    # sentences, empty on a fleet this panel has nothing to correct about, and composed
    # from the rows beside them so the cards and the warning cannot disagree.
    doubts: list[str]
    # And the standing limit of the counts, said whatever the fleet looks like. Carried on
    # the value object rather than written into the template for the same reason every
    # other sentence here is: a screen may not compose its own account of what it knows.
    # No default, like every field above it: this screen is built in one place, and a
    # default here would be a second place the sentence could come from.
    limit: str


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

    AND FOR ONE NODE THE COMPARISON IS NOT THE QUESTION AT ALL — M23, round 8. A node the
    state machine will not put back into service is never pushed to again, so how far its
    last configuration sits from the one we would render is a measurement of nothing, and
    the answer it produced was the reassuring one: the walk read ``retired`` beside ``in
    sync`` on a host five revocations old. That is asked FIRST, above the render, because
    no later branch could unsay it — and because rendering a node nothing will be sent is
    work done for an answer that cannot be used.
    """
    if apply.cannot_serve_again(node.state):
        return CANNOT_BE_RECONCILED

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


# How a kept probe finding is said on the row it survives on — M26's first acceptance
# walk. The finding itself is the sentence the operator read when they pressed the button
# (``health_summary``, recorded by ``services/health``); what this adds is WHEN, because a
# fault found four minutes ago and one found last Tuesday are different facts and the row
# is read long after the banner is gone.
#
# It says "probe" rather than "why", which is the word the row's other detail line uses
# for ``state_detail``: those two are different in kind and a reader has to be able to
# tell them apart without knowing this codebase. ``state_detail`` is what THIS control
# plane last failed to do to the host; this is what the HOST last said about itself.
PROBE_FINDING = "probe, {when} UTC — {finding}"


def probe_note(node: Node) -> str | None:
    """What the last probe of this node found, or ``None`` when there is nothing to say.

    ``None`` covers two different states on purpose, because neither is a finding: a node
    nobody has probed, and a node whose last probe found nothing wrong. What tells those
    two apart is the FLEET reading below — a row carrying no note is not making a claim,
    and the screens that would otherwise be read as making one say so themselves.

    Composed here rather than in the template for the reason every sentence in this module
    is: the Nodes screen and the Overview say this about the same host, and a template
    that wrote its own version of it would be the second account of one answer.
    """
    if node.last_probe_at is None or not node.last_probe_finding:
        return None
    return PROBE_FINDING.format(
        when=_in_utc(node.last_probe_at).strftime("%d %b %Y %H:%M"),
        finding=node.last_probe_finding,
    )


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
            probe=probe_note(node),
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


# What the Users screen says instead of nothing about a withdrawal it cannot confirm —
# M23, round 2, measured on the real leaf: a revoke whose push failed left the row reading
# "revoked / no access" while that person's tunnel was carrying traffic, with the truth
# only on the Nodes screen and only in a banner that had already gone.
#
# IT IS A FLEET SENTENCE AND NOT A PER-PERSON ONE, and that is forced rather than chosen.
# A revocation DELETES the credential rows — which is the property that makes revocation
# total (``friends.revoke``) — so the moment it commits, nothing in this database records
# which nodes that person was on. Naming them per row would need a record this schema does
# not carry and the charter would not obviously want; what is knowable is which hosts this
# panel cannot say are running what it would give them, which is the same set for
# everybody and is exactly what "may still be serving a withdrawn credential" means.
#
# So it hedges, and the hedge is the honest part: "may still be carried" is what a panel
# that cannot see a running daemon may say. It names the nodes, because that is the text
# the operator acts on, and it ends where the answer lives — probe and apply are on the
# Nodes screen and nowhere else.
#
# FOR THE NODES WHERE THAT IS ACTUALLY TRUE, since M23's thirteenth round. Round 12 taught
# the revoke dialog that a node the state machine will not put back into service cannot be
# finished from this panel, and left this banner saying the opposite about the same host:
# "probe it on the Nodes screen and apply it; that is where this state is read and the
# only place it changes", over a node where both buttons answer that they refuse it. The
# banner appears exactly when it matters — a withdrawn person may still be carried there —
# so the one sentence the operator acts on was the one that sent them nowhere.
WITHDRAWAL_UNCONFIRMED = (
    "Withdrawn access is not confirmed on {nodes}: {this} not running the configuration "
    "this panel would give {it}, and a daemon goes on serving the file it was last "
    "started with — so anyone withdrawn while that is true may still be carried there, "
    "whatever this table says. Probe {it} on the Nodes screen and apply {it}; that is "
    "where this state is read and the only place it changes."
)

# And the same doubt about a node no press on this panel can resolve — the other half of
# the sentence above, split off rather than hedged into it.
#
# ONE PREDICATE DECIDES WHICH, and it is ``apply.cannot_serve_again``: the same one round
# 12 gave the apply door and the probe door, so a state added later that cannot serve
# again lands here without this module being found and edited. It names no literal state
# for that reason — what refuses is the machine.
#
# It says MORE than the sentence beside it rather than less, because the operator's next
# move is genuinely different and there is no button on this screen or the Nodes screen
# that makes it. The wording is ``revocation._WHY_NOT_UPDATED[NotUpdated.CANNOT_SERVE]``'s,
# said in a standing note's voice: nothing reaches that host from here, the host may still
# be authorising the credential, and the way back is a new record for it. The two are not
# one constant because one is about a press that just happened and this is about a fleet
# reading — but they must not disagree, and acceptance judges both.
WITHDRAWAL_UNCONFIRMABLE = (
    "Withdrawn access is not confirmed on {nodes}, and no screen in this panel "
    "finishes it: {this} in the state an operator records a host as GONE in, which is the "
    "one state this control plane will neither probe nor apply — so anyone withdrawn while "
    "that was true may still be carried there, and nothing pushed from here reaches {it}. "
    "If such a host is genuinely back, register it again with \"add node\" on the Nodes "
    "screen and apply that one; otherwise it is the host being gone that ends this."
)

# What the actions cell says on a row nobody can act on any more. It replaced "no access"
# — M23, round 2: that is a claim about a person's connectivity, which this control plane
# cannot make about a host it has not confirmed, and the walk measured it being false. The
# words are about what the OPERATOR did, which is the part that is always true.
ACCESS_WITHDRAWN = "access withdrawn"


@dataclasses.dataclass(frozen=True, slots=True)
class UnconfirmedNode:
    """One host this panel cannot say has stopped serving what it was last given.

    Two fields because the screen has two things to say about such a host and they are not
    the same sentence — M23's thirteenth round. Which one it gets is not a property of the
    doubt but of the node's STATE: a degraded host is probed and applied, and a host the
    operator has recorded as gone is neither, ever.
    """

    name: str

    # Whether probe and apply are still the way to end the doubt here. Read through
    # ``apply.cannot_serve_again`` and never off a literal state, so the two buttons'
    # refusal and this banner's instruction come from one answer — that predicate is the
    # one round 12 built for exactly this question.
    can_be_finished: bool


def withdrawn_cell(unconfirmed: Sequence[UnconfirmedNode]) -> str | None:
    """What the actions cell may say about a revoked row, or ``None`` for nothing at all.

    ROUND 2 CHANGED THE WORDS AND ROUND 3 FOUND THEM STILL WRONG. "access withdrawn" is
    about the operator's own action and is always true of the database — but the walk read
    it on the row of somebody who downloaded a megabyte through the real leaf while it was
    on screen, and a reader does not parse a cell that carefully. Beside a standing note
    saying the withdrawal is not confirmed, the cell was the sentence contradicting it.

    So the cell says nothing while that note is up. NOTHING, and not a hedge of its own:
    what a per-row sentence would have to claim is which nodes THIS person was on, and a
    revocation deletes exactly the rows that would say (``friends.revoke``) — so there is
    no per-row answer to give, which is the finding round 2 got right and this does not
    reopen. An empty cell is the honest amount, and the doubt is stated once, above the
    table, where it names the nodes and the two controls that resolve it.

    Driven by the SAME reading as that note, and from the same list, so the two cannot
    disagree: while the fleet is confirmed the cell says what the operator did, and the
    moment it is not, it stops saying anything.
    """
    return None if unconfirmed else ACCESS_WITHDRAWN


async def unconfirmed_nodes(session: AsyncSession) -> list[UnconfirmedNode]:
    """Every node this panel cannot say is running the configuration it would push.

    The Nodes screen's own two readings, joined and named: a node is CONFIRMED when it is
    in a serving state and its drift cell reads in sync, and is in this list otherwise —
    but only once something has actually been pushed to it. A node nothing ever reached is
    serving nobody, so it carries no withdrawn credential either, and listing it would put
    a permanent warning on a first-run panel.

    Nothing here is about a person. It is the fleet's own state, asked once for a screen
    that has to say what a withdrawal it cannot confirm means.

    One render per node, like ``node_rows``, and for the same reason: the answer is
    honest rather than cached. It touches no network, so a fleet with every host
    unreachable costs exactly what a healthy one does, and it is bounded by the size of a
    fleet this product is built for — one owner and a handful of nodes.
    """
    unconfirmed = []
    for node in await nodes.list_nodes(session):
        if not any(row.applied_at for row in node.transports):
            continue
        if node.state in NodeState.serving() and await drift_of(session, node) == IN_SYNC:
            continue
        unconfirmed.append(
            UnconfirmedNode(
                name=node.name,
                can_be_finished=not apply.cannot_serve_again(node.state),
            )
        )
    return unconfirmed


def _about(names: Sequence[str], sentence: str) -> str:
    """One of the two sentences above, agreeing with the number of hosts it names."""
    return sentence.format(
        nodes=", ".join(names),
        this="that node is" if len(names) == 1 else "those nodes are",
        it="it" if len(names) == 1 else "them",
    )


def withdrawal_doubt(unconfirmed: Sequence[UnconfirmedNode]) -> str | None:
    """The sentence for those nodes, or ``None`` when there is nothing to say.

    ``None`` on a fleet where every host is confirmed, so the screen carries no standing
    warning — a banner that is always there is a banner nobody reads on the day it means
    something.

    UP TO TWO SENTENCES SINCE M23's THIRTEENTH ROUND, and both are said when the fleet has
    both kinds of host in it. Splitting rather than picking one is what the finding forces:
    the nodes are named because naming them is the text the operator acts on, so a fleet
    with a degraded host AND a retired one has to say which instruction belongs to which —
    one sentence covering both would either send them to a button that refuses half the
    list, which is the defect, or drop the instruction entirely from the half where it
    works.

    Sorted only by the order ``unconfirmed_nodes`` read the fleet in, which is the Nodes
    screen's own order: a banner that reshuffles between reloads reads as the fleet
    changing.
    """
    if not unconfirmed:
        return None
    finishable = [node.name for node in unconfirmed if node.can_be_finished]
    written_off = [node.name for node in unconfirmed if not node.can_be_finished]
    return " ".join(
        _about(names, sentence)
        for names, sentence in (
            (finishable, WITHDRAWAL_UNCONFIRMED),
            (written_off, WITHDRAWAL_UNCONFIRMABLE),
        )
        if names
    )


# WHAT ADDING A USER DOES NOT DO — M26's first acceptance walk, and the finding is the
# shape this project keeps producing: every signal green and nothing carried.
#
# The walk added a friend and fetched their configuration file. It was complete and
# correct — the node's real public key, an address out of that row's pool — while on the
# host the rendered config held ZERO peer blocks and the daemon listed none. A friend's
# client would have handshaked into nothing. Only a SECOND apply, three minutes later, put
# the peer on the node and made the traffic flow.
#
# Adding a user changes what this panel WOULD push and touches no host, which is correct
# and is the whole of the defect: nowhere the operator was standing said so. The Users
# screen's other standing note is about access that was WITHDRAWN and cannot be confirmed
# gone — the exact opposite direction — so a reader who had just pressed "add user" had no
# reason to read it as being about them.
#
# It is said on the Users screen and again in the dialog that hands the link over, because
# that dialog is the moment the false promise is delivered. ONE CONSTANT for both, so the
# screen and the dialog cannot come to different accounts of one fact.
#
# It names the nodes, like every other sentence on these screens that asks the operator to
# go and do something, and it ends where the press is.
MATERIAL_NOT_ON = (
    "A user added here is not on {nodes} yet: {this} not running the configuration this "
    "panel would give {it}, and adding a user changes only what this panel would push. "
    "So anyone added or granted since {it} was last applied has no credential on {it} — "
    "their link carries {it}, their client would find nothing of theirs there, and "
    "nothing about the link itself would look wrong. Apply {it} on the Nodes screen."
)

# The same reading on the Overview, where what it has to correct is a COUNTER rather than
# a link. Same list, different sentence, for the reason M23 split its two: the operator's
# next move is the same press, but what they are reading it against is not.
FLEET_NOT_PUSHED = (
    "Not yet pushed to {nodes}: {this} not running the configuration this panel would "
    "give {it}, so something has changed here since {it} was last applied. The counts "
    "above are counts of configuration, so {it} is still in them and still in every "
    "user's link. Apply {it} on the Nodes screen."
)

# And what the last probe found, on the screen whose subtitle promises to say whether the
# nodes are running what they were told to — M26's first acceptance walk, the other half
# of the same finding. The walk stopped a daemon, probed, read the correct answer, and
# then watched the Overview go on reporting "nodes active 2 … transports serving 2" while
# the friend's ping was 100% loss.
#
# It does not repeat the finding itself. The finding is on the node's own row, where probe
# and apply are, and a full diagnosis in a banner on another screen is a second copy of a
# sentence that can be 1000 characters long.
FLEET_NOT_SERVING = (
    "The last probe of {nodes} found {it} not serving what this panel gave {it}, and "
    "nothing has been applied to {it} since. The counts above are counts of "
    "configuration, so {it} is still in them and still in every user's link. The finding "
    "is on the Nodes screen, under that row."
)

# The standing limit of all four counters, said once and always — not a warning and not a
# reading of any particular fleet. It is here because the two sentences above only appear
# when this panel KNOWS something is wrong, and a screen that is silent the rest of the
# time would be read as having checked. Nothing on this screen dials a host: the counters
# are configuration, and the only thing that measures a host is the button on the Nodes
# screen.
COUNTERS_COUNT_CONFIGURATION = (
    "These four count configuration — what is registered, enabled and in service. "
    "Nothing on this screen dials a host, so none of them moves when a daemon stops. "
    "What a host is actually running is measured only when you press probe on the Nodes "
    "screen, and what that found is kept until the next apply."
)


async def nodes_missing_what_they_would_be_given(session: AsyncSession) -> list[str]:
    """Serving nodes whose host does not hold the configuration this panel would push.

    THE SUPERSET OF "a user was added and nobody applied", which is what M26's walk found,
    and it is deliberately not narrowed to that: a granted credential, a withdrawn one, a
    resized pool and a changed parameter are the same fact about the same host, and a list
    that tracked only one of them would go quiet on the others.

    ``in sync`` and ``nothing enabled`` are the two readings that are NOT this. The first
    is the host holding exactly what we would give it; the second is a node with nothing
    switched on, which has nothing to be behind about — and listing it would put a
    standing warning on a first-run panel, which is the one place it means nothing.

    Serving only. A draft or degraded node is not in anybody's link, so a user's material
    missing from it is not a promise being made to anyone — and the Users screen's other
    note is already about exactly those hosts, from the other direction.

    One render per node, like ``node_rows`` and ``unconfirmed_nodes``, and the Users screen
    now pays for two passes over a fleet this product sizes at a handful of hosts. It
    touches no network either way; the alternative is caching a reading that has to be
    true at the moment it is read.
    """
    behind = []
    for node in await nodes.list_nodes(session):
        if not node.is_serving():
            continue
        if await drift_of(session, node) in (IN_SYNC, NOTHING_ENABLED):
            continue
        behind.append(node.name)
    return behind


def material_doubt(behind: Sequence[str]) -> str | None:
    """What a link handed over now cannot promise, or ``None`` when it can.

    ``None`` on a fleet holding everything we would give it, so neither the Users screen
    nor the subscription dialog carries a standing warning — the same rule
    ``withdrawal_doubt`` keeps, and for the same reason.
    """
    return _about(list(behind), MATERIAL_NOT_ON) if behind else None


def fleet_doubt(rows: Sequence[NodeRow]) -> list[str]:
    """What the Overview's counters do not know, as the sentences that say so.

    Composed from the rows the screen is already showing rather than from a second reading
    of the fleet: the cards, the node preview and these sentences are then one answer seen
    three ways, and there is no arrangement of them in which the preview says a node is
    behind and the sentence under the cards does not.

    Up to two, in the order an operator acts on them: a host that was MEASURED not serving
    is worse news than one that is merely behind, and it is the one the walk watched the
    product forget.
    """
    found = [row.name for row in rows if row.probe]
    behind = [
        row.name
        for row in rows
        if row.state in NodeState.serving() and row.drift not in (IN_SYNC, NOTHING_ENABLED)
    ]
    return [
        _about(names, sentence)
        for names, sentence in ((found, FLEET_NOT_SERVING), (behind, FLEET_NOT_PUSHED))
        if names
    ]


async def friend_rows(session: AsyncSession) -> list[FriendRow]:
    """Every friend, with how much of the fleet they are covered on.

    ``transports_serving`` is the denominator every active friend shares, so a row reading
    ``2 / 3`` says "this person is missing one of the protocols being served", which is an
    actionable fault in OUR configuration and the reason the column exists.

    ``serving_transports`` is friend-facing rows only, so the denominator never counts one
    end of a hop — a tunnel between two of our own nodes is not something a person holds a
    credential on.
    """
    serving = await nodes.serving_transports(session)
    serving_ids = {row.id for row in serving}
    return [
        FriendRow(
            id=friend.id,
            nickname=friend.nickname,
            is_active=friend.is_active,
            added=friend.created_at,
            transports_served=sum(
                1
                for credential in friend.credentials
                if credential.node_transport_id in serving_ids
            ),
            transports_serving=len(serving_ids),
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
    # Whether an apply on this node would have anything to push — M18.1's review. Read
    # from the rows already in hand, once for the whole dialog, and true only when the
    # node has no enabled row of any purpose left.
    nothing_left_enabled = not any(row.enabled for row in rows)
    # And whether anything on this node has ever reached its host, measured once for the
    # whole dialog off the rows already in hand. ``applied_at`` is written by a successful
    # push and by nothing else, and a withdrawal leaves it alone — so a row that carries
    # one is proof, and no row carrying one is only the absence of proof.
    never_applied_here = not any(row.applied_at is not None for row in rows)
    # Whether each row's transport reaches a user's link at all — its own declaration,
    # keyed by row id and read once for the whole dialog like every other measurement
    # above. ``get`` and not ``[]``: a row whose package has left the image still has to
    # render a line, the same reason ``key_rows`` resolves it this way, and a transport
    # that is not in this image delivers nothing.
    installed = discover()
    delivers = {
        row.id: row.transport_name in installed
        and installed[row.transport_name].subscription_expressible
        for row in rows
    }
    # And whether this panel would offer each of them again — the same list the enable
    # dialog is built from, asked once for the whole dialog.
    offerable = set(transports.offerable_transports())
    return [
        OfferRow(
            id=row.id,
            node_id=node.id,
            node=node.name,
            transport=placed_as(row.transport_name, row.config_name),
            offered=row.enabled,
            for_friends=row.purpose == TransportPurpose.FRIENDS,
            standing=_standing(
                row.purpose,
                row.enabled,
                nothing_left_enabled=nothing_left_enabled,
                deliverable=delivers[row.id],
            ),
            deliverable=delivers[row.id],
            offerable_again=row.transport_name in offerable,
            # Measured per row rather than reusing the whole-dialog reading above,
            # because it is a different question: that one is "is anything enabled
            # here now", this one is "would anything be enabled here without this
            # row". They agree on every row of a node with nothing enabled and differ
            # on the last enabled one, which is the row both dialogs are wrong about.
            nothing_else_enabled=not any(
                other.enabled for other in rows if other.id != row.id
            ),
            # About the NODE and not about this row, unlike the flag above it: what the
            # dialog is deciding is whether this panel may describe what the host is
            # serving, and one applied transport makes the host a machine we have pushed
            # to whichever row is being withdrawn or removed.
            never_applied_here=never_applied_here,
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


def _standing(
    purpose: TransportPurpose,
    enabled: bool,
    *,
    nothing_left_enabled: bool,
    deliverable: bool,
) -> str:
    """Which of the five sentences this row is in.

    A branch on our own topology, on the operator's own flag and on the transport's own
    declaration — never on a protocol. A hop end is answered first because ``enabled``
    means something different there: it says the tunnel should be running, not that
    anybody is being offered anything.

    ``nothing_left_enabled`` is a fact about the NODE, passed in rather than measured
    here because it is the same measurement for every row in the dialog and the caller
    has already read them all. It only ever changes the withdrawn sentence: an apply that
    has something to push is what stops the host serving a withdrawn row, and on a node
    with nothing enabled at all there is no such apply.

    ``deliverable`` is a fact about the TRANSPORT, passed in for the same reason: the
    caller has the registry open already. It is ``subscription_expressible`` — whether the
    protocol rides in the base64 LINK, not whether a user can receive it, which is a
    different question this panel got wrong in both directions (see
    ``OFFER_NOT_IN_THE_LINK``). It only ever changes the OFFERED sentence — M20's
    acceptance, which read "in every user's link at their next refresh" on a row that is
    in no link. The withdrawn sentences are left alone deliberately: "out of every user's
    link" claims nothing about having been in one, so it is true of both kinds and stays
    one sentence.
    """
    if purpose != TransportPurpose.FRIENDS:
        return OFFER_HOP_END
    if enabled:
        return OFFER_IN_EVERY_LINK if deliverable else OFFER_NOT_IN_THE_LINK
    return OFFER_WITHDRAWN_LAST_ON_THE_NODE if nothing_left_enabled else OFFER_WITHDRAWN


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
    a short pool anywhere on this node is a node that cannot carry the fleet it is being
    put in front of — usually refused outright, inside the transaction and with nothing
    committed, but only after the operator has pressed. Where every active user already
    holds a credential on that row nothing is minted and the move would commit, which is
    why ``POOL_SHORT_TO_SERVE`` states the ceiling rather than the refusal. The
    measurement is ``addresses.shortfalls_among``, over this node's own ENABLED rows,
    which are exactly the ones that become serving with it. A node that is already
    serving is asked nothing: it grants nobody anything by staying where it is.
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

    This is the whole of M9.3's hard rule. Every string below is chosen by something the
    TRANSPORT declares about itself, and none of them is chosen by which protocol it is
    — there is no name compared to anything here, in the template, or anywhere on the
    path between them. Ship a fifth protocol and its row writes itself; ship one that
    declares itself identified and the warning appears with no edit; retire one and the
    row says so, with nothing in this zone to change.

    The two conditions in ``delivery_note`` are not the same condition. A transport with
    no declared format serialises into nothing a user could consume at all; a transport
    with one that is not the base64 link serialises fine and is handed over in its own
    shape (``subscription_expressible``). Reporting the second as the first would tell the
    operator a protocol is unusable when it is merely not a link.
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
            else TRANSPORT_NOT_IN_THE_LINK
        ),
        exposure=(
            TRANSPORT_IDENTIFIED
            if meta.blocked_by_inspection
            else TRANSPORT_CAMOUFLAGED
        ),
        identified=meta.blocked_by_inspection,
        hop_note=None if meta.hop_expressible else TRANSPORT_NO_HOP,
        # THE REGISTRY'S OWN DECLARATION, asked through the one function in this zone
        # that asks it — no name is compared here, in the template, or anywhere between
        # them, which is the same rule the three strings above follow.
        address_note=(
            TRANSPORT_ADDRESS_PER_USER
            if addresses.spec_for(meta.name) is not None
            else None
        ),
        # M20, and the one cell on this screen that is about what the PANEL will do
        # rather than about what the protocol is. The consequence is this zone's
        # sentence and the cause is the transport's, joined here so the template still
        # prints one composed string and still cannot tell one protocol from another.
        retired_note=(
            f"{TRANSPORT_RETIRED} {meta.retired.reason}" if meta.retired else None
        ),
        why=TRANSPORT_WHY_IDENTIFIED if meta.blocked_by_inspection else None,
    )


# What the Keys screen says about users on one row whose material predates what the
# transport now declares — M23, and the whole of the panel's half of that finding.
#
# The situation is real and the owner has one: a transport gained a per-consumer value
# (the WireGuard family's per-pair pre-shared key), and a credential minted before that
# declaration does not carry it. The renderer refuses to build a configuration file for
# such a credential rather than hand out the node-wide key to a second person, so the
# download quietly stops producing a file for this node — while the tunnel those people
# already hold keeps working, because the node still authorises them.
#
# So the sentence says both halves, in that order: nothing is broken for them yet, and
# the repair is one button on this row. Without it the refusal is written in a place
# nobody reads — ``edge``, at the moment a user's client asks — and the operator's first
# notice is somebody reporting a download that gives them nothing.
#
# COUNTS AND NEVER NAMES. Which person holds pre-declaration material is a fact about a
# person on a screen that may not hold one, and the action is the same for all of them.
#
# In the panel's vocabulary (``user``) like every other constant in this module, and it
# names no protocol: what is missing is read from the transport's own declaration and
# never printed — a field name here would be this file knowing which protocol it is
# looking at, and would tell the operator something they cannot act on either way.
STALE_MATERIAL = (
    "material for {count} of the users on this row was minted before this protocol "
    "declared all of it, so no configuration file can be built for them on this node and "
    "their download returns nothing for it. What they already imported keeps working — "
    "the node still authorises them. Use \"rotate keys\" on this row: it re-mints what "
    "each of them holds, and nobody re-imports a link."
)


def stale_material(count: int) -> str | None:
    """The sentence for a row whose users cannot all be handed a configuration — M23.

    ``None`` for a row where every credential carries what its transport declares, which
    is every row on a fleet where nothing was minted before a declaration changed — so
    the cell exists only when there is something to do about it.
    """
    if not count:
        return None
    return STALE_MATERIAL.format(count=count)


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

    THE NODE-TRANSPORT ROW's ``secrets`` COLUMN IS NEVER READ HERE, and that is what
    keeps the fingerprint cell honest: it is computed from ``params``, the clear column,
    so the screen cannot show a node's key material even by accident.

    WHAT IS READ SINCE M23 is each CREDENTIAL's material, and only to count the ones that
    do not carry what their transport declares (``stale_material``). No value from it
    reaches this function's result — the credential loop produces an integer — and no
    value from it reaches the template, which is handed a sentence. It is read because
    the alternative was the operator learning about it from a user whose download stopped
    working, which is how the owner's own leaf was found.
    """
    installed = discover()
    held_by = {}
    for node_transport_id, subject, secrets in (
        await session.execute(
            select(Credential.node_transport_id, Credential.subject, Credential.secrets)
        )
    ).all():
        # As ``edge`` sees a consumer's material: the credential's own secrets with the
        # subject under the name the contract requires (``edge.node.Credential``). The
        # tunnel address is not overlaid and does not need to be — it is not key
        # material, so no ``KeySpec`` names it and nothing below looks for it.
        held_by.setdefault(node_transport_id, []).append(
            {**json.loads(secrets), "subject": subject}
        )
    counted = {row_id: len(held) for row_id, held in held_by.items()}

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
                    # The same set the replace form draws its boxes from — M23 widened
                    # that to every field an operator may supply, and this flag decides
                    # whether the button to it exists, so the two are read from one
                    # answer. A row whose every parameter is minted still offers nothing.
                    replaceable=bool(
                        meta and transports.supplied_params(row.transport_name)
                    ),
                    stale_material=(
                        stale_material(
                            sum(
                                1
                                for held in held_by.get(row.id, ())
                                if keymaterial.missing_client_material(
                                    meta.key_material, held
                                )
                            )
                        )
                        if meta and for_friends
                        else None
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


def refused_under_boxes(names: list[str]) -> str:
    """What the TOP of a dialog says when the refusal itself is under a box below it.

    M17.2's acceptance. The enable dialog is taller than a laptop's window — a list of
    what the node already runs, then a group of boxes per transport — and a 422 re-renders
    it scrolled back to the top, because the swap replaces the scrolling element. The pool
    box is the LAST field, so its refusal arrived correctly styled, correctly worded and
    entirely off screen: the operator read an unchanged dialog and pressed again. This
    project has been bitten by a refusal nobody sees before (M9, the banner slot cleared
    on htmx:afterRequest), which is why an awkwardness is being treated as a failure.

    ``app.js`` also moves focus to the refused control, which scrolls it into view. This
    is the half that does not depend on that: a line in the operator's eyeline saying the
    submission was refused and where the reason is.

    IT NAMES THE BOXES AND REPEATS NO MESSAGE. A second copy of the sentence would be two
    places to change it and two places for it to drift; what the top of a dialog owes the
    operator is that something was refused and where to look. Names arrive with their
    group prefix stripped — that prefix is markup, not a parameter — and sorted, so two
    refusals about the same boxes read identically.

    Singular and plural, for the same reason ``no_room_for_another_user`` counts its own
    list: this sentence is read directly above the thing it is describing.
    """
    boxes = sorted({name.rsplit("-", 1)[-1] for name in names})
    if len(boxes) == 1:
        return (
            f"Nothing was enabled. The reason is under {boxes[0]}, further down this "
            "dialog."
        )
    return (
        "Nothing was enabled. The reasons are under these boxes, further down this "
        f"dialog: {', '.join(boxes)}."
    )


async def nothing_left_enabled_on(session: AsyncSession, node_id: str) -> bool:
    """Whether an apply on this node would have anything at all to push — M18.1's review.

    The question the two summaries below and ``_standing`` all turn on, asked of the
    database rather than of a collection because both callers ask it AFTER their own
    mutation committed: the withdraw route has just flipped a flag and the remove route
    has just deleted the row, and an in-memory list taken before either is a list of what
    used to be true.

    Enabled rows of EVERY purpose count, hop ends included: ``apply.render_for_node``
    renders both, so one live hop end is enough to give the apply something to push and
    the sentences below stay as they were.
    """
    remaining = await session.execute(
        select(NodeTransport.id)
        .where(NodeTransport.node_id == node_id)
        .where(NodeTransport.enabled.is_(True))
        .limit(1)
    )
    return remaining.first() is None


def withdrawal_summary(node: str, transport: str, *, nothing_left_enabled: bool) -> str:
    """What withdrawing a transport does, and — as loudly — what it does not do.

    Here rather than in the route for the reason ``tear_down_summary`` is: this is a
    judgement about what is still true of the fleet, and routes in this codebase do
    wiring. The second sentence is ``nodes.set_transport_enabled``'s own warning made
    operator-facing: disabling changes what the control plane DELIVERS, not what the
    host is running. A person who already holds a fetched configuration keeps
    connecting until the node is applied without them, and an operator who reads
    "withdrawn" as "stopped" has been told the opposite of what happened.

    THE SECOND SENTENCE USED TO END ON AN APPLY THAT IS REFUSED — M18.1's review, and it
    was the worst place in the console for it to be wrong. Withdrawing the node's last
    enabled row leaves ``render_for_node`` with nothing, so the apply this sentence sent
    the operator to answers "nothing to push" and the host keeps serving the row — which
    still authorises every friend who holds a credential on it, since a withdrawal mints
    nothing away. The only way out is to offer a transport there again, so the sentence
    says that, and says what it costs: the offered row goes back into every user's link.
    """
    if not nothing_left_enabled:
        return (
            f"{transport} withdrawn on {node} — out of every user's link at their next "
            "refresh. The node is still configured to serve it: apply it to stop that."
        )
    return (
        f"{transport} withdrawn on {node} — out of every user's link at their next "
        f"refresh. It was the last transport enabled on {node}, so an apply now has "
        "nothing to push and is refused: the node keeps serving it, and everyone holding "
        f"a credential on it, until a transport on {node} is offered again — back into "
        "every user's link — and applied."
    )


def removal_summary(node: str, transport: str, *, nothing_left_enabled: bool) -> str:
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

    AND ON A NODE WITH NOTHING LEFT ENABLED that action is refused, exactly as it is for
    a withdrawal — M18.1's review. The verb differs from the withdrawn twin's because the
    row differs: a withdrawn row is still there to be offered again, a removed one is
    gone, so what is owed here is enabling a transport rather than offering one back.
    """
    if not nothing_left_enabled:
        return (
            f"{transport} removed from {node} — out of every user's link at their next "
            "refresh, and the material minted for it is gone with it. Its listening port "
            "and its config name on this node are free again. The node is still "
            "configured to serve it: apply it to stop that."
        )
    return (
        f"{transport} removed from {node} — out of every user's link at their next "
        "refresh, and the material minted for it is gone with it. Its listening port "
        f"and its config name on this node are free again. It was the last transport "
        f"enabled on {node}, so an apply now has nothing to push and is refused: the "
        f"node keeps serving it until a transport on {node} is enabled and applied."
    )


def offer_summary(node: str, transport: str, *, deliverable: bool) -> str:
    """What offering a transport again costs the people on it: nothing.

    The other half of criterion 3, and the half that has to say "nobody does anything":
    every active user is granted material on it here, and their link does not move.

    ON A TRANSPORT THAT IS NOT A LINK the first half of that was false — M20's acceptance.
    The grant still happens and the node is still told to serve it; what does not change
    is the base64 document, because it is the v1 URI list and this protocol is not one.
    Same fact as the row's own sentence (``OFFER_NOT_IN_THE_LINK``) and deliberately not
    the same words: this one is read after the press and has to say what just happened.

    It says the material is MINTED rather than that nothing reaches anybody, because
    something does: the same token answers with this friend's configuration file, so the
    honest report of this press is that everyone was granted and the link did not move.
    """
    if not deliverable:
        return (
            f"{transport} offered again on {node} — every user is granted material on it, "
            "and the subscription link itself does not change: this transport is a config "
            "file, which a user's client gets from that same link by asking for it."
        )
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
    nodes active, active users, hops established, transports serving. Each is a fact
    about the FLEET. How many friends exist is not a record of what any of them did.

    THE FIRST KICKER WAS "nodes online" AND COUNTED NEITHER — M18's acceptance. The value
    is the number of nodes in the ACTIVE state, which is an operator-settable column: a
    node moved there by hand, never applied and serving nobody, counted towards "online",
    and acceptance watched the figure go 1 → 2 by flipping a state. Online additionally
    claims something this screen is built not to ask — it renders with every host
    unreachable and touches no network, which is the whole reason it paints instantly
    (see ``drift_of``). So the label now names what it counts, and the state it names is
    the one the Nodes screen's own column shows and the one ``NodeState.serving()``
    admits to a subscription. What each node is actually running stays where it already
    is and is a different question: the drift cell, per node, on that screen.

    AND THE FOURTH KICKER WAS "transports enabled" AND COUNTED SOMETHING NARROWER —
    M20's acceptance, which is the identical defect one card over. The value has always
    been ``nodes.serving_transports``: distinct protocols enabled for friends ON A NODE
    THAT IS SERVING. The walk watched it read 0 with four rows at ``enabled=true``,
    because every node holding them was still draft — a true number whose meaning was
    nowhere on the screen. The label now names the state, exactly as "nodes active" and
    "hops established" beside it do, and the zero it shows is then the same zero the card
    to its left is showing for the same reason.
    """
    rows = await node_rows(session)
    people = await friend_rows(session)
    hops = await relay.list_hops(session)

    in_state = [row for row in rows if row.state == NodeState.ACTIVE]
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
    # Distinct protocols a user could be routed onto right now: enabled, friend-facing,
    # and on a node in a state that reaches a subscription at all. NAMED for what it
    # measures since M20's acceptance, because the kicker beside it now says the same
    # word — see this function's own docstring.
    serving = {
        row.transport_name
        for row in await nodes.serving_transports(session)
        if row.purpose == TransportPurpose.FRIENDS
    }
    installed = discover()
    # What the panel would let the operator enable today — services/transports.py's own
    # answer, not a name compared here. It is a SUBSET of what the image ships: a
    # transport the registry has retired is not proposed (M20), and neither is one that
    # serialises into no subscription shape. "of 4 this image ships" beside a value of 1
    # therefore read as "three left to enable" when only two were — the same sentence
    # the Transports screen's retired row exists to stop the operator hunting for, on the
    # screen they meet first.
    offerable = transports.offerable_transports()

    return Overview(
        doubts=fleet_doubt(rows),
        limit=COUNTERS_COUNT_CONFIGURATION,
        stats=[
            Stat(
                kicker="nodes active",
                value=len(in_state),
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
                kicker="transports serving",
                value=len(serving),
                # "OF 4 this image ships" read as a denominator of the value above it, so
                # a fleet serving all four beside "3 can be enabled" looked like an
                # arithmetic error — M20's acceptance. It never was one: the value is a
                # count of the FLEET and both figures here are counts of the IMAGE, which
                # is what dropping the "of" says.
                meta=(
                    f"{len(installed)} in this image, "
                    f"{len(offerable)} can be enabled"
                    if len(offerable) != len(installed)
                    else _plural(len(installed), "transport", "in this image")
                ),
            ),
        ],
        nodes=rows,
        friends=people,
    )


# What a probe can never establish, said in the sentence that reports the good news —
# M22.2. The probe reads a node's containers and its socket table over SSH; it does not
# dial the node, it cannot ask whether a peer completed a handshake (``edge.health
# .listening`` says why that is refused rather than unimplemented), and what it finds on
# a port is SOMETHING holding it rather than provably our container.
#
# It is on the healthy answer and not on the failing ones deliberately. A failure is
# already a narrower claim than the operator wants; it is the word "serving" that was
# read as "working", and this is the sentence that word lived in.
#
# IT NAMES THE FIREWALLS SINCE M23, round 2, and that sentence was bought on the real
# leaf: a transport was enabled on a port the host's ufw did not allow, the node read
# "active / in sync", this probe read "is listening", and the client sent 12 479 bytes and
# received none. Every reading was true. "Not dialled from outside" was already the whole
# of it in principle, and in practice the operator read it as a formality — so the two
# layers that actually sit between a bound socket and a user are named, because a socket
# bound behind a closed firewall is exactly what this probe must not be read as
# disproving. Neither layer is one this control plane can see or change: the host's is
# opened by ``scripts/node-bootstrap.sh --port``, and the provider's is in their console.
WHAT_A_PROBE_CANNOT_SEE = (
    "Read on the node itself, not dialled from outside — so this is not proof that "
    "anyone can connect. A port bound behind a closed host firewall, or behind a closed "
    "security group at the provider, reads from here exactly like this one does."
)


def health_summary(name: str, health: schemas.HealthResponse) -> str:
    """One node's probe result as a sentence the console can put on screen.

    Composed here rather than in the route because it is the same judgement the
    pre-redesign panel's ``panel/health.html`` made in markup, and the console needs it
    as TEXT: a probe answers into a persistent notice when the node is fine and into a
    persistent failure banner when it is not, and neither carries a template. That
    fragment went with the page in M9.6; this function is what carried its reading across.

    Note what it cannot say, because the value does not exist upstream: no client
    count, no address, no traffic figure. Health means "is this node serving what we
    told it to", and the charter's no-logging rule covers this screen like every other.

    ``drifted`` and ``stale`` get their own sentences and are not collapsed into one:
    they are different faults with different repairs, and M1 found a node in the field
    reporting no drift while its daemon had never read the file it was reporting about.

    AND THE HEALTHY SENTENCE NO LONGER SAYS "SERVING" — M22.2. It said *"realhost is
    serving amneziawg, vless-ws-tls"* about a node where one of the two was exiting 23
    every second with nothing on its port, and the operator stopped looking, which is
    what the charter treats as the failure that hurts most. The verb now names what was
    actually established and nothing beyond it, and it is a DIFFERENT verb depending on
    how much was established: "is listening for" where the port was checked and held,
    "is running" where it could not be checked. A sentence that reads the same either
    way is a sentence that means the weaker of the two, always.
    """
    if not health.reachable:
        return f"{name} could not be reached — {health.detail or 'no reason was reported'}"

    if health.healthy:
        return _serving_summary(name, health)

    reason = health.detail or "no reason was reported"
    parts = [f"{name} answered but is not serving — {reason}."]
    if health.restarting:
        parts.append(
            "A container that keeps restarting is up in the engine's own reading and "
            "carrying nothing: it starts, fails and starts again. Applying the same "
            "configuration will not change that — what the container itself printed on "
            "the node says why it will not start."
        )
    if health.not_listening:
        parts.append(
            "Its container is up and nothing holds the port that transport was given, "
            "so there is nothing on the node for anyone to reach."
        )
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


def _serving_summary(name: str, health: schemas.HealthResponse) -> str:
    """The good-news sentence, which says exactly how much good news it is.

    Three shapes, because there are three states worth telling apart and one word for
    all of them is the defect M22 is about. Everything checked and holding; some running
    transports whose port nobody could ask about; and nothing enabled at all, which is
    not a fault and never was.
    """
    if not health.running:
        return f"{name} answered, and has no transport enabled to serve"

    parts = []
    if health.listening:
        each = "each container is" if len(health.listening) > 1 else "its container is"
        parts.append(
            f"{name} is listening for {', '.join(health.listening)} — {each} up and "
            f"something holds its port."
        )
    if health.unchecked_ports:
        # The weaker claim, in its own sentence and in its own verb. These containers are
        # up on the configuration we pushed and that is the whole of what is known about
        # them: nothing asked whether anything is bound, so nothing here says it is.
        subject = "It is also running" if health.listening else f"{name} is running"
        parts.append(
            f"{subject} {', '.join(health.unchecked_ports)}, whose port was not checked."
        )
    parts.append(WHAT_A_PROBE_CANNOT_SEE)
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


# --- M23: the key a node was registered without -------------------------------

def ssh_key_set(node_name: str) -> str:
    """The toast for a stored SSH key — naming the step the operator still owes.

    Same shape and same reason as ``resolver_set`` above: storing the key changes the
    record and touches no host, and this is the moment an operator who registered a node
    without one is most likely to believe the node is now working.
    """
    return f"ssh key stored for {node_name} — apply it to push its configuration"


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


# What ENABLING a transport will do, at the moment the operator decides to — M20's
# acceptance, round 2. The enable dialog's footer said one of these for every protocol on
# it ("Enabling puts this protocol into every active user's link at their next refresh
# and asks nothing of anybody"), and for a transport whose configuration is a FILE that
# is false in both halves: it is in nobody's link, and somebody does have to ask for it
# in the shape it comes in.
#
# WORSE PLACED THAN THE ROW SENTENCES the same acceptance corrected (``OFFER_IN_EVERY
# _LINK`` and its sibling), which is why it is here rather than left for a later pass: a
# row's standing is read afterwards, and this is read while the operator is choosing. An
# operator who enables a config-file transport on this sentence's word walks away
# believing every friend has it.
#
# The second arm may not say the friend cannot have it, and may not say they simply get
# it — the same two failures ``OFFER_NOT_IN_THE_LINK`` names at length, and the same
# wording is used here so the operator reads one fact in both places. Nothing in this
# panel yet hands the operator the URL that asks for the file shape; closing that is its
# own milestone and is not what this sentence may promise.
#
# Chosen by ``subscription_expressible`` — whether the protocol rides in the base64 LINK
# — and never by a name, like every other string in this module.
ENABLING_IN_EVERY_LINK = (
    "Enabling puts this protocol into every active user's link at their next refresh and "
    "asks nothing of anybody."
)
ENABLING_NOT_IN_THE_LINK = (
    "Enabling grants every active user material on this protocol and puts it in nobody's "
    "link: this transport is a config file, and a user's client gets it from that same "
    "link only by asking for that shape."
)


def enabling_notes(offered: list[str]) -> dict[str, str]:
    """What enabling each offered transport does, keyed by transport.

    Keyed the way ``pool_boxes`` and ``tuning`` are, so the dialog prints it inside the
    group it is about and the operator reads the sentence for the protocol they chose
    rather than one sentence stretched over all of them.

    TWO ARMS AND NOT THREE, unlike the Transports screen's own delivery note: this list
    is ``offerable_transports``, so every name in it declares a format a client can
    consume — a transport that declares none is not proposed here, and the enable service
    refuses it outright. The question left is only which SHAPE, which is what
    ``subscription_expressible`` answers.
    """
    installed = discover()
    return {
        name: (
            ENABLING_IN_EVERY_LINK
            if installed[name].subscription_expressible
            else ENABLING_NOT_IN_THE_LINK
        )
        for name in offered
    }


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
    say is that the size is a ceiling for the people who are not here yet — a ceiling
    this milestone also ships the means to raise, which is why that branch names where.
    "Can ever serve" was the wrong word for it: the first-run operator is the one least
    able to know the number is not permanent, and the likeliest to oversize wildly or put
    the whole thing off because of it.

    It does not repeat that a smaller pool is refused — ``POOL_BOX_HINT``, which this is
    appended to, has already said so.
    """
    if people == 0:
        return (
            "No user is active yet, so nothing takes an address from it today — the "
            "size is the ceiling on how many this node serves on this protocol, until "
            "you raise it on Keys & configs, under replace params."
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
def no_room_for_another_user(pools: int) -> str:
    """The sentence above the list, agreeing with the list — M17.2's acceptance.

    It was a constant reading "one of those pools is full:" whatever followed it, and two
    serving rows with no room printed two pools under it. A count is the one thing this
    sentence can get wrong and the operator can check: the fleet in this product is one
    person's, and a sentence that miscounts the thing directly beneath it is the kind of
    seam that makes them doubt the numbers in it — which are the whole content of the
    lines that follow.
    """
    which = "one of those pools is" if pools == 1 else f"{pools} of those pools are"
    return (
        "There is no room for another user yet. A user is given an address on every "
        f"transport that serves them, and {which} full:"
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
