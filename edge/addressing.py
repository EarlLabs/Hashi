"""Who holds which address inside one tunnel — M17.

WHAT: the arithmetic behind a pool of tunnel addresses. ``pool`` enumerates one,
      ``pool_problem`` says in a single sentence why an operator's pool cannot work,
      ``carriage_problem`` says why one address already in somebody's hands could not be
      carried by a proposed tunnel, ``host_of`` gives one address's canonical bare host,
      and ``networks_overlap`` answers whether two tunnels would share a range.
WHY:  M17, found in the field. ``peer_tunnel_address`` was a single operator parameter,
      so a WireGuard-family transport had exactly one address to give out and therefore
      exactly one friend — against a charter scale of ~30-50. The renderers' refusal to
      put two peers on one address (``AmbiguousPeerRoute``) is right and is untouched:
      on a WireGuard server ``AllowedIPs`` is the authorisation list AND the routing
      table, so a shared address is a silent hijack of the first friend's return path.
      What was missing is where the second address comes from.

      **The second argued exception to "a transport is one directory", beside
      ``egress.py``, and it is argued on the same two grounds.** Nothing here is
      protocol-specific: adding one to an address, asking whether a range has room for
      a run of them, and asking whether two ranges meet are true of every tunnel that
      hands addresses out, and a copy per package is how two copies come to disagree
      about which addresses are usable. And the overlap rule is inherently
      cross-transport — it compares the rows of DIFFERENT transports on one node, whose
      data planes share that host's routing table — so no single transport's package is
      a place it could live at all.
HOW:  pure, like everything in this zone: values in, values out. No I/O, no database,
      no clock, no randomness, and nothing here reads an address, an interface or a
      routing table off any machine.

      **It takes values, never field names.** The caller passes addresses; WHICH
      parameter they were read from is the transport's own declaration
      (``registry.PeerAddress``). So this module never learns that a field is called
      ``peer_tunnel_address``, and a transport that names it something else is served
      by the same arithmetic without an edit here.

      **It never builds a pool in order to measure one.** Every question about room is
      answered from the addresses themselves, so a pool sized in the millions costs
      what a pool of three costs. ``pool`` itself is lazy for the same reason: the
      caller almost always wants the next free address, not a list.

      **It hardcodes no range, not even a private one.** Every bound comes from the
      address the operator typed; ``is_private`` is the standard library's answer about
      an address it was handed, never a range written down here. ``CLAUDE.md``: a
      hardcoded range is a network you cannot rotate away from.
"""

import ipaddress
from collections.abc import Iterator

# A prefix long enough that the network has no address to spare for naming itself.
# RFC 3021 gives a /31 two usable hosts and no broadcast; a /32 is one host. Below that
# length the first and last addresses of the range are not hosts, and a device handed
# one of them cannot be reached — which is why the rule is stated as a prefix length
# rather than as a pair of addresses.
#
# Consulted in exactly three places in ``pool_problem``, and nowhere else: the
# network-address refusal, the broadcast-address refusal, and the room left in the
# "runs past the end" sentence. Every other refusal there applies at any prefix length.
# The count is written down because a guard nothing exercises is a guard that drifts:
# ``test_a_workable_pool_has_no_problem`` carries a /31 case for that reason.
SHORTEST_PREFIX_WITHOUT_EDGES = 31


def host_of(address: str) -> str:
    """One address's canonical bare host, whichever form it arrived in.

    ``10.0.0.2/24`` and ``10.0.0.2`` name the same host and the same allocation: the
    prefix says how much room the tunnel has, not who holds the address. So an
    allocation is compared and stored in this form, while the address WRITTEN into a
    config keeps the prefix the operator typed — see ``pool``.
    """
    return str(ipaddress.ip_interface(address).ip)


def pool(first: str, size: int) -> Iterator[str]:
    """``size`` consecutive addresses starting at ``first``, produced one at a time.

    Each is written with FIRST'S OWN PREFIX, and that is what makes the first one
    byte-identical to ``str(ipaddress.ip_interface(first))`` — exactly the value a
    WireGuard-family renderer already falls back to when a credential carries no
    address of its own. A transport enabled before M17 therefore renders the same bytes
    afterwards: its one typed address is its pool's first entry.

    Lazy on purpose. An operator may size a pool at a /8's worth of addresses, and the
    caller wants the lowest free one, not sixteen million strings — so nothing here
    builds a list, and neither does anything that measures a pool.

    Validates nothing: ``pool_problem`` is the gate, and it is the caller's job to ask
    it first. A run walked past the end of the address space raises from ``ipaddress``
    itself rather than wrapping round.
    """
    interface = ipaddress.ip_interface(first)
    written_as = type(interface)
    prefix = interface.network.prefixlen
    start = int(interface.ip)
    for offset in range(size):
        yield str(written_as((start + offset, prefix)))


