"""A friend's decrypted packet has to leave the node — M14.

WHAT: the forwarding and NAT a kernel tunnel needs, rendered into the config that
      creates the interface, and removed when the interface goes away.
WHY:  M14 is a field observation, not a hypothesis. On a real entry node with a real
      client the handshake completed in both directions, the interface was ``UP``, the
      container was ``Up`` — and an address echo through the tunnel timed out. The host
      had ``net.ipv4.ip_forward = 1``, a FORWARD policy of DROP, and no NAT rule for the
      tunnel subnet, because the rendered config had no ``PostUp``/``PostDown`` at all.
      Nothing logged it and nothing should: logging is off by charter.

      So every assertion here is about the shape of a file, and the failure it guards is
      the quietest one this project has: a tunnel that is genuinely established and
      carries nothing.
HOW:  pure, like the rest of this zone. Parametrised over the WireGuard family as the
      family is DERIVED — a data plane whose tool takes the interface name from the
      config's filename (``DataPlane.interface_from_config_filename``, M2's rule) — so a
      third member of the family is tested by arriving rather than by being listed.

What this does NOT prove, and it is the whole of M14's first "done when": that a packet
reaches the internet. That is a field observation on a real node with a real client, and
no assertion in this file stands in for it.
"""

import dataclasses
import ipaddress
import re

import pytest

from edge import relay
from edge.bootstrap.node_stack import DATA_PLANES
from edge.egress import (
    NOT_THE_INTERNET,
    NOT_THE_INTERNET_IPV4,
    RESOLVER_PORT,
    RESOLVER_PROTOCOLS,
    Egress,
    EgressNotRenderable,
    wg_quick_hooks,
)
from edge.node import NodeView
from edge.registry import discover, profile

# The family, derived rather than named. Same rule as
# tests/edge/test_the_wireguard_family_can_start.py: what these transports share is a
# TOOL, and the tool is what runs the hooks under test here.
WG_FAMILY = sorted(
    name
    for name, meta in discover().items()
    if DATA_PLANES[meta.config_format].interface_from_config_filename
)

# Every transport, so the parameter is part of the contract rather than a favour two
# packages do the caller.
INSTALLED = sorted(discover())

# wg-quick substitutes this with the interface's real name when it runs a hook. It is
# the ONLY interface token a rendered rule may contain — see the test below.
INTERFACE_TOKEN = "%i"


def hook_lines(config: str, directive: str) -> list[str]:
    """Every ``PostUp``/``PostDown`` line in a rendered wg-quick config."""
    return [
        line.split("=", 1)[1].strip()
        for line in config.splitlines()
        if line.startswith(f"{directive} ")
    ]


def commands(hook: str) -> list[str]:
    """The individual commands one hook line runs, in order."""
    return [part.strip() for part in hook.split(";") if part.strip()]


def rule_spec(command: str) -> str:
    """A netfilter command reduced to the rule it names, with the verb removed.

    ``-I FORWARD 1 -i %i -j ACCEPT`` and ``-D FORWARD -i %i -j ACCEPT`` describe ONE
    rule: the first installs it, the second removes it. Reducing both to the same text
    is what lets this file assert that teardown is the exact inverse of setup, rather
    than that both lines merely mention iptables.
    """
    without_shell = command.split("||", 1)[0].strip()
    words = without_shell.split()
    reduced: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        if word in {"-I", "-A"}:
            # The chain, and the position an insert carries and a delete does not.
            reduced.append(words[index + 1])
            index += 2
            if index < len(words) and words[index].isdigit():
                index += 1
            continue
        if word == "-D":
            reduced.append(words[index + 1])
            index += 2
            continue
        reduced.append(word)
        index += 1
    return " ".join(reduced)


# A stand-in for whatever this host's route to the internet is called. It is never
# RENDERED — the rules name only ``%i`` and the test above holds them to it — so this is
# only a second interface to evaluate a packet against, and any name that is not ``%i``
# would do.
SOME_OTHER_INTERFACE = "not-the-tunnel"

# A destination that stands for "the internet" — the one thing a friend's tunnel is for,
# and since M23's fifth round the only thing it carries. It CANNOT be an RFC 5737
# documentation address like every other fixture in this zone: those ranges are exactly
# what the new rules drop, so a packet addressed to one would prove the opposite of what
# it was asked. This is the deprecated 6to4 relay anycast block — reserved, so it is
# nobody's host and nothing here ever dials it, and globally routable, so the rules must
# carry it. ``test_the_destination_that_stands_for_the_internet_is_on_it`` holds it to
# that rather than trusting this comment.
SOMEWHERE_ON_THE_INTERNET = "192.88.99.10"

# The address the walk actually reached: the Russian entry node's end of the hop, on the
# real leaf that carries the owner's traffic. RFC 1918, so nothing on the open internet
# can reach it — which is the whole of the finding. A friend's tunnel handed it out.
THE_ENTRY_ON_THE_HOP = "10.90.0.1"

# A resolver a node's record may legitimately name and a friend's tunnel would otherwise
# drop. The same value as ``tests/edge/test_a_friends_lookup_leaves_through_the_hop.py``
# uses, written out again rather than imported: pytest runs with
# ``--import-mode=importlib`` and this zone's conftest says test modules here do not
# import each other.
A_RESOLVER_ON_THE_INTERNET = "192.88.99.53"


def forward_chain(config: str) -> list[str]:
    """The filter FORWARD chain as the kernel holds it once ``PostUp`` has run.

    Built rather than read off the line, because ORDER is the whole finding here and the
    order in the file is the reverse of the order in the chain: every rule is installed
    with ``-I FORWARD 1``, so the last command in the hook ends up at the head. A test
    that asserted "the DROP is present" would have passed against a DROP sitting behind
    the two ACCEPTs, which is a DROP that decides nothing.
    """
    chain: list[str] = []
    for command in commands(hook_lines(config, "PostUp")[0]):
        words = command.split()
        if words[:3] != ["iptables", "-t", "filter"]:
            continue
        assert words[3:5] == ["-I", "FORWARD"], f"unexpected verb: {command}"
        chain.insert(int(words[5]) - 1, " ".join(words[6:]))
    return chain


