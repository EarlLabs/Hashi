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

      Nothing here compares a transport name to a literal. ``PORT_FIELD`` is the hop
      contract's vocabulary rather than any protocol's (see ``services.transports``),
      and whether a name is usable as an interface is asked of ``edge``, which owns the
      rule its own tools enforce.
"""

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict
from control.app.models import Node, NodeTransport
from control.app.services.transports import PORT_FIELD
from edge.bootstrap import node_stack

# What an operator is told when the port they chose is already spoken for on that node.
# It names the node, the port and the transport already holding it, because all three
# are the operator's own inventory and the middle one is the box they have to change.
PORT_TAKEN = (
    "node {node!r} already listens on port {port} for {holder!r}. Two transports on one "
    "node cannot share a port — each data plane binds the node's own address — so give "
    "this one a different port."
)

# What an operator is told when a node cannot take another instance of one transport
# because there is no legal name left for its config file. Unreachable for every
# transport this image ships, and stated rather than assumed away: the wg-quick family's
# interface names are capped at 15 characters by the kernel, so a long transport name
# runs out of suffixes.
NO_NAME_LEFT = (
    "node {node!r} cannot take another {transport!r}: this transport's tool takes its "
    "network interface name from its config file, and every name that would fit on this "
    "node is already used. Remove one before adding another."
)

# How many instances of one transport a node may be asked for before the names run out.
# Not a policy on how many are sensible — that is the operator's business and the ports
# are the real limit — but a bound on the search, so a node with a corrupt row cannot
# turn this into an unbounded loop.
_MOST_INSTANCES = 16


def port_of(params: Mapping[str, object]) -> object | None:
    """The port this row will listen on, or ``None`` for a transport that names none.

    Read out of the transport's own validated parameters under the one field name this
    zone knows. A transport that declares no port has nothing to collide over and is
    not constrained here — which is also what the database's partial uniqueness over
    ``params ->> 'port'`` says, since a missing key is NULL and Postgres treats NULLs
    as distinct.
    """
    return params.get(PORT_FIELD)


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
    port: object | None,
    excluding: str | None = None,
) -> None:
    """Refuse a port another transport on this node has already claimed.

    ``excluding`` is the row being changed, on the path that retypes a port rather than
    creating one — without it a row would collide with itself and no port could ever be
    replaced by the value it already has.
    """
    if port is None:
        return
    for row in await _rows_on(session, node.id, excluding=excluding):
        if port_of(row.params) == port:
            raise Conflict(
                PORT_TAKEN.format(node=node.name, port=port, holder=row.transport_name)
            )


async def claim(
    session: AsyncSession, *, node: Node, transport_name: str, params: Mapping[str, object]
) -> str:
    """Refuse what this row would collide with, and answer with the name it takes.

    Called once per row, after the transport has validated its parameters — so the port
    asked about is the one that will be stored, including one the transport defaulted
    rather than one the operator typed — and before anything is written.

    Nothing is committed here and nothing is reserved: the caller adds its row in the
    same transaction, and the database holds the same two rules as constraints
    (``NodeTransport.__table_args__``) so a race loses at the flush rather than
    silently producing a node that cannot start.
    """
    await port_is_free(session, node=node, port=port_of(params))

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