def pool_problem(first: str, within: str, size: int) -> str | None:
    """Why a pool of ``size`` addresses starting at ``first`` cannot work, or ``None``.

    A sentence rather than an exception, in ``egress.resolver_problem``'s shape and for
    its reason: one rule asked in two places — here, and by `control` while the operator
    is still looking at the box — so each caller raises the refusal its own surface
    speaks. It carries the addresses the operator typed and counts derived from them,
    and never a credential, a key or a person.

    Every refusal below stands in front of a failure that is otherwise silent, because
    a tunnel address that cannot work still produces a config the daemon accepts and an
    interface that comes up:

    * **a pool of fewer than one** hands nobody an address, so the transport serves the
      friends it is offered to by giving them nothing.
    * **values that do not parse** — refused here rather than at render, where the
      operator is no longer looking.
    * **IPv6** — the forwarding rules this project renders are IPv4 only
      (``edge/egress.py`` refuses a local exit on a v6 tunnel, because a pinned
      data-plane image has not been shown to carry ``ip6tables``), so every user in
      such a pool holds an address their traffic cannot leave by.
    * **a first address outside the tunnel's own network** — M14's failure exactly:
      only what is sourced from that network is masqueraded out of the node, so the
      handshake completes, the interface comes up, and nothing moves.
    * **a run over the node's own address** — a user handed it is authorised to send as
      the node, and everything addressed to the node on that tunnel is routed to them.
    * **a run over the network or broadcast address** — neither names a host, and a
      device given one is unreachable while looking configured.
    * **a run past the end of the network, or out of private address space** — the
      first is a pool the operator sized larger than the range they typed; the second
      would route addresses this node does not own into the tunnel.

    The room left is computed from the addresses, never by building the pool: a pool
    that does not fit is refused in the same time as one that does.
    """
    if size < 1:
        return (
            f"a pool of {size} addresses hands nobody an address. Each user on this "
            "transport is given one of their own, so a pool has to hold at least one."
        )

    try:
        interface = ipaddress.ip_interface(within)
    except ValueError:
        return (
            f"the tunnel address {within!r} is not an address with a prefix, so nothing "
            "says how much room there is to give out."
        )

    try:
        start = ipaddress.ip_interface(first)
    except ValueError:
        return (
            f"the pool's first address {first!r} is not an address, so there is nothing "
            "to hand out from."
        )

    if interface.version != 4 or start.version != 4:
        return (
            f"the pool starting at {first!r} inside {within!r} is IPv6. The forwarding "
            "rules this project renders are IPv4 only — see edge/egress.py, which "
            "refuses a local exit on a v6 tunnel because the data-plane images have not "
            "been shown to carry the tool it needs — so every user in this pool would "
            "hold an address their traffic could not leave by. Give this transport an "
            "IPv4 tunnel."
        )

    network = interface.network
    if start.ip not in network:
        return (
            f"the pool's first address {start.ip} is outside {network}, which is the "
            f"network this tunnel's own address {within!r} describes. Only what is "
            "sourced from that network is masqueraded out of the node, so a user given "
            "an address outside it would complete a handshake, bring the tunnel up and "
            "carry nothing, with every screen green."
        )

    first_number = int(start.ip)
    last_number = first_number + size - 1
    own_number = int(interface.ip)
    has_edges = network.prefixlen < SHORTEST_PREFIX_WITHOUT_EDGES

    if first_number <= own_number <= last_number:
        return (
            f"a pool of {size} addresses starting at {start.ip} runs through "
            f"{interface.ip}, which is the node's own address on this tunnel. The user "
            "who was handed it would be authorised to send as the node, and everything "
            "the node is sent on this tunnel would be routed to them instead. Start the "
            "pool past the node's own address."
        )

    if has_edges and first_number == int(network.network_address):
        return (
            f"a pool of {size} addresses starting at {start.ip} starts on {network}'s "
            "own network address, which names the network rather than a host in it. The "
            "first user would be given an address nothing can reach. Start one higher."
        )

    edge_number = int(network.broadcast_address)
    if last_number > edge_number:
        room = max(edge_number - (1 if has_edges else 0) - first_number + 1, 0)
        return (
            f"a pool of {size} addresses starting at {start.ip} runs past the end of "
            f"{network}: {room} are left from there. Give the tunnel a shorter prefix, "
            "start the pool lower, or size it to what the range holds."
        )

    if has_edges and last_number == edge_number:
        return (
            f"a pool of {size} addresses starting at {start.ip} ends on "
            f"{network.broadcast_address}, which is the network's broadcast address "
            "rather than a host in it. The last user would be given an address nothing "
            "can reach. Ask for one fewer."
        )

    last = type(start.ip)(last_number)
    # ``summarize_address_range`` answers this exactly and in bounded work: the run is
    # covered by at most as many blocks as an address has bits, whatever the pool's
    # size, so a private-space check never costs what enumerating the pool would.
    if not all(
        block.is_private for block in ipaddress.summarize_address_range(start.ip, last)
    ):
        return (
            f"a pool of {size} addresses starting at {start.ip} reaches {last}, and the "
            "run leaves private address space on the way. A public address handed to a "
            "user would route traffic this node does not own into the tunnel. Keep the "
            "pool inside a private range."
        )

    return None


