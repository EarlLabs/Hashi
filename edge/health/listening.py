"""Is anything actually holding the port a transport was given? — M22.

WHAT: reads a node's LISTENING socket table over SSH, and answers, for one placed
      config, whether something binds its port over every transport-layer protocol the
      transport declared it binds.
WHY:  M22. A container that is up is not a transport that is serving, and the two were
      the same answer. On a real node on 2026-09-13 a proxy was crash-looping on a
      missing certificate with nothing bound on its port, and the panel reported the node
      as serving it on six consecutive probes. ``node_stack.running_containers`` closes
      the crash loop; this closes the other half — a container that starts, binds nothing
      and idles is up for ever and carries nobody, and no reading of the container can
      see that.

      WHY NOT A HANDSHAKE, which is the question the operator is really asking. Two
      reasons, in the order of how far each reaches, and the SECOND is the one that
      settles it. The first is the charter's and it is the sharper of the two where it
      applies: a wg-family handshake table is a list of PEER KEYS with timestamps, which
      is who connected and when, so a probe reading it would be a connection log whatever
      it then did with the bytes. But it applies only to a family that HAS such a table —
      an Xray transport keeps none to read, and asking whether a peer reached it means
      dialling it. Which is the second reason, and the general one: the question cannot
      be asked without naming a protocol — a different command and a different answer per
      transport, in shared code, which core invariants §1 forbids and which is the rule
      keeping "a new protocol is one new package" true. That one covers every transport
      alike, which is why it and not the first is what closes the question. So the
      ceiling on what this may know is deliberate rather than an implementation
      shortfall, and the sentence the operator reads says so
      (``control.app.services.console``).
HOW:  ``ss``, restricted to LISTENING sockets. The restriction is not tidiness: a
      listening socket has no peer — ``ss`` prints ``0.0.0.0:*`` in that column for every
      line — so the output cannot contain an address belonging to a person even
      momentarily, in memory or in a failure message. Nothing here is written anywhere:
      the charter's no-logging rule covers a probe exactly as it covers everything else,
      and a probe is the surface most likely to grow a log by accident.

      ``/proc/net/tcp`` and friends were the alternative and are rejected for that one
      reason. They need no tool installed at all, which is a real advantage on a host
      nobody has audited — and they list every ESTABLISHED connection with its remote
      address. Reading a person's address in order to discard it is not a thing this
      project does.

      WHICH protocols to ask about is ``TransportMeta.listens_on``, which already exists
      and is already read by ``control`` for the port-collision rule. It is a declaration
      used to CHOOSE a measurement rather than used AS one — the difference M20 turned on.
      A declaration that claims MORE than the container binds is loud and safe: the extra
      protocol's socket is not found, ``is_answering``'s ``all()`` fails, and the probe
      reports nothing listening. A declaration that claims LESS is not caught here at
      all, and saying so is the honest half: this module then checks the protocols it was
      given, finds them held, and reports listening while the undeclared half may be
      dead. What limits that is not this module — it is that the same declaration is what
      M15 reserves a port with, so a transport wrong about its own listener is wrong in a
      place the codebase already reads. Nothing here compares a transport's name to
      anything.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from edge.bootstrap.ssh import NodeConnection
from edge.registry import Layer4

# NO MODULE LOGGER, unlike every other module in this zone, and the absence is the point.
# This one reads a node's socket table; a logger sitting ready beside that is an
# invitation, and the charter's no-logging rule has no "temporarily, while debugging"
# clause. Anything this module ever needs to say, it says by returning it.

# The node's listening sockets, and nothing else on the node.
#
# ``-l`` LISTENING only — see this module's header: it is what makes a peer address
# impossible in the output rather than merely unused. ``-n`` numeric, so a port is a
# number and no name lookup is attempted. ``-t -u`` the two protocols ``Layer4`` names.
#
# No ``-p``: which process holds a socket needs privilege this connection does not have,
# and is not the question. No ``-H``: suppressing the header is an option old iproute2
# does not have, and a node that answered "unrecognized option" would be read as a node
# whose sockets could not be checked. The header is dropped by not parsing as a protocol.
LISTENING_SOCKETS = "ss -l -n -t -u"

# Which whitespace-separated field of one ``ss`` line is which. Its columns are Netid,
# State, Recv-Q, Send-Q, Local Address:Port, Peer Address:Port — and the last is never
# read, by construction and on purpose.
_NETID = 0
_LOCAL = 4
_FIELDS = 5


@dataclass(frozen=True)
class Listener:
    """Where one placed config is expected to answer: a port, and what binds it.

    Built by `control` out of the operator's own parameters and the transport's own
    ``listens_on`` declaration, and passed in — this zone does no database and resolves
    no row, exactly as ``probe``'s ``expected`` is rendered by the caller.
    """

    port: int

    # Every transport-layer protocol that must hold that port for this config to be
    # answering. A set, because a transport may legitimately bind both, and ALL of them
    # have to be there: a transport that declares two and holds one is half up.
    protocols: frozenset[Layer4]


def parse_sockets(output: str) -> dict[Layer4, frozenset[int]]:
    """``ss``'s listening table as protocol → the port numbers bound on it.

    Only the port is taken, never the address, and that is a rule rather than an
    economy: which address a daemon bound is the node's business, and a port is the one
    thing the control plane gave it and can therefore check.

    A line this function does not understand is skipped rather than guessed at — the
    header, an address family ``Layer4`` has no name for, anything a future ``ss``
    adds. Skipping is safe in one direction only, which is why ``bound_ports`` refuses to
    report an EMPTY table as "nothing is listening".
    """
    bound: dict[Layer4, set[int]] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < _FIELDS:
            continue
        try:
            layer4 = Layer4(fields[_NETID])
        except ValueError:
            continue
        # ``rpartition`` because the address half may hold colons of its own: an IPv6
        # socket prints ``[::]:51820``, and one bound to an interface prints
        # ``127.0.0.53%lo:53``. The port is what follows the LAST colon.
        _, _, port = fields[_LOCAL].rpartition(":")
        if not port.isdigit():
            continue
        bound.setdefault(layer4, set()).add(int(port))
    return {layer4: frozenset(ports) for layer4, ports in bound.items()}


async def bound_ports(connection: NodeConnection) -> dict[Layer4, frozenset[int]] | None:
    """What this node is listening on, or ``None`` when that could not be established.

    ``None`` is a third answer and it is the point of this function's shape. "Nothing is
    listening" and "nobody could ask" are different facts with different sentences, and
    collapsing them would report a host without ``ss`` as a fleet-wide outage — which is
    the shape of wrongness this whole milestone is about, pointed the other way.

    Two things produce it. A command that failed at all: no ``ss`` on the host (the shell
    exits 127), or one that refused. And an EMPTY table, which cannot be true of a node
    this code is talking to — we arrived over a listening socket on it, so a reading with
    no listening socket in it is a reading we did not understand, not a node with none.
    That second guard is what stops a future change in ``ss``'s output from silently
    reporting every transport in the fleet as dead.

    Nothing about the reading is logged or stored. See this module's header.
    """
    result = await connection.run(LISTENING_SOCKETS, check=False)
    if result.exit_status != 0:
        return None
    bound = parse_sockets(result.stdout)
    return bound or None


def is_answering(bound: Mapping[Layer4, frozenset[int]], listener: Listener) -> bool:
    """Whether every protocol this config declared holds its port on that node.

    ALL of them, never any: a transport binding both TCP and UDP on one number and
    holding only one is serving half of what it said it would, and reporting it as
    listening would be the M22 defect one protocol in.

    What this establishes is that SOMETHING holds the port — not that it is our
    container. Nothing readable from the node distinguishes them without privilege we do
    not take, and the sentence the operator reads says so rather than implying otherwise.
    """
    return bool(listener.protocols) and all(
        listener.port in bound.get(protocol, frozenset())
        for protocol in listener.protocols
    )


__all__ = ["LISTENING_SOCKETS", "Listener", "bound_ports", "is_answering", "parse_sockets"]
