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

import asyncssh
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import (
    Conflict,
    DomainError,
    NotDeliverable,
    NotFound,
    ParamsRefused,
)
from control.app.models import (
    AuditAction,
    Node,
    NodeState,
    NodeTransport,
    TransportPurpose,
)
from control.app.services import audit, keymaterial
from edge.egress import Egress
from edge.node import NodeView
from edge.registry import KeyScope, discover, profile

logger = logging.getLogger(__name__)

# What a node record gets when the operator leaves the SSH boxes empty. Named here
# rather than typed into the panel's form because M9 forbids a template naming a port:
# a value written into markup is one nobody can find when it has to change, and the
# add-node dialog now renders these as its placeholders instead of carrying its own
# copy. They are defaults for reaching a host we own, not a fact about any provider.
DEFAULT_SSH_USER = "root"
DEFAULT_SSH_PORT = 22

# What an operator is told when the text in the SSH key box is not a key this control
# plane can load. One sentence, used by the form that accepts a key and by the push path
# that finds an unusable one already stored, so the two cannot describe it differently.
#
# It carries no part of what was pasted. The value is a credential for every node in the
# fleet, and a refusal that quoted the first line of it would put it in the markup of the
# one form written never to render it back (see the dialog's own note).
SSH_KEY_UNUSABLE = (
    "not a private key this control plane can read — paste the whole key, from its "
    "BEGIN line to its END line, and not one that is protected by a passphrase"
)


def ssh_key_is_usable(key: str) -> bool:
    """Whether the SSH layer will be able to load this private key.

    Asked with the SAME call the connection itself makes, so "accepted by the panel" and
    "usable for reaching a node" cannot come to mean two different things. A structural
    check on the BEGIN and END lines would accept a truncated body, and the operator
    would learn about it at the first apply — as an internal error, which is what this
    function exists to stop being the answer to a mistyped paste.

    ``ValueError`` because that is the base of what the library raises for both shapes of
    unusable key: text that is not a key at all, and a key this control plane holds no
    passphrase for. Neither is an internal error and neither is worth two sentences —
    both mean the credential cannot be used and has to be pasted again.

    Nothing is logged and nothing is returned but the answer: the argument is a
    credential, and the exception it raises can quote what it was given.
    """
    try:
        asyncssh.import_private_key(key)
    except ValueError:
        return False
    return True


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


# Which way out a node's traffic takes, by the purpose the row already records and by
# whether that node has a hop of its own — M14.3, and M3 for the second half of the key.
# A TABLE rather than a branch: both halves are topology (``purpose`` is "who is on the
# far end of this tunnel", the flag is "does this node have a way out that is not its
# own"), and `control` still compares no transport name to a literal.
#
# The answers are not symmetric in how they fail, and that is why this is written down
# rather than assumed. A friend-facing tunnel with no exit produces a friend who says at
# once that nothing loads. A friend-facing tunnel on an ENTRY that exits locally produces
# a friend in Russia whose traffic leaves in Russia, with two active nodes and a live hop
# on every screen and nothing to notice.
#
# WHICH OF THE RELAY ENTRIES BELOW IS LIVE TODAY: none, and they are here on purpose.
# ``apply.render_for_node`` never asks this function about a hop end — it recognises a
# relay purpose first and dispatches the pair to ``relay.render_end``, which reaches
# ``edge.relay.render_hop``, and THAT is where a hop end's policy actually comes from
# (since M3: the leaf exits locally, the entry renders the way out and exits nowhere).
# So the guarantee in force is ``render_hop``'s own, and these rows are a forward guard:
# the day something renders a hop end through the ordinary server path, the answer is
# already decided and it is the safe one. They are unreachable, not dead — do not delete
# them because the call graph says nothing reaches them, and note they deliberately still
# say NONE rather than mirroring what ``render_hop`` does. A guard's job is to be safe,
# and this one cannot supply the address the entry's real policy needs.
_EGRESS: dict[tuple[str, bool], Egress] = {
    # (purpose, this node has a hop it dials)
    (TransportPurpose.FRIENDS, False): Egress.LOCAL,
    (TransportPurpose.FRIENDS, True): Egress.HOP,
    (TransportPurpose.RELAY_ENTRY, False): Egress.NONE,
    (TransportPurpose.RELAY_ENTRY, True): Egress.NONE,
    (TransportPurpose.RELAY_LEAF, False): Egress.NONE,
    (TransportPurpose.RELAY_LEAF, True): Egress.NONE,
}


