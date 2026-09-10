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

from control.app.errors import Conflict, DomainError, HopEndRefused, NotFound
from control.app.models import Node, NodeTransport, TransportPurpose
from control.app.services import keymaterial, nodes
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
    four surfaces later: this closes ``fields``, the flattened message, the console, the
    pre-redesign page's outcome fragment and the API envelope at once. The console's
    allow-list stays as the second line of defence.

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
    """
    values = sorted(
        {str(value) for value in withholding if value is not None and value != ""},
        key=len,
        reverse=True,
    )
    fields: dict[str, str] = {}
    for error in exc.errors():
        where = _without(".".join(str(part) for part in error["loc"]), values)
        fields.setdefault(where, _without(_plainly(error["msg"]), values))
    return fields


def _without(text: str, values: list[str]) -> str:
    """One sentence with every held value struck out of it."""
    for value in values:
        text = text.replace(value, WITHHELD)
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

    for node in (entry_node, leaf_node):
        existing = await session.execute(
            select(NodeTransport)
            .where(NodeTransport.node_id == node.id)
            .where(NodeTransport.transport_name == transport_name)
        )
        if existing.scalars().first() is not None:
            raise Conflict(
                f"{transport_name!r} is already configured on node {node.name!r}"
            )

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

        secret_keys = set(minted.secrets)
        ends.append(
            NodeTransport(
                node_id=node.id,
                transport_name=transport_name,
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
        raise DomainError(f"these two ends would not form a working tunnel: {exc}") from exc

    session.add_all(ends)
    await session.flush()
    entry_end.peer_node_transport_id = leaf_end.id
    leaf_end.peer_node_transport_id = entry_end.id
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
    if end.peer_node_transport_id is not None:
        peer = await session.get(NodeTransport, end.peer_node_transport_id)
        if peer is not None:
            affected.append(peer.node_id)
            # Unlinked first: with the FK still pointing at a row being deleted in the
            # same flush, the SET NULL and the delete race in an order SQLAlchemy is
            # free to choose.
            peer.peer_node_transport_id = None
            end.peer_node_transport_id = None
            await session.flush()
            await session.delete(peer)
    await session.delete(end)
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