def carriage_problem(address: str, within: str) -> str | None:
    """Why a tunnel at ``within`` could not carry ``address``, as a clause, or ``None``.

    ``pool_problem`` asks whether a RUN of addresses can be handed out; this asks the
    same rules, in the same order, about ONE address somebody is already using — which
    is a different question only in what the answer may say. The two agree about WHETHER
    (``test_what_a_tunnel_cannot_carry_is_what_a_pool_of_one_refuses`` pins it), and a
    rule added to one without the other is what that test turns red for.

    IT NAMES NOTHING AT ALL — not the address it was handed, and not a value derived
    from the tunnel either. Its caller is composing a refusal about addresses that
    PEOPLE are holding, and which person holds which address is the one record this
    project does not keep; the tunnel it is about is already quoted in the sentence this
    clause lands in, so repeating its network or its broadcast address here would add
    nothing but a second place a held value could appear verbatim.

    A CLAUSE RATHER THAN A SENTENCE, which is the shape the caller needs: it counts how
    many addresses each answer applies to and writes "1 is <clause>; 2 are <clause>", so
    every answer below has to read after a count. That is also why the answer is not
    ``pool_problem``'s own sentence, which quotes the address it was asked about and
    speaks about a pool nobody was sizing.
    """
    try:
        interface = ipaddress.ip_interface(within)
    except ValueError:
        return "on a tunnel whose own address is not an address with a prefix"

    try:
        held = ipaddress.ip_interface(address).ip
    except ValueError:
        return "not an address at all"

    if interface.version != 4 or held.version != 4:
        return (
            "on an IPv6 tunnel, and the forwarding rules this project renders are IPv4 "
            "only — see edge/egress.py"
        )

    network = interface.network
    if held not in network:
        return "outside the range this tunnel describes"

    if held == interface.ip:
        return (
            "the node's own address on this tunnel, which would authorise whoever holds "
            "it to send as the node"
        )

    has_edges = network.prefixlen < SHORTEST_PREFIX_WITHOUT_EDGES
    if has_edges and held == network.network_address:
        return "this range's network address, which names the network rather than a host"

    if has_edges and held == network.broadcast_address:
        return "this range's broadcast address, which is not a host in it either"

    if not held.is_private:
        return "outside private address space, which this node does not own"

    return None


def networks_overlap(a: str, b: str) -> bool:
    """Whether two tunnel addresses describe networks that share any address.

    Asked of the whole range each address describes rather than of the two addresses,
    because the question is about what may be HANDED OUT: two interfaces on one node
    whose ranges meet can give two different people the same address. Their data planes
    share the host's routing table, so a reply meant for one person's device can reach
    the other's — a cross-person hijack that no single rendered config can see, which is
    why the comparison lives here rather than inside either transport.

    Two different address families cannot overlap, and asking would raise rather than
    answer, so they are answered ``False`` here.
    """
    first = ipaddress.ip_interface(a).network
    second = ipaddress.ip_interface(b).network
    if first.version != second.version:
        return False
    return first.overlaps(second)


__all__ = [
    "SHORTEST_PREFIX_WITHOUT_EDGES",
    "carriage_problem",
    "host_of",
    "networks_overlap",
    "pool",
    "pool_problem",
]
