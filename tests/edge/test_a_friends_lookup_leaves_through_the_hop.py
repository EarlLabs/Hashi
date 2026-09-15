"""A friend's lookups leave through the hop, like their traffic — M16.

WHAT: what an entry node's friend-facing proxy renders about name resolution once that
      node has a hop, and what every node without one goes on rendering: nothing at all.
WHY:  M3 moved the exit abroad and left the lookup behind. ``sendThrough`` binds the
      connection, not the resolution that comes before it, so every destination a friend
      asked for was still resolved by the entry host's own resolver — inside the network
      the hop exists to leave — while the exit address looked exactly right. As invisible
      as M3's own failure: pages load, the exit is abroad, and the list of names never
      left home.

      So each of the three settings that move the lookup is asserted on its own. A config
      carrying the resolver but not the outbound's ``domainStrategy`` never consults the
      resolver at all, and would pass a test that only looked for a ``dns`` block.
HOW:  pure renders, parsed as JSON, over the proxies — the transports that terminate a
      connection, derived exactly as the M3 file derives them — plus one pass through the
      pinned Xray's own checker. Every address is from a documentation range.

What this does NOT prove is where the query actually leaves the entry host. The checker
proves the file loads and this file proves what it asks for; watching the lookup leave
through the tunnel is M16.2's scenario, and on the two real hosts it is the milestone's
acceptance walk.
"""

import dataclasses
import ipaddress
import json

import pytest

from edge.bootstrap.node_stack import DATA_PLANES
from edge.checker import validate, xray_binary
from edge.egress import (
    NO_RESOLVER,
    Egress,
    EgressNotRenderable,
    ResolverMissing,
    lookup_resolver,
    resolver_problem,
)
from edge.registry import ConfigFormat, discover, profile

# The transports whose data plane terminates a connection and opens a new one — the only
# kind that resolves a friend's destination itself. Derived as the M3 file derives it, so
# a proxy added later is held to this by arriving.
PROXIES = sorted(
    name
    for name, meta in discover().items()
    if not DATA_PLANES[meta.config_format].interface_from_config_filename
)

INSTALLED = sorted(discover())

# The hop's near end on an entry node, as in the M3 file. RFC 1918.
HOP_ADDRESS = "10.44.0.1"

# A resolver that is ON THE INTERNET, which every other address in this zone's fixtures
# deliberately is not: the documentation ranges (RFC 5737) the rulebook mandates are all
# addresses a friend's tunnel now drops, so a test that wanted "a resolver needing no
# exception" could not use one. This is the deprecated 6to4 relay anycast block — still
# reserved, so it is nobody's host, and still globally routable, so the rules carry it
# without an exception. The test below asserts that rather than trusting this comment.
A_RESOLVER_ON_THE_INTERNET = "192.88.99.53"


