"""Creating nodes and enabling transports on them — backlog item 7.

WHAT: the operator's write operations against the node registry, plus the read
      helpers the renderer and the panel use.
WHY:  "add an exit country" and "enable a protocol" are the two operations the
      charter's criteria 2 and 3 are written in terms of, and both have to be data
      changes rather than code changes.
HOW:  every transport-specific decision is delegated. Parameters are validated by
      the transport's own ``Params`` model, key material is minted from the
      transport's own declarations, and the transport's name is stored as opaque
      text. There is no ``if transport_name ==`` in this module, and the tests
      assert that for the whole zone.
"""

import json
import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict, DomainError, NotDeliverable, NotFound
from control.app.models import Node, NodeState, NodeTransport, TransportPurpose
from control.app.services import keymaterial
from edge.egress import Egress
from edge.node import NodeView
from edge.registry import KeyScope, discover, profile

logger = logging.getLogger(__name__)


# --- reading ----------------------------------------------------------------

async def get_node(session: AsyncSession, node_id: str) -> Node:
    node = await session.get(Node, node_id)
    if node is None:
        raise NotFound("no such node")
    return node


async def list_nodes(session: AsyncSession) -> list[Node]:
    """Every node, newest last, so the panel's order is stable across reloads."""
    result = await session.execute(select(Node).order_by(Node.created_at, Node.id))
    return list(result.scalars().unique())


async def get_node_transport(session: AsyncSession, node_transport_id: str) -> NodeTransport:
    node_transport = await session.get(NodeTransport, node_transport_id)
    if node_transport is None:
        raise NotFound("no such node transport")
    return node_transport


async def serving_transports(session: AsyncSession) -> list[NodeTransport]:
    """Every node-transport a friend may legitimately be routed onto.

    One query, one definition. This is what a subscription is built from, and the
    filter is the whole safety property: a node that is draft, degraded or retired
    must never appear in anyone's configuration, because being routed onto a
    half-configured node produces a bug report about the client.
    """
    result = await session.execute(
        select(NodeTransport)
        .join(Node)
        .where(NodeTransport.enabled.is_(True))
        # Friend-facing rows only. An entry↔leaf hop (item 16) is a transport enabled
        # on a node and would otherwise qualify — and a friend handed the hop would be
        # routed straight past the entry node the whole topology exists to hide behind.
        .where(NodeTransport.purpose == TransportPurpose.FRIENDS)
        .where(Node.state.in_(NodeState.serving()))
        .order_by(Node.location_label, Node.name, NodeTransport.transport_name)
    )
    return list(result.scalars().unique())


def node_view(node: Node) -> NodeView:
    """Project a database row into the pure value object ``edge`` renders from.

    The boundary in one function: everything below this line in the call stack is
    pure, has no session, and cannot lazily load anything.
    """
    return NodeView(
        id=node.id,
        address=node.address,
        location_label=node.location_label,
        display_name=node.name,
    )


# What a node may do with the packets one of its transports decrypts, by the purpose the
# row already records — M14.3. A TABLE rather than a branch: the question is topology
# ("who is on the far end of this tunnel"), which is exactly what ``purpose`` is, and
# `control` still compares no transport name to a literal.
#
# The two answers are not symmetric in how they fail, and that is why this is written
# down rather than assumed. A friend-facing tunnel with no exit produces a friend who
# says at once that nothing loads. A hop that exits locally produces a friend in Russia
# whose traffic leaves in Russia, with two active nodes and a live hop on every screen.
#
# WHICH OF THE TWO RELAY ENTRIES BELOW IS LIVE TODAY: neither, and they are here on
# purpose. ``apply.render_for_node`` never asks this function about a hop end — it
# recognises a relay purpose first and dispatches the pair to ``relay.render_end``, which
# reaches ``edge.relay.render_hop``, and THAT is where a hop's ``NONE`` actually comes
# from. So the guarantee in force is ``render_hop``'s own, and these two rows are a
# forward guard: the day something renders a hop end through the ordinary server path,
# the answer is already decided and it is the safe one. They are unreachable, not dead —
# do not delete them because the call graph says nothing reaches them.
_EGRESS: dict[str, Egress] = {
    TransportPurpose.FRIENDS: Egress.LOCAL,
    TransportPurpose.RELAY_ENTRY: Egress.NONE,
    TransportPurpose.RELAY_LEAF: Egress.NONE,
}


def egress_for(node_transport: NodeTransport) -> Egress:
    """The egress policy this row's purpose implies.

    Unknown purposes fall to ``NONE`` rather than raising, and that is the fail-closed
    rule rather than laziness: a purpose this table has not been taught about is a
    topology nobody has decided the exit policy for, and the safe answer to an undecided
    question is no exit.

    Sending traffic INTO a hop rather than out of a node is the third answer, and it is
    M3's: it belongs in this table, next to these two, and needs no new mechanism.
    """
    return _EGRESS.get(node_transport.purpose, Egress.NONE)