def matches(
    rule: str,
    *,
    arriving_on: str,
    leaving_by: str,
    destined_for: str,
    protocol: str | None,
    port: int | None,
) -> bool:
    """Whether one rule matches one packet, read the way netfilter reads it.

    Grew a destination and a port in M23's fifth round, and had to: the friend-facing
    rules now decide by where a packet is GOING, so a matcher that looked only at
    interfaces would report the first rule in the chain as the verdict for every packet —
    and every assertion in this file would have been about the wrong rule while staying
    green.

    An interface, a protocol and a port are compared as the strings iptables holds them.
    A destination is compared by CONTAINMENT, because a rule names a network and a packet
    carries one address. A rule that names something the packet does not carry at all
    does not match it — which is what makes ``-p udp --dport 53`` an exception for a
    lookup rather than for everything sent to that address.
    """
    words = rule.split()

    def named(flag: str) -> str | None:
        return words[words.index(flag) + 1] if flag in words else None

    for flag, value in (
        ("-i", arriving_on),
        ("-o", leaving_by),
        ("-p", protocol),
        ("--dport", port),
    ):
        wanted = named(flag)
        if wanted is None:
            continue
        if value is None or wanted != str(value):
            return False

    destination = named("-d")
    return destination is None or (
        ipaddress.ip_address(destined_for) in ipaddress.ip_network(destination)
    )


def verdict(
    chain: list[str],
    *,
    arriving_on: str,
    leaving_by: str,
    destined_for: str = SOMEWHERE_ON_THE_INTERNET,
    protocol: str | None = None,
    port: int | None = None,
) -> str | None:
    """What netfilter does with one forwarded packet: the FIRST matching rule's target.

    ``None`` when nothing matches, which means the chain's own policy decides — on the
    measured host that is ufw's DROP, and on a host without ufw it is ACCEPT. Neither is
    a property of what this project renders, which is why "nothing matched" is its own
    answer rather than being reported as a drop.

    A packet with no destination named is one bound for the internet, which is what a
    friend's tunnel exists to carry and what most of the questions below are about.
    """
    for rule in chain:
        if matches(
            rule,
            arriving_on=arriving_on,
            leaving_by=leaving_by,
            destined_for=destined_for,
            protocol=protocol,
            port=port,
        ):
            words = rule.split()
            return words[words.index("-j") + 1]
    return None


