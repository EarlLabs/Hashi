"""What two transports on one node cannot share — M15.

WHAT: the one answer to "may this transport be placed on this node, and under what
      name", asked by every path that writes a ``NodeTransport`` row or changes the
      parameters of one.
WHY:  the rule used to be one row per ``(node, transport_name)``, which is not what
      collides. It made the runbook's own advice impossible to follow: AmneziaWG is
      MANDATED for the entry→leaf hop and RECOMMENDED for users on the same box, so
      whichever was enabled first excluded the other — permanently, because at the time
      there was no delete for a node transport (``nodes.remove_transport`` is that exit
      and arrived with M15.2). What actually collides on a host is the listening port,
      because the data planes run with ``network_mode: host``, and the config file's
      name, because ``edge`` derives the wg-quick family's network interface from it.

      AND — M17.1c — THE TUNNEL'S OWN RANGE, which is the third thing and the one with
      a victim. Two tunnels on one node whose ranges meet can hand two different people
      the same address; their data planes share that host's single routing table, so a
      reply meant for one person's device is sent to the other's. It is not a conflict
      any file shows: each config is individually valid, and the renderers' own
      ``AmbiguousPeerRoute`` reads ONE file and therefore cannot see the second
      interface at all. It is caught here or nowhere.
HOW:  one function, ``claim``, called just before a row is written, plus ``port_is_free``
      and ``tunnel_network_is_free`` for the path that retypes those values on a row that
      already exists. All of them read the node's existing rows and nothing else. The
      refusal is a ``Conflict`` — 409, the status the old duplicate refusal answered with,
      so no caller's envelope changes.

      A PORT NUMBER IS NOT A PORT. Two transports collide only when they bind the same
      number over the same transport-layer protocol: a TCP proxy on 8443 and an
      obfuscated UDP tunnel on 8443 are two sockets, and the runbook puts that pair
      within reach by naming 8443 as a Reality port. Which protocols a transport binds
      is asked of ``TransportMeta.listens_on`` — a declaration added in `edge` for this,
      because ``family`` is free text the contract says `control` reads *"to decide
      nothing at all"*, and a rule keyed on it would be a rule expressed in terms of the
      wrong concept, which is the very defect M15 is closing.

      WHY THE PORT RULE IS NOT A DATABASE CONSTRAINT, while the config name is. Postgres
      cannot answer "do these two rows bind overlapping protocols" without a stored copy
      of a transport package's own declaration on every row — and a stored copy of
      somebody else's declaration goes stale the day they change it. This codebase
      already makes that call the same way for ``config_format``, which is asked of the
      registry at every render rather than written into ``node_transports``. So the
      config name — which is ours to choose and true of the row — is a constraint, and
      the port rule lives here, in the one function every writing path goes through.

      WHICH MEANS THE PORT RULE IS A READ AND NOT A LOCK, and that is worth saying plainly
      rather than leaving as an inference from the paragraph above. The tunnel-range rule
      is the same shape and has no constraint behind it either, for the same reason — a
      range is a value of the transport's own JSONB and Postgres cannot be asked whether
      two of them meet. ``claim``, ``port_is_free`` and ``tunnel_network_is_free`` look at
      the node's rows and decide; nothing serialises them, so two
      enables submitted at the same instant could both find a port free and both take it.
      The config name cannot go that way — it loses at the flush, because the schema holds
      it. For the PORT this is accepted rather than closed: the charter's product is one
      operator on one console, the window is the few milliseconds between the read and the
      commit, and the symptom is legible (a second container that will not bind, on a node
      that has not been applied yet). The repair is to remove one of the two rows and
      apply again. A lock here would be a row-level lock on a table the delivery endpoint
      reads, taken on every enable, to close a race one person cannot have with themselves.

      THE RANGE RULE IS LEFT OPEN ON DIFFERENT TERMS, AND THEY ARE WORSE. Do not read the
      paragraph above as covering it: a lost port race announces itself and a lost RANGE
      race is silent and permanent. Two interfaces come up, each config file is correct on
      its own, ``AmbiguousPeerRoute`` reads one file and cannot see the other, and
      ``uq_credential_tunnel_address`` is scoped ``(node_transport_id, digest)`` with the
      digest keyed by the row id — so one address on two rows is two digests in two scopes
      and the constraint cannot see it either. Nothing re-checks on read, render, apply or
      migration, so the state this rule exists to forbid, once it exists, is invisible on
      every screen while two people are handed one address. It is left open because the
      probability is genuinely small for one operator on one console — and because closing
      it means a per-node lock taken by every writer of that node's rows, which
      ``relay.establish_hop`` takes on TWO nodes at once, so it would need a fixed lock
      order or two hops laid in opposite directions deadlock. That is the trade, written
      down (``docs/decisions.md``, 2026-09-13) rather than inherited from the port.

      Nothing here compares a transport name to a literal. ``PORT_FIELD`` is the hop
      contract's vocabulary rather than any protocol's (see ``services.transports``),
      and "would this name work as an interface", "what does this bind" and "do these two
      ranges meet" are all asked of ``edge``, which owns those facts. WHICH parameter
      holds a row's tunnel range is asked of the transport's own declaration
      (``TransportMeta.peer_address``, through ``services.addresses``), so this module
      names no address field either.
"""

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict
from control.app.models import Node, NodeTransport, TransportPurpose
from control.app.services import addresses, delivery
from control.app.services.transports import PORT_FIELD
from control.app.settings import Settings
from edge.addressing import networks_overlap
from edge.bootstrap import delivery_site, node_stack
from edge.registry import Layer4, discover, profile