def render_params(node_transport: NodeTransport) -> dict:
    """A transport's full parameters, secrets merged back in for rendering.

    The split between ``params`` and ``secrets`` exists for storage, not for
    rendering — the renderer needs all of it. Merged here, in one place, so no
    service assembles it by hand and forgets the secret half (which produces a
    config with an empty private key: valid JSON, dead node).

    The result contains decrypted secrets. It goes to a renderer and to the node,
    and it must never reach a log record, a template context or an exception
    message.
    """
    return {**node_transport.params, **json.loads(node_transport.secrets)}


# --- writing ----------------------------------------------------------------

async def create_node(
    session: AsyncSession,
    *,
    name: str,
    address: str,
    location_label: str,
    ssh_host: str | None = None,
    ssh_port: int = 22,
    ssh_user: str = "root",
    ssh_private_key: str | None = None,
) -> Node:
    """Register a node. It starts in ``draft`` and carries no traffic yet.

    Draft rather than active is deliberate: a node exists as a record before it is
    configured, and a record that defaulted to active would put an unconfigured host
    into every friend's subscription the moment it was typed in.
    """
    existing = await session.execute(select(Node).where(Node.name == name))
    if existing.scalars().first() is not None:
        raise Conflict(f"a node named {name!r} already exists")

    node = Node(
        name=name,
        address=address,
        location_label=location_label,
        state=NodeState.DRAFT,
        # Defaults to the routable address, since the common case is one host doing
        # both jobs — but it is a separate column because an entry node fronting a
        # leaf is reached at a different address than the one clients dial.
        ssh_host=ssh_host or address,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        ssh_private_key=ssh_private_key,
    )
    session.add(node)
    await session.commit()
    logger.info("node created: %s", node.id)
    return node


async def enable_transport(
    session: AsyncSession,
    *,
    node_id: str,
    transport_name: str,
    params: dict,
) -> NodeTransport:
    """Enable one transport on one node, minting whatever material it declared.

    The order of operations matters and is the reason this is one function rather
    than three: material is minted BEFORE validation, then validation runs over the
    merged result. A transport whose ``Params`` requires a private key cannot be
    validated without one, so validating the operator's input alone would reject
    every correct request.
    """
    installed = discover()
    if transport_name not in installed:
        # Names the installed set, which is safe: it is a property of our own image,
        # not of any node or friend.
        raise NotFound(
            f"no transport named {transport_name!r} is installed "
            f"(have: {', '.join(sorted(installed))})"
        )

    meta = installed[transport_name]

    # Refused out loud rather than silently omitted later. The charter's amendment A
    # and backlog item 7 S2a: a transport a friend cannot receive AT ALL would produce
    # a friend whose config is quietly one node short, and they would have no way to
    # notice.
    #
    # The condition moved with item 27, and the move is the point. It used to be "not
    # expressible in the v1 URI list", because that was the only shape delivery could
    # produce — so a transport whose configuration is a file was refused for a reason
    # that was about US, not about it. Now that the delivery endpoint hands out files
    # too, the honest question is whether the transport declares ANY friend-facing
    # format. One that declares none still cannot reach a friend, and is still refused.
    if not meta.subscription_formats:
        raise NotDeliverable(
            f"transport {transport_name!r} declares no format a friend's client can "
            "consume, so enabling it would deliver an incomplete subscription. "
            "Refusing rather than shipping a silent gap."
        )

    node = await get_node(session, node_id)

    duplicate = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.transport_name == transport_name)
    )
    if duplicate.scalars().first() is not None:
        raise Conflict(f"{transport_name!r} is already enabled on node {node.name!r}")

    transport = profile(transport_name)
    minted = keymaterial.mint(meta.key_material, KeyScope.NODE)

    # Operator input, then generated public values. Generated material wins on a
    # collision: an operator must not be able to supply their own "public key" for
    # a keypair whose private half we just minted.
    merged = {**params, **minted.params, **minted.secrets}
    try:
        validated = transport.validate(merged)
    except ValidationError as exc:
        # Converted to a domain error rather than allowed to escape. A Pydantic
        # ValidationError out of a service becomes an unhandled 500, which tells the
        # operator "internal error" for what is really "your port is out of range" —
        # and a 500 also means the message they need is only in the server log.
        #
        # Only the transport's own field errors are surfaced, never the input values:
        # the merged mapping at this point contains the private key we just minted.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise DomainError(
            f"transport {transport_name!r} rejected these parameters — {problems}"
        ) from exc

    # Split the validated result back apart for storage. Driven by which keys the
    # generator produced as secret, so a transport's own declaration decides what is
    # encrypted — this function never judges a value by its name.
    secret_keys = set(minted.secrets)
    node_transport = NodeTransport(
        node_id=node.id,
        transport_name=transport_name,
        params={k: v for k, v in validated.items() if k not in secret_keys},
        secrets=json.dumps({k: v for k, v in validated.items() if k in secret_keys}),
        enabled=True,
    )
    session.add(node_transport)
    await session.commit()
    logger.info("transport enabled on node %s", node.id)
    return node_transport


