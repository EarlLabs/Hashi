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
from control.app.models import Node, NodeState, NodeTransport
from control.app.services import keymaterial
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
    # and backlog item 7 S2a: a transport that cannot be expressed in the v1
    # subscription would produce a friend whose config is quietly one node short,
    # and they would have no way to notice.
    if not meta.subscription_expressible:
        raise NotDeliverable(
            f"transport {transport_name!r} cannot be expressed in the subscription "
            "format friends use, so enabling it would deliver an incomplete "
            "subscription. Refusing rather than shipping a silent gap."
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


async def set_node_state(
    session: AsyncSession, *, node_id: str, state: NodeState, detail: str | None = None
) -> Node:
    """Move a node between states, recording why when it is not good news.

    The only way state changes. Centralised so that "degraded" always carries a
    reason for the operator — a node sitting in degraded with no explanation is a
    node nobody fixes.
    """
    node = await get_node(session, node_id)
    became_serving = state in NodeState.serving() and node.state not in NodeState.serving()

    node.state = state
    node.state_detail = detail if state is NodeState.DEGRADED else None
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