# What an operator is told when the port they chose is already spoken for on that node.
# It names the node, the port, the protocol and the transport already holding it: all
# four are the operator's own inventory, the port is the box they have to change, and the
# protocol is what makes the refusal true rather than merely cautious.
PORT_TAKEN = (
    "node {node!r} already listens on {protocol} port {port} for {holder!r}. Two "
    "transports on one node cannot share a port over the same protocol — each data plane "
    "binds the node's own address — so give this one a different port."
)

# What an operator is told when a node cannot take another instance of one transport
# because there is no legal name left for its config file. Unreachable for every
# transport this image ships, and stated rather than assumed away: the wg-quick family's
# interface names are capped at 15 characters by the kernel, so a long transport name
# runs out of suffixes.
# It names BOTH answers since M15.2, which is the step that made the first one true: a
# node transport can be removed, and removal is what gives its name back. Until then the
# sentence deliberately offered only another node, because a refusal that names an action
# the product does not have sends the operator looking for a button.
NO_NAME_LEFT = (
    "node {node!r} cannot take another {transport!r}: this transport's tool takes its "
    "network interface name from its config file, and every name that would fit on this "
    "node is already used. Remove one of them from this node, or put this one on another."
)

# What an operator is told when the tunnel they typed shares a range with another of this
# node's tunnels — M17.1c. It names both ranges as the operator typed them and the
# transport already holding one: all three are that operator's own inventory, already on
# the Keys & configs screen, and none of them is an address any person holds. The middle
# sentence is the whole reason this refusal exists, and it is stated rather than implied,
# because the failure it stands in front of looks like nothing at all — two valid files,
# two interfaces that come up, and one user's traffic arriving at another's device.
TUNNEL_TAKEN = (
    "node {node!r} already carries {holder!r} on a tunnel at {held}, and {wanted} is in "
    "the same range. Two tunnels on one node cannot share one: their data planes write "
    "into that host's single routing table, so a reply meant for one person's device "
    "would be sent to whoever holds the same address on the other — and neither config "
    "file shows it, because each is correct on its own. Give this tunnel a range of its "
    "own."
)

# How many instances of one transport a node may be asked for before the names run out.
# Not a policy on how many are sensible — that is the operator's business and the ports
# are the real limit — but a bound on the search, so a node with a corrupt row cannot
# turn this into an unbounded loop.
_MOST_INSTANCES = 16


