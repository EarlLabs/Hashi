"""What a node does with the packets it decrypts — M14.3, its way out — M3, and where it
looks a name up — M16.

WHAT: ``Egress``, the closed vocabulary that says which way out traffic arriving over one
      tunnel takes, and the two expressions of it: ``wg_quick_egress`` for a data plane
      whose packets the kernel routes, ``exit_origin`` for one that terminates a
      connection and opens a new one. Beside the second, ``lookup_resolver``: the resolver
      such a proxy must ask, instead of its host's, when its way out is a hop.
WHY:  M14, measured on a real entry node with a real client. The handshake completed in
      both directions, the interface was up, the container was up — and nothing moved,
      because a decrypted packet was dropped by the host's FORWARD chain having never
      been NATed. The rendered config had no ``PostUp``/``PostDown``, so nothing added
      either rule when the interface came up and nothing removed them when it went down.

      The policy is a value rather than a branch because the two answers are not
      interchangeable and the wrong one is silent. A friend-facing tunnel on a leaf must
      exit here. A node-to-node hop must NOT: masquerading it out of the entry is a
      friend in Russia exiting in Russia while every screen shows green, which is the
      failure this project is most afraid of. So the default is ``NONE`` — decision 3's
      fail-closed rule, expressed as the value a caller gets when it says nothing.

      M3 added the third answer, and it is the one the charter is actually built on: an
      entry node's friends exit through a HOP, at a foreign leaf, never out of the entry's
      own route. Same shape — a value, not a branch — because the failure has the same
      silence: friend connects, pages load, panel shows two active nodes and a live hop,
      and the exit is in Russia.

      M16 found what M3 left behind. A proxy handed a hostname resolves it before it
      dials, and ``exit_origin`` binds the dial, not the lookup: the exit moved abroad
      while the list of names a friend asked for, in order and with timing, stayed with
      the host's resolver on the near side of the hop. Same shape again — the answer is
      a value from the node's record — and the same refusal when the value is missing,
      because rendering without it IS the leak, with every screen green.
HOW:  pure, like everything in this zone: text in, text out, no clock, no I/O, and
      nothing here reads a node, an interface or an address off this machine.

      **It names no interface.** The egress interface is not ``eth0`` everywhere, and a
      rendered name is a node the fleet could not rotate onto (``CLAUDE.md``). The rule
      is written so it never needs one: masquerade what came FROM the tunnel subnet and
      is leaving by anything that is not the tunnel itself. ``%i`` is wg-quick's own
      substitution for the interface it is bringing up, so even the tunnel's name is the
      tool's answer rather than ours.

      **It never logs.** netfilter has a ``LOG`` target and it would break the charter's
      one absolute rule in a single word. There is none here, not even commented out.

One copy, shared by every transport whose config a wg-quick-style tool reads, and
deliberately so. The two WireGuard-family packages duplicate everything else about their
rendering on purpose — one has obfuscation, the other has none, and a shared renderer
would be one ``if`` away from emitting the wrong one. This is the exception, argued
rather than assumed: these lines contain nothing protocol-specific at all, and two
copies of a firewall rule that must be its own exact inverse is precisely how residue
ends up on a node.
"""

import enum
import ipaddress
from dataclasses import dataclass


class Egress(enum.StrEnum):
    """Which way out the traffic on one tunnel takes, if it takes one at all.

    A property of the RELATIONSHIP rather than of the transport or of the node: the same
    protocol on the same host exits locally when friends dial it on a leaf, exits through
    a hop when they dial it on an entry, and must do neither when it is itself one end of
    a hop. ``control`` derives it from the ``purpose`` its ``node_transports`` row already
    carries — plus, since M3, whether that node has a hop of its own — and passes it in.
    """

    # Nothing is forwarded off this node. The fail-closed answer, and the default
    # everywhere: no exit at all beats a quiet local one.
    NONE = "none"

    # Forwarded, and masqueraded out of whatever route this node has to the internet.
    # What a friend-facing transport on a leaf needs, and the whole of M14.1.
    LOCAL = "local"

    # Out through a HOP to another node, and never out of this node's own route — M3,
    # and the charter's core claim. The near end of that hop is named separately
    # (``exit_via``), because "which way out" and "which address is the way out" are two
    # facts and a policy that carried only the first would be a policy no renderer could
    # act on.
    #
    # It is a third VALUE and not a branch, which is the whole point: an entry node's
    # friend-facing transport is handed ``HOP`` instead of ``LOCAL`` and renders whatever
    # its own data plane needs to obey it. Nothing outside a transport's package learns
    # what the hop is made of — see ``exit_origin`` and ``wg_quick_egress``.
    HOP = "hop"


