"""Entry→leaf hops between two nodes — backlog item 16.

WHAT: establishing, re-pointing and tearing down the tunnel that carries traffic from
      the entry node the friends dial to the leaf node their traffic leaves from.
WHY:  this is the charter's topology, and it is what makes criterion 2 ("replace any
      node in ten minutes") true of a LEAF: friends only ever hold the entry's address,
      so a blocked leaf is replaced by re-pointing one hop and pushing two nodes — with
      nobody touching their device.
HOW:  a hop is two ordinary ``NodeTransport`` rows that point at each other, marked
      with the end of the hop they are. Reusing the friend-facing row shape rather than
      inventing a parallel table is deliberate: key minting, encryption at rest,
      rotation, apply and drift detection then work on a hop for free, and none of them
      needed a line of "if this is a relay".

      What this module refuses to do is as important as what it does. A hop row is
      never granted to a friend and never appears in a subscription (see
      ``nodes.serving_transports``), because a friend holding the entry↔leaf tunnel
      would be routed straight past the entry node the topology exists to hide behind.
"""

import json
import logging
from collections.abc import Iterable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import (
    DomainError,
    HopEndRefused,
    NoExitThroughTheHop,
    NotFound,
)
from control.app.models import AuditAction, Node, NodeTransport, TransportPurpose
from control.app.services import audit, keymaterial, nodes, placement, transports
from edge import relay as edge_relay
from edge.registry import KeyScope, discover, profile

logger = logging.getLogger(__name__)


async def hop_ends(session: AsyncSession, node_id: str) -> list[NodeTransport]:
    """Every hop end configured on one node."""
    result = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node_id)
        .where(NodeTransport.purpose.in_(TransportPurpose.relays()))
        .order_by(NodeTransport.transport_name)
    )
    return list(result.scalars().unique())


async def peer_of(session: AsyncSession, end: NodeTransport) -> NodeTransport:
    """The far end of a hop, or a loud failure.

    Loud because the alternative is rendering one end of a tunnel as though it were a
    server with no peers: a valid file, a daemon that starts, and an exit that carries
    nothing. ``peer_node_transport_id`` is SET NULL on delete precisely so this case is
    reachable and has to be handled here rather than assumed away.
    """
    if end.peer_node_transport_id is None:
        raise DomainError(
            f"the far end of this hop on node {end.node_id} is gone, so it cannot be "
            "rendered. Re-establish the hop, or remove this end."
        )
    peer = await session.get(NodeTransport, end.peer_node_transport_id)
    if peer is None:
        raise DomainError("the far end of this hop no longer exists")
    return peer


async def exit_through_hop(session: AsyncSession, node: Node) -> str | None:
    """The address on this node that its friends' traffic must leave through — M3.

    ``None`` for a node with no hop of its own: a leaf, or a single-box deployment. That
    is every node that has always exited directly and must keep doing so, which is why
    this is the answer a node gets when the query finds nothing rather than an error.

    Read from the row's EXISTENCE and not from ``enabled``, and the difference is decision
    3. A hop end an operator has switched off is a tunnel that is not running — so the
    friend-facing config still points at an address that is not there, and the friend gets
    no exit. Filtering on ``enabled`` would instead hand that node back its direct
    outbound: a friend in Russia exiting in Russia the moment somebody unticks a box.
    """
    result = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.node_id == node.id)
        .where(NodeTransport.purpose == TransportPurpose.RELAY_ENTRY)
        .order_by(NodeTransport.transport_name)
    )
    ends = list(result.scalars().unique())
    if not ends:
        return None
    if len(ends) > 1:
        # Refused rather than resolved by picking one. A node has ONE way out — the route
        # both hops would install lives in a single table on the host, so the second
        # container's PostUp fails and the tunnel that ends up carrying the traffic is
        # whichever came up first. An operator reading "this node dials two hops" can fix
        # it; an operator reading nothing cannot.
        raise DomainError(
            f"node {node.name!r} is the entry end of {len(ends)} hops, and a node can "
            "have only one way out. Dissolve all but one before applying it."
        )
    return edge_relay.exit_via(
        edge_relay.HopEnd(node=nodes.node_view(node), params=nodes.render_params(ends[0]))
    )


