"""What the redesigned console puts on screen, and nothing more.

WHAT: the Overview's four stat cards, the node rows they summarise, and the friend
      rows the Users screen lists.
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

from control.app.models import Friend, Node, NodeState, Subscription, TransportPurpose
from control.app.services import apply, friends, nodes, relay
from edge.bootstrap import node_stack
from edge.registry import discover

logger = logging.getLogger(__name__)

# What the drift cell can say. Strings rather than an enum because they are read only
# by a template and by the operator; a state machine here would be ceremony.
IN_SYNC = "in sync"
NEVER_APPLIED = "never applied"
NOTHING_ENABLED = "nothing enabled"
UNRENDERABLE = "cannot render"


@dataclasses.dataclass(frozen=True, slots=True)
class Stat:
    """One card on the Overview: a kicker, a number, and a line of context."""

    kicker: str
    value: int
    meta: str


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
