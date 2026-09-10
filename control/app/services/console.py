"""What the redesigned console puts on screen, and nothing more.

WHAT: the Overview's four stat cards, the node rows they summarise, the friend rows
      the Users screen lists, the hop rows the Hops screen lists, and the capability
      row the Transports screen lists per protocol this image ships.
WHY:  the design (``design/README.md``) drew four cells that measure PEOPLE —
      "throughput now", "last seen", node "load", and a whole Traffic screen. The
      charter's non-goals forbid every one of them: *"No traffic logging, no DNS
      logs, no per-user analytics. Not 'off by default' — absent, so there is nothing
      to seize or subpoena."* ``docs/decisions.md`` decision 6 replaced them with
      facts the control plane already holds, and this module is where that decision
      becomes code — so there is one file to read to see what the console may know.
HOW:  every figure here is derived from configuration rows: node states, credential
      grants, applied digests. Nothing counts an event, nothing has a clock in it
      except ``created_at`` on a row the operator themselves created, and no function
      in this module could be extended into a per-connection figure without adding a
      column that ``test_no_model_records_anything_about_a_connection`` would refuse.

The one figure that looks like a measurement and is not: ``nodes_served``. It counts
the credentials WE minted for a friend against the node-transports currently serving —
"is this person covered", a property of our own configuration. It does not move when
they connect, it does not move when they do not, and it is identical for a friend whose
device is in a drawer.
"""

import dataclasses
import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.api import schemas
from control.app.errors import NotFound
from control.app.models import (
    Friend,
    Node,
    NodeState,
    Subscription,
    TransportPurpose,
)
from control.app.services import apply, friends, nodes, relay
from edge.bootstrap import node_stack
from edge.registry import TransportMeta, discover

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


@dataclasses.dataclass(frozen=True, slots=True)
class Stat:
    """One card on the Overview: a kicker, a number, and a line of context."""

    kicker: str
    value: int
    meta: str


@dataclasses.dataclass(frozen=True, slots=True)
class TransportChip:
    """One transport enabled on a node, as the Nodes screen tags it.

    ``name`` is whatever the transport declared about itself — the console compares it
    to nothing, and the template that renders these prints it without ever naming one.
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
    why: str | None


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

    applied = {
        row.transport_name: row.applied_digest
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
                    name=row.transport_name,
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

    This is the whole of M9.3's hard rule. Three of the strings below are chosen by a
    boolean the TRANSPORT declares about itself, and none of them is chosen by which
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
        why=TRANSPORT_WHY_IDENTIFIED if meta.blocked_by_inspection else None,
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

    Composed here rather than in the route because it is the same judgement the old
    panel's ``panel/health.html`` made in markup, and the console needs it as TEXT: a
    probe answers into a toast when the node is fine and into a persistent banner when
    it is not, and neither carries a template.

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