def port_of(params: Mapping[str, object]) -> str | None:
    """The port this row will listen on, as text, or ``None`` for a row that names none.

    Read out of the transport's own validated parameters under the one field name this
    zone knows. A transport that names no port has nothing to collide over and is not
    constrained here.

    AS TEXT, and that is not tidiness. ``params`` is JSONB the transport owns: every
    shipped transport declares its port as an ``int`` and pydantic coerces a typed form
    field into one, but nothing in this zone requires that — a transport declaring it a
    string would give ``8443`` and ``"8443"`` as two different values to ``==``, the
    service would find no collision, and the two daemons would meet on the node. One
    comparison for every transport, whatever shape it stores.
    """
    port = params.get(PORT_FIELD)
    return None if port is None else str(port)


def binds_of(transport_name: str) -> frozenset[Layer4]:
    """Which transport-layer protocols this transport's listener binds.

    Asked of the transport's own declaration every time rather than stored on the row,
    for the reason in this module's header: a copy of somebody else's declaration goes
    stale the day they change it, and this is the same call the codebase already makes
    for ``config_format``.
    """
    return profile(transport_name).meta.listens_on


async def _rows_on(
    session: AsyncSession, node_id: str, *, excluding: str | None = None
) -> list[NodeTransport]:
    """Every transport row on one node, whatever it is for and whether or not it is on.

    ENABLED IS NOT CONSULTED, deliberately. A disabled row is a transport an operator
    switched off and will switch back on, and its port and its interface name are still
    reserved for it — letting a second row take them would move the collision to the
    moment the first is re-enabled, which is the same "found months later" failure M15
    exists to close. Removing a row is what frees its port, and removing one is
    ``nodes.remove_transport`` (M15.2) — the exit this rule always assumed.
    """
    result = await session.execute(
        select(NodeTransport).where(NodeTransport.node_id == node_id)
    )
    return [row for row in result.scalars().unique() if row.id != excluding]


def _candidate_names(transport_name: str) -> list[str]:
    """The names a config could be placed under on one node, best first.

    The transport's own name first, which is what every row written before M15 holds and
    what every node in the field already has on disk — so a first instance keeps the
    file it has always had and nothing is renamed under a running daemon. After that a
    numbered suffix, which is readable on the node (``awg show`` prints the interface)
    and stays inside the kernel's 15 characters for one more instance than anybody will
    want.
    """
    return [transport_name, *(f"{transport_name}-{n}" for n in range(2, _MOST_INSTANCES + 1))]


async def port_is_free(
    session: AsyncSession,
    *,
    node: Node,
    transport_name: str,
    port: str | None,
    excluding: str | None = None,
) -> None:
    """Refuse a port another transport on this node already binds over the same protocol.

    ``excluding`` is the row being changed, on the path that retypes a port rather than
    creating one — without it a row would collide with itself and no port could ever be
    replaced by the value it already has.

    TRANSPORT AGAINST TRANSPORT ONLY. The socket a delivery host's own listener holds is
    ``delivery_socket_is_free`` below, a separate call for a separate holder — every
    caller of this one makes that one too.

    A row whose transport this image no longer ships is skipped rather than guessed at:
    nothing can say what it binds, and inventing an answer would either refuse a port
    that is free or allow one that is not. Such a node cannot be rendered or applied at
    all (``apply.render_for_node`` raises for it), so the operator meets it there, with a
    sentence about the missing package rather than about a port.
    """
    if port is None:
        return
    installed = discover()
    if transport_name not in installed:
        return
    binds = binds_of(transport_name)
    for row in await _rows_on(session, node.id, excluding=excluding):
        if port_of(row.params) != port or row.transport_name not in installed:
            continue
        shared = binds & binds_of(row.transport_name)
        if shared:
            raise Conflict(
                PORT_TAKEN.format(
                    node=node.name,
                    protocol="/".join(sorted(shared)).upper(),
                    port=port,
                    holder=row.transport_name,
                )
            )