async def dials_a_hop(session: AsyncSession, node_id: str) -> bool:
    """Whether this node's own way out is a hop — M25.

    ``exit_through_hop``'s question without its answer, and deliberately not that
    function: this is asked at a DOOR, before anything is minted, where the address is
    not wanted and the work of getting it is a liability. That one renders the end's
    parameters, which decrypts this node's stored material, and refuses out loud when a
    node holds two entry ends — both right where it is called from (an apply, which needs
    the address and must not proceed on a node with two ways out) and both wrong here,
    where the caller only needs to know whether there is one.

    Read from the row's EXISTENCE and not from ``enabled``, which is the same decision
    ``exit_through_hop`` documents: a hop end switched off is a hop that is down, not a
    node that has got its direct exit back. A door that consulted the flag would let the
    combination in through a switched-off hop and find it again the moment the operator
    switched the hop back on — at the apply, which is where this refusal exists to stop
    the operator ending up.

    The LEAF end of a hop is not a way out and is not counted: that node's friends leave
    by its own route, which is route B and is untouched by any of this.
    """
    result = await session.execute(
        select(NodeTransport.id)
        .where(NodeTransport.node_id == node_id)
        .where(NodeTransport.purpose == TransportPurpose.RELAY_ENTRY)
        .limit(1)
    )
    return result.first() is not None


def hop_view(node_transport: NodeTransport) -> edge_relay.HopEnd:
    """Project one stored end into the pure value object ``edge.relay`` renders from."""
    return edge_relay.HopEnd(
        node=nodes.node_view(node_transport.node),
        params=nodes.render_params(node_transport),
    )


def render_end(end: NodeTransport, peer: NodeTransport) -> str:
    """This end's configuration for the hop it belongs to.

    Both ends are rendered together — a hop is only expressible as a pair — and the one
    belonging to ``end`` is returned. That is what makes the entry/leaf asymmetry
    (only the entry dials) come out of ``edge.relay`` rather than being reconstructed
    here from the purpose column.
    """
    near, far = hop_view(end), hop_view(peer)
    if end.purpose == TransportPurpose.RELAY_ENTRY:
        entry_config, _ = edge_relay.render_hop(
            end.transport_name, entry=near, leaf=far
        )
        return entry_config
    _, leaf_config = edge_relay.render_hop(end.transport_name, entry=far, leaf=near)
    return leaf_config


# What an operator is told when two ends would render into files that carry nothing.
# One sentence, used where a hop is first established and where one end of an existing
# hop is rewritten, because those are the same mistake at two moments — and because
# ``HopNotRenderable`` is not a ``DomainError``: whichever path lets it escape answers
# 500 and tells the operator that nothing was changed.
HOP_WOULD_NOT_WORK = "these two ends would not form a working tunnel: {reason}"


def check_renders_as_a_pair(
    end: NodeTransport, peer: NodeTransport, *, end_params: dict, peer_params: dict
) -> None:
    """Refuse two hop ends that would not carry traffic — before either one is written.

    ``render_end`` renders what the rows CURRENTLY hold; this renders what a caller is
    about to write into them, which is the difference that matters to anything rewriting
    one end of a live hop. ``edge.relay`` refuses the combinations that produce two
    individually valid configuration files and a handshake that never completes —
    mismatched symmetric material above all — and it does so by raising
    ``HopNotRenderable``, which is not a ``DomainError``. A caller that renders after it
    has committed therefore does not get a refusal at all: it gets a 500 over a change
    that has already happened.

    Pure: it reads the two rows' nodes and renders. Nothing is written and nothing is
    read from the database, so it is safe to call between validating and committing —
    which is the only place it belongs.
    """
    near = edge_relay.HopEnd(node=nodes.node_view(end.node), params=end_params)
    far = edge_relay.HopEnd(node=nodes.node_view(peer.node), params=peer_params)
    entry, leaf = (
        (near, far) if end.purpose == TransportPurpose.RELAY_ENTRY else (far, near)
    )
    try:
        edge_relay.render_hop(end.transport_name, entry=entry, leaf=leaf)
    except edge_relay.HopNotRenderable as exc:
        raise DomainError(HOP_WOULD_NOT_WORK.format(reason=exc)) from exc


def _end_word(purpose: TransportPurpose) -> str:
    """Which end of the hop this is, in the word an operator uses for it.

    ``relay-entry`` is the column's vocabulary and belongs in the database, not in a
    sentence somebody reads while a rotation is half done. A two-way branch on our own
    topology enum, in the module that owns hops — it names no protocol and there is no
    third end.
    """
    return "entry" if purpose == TransportPurpose.RELAY_ENTRY else "leaf"