def rendered(name: str, node, request, egress: Egress) -> str:
    """One transport's server config under one egress policy."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    clients = fixture(name, "credentials")
    return transport.profile.render_server(node, validated, clients, egress=egress)


def a_friends_address(name: str, request) -> str:
    """One address on this tunnel that a friend's device holds.

    The first address the pool hands out, out of the transport's own parameters, so the
    question "can one friend reach another" is asked with the address a friend actually
    has rather than with one this file invented.
    """
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    return str(ipaddress.ip_interface(str(validated["peer_tunnel_address"])).ip)


# --- M14.1: the traffic must leave the node ---------------------------------------

@pytest.mark.parametrize("name", WG_FAMILY)
def test_a_local_exit_renders_the_rules_the_kernel_needs(name: str, node, request) -> None:
    """FORWARD in both directions, and one MASQUERADE for the tunnel's own subnet.

    All three, because the field failure needed all three: the packet was dropped by the
    FORWARD chain having never been NATed, and either rule alone would still have left it
    dead.
    """
    config = rendered(name, node, request, Egress.LOCAL)
    up = hook_lines(config, "PostUp")

    assert len(up) == 1, f"expected exactly one PostUp line, got {up}"
    specs = [rule_spec(command) for command in commands(up[0])]

    assert "FORWARD -i %i -j ACCEPT" in " | ".join(specs), specs
    assert "FORWARD -o %i -j ACCEPT" in " | ".join(specs), specs
    assert any("MASQUERADE" in spec for spec in specs), specs


# --- M23: and it must leave, rather than arrive at the friend in the next flat -------

@pytest.mark.parametrize("name", WG_FAMILY)
def test_one_friend_cannot_reach_another_inside_the_tunnel(
    name: str, node, request
) -> None:
    """The walk's ``ping`` and its ``nc``, asked of the chain instead of of a host.

    Measured on the real leaf with two real clients: one friend pinged the other's tunnel
    address with 0% loss and carried a TCP payload to a listener on it. The cause was not
    the crypto — a friend cannot forge another's address, which the same walk confirmed —
    it was this chain. ``-i %i -j ACCEPT`` matches a packet that arrives on the tunnel and
    leaves by the tunnel, and with a pool every friend on the node is in one routed
    network, so thirty people who need not know each other could reach each other's
    laptops and phones.

    Asserted as the VERDICT rather than as the presence of a rule, because the presence of
    a rule was never the question: a DROP behind either ACCEPT is a DROP that never runs.
    """
    chain = forward_chain(rendered(name, node, request, Egress.LOCAL))

    assert verdict(
        chain,
        arriving_on=INTERFACE_TOKEN,
        leaving_by=INTERFACE_TOKEN,
        # The other friend's own address, out of this transport's own parameters, rather
        # than a packet bound for the internet that happens to be leaving by the tunnel.
        # It is what the walk sent, and since the rules decide by destination it is the
        # only version of this question that still asks anything.
        destined_for=a_friends_address(name, request),
    ) == "DROP"


@pytest.mark.parametrize("name", WG_FAMILY)
def test_the_way_out_and_the_way_back_stay_open(name: str, node, request) -> None:
    """The other half, and the one a wider drop would take with it.

    ``-i %i -j DROP`` would close friend-to-friend and the exit in the same stroke, which
    is M14 again with a different author. The drop has to be exactly the pair that both
    enters and leaves by this interface; everything else is what the tunnel is for, in
    both directions.
    """
    chain = forward_chain(rendered(name, node, request, Egress.LOCAL))

    assert verdict(
        chain, arriving_on=INTERFACE_TOKEN, leaving_by=SOME_OTHER_INTERFACE
    ) == "ACCEPT"
    assert verdict(
        chain, arriving_on=SOME_OTHER_INTERFACE, leaving_by=INTERFACE_TOKEN
    ) == "ACCEPT"


@pytest.mark.parametrize("name", WG_FAMILY)
def test_nothing_between_two_other_interfaces_is_touched(
    name: str, node, request
) -> None:
    """Scoped to this tunnel, so nothing else the operator firewalls is decided here.

    A node runs other things — the control plane reaches it over SSH, and a second
    transport may have its own interface — and a rule of ours that matched their traffic
    would be this project deciding a policy it was never asked about.
    """
    chain = forward_chain(rendered(name, node, request, Egress.LOCAL))

    assert verdict(
        chain, arriving_on=SOME_OTHER_INTERFACE, leaving_by=SOME_OTHER_INTERFACE
    ) is None


# --- M23, round 5: and it must leave for the INTERNET, not into the node's own wiring --

def test_the_destination_that_stands_for_the_internet_is_on_it() -> None:
    """The fixture every question below leans on, held to what it claims.

    If this address were one of the ranges a friend's tunnel drops, every "still reaches
    the internet" assertion in this file would be asking whether a DROP is an ACCEPT —
    and would have been changed to agree with whatever the rules did.
    """
    assert ipaddress.ip_address(SOMEWHERE_ON_THE_INTERNET).is_global
    assert ipaddress.ip_address(A_RESOLVER_ON_THE_INTERNET).is_global
    assert not ipaddress.ip_address(THE_ENTRY_ON_THE_HOP).is_global


@pytest.mark.parametrize("name", WG_FAMILY)
def test_a_friend_cannot_reach_the_node_this_one_is_attached_to(
    name: str, node, request
) -> None:
    """The walk's ``nc 10.90.0.1 22``, asked of the chain instead of of a host.

    Measured on the owner's real leaf with a real client: a friend opened TCP to the
    Russian ENTRY node's address on the hop and was answered by its SSH daemon, with the
    packet masqueraded on the way in so the entry saw it arrive from its own trusted peer.
    Ports 80 and 443 answered too and 4444 did not, so it was the host and not a probe
    artefact, and the round trip named it: 104 ms against the leaf's own 52.

    The cause was ``-i %i -j ACCEPT``, which permits a friend's packet to leave by ANY
    interface — and one of this host's interfaces is the hop, the owner's live route out
    of Russia. Asked here as a VERDICT on a packet leaving by SOME OTHER interface,
    because "which interface" is exactly what this project's rules may not name.
    """
    chain = forward_chain(rendered(name, node, request, Egress.LOCAL))

    assert verdict(
        chain,
        arriving_on=INTERFACE_TOKEN,
        leaving_by=SOME_OTHER_INTERFACE,
        destined_for=THE_ENTRY_ON_THE_HOP,
    ) == "DROP"


@pytest.mark.parametrize("destination", NOT_THE_INTERNET_IPV4)
@pytest.mark.parametrize("name", WG_FAMILY)
def test_nothing_off_the_internet_is_reachable_from_a_friends_tunnel(
    name: str, destination: str, node, request
) -> None:
    """The whole class, not just the address the walk happened to dial.

    The hop was the one that was found, but a leaf is attached to more than its hop: its
    provider's LAN, its metadata service on ``169.254.169.254``, any other tunnel on the
    box. One rule per range, and this asks each of them for a verdict rather than
    asserting the rule is in the file.

    Over ``NOT_THE_INTERNET_IPV4`` rather than over the whole list since M23's twelfth
    round, and the narrowing is asserted rather than assumed: the test below holds that
    constant to being exactly the v4 half of the one list, and the one after it holds
    these rules to naming no other family. Asking an ``iptables`` chain for its verdict
    on ``fc00::2`` would be asking it a question it cannot be given.
    """
    chain = forward_chain(rendered(name, node, request, Egress.LOCAL))
    somewhere_in_it = str(ipaddress.ip_network(destination)[1])

    assert verdict(
        chain,
        arriving_on=INTERFACE_TOKEN,
        leaving_by=SOME_OTHER_INTERFACE,
        destined_for=somewhere_in_it,
    ) == "DROP"


# The registry as the standard library holds it, by family, and the ONE range this
# project deliberately does not carry.
#
# ``100.64.0.0/10`` joins the v4 half because ``ipaddress`` keeps it out of
# ``_private_networks`` and answers for it separately, at address level, inside
# ``is_global``. There is no v6 equivalent — carrier-grade NAT is a v4 problem.
#
# ``::ffff:0:0/96`` is the exception, and it is stated here rather than discovered at
# the assertion so that it is read as a decision. The pinned Xray refuses that CIDR
# outright — ``invalid network mask for router: 96`` — because it folds an IPv4-mapped
# address back to four bytes before measuring the prefix. The same folding is why
# nothing escapes: every address in it IS an address in the v4 half by the time any rule
# reads it, which the proxy file measures rather than argues.
IANAS_REGISTRY = {
    4: [
        *ipaddress.IPv4Address._constants._private_networks,
        ipaddress.IPv4Network("100.64.0.0/10"),
    ],
    6: list(ipaddress.IPv6Address._constants._private_networks),
}
SPELLED_IN_THE_OTHER_FAMILY = ipaddress.IPv6Network("::ffff:0:0/96")

# The well-known NAT64 prefix — M23's thirteenth round, and the reason the first
# direction below is no longer one assertion. Stated here rather than imported from
# ``edge.egress`` for the reason ``IANAS_REGISTRY`` reads the standard library rather
# than the renderer: what this file is for is holding the constant against an answer it
# worked out without it.
#
# RFC 6052 §2.2 puts the IPv4 address in the low 32 bits of a /96 well-known-prefix
# address, which is the arithmetic ``decoded_from_nat64`` below undoes.
NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")

# The other registry entry that is GLOBALLY REACHABLE, and the one range this list must
# never grow. Named so the decision is under assertion instead of in a comment somebody
# re-opens: see ``test_the_two_globally_reachable_registry_entries_are_a_decision``.
THE_6TO4_RELAY_ANYCAST = ipaddress.IPv4Network("192.88.99.0/24")


def decoded_from_nat64(network: ipaddress.IPv6Network) -> ipaddress.IPv4Network:
    """The IPv4 range a well-known-prefix NAT64 range carries in its low 32 bits."""
    return ipaddress.IPv4Network(
        (
            int(network.network_address) & 0xFFFFFFFF,
            network.prefixlen - NAT64_WELL_KNOWN.prefixlen,
        )
    )


def test_every_range_a_friend_cannot_reach_is_the_registrys_or_a_spelling_of_one() -> None:
    """What the list tracks, in both directions and both families — and it is not one rule.

    ``CLAUDE.md`` forbids a hardcoded address because it names something a node could
    have to rotate away from. These name nothing of any node, and they are not ours to
    choose: what is on the public internet is a registry, and the standard library
    carries it. Holding the constant against ``ipaddress`` is what keeps that true — a
    range that drifts fails here rather than in a friend's tunnel.

    TWO KINDS OF ENTRY SINCE M23's THIRTEENTH ROUND, which is the round that had to say
    what the list actually tracks. It is NOT IANA's registry as such: two entries of that
    registry are marked globally reachable, and a friend dialling either reaches the
    public internet. So the ordinary entry is held to ``not is_global`` exactly as before,
    and the second kind — a range inside the well-known NAT64 prefix — is held to
    something else entirely, because it IS globally reachable and is refused anyway: its
    low 32 bits are an IPv4 address this list already refuses, and a NAT64 translator on
    the path puts the packet there. Measured, not argued: ``[64:ff9b::7f00:1]`` was
    reached through the product's own rendered config in the round before this one, in
    the same run that refused ``127.0.0.1`` and ``[::ffff:127.0.0.1]``.

    Each is checked against its OWN claim rather than one loosened claim covering both,
    so an ordinary range that becomes globally reachable still fails here, and a NAT64
    range that stopped decoding into the v4 half fails too.

    BOTH FAMILIES SINCE M23's TWELFTH ROUND, which is the round that found the list was
    only ever half of what it claimed to be: ``[::1]`` and ``[fc00::2]`` answered a
    friend through the product's own rendered proxy config while ``127.0.0.1`` and
    ``172.17.0.5`` were refused. Asked per family rather than over one flat list, because
    ``subnet_of`` across families is a ``TypeError`` — so a flat loop would have passed
    by short-circuiting on the v4 entries that come first, which is exactly what it did
    for one round after the v6 half was added.

    The second half reads ``ipaddress``'s own private list, which is not public API. That
    is deliberate and it belongs HERE rather than in the renderer: a test may notice that
    a Python upgrade moved the registry, and should; a rendered firewall rule may not
    depend on an underscore.
    """
    ours = [ipaddress.ip_network(network) for network in NOT_THE_INTERNET]
    refusing_v4 = [network for network in ours if network.version == 4]

    # Nothing we drop is on the internet — so no friend loses a destination they could
    # legitimately have reached. Unless it is one address wearing another's hat, which is
    # the one licence this list has and is spent entirely inside the NAT64 prefix.
    for network in ours:
        if network.version == 6 and network.subnet_of(NAT64_WELL_KNOWN):
            carried = decoded_from_nat64(network)
            assert any(carried.subnet_of(covering) for covering in refusing_v4), (
                f"{network} is globally reachable and is dropped, and what it carries "
                f"({carried}) is not something this list refuses — so it is not a second "
                "spelling of anything and a friend loses a destination for nothing"
            )
            continue
        assert not network.is_global, f"{network} is on the internet and is dropped"

    # And nothing off the internet escapes, in either family.
    for version, registry in IANAS_REGISTRY.items():
        covering_us = [network for network in ours if network.version == version]
        assert covering_us, f"nothing in this list is IPv{version} at all"
        for network in registry:
            if network == SPELLED_IN_THE_OTHER_FAMILY:
                continue
            assert any(network.subnet_of(covering) for covering in covering_us), (
                f"{network} is not on the internet and nothing drops it"
            )

    # Two /32s inside ``192.0.0.0/24`` — the PCP and NAT64 discovery anycast addresses —
    # ARE globally reachable, and are dropped with the block around them. Deliberate, and
    # asserted rather than left to be discovered: they are IETF protocol machinery no
    # friend's device asks a VPN for, and two exceptions in every node's firewall would
    # cost more to read than they buy. The v6 half has six of the same shape, all inside
    # ``2001::/23``, and they are carried on the same terms.
    for constants in (ipaddress.IPv4Address._constants, ipaddress.IPv6Address._constants):
        for exception in constants._private_networks_exceptions:
            covering_us = [
                network for network in ours if network.version == exception.version
            ]
            assert any(exception.subnet_of(covering) for covering in covering_us), exception


def test_every_range_the_v4_half_refuses_is_refused_in_its_nat64_spelling_too() -> None:
    """The derivation, held — so the fourteenth range cannot arrive without its spelling.

    M23's thirteenth round found ``[64:ff9b::7f00:1]`` reaching a node's own loopback
    through the product's own rendered config: ``64:ff9b::/96`` carries an IPv4 address in
    its low 32 bits, and every range this list held in that family was written out by
    hand, so the one that mattered was simply not among them. Typing the thirteen would
    have closed that finding and left the class open — the next range added to the v4 half
    would arrive with no spelling in the other.

    So the spelling is derived in ``edge/egress.py`` and this is what says it stayed
    derived. A second hand-maintained tuple passes every other assertion in this file.

    The v4 half ONLY. The v6 ranges have no NAT64 spelling: the prefix embeds four bytes,
    which is what makes the arithmetic total for one family and undefined for the other.
    """
    ours = [ipaddress.ip_network(network) for network in NOT_THE_INTERNET]
    spelled = {
        decoded_from_nat64(network)
        for network in ours
        if network.version == 6 and network.subnet_of(NAT64_WELL_KNOWN)
    }

    assert spelled == {ipaddress.ip_network(network) for network in NOT_THE_INTERNET_IPV4}, (
        "the two spellings of this list have drifted: a destination a friend cannot reach "
        "in one family is reachable in the other, which is the whole of the finding"
    )


def test_the_two_globally_reachable_registry_entries_are_a_decision() -> None:
    """Why the list is not simply IANA's registry, pinned so the next walk reads it.

    Two entries of that registry are marked GLOBALLY REACHABLE, and a walk that reads the
    registry and not this test files both as gaps. They are not gaps, and they are not the
    same case as each other:

    * ``192.88.99.0/24``, the deprecated 6to4 relay anycast block. A packet addressed
      there arrives at a relay router on the public internet and nothing in the address
      says where it goes next — so it IS the internet, and it is the address this
      project's own stands use for that word (``tests/edge`` above, and
      ``tests/e2e/edge/test_a_friend_exits_at_the_leaf_and_not_at_the_entry.py``, which
      round eleven had to fix because it was passing through the very bypass it was
      closing). Adding it would refuse the one destination those scenarios exist to prove
      a friend still reaches.
    * ``64:ff9b::/96``, the well-known NAT64 prefix. Globally reachable too, and an
      address in it with a GLOBAL IPv4 address inside is how a v6-only client reaches the
      v4 internet — so the prefix itself stays reachable, and only its embeddings of what
      this list already refuses are refused. That split is the thirteenth round's whole
      answer, and this holds both halves of it.

    So the membership test this list actually applies is "not globally reachable, or a
    spelling of something that is not" — and these two are what make that sentence
    necessary rather than a restatement of the registry.
    """
    ours = [ipaddress.ip_network(network) for network in NOT_THE_INTERNET]

    assert THE_6TO4_RELAY_ANYCAST.is_global and NAT64_WELL_KNOWN.is_global, (
        "the two ranges this test is about are no longer globally reachable, so the "
        "decision it pins has changed and the reasoning above has to be rewritten"
    )
    # By family, because ``subnet_of`` across two is a ``TypeError`` rather than a False —
    # the same trap round twelve fell into with a flat loop.
    for reachable in (THE_6TO4_RELAY_ANYCAST, NAT64_WELL_KNOWN):
        for network in ours:
            if network.version != reachable.version:
                continue
            assert not reachable.subnet_of(network), (
                f"{network} refuses the whole of {reachable}, which is on the public "
                "internet: the first is what this project's stands mean by the word, and "
                "the second is every v6-only client's route to the v4 internet. Only the "
                "NAT64 prefix's embeddings of the v4 half belong in this list"
            )


def test_the_one_list_carries_both_families_and_each_renderer_takes_its_own() -> None:
    """One list, split by ``ipaddress`` rather than by a second tuple somebody types.

    The two data planes that read ``NOT_THE_INTERNET`` do not have the same reach: a
    proxy writes it into Xray's ``routing.rules[].ip``, which takes both families, and
    the wg family writes it into ``iptables``, which takes one. Round eleven named that
    as the reason the v6 half could not simply be added, and this is the shape that
    answers it — so what this holds is that the split stays DERIVED. A second
    hand-maintained list would pass every other assertion in this file while drifting.
    """
    families = {ipaddress.ip_network(network).version for network in NOT_THE_INTERNET}
    assert families == {4, 6}, (
        f"the one list names only IPv{families.pop()}, so a destination spelled in the "
        "other family walks past every refusal this project renders"
    )

    assert NOT_THE_INTERNET_IPV4 == tuple(
        network for network in NOT_THE_INTERNET if ipaddress.ip_network(network).version == 4
    )
    # Order too, and not only membership: the wg family's rules are installed at the head
    # of the chain in reverse, so a reordering is a different chain.
    assert NOT_THE_INTERNET[: len(NOT_THE_INTERNET_IPV4)] == NOT_THE_INTERNET_IPV4


@pytest.mark.parametrize("name", WG_FAMILY)
def test_no_rule_a_kernel_tunnel_renders_names_an_address_iptables_cannot_take(
    name: str, node, request
) -> None:
    """The constraint that made the split necessary, asserted where it would break.

    An IPv6 destination in an ``iptables`` rule is not a narrower rule — the command
    refuses it, wg-quick runs the hook under ``set -e``, and the interface does not come
    up. So every node in the wg family would stop carrying traffic, which is the failure
    this whole module exists to prevent, produced by a fix for a different one.

    Every address any rendered rule names, whatever the flag that names it, so a resolver
    exception or a masqueraded source added later is held to the same answer as a drop.
    """
    config = rendered(name, node, request, Egress.LOCAL)
    rules = [
        rule_spec(command)
        for directive in ("PostUp", "PostDown")
        for hook in hook_lines(config, directive)
        for command in commands(hook)
    ]
    assert rules, "nothing was rendered, so this asserts nothing"

    named: list[tuple[str, object]] = []
    for rule in rules:
        for word in rule.split():
            try:
                network = ipaddress.ip_network(word, strict=False)
            except ValueError:
                continue
            named.append((rule, network))

    # Counted, not just filtered: if what a rule looks like ever changed enough that
    # nothing here parses as an address, every assertion below would hold vacuously and
    # this test would go on passing over rules it had stopped reading.
    assert len(named) > len(NOT_THE_INTERNET_IPV4), (
        f"only {len(named)} addresses were found in {len(rules)} rules, which is fewer "
        "than the drops alone — this test is no longer reading what it is about"
    )
    for rule, network in named:
        assert network.version == 4, (
            f"{rule!r} names {network}, which iptables cannot take: the hook fails, "
            "the interface never comes up, and the node carries nothing"
        )


@pytest.mark.parametrize("name", WG_FAMILY)
def test_a_friend_may_still_ask_the_resolver_their_own_file_names(
    name: str, node, request
) -> None:
    """The exception, and the reason the drops above do not take DNS with them.

    A node's record is allowed to name a PRIVATE resolver — ``resolver_problem`` refuses
    loopback and a name and deliberately allows this, because a resolver the node can
    reach is one its friends can reach through it — and ``client_resolvers`` writes that
    value into every friend's own config file. Dropped, it would take every name away
    from every friend on that node while addresses kept working: the shape this project
    fears, produced by the fix for it.

    Both protocols, because a lookup falls back to TCP for an answer that does not fit.
    """
    chain = forward_chain(rendered(name, node, request, Egress.LOCAL))

    assert not ipaddress.ip_address(node.resolver).is_global, (
        "this node's resolver is on the internet, so it needs no exception and this "
        "test would pass without one"
    )
    for protocol in RESOLVER_PROTOCOLS:
        assert verdict(
            chain,
            arriving_on=INTERFACE_TOKEN,
            leaving_by=SOME_OTHER_INTERFACE,
            destined_for=node.resolver,
            protocol=protocol,
            port=int(RESOLVER_PORT),
        ) == "ACCEPT"


@pytest.mark.parametrize("name", WG_FAMILY)
def test_the_exception_is_a_lookup_and_not_the_host_that_answers_it(
    name: str, node, request
) -> None:
    """Scoped to the port DNS is spoken on, which is the whole width of the exception.

    An operator is free to point their friends' resolver at any address, and one of the
    addresses they could point it at is the entry node. Address-only, this exception would
    hand back in full the reach the rules above exist to take away — the finding, through
    the door left open for its own fix.
    """
    chain = forward_chain(rendered(name, node, request, Egress.LOCAL))

    assert verdict(
        chain,
        arriving_on=INTERFACE_TOKEN,
        leaving_by=SOME_OTHER_INTERFACE,
        destined_for=node.resolver,
        protocol="tcp",
        port=22,
    ) == "DROP"


@pytest.mark.parametrize("name", WG_FAMILY)
def test_a_resolver_on_the_internet_needs_no_rule_of_its_own(
    name: str, node, request
) -> None:
    """The exception exists only where the drops would otherwise take it away.

    So a node whose resolver is an ordinary public one renders no exception at all, its
    rule set says exactly what its exceptions are, and the bytes of its config do not
    move when the record is filled in — which is the claim
    ``test_a_friends_lookup_leaves_through_the_hop.py`` still holds for every transport.
    """
    on_the_internet = dataclasses.replace(node, resolver=A_RESOLVER_ON_THE_INTERNET)
    chain = forward_chain(rendered(name, on_the_internet, request, Egress.LOCAL))

    assert not any(A_RESOLVER_ON_THE_INTERNET in rule for rule in chain), chain
    assert verdict(
        chain,
        arriving_on=INTERFACE_TOKEN,
        leaving_by=SOME_OTHER_INTERFACE,
        destined_for=A_RESOLVER_ON_THE_INTERNET,
        protocol="udp",
        port=int(RESOLVER_PORT),
    ) == "ACCEPT"


@pytest.mark.parametrize("name", WG_FAMILY)
def test_the_masqueraded_source_is_the_tunnels_own_subnet(name: str, node, request) -> None:
    """Derived from the interface address in the node's own record, never a constant."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    network = ipaddress.ip_interface(str(validated["tunnel_address"])).network

    config = rendered(name, node, request, Egress.LOCAL)

    assert f"-s {network}" in hook_lines(config, "PostUp")[0]


