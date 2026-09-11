"""What two transports on one node cannot share — M15.

WHAT: the one answer to "may this transport be placed on this node, and under what
      name", asked by every path that writes a ``NodeTransport`` row or changes the
      parameters of one.
WHY:  the rule used to be one row per ``(node, transport_name)``, which is not what
      collides. It made the runbook's own advice impossible to follow: AmneziaWG is
      MANDATED for the entry→leaf hop and RECOMMENDED for friends on the same box, so
      whichever was enabled first excluded the other — permanently, because there is
      no delete for a node transport (M15.2 is the exit). What actually collides on a
      host is the listening port, because the data planes run with
      ``network_mode: host``, and the config file's name, because ``edge`` derives the
      wg-quick family's network interface from it.
HOW:  one function, ``claim``, called just before a row is written, plus ``port_is_free``
      for the path that retypes a port on a row that already exists. Both read the
      node's existing rows and nothing else. The refusal is a ``Conflict`` — 409, the
      status the old duplicate refusal answered with, so no caller's envelope changes.

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
      rather than leaving as an inference from the paragraph above. ``claim`` and
      ``port_is_free`` look at the node's rows and decide; nothing serialises them, so two
      enables submitted at the same instant could both find a port free and both take it.
      The config name cannot go that way — it loses at the flush, because the schema holds
      it. This is accepted rather than closed: the charter's product is one operator on one
      console, the window is the few milliseconds between the read and the commit, and the
      symptom is legible (a second container that will not bind, on a node that has not
      been applied yet). The repair is to remove one of the two rows and apply again. A
      lock here would be a row-level lock on a table the delivery endpoint reads, taken on
      every enable, to close a race one person cannot have with themselves.

      Nothing here compares a transport name to a literal. ``PORT_FIELD`` is the hop
      contract's vocabulary rather than any protocol's (see ``services.transports``),
      and both "would this name work as an interface" and "what does this bind" are
      asked of ``edge``, which owns those facts.
"""

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict
from control.app.models import Node, NodeTransport
from control.app.services.transports import PORT_FIELD
from edge.bootstrap import node_stack
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
# There is deliberately no "remove one and try again" in this sentence: until M15.2
# lands there is no delete for a node transport, and a refusal that names an action the
# product does not have sends the operator looking for a button. It says what is true
# today — another node — and M15.2 is where the second answer appears.
NO_NAME_LEFT = (
    "node {node!r} cannot take another {transport!r}: this transport's tool takes its "
    "network interface name from its config file, and every name that would fit on this "
    "node is already used. Put this one on another node."
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
    exists to close. Removing a row is what frees its port, and making a row removable
    is M15.2.
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


async def claim(
    session: AsyncSession, *, node: Node, transport_name: str, params: Mapping[str, object]
) -> str:
    """Refuse what this row would collide with, and answer with the name it takes.

    Called once per row, after the transport has validated its parameters — so the port
    asked about is the one that will be stored, including one the transport defaulted
    rather than one the operator typed — and before anything is written.

    Nothing is committed here and nothing is reserved: the caller adds its row in the
    same transaction, and the config name it answers with is held by a unique constraint
    in the schema too (``NodeTransport.__table_args__``), so a race loses at the flush
    rather than silently producing a node with two configs at one path. THE PORT ANSWER
    HAS NO SUCH BACKSTOP — it is a read, and this module's header says what that costs
    and why it is accepted.
    """
    await port_is_free(
        session, node=node, transport_name=transport_name, port=port_of(params)
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