def _plainly(message: str) -> str:
    """A Pydantic message as the sentence the transport actually wrote.

    Pydantic prefixes a custom validator's own text with ``Value error,`` — so the
    transport's carefully written *"is not a private address — a public range here
    would route the node's own traffic into the tunnel"* reaches the operator wearing a
    label about Pydantic's internals. The prefix is dropped and nothing else is
    rewritten: a transport's own words are the best sentence available here, and every
    other message shape (``Input should be a valid integer``) is already plain.
    """
    for noise in ("Value error, ", "Assertion failed, "):
        if message.startswith(noise):
            return message[len(noise):]
    return message


# What stands in a refusal where a held value was struck out. A marker rather than an
# ellipsis, because an operator reading *"does not match the key [withheld]"* can tell
# that this panel removed something — a sentence that simply stopped short would read as
# the transport's own words and send them looking for a value that was never there.
WITHHELD = "[withheld]"

# The longest value a refusal may repeat back, and what stands in its place when it is
# longer. Not a rule about what a transport may be GIVEN — its own model decides that —
# but about what this control plane PRINTS: a validator quotes the value it rejected, so
# a thousand characters pasted into an address box came back as a thousand characters of
# the operator's own paste in a dialog, pushing every control below it off the screen.
# Found in M16's acceptance on the resolver box and again in M17's on an address box, so
# it is closed once, here, where every refusal about a parameter is already composed —
# which also closes the API envelope, where the same thousand characters were echoed.
#
# 128 is generous against real input: the longest value any shipped transport legitimately
# takes is a hostname, and an address with its prefix is under twenty. Nothing a working
# submission produces comes near it.
#
# A named marker rather than an ellipsis, for ``WITHHELD``'s own reason: a sentence that
# simply stopped short reads as the transport's own words, and the operator goes looking
# for a value that was never there.
TOO_LONG_TO_REPEAT = 128
OVER_LONG = "[too long to repeat]"


def refused_fields(
    exc: ValidationError, *, withholding: Iterable[object]
) -> dict[str, str]:
    """A transport's refusal as ``{parameter: sentence}``, carrying no held value.

    THE ONE PLACE that decides what may not be printed. Every path in this codebase that
    validates operator parameters against a transport's own model composes its refusal
    here, and the list is written out rather than described so that the next path added
    can see whether it is on it:

    * ``nodes.enable_transport`` — first enabling a transport on a node;
    * ``relay.establish_hop`` — both ends of a hop, below;
    * ``rotation.rotate_keys`` — re-minting a node's material;
    * ``rotation.replace_params`` — replacing an operator-supplied parameter.

    All four validate a mapping into which freshly minted or stored secrets have just
    been merged. It was four separate implementations, each answering "what may not be
    printed" differently at its own caller, which is how one of them stopped being
    updated: the console's allow-list closed the class of LOCATIONS and left the class
    of MESSAGES open. A ``field_validator`` on a field the form legitimately has a box
    for reads the rest of the already-validated mapping through ``info.data``, so
    Pydantic files the complaint at a real box name and the sentence — carrying the
    node's decrypted private key — is printed as visible text. See
    ``docs/decisions.md`` (2026-09-10).

    TWO THINGS THAT VALIDATE AND ARE DELIBERATELY NOT HERE, so that "every path" above
    means what it says. The add-node form (``panel/routes.py``) validates a schema that
    carries an SSH private key, but composes its own sentence from the error's TYPE and
    never reads ``msg`` at all — it cannot print a validator's words, so there is
    nothing here to strike. And ``apply.validate_before_push`` puts an external
    checker's output about a RENDERED config into a failure message; that is not a
    ``ValidationError`` and not a mapping of fields, and closing it is a different guard
    on a different value — it is not covered by this function and must not be assumed to
    be.

    So the values are removed here, while they are still in scope, rather than sorted
    four surfaces later: this closes ``fields``, the flattened message, the console and
    the API envelope at once — and the pre-redesign page's outcome fragment, which was
    the fourth until M9.6 deleted it. The console's allow-list stays as the second line
    of defence.

    ``withholding`` is **what is stored encrypted or minted as secret** — the same set
    ``stored_material`` sweeps for in the tests — and deliberately not "everything
    minted". A value the transport declared not-secret ships inside every user's own
    link, so striking it out of a sentence protects nothing and costs the operator a
    reason; some of those are also short enough that a blanket substring strike would
    eat unrelated text. There is no minimum length on a value that IS secret, and that
    asymmetry is the point: over-redaction costs a word, under-redaction prints a key.

    Matching is exact substring, longest value first so that a value containing another
    is struck whole.

    WHAT THIS CANNOT SEE, which is the residual after it and the accurate record of it:
    a value the validator TRANSFORMED before quoting — re-encoded (base64 to hex),
    truncated to a prefix, case-folded, or reversed — is not the same substring and
    survives. Nothing downstream covers that either; the console's allow-list is about
    where a complaint is filed, not what it says. A transport whose validator quotes a
    derivative of what it was given is the shape this guard would miss, and the only
    real answer to it is the one the codebase already relies on everywhere else: a
    transport's validator quotes the operator's input and not the material minted
    alongside it.

    The location is redacted too — a name is normally a Python identifier and safe, but
    a nested one can carry a mapping key, and this costs one line.

    AND WHAT IS PRINTABLE IS ALSO BOUNDED IN LENGTH — see ``TOO_LONG_TO_REPEAT``. A
    validator quotes the value it rejected, so an over-long paste was echoed whole into a
    dialog and into the API envelope; it is struck out here by the same mechanism as a
    held value, with its own marker, because the reason is different.
    """
    values = sorted(
        {str(value) for value in withholding if value is not None and value != ""},
        key=len,
        reverse=True,
    )
    # What the operator themselves sent, where it is too long to put back on a screen.
    # Struck out by the same mechanism and for a different reason: not because it is
    # secret, but because a refusal that repeats it is a refusal nobody can read past.
    # Taken from Pydantic's own record of what failed, so no caller has to hand it over.
    bulky = sorted(
        {
            error["input"]
            for error in exc.errors()
            if isinstance(error.get("input"), str)
            and len(error["input"]) > TOO_LONG_TO_REPEAT
        },
        key=len,
        reverse=True,
    )
    fields: dict[str, str] = {}
    for error in exc.errors():
        where = _readable(".".join(str(part) for part in error["loc"]), values, bulky)
        fields.setdefault(where, _readable(_plainly(error["msg"]), values, bulky))
    return fields