@pytest.mark.parametrize("name", WG_FAMILY)
def test_no_egress_interface_name_is_hardcoded(name: str, node, request) -> None:
    """The trap M14 names. Every ``-i``/``-o`` in a rule is wg-quick's own ``%i``.

    ``eth0`` is not the egress interface everywhere, and a rendered name is a node this
    fleet could not rotate onto. The rule is written so it never needs one: masquerade
    what came from the tunnel and is leaving by anything that is not the tunnel.
    """
    config = rendered(name, node, request, Egress.LOCAL)

    for directive in ("PostUp", "PostDown"):
        for hook in hook_lines(config, directive):
            interfaces = re.findall(r"(?:^|\s)-[io]\s+(\S+)", hook)
            assert interfaces, f"{directive} names no interface at all: {hook}"
            assert set(interfaces) == {INTERFACE_TOKEN}, (
                f"{directive} hardcodes an interface name: {sorted(set(interfaces))}"
            )


@pytest.mark.parametrize("name", WG_FAMILY)
def test_nothing_rendered_ever_logs_a_packet(name: str, node, request) -> None:
    """Charter, and netfilter has a LOG target that would break it in one word."""
    for policy in (Egress.NONE, Egress.LOCAL):
        config = rendered(name, node, request, policy)
        assert " LOG" not in config
        assert "NFLOG" not in config
        assert "--log-prefix" not in config