# What an operator is told when the port they chose is the one their users refresh their
# configuration on — M27.6, and the owner's decision of 2026-09-27 that delivery gets it.
#
# It names what holds the port rather than saying "reserved", because the thing holding
# it is not a transport and does not appear in the operator's own inventory of this node:
# a refusal that named nothing would read as a bug. And it states the COST of the repair
# in the same breath, because the repair is not free and the operator is the only one who
# can weigh it — on an entry node the transport this refuses is usually the one whose
# camouflage is being on the port an ordinary website is on.
PORT_IS_DELIVERYS = (
    "node {node!r} answers its own users' subscription refreshes on {protocol} port "
    "{port}, so no transport on it can hold that port. That endpoint is what somebody "
    "fetches a new configuration from at the moment a node has been blocked, so it has "
    "to be on the port an ordinary HTTPS client reaches. Give this transport another "
    "port — and weigh what that costs here, because a TLS transport answering on an "
    "unusual port is itself a signal. A host that is not to serve refreshes of its own "
    "is one with no user-facing transport on it."
)


async def delivery_socket_is_free(
    session: AsyncSession,
    *,
    node: Node,
    transport_name: str,
    port: str | None,
    settings: Settings,
    purpose: TransportPurpose = TransportPurpose.USERS,
    excluding: str | None = None,
) -> None:
    """Refuse a transport that would fight this node's own delivery listener — M27.6.

    THE THIRD OCCUPANT OF A TABLE THAT ALREADY HAD TWO, and that is why it is here
    rather than anywhere else. A delivery host runs one more container on the node's
    real interface, exactly as every data plane does, and the rule that two things on
    one node cannot hold one socket is this module's. What is new is only that the third
    occupant is not a row an operator can see, so the refusal has to name it.

    WHICH SOCKET IS ASKED OF ``edge``. ``delivery_site.DELIVERY_PORT`` is that zone's
    measurement of what its own rendered site binds, not a number chosen here — nothing
    in this file may name a port, and a copy of that one would be the drift this module's
    header refuses for ``config_format`` and for ``listens_on``.

    WHETHER THIS NODE IS ONE IS ``delivery.listener_for``, the same call the apply makes
    and the same one the Nodes screen composes its sentence from — so the refusal and the
    screen cannot come to different views of one host. A fleet holding no certificate
    serves no refreshes from anywhere, and reserving the socket there would tax every
    operator who never asked for the feature with a sentence that is not true of their
    fleet: the screen would say "not served from any host" while the form said the host
    answers refreshes on that port.

    It is the DATABASE and CONFIGURATION halves of the question and never the reading of
    the host: this runs on a form submission, and a check that dialled the node would make
    enabling a transport depend on the host being up. The over-answer is the co-located
    box, where the control plane's own Caddy holds the same port for the panel — so the
    refusal is true there too, for a different holder.

    THE ORDERING HAZARD IS CLOSED ELSEWHERE, deliberately. An operator can put a
    transport on this socket while no certificate is configured and add one afterwards,
    and this check cannot see the future. What catches it is the apply: the delivery
    service is watched like every other container on the node, so a listener that cannot
    bind leaves the node degraded with the port named — rather than being pre-empted here
    by a refusal nobody could act on yet.

    IT READS ``_rows_on`` AND THEREFORE IGNORES ``enabled``, unlike the same row question
    asked during an apply (``delivery.may_serve_delivery``, which is handed the rows that
    apply is pushing). That is this module's own rule rather than a divergence from that
    one: a disabled row still holds its port and its name, because freeing them would
    move the collision to the moment somebody switches it back on. A node whose only
    user-facing row is switched off is not serving refreshes today and will be the
    instant it is switched on, so the socket is held for it here — while the apply, which
    is describing a host as it is about to be, reads what is actually enabled.

    BOTH DIRECTIONS, because a node becomes a delivery host by gaining a user-facing row
    and not only by being one already. Enabling something on the port is refused when the
    node carries users; enabling a user-facing row is refused when something already
    holds the port. Without the second, the two rows could be created in the order that
    passes and the collision would appear on the node, at apply, as a container that
    will not bind.
    """
    try:
        if delivery.listener_for(node, settings) is None:
            # Nothing would answer refreshes here — no name a certificate can be issued
            # for, or no usable certificate anywhere in the fleet — so this node's ports
            # are entirely its transports'.
            return
    except delivery.DeliveryCertificateUnusable:
        # A configured pair this control plane cannot load. It is a fleet-wide fault with
        # a sentence of its own on the Nodes screen, and it is not this form's to answer:
        # refusing a port over it would be a second report of one problem, on a screen
        # that cannot fix it. No host serves delivery in that state either.
        return
    rows = await _rows_on(session, node.id, excluding=excluding)
    claiming_users = purpose == TransportPurpose.USERS
    if not claiming_users and not any(
        row.purpose == TransportPurpose.USERS for row in rows
    ):
        return

    def refuse() -> None:
        raise Conflict(
            PORT_IS_DELIVERYS.format(
                node=node.name,
                protocol=str(delivery_site.DELIVERY_LAYER4).upper(),
                port=delivery_site.DELIVERY_PORT,
            )
        )

    if _holds_the_delivery_socket(transport_name, port):
        refuse()
    # AND THE OTHER DIRECTION, BUT ONLY WHEN THIS CLAIM IS WHAT CREATES THE COLLISION.
    # A node becomes a delivery host by gaining a user-facing row, so a user-facing row
    # arriving on a host where something already holds the socket is refused here rather
    # than discovered on the node as a container that will not bind.
    #
    # It is NOT asked of every other claim on such a node, and the narrowing is the rule
    # that a refusal is about what was submitted. A node whose rows already collide can
    # only have been written before this check existed; answering an operator laying a
    # HOP with a sentence about a user-facing transport they did not touch, on a form
    # that cannot fix it, is the defect M23's thirteenth round found in the revocation
    # banner — a true sentence that sends somebody nowhere.
    if claiming_users:
        for row in rows:
            if _holds_the_delivery_socket(row.transport_name, port_of(row.params)):
                refuse()


