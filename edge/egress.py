"""What a node does with the packets it decrypts — M14.3, its way out — M3, and where it
looks a name up — M16, and M23 for the friend.

WHAT: ``Egress``, the closed vocabulary that says which way out traffic arriving over one
      tunnel takes, and the two expressions of it: ``wg_quick_egress`` for a data plane
      whose packets the kernel routes, ``exit_origin`` for one that terminates a
      connection and opens a new one. Beside the second, ``lookup_resolver``: the resolver
      such a proxy must ask, instead of its host's, when its way out is a hop — and
      ``client_resolvers``, the same question asked of a FRIEND's own config file, whose
      device has no resolver left once the tunnel routes every address. Beside that in
      turn, ``CLIENT_ROUTES``: what "every address" is, and why it keeps naming a family
      no node in this fleet can carry.
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

      M23's fifth walk found the one thing none of them looked at: not where a friend's
      traffic LEAVES, but what it can reach on the way. On the owner's real leaf a friend
      opened TCP to the Russian entry node's address on the hop and was answered by its
      SSH daemon — an RFC1918 address no client can reach from the open internet, with
      the packet masqueraded on the way in so the entry saw it arrive from its own
      trusted peer. ``-i %i -j ACCEPT`` lets a decrypted packet leave by ANY interface,
      and one of a leaf's interfaces is the hop. So a friend-facing tunnel now says what
      a friend's traffic may reach — the internet, and the resolver their own file tells
      them to ask — and the LEAF END OF A HOP, which carries another node's traffic and
      is nobody's device, is its own policy (``RELAY``) instead of the same value asked
      to mean two things.
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
from collections.abc import Sequence
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
    # What a friend-facing transport on a leaf needs, and the whole of M14.1. Since M23
    # it also says WHOSE traffic this is — a friend's device, which may reach the
    # internet and nothing else this node is attached to (``NOT_THE_INTERNET``).
    LOCAL = "local"

    # The same exit, for the far END OF A HOP rather than for a friend's device: what
    # arrives here has already been through another node of ours, and leaves by this
    # node's own route. A second value rather than a second meaning for ``LOCAL``,
    # because the two differ in exactly the way that matters — M23's fifth walk.
    #
    # A friend's packets are theirs, arrive from a device this project does not control,
    # and must reach only the internet. What arrives over a hop is an ENTRY NODE's
    # forwarded traffic, and the entry's own lookups go through it to a resolver the
    # record is allowed to name privately (``resolver_problem``), so the narrow rule
    # would take away the very thing the hop was built to carry. Told apart HERE rather
    # than guessed at: ``relay.render_hop`` is the only caller, and it knows which end it
    # is rendering — see the note there, and ``control`` keeps sending ``LOCAL`` for a
    # friend-facing row and gets the strict answer without knowing this value exists.
    #
    # It renders the rules ``LOCAL`` rendered before this walk, byte for byte, which is
    # the property that lets the owner's live hop be re-applied without a change.
    RELAY = "relay"

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
# THE ORDER HERE IS THE INVERSE OF THE ORDER IN THE CHAIN, and that is the point rather
# than an accident — M23, measured on the real leaf. Every rule is installed with
# ``-I <chain> 1``, so the LAST one written ends up at the HEAD and decides first. A rule
# written first sits behind the others and decides nothing — and a test asserting it was
# present would pass, which is why the tests assert the VERDICT a packet gets.
#
# ``! -o %i`` on the MASQUERADE is what removes the need for an egress interface name AND
# keeps tunnel-internal traffic alone: a packet from one peer to another never leaves the
# interface, so it must not be rewritten to look like the node.
#
# Nothing below REJECTs, and every refusal is a DROP: a rejection answers, and an answer
# is a signal — one friend's device enumerating the others, or a scan mapping what a node
# is attached to. Nothing below logs either. netfilter has a ``LOG`` target that would
# break the charter's one absolute rule in a single word; there is none here, not even
# commented out.


# The two ACCEPTs that make a tunnel carry traffic at all, and the DROP that stops what
# arrives on it from leaving by it again.
#
# Both ACCEPTs are needed and neither is enough: the measured host had ufw's ``deny
# (routed)`` default, so the return direction is dropped just as readily as the outbound
# one. Both are also wider than they look — ``-i %i -j ACCEPT`` permits ``%i → %i``, and
# so does ``-o %i -j ACCEPT``. With a pool every friend on this node holds an address in
# one routed network, so those two alone gave thirty people who need not know each other
# full IP reachability to each other's laptops and phones: observed on a real node with
# two real clients, ``ping`` at 0% loss and a TCP payload carried. The DROP is written
# after them so that it lands in front of them.
#
# Safe on the leaf end of a hop, which renders exactly these three: that interface has
# one peer authorised for a single ``/32``, so ``%i → %i`` there is the far end
# addressing itself through the tunnel, which is not a packet any working hop sends. The
# entry end renders ``Egress.HOP`` and no filter rule at all, so it never sees this line.
_CARRY = (
    "-i %i -j ACCEPT",
    "-o %i -j ACCEPT",
    "-i %i -o %i -j DROP",
)

# What a FRIEND's traffic may not reach: every destination that is not on the public
# internet, and every second SPELLING of one. Their traffic is here to reach the internet,
# and the walk that found this measured the cost of the difference.
#
# WHAT THIS LIST TRACKS, stated before the ranges because M23's thirteenth round spent a
# finding on the question and the answer is not "IANA's registry". It is IANA's registry
# MINUS the entries that registry marks *globally reachable*, PLUS the one range that is
# globally reachable and carries a refused address inside it. Two entries sit on that
# line and they are the two a reader will ask about:
#
#   * ``192.88.99.0/24`` — the deprecated 6to4 relay anycast block. In the registry, and
#     GLOBALLY REACHABLE by it: a packet addressed there arrives at a relay router on the
#     public internet, and nothing about the address says where it goes next. It is
#     therefore the internet, it is deliberately NOT here, and it is the address this
#     project's own stands use for the word (``tests/e2e/edge/`` and ``tests/edge/``).
#     Adding it because the registry names it would refuse the one destination those
#     scenarios exist to prove a friend still reaches.
#   * ``64:ff9b::/96`` — the WELL-KNOWN NAT64 prefix (RFC 6052 §2.1). Also in the registry
#     and also globally reachable, and it is the one range where that is not the whole
#     answer: its low 32 bits ARE an IPv4 address, and a NAT64 translator on the path is
#     standard, deployed equipment that puts the packet exactly there. So the prefix is
#     not refused and its EMBEDDINGS OF THE V4 HALF ABOVE are — derived below, never
#     typed. ``64:ff9b::7f00:1`` is ``127.0.0.1`` wearing a different hat; ``64:ff9b::``
#     with a global address in it is the internet, and stays reachable.
#
# So the membership test is "not globally reachable, or a spelling of something that is
# not" — and ``is_global`` is the standard library's name for the registry's own column,
# which is what makes the test below able to hold this list to it.
#
# WHAT IS DELIBERATELY NOT HERE, so the next walk reads it instead of re-finding it:
# ``::/96``, the IPv4-COMPATIBLE prefix, which looks like the NAT64 case and is not.
# Measured against the pinned Xray as a live proxy, with responders on a container's own
# loopback: ``[::ffff:192.88.99.9]`` reached the host at ``192.88.99.9`` — folded — while
# ``[::c058:6309]`` and ``[64:ff9b::c058:6309]`` both timed out, so neither is folded by
# the daemon and both are dialled as literal IPv6. The difference between the two is what
# the NETWORK does with them: RFC 6052 makes the NAT64 prefix mandatory for a translator,
# while ``::/96`` was deprecated by RFC 4291 §2.5.5.1, its tunnelling mechanism removed by
# RFC 4213, and it is in no registry — nothing anywhere turns ``::7f00:1`` into
# ``127.0.0.1``. Refusing it would take away a class of address on the grounds of a
# translation no deployed equipment performs, which is the ad-hoc widening this note
# exists to stop.
#
# TWO CONSUMERS AND ONE LIST, which is the reason it is a constant here and not a rule.
# A kernel tunnel drops these in the FORWARD chain (``_friend_rules``); a proxy, which
# forwards no packet at all, refuses them in its own outbound routing — each transport
# package shapes the rule its data plane speaks, and both read this. A second copy is how
# the two answers drift, and only one of them would be under the test below that holds the
# ranges against the standard library.
#
# M23, round 5, on the owner's real leaf: a friend opened TCP to ``10.90.0.1`` — the
# Russian entry node's address on the hop — and was answered by its SSH daemon, 104 ms
# away against the leaf's own 52. That address is RFC1918 and unreachable from the open
# internet, so the tunnel was granting reach that nothing else grants, to the one node in
# this fleet that is inside Russia, for every one of thirty to fifty friends.
#
# WHY A DESTINATION RULE AND NOT AN INTERFACE ONE — the decision worth recording, rather
# than the list. What makes the entry reachable is a ROUTE on the leaf, out of an
# interface this module may not name: it renders one file per transport, it may never
# look at a host, and a node's other interfaces are not data it is given. Inside one
# interface's own rules the only thing that tells the internet apart from the private
# neighbourhood a node sits in is the DESTINATION, so that is what is matched. Naming the
# hop's interface would also have closed exactly one hole and left the host's own LAN, its
# provider's metadata service and every other tunnel on the box wide open.
#
# WHY THE LIST IS HERE AND NOT ON A NODE'S RECORD. ``CLAUDE.md`` forbids a hardcoded
# country, provider, IP, domain or port because each names something a node could have to
# rotate away from. This names nothing of any node: it is read off a registry, identical
# on every host in every country, and no node this fleet can register is reachable at one
# of these addresses. It is also not OUR list —
# ``tests/edge/test_a_tunnel_carries_traffic_off_the_node.py`` holds it against the
# standard library's own answer in both directions, so a range that drifts from
# ``ipaddress`` fails the suite rather than a friend's tunnel.
#
# Contained blocks are left out where a wider one already covers them
# (``255.255.255.255/32`` is inside ``240.0.0.0/4``, ``192.0.0.170/31`` inside
# ``192.0.0.0/24``): a rule that can never be reached is a rule an operator reading
# ``iptables -S`` has to work out is dead.
#
# BOTH FAMILIES SINCE M23's TWELFTH ROUND, and that round is the reason the split below
# exists at all. Measured by running the product's own rendered ``vless-reality.json``
# unedited in the pinned Xray: ``127.0.0.1`` was refused, the NAME ``localhost`` was
# refused, ``172.17.0.5`` was refused — and ``[::1]`` and ``[fc00::2]`` were reached and
# answered. Every range this list held was IPv4, so the same destinations spelled in the
# other family walked straight past a list written to name them.
#
# ONE LIST STILL, because a second hand-typed one is exactly how the two answers drift
# and only one of them would be under the test that holds these against the standard
# library. What differs between the consumers is not the policy but their REACH: a proxy
# writes these into Xray's ``routing.rules[].ip``, which takes both families happily; the
# wg family writes them into ``iptables``, which takes one — ``ip6tables`` is a different
# binary and one of the pinned data-plane images does not ship it, the same fact
# ``wg_quick_hooks`` refuses a v6 tunnel over. So the FAMILY SPLIT IS DERIVED rather than
# typed: everything is written once here and ``NOT_THE_INTERNET_IPV4`` below is what
# ``ipaddress`` says of it, so a range added to either half reaches every renderer that
# can express it and reaches none that cannot.
#
# DERIVING THE LIST ITSELF FROM ``ipaddress`` IS STILL REFUSED, and that is round nine's
# decision extended rather than a new one. The registry the standard library holds lives
# behind ``_private_networks``, and a rendered firewall rule may not depend on an
# underscore; a TEST may, and should, so a Python release that moves the registry turns
# the suite red instead of a friend's tunnel. The literal is here; the test holds it
# against that answer in both directions, now for both families.
#
# ``::ffff:0:0/96`` — every IPv4 address written as an IPv6 one — IS ABSENT, and it is
# the one entry of this registry that is, so here is why rather than a reader having to
# work out whether it was forgotten. The pinned Xray REFUSES it, in both spellings:
#
#     invalid IP: ::ffff:0:0/96 > invalid network mask for router: 96
#
# It folds an IPv4-mapped address back to four bytes before it measures the prefix, so
# /96 is a mask wider than the address it thinks it has. That same folding is what makes
# the absence safe rather than a hole: a destination arriving as ``::ffff:127.0.0.1`` is
# ``127.0.0.1`` by the time any rule is read, and the v4 half above already refuses it.
# The range is covered by this list one spelling over, not left out of it —
# ``tests/edge/test_a_tunnel_carries_traffic_off_the_node.py`` states that as the single
# exception it allows, and the proxy file measures the mapped spelling's verdict.
_NOT_GLOBALLY_REACHABLE = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "240.0.0.0/4",
    # The same registry, the other family. ``2001:db8::/32`` and ``3fff::/20`` are the
    # documentation ranges, so they are outside ``2001::/23`` rather than inside it.
    "::/128",
    "::1/128",
    "64:ff9b:1::/48",
    "100::/64",
    "2001::/23",
    "2001:db8::/32",
    "2002::/16",
    "3fff::/20",
    "fc00::/7",
    "fe80::/10",
)

# The prefix a NAT64 translator is required to translate, and the reason the list above is
# not the whole list — M23's thirteenth round, measured on the same live proxy the twelfth
# used. ``[64:ff9b::7f00:1]`` was REACHED through the product's own rendered config while
# ``127.0.0.1`` and ``[::ffff:127.0.0.1]`` beside it were refused: the low 32 bits of a
# well-known-prefix address ARE an IPv4 address (RFC 6052 §2.2), so that is the node's own
# loopback under a third spelling and the list named two of the three.
#
# The prefix ITSELF is not refused — it is globally reachable, and an address in it with a
# global IPv4 address inside is how a v6-only client reaches the v4 internet. What is
# refused is exactly its embedding of each range the v4 half already refuses, which is a
# fixed arithmetic rather than a judgement: prefix, then the range's own bits, then the
# range's own width 96 bits further in.
_NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")


def _as_nat64_spells_it(destination: str) -> str:
    """One IPv4 range, written the way the well-known NAT64 prefix carries it.

    DERIVED, so the two spellings of the list cannot drift: a range added to the v4 half
    gets its NAT64 spelling by being added, and one removed loses it the same way. Typing
    the thirteen out is how the round after this one finds the fourteenth missing.

    Pure arithmetic on the standard library's own types, like everything else in this
    module: no clock, no I/O, and the same answer on every host.
    """
    network = ipaddress.ip_network(destination)
    return str(
        ipaddress.IPv6Network(
            (
                int(_NAT64_WELL_KNOWN.network_address) | int(network.network_address),
                _NAT64_WELL_KNOWN.prefixlen + network.prefixlen,
            )
        )
    )


# The one list both data planes read. The literal half first — which is also what keeps
# ``NOT_THE_INTERNET_IPV4`` below a PREFIX of this tuple, the property the wg family's
# chain order is asserted on — and the derived spellings after it.
NOT_THE_INTERNET = (
    *_NOT_GLOBALLY_REACHABLE,
    *(
        _as_nat64_spells_it(destination)
        for destination in _NOT_GLOBALLY_REACHABLE
        if ipaddress.ip_network(destination).version == 4
    ),
)

# What ``iptables`` can express of the list above — read off it, never typed again.
#
# An IPv6 destination in an ``iptables`` rule is not a narrower rule, it is a rule the
# command refuses outright: the hook fails, wg-quick is running it under ``set -e``, and
# the interface does not come up. So each data plane takes what it can say and the one
# list stays one list.
#
# What that leaves a friend on a kernel tunnel is not the hole it looks like. Their own
# config routes ``::/0`` into the tunnel and the node discards every IPv6 packet before
# any chain is consulted — WireGuard's own authorisation list, not ours — so there is
# nothing at this end for a rule to refuse. See ``CLIENT_ROUTES``, where that is argued;
# it is not reopened here.
NOT_THE_INTERNET_IPV4 = tuple(
    destination
    for destination in NOT_THE_INTERNET
    if ipaddress.ip_network(destination).version == 4
)

# The one thing off the internet a friend may still reach: the resolver their own config
# file tells them to ask, on the port a resolver is asked on.
#
# It exists because ``client_resolvers`` hands a friend's device the node record's own
# resolver and ``resolver_problem`` deliberately allows that to be a private address —
# "a resolver this node can reach is one that friend can reach" is the sentence round
# one's DNS fix was built on, and an operator copying the value out of their leaf's
# ``/etc/resolv.conf``, which is the most natural place to find one, gets a private
# address. Without this exception the drops above would take every name away from every
# friend on such a node, silently, while addresses kept working: the failure shape this
# project is most afraid of, reintroduced by the fix for it.
#
# Scoped to the port and the two protocols DNS is spoken on, which is not the hardcoded
# port ``CLAUDE.md`` forbids: a wg-quick ``DNS =`` line carries no port at all, so there
# is no other value this could be and nothing to rotate. An address-only exception would
# be far wider than the hole it closes — an operator who pointed their friends' DNS at
# the entry node would hand back, in full, the reach these rules exist to take away.
RESOLVER_PORT = "53"
RESOLVER_PROTOCOLS = ("udp", "tcp")


def _forward(rules: Sequence[str]) -> tuple[tuple[str, str, str], ...]:
    """Filter-table FORWARD rules, in the order they are written — see above for why."""
    return tuple(("filter", "FORWARD", rule) for rule in rules)


def _masquerade(network: str) -> tuple[str, str, str]:
    """The one NAT rule: what came from this tunnel and is leaving by anything else."""
    return ("nat", "POSTROUTING", f"-s {network} ! -o %i -j MASQUERADE")


def _relay_rules(network: str) -> tuple[tuple[str, str, str], ...]:
    """The leaf end of a hop: what arrives over it leaves by this node's own route.

    Deliberately unchanged by M23's fifth round, byte for byte, and the restraint is the
    decision. What arrives here is an ENTRY node's forwarded traffic, not a device's, and
    it includes that node's own lookups — which M16 lets the record point at a private
    resolver on this side of the hop. The narrow rule a friend's tunnel gets would take
    that away, and the owner's live hop renders from this line.

    What it therefore does not close, and could not, is the mirror of the finding: a friend
    served by the ENTRY, whose proxy will dial whatever it is asked for, can be sent to an
    address on this node's own private neighbourhood. A rule at this end cannot tell that
    packet from the hop's own traffic — it arrives over the same tunnel, from the same
    peer — so the refusal belongs to the thing that OPENS the connection. Round nine
    recorded it rather than half-building it here; it is built now, in each proxy
    package's own template, off ``NOT_THE_INTERNET`` above, and scoped to the friend's
    inbound so the lookups this function protects stay protected there too.
    """
    return (*_forward(_CARRY), _masquerade(network))


def _friend_rules(
    network: str, resolvers: Sequence[str]
) -> tuple[tuple[str, str, str], ...]:
    """A friend's own tunnel: the internet, the resolver they were told to ask, no more.

    ``resolvers`` are the addresses this friend's own configuration file names that the
    drops would otherwise take away — see ``_resolver_exceptions``. They are written LAST
    so they land at the head of the chain, in front of the drops they are exceptions to;
    everything about the order here reads backwards, and the comment above says why.

    WHAT THESE RULES STILL DO NOT REACH, recorded rather than half-closed — M23's
    thirteenth round, and it is the FORWARD chain's own boundary. Every rule here is about
    a packet this node forwards; a friend opening a connection to the node's OWN address on
    this interface is INPUT, and nothing in this chain is on that path. On the owner's real
    leaf that reaches the host's sshd, which writes ``Connection closed by <the friend's
    tunnel address>`` into ``auth.log`` — the one record the charter says must not exist,
    written by a daemon this project did not render and does not configure. Nothing hashi
    renders logs anything: there is no ``-j LOG`` here or anywhere, ufw's own logging is
    turned off before the firewall can come up, ``nf_conntrack_acct`` is read and answered
    for, and Xray's access log is ``none``. This is the one address that lands in a log
    anyway, and it lands in somebody else's.

    IT IS NOT CLOSED HERE BECAUSE THE RULE THAT CLOSES IT IS NOT THIS SHAPE. It would be an
    INPUT rule naming the node's own tunnel address and the port sshd answers on — a port
    this module may not name (``CLAUDE.md``) and a fact it is not given, since the node's
    SSH port is operator data on a record `control` holds. And it must NOT be mirrored onto
    the entry's end of a hop, where the leaf's replies arrive addressed to the tunnel: a
    rule written once and rendered by both ends would take the hop down. That is a decision
    about two roles and a value neither of them currently carries, which is a milestone and
    not a line — the same judgement round nine made about the mirror above, and the same
    shape M22 was proposed in.
    """
    return (
        *_forward(
            (
                *_CARRY,
                *(
                    f"-i %i -d {destination} -j DROP"
                    # The v4 half only, and the filter is the whole of M23's twelfth
                    # round at this end: ``iptables`` cannot be handed the other one.
                    for destination in NOT_THE_INTERNET_IPV4
                ),
                *(
                    f"-i %i -d {resolver} -p {protocol} --dport {RESOLVER_PORT} -j ACCEPT"
                    for resolver in resolvers
                    for protocol in RESOLVER_PROTOCOLS
                ),
            )
        ),
        _masquerade(network),
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


def _off_the_internet(address: str) -> bool:
    """Whether the rules a friend's tunnel carries would drop a packet addressed here.

    Asked of the list itself rather than of ``ipaddress.is_global``, so an exception can
    never be rendered for an address the drops do not take away, nor withheld from one
    they do. The two answers agree today and the test holds them to it; deriving the
    question from the list is what keeps them agreeing.

    Of ``NOT_THE_INTERNET_IPV4`` and not of the whole list, because the drops this is
    about are the ones ``_friend_rules`` renders and those are the v4 half. No IPv6
    resolver reaches here — ``client_resolvers`` refuses one first, which is what
    ``_resolver_exceptions`` catches — so this is the same answer said honestly rather
    than a second behaviour.
    """
    destination = ipaddress.ip_address(address)
    return any(
        destination in ipaddress.ip_network(network) for network in NOT_THE_INTERNET_IPV4
    )


def _resolver_exceptions(
    client_dns: Sequence[str], node_resolver: str | None, tunnel_address: str
) -> tuple[str, ...]:
    """The resolvers a friend on this tunnel must still reach through the drops.

    Asked through ``client_resolvers`` rather than beside it: the address a rule opens and
    the address the friend's own file names are then one answer, and cannot drift into a
    hole for a resolver nobody was told to ask. Only those the drops would take away are
    returned, so a node whose resolver is on the internet renders no exception at all and
    the rule set states exactly what its exceptions are.

    A resolver this tunnel could never give a friend gets no exception either, rather than
    a refusal, and the asymmetry is deliberate. The refusal belongs to the file that would
    have carried it — ``render_client_config`` raises there, and `control` already knows
    to skip such a row when a friend downloads. Raising HERE would take a whole node out
    of service, every transport on it and every friend, over a value that reaches one
    file; and a fleet that stored such a value before it was refused at input still holds
    it. Fail-closed either way: no exception is the strict answer, not the lenient one.
    """
    try:
        resolvers = client_resolvers(client_dns, node_resolver, tunnel_address)
    except EgressNotRenderable:
        return ()
    return tuple(resolver for resolver in resolvers if _off_the_internet(resolver))


def wg_quick_hooks(
    egress: Egress,
    tunnel_address: str,
    exit_via: str | None = None,
    *,
    client_dns: Sequence[str] = (),
    node_resolver: str | None = None,
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

    ``client_dns`` and ``node_resolver`` are the two sources a FRIEND's own config file
    names its resolver from, and they are here for one reason: under ``Egress.LOCAL`` the
    rules have to let through exactly what that file tells the device to ask, and nothing
    else off the internet. They are the same two values ``render_client_config`` reads,
    passed through one function so the file and the firewall cannot disagree. Ignored by
    every other policy — a hop end carries nobody's device.
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

    if egress not in (Egress.LOCAL, Egress.RELAY):
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

    # Which rule set, decided by the policy's own value and nothing else. A friend's
    # device may reach the internet and the resolver it was handed; the far end of a hop
    # is another node of ours and keeps what it always had — see both functions.
    rules = (
        _friend_rules(
            str(interface.network),
            _resolver_exceptions(client_dns, node_resolver, tunnel_address),
        )
        if egress is Egress.LOCAL
        else _relay_rules(str(interface.network))
    )

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
    egress: Egress,
    tunnel_address: str,
    exit_via: str | None = None,
    *,
    client_dns: Sequence[str] = (),
    node_resolver: str | None = None,
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
            hooks=wg_quick_hooks(
                egress,
                tunnel_address,
                client_dns=client_dns,
                node_resolver=node_resolver,
            ),
            table=None,
            peer_route=None,
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


def client_resolver_problem(resolver: str) -> str | None:
    """Why a FRIEND's device could not reach ``resolver`` through their tunnel, or ``None``.

    ``resolver_problem``'s sibling, one consumer further out, and written in the same
    shape for the same reason: a sentence rather than an exception, so the renderer can
    raise it and an INPUT FORM can refuse the value while the operator is still looking
    at the box. That split is the whole of M23's second round — the rule below was
    enforced here at render only, so an IPv6 resolver was accepted by the panel, stored,
    and then took away the configuration of every user on that node at the moment they
    downloaded it.

    Two exclusions, and neither is a property of either protocol — which is why they live
    beside the tunnel's egress policy rather than in a transport's own model, and why a
    transport that asks this question asks it HERE:

    * **a name** cannot be written into a tunnel's DNS setting at all: resolving it is the
      very thing the setting is for, so the device would have to resolve in order to learn
      how to resolve.
    * **IPv6** — a friend's config routes every v6 address into the tunnel
      (``CLIENT_ROUTES``) and the node drops all of it (see that constant's note), so a v6
      resolver is one the device can ask and never hear from. Every name fails, which is
      exactly the M23 failure the client's ``DNS`` line was added to fix, with the box
      filled in.

    What it does NOT ask is whether the resolver is inside a particular tunnel's own
    range: that needs the tunnel, and the caller that has one asks it separately — see
    ``client_resolvers``. A predicate over one value is what an input form can call
    field by field.
    """
    try:
        address = ipaddress.ip_address(resolver)
    except ValueError:
        return (
            f"{resolver!r} is not an address, and a resolver written into a tunnel's "
            "DNS setting cannot be a name: looking that name up is the very thing "
            "the setting is for."
        )
    if address.version != 4:
        return (
            f"the resolver {resolver!r} is an IPv6 address, and this tunnel carries "
            "IPv4 only — every IPv6 packet a friend's device sends into it is dropped "
            "at the node. The device would ask this resolver and never hear back, so "
            "no name would resolve at all. Give an IPv4 address."
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
    ``exit_via`` would be: it is a fact about the node, kept for the day it dials a hop —
    and, since M23, read by ``client_resolvers`` for a friend's own config file on a node
    that never dials one. This function still ignores it off a hop, because a PROXY on a
    node without one has nothing to move; that is a statement about this consumer and no
    longer about the field.

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


# What a FRIEND's device is told to send into the tunnel, and the second-widest value in
# this module. BOTH families, and the IPv6 half is the deliberate one — M23, measured on
# the owner's real leaf.
#
# That leaf has no IPv6 at all: no global v6 address, no v6 default route, nothing
# reachable. Nor could it have, from anything this project renders — ``wg_quick_egress``
# refuses a v6 tunnel outright and ``_rules`` are ``iptables``. So every IPv6 packet a
# friend's device sends in dies at the node. It dies BEFORE any rule of ours is
# consulted, which is the fact every proposed remedy founders on: AllowedIPs is the
# authorisation list as well as the routing table, and a friend's peer entry on the node
# authorises one IPv4 host route, so WireGuard itself discards a decrypted packet whose
# source is a v6 address.
#
# It stays wide anyway, because both alternatives are worse than what it costs:
#
# * NARROWING IT TO IPv4 does not stop the traffic, it re-routes it. IPv6 would leave by
#   the friend's own connection, from their own address, to every destination that has an
#   IPv6 one — fast, silent, and an exit in the country the whole topology exists to
#   leave, with every screen green. A performance fix that produces the failure this
#   project is most afraid of.
# * A REJECTION AT THE NODE, so the device gives up on IPv6 at once instead of waiting,
#   cannot be built at this layer at all. The packet never reaches a filter chain (see
#   above), and an ICMPv6 answer could not get back: this node has no IPv6 route to the
#   friend's address, and their peer entry does not authorise that address either, so its
#   own WireGuard would drop the answer on the way out. ``-j REJECT`` here would be a rule
#   that never matches — and a test asserting it was present would pass.
#
# What it costs a friend is real and is not fixable in this zone: a destination reachable
# over both families is tried over IPv6 first and answers only once their device gives up
# on it. What would fix it is a node that can CARRY IPv6 — a v6 address for every friend,
# a v6 range on the tunnel, and rules in the other tool — and whether a node can do that
# is a fact about a host. Nothing in this zone may look at one, so it would have to arrive
# on the node's record, the way ``resolver`` did.
CLIENT_ROUTES = ("0.0.0.0/0", "::/0")


def client_resolvers(
    client_dns: Sequence[str], node_resolver: str | None, tunnel_address: str
) -> tuple[str, ...]:
    """The resolvers a FRIEND's config names, in the order they are written.

    The third consumer of the same M16 question — "where are the names this node's
    traffic asks for looked up" — and the one M23 found missing on a real leaf. A
    friend's config routes every address into the tunnel (``AllowedIPs = 0.0.0.0/0,
    ::/0``, which is the charter: their traffic exits abroad, not some of it). That route
    includes the resolver the device was already using, and on a home or office network
    that resolver is a private address on the near side, unreachable from the exit. So
    the tunnel comes up, the handshake completes, five megabytes move — and not one name
    resolves. Measured on the real leaf with two real clients, both identically.

    Two sources, most specific first, and neither is a value this module chose:

    * ``client_dns`` — the transport's own parameter, per node × transport. An operator
      who answers it has said exactly what a friend's device should ask.
    * the node record's ``resolver`` — M16's field, and the one an operator reaches for
      first. It already answers "where does the traffic leaving this node look names
      up"; a friend's traffic leaves through this node, so it is the same question and
      gets the same answer rather than a second field to keep in step. The friend's query
      travels the tunnel, is decrypted here and leaves by this node's own route — so a
      resolver this node can reach is one that friend can reach. **This widens what the
      field means, deliberately and on the record: see ``edge/node.py``.**

    Empty when neither is set, which is a real state rather than an error, and the client
    template says so in the file itself — including what it costs, which is the half the
    file used to get wrong. It is not refused here: the refusal would punish an operator
    who has no box to answer in, because ``client_dns`` declares a default and
    ``control``'s enable dialog offers a box only for what a transport REQUIRES. That is
    the control-side half of this finding, and until it lands a refusal would turn "a
    friend with no names" into "a friend with no config".

    Two things ARE refused, because both would be worse than silence.

    A resolver inside this tunnel's own network: every address in that range is one a
    friend's device holds, so a resolver there points every friend's lookups at whichever
    person was given it — the one record this project must never create. The transport's
    own ``Params`` already refuses that where it is TYPED; this is the same rule applied
    to the value arriving from the node record, where nothing has yet checked it against
    this tunnel.

    And an IPv6 resolver, which is the same sentence ``resolver_problem`` says about a
    hop, said one consumer further out. A friend's config routes every IPv6 address into
    the tunnel (``CLIENT_ROUTES``) and the node drops all of it, so a v6 resolver is one
    the device can ask and never hear from: every name fails, exactly the M23 failure this
    function was written for, with the box filled in. Refused here rather than in each
    transport's ``Params`` on purpose — what makes it unreachable is the tunnel's egress,
    which is this module's fact and not a property of either protocol.
    """
    resolvers = tuple(client_dns) or tuple(
        value for value in (node_resolver,) if value and value.strip()
    )
    if not resolvers:
        return ()

    network = ipaddress.ip_interface(tunnel_address).network
    for resolver in resolvers:
        # The two rules that need nothing but the value, asked through the predicate a
        # FORM asks them through as well (``client_resolver_problem``) — so the sentence
        # an operator reads when a box refuses their resolver and the sentence a render
        # refuses by are one sentence, and neither can be fixed without the other.
        problem = client_resolver_problem(resolver)
        if problem:
            raise EgressNotRenderable(problem)
        address = ipaddress.ip_address(resolver)
        if address.version == network.version and address in network:
            raise EgressNotRenderable(
                f"the resolver {resolver!r} is inside {network}, which is this tunnel's "
                "own range. Every address in it is one a friend's device is given, so "
                "every friend's lookups would go to whoever holds it. Give a resolver "
                "outside the tunnel."
            )
    return resolvers


__all__ = [
    "CLIENT_ROUTES",
    "EXIT_ROUTE",
    "HOP_ROUTE_TABLE",
    "NOT_THE_INTERNET",
    "NOT_THE_INTERNET_IPV4",
    "NO_RESOLVER",
    "NO_ROUTES",
    "RESOLVER_PORT",
    "RESOLVER_PROTOCOLS",
    "Egress",
    "EgressNotRenderable",
    "ResolverMissing",
    "WgQuickEgress",
    "WgQuickHooks",
    "client_resolver_problem",
    "client_resolvers",
    "exit_origin",
    "lookup_resolver",
    "resolver_problem",
    "wg_quick_egress",
    "wg_quick_hooks",
]