# --- M14.2: and it must stop when the tunnel does ----------------------------------

@pytest.mark.parametrize("name", WG_FAMILY)
def test_every_rule_added_is_removed_again(name: str, node, request) -> None:
    """PostDown is the exact inverse of PostUp — the whole of M14.2.

    A rule left behind on a node whose transport was disabled is residue on a host the
    project promises holds nothing that cannot be regenerated. Asserted as set equality
    over the rules themselves rather than "there is a PostDown", because a PostDown that
    removes two of three rules reads as present and leaves the interesting one.
    """
    config = rendered(name, node, request, Egress.LOCAL)

    added = [rule_spec(command) for command in commands(hook_lines(config, "PostUp")[0])]
    removed = [rule_spec(command) for command in commands(hook_lines(config, "PostDown")[0])]

    assert sorted(added) == sorted(removed)


@pytest.mark.parametrize("name", WG_FAMILY)
def test_teardown_does_not_abandon_the_rest_of_its_rules(name: str, node, request) -> None:
    """Each delete tolerates a rule that is already gone.

    ``wg-quick`` runs a hook under ``set -e``, so the first delete that fails abandons
    every delete after it — and a rule the previous run already removed fails. Without
    this the residue M14.2 exists to prevent is created by the teardown itself.
    """
    config = rendered(name, node, request, Egress.LOCAL)

    for command in commands(hook_lines(config, "PostDown")[0]):
        assert command.endswith("|| true"), command