def _readable(text: str, values: list[str], bulky: list[str]) -> str:
    """One sentence with every held value struck out and every unprintable one shortened.

    Held values first, so a value that is both secret and over-long is named as withheld
    rather than merely as long: over-redaction costs a word, under-redaction prints a key.
    """
    return _without(_without(text, values), bulky, OVER_LONG)


def _without(text: str, values: list[str], marker: str = WITHHELD) -> str:
    """One sentence with every listed value struck out of it."""
    for value in values:
        text = text.replace(value, marker)
    return text


async def establish_hop(
    session: AsyncSession,
    *,
    entry_node_id: str,
    leaf_node_id: str,
    transport_name: str,
    entry_params: dict,
    leaf_params: dict,
) -> tuple[NodeTransport, NodeTransport]:
    """Configure both ends of one hop, minting each end's material.

    Validated as a PAIR before either row is written. A hop whose ends disagree is two
    perfectly valid files and a tunnel that never comes up, so half-establishing one
    would leave the operator with a node that looks configured and an exit that is
    unreachable — which is the failure mode this whole module is shaped around.
    """
    installed = discover()
    if transport_name not in installed:
        raise NotFound(
            f"no transport named {transport_name!r} is installed "
            f"(have: {', '.join(sorted(installed))})"
        )

    if entry_node_id == leaf_node_id:
        raise DomainError("a node cannot be its own exit")

    entry_node = await nodes.get_node(session, entry_node_id)
    leaf_node = await nodes.get_node(session, leaf_node_id)

    # THE SECOND DOOR — M25, and the same rule as ``nodes._enable``'s approached from the
    # other side. Giving a node a hop is giving its friends ``Egress.HOP``, so every
    # transport it already offers them has to be one that can honour it; a kernel tunnel
    # cannot, and the node's next apply would refuse to render the row it has been serving
    # from. Refused here rather than there, before either end is minted or written, so the
    # operator's fleet is exactly as it was and no material exists to be thrown away.
    #
    # Only the ENTRY node is asked. The leaf's friends exit by the leaf's own route
    # exactly as they always have — that is route B, and nine field walks are built on it.
    #
    # Every friend-facing row on it, switched on or not, for ``dials_a_hop``'s reason: a
    # row that is off can be switched back on from this panel, and that surface has no
    # node to refuse about. Sorted by the transport's name so a node offering two
    # unrenderable rows names the same one every time rather than whichever the database
    # returned first.
    #
    # A row naming a transport this image no longer ships is skipped, not refused: it
    # renders nothing whatever this node's topology is, so it is not this refusal's
    # subject and a sentence about the hop would send the operator after the wrong thing.
    for offer in await nodes.friend_facing_on(session, entry_node.id):
        offered = installed.get(offer.transport_name)
        if offered is not None and not offered.serves_friends_through_a_hop:
            raise NoExitThroughTheHop(
                transports.NO_HOP_OVER_WHAT_IT_OFFERS.format(
                    node=entry_node.name, name=offer.transport_name
                )
            )

    # What used to stand here was a refusal when either node already had a row for this
    # transport, whatever that row was FOR — so a node offering AmneziaWG to friends
    # could never become a hop end over it, which is the defect M15 is about. The rule
    # moved onto what actually collides (``services.placement``) and is asked per end
    # below, once each end's parameters have been validated.

    meta = installed[transport_name]
    transport = profile(transport_name)

    entry_minted = keymaterial.mint(meta.key_material, KeyScope.NODE)
    leaf_minted = keymaterial.mint(meta.key_material, KeyScope.NODE)

    # Values the transport DECLARED as symmetric are minted once and copied, never
    # minted twice. See ``KeySpec.shared_between_peers``: nothing here recognises the
    # field by name, so a future transport with a different symmetric value works
    # unchanged.
    for spec in meta.key_material:
        if spec.scope is not KeyScope.NODE or not spec.shared_between_peers:
            continue
        for side in ("params", "secrets"):
            entry_side = getattr(entry_minted, side)
            if spec.name in entry_side:
                getattr(leaf_minted, side)[spec.name] = entry_side[spec.name]

    # Both ends' secrets, gathered once: a refusal at either end is composed from a
    # mapping that holds one of them, and a symmetric value is the same string in both.
    withheld_values = [*entry_minted.secrets.values(), *leaf_minted.secrets.values()]

    ends = []
    for node, supplied, minted, purpose in (
        (entry_node, entry_params, entry_minted, TransportPurpose.RELAY_ENTRY),
        (leaf_node, leaf_params, leaf_minted, TransportPurpose.RELAY_LEAF),
    ):
        merged = {**supplied, **minted.params, **minted.secrets}
        try:
            validated = transport.validate(merged)
        except ValidationError as exc:
            # Kept PER FIELD as well as flattened into the sentence. A caller with a
            # form has somewhere to put "this box, this reason", and one sentence at the
            # top of a twenty-four-box form makes the operator hunt for the parameter
            # the prose names. See ``HopEndRefused``.
            #
            # Never the VALUES of the mapping: at this point it holds the private keys
            # just minted for BOTH ends, and a validator's complaint may quote what it
            # was given whichever field it names. It is not enough to assume it quotes
            # only what the operator typed — that assumption is what
            # ``refused_fields`` was written to stop relying on, so every minted secret
            # is struck out of every sentence here, before ``fields`` or the flattened
            # message reaches a caller that renders either without choosing to.
            fields = refused_fields(exc, withholding=withheld_values)
            problems = "; ".join(
                f"{where}: {message}" for where, message in fields.items()
            )
            raise HopEndRefused(
                f"transport {transport_name!r} rejected the {_end_word(purpose)} end's "
                f"parameters — {problems}",
                purpose=str(purpose),
                fields=fields,
            ) from exc

        # This end's collisions on ITS OWN node, in the same one place the enable route
        # asks — M15. Per end rather than per hop: the two ends are on two different
        # nodes and each is placed against whatever that node already runs.
        config_name = await placement.claim(
            session, node=node, transport_name=transport_name, params=validated
        )

        secret_keys = set(minted.secrets)
        ends.append(
            NodeTransport(
                node_id=node.id,
                transport_name=transport_name,
                config_name=config_name,
                params={k: v for k, v in validated.items() if k not in secret_keys},
                secrets=json.dumps(
                    {k: v for k, v in validated.items() if k in secret_keys}
                ),
                purpose=purpose,
                # A hop is never in a subscription, so ``enabled`` says only that the
                # tunnel should be running.
                enabled=True,
            )
        )

    entry_end, leaf_end = ends

    # Rendered before anything is written. ``edge.relay`` refuses the combinations that
    # would produce two valid files and no tunnel — ends on different networks, both
    # ends on one address, mismatched symmetric material — and refusing here means the
    # operator's mistake costs them a form submission rather than a dead exit.
    try:
        edge_relay.render_hop(
            transport_name,
            entry=edge_relay.HopEnd(
                node=nodes.node_view(entry_node),
                params={**entry_end.params, **json.loads(entry_end.secrets)},
            ),
            leaf=edge_relay.HopEnd(
                node=nodes.node_view(leaf_node),
                params={**leaf_end.params, **json.loads(leaf_end.secrets)},
            ),
        )
    except edge_relay.HopNotRenderable as exc:
        raise DomainError(HOP_WOULD_NOT_WORK.format(reason=exc)) from exc

    session.add_all(ends)
    await session.flush()
    entry_end.peer_node_transport_id = leaf_end.id
    leaf_end.peer_node_transport_id = entry_end.id
    # Which two nodes, by the names the operator gave them, in the order the tunnel
    # runs: the entry dials, the leaf waits. Neither end's parameters and neither
    # node's address — a hop's twenty-two typed values are what this table has no
    # column for, on purpose.
    audit.record(
        session,
        AuditAction.HOP_ESTABLISHED,
        first_label=entry_node.name,
        second_label=leaf_node.name,
    )
    await session.commit()

    logger.info("hop established between nodes %s and %s", entry_node.id, leaf_node.id)
    return entry_end, leaf_end