def _holds_the_delivery_socket(transport_name: str, port: str | None) -> bool:
    """Would this transport, on this port, bind the socket a delivery listener holds.

    A row whose transport this image no longer ships is skipped for ``port_is_free``'s
    reason: nothing can say what it binds, and inventing an answer would either refuse a
    port that is free or allow one that is not.
    """
    if port != str(delivery_site.DELIVERY_PORT) or transport_name not in discover():
        return False
    return delivery_site.DELIVERY_LAYER4 in binds_of(transport_name)


def tunnel_of(transport_name: str, params: Mapping[str, object]) -> str | None:
    """The address describing this row's tunnel range, or ``None`` for a row with none.

    Read under the name the TRANSPORT declared (``PeerAddress.within`` — the parameter
    whose network says how much room there is), so this module learns no field name and a
    transport that calls its interface address something else is compared the same way.

    ``None`` for a transport that hands its consumers no address of their own, and for one
    this image does not ship: neither has a range this rule can be stated about, and the
    second is skipped for ``port_is_free``'s reason — nothing can say what it holds, and
    inventing an answer would either refuse a range that is free or allow one that is not.
    """
    spec = addresses.spec_for(transport_name)
    if spec is None:
        return None
    value = params.get(spec.within)
    return None if value is None else str(value)