class EgressNotRenderable(Exception):
    """The policy cannot be expressed for this tunnel, and pretending would be silent.

    Raised rather than rendered as a partial rule set, for the same reason
    ``relay.HopNotRenderable`` exists: the failure it would otherwise hide is a config
    the daemon accepts, an interface that comes up, a handshake that completes and a
    friend who carries nothing.
    """


@dataclass(frozen=True)
class WgQuickHooks:
    """The two hook lines a wg-quick config carries for one egress policy.

    Two fields rather than a rendered fragment because the template places them, and
    because ``up`` and ``down`` have to be checkable against each other — that they
    describe the same rules is M14.2, and a test asserts it.
    """

    up: str
    down: str


# The rules, as (table, chain, rule) — one place, so ``PostUp`` and ``PostDown`` cannot
# drift into describing different rule sets.
#
# Both FORWARD rules are needed and neither is enough. The measured host had ufw's
# ``deny (routed)`` default, so the return direction is dropped just as readily as the
# outbound one.
#
# ``! -o %i`` on the MASQUERADE is what removes the need for an egress interface name AND
# keeps tunnel-internal traffic alone: a packet from one peer to another never leaves the
# interface, so it must not be rewritten to look like the node.
def _rules(network: str) -> tuple[tuple[str, str, str], ...]:
    return (
        ("filter", "FORWARD", "-i %i -j ACCEPT"),
        ("filter", "FORWARD", "-o %i -j ACCEPT"),
        ("nat", "POSTROUTING", f"-s {network} ! -o %i -j MASQUERADE"),
    )


# The routing table the way out through a hop is written into, and the ONLY constant in
# this module that is not derived from the node's own record.
#
# It has to be a number: ``ip`` reads a table by name only from ``/etc/iproute2/rt_tables``,
# which is host state this project does not create (a node holds nothing that cannot be
# regenerated). 51820 is wg-quick's own table and is deliberately NOT reused — a hop end
# renders ``Table = off`` precisely so wg-quick installs nothing, and sharing its number
# would put our route where its teardown looks.
#
# One number for the whole node, which is a limit rather than an oversight: two hop ends
# dialling out of ONE node would both add a default route here and the second ``ip route
# add`` would fail — loudly, at ``PostUp``, taking that container down rather than
# silently stealing the first hop's traffic. A node has one way out.
HOP_ROUTE_TABLE = "51821"

# What the far end of the hop is allowed to send us, and therefore what we may send it.
#
# WIDE, and it is the one place in this project where that is correct. AllowedIPs is
# WireGuard's crypto-routing table as well as its authorisation list: a packet for the
# internet is only encrypted to a peer whose AllowedIPs covers the DESTINATION, and a
# reply is only accepted from a peer whose AllowedIPs covers its SOURCE. So an entry node
# whose exit is the far end of this tunnel cannot route a friend's traffic through it with
# anything narrower — the packet is dropped by the interface, and nothing logs it.
#
# What made a wide entry dangerous is not this line but wg-quick's ROUTES, which is a
# separate switch: ``Table = off`` below means no route is installed at all, so the node's
# own traffic — the SSH session the control plane manages it over above all — never enters
# the tunnel. Only what is explicitly sourced from the tunnel's own address does, by the
# rule in ``_hop_rules``.
EXIT_ROUTE = "0.0.0.0/0"

# wg-quick's ``Table`` value for an interface whose routes we install ourselves.
NO_ROUTES = "off"


# The way out through a hop, as (command, arguments) — one place, so the hooks that add it
# and the hooks that remove it cannot drift apart.
#
# SOURCE-BASED, and that is the whole safety property. Only traffic already sourced from
# the tunnel's own address is sent through the tunnel; everything else on the node —
# SSH above all — keeps using the main table and never sees this. The tunnel's address is
# a fact from the node's own record, so nothing here is a constant but the table number.
#
# ``%i`` is wg-quick's own substitution for the interface it is bringing up: even the
# tunnel's name is the tool's answer rather than ours, exactly as in ``_rules``.
#
# And it never logs. ``ip`` has no logging target to reach for, but the rule holds here
# as everywhere: nothing this project renders may record a connection.
def _hop_rules(exit_via: str) -> tuple[tuple[str, str], ...]:
    return (
        ("rule", f"from {exit_via} lookup {HOP_ROUTE_TABLE}"),
        ("route", f"default dev %i table {HOP_ROUTE_TABLE}"),
    )