async def dissolve_hop(session: AsyncSession, *, node_transport_id: str) -> list[str]:
    """Remove both ends of a hop. Returns the node ids that need re-applying.

    Both ends, always. Removing one would leave the other configured to expect a peer
    that is no longer configured — a node still holding a tunnel interface for an exit
    that has been decommissioned.
    """
    end = await session.get(NodeTransport, node_transport_id)
    if end is None:
        raise NotFound("no such transport on any node")
    if end.purpose not in TransportPurpose.relays():
        raise DomainError("that transport is not part of a hop")

    affected = [end.node_id]
    # Read before anything is deleted, and off the loaded rows: both names are gone
    # from this transaction by the time the entry is written, and a label looked up
    # afterwards would be a label that cannot be read.
    # Fetched by id rather than reached through ``end.node``: an eagerly configured
    # relationship is still unloaded on a row this session created itself, and touching
    # it is lazy I/O, which an async session answers with MissingGreenlet.
    labels = [(await nodes.get_node(session, end.node_id)).name, None]
    if end.peer_node_transport_id is not None:
        peer = await session.get(NodeTransport, end.peer_node_transport_id)
        if peer is not None:
            affected.append(peer.node_id)
            labels[1] = (await nodes.get_node(session, peer.node_id)).name
            if end.purpose == TransportPurpose.RELAY_LEAF:
                # Entry first, the way the tunnel runs and the way ``establish_hop``
                # wrote it, so the trail reads the same whichever end the operator
                # happened to tear down from.
                labels.reverse()
            # Unlinked first: with the FK still pointing at a row being deleted in the
            # same flush, the SET NULL and the delete race in an order SQLAlchemy is
            # free to choose.
            peer.peer_node_transport_id = None
            end.peer_node_transport_id = None
            await session.flush()
            await session.delete(peer)
    await session.delete(end)
    # Both ends' node names when there were two, one when the operator is removing what
    # was left of a half hop — which is exactly the case the second label being nullable
    # exists for.
    audit.record(
        session,
        AuditAction.HOP_DISSOLVED,
        first_label=labels[0],
        second_label=labels[1],
    )
    await session.commit()
    logger.info("hop dissolved from node-transport %s", node_transport_id)
    return affected


async def list_hops(session: AsyncSession) -> list[tuple[NodeTransport, NodeTransport | None]]:
    """Every hop, as (entry end, leaf end) pairs, for the panel.

    A half-hop is returned with ``None`` rather than skipped: the operator has to be
    able to SEE that one end is missing, which is the whole reason the foreign key is
    SET NULL rather than CASCADE.
    """
    result = await session.execute(
        select(NodeTransport)
        .where(NodeTransport.purpose == TransportPurpose.RELAY_ENTRY)
        .join(Node)
        .order_by(Node.name)
    )
    pairs = []
    for entry_end in result.scalars().unique():
        peer = (
            await session.get(NodeTransport, entry_end.peer_node_transport_id)
            if entry_end.peer_node_transport_id
            else None
        )
        pairs.append((entry_end, peer))
    return pairs