async def tunnel_network_is_free(
    session: AsyncSession,
    *,
    node: Node,
    transport_name: str,
    params: Mapping[str, object],
    excluding: str | None = None,
) -> None:
    """Refuse a tunnel range another of this node's tunnels already covers — M17.1c.

    EVERY ROW ON THE NODE, hop ends and withdrawn rows included, which is ``_rows_on``'s
    own rule and is load-bearing twice here. A hop end is a tunnel on that host exactly as
    a user-facing row is — the runbook puts both on the entry node — and its interface
    is up whether or not anybody is offered it. A withdrawn row keeps its range for the
    same reason it keeps its port: switching it back on must not be the moment the
    collision appears.

    ``excluding`` is the row being changed, on the path that retypes a range rather than
    creating one — without it a row would overlap itself and no range could ever be
    replaced by the one it already has.

    Whether two ranges meet is ``edge.addressing.networks_overlap``'s answer, asked of the
    whole network each address describes rather than of the two addresses: the question is
    about what may be HANDED OUT. ``10.66.0.1/24`` and ``10.66.9.1/24`` are different
    ranges; ``10.66.0.1/24`` and ``10.66.0.9/16`` are not, and the second pair is the one
    an operator writes by accident.
    """
    wanted = tunnel_of(transport_name, params)
    if wanted is None:
        return
    for row in await _rows_on(session, node.id, excluding=excluding):
        held = tunnel_of(row.transport_name, row.params)
        if held is None or not networks_overlap(wanted, held):
            continue
        raise Conflict(
            TUNNEL_TAKEN.format(
                node=node.name, holder=row.transport_name, held=held, wanted=wanted
            )
        )


async def claim(
    session: AsyncSession,
    *,
    node: Node,
    transport_name: str,
    params: Mapping[str, object],
    settings: Settings,
    purpose: TransportPurpose = TransportPurpose.USERS,
) -> str:
    """Refuse what this row would collide with, and answer with the name it takes.

    Called once per row, after the transport has validated its parameters — so the port
    asked about is the one that will be stored, including one the transport defaulted
    rather than one the operator typed — and before anything is written.

    Nothing is committed here and nothing is reserved: the caller adds its row in the
    same transaction, and the config name it answers with is held by a unique constraint
    in the schema too (``NodeTransport.__table_args__``), so a race loses at the flush
    rather than silently producing a node with two configs at one path. THE PORT AND THE
    TUNNEL RANGE HAVE NO SUCH BACKSTOP — both are reads, and this module's header says
    what that costs and why it is accepted.
    """
    await port_is_free(
        session, node=node, transport_name=transport_name, port=port_of(params)
    )
    # And against the one occupant of this node's sockets that is not a row — M27.6.
    # After the transport-against-transport rule, so a row that collides with both is
    # answered about the one whose holder the operator can see on their own screen.
    await delivery_socket_is_free(
        session,
        node=node,
        transport_name=transport_name,
        port=port_of(params),
        settings=settings,
        purpose=purpose,
    )
    # AFTER the port and before the name, so a request that gets both wrong is answered
    # about the port first — the older refusal, the one every existing caller asserts on.
    # This is where establishing a hop meets the rule as well: ``relay.establish_hop``
    # claims each end on its own node, so a hop laid over a node's user-facing tunnel is
    # refused with the form still in front of the operator.
    await tunnel_network_is_free(
        session, node=node, transport_name=transport_name, params=params
    )

    taken = {row.config_name for row in await _rows_on(session, node.id)}
    first, *rest = _candidate_names(transport_name)
    if first not in taken:
        # The transport's own name is taken VERBATIM and is not measured against the
        # interface rule. A transport whose own name the kernel will not accept has
        # always been refused at render time instead (``services_for`` →
        # ``UnrunnableTransport``, which names the transport as the thing to fix), and
        # moving that refusal here would be a second answer to a question `edge` already
        # answers — and a new refusal on a path M15 is not about.
        return first
    for candidate in rest:
        # The suffixed names ARE ours to choose, so they are measured: the wg-quick
        # family's tool takes its interface name from this string and the kernel caps it
        # at 15 characters, so a long transport name runs out of room here rather than
        # on the node.
        if candidate not in taken and node_stack.config_name_is_usable(
            transport_name, candidate
        ):
            return candidate

    raise Conflict(NO_NAME_LEFT.format(node=node.name, transport=transport_name))