async def set_transport_enabled(
    session: AsyncSession, *, node_transport_id: str, enabled: bool
) -> NodeTransport:
    """Turn one node's transport on or off for friends — charter criterion 3.

    The criterion is "a transport is enabled from the panel and arrives in every
    friend's subscription at the next refresh". Its other half is what makes it a
    control and not just an addition: turning the transport back off has to remove it
    from every friend's subscription again, with nobody touching their device. Until
    this function existed, ``NodeTransport.enabled`` was written ``True`` at creation
    and never changed by any route, so only the positive half was expressible.

    Enabling grants material to every active friend, exactly as enabling a transport
    for the first time does — otherwise a transport switched off and on again would
    come back only for friends created in between.

    Idempotent: setting the value it already has does nothing and does not re-grant.
    A retried click is not an event.

    **What this does NOT do, and must not be reported as doing:** disabling changes
    what `control` DELIVERS, not what a node is running. A friend who already holds a
    fetched config keeps connecting until the node is re-applied without them. Use
    it to withdraw a protocol from the fleet's offer; use revocation (item 9) to
    withdraw a person's access.
    """
    node_transport = await get_node_transport(session, node_transport_id)

    # A hop end is not an offer to friends, and switching one off is not a delivery
    # change — it is half a tunnel that stops completing a handshake while both ends
    # still look configured. Refused by pointing at the operation that removes both.
    if node_transport.purpose != TransportPurpose.FRIENDS:
        raise Conflict(
            "this transport is one end of an entry-to-leaf hop, not something "
            "friends are offered. Switching one end off would leave a tunnel that "
            "no longer completes while both ends still look configured — remove the "
            "hop instead (DELETE /api/hops/{node_transport_id})."
        )

    if node_transport.enabled == enabled:
        return node_transport

    node_transport.enabled = enabled
    await session.commit()
    logger.info("node-transport %s enabled -> %s", node_transport.id, enabled)

    if enabled:
        # Same deferred import, same cycle, same reasoning as ``set_node_state``.
        from control.app.services import friends  # noqa: PLC0415

        for friend in await friends.list_friends(session):
            if friend.is_active:
                await friends.grant_everywhere(session, friend)
        await session.commit()

    return node_transport


async def set_node_state(
    session: AsyncSession, *, node_id: str, state: NodeState, detail: str | None = None
) -> Node:
    """Move a node between states, recording why when it is not good news.

    The only way state changes. Centralised so that "degraded" always carries a
    reason for the operator — a node sitting in degraded with no explanation is a
    node nobody fixes.
    """
    node = await get_node(session, node_id)

    # A no-op is allowed and does nothing, so a retry after a failed apply is safe.
    #
    # ``!=``, never ``is not``. This line WAS an identity check, and it was always true:
    # the column handed back a plain ``str`` and never the ``NodeState`` singleton, so
    # the no-op branch never fired and a second failed apply was refused
    # ``degraded -> degraded``. ``apply._record_failure`` swallows that Conflict by
    # design, so the node kept the FIRST failure's reason and the operator retrying was
    # shown the error they had already fixed (M4.5). The column is ``EnumText`` now and
    # does hand back the member, but the comparison stays an equality: what this asks is
    # "is this the same state", which is never a question about object identity.
    if state != node.state and state not in NodeState.allowed_from(node.state):
        raise Conflict(
            f"a node cannot go from {node.state} to {state}. "
            f"From {node.state} it may become: "
            f"{', '.join(NodeState.allowed_from(node.state)) or 'nothing — this state is final'}"
        )

    became_serving = state in NodeState.serving() and node.state not in NodeState.serving()

    node.state = state
    # ``==`` for the same reason as above: a caller handing this the raw string a route
    # parsed would otherwise silently drop the operator's explanation on the floor.
    node.state_detail = detail if state == NodeState.DEGRADED else None
    await session.commit()
    logger.info("node %s state -> %s", node.id, state)

    if became_serving:
        # THE moment charter criterion 2 depends on. A node becoming serving must hand
        # a credential to every existing friend, or their subscription resolves to a
        # fleet that no longer includes the node they were supposed to be moved onto —
        # and the promise is that a replacement node requires no action from any user.
        #
        # It has to happen here rather than only when a transport is enabled: a
        # transport is normally enabled while the node is still a draft (it has not
        # been configured yet), so at that point there is nothing serving to grant.
        # Getting this wrong is silent — every friend simply gets an empty
        # subscription — which is why the ordering has its own test.
        #
        # Imported inside the function to break a cycle: ``friends`` imports this
        # module for ``serving_transports``. A deferred import is the honest fix here;
        # the alternative is a third module that exists only to hold one call.
        from control.app.services import friends  # noqa: PLC0415

        for friend in await friends.list_friends(session):
            if friend.is_active:
                await friends.grant_everywhere(session, friend)
        await session.commit()

    return node
