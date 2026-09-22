"""Where a user's IPv6 goes, now that their names resolve — M23.

WHAT: the ``AllowedIPs`` a user's configuration file gives their device, the peer entry
      the node authorises them with, and the resolver the same file may name.
WHY:  M23 fixed a user's DNS and unmasked this. The owner's leaf, measured on
      2026-09-14:

          $ ip -6 addr show scope global   (nothing)
          $ ip -6 route show default       (nothing)
          $ ping6 <a public resolver>      connect: Network is unreachable

      So the node has no IPv6 exit, and nothing this project renders could give it one —
      ``wg_quick_egress`` refuses a v6 tunnel and the forwarding rules are ``iptables``.
      A user's file nevertheless routes every IPv6 address into the tunnel, where the
      node discards it. While nothing resolved, no device ever asked for an IPv6 address;
      now that names resolve, a device that gets a AAAA answer tries it first and waits.

      That cost is real and this file does not pretend otherwise. What it pins is that
      the two ways of removing the cost stay closed. NARROWING the route is the one that
      looks like a performance fix and is the leak: IPv6 would leave by the user's own
      connection, from their own address, to every destination that has an IPv6 one.
      WIDENING the node's peer entry is the other, and it hands one user the right to
      send us traffic sourced as anybody — which is also, incidentally, why a rejection
      at the node cannot be built: with the entry narrow, the node's own WireGuard
      discards the packet before any rule of ours is reached, so there is nothing for a
      filter chain to answer.
HOW:  pure renders over the family DERIVED from what a transport declares — the set that
      serialises a user's material into a config FILE — and every address is from a
      documentation range.

What this does NOT prove is what a user's device does with the file. Whether a given
client routes IPv6 into a tunnel that has no IPv6 address of its own, or quietly keeps
using its own connection for it, is a field observation with that client on a network
that has IPv6 — and no assertion here stands in for it.
"""

import ipaddress

import pytest
from pydantic import ValidationError

from edge.egress import Egress, EgressNotRenderable, client_resolver_problem
from edge.registry import SubscriptionFormat, discover, profile

# Derived the way the rest of this suite derives it: the transports that hand a user a
# whole file. Never a hardcoded transport name.
CONFIG_FILE_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
)

DIRECTIVE = "AllowedIPs = "

# RFC 3849 documentation prefix, standing in for the resolver an operator most plausibly
# pastes in: a public one, in the family their own machine happens to print first.
A_RESOLVER_THE_TUNNEL_CANNOT_CARRY = "2001:db8::53"

# The two halves the file has to say in words, pinned as the words themselves. A user
# who reads only "everything goes through the tunnel" has been told the opposite of what
# happens to half of it — the mistake M23 already found once in this same file — and the
# operator reading it needs the second half, because narrowing the line is the leak rather
# than the optimisation it looks like.
SAYS_WHAT_IS_DROPPED = "IPv6 sent into this tunnel is dropped"
SAYS_WHAT_NARROWING_COSTS = "showing a real address"


def rendered_client(name: str, node, request, **params_overrides) -> str:
    """One user's configuration file, for the first fixture credential."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    params = transport.validate({**fixture(name, "params"), **params_overrides})
    return transport.profile.render_client_config(
        node, params, fixture(name, "credentials")[0]
    ).content


def rendered_client_from_stored(name: str, node, request, **stored) -> str:
    """The same file, from a row whose parameters were STORED before a rule existed.

    The override is applied after validation rather than through it, and that is the only
    way to reach the renderer's own refusal now that the transport's model refuses the
    same value: a fleet that stored one before the model did still holds it, and the
    renderer is what meets it. Validating the override instead would test the validator
    twice and the renderer not at all.
    """
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    params = {**transport.validate(fixture(name, "params")), **stored}
    return transport.profile.render_client_config(
        node, params, fixture(name, "credentials")[0]
    ).content


def rendered_server(name: str, node, request, egress: Egress) -> str:
    """The node's own config for the same transport, under one egress policy."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    clients = fixture(name, "credentials")
    return transport.profile.render_server(node, validated, clients, egress=egress)