def wg_quick_hooks(
    egress: Egress, tunnel_address: str, exit_via: str | None = None
) -> WgQuickHooks | None:
    """The ``PostUp``/``PostDown`` pair for one interface under one policy.

    ``None`` when the policy asks for no exit — there is nothing to add, and an empty
    hook line in the file would read as a decision that had been made and lost.

    ``tunnel_address`` is the interface's own address WITH its prefix, exactly as the
    transport's ``Params`` validated it. The masqueraded source is that address's
    network, so the range comes from the node's own record and never from a constant
    here.

    ``exit_via`` is the address the node's way out runs through, and is meaningful only
    under ``Egress.HOP`` — where it must be THIS interface's own address, because the only
    tunnel that can carry a node's exit is the tunnel that is the exit. Anything else is
    refused by ``wg_quick_egress``, which is where the two are compared.
    """
    if egress is Egress.HOP:
        rules = _hop_rules(exit_via or "")
        # ``add``/``del`` rather than iptables' ``-I``/``-D``, and no position: a rule is
        # ordered by its priority and a route by its table, neither of which is an index
        # into a chain.
        up = "; ".join(f"ip {command} add {arguments}" for command, arguments in rules)
        # ``|| true`` for the same reason every delete in this module carries it: wg-quick
        # runs a hook under ``set -e``, and at PostDown the interface is already gone, so
        # the route delete fails on a device that no longer exists. Without it the ip RULE
        # — the one thing here that does NOT go away with the interface — would be left
        # behind on the node by its own teardown.
        down = "; ".join(f"ip {command} del {arguments} || true" for command, arguments in rules)
        return WgQuickHooks(up=up, down=down)

    if egress is not Egress.LOCAL:
        return None

    interface = ipaddress.ip_interface(tunnel_address)
    if interface.version != 4:
        # An IPv6 tunnel needs ``ip6tables``, which is a different binary — and one of
        # the pinned data-plane images does not ship it, so a rendered v6 rule would
        # fail inside the container and take the interface down with it. Refused where
        # an operator can still read why, rather than rendered as an IPv4 rule that
        # matches nothing.
        raise EgressNotRenderable(
            f"a local exit was asked for on the IPv6 tunnel {tunnel_address!r}. The "
            "forwarding rules this project renders are IPv4 only; a v6 exit needs a "
            "tool the data-plane images have not been shown to carry. Give this "
            "transport an IPv4 tunnel address, or leave it with no local exit."
        )

    rules = _rules(str(interface.network))

    # Inserted at the head of the chain rather than appended: the measured host runs ufw,
    # whose own rules sit in the same chain, and a rule appended behind them is a rule
    # that may never be reached. Scoped to this interface, so nothing else the operator
    # firewalls is affected.
    up = "; ".join(f"iptables -t {table} -I {chain} 1 {rule}" for table, chain, rule in rules)

    # ``|| true`` on every delete, and it is not decoration. wg-quick runs a hook under
    # ``set -e``, so the first delete that fails abandons every delete after it — and a
    # rule an earlier teardown already removed fails. Without this, the residue M14.2
    # exists to prevent would be created by the teardown itself.
    down = "; ".join(
        f"iptables -t {table} -D {chain} {rule} || true" for table, chain, rule in rules
    )

    return WgQuickHooks(up=up, down=down)


@dataclass(frozen=True)
class WgQuickEgress:
    """Everything one egress policy changes in a wg-quick-style config.

    Three fields because the policy reaches three different places in the file, and a
    renderer that got two of them right would produce a config that comes up and carries
    nothing: the hooks, the ``Table`` switch that decides whether the tool installs routes
    of its own, and what the peer carrying the exit is allowed to route.
    """

    hooks: WgQuickHooks | None

    # The value for wg-quick's ``Table =``, or ``None`` to leave the line out and let the
    # tool do what it has always done.
    table: str | None

    # The AllowedIPs for the peer on the far side of this node's exit, or ``None`` when no
    # peer here carries an exit and each gets its own address only.
    peer_route: str | None


def _bare_address(address: str) -> str:
    """One address without its prefix, whichever form it arrived in."""
    return str(ipaddress.ip_interface(address).ip)


