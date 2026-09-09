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

import ipaddress
import re

import pytest

from edge import relay
from edge.bootstrap.node_stack import DATA_PLANES
from edge.egress import Egress, EgressNotRenderable, wg_quick_hooks
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


def rendered(name: str, node, request, egress: Egress) -> str:
    """One transport's server config under one egress policy."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    clients = fixture(name, "credentials")
    return transport.profile.render_server(node, validated, clients, egress=egress)


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


@pytest.mark.parametrize("name", HOP_CAPABLE_FAMILY)
def test_neither_end_of_a_hop_ever_gets_a_local_exit(name: str, node, request) -> None:
    """The failure the charter is most afraid of, asserted at both ends.

    A hop carries traffic BETWEEN our own nodes. Masquerading it out of the entry is a
    friend in Russia exiting in Russia while every screen shows green — so ``render_hop``
    fixes the policy itself rather than trusting whatever the caller believed.
    """
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    base = fixture(name, "params")
    entry = relay.HopEnd(
        node=node,
        params=transport.validate(
            {**base, "tunnel_address": "10.44.0.1/24", "peer_tunnel_address": "10.44.0.2/24"}
        ),
    )
    leaf = relay.HopEnd(
        node=NodeView(
            id="99999999-9999-4999-8999-999999999999",
            # RFC 5737 documentation address, like every fixture in this zone.
            address="192.0.2.30",
            location_label="leaf",
            display_name="leaf-2",
        ),
        params=transport.validate(
            {**base, "tunnel_address": "10.44.0.2/24", "peer_tunnel_address": "10.44.0.1/24"}
        ),
    )

    for config in relay.render_hop(name, entry=entry, leaf=leaf):
        assert "MASQUERADE" not in config
        assert "PostUp" not in config


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