def rendered(name: str, node, request, **policy) -> str:
    """One transport's server config for ``node`` under one exit policy."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    return transport.profile.render_server(
        node, validated, fixture(name, "credentials"), **policy
    )


def hop_config(name: str, node, request) -> dict:
    """The config an entry node with a hop is sent, parsed.

    Parsed rather than matched as text: the assertions below are about what a key says
    and what refers to what, which a substring search cannot follow.
    """
    if profile(name).meta.config_format is not ConfigFormat.XRAY_JSON:
        pytest.skip(f"{name} renders a format these assertions cannot read")
    return json.loads(
        rendered(name, node, request, egress=Egress.HOP, exit_via=HOP_ADDRESS)
    )


# --- the three settings, each on its own -------------------------------------------

@pytest.mark.parametrize("name", PROXIES)
def test_the_lookup_is_asked_of_the_resolver_on_the_nodes_record(
    name: str, node, request
) -> None:
    """The address comes from the node, and from nowhere else — never a default."""
    assert hop_config(name, node, request)["dns"]["servers"] == [node.resolver]


# Xray's outbound that opens no connection at all. Since M23's ninth round a config with
# a hop carries one, to refuse the destinations a friend's traffic may not reach — see
# ``tests/edge/test_a_proxy_dials_the_internet_and_not_its_own_neighbourhood.py``. It is
# named here because the assertion below is about outbounds that RESOLVE a name, and this
# one resolves nothing because it dials nothing.
REACHES_NOTHING = "blackhole"


@pytest.mark.parametrize("name", PROXIES)
def test_the_outbound_resolves_through_it_rather_than_through_the_host(
    name: str, node, request
) -> None:
    """The setting that makes the ``dns`` object matter at all.

    Without it the outbound is ``AsIs``: it hands the NAME to the host's resolver and the
    ``dns`` object is never consulted — which is the config M3 shipped, with a resolver
    pasted on top. Checked on every outbound that opens one, because the one without it is
    the one a friend's names leak through.

    The blackhole is excluded and its exclusion is asserted rather than skipped past: it
    dials nothing, so a resolution strategy on it would be a key that reads as a decision
    and decides nothing. Written as a partition so a THIRD kind of outbound arriving is
    held to the strategy rather than quietly waved through.
    """
    for outbound in hop_config(name, node, request)["outbounds"]:
        if outbound["protocol"] == REACHES_NOTHING:
            assert "domainStrategy" not in outbound.get("settings", {}), outbound
            continue
        assert outbound.get("settings", {}).get("domainStrategy") == "UseIPv4", outbound


@pytest.mark.parametrize("name", PROXIES)
def test_the_lookup_itself_leaves_by_the_hop_outbound(name: str, node, request) -> None:
    """The resolver's own queries are routed, by tag, to an outbound bound to the hop.

    Asserted as a chain of references rather than as the presence of a rule: the queries
    carry a tag, some rule names that tag, and every outbound such a rule names is bound
    to the hop's address. Break any link and the query goes out by whatever the default
    is — right today only because the hop outbound happens to be the only one.
    """
    config = hop_config(name, node, request)
    tag = config["dns"].get("tag")
    assert tag, "the resolver's queries carry no tag, so no rule can say where they go"

    carriers = [
        rule["outboundTag"]
        for rule in config["routing"]["rules"]
        if tag in rule.get("inboundTag", ())
    ]
    assert carriers, "no rule routes the resolver's queries; they take the default way out"
    outbounds = {outbound["tag"]: outbound for outbound in config["outbounds"]}
    for carrier in carriers:
        assert outbounds[carrier].get("sendThrough") == HOP_ADDRESS, outbounds[carrier]


@pytest.mark.parametrize("name", PROXIES)
def test_only_ipv4_is_asked_for_because_only_ipv4_crosses_the_hop(
    name: str, node, request
) -> None:
    """Held here because the pinned Xray will not hold it.

    Xray accepts any string for ``queryStrategy`` and quietly asks for both record types
    when it does not recognise one — so a misspelling passes the upstream checker and
    sends a query for an address the hop cannot carry. This assertion is the only thing
    that notices.
    """
    assert hop_config(name, node, request)["dns"]["queryStrategy"] == "UseIPv4"


@pytest.mark.parametrize("name", PROXIES)
def test_no_name_looked_up_is_written_down_or_labelled_with_its_asker(
    name: str, node, request
) -> None:
    """The charter's one record, at the step where it is easiest to create.

    ``dnsLog`` is written out as ``false`` rather than left to the upstream default: a
    default is a promise about somebody else's code, and this one turning over would put
    every name looked up into the container log. ``clientIp`` would attach the asker's
    network to each query; it must not appear anywhere in the object.
    """
    config = hop_config(name, node, request)
    assert config["log"]["dnsLog"] is False
    assert config["log"]["access"] == "none"
    assert "clientIp" not in json.dumps(config["dns"])


# --- where it does not apply --------------------------------------------------------

@pytest.mark.parametrize("name", INSTALLED)
def test_a_node_with_no_hop_renders_the_same_bytes_with_or_without_a_resolver(
    name: str, node, request
) -> None:
    """Every leaf, and every single-box deployment.

    The golden files pin these bytes from the other side; this pins that a resolver on the
    record changes none of them. There the lookup and the exit already leave one host by
    one route, so there is nothing to move.

    The NODE's config, and since M23 that qualifier is load-bearing: a friend's own
    configuration file on such a node DOES change with the record, because a friend's
    device has no route to its usual resolver once the tunnel routes every address. That
    is ``tests/edge/test_a_friend_can_resolve_a_name.py``, and the two claims are about
    two different files.

    ONE EXCEPTION, added by M23's fifth round and narrower than it sounds: a friend's
    tunnel now carries only what is on the internet, so a resolver that is NOT — a
    private one, which the record is allowed to name — has to be let through by name in
    the node's own rules. A resolver on the internet needs no such rule and changes
    nothing, which is why this test uses one, and the exception itself is asserted where
    the rest of that policy is
    (``tests/edge/test_a_tunnel_carries_traffic_off_the_node.py``).
    """
    assert ipaddress.ip_address(A_RESOLVER_ON_THE_INTERNET).is_global, (
        "this test's resolver must be one the friend-facing rules carry with no "
        "exception of its own, or it proves nothing about the bytes"
    )
    on_the_internet = dataclasses.replace(node, resolver=A_RESOLVER_ON_THE_INTERNET)

    with_one = rendered(name, on_the_internet, request, egress=Egress.LOCAL)
    without = rendered(
        name, dataclasses.replace(node, resolver=None), request, egress=Egress.LOCAL
    )
    assert with_one == without
    if profile(name).meta.config_format is ConfigFormat.XRAY_JSON:
        config = json.loads(with_one)
        assert "dns" not in config
        assert "dnsLog" not in config["log"]


# --- and it fails closed ------------------------------------------------------------

@pytest.mark.parametrize("name", PROXIES)
def test_a_hop_with_no_resolver_is_refused_rather_than_answered_at_home(
    name: str, node, request
) -> None:
    """Decision 3, applied to the lookup.

    Rendering without a resolver is not neutral: it is the host's resolver — the leak
    itself, with every screen green. Refused as its own type, because it is the one
    refusal an operator fixes on the node's record, and a caller that has to tell them so
    must not have to read the message to find out which refusal it was.
    """
    with pytest.raises(ResolverMissing) as refusal:
        rendered(
            name,
            dataclasses.replace(node, resolver=None),
            request,
            egress=Egress.HOP,
            exit_via=HOP_ADDRESS,
        )
    assert str(refusal.value) == NO_RESOLVER


@pytest.mark.parametrize(
    "resolver",
    [
        # A name has to be looked up before it can be asked anything — at home.
        "dns.example.com",
        "https://dns.example.com/dns-query",
        # Xray's keyword for the host's own resolver: the leak, by name.
        "localhost",
        # Xray's form that dials the resolver directly, outside the routing rules.
        "https+local://192.0.2.53/dns-query",
        # A port is not part of an address, and nothing here would carry one.
        "192.0.2.53:53",
        # The hop carries IPv4 only. RFC 3849 documentation prefix.
        "2001:db8::53",
        # A stub on this host, which asks the host's own upstream.
        "127.0.0.53",
        "0.0.0.0",
    ],
)
def test_a_resolver_that_would_be_answered_on_this_side_is_refused(resolver: str) -> None:
    """Each of these is a file Xray would load and a lookup that never leaves home.

    Refused as the general type and NOT as ``ResolverMissing``: the node HAS a resolver,
    it is the wrong kind, and a caller telling the operator to "set one" would be wrong.
    """
    assert resolver_problem(resolver)
    with pytest.raises(EgressNotRenderable) as refusal:
        lookup_resolver(Egress.HOP, resolver)
    assert not isinstance(refusal.value, ResolverMissing)


def test_a_resolver_is_asked_for_only_where_there_is_a_hop() -> None:
    """The policy, stated once, without a transport."""
    assert lookup_resolver(Egress.HOP, "192.0.2.53") == "192.0.2.53"
    # A resolver inside the far end's own network is reached through the hop like any
    # other, so a private address is an answer, not a mistake.
    assert lookup_resolver(Egress.HOP, "10.20.0.2") == "10.20.0.2"
    # With no hop nothing is asked — and nothing is checked: a leaf never fails to render
    # over a field it does not use.
    assert lookup_resolver(Egress.LOCAL, "192.0.2.53") is None
    assert lookup_resolver(Egress.LOCAL, "localhost") is None
    assert lookup_resolver(Egress.NONE, None) is None
    for missing in (None, "", "   "):
        with pytest.raises(ResolverMissing, match="names no resolver"):
            lookup_resolver(Egress.HOP, missing)


# --- and the daemon takes it --------------------------------------------------------

@pytest.mark.parametrize("name", PROXIES)
def test_the_pinned_xray_accepts_a_hop_config_with_its_resolver(
    name: str, node, request, tmp_path
) -> None:
    """The upstream checker, over the config a node with a hop is actually sent.

    Necessary and not sufficient, which is why the assertions above exist: the pinned
    Xray refuses an unknown outbound ``domainStrategy`` but accepts an unknown
    ``queryStrategy`` and ignores keys it does not know — so "it loads" proves the file
    loads, not that the lookup goes where this file says.
    """
    if xray_binary() is None:
        pytest.skip(
            "xray not present — that the daemon accepts an entry node's config with its "
            "resolver is NOT proven by this run. Install it: "
            "scripts/fetch-upstream-checkers.sh"
        )
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    materialise = request.getfixturevalue("checkable_params_for")
    validated = transport.validate(materialise(fixture(name, "params"), tmp_path))
    config = transport.profile.render_server(
        node,
        validated,
        fixture(name, "credentials"),
        egress=Egress.HOP,
        exit_via=HOP_ADDRESS,
    )

    result = validate(config, config_format=transport.meta.config_format)
    assert result.ok, f"{name}: xray rejected the entry node's config\n{result.output}"
