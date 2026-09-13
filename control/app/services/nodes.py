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
from control.app.services import addresses, audit, keymaterial, placement
from edge.addressing import pool_problem
from edge.egress import Egress, resolver_problem
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
        # The row's own id last, so the order is TOTAL — M17. Two instances of one
        # transport on one node (which M15 permits) tied on every other key, and the
        # order a subscription is built in, and the order addresses are handed out in,
        # were then whatever Postgres returned. A tie-break nobody can see is a fleet
        # whose allocation is not reproducible.
        .order_by(
            Node.location_label,
            Node.name,
            NodeTransport.transport_name,
            NodeTransport.id,
        )
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
        resolver=node.resolver,
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
    resolver: str | None = None,
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

    # A resolver that could never carry a lookup through a hop is refused here too, while
    # the operator is still looking at the box, rather than by ``edge`` at the first apply
    # after a hop is established — on another screen, maybe weeks later. It can be set
    # again afterwards (``set_resolver``), but that is the repair, not the plan. Asked of
    # ``edge``, which owns what the value means, so the rule this refuses by and the rule
    # a render refuses by are one rule.
    if resolver:
        problem = resolver_problem(resolver)
        if problem:
            raise DomainError(problem)

    existing = await session.execute(select(Node).where(Node.name == name))
    if existing.scalars().first() is not None:
        raise Conflict(f"a node named {name!r} already exists")

    node = Node(
        name=name,
        address=address,
        location_label=location_label,
        resolver=resolver or None,
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


async def set_resolver(session: AsyncSession, *, node_id: str, resolver: str) -> Node:
    """Name the resolver a node's lookups are sent to through its hop — after registration.

    The one field on a node record that can change once the node exists (M16). Everything
    else there stays fixed and a new host is a new node, but this one could not: the
    upgrade that added it gave every existing node none, a node that dials a hop does not
    render without one, and a node that cannot be rendered cannot be reached by a
    revocation either. So the value is node-record data that has to be writable onto the
    node that needs it — which, the day this lands, is one already in the field.

    Refused with ``edge``'s own sentence when the value could never carry a lookup: the
    rule a render refuses by, in the same words. Setting the value a node already holds
    changes nothing and records nothing — a retried click is not an event. It changes the
    record and never the host; the operator's next apply carries it there.
    """
    node = await get_node(session, node_id)
    problem = resolver_problem(resolver)
    if problem:
        raise DomainError(problem)
    if resolver != node.resolver:
        node.resolver = resolver
        # The node's name and nothing else — never the resolver. An address against a
        # time is the record this trail was shaped to refuse, and a resolver is one.
        audit.record(session, AuditAction.NODE_RESOLVER_SET, first_label=node.name)
        await session.commit()
        logger.info("node %s resolver set", node.id)
    return node


async def enable_transport(
    session: AsyncSession,
    *,
    node_id: str,
    transport_name: str,
    params: dict,
    pool_size: int | None = None,
) -> NodeTransport:
    """Enable one transport on one node, minting whatever material it declared.

    Commits, and grants nobody. NO PRODUCTION CALLER SINCE M17: both surfaces call
    ``enable_and_grant`` below, because the grant may not be a second transaction — see
    its note. What is left here is the plain enable, which is what a test wanting a row
    without a fan-out asks for, and ``test_no_surface_enables_a_transport_without
    _granting_it`` is what keeps a route from drifting back onto it.
    """
    node_transport = await _enable(
        session,
        node_id=node_id,
        transport_name=transport_name,
        params=params,
        pool_size=pool_size,
    )
    await session.commit()
    logger.info("transport enabled on node %s", node_transport.node_id)
    return node_transport


async def enable_and_grant(
    session: AsyncSession,
    *,
    node_id: str,
    transport_name: str,
    params: dict,
    pool_size: int | None = None,
) -> NodeTransport:
    """Enable a transport and hand it to every active friend — in ONE transaction.

    Criterion 3 stated as an operation: a protocol enabled from the panel is in every
    subscriber's config at their next refresh with no further action from anybody.

    IT IS ONE TRANSACTION SINCE M17, and that is the reason this function exists at all
    rather than each surface running its own loop after the enable committed. Granting
    now allocates an address per person on a transport that gives each of them one, and a
    pool too small refuses — so with the enable already committed, the operator would be
    left with a row on the node that nobody can be granted, having been told the
    operation failed. Both surfaces call this, so neither can drift back.

    The grant is a no-op on a node that is not serving yet, which is the ordinary case: a
    transport is normally enabled while the node is still a draft, and the moment the
    node starts serving is where ``set_node_state`` does the same fan-out.
    """
    node_transport = await _enable(
        session,
        node_id=node_id,
        transport_name=transport_name,
        params=params,
        pool_size=pool_size,
    )

    # Deferred for the cycle ``set_node_state`` names: ``friends`` imports this module.
    from control.app.services import friends  # noqa: PLC0415

    for friend in await friends.list_friends(session):
        if friend.is_active:
            await friends.grant_everywhere(session, friend)

    await session.commit()
    logger.info("transport enabled on node %s", node_transport.node_id)
    return node_transport


async def _enable(
    session: AsyncSession,
    *,
    node_id: str,
    transport_name: str,
    params: dict,
    pool_size: int | None = None,
) -> NodeTransport:
    """Everything enabling a transport does except commit.

    Split out so that the grant fan-out above can run in the same transaction as the row
    it is about. Flushes, so the new row is visible to ``serving_transports`` — without
    that, enabling a transport on a node that is ALREADY serving would grant nobody.

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

    # What this row would collide with on this node, asked in the one place that answers
    # it — M15. It replaces the ``(node, transport_name)`` duplicate check that used to
    # stand a few lines above: a node may now run two instances of one transport, and
    # what it may not do is give them one port or one config file. Asked AFTER
    # validation, because the port that matters is the one that will be stored, which
    # for a transport that defaults its port is not a value the operator typed.
    config_name = await placement.claim(
        session, node=node, transport_name=transport_name, params=validated
    )

    # How many people this row can hand an address to — M17. AFTER ``claim`` on purpose:
    # a request that gets both wrong is answered about the port first, which is the older
    # refusal, the one every existing caller asserts on, and the one that is about the
    # node rather than about a number the operator typed.
    await sized_pool(
        session,
        node=node,
        transport_name=transport_name,
        params=validated,
        pool_size=pool_size,
    )

    # Split the validated result back apart for storage. Driven by which keys the
    # generator produced as secret, so a transport's own declaration decides what is
    # encrypted — this function never judges a value by its name.
    secret_keys = set(minted.secrets)
    node_transport = NodeTransport(
        node_id=node.id,
        transport_name=transport_name,
        config_name=config_name,
        params={k: v for k, v in validated.items() if k not in secret_keys},
        secrets=json.dumps({k: v for k, v in validated.items() if k in secret_keys}),
        enabled=True,
        # NULL for every transport that hands out no address of its own, which is what
        # ``sized_pool`` has just insisted on — so "this row has a pool" and "this
        # transport declares one" cannot come apart in the database.
        pool_size=pool_size,
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
    # Flushed and not committed: the caller owns the transaction. It has to be flushed,
    # though — ``serving_transports`` is a query, and a row that is only pending would be
    # invisible to the grant fan-out that may follow this in the same transaction.
    await session.flush()
    return node_transport


# What an operator is told about the pool box, in the three ways it can be wrong. Each
# names what to do rather than only what was refused, and none of them names an address:
# the value in question is a count.
POOL_SIZE_REQUIRED = (
    "this transport gives every friend an address of its own, so it needs to be told how "
    "many addresses it may hand out. Size the pool for the fleet this node will serve."
)
POOL_SIZE_NOT_TAKEN = (
    "this transport identifies each friend by their own material rather than by an "
    "address, so there is no pool to size on it."
)
POOL_SIZE_BELOW_THE_FLEET = (
    "a pool of {size} cannot hold the {people} friends this control plane already has, "
    "and every one of them is granted a credential here the moment this node serves. "
    "Nothing has been changed — size the pool for the fleet."
)


async def sized_pool(
    session: AsyncSession,
    *,
    node: Node,
    transport_name: str,
    params: dict,
    pool_size: int | None,
    against_the_fleet: bool = True,
) -> None:
    """Refuse a pool that cannot work, before anything is written — M17.

    Four questions, and the first two are about whether there is a pool at all: a
    transport that declares each consumer needs an address of their own MUST be told how
    many there are, and one that declares nothing must not be given a number that would
    then mean nothing. Both are read off ``TransportMeta.peer_address`` through
    ``addresses.spec_for``, so this function names no transport and no field.

    The third is ``edge``'s own sentence about the pool: whether it fits inside the
    tunnel, clears the node's own address, and stays in private space. Asked here, while
    the operator is still looking at the box, rather than at the first render.

    The fourth is this control plane's: a pool smaller than the fleet is one that refuses
    the next person to be granted, and the moment to say so is before the row exists
    rather than at whichever later operation happens to trip over it.

    Refused as ``ParamsRefused`` with the complaint under the pool's own box, which is
    what lets the console put the sentence where the number was typed. The box is not a
    parameter of the transport — nothing of this reaches the transport's model.

    EVERY SENTENCE NAMES THE NODE AS WELL AS THE TRANSPORT, which the milestone's own
    done-when asks for and which only the message can carry: the per-box sentence goes
    under a box in a dialog the operator opened from one row, but the message travels out
    of ``POST /api/transports/{id}/params``, whose caller addressed an opaque id and has
    no node in the request at all. A script sizing two rows in a loop was told twice that
    one transport had rejected a size, with nothing saying whose row it was.

    PUBLIC SINCE M17.1c, and asked by the second path that can change a pool:
    ``rotation.replace_params``, which resizes a row that already exists. One definition
    of what a workable pool is, for the same reason ``addresses.fleet_size`` is one
    definition of who is in the fleet — the two paths that refuse a size must not be able
    to disagree about which sizes they refuse.

    ``against_the_fleet`` is the one question that does NOT apply on that second path when
    the operator is not sizing anything. Replacing a blocked decoy on a row whose pool is
    already smaller than the fleet has to go through: the pool is wrong either way, and
    refusing the rotation leaves the operator unable to rotate away from a blocked value —
    which is the charter's first job for them. The third question is still asked there,
    against the size the row already has, because THAT is the check that was missing: a
    replaced parameter could move the tunnel out from under the pool with nothing looking.
    """
    spec = addresses.spec_for(transport_name)

    if spec is None:
        if pool_size is not None:
            raise ParamsRefused(
                f"transport {transport_name!r} on node {node.name!r} rejected these "
                f"parameters — {addresses.POOL_BOX}: {POOL_SIZE_NOT_TAKEN}",
                fields={addresses.POOL_BOX: POOL_SIZE_NOT_TAKEN},
            )
        return

    if pool_size is None:
        raise ParamsRefused(
            f"transport {transport_name!r} on node {node.name!r} rejected these "
            f"parameters — {addresses.POOL_BOX}: {POOL_SIZE_REQUIRED}",
            fields={addresses.POOL_BOX: POOL_SIZE_REQUIRED},
        )

    # Over the VALIDATED parameters, so the addresses measured are the ones that will be
    # stored — normalised by the transport's own validator, not as they were typed.
    problem = pool_problem(str(params[spec.name]), str(params[spec.within]), pool_size)
    if problem:
        raise ParamsRefused(
            f"transport {transport_name!r} on node {node.name!r} rejected these "
            f"parameters — {addresses.POOL_BOX}: {problem}",
            fields={addresses.POOL_BOX: problem},
        )

    # THE FLEET COUNT IS ``addresses``', not this module's own query — M17.
    # The same number is the floor in the enable dialog's placeholder and the threshold
    # the add-a-friend refusal uses; written out here as well, a later change to who
    # counts as being in the fleet would land in one copy and the box would offer a size
    # this refuses.
    if not against_the_fleet:
        return

    people = await addresses.fleet_size(session)
    if pool_size < people:
        short = POOL_SIZE_BELOW_THE_FLEET.format(size=pool_size, people=people)
        raise ParamsRefused(
            f"transport {transport_name!r} on node {node.name!r} rejected these "
            f"parameters — {addresses.POOL_BOX}: {short}",
            fields={addresses.POOL_BOX: short},
        )


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
    withdraw a person's access; use ``remove_transport`` to take the row away
    altogether, which is also the only thing that frees its port and its config name.
    """
    node_transport = await get_node_transport(session, node_transport_id)

    # A hop end is not an offer to friends, and switching one off is not a delivery
    # change — it is half a tunnel that stops completing a handshake while both ends
    # still look configured. Refused by pointing at the operation that removes both.
    if node_transport.purpose != TransportPurpose.FRIENDS:
        # The id is substituted rather than left as a placeholder, for the reason
        # ``REMOVE_IS_FOR_AN_OFFER`` gives: an envelope naming ``{node_transport_id}``
        # literally is one the script reading it has to decode.
        raise Conflict(
            "this transport is one end of an entry-to-leaf hop, not something "
            "friends are offered. Switching one end off would leave a tunnel that "
            "no longer completes while both ends still look configured — remove the "
            f"hop instead (DELETE /api/hops/{node_transport_id})."
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

    if enabled:
        # INSIDE THE TRANSACTION SINCE M17, and the order of these two statements is the
        # whole of it. This used to commit the flag and then grant in a second
        # transaction: with an address per friend to allocate, a pool with no room then
        # refused AFTER the transport was already back in everybody's subscription, and
        # the operator was told the offer failed while the row said it had succeeded.
        # Now a refusal from the fan-out rolls this back with it and nothing committed.
        #
        # Flushed above (the flag is what makes the row serving), so the grant sees it.
        #
        # Same deferred import, same cycle, same reasoning as ``set_node_state``.
        from control.app.services import friends  # noqa: PLC0415

        await session.flush()
        for friend in await friends.list_friends(session):
            if friend.is_active:
                await friends.grant_everywhere(session, friend)

    await session.commit()
    logger.info("node-transport %s enabled -> %s", node_transport.id, enabled)

    return node_transport


# What an operator is told when they ask to remove one END OF A HOP. Removal is for a
# transport this node OFFERS; a hop is a pair, and the operation that takes a pair away
# already exists — so the refusal names it rather than merely declining.
#
# It names the API path for the same reason ``set_transport_enabled``'s does: ``/api`` is
# this service's other caller and a script reading the envelope has nothing else to go
# on. FORMATTED WITH THE ROW'S OWN ID, so what the caller reads is the call they can
# make rather than a placeholder they have to decode — the id is the one they just
# addressed, so this discloses nothing they did not send. The console does not repeat
# any of it: it answers in its own words from ``console.REMOVE_HOP_END``, because "no
# URL typed by hand" is what the panel promises.
REMOVE_IS_FOR_AN_OFFER = (
    "this transport is one end of an entry-to-leaf hop, not something friends are "
    "offered. Removing one end would leave the other holding a tunnel to an exit that "
    "is no longer configured — remove the hop instead, which takes both ends "
    "(DELETE /api/hops/{node_transport_id})."
)


async def remove_transport(session: AsyncSession, *, node_transport_id: str) -> str:
    """Delete one friend-facing transport, and everything minted under it — M15.2.

    Returns the id of the node that now needs re-applying.

    DISABLING IS NOT REMOVING, and until this existed only the first was expressible.
    ``set_transport_enabled`` flips a flag: the row keeps its listening port and its
    config name, deliberately, because freeing them on a switch-off would move the
    collision to the moment the operator switches it back on (``services.placement``).
    So a row was the one thing in this product that could be created and never taken
    back — and since M15 moved uniqueness onto the port and the config name, THIS is
    what frees them. An operator who enabled a transport on the port the hop needs had,
    before this function, no exit but editing the database by hand.

    WHAT GOES WITH THE ROW. Every ``Credential`` minted for it, by the same cascade
    ``dissolve_hop`` relies on — ``NodeTransport.credentials`` is ``delete-orphan`` and
    the foreign key is ON DELETE CASCADE, so the material a person held on this node ×
    transport is destroyed rather than orphaned. That is the difference from withdrawing,
    where every credential stays minted against a row that is merely switched off.
    Nothing else points at this row: a hop peer would, and a hop end is refused above.

    WHAT DOES NOT GO WITH IT, and must not be reported as going: the daemon on the host.
    Deleting a row changes what this control plane DELIVERS and what it would RENDER, not
    what the node is running — the file is still on disk and the container still serves
    it until the node is applied again, which is why the caller is handed the node that
    needs it and why the console's sentence says so. Exactly the distinction
    ``set_transport_enabled`` insists on, and it is sharper here: the operator has just
    watched the row disappear from the panel.

    NOT PUSHED FROM HERE, for ``dissolve_hop``'s reason: a node may be unreachable, and a
    removal that failed because the host is down would leave the operator unable to free a
    port on a machine that no longer exists — which is exactly when they need to.
    """
    node_transport = await get_node_transport(session, node_transport_id)

    if node_transport.purpose != TransportPurpose.FRIENDS:
        raise Conflict(
            REMOVE_IS_FOR_AN_OFFER.format(node_transport_id=node_transport_id)
        )

    # Both labels read BEFORE the delete, off rows this transaction still holds: after
    # the flush the transport row is gone and its attributes are not a source of
    # anything. The node is fetched by id rather than reached through
    # ``node_transport.node`` — the relationship is eager but unloaded on a row another
    # session created, and touching it is lazy I/O, which an async session answers with
    # MissingGreenlet.
    node = await get_node(session, node_transport.node_id)
    transport_name = node_transport.transport_name

    # ``await`` because the cascade may have to LOAD the credentials it is about to
    # delete, and a lazy load on an async session only runs inside this call.
    await session.delete(node_transport)
    # Which node and which transport, both copied whole off inventory rows — the same
    # two labels the enable that created this row wrote, so a reader sees the pair. The
    # config name it was placed under is NOT here: it is this control plane's own
    # bookkeeping rather than a name the operator chose, and the trail's rule is that a
    # label is a value read off a row the operator recognises.
    audit.record(
        session,
        AuditAction.TRANSPORT_REMOVED,
        first_label=node.name,
        second_label=transport_name,
    )
    await session.commit()
    logger.info("node-transport %s removed from node %s", node_transport_id, node.id)
    return node.id


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
        # IN THIS TRANSACTION SINCE M17. The state change used to commit first and grant
        # afterwards, which with an address per friend to allocate meant a node could go
        # active — recorded, on every screen, in every subscription — and only then be
        # unable to give somebody an address. The operator was told the operation failed
        # by a control plane that had already done half of it. Now a pool with no room
        # anywhere in the fleet rolls this state change back with it.
        #
        # Flushed rather than committed first, because ``serving_transports`` is a query:
        # without the flush the node is still draft as far as the database is concerned
        # and the fan-out below would grant nobody anything.
        #
        # Imported inside the function to break a cycle: ``friends`` imports this
        # module for ``serving_transports``. A deferred import is the honest fix here;
        # the alternative is a third module that exists only to hold one call.
        from control.app.services import friends  # noqa: PLC0415

        await session.flush()
        for friend in await friends.list_friends(session):
            if friend.is_active:
                await friends.grant_everywhere(session, friend)

    await session.commit()
    logger.info("node %s state -> %s", node.id, state)

    return node