def allowed_ips(config: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Every range any ``AllowedIPs`` line in a rendered config names, parsed.

    Parsed rather than compared as text, because the property is about which addresses
    are covered and a string comparison would pass against ``::/1`` — half the family,
    rendered as a line that reads like the whole of it.
    """
    return [
        ipaddress.ip_network(entry.strip())
        for line in config.splitlines()
        if line.startswith(DIRECTIVE)
        for entry in line[len(DIRECTIVE) :].split(",")
    ]


def prose(config: str) -> str:
    """Every comment in the file as one line of running text.

    The templates wrap at eighty-odd columns, so a sentence a user reads as one
    sentence is several lines in the bytes — the same helper, and the same reason, as
    tests/edge/test_a_user_can_resolve_a_name.py. It is copied rather than imported
    because pytest runs with ``--import-mode=importlib``, under which importing across
    test modules is not reliable (see the note on ``transport_fixture``).
    """
    return " ".join(
        line.lstrip("#").strip() for line in config.splitlines() if line.startswith("#")
    )


# --- the user's end: everything goes in, including what cannot come out -----------

@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_every_address_a_users_device_can_reach_enters_the_tunnel(
    name: str, node, request
) -> None:
    """Both families, and the second one is the assertion worth having.

    IPv4 alone would be faster for this user and would be the charter failure: their
    IPv6 traffic would leave by their own connection, showing their real address to every
    destination that has an IPv6 one, while the panel showed a green tunnel and an exit
    abroad. Asserted as coverage of the whole family rather than as the text of the line,
    so a narrowing that still reads as wide is red.
    """
    routes = allowed_ips(rendered_client(name, node, request))

    for family in (4, 6):
        assert any(route.prefixlen == 0 for route in routes if route.version == family), (
            f"a user's {name} config leaves IPv{family} outside the tunnel, so it "
            f"leaves by their own connection: {[str(route) for route in routes]}"
        )


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_file_a_user_holds_says_what_ipv6_costs_them(
    name: str, node, request
) -> None:
    """The cost is not fixable here, so the file carries it in words instead.

    M23's own lesson from this same file: a config that explains itself incorrectly is
    worse than one that says nothing. A user whose IPv6 is silently discarded reports
    "the VPN is slow"; the operator who reads the same file has to find the sentence
    saying that the obvious fix is the leak, because nothing else will tell them.
    """
    said = prose(rendered_client(name, node, request))

    assert SAYS_WHAT_IS_DROPPED in said, (
        "the file routes IPv6 into a tunnel that discards it and does not say so"
    )
    assert SAYS_WHAT_NARROWING_COSTS in said, (
        "the file does not say what taking IPv6 out of that line would cost, which is the "
        "change the next person to read it will want to make"
    )


# --- the node's end: and the reason it is discarded rather than answered -------------

@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_node_authorises_no_ipv6_from_a_user(name: str, node, request) -> None:
    """One IPv4 host route per peer, which is what discards the IPv6 — and must stay.

    ``AllowedIPs`` on the node is the authorisation list as well as the routing table, so
    this entry is what makes WireGuard itself drop a decrypted packet whose source is an
    IPv6 address. That has two consequences worth pinning together: no filter rule of
    ours can ever answer such a packet (it never reaches a chain), and the tempting way to
    make one possible — widening this entry — would let one user send us traffic sourced
    as anybody at all.

    The day a node can carry IPv6 this test changes, and the change is deliberate: it
    needs a v6 address for every user and a v6 range on the tunnel, neither of which
    exists here.
    """
    routes = allowed_ips(rendered_server(name, node, request, Egress.LOCAL))

    assert routes, "the node authorises nobody, so this proves nothing"
    for route in routes:
        assert route.version == 4 and route.prefixlen == route.max_prefixlen, (
            f"{name} authorises a peer for {route}, which is wider than that peer's own "
            "address — AllowedIPs is the authorisation list, so this peer may now send "
            "traffic sourced as anybody in it"
        )


# --- and a resolver in a family the tunnel cannot carry is no resolver at all --------

@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_resolver_a_users_device_could_never_reach_is_refused(
    name: str, node, request
) -> None:
    """The box M23 added to the panel, filled in with an address of the wrong family.

    Every query would go into the tunnel and be discarded at the node, so not one name
    would resolve — the exact failure the resolver was written for, produced by the field
    that fixes it. ``resolver_problem`` already refuses this on a node's record for the
    same reason one hop further in; this is the transport's own parameter, which nothing
    had checked against what the tunnel can carry.

    FROM A STORED ROW since M23's round 2, and the change is what the fix cost this test
    rather than a weakening of it. The value is refused when it is typed now (the test
    below), so the only way to still hold one is to have stored it before that rule
    existed — which is true of any fleet running this product today, and is exactly the
    row whose render must keep refusing.
    """
    with pytest.raises(EgressNotRenderable) as refusal:
        rendered_client_from_stored(
            name, node, request, client_dns=(A_RESOLVER_THE_TUNNEL_CANNOT_CARRY,)
        )

    assert A_RESOLVER_THE_TUNNEL_CANNOT_CARRY in str(refusal.value), (
        "the refusal does not name the value an operator has to change"
    )


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_that_resolver_is_refused_when_it_is_TYPED_and_not_when_it_is_rendered(
    name: str, request
) -> None:
    """The round-2 finding: refusing at render is refusing in the wrong place — M23.

    The refusal above fires when a USER downloads their configuration, which is a 500
    that takes away every node they hold rather than a complaint about the box the value
    was typed into. It is also the last moment anyone can act on it: by then the value is
    stored, the panel has answered 200, and the person who could fix it has left the
    screen.

    So the transport's own model asks the same question of the same value, which puts the
    refusal on every path that can store one — both panel forms and the JSON API — with
    no route knowing the field's name. A hostname in this box was always refused this way;
    an address of the wrong family was not.

    Red against the previous commit: ``validate`` accepts the value and nothing complains
    until a download.
    """
    fixture = request.getfixturevalue("transport_fixture")
    params = {
        **fixture(name, "params"),
        "client_dns": (A_RESOLVER_THE_TUNNEL_CANNOT_CARRY,),
    }

    with pytest.raises(ValidationError) as refused:
        profile(name).validate(params)

    assert "client_dns" in str(refused.value), refused.value
    assert A_RESOLVER_THE_TUNNEL_CANNOT_CARRY in str(refused.value), refused.value


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_box_and_the_renderer_refuse_it_in_one_sentence(
    name: str, node, request
) -> None:
    """One rule, one wording, and ``edge`` owns both halves of it.

    The value is unreachable because of what the TUNNEL carries, not because of anything
    either protocol does, so the sentence is written once in ``egress`` and quoted by
    whoever is asking. If a transport ever grows its own copy, this is what fails: two
    sentences for one rule is how a fix lands on one path and not the other, which is the
    shape of the finding this test was written for.
    """
    said = client_resolver_problem(A_RESOLVER_THE_TUNNEL_CANNOT_CARRY)
    assert said, "the predicate accepts a resolver the tunnel cannot carry"

    fixture = request.getfixturevalue("transport_fixture")
    with pytest.raises(ValidationError) as typed:
        profile(name).validate(
            {**fixture(name, "params"), "client_dns": (A_RESOLVER_THE_TUNNEL_CANNOT_CARRY,)}
        )
    with pytest.raises(EgressNotRenderable) as rendered:
        rendered_client_from_stored(
            name, node, request, client_dns=(A_RESOLVER_THE_TUNNEL_CANNOT_CARRY,)
        )

    assert said in str(typed.value), typed.value
    assert said in str(rendered.value), rendered.value