def wg_quick_egress(
    egress: Egress, tunnel_address: str, exit_via: str | None = None
) -> WgQuickEgress:
    """One kernel tunnel's whole egress policy, ready for its template.

    Refuses rather than renders where the policy cannot be honoured, for the reason every
    refusal in this zone exists: the alternative is a file the daemon accepts, an
    interface that comes up, and traffic leaving where it must not.
    """
    if egress is not Egress.HOP:
        if exit_via is not None:
            # A caller that names a way out and then asks for a different policy has said
            # two contradictory things, and one of them is "exit locally". Refused rather
            # than resolved in either direction.
            raise EgressNotRenderable(
                f"this tunnel was given the exit address {exit_via!r} and the egress "
                f"policy {egress!r}, which are two different answers to where its traffic "
                "leaves. Nothing is rendered from a contradiction."
            )
        return WgQuickEgress(
            hooks=wg_quick_hooks(egress, tunnel_address), table=None, peer_route=None
        )

    if not exit_via:
        raise EgressNotRenderable(
            "this tunnel was told its traffic leaves through a hop, but not which address "
            "the hop runs through, so no route to it can be written. That address is the "
            "near end of the hop; without it the config would come up and carry nothing."
        )

    interface = ipaddress.ip_interface(tunnel_address)
    if _bare_address(exit_via) != str(interface.ip):
        # The tunnel being configured is NOT the way out — some other interface on this
        # node is. A kernel tunnel cannot express that: its packets are handed to the
        # node's own routing stack, which would send them out of the node's own route,
        # which on an entry node is the exit in Russia this whole topology exists to
        # avoid. Refused, out loud, on the node's page. Decision 3: no exit beats that one.
        raise EgressNotRenderable(
            f"this node's traffic leaves through {_bare_address(exit_via)}, which is not "
            f"this tunnel's own address ({interface.ip}). A tunnel whose packets this "
            "node's kernel routes cannot send them out through a different interface, so "
            "they would leave by the node's own route instead — which is the silent "
            "failure the hop exists to prevent. Give this node's friends a transport that "
            "terminates their connection and re-originates it, or take the hop away."
        )

    if interface.version != 4:
        # The same refusal, and the same reason, as the IPv6 branch in ``wg_quick_hooks``:
        # the rule and the route this renders are IPv4, and a v6 tunnel would need
        # commands the pinned images have not been shown to carry. Refused where an
        # operator can read why.
        raise EgressNotRenderable(
            f"an exit through a hop was asked for on the IPv6 tunnel {tunnel_address!r}. "
            "The rule and route this project renders are IPv4 only. Give this hop an IPv4 "
            "tunnel address."
        )

    return WgQuickEgress(
        hooks=wg_quick_hooks(egress, tunnel_address, _bare_address(exit_via)),
        # wg-quick installs NOTHING for this interface. That is what makes the wide
        # AllowedIPs below safe: the tool's own answer to a default route is a default
        # route in the main table, which would take the node's SSH session with it.
        table=NO_ROUTES,
        peer_route=EXIT_ROUTE,
    )


def exit_origin(egress: Egress, exit_via: str | None) -> str | None:
    """The local address a proxy must originate this node's outgoing connections from.

    The other half of the same policy, for the other kind of data plane. A userspace proxy
    forwards no packet in the kernel — it terminates a connection and opens a new one — so
    there is no rule for it to add and nothing for ``wg_quick_egress`` to say. What decides
    where that new connection goes is the address it is opened FROM: bound to the node's
    hop address, it can only reach the internet through the hop, and while the hop is down
    it cannot be opened at all.

    ``None`` means "this node's own route", which is what every node without a hop has
    always done and must keep doing.
    """
    if egress is not Egress.HOP:
        if exit_via is not None:
            raise EgressNotRenderable(
                f"this transport was given the exit address {exit_via!r} and the egress "
                f"policy {egress!r}, which are two different answers to where its traffic "
                "leaves. Nothing is rendered from a contradiction."
            )
        return None

    if not exit_via:
        raise EgressNotRenderable(
            "this transport was told its traffic leaves through a hop, but not which "
            "address the hop runs through. Rendering it without one would leave the "
            "connection to be opened from the node's own address — an exit in the country "
            "the hop exists to leave, with nothing saying so."
        )
    return _bare_address(exit_via)


# What an operator reads when a node whose traffic leaves through a hop has no resolver on
# its record. A constant so the sentence acceptance judges is held by a test, not retyped.
NO_RESOLVER = (
    "this node's traffic leaves through a hop, and its record names no resolver for the "
    "destinations its friends ask for. Without one they would be looked up by this host's "
    "own resolver — on the near side of the hop, inside the network the hop exists to "
    "leave — while the traffic itself exits at the far end. Nothing is rendered until the "
    "node has one: an IPv4 address the far end of the hop can reach."
)