# --- M14.3: the policy is data, and a hop end never exits locally ------------------

@pytest.mark.parametrize("name", INSTALLED)
def test_the_policy_defaults_to_no_exit_at_all(name: str, node, request) -> None:
    """Fail closed. A caller that says nothing gets a tunnel that forwards nothing.

    Decision 3: no exit beats a quiet local one. This is asserted over EVERY transport,
    including those whose data plane cannot express the policy — the default has to be
    safe before it is useful.
    """
    config = rendered(name, node, request, Egress.NONE)

    assert "iptables" not in config
    assert "MASQUERADE" not in config
    assert "PostUp" not in config
    assert "PostDown" not in config


@pytest.mark.parametrize("name", INSTALLED)
def test_the_default_is_the_no_exit_policy(name: str, node, request) -> None:
    """Omitting the argument renders exactly what asking for no exit renders."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    clients = fixture(name, "credentials")

    assert transport.profile.render_server(node, validated, clients) == rendered(
        name, node, request, Egress.NONE
    )


HOP_CAPABLE_FAMILY = [name for name in WG_FAMILY if profile(name).meta.hop_capable]

# The two ends of one hop, as ``render_hop`` writes them. A tunnel network of its own, so
# nothing here is confused with the friend-facing fixtures above.
HOP_NETWORK = ("10.44.0.1/24", "10.44.0.2/24")


def hop_configs(name: str, node, request) -> tuple[str, str]:
    """One hop rendered for both of its ends, entry first.

    Through ``render_hop`` rather than by calling the renderer twice, because WHICH
    POLICY each end gets is that function's decision and not the caller's — which is the
    property several of the tests below are about.
    """
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    base = fixture(name, "params")
    near, far = HOP_NETWORK
    entry = relay.HopEnd(
        node=node,
        params=transport.validate(
            {**base, "tunnel_address": near, "peer_tunnel_address": far}
        ),
    )
    leaf = relay.HopEnd(
        node=NodeView(
            id="99999999-9999-4999-8999-999999999999",
            # RFC 5737 documentation address, like every fixture in this zone.
            address="192.0.2.30",
            location_label="leaf",
            display_name="leaf-2",
            resolver=None,
        ),
        params=transport.validate(
            {**base, "tunnel_address": far, "peer_tunnel_address": near}
        ),
    )
    return relay.render_hop(name, entry=entry, leaf=leaf)


@pytest.mark.parametrize("name", HOP_CAPABLE_FAMILY)
def test_only_the_leaf_end_of_a_hop_exits_locally(name: str, node, request) -> None:
    """The failure the charter is most afraid of, asserted at the end that could have it.

    The two ends are not symmetric, and M3 is where that stopped being academic. The LEAF
    masquerades what arrives over the hop out of its own route — that IS the exit, the
    foreign address a friend is supposed to appear from. The ENTRY must never do it:
    masquerading there is a friend in Russia exiting in Russia while every screen shows
    green. ``render_hop`` fixes both rather than trusting whatever the caller believed.

    M14 left this as "neither end, ever", with a note that the property had to survive M3.
    Half of it did not, and could not: an exit that masquerades nowhere is a hop that
    carries nothing. What survives — and is the assertion worth having — is that the entry
    never does.
    """
    entry_config, leaf_config = hop_configs(name, node, request)

    assert "MASQUERADE" not in entry_config, "the entry masquerades a friend into Russia"
    # The leaf's is the exit itself, and it is the same rule M14 measured on real
    # hardware: FORWARD both ways, and one masquerade for the tunnel's own subnet — which
    # is the range the entry's own tunnel address sits in.
    assert "MASQUERADE" in leaf_config
    assert hook_lines(leaf_config, "PostUp"), "the leaf forwards nothing, so the hop exits nowhere"


@pytest.mark.parametrize("name", HOP_CAPABLE_FAMILY)
def test_the_leaf_end_of_a_hop_renders_the_rules_it_was_already_running(
    name: str, node, request
) -> None:
    """The owner's live hop, pinned — M23's fifth round changed nothing at this end.

    That end is the leaf side of the tunnel carrying the owner's real traffic out of
    Russia, and the next apply rewrites its file. So the narrowing a friend's tunnel
    received is asserted to have stopped here, rule for rule and in order: the two
    ACCEPTs, the drop that keeps the tunnel out of itself, and one masquerade.
    """
    config = rendered(name, node, request, Egress.RELAY)
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    network = ipaddress.ip_interface(str(validated["tunnel_address"])).network

    assert [rule_spec(command) for command in commands(hook_lines(config, "PostUp")[0])] == [
        "iptables -t filter FORWARD -i %i -j ACCEPT",
        "iptables -t filter FORWARD -o %i -j ACCEPT",
        "iptables -t filter FORWARD -i %i -o %i -j DROP",
        f"iptables -t nat POSTROUTING -s {network} ! -o %i -j MASQUERADE",
    ]


@pytest.mark.parametrize("name", HOP_CAPABLE_FAMILY)
def test_what_arrives_over_a_hop_still_reaches_a_private_resolver(
    name: str, node, request
) -> None:
    """Why the leaf end is a policy of its own rather than a friend's tunnel — M16.

    What arrives over a hop is an ENTRY NODE's forwarded traffic, and part of it is that
    node's own lookups: M16 routes them through the hop precisely so they leave at the
    far end, and ``resolver_problem`` allows the record to name a resolver inside the far
    end's own network. A friend's drops applied here would take the hop's own DNS away —
    the failure M16 exists to prevent, reintroduced at the other end of the same tunnel.
    """
    chain = forward_chain(rendered(name, node, request, Egress.RELAY))

    assert verdict(
        chain,
        arriving_on=INTERFACE_TOKEN,
        leaving_by=SOME_OTHER_INTERFACE,
        destined_for=node.resolver,
    ) == "ACCEPT"


@pytest.mark.parametrize("name", HOP_CAPABLE_FAMILY)
def test_a_hop_end_is_told_which_end_it_is_rather_than_being_asked(
    name: str, node, request
) -> None:
    """``render_hop`` decides, exactly as it decides the exit itself.

    The two policies are one argument apart and the wrong one is silent in both
    directions: a friend's tunnel given the relay's rules reaches the entry node, and a
    hop end given a friend's rules stops carrying the entry's lookups. Asserted through
    the function an operator's apply actually goes through, so a caller could not pick.
    """
    _, leaf_config = hop_configs(name, node, request)
    chain = forward_chain(leaf_config)

    assert verdict(
        chain,
        arriving_on=INTERFACE_TOKEN,
        leaving_by=SOME_OTHER_INTERFACE,
        destined_for=THE_ENTRY_ON_THE_HOP,
    ) == "ACCEPT"
    assert chain == forward_chain(
        rendered(name, node, request, Egress.RELAY)
    ), "the leaf end of a hop is not rendering the relay policy"


def test_a_local_exit_over_ipv6_is_refused_rather_than_half_rendered() -> None:
    """Refused, because half a rule is a tunnel that silently carries nothing.

    The hooks this module writes are IPv4 rules. An IPv6 tunnel needs the other tool,
    and one of the pinned data-plane images does not ship it — so rendering an IPv4 rule
    for a v6 subnet, or nothing at all, would reproduce M14 exactly.
    """
    with pytest.raises(EgressNotRenderable):
        wg_quick_hooks(Egress.LOCAL, "fd00:44::1/64")


def test_no_exit_over_ipv6_is_not_refused() -> None:
    """The refusal is about the RULE, not about the address family in general."""
    assert wg_quick_hooks(Egress.NONE, "fd00:44::1/64") is None


# --- M19.3: a hook that runs a program the image may not have ----------------------

# The data planes whose tool runs these hooks, derived the same way ``WG_FAMILY`` is: a
# hook line only ever reaches a tool that reads a wg-quick-style config, and that tool is
# identified by the rule M2 wrote down rather than by a list of names here.
WG_QUICK_DATA_PLANES = sorted(
    {
        config_format: plane
        for config_format, plane in DATA_PLANES.items()
        if plane.interface_from_config_filename
    }.items()
)

# A tunnel address and the way out that runs through it, for the two policies that render
# a hook. Documentation ranges, like every fixture in this zone; neither value reaches an
# assertion, they are only what the rules are built from.
A_TUNNEL = "10.44.0.1/24"
ITS_OWN_ADDRESS = "10.44.0.1"


def programs_a_hook_runs(hooks) -> set[str]:
    """Every program one hook pair invokes, up and down, as bare command names.

    ``argv[0]`` of each statement in the line — the same reading ``/bin/sh`` does when
    wg-quick hands it the hook. ``|| true`` is stripped first, so a teardown's tolerance
    is not mistaken for a second command.
    """
    found = set()
    for line in (hooks.up, hooks.down):
        for command in commands(line):
            found.add(command.split("||", 1)[0].split()[0])
    return found


@pytest.mark.parametrize("egress", list(Egress))
@pytest.mark.parametrize("config_format, data_plane", WG_QUICK_DATA_PLANES)
def test_every_program_a_hook_runs_is_declared_on_the_data_plane(
    egress: Egress, config_format, data_plane
) -> None:
    """The hooks run programs, and only ``DataPlane.executables`` says which — M19.3.

    Nothing about ``command`` reveals them: the tool reads the hook out of the config
    file and hands it to a shell, so an image without the program fails a container at a
    time, inside a script, with an error that reads as a config problem. The declaration
    is what ``tests/edge/test_every_data_plane_command_is_executable.py`` holds against
    the real image, and it is only as good as its completeness.

    ``ip`` is why this exists. M3 put ``ip rule`` and ``ip route`` into the hop's hooks
    and left the declaration alone, so for sixteen milestones the offline check would
    have passed a pinned image with no ``iproute2`` in it. Derived from the rendered
    rules rather than listed, so the next policy that reaches for a new program is
    covered by arriving — which is the half M3 could not have got right by remembering.

    Parametrised over the whole of ``Egress`` for the same reason: it is a closed
    vocabulary, and a fourth value is a fourth set of hooks.
    """
    hooks = wg_quick_hooks(
        egress, A_TUNNEL, exit_via=ITS_OWN_ADDRESS if egress is Egress.HOP else None
    )
    if hooks is None:
        # The policy renders no hook at all, so it invokes nothing. Asserted rather than
        # skipped: "no hooks" is the fail-closed answer and a test that skipped here
        # would stop noticing if it changed.
        assert egress is Egress.NONE, f"{egress} renders no hook and is not the no-exit policy"
        return

    for program in programs_a_hook_runs(hooks):
        assert program in data_plane.executables, (
            f"the {egress} hooks run {program!r} and the data plane for {config_format} "
            f"does not declare it, so nothing holds it against the image that would run "
            f"it: {data_plane.executables}"
        )