def egress_for(node_transport: NodeTransport, hop_exit: str | None = None) -> Egress:
    """Which way out this row's traffic takes.

    ``hop_exit`` is the address this node's own way out runs through, or ``None`` when it
    has no hop — see ``relay.exit_through_hop``. Only its presence is read here; the
    address itself travels beside this value to the renderer, because a policy of "out
    through the hop" and the address the hop runs through are two facts and neither is
    usable alone.

    Unknown purposes fall to ``NONE`` rather than raising, and that is the fail-closed
    rule rather than laziness: a purpose this table has not been taught about is a
    topology nobody has decided the exit policy for, and the safe answer to an undecided
    question is no exit. The same applies to the pairing itself — a combination missing
    from the table is no exit, never a local one.
    """
    return _EGRESS.get((node_transport.purpose, hop_exit is not None), Egress.NONE)


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
    ssh_port: int = DEFAULT_SSH_PORT,
    ssh_user: str = DEFAULT_SSH_USER,
    ssh_private_key: str | None = None,
) -> Node:
    """Register a node. It starts in ``draft`` and carries no traffic yet.

    Draft rather than active is deliberate: a node exists as a record before it is
    configured, and a record that defaulted to active would put an unconfigured host
    into every friend's subscription the moment it was typed in.

    A key that will not load is refused HERE and not stored. It is ordinary bad input —
    a paste that lost its last line, a key with a passphrase — and the alternative is
    what it used to be: the record accepted, and the mistake reported at the first apply
    as an internal error naming an exception class and pointing at a container log. The
    node cannot be edited afterwards either, so the moment to say so is this one.
    """
    # Truthiness rather than ``is not None``: an empty string means "not supplied"
    # everywhere else on this path — the SSH layer treats it as no key at all — and a
    # refusal saying an empty box is not a key would be about the wrong thing.
    if ssh_private_key and not ssh_key_is_usable(ssh_private_key):
        raise DomainError(SSH_KEY_UNUSABLE)

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
    # The name the operator just chose, copied whole. Not the address, not the SSH
    # host, not the location: an address against a time is the record the charter says
    # is absent, and the name is the only part of this row the panel names it by.
    audit.record(session, AuditAction.NODE_ADDED, first_label=node.name)
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
        # NEVER THE VALUES of the merged mapping: it holds the private key minted three
        # lines up. This used to say "only the transport's own field errors are
        # surfaced, never the input values" and leave it at that — which is exactly the
        # assumption ``docs/decisions.md`` (2026-09-10) exists to stop relying on. A
        # validator's own message can quote what it was handed whichever field it names,
        # and this message goes straight into the error envelope that answers both
        # ``POST /api/nodes/{id}/transports`` and the panel's form.
        #
        # So the sentences are composed by ``relay.refused_fields``, which strikes every
        # minted secret out of them — the one function every path that validates
        # operator parameters against a transport's model shares, precisely so that
        # "what may not be printed" cannot be answered four different ways.
        #
        # KEPT PER FIELD as well as flattened into the sentence, which is the M9.5
        # addition here. ``ParamsRefused`` is a ``DomainError`` that INHERITS its status
        # and its code (see the exception's own note), so ``POST /api/nodes/{id}/
        # transports`` answers exactly as it always has — envelope for envelope, and so
        # did the pre-redesign form for as long as it existed. What it adds is somewhere
        # for the console's enable
        # dialog to put "this box, this reason", which is the same reason
        # ``relay.establish_hop`` and ``rotation.replace_params`` raise their own
        # subclasses: a sentence at the top of an eleven-box form makes the operator
        # hunt for the parameter the prose names.
        #
        # Imported inside the function to break a cycle: ``relay`` imports this module
        # for ``node_view`` and ``render_params``. Same deferred-import reasoning as the
        # two ``friends`` imports below.
        from control.app.services import relay  # noqa: PLC0415

        fields = relay.refused_fields(exc, withholding=minted.secrets.values())
        problems = "; ".join(f"{where}: {message}" for where, message in fields.items())
        raise ParamsRefused(
            f"transport {transport_name!r} rejected these parameters — {problems}",
            fields=fields,
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
    # Two labels: which node, and which transport. Both read off rows — the node's own
    # name and the name the transport package declared about itself — so this module
    # still compares no transport name to a literal and still composes nothing. The
    # parameters that were just validated are NOT here, and must not be: a parameter
    # value is a port, a decoy host or a key, and none of the three belongs in a
    # durable record.
    audit.record(
        session,
        AuditAction.TRANSPORT_ENABLED,
        first_label=node.name,
        second_label=transport_name,
    )
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
    # Fetched rather than reached through ``node_transport.node``. The relationship is
    # eager, but a row this session created moments ago has never been LOADED, so
    # touching it is lazy I/O — which on an async session is an immediate
    # MissingGreenlet crash rather than a slow query. Same rule as in
    # ``friends.grant_everywhere``.
    node = await get_node(session, node_transport.node_id)
    # Below the idempotence check above, so a retried click writes nothing: only a
    # change that actually happened is an entry. Two actions rather than one action and
    # a boolean, because the trail has no column for a value and is not getting one —
    # what a row may carry is a label read off the inventory, and "true" is neither.
    audit.record(
        session,
        AuditAction.TRANSPORT_OFFERED if enabled else AuditAction.TRANSPORT_WITHDRAWN,
        first_label=node.name,
        second_label=node_transport.transport_name,
    )
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

    changed = state != node.state

    node.state = state
    # ``==`` for the same reason as above: a caller handing this the raw string a route
    # parsed would otherwise silently drop the operator's explanation on the floor.
    node.state_detail = detail if state == NodeState.DEGRADED else None

    if changed:
        # THE LINE THIS TABLE'S SHAPE WAS WRITTEN AGAINST. The state is recorded and
        # ``detail`` is not, and they sit one line apart: ``state_detail`` is 500
        # characters that can carry a remote host's words, and an
        # f-string joining the two would satisfy every other rule about this table. The
        # state is a member of a closed enum read straight off the row; the reason for a
        # degraded node lives on the node, where the operator already reads it.
        #
        # Recorded even when the new state is ``degraded``, which is not a contradiction
        # of "no failures": what is recorded is the state change, which committed — not
        # the operation that failed, and not why.
        audit.record(
            session,
            AuditAction.NODE_STATE_CHANGED,
            first_label=node.name,
            second_label=str(state),
        )

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