class ResolverMissing(EgressNotRenderable):
    """A node whose traffic leaves through a hop, and whose record names no resolver.

    Its own type beside the general refusal, because it is the one refusal an operator
    fixes on the node's RECORD rather than in its topology — and a caller that has to tell
    them so, such as a revocation that could not reach the node, must not have to read this
    message to learn which refusal it was. Raised only for a MISSING resolver: one that is
    present and wrong is the general refusal, since "set one" would be the wrong advice.
    """


def resolver_problem(resolver: str) -> str | None:
    """Why ``resolver`` cannot answer a node's lookups through its hop, or ``None``.

    One rule, asked in two places: here at render, and by `control` whenever a node's
    resolver is written — at registration and when it is set afterwards — so a value that
    will never render is refused while the operator is still looking at the box. A sentence
    rather than an exception, so each caller raises the refusal its own surface speaks.

    A plain IPv4 address and nothing else, and each exclusion is a way the lookup would
    quietly stay on this side of the hop:

    * **a name** needs a lookup of its own before it can be asked anything, and that one
      is made by this host's resolver — the leak, one query earlier. The same test turns
      away a URL and the proxy's own keywords (to Xray, ``localhost`` MEANS the host's
      resolver) without this module having to know any of them.
    * **IPv6** — the hop carries IPv4 only (``EXIT_ROUTE``), so a v6 resolver is one no
      lookup can reach: every name fails, and nothing says why.
    * **loopback or unspecified** — answered on this host, by a stub that asks the host's
      upstream: the leak through a back door, and the most natural value for an operator
      to copy out of a host's own resolver configuration.

    A private address is deliberately NOT refused. The query is source-routed into the
    tunnel whatever its destination, so a resolver inside the far end's own network is
    reached through the hop like any other. What no node record can show is an address
    this host holds on another interface — answered here, like loopback — which is why
    the address should be one the far end can reach and this end does not own.
    """
    try:
        address = ipaddress.ip_address(resolver)
    except ValueError:
        return (
            f"the resolver {resolver!r} is not an IPv4 address. A name would itself have to "
            "be looked up first, by this host's own resolver — the lookup the hop exists to "
            "move. Give the resolver's address."
        )
    if address.version != 4:
        return (
            f"the resolver {resolver!r} is an IPv6 address, and the hop carries IPv4 only, so "
            "no lookup could reach it. Give an IPv4 address."
        )
    if address.is_loopback or address.is_unspecified:
        return (
            f"the resolver {resolver!r} would be answered on this host, which asks its own "
            "upstream — the lookup the hop exists to move. Give the address of a resolver "
            "the far end of the hop can reach."
        )
    return None


def lookup_resolver(egress: Egress, resolver: str | None) -> str | None:
    """The resolver a proxy must look its destinations up at, or ``None`` for its host's.

    ``exit_origin``'s companion, for the part of a connection that happens before it is
    opened. A friend's client hands the proxy a NAME; the proxy resolves it, then dials.
    ``exit_origin`` decides where the dial leaves from and says nothing about the lookup,
    and a proxy left to itself asks its host's resolver — on an entry node, inside the
    network the hop exists to leave. Under ``Egress.HOP`` the lookup gets a resolver of its
    own, and the proxy's template sends the query out through the same hop as the traffic.

    ``None`` for every policy that is not a hop, meaning "the host's own resolver" — what
    every node without a hop has always used, and correctly: there the lookup and the exit
    already leave one host by one route, so nothing needs moving and the config stays byte
    for byte what it was. A resolver on such a node's record is not the contradiction an
    ``exit_via`` would be: it is a fact about the node, kept for the day it dials a hop, and
    not needed yet — so it is not checked here either, and a leaf never fails to render
    over a field it does not use.

    Under a hop with no usable resolver it REFUSES, for the reason ``exit_origin`` refuses
    a hop with no address: rendering anyway is not neutral. It is the host's resolver — the
    leak itself, with every screen green.
    """
    if egress is not Egress.HOP:
        return None
    if resolver is None or not resolver.strip():
        raise ResolverMissing(NO_RESOLVER)
    problem = resolver_problem(resolver)
    if problem:
        raise EgressNotRenderable(problem)
    return resolver


__all__ = [
    "EXIT_ROUTE",
    "HOP_ROUTE_TABLE",
    "NO_RESOLVER",
    "NO_ROUTES",
    "Egress",
    "EgressNotRenderable",
    "ResolverMissing",
    "WgQuickEgress",
    "WgQuickHooks",
    "exit_origin",
    "lookup_resolver",
    "resolver_problem",
    "wg_quick_egress",
    "wg_quick_hooks",
]
