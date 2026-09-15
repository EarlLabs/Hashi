"""A friend may ask a node for the internet, and for nothing that node sits in.

WHAT: the routing rules a proxy renders about WHERE a friend's connection may be opened
      to — on a leaf as much as on an entry since M23's tenth round — and the two things
      they deliberately leave reachable.
WHY:  M23's fifth walk measured the same hole on the other kind of data plane — a friend
      on the owner's real leaf opened TCP to ``10.90.0.1``, the Russian entry node's
      address on the hop, and was answered by its SSH daemon. The ninth round closed that
      direction in the wg family's own firewall rules and reported the MIRROR rather than
      claiming it fixed: a friend served by an ENTRY is served by a proxy, so no FORWARD
      rule of ours is anywhere on their path. Xray dials whatever it is asked for, bound
      to the hop's near address; the leaf's peer entry authorises that source; the leaf's
      own address is then INPUT, and its sshd answers. Same exposure, different mechanism —
      this one is not netfilter at all, it is where the proxy is willing to dial.

      So the assertions here are about a VERDICT rather than about the presence of a rule.
      Xray takes the first rule that matches and the rule below the refusal matches
      everything from a friend's inbound, so a refusal written in the wrong place is a
      refusal that decides nothing — and a test asserting it was in the file would pass.
HOW:  pure renders, parsed as JSON, over the transports that TERMINATE a connection —
      derived as the M3 and M16 files derive them, so a proxy added later is covered by
      arriving. Every address is reserved and nothing here dials anything.

      M23's TENTH round is the same two questions asked where the ninth stopped. First,
      on the OTHER kind of node: a friend on a leaf gets ``Egress.LOCAL``, whose config
      carried no routing at all, and a leaf's neighbourhood is the wider one — the entry
      across the hop, the provider's LAN, the metadata service, its own loopback. Second,
      the residual the ninth round wrote into its own template: the rule matches an
      ADDRESS, and at Xray's default a friend who asks for a NAME never has one compared,
      so any wildcard DNS service turned every refused address back into a reachable one.
      Both are verdicts here too, and ``where_a_friend_lands`` now models the step that
      decides the second: WHETHER the rules ever see an address at all.

What this does NOT prove is that a packet stops at a real node. That is a field
observation on the owner's two hosts, and it is M23's own acceptance walk. Nor can it say
what a real resolver would answer for a real name: the answer is supplied to the
evaluator below, because this zone renders text and asks no question of any network.
"""

import dataclasses
import ipaddress
import json

import pytest

from edge.bootstrap.node_stack import DATA_PLANES
from edge.checker import validate, xray_binary
from edge.egress import NOT_THE_INTERNET, Egress
from edge.registry import ConfigFormat, discover, profile

# The transports whose data plane terminates a connection and opens a new one. Derived as
# the M3 and M16 files derive it — what decides whether "where may this dial" is even a
# question is the data plane, not the protocol.
PROXIES = sorted(
    name
    for name, meta in discover().items()
    if not DATA_PLANES[meta.config_format].interface_from_config_filename
)

# The hop's near end on an entry node, as in the M3 and M16 files. RFC 1918.
HOP_ADDRESS = "10.44.0.1"

# The address the mirror reaches: the LEAF's end of the hop that carries the owner's real
# traffic. The fifth walk dialled the entry's end of it from the other side; from the
# entry, the same tunnel points here. RFC 1918, so nothing on the open internet reaches
# it — which is the whole of the finding.
THE_LEAF_ON_THE_HOP = "10.90.0.2"

# And the other end of that same tunnel: the RUSSIAN ENTRY, which is what a friend served
# by the LEAF's own proxy reaches across it. The exact address the fifth walk opened TCP
# to on the owner's real leaf and was answered by an SSH daemon — the one node in this
# fleet that is inside Russia, reachable from thirty to fifty friends' devices and from
# nothing else on the internet.
THE_ENTRY_ON_THE_HOP = "10.90.0.1"

# A name, and what a resolver answers for it. Two pieces because the thing under test is
# whether the rules are ever shown the second: at Xray's default they compare the first
# against a list of networks, which nothing about a name can ever be in.
#
# ``.example`` is RFC 2606's reserved TLD, so this resolves nowhere and belongs to nobody.
# The shape it stands for is a wildcard DNS service — ``10.90.0.1.nip.io`` and its like —
# where the name IS the address and anybody can mint one for any address they please.
A_NAME = "the-entry-on-the-hop.example"

# A destination that stands for "the internet", and the one thing a friend's tunnel is
# for. It cannot be an RFC 5737 documentation address like most fixtures in this zone:
# those ranges are exactly what is refused below, so a connection to one would prove the
# opposite of what it was asked. The deprecated 6to4 relay anycast block — reserved, so
# it is nobody's host, and globally routable, so the rules must carry it. The same value
# the wg family's own file uses, written out again rather than imported: pytest runs with
# ``--import-mode=importlib`` and this zone's test modules do not import each other.
SOMEWHERE_ON_THE_INTERNET = "192.88.99.10"

# Xray's outbound that opens nothing. Named once so the assertions below read as "the
# connection reached nothing" rather than as a protocol string repeated nine times.
REACHES_NOTHING = "blackhole"

# The tag the friend-facing inbound carries, and the tag the node's own resolver's queries
# carry. Both are the template's, and the whole carve-out is the difference between them.
A_FRIEND = "in"
THE_NODES_OWN_LOOKUP = "lookup"


def rendered(name: str, node, request, **policy) -> str:
    """One transport's server config for ``node`` under one exit policy."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    return transport.profile.render_server(
        node, validated, fixture(name, "credentials"), **policy
    )


def hop_config(name: str, node, request) -> dict:
    """The config an entry node with a hop is sent, parsed."""
    if profile(name).meta.config_format is not ConfigFormat.XRAY_JSON:
        pytest.skip(f"{name} renders a format these assertions cannot read")
    return json.loads(
        rendered(name, node, request, egress=Egress.HOP, exit_via=HOP_ADDRESS)
    )


def leaf_config(name: str, node, request) -> dict:
    """The config a node with NO hop is sent, parsed.

    Every leaf, and every single-box deployment. Its friends get ``Egress.LOCAL``: no
    ``sendThrough``, no resolver of the node's own, and until M23's tenth round no routing
    section at all — so the source of an outgoing connection was the node's own route and
    its DESTINATION was anything the node could reach. Which on a leaf includes the entry
    at the far end of the hop, and that entry is in Russia.
    """
    if profile(name).meta.config_format is not ConfigFormat.XRAY_JSON:
        pytest.skip(f"{name} renders a format these assertions cannot read")
    return json.loads(rendered(name, node, request, egress=Egress.LOCAL))


# The two seats a friend can be sat in, and the reason the claims below are parametrised
# over both instead of written once and mirrored by hand. The ninth round wrote them for
# the entry alone, and the leaf — the wider exposure of the two — went unasserted for a
# round because nothing named it. A seat added later is covered by arriving.
SEATS = {"an entry node with a hop": hop_config, "a leaf with no hop": leaf_config}


def where_a_friend_lands(
    config: dict, *, arriving_on: str, destined_for: str, resolves_to: str | None = None
) -> dict:
    """The outbound Xray hands one connection to, evaluated the way Xray evaluates it.

    Built rather than looked for, because ORDER is the finding here just as it was in the
    kernel tunnels' chain: rules are read top to bottom and the FIRST one whose every
    condition matches decides. A refusal written after the rule that carries a friend is
    a refusal that never runs, and asserting it is in the file would not notice.

    Two conditions, which are the only two the rendered rules carry: the inbound's tag,
    and whether the destination falls in one of the rule's networks. An ABSENT condition
    is unconstrained and not unsatisfiable — a rule with no ``inboundTag`` decides every
    connection, not none — and getting that backwards is what makes an instrument blind to
    the mutation that matters: a refusal that stopped naming the friend's inbound would go
    on refusing them while quietly refusing the node's own lookups too, and an evaluator
    that skipped the rule would report both as fine.

    ``destined_for`` may be a NAME, and then ``resolves_to`` is what a resolver would
    answer for it — supplied rather than looked up, because this zone asks nothing of any
    network. WHETHER THAT ANSWER IS EVER COMPARED is the second thing under test, and it
    is ``routing.domainStrategy`` that decides it. All three of Xray's values are modelled
    because the difference between them is the whole of M23's tenth round, measured
    against the pinned binary rather than read off a page:

    * ``AsIs``, the default the ninth round left in place: a name is never resolved, so it
      is in none of the refusal's networks and walks past it.
    * ``IpIfNonMatch``: resolve only if the whole pass matched nothing. Here the rule
      below the refusal matches this inbound with no condition on the destination, so
      nothing is ever left unmatched and this is a NO-OP — the reason it is not what the
      template asks for.
    * ``IpOnDemand``: resolve as soon as a rule carrying addresses is read, which is the
      first rule. The answer is compared and the refusal decides.

    The second pass ``IpIfNonMatch`` asks for is written out and is UNREACHABLE for every
    config this project renders — and it is kept precisely because that is the finding,
    not in spite of it. Deleting it and treating ``IpIfNonMatch`` as ``AsIs`` would make
    the claim "the lesser value would not have closed it" a property of this function
    rather than of the rules: with the catch-all gone from a future template, this
    evaluator would then go on reporting a hole that had been closed. Left in, the rules
    decide, exactly as they do in the daemon.

    With no rule matching, Xray uses the first outbound. Modelled rather than asserted
    against, because that default is what the file leans on for anything unmatched.
    """
    strategy = config["routing"].get("domainStrategy", "AsIs")
    outbounds = {outbound["tag"]: outbound for outbound in config["outbounds"]}

    def pass_over(
        destination: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
    ) -> dict | None:
        for rule in config["routing"]["rules"]:
            tags = rule.get("inboundTag")
            if tags is not None and arriving_on not in tags:
                continue
            networks = rule.get("ip")
            if networks is not None and (
                destination is None
                or not any(
                    destination in ipaddress.ip_network(network) for network in networks
                )
            ):
                continue
            return outbounds[rule["outboundTag"]]
        return None

    try:
        known = ipaddress.ip_address(destined_for)
    except ValueError:
        known = None

    if known is None and strategy == "IpOnDemand":
        known = ipaddress.ip_address(resolves_to) if resolves_to else None
    landed = pass_over(known)
    if landed is None and known is None and strategy == "IpIfNonMatch" and resolves_to:
        landed = pass_over(ipaddress.ip_address(resolves_to))
    return landed if landed is not None else config["outbounds"][0]


# --- the fixture every question below leans on -------------------------------------

def test_the_destinations_this_file_uses_are_what_it_says_they_are() -> None:
    """If these drifted, every assertion below would be asking the opposite question."""
    assert ipaddress.ip_address(SOMEWHERE_ON_THE_INTERNET).is_global
    assert not ipaddress.ip_address(THE_LEAF_ON_THE_HOP).is_global


# --- M23, round 9's mirror: what a friend may ask this node to dial ------------------

@pytest.mark.parametrize("name", PROXIES)
def test_a_friend_cannot_ask_this_node_to_dial_the_leaf_on_the_hop(
    name: str, node, request
) -> None:
    """The walk's ``nc 10.90.0.1 22``, asked from the entry's side instead of the leaf's.

    Nothing of this node's forwards that packet, so the verdict comes from the proxy's own
    routing rather than from any chain: the friend's connection reaches an outbound that
    opens nothing, instead of one bound to the hop.
    """
    landed = where_a_friend_lands(
        hop_config(name, node, request),
        arriving_on=A_FRIEND,
        destined_for=THE_LEAF_ON_THE_HOP,
    )

    assert landed["protocol"] == REACHES_NOTHING, landed


@pytest.mark.parametrize("destination", NOT_THE_INTERNET)
@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_nothing_off_the_internet_can_be_dialled_for_a_friend(
    name: str, seat: str, destination: str, node, request
) -> None:
    """The whole class, not only the address the walk happened to reach.

    A node is attached to more than its hop: its provider's LAN, its metadata service on
    ``169.254.169.254``, every service it runs on its own loopback. Each range is asked
    for a verdict rather than checked for a rule, and asked of BOTH seats — a leaf is a
    node too, and the one the fifth walk was actually standing on.
    """
    landed = where_a_friend_lands(
        SEATS[seat](name, node, request),
        arriving_on=A_FRIEND,
        destined_for=str(ipaddress.ip_network(destination)[1]),
    )

    assert landed["protocol"] == REACHES_NOTHING, landed


@pytest.mark.parametrize("name", PROXIES)
def test_a_friend_still_reaches_the_internet_through_the_hop(
    name: str, node, request
) -> None:
    """The control, and the reason the refusals above are not simply an outage.

    A friend's traffic is here to reach the internet. If this failed, every assertion
    above would be satisfied by a config that carries nothing at all.
    """
    landed = where_a_friend_lands(
        hop_config(name, node, request),
        arriving_on=A_FRIEND,
        destined_for=SOMEWHERE_ON_THE_INTERNET,
    )

    assert landed["sendThrough"] == HOP_ADDRESS, landed
    assert landed["protocol"] != REACHES_NOTHING, landed


@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_the_refusal_is_read_before_the_rule_that_carries_a_friend(
    name: str, seat: str, node, request
) -> None:
    """Order, which is the whole of the finding and not a detail of the file.

    Xray takes the first rule whose conditions all match, and the rule that sends a
    friend's inbound into the hop carries no destination at all — so it matches every
    connection from that inbound, including the ones the refusal exists for. Written
    after it, the refusal would be unreachable, and a test that looked for the rule
    rather than for the verdict would pass.
    """
    rules = SEATS[seat](name, node, request)["routing"]["rules"]
    friends = [
        index for index, rule in enumerate(rules) if A_FRIEND in rule.get("inboundTag", ())
    ]
    assert friends, "no rule names the friend-facing inbound at all"

    first = rules[friends[0]]
    assert first.get("ip"), (
        "the first rule that decides a friend's connection carries no destination, so it "
        f"matches all of them and nothing below it is ever read: {first}"
    )


@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_what_is_refused_is_dropped_and_never_answered(
    name: str, seat: str, node, request
) -> None:
    """DROP and not REJECT, said in the other tool's vocabulary.

    Xray's blackhole can be told to write an HTTP 403 back instead of closing, and that
    would be an answer — which is a signal, and a signal is how one friend's device
    enumerates what a node is attached to or a scan maps the fleet. The kernel rules made
    the same choice in the same words; this is that choice where a proxy makes it, written
    out rather than left to the upstream default.
    """
    config = SEATS[seat](name, node, request)
    refusals = [
        outbound
        for outbound in config["outbounds"]
        if outbound["protocol"] == REACHES_NOTHING
    ]
    assert refusals, "nothing in this config refuses anything"
    for refusal in refusals:
        assert refusal["settings"]["response"]["type"] == "none", refusal


# --- M23, round 10: the same question from the other seat -----------------------------

@pytest.mark.parametrize("name", PROXIES)
def test_a_friend_on_a_leaf_cannot_dial_the_entry_across_the_hop(
    name: str, node, request
) -> None:
    """The fifth walk's own measurement, on the node it was made from.

    ``nc 10.90.0.1 22`` from a friend's tunnel on the owner's real leaf, answered by the
    Russian entry's SSH daemon. The ninth round closed it for a friend on a wg-family
    tunnel and for a friend on an entry's proxy, and left this one: a leaf's OWN proxy,
    which renders no ``sendThrough`` and had no routing section at all, so it dialled
    whatever it was handed from whatever route the node had — and one of a leaf's routes
    is the hop.
    """
    landed = where_a_friend_lands(
        leaf_config(name, node, request),
        arriving_on=A_FRIEND,
        destined_for=THE_ENTRY_ON_THE_HOP,
    )

    assert landed["protocol"] == REACHES_NOTHING, landed


@pytest.mark.parametrize("name", PROXIES)
def test_a_friend_on_a_leaf_still_reaches_the_internet_by_the_nodes_own_route(
    name: str, node, request
) -> None:
    """The control for the leaf, and the claim M3 makes about every node without a hop.

    A leaf IS the exit. If this failed, the refusals above would be satisfied by a config
    that takes a friend's internet away instead of taking the node's neighbourhood away —
    and the two are told apart only here. ``sendThrough`` must be absent rather than
    anything in particular: the way out of a node with no hop is its own route.
    """
    landed = where_a_friend_lands(
        leaf_config(name, node, request),
        arriving_on=A_FRIEND,
        destined_for=SOMEWHERE_ON_THE_INTERNET,
    )

    assert landed["protocol"] != REACHES_NOTHING, landed
    assert "sendThrough" not in landed, landed


# --- M23, round 10: and the same question asked with a NAME ---------------------------

@pytest.mark.parametrize("destination", NOT_THE_INTERNET)
@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_a_name_that_resolves_off_the_internet_is_refused_too(
    name: str, seat: str, destination: str, node, request
) -> None:
    """The residual the ninth round wrote into its own template, closed.

    Measured against the pinned Xray before it was written: a friend asking for the
    ADDRESS ``127.0.0.1`` was refused, and the same friend asking for the NAME
    ``localhost`` was answered. A rule that compares addresses decides nothing about a
    destination that is still a name when it is read, and a wildcard DNS service turns
    any address into a name for nothing — so every range above had a way round it.
    """
    landed = where_a_friend_lands(
        SEATS[seat](name, node, request),
        arriving_on=A_FRIEND,
        destined_for=A_NAME,
        resolves_to=str(ipaddress.ip_network(destination)[1]),
    )

    assert landed["protocol"] == REACHES_NOTHING, landed


@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_a_name_on_the_internet_is_still_carried(
    name: str, seat: str, node, request
) -> None:
    """The control for the rule above: resolving destinations must not cost a friend the
    web. Almost everything a friend asks for is a name, so a strategy that refused them
    all would be an outage rather than a policy — and every assertion about a refusal
    would pass."""
    landed = where_a_friend_lands(
        SEATS[seat](name, node, request),
        arriving_on=A_FRIEND,
        destined_for=A_NAME,
        resolves_to=SOMEWHERE_ON_THE_INTERNET,
    )

    assert landed["protocol"] != REACHES_NOTHING, landed


@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_neither_lesser_strategy_would_have_closed_it(
    name: str, seat: str, node, request
) -> None:
    """Why the value is ``IpOnDemand`` and not one of the two cheaper answers.

    The config is rendered and then the ONE key is changed, so the comparison is between
    this file's rules under three strategies and nothing else. At ``AsIs`` — the default,
    and what these configs carried for a round — the name walks past the refusal. At
    ``IpIfNonMatch`` it walks past it too, and that is the surprising one: it resolves only
    when a whole pass matched nothing, and the rule below the refusal matches this inbound
    unconditionally, so there is never a non-match to trigger it. Both were measured
    against the pinned binary; without this test the first person to "simplify" the value
    would find the suite still green.
    """
    for lesser in ("AsIs", "IpIfNonMatch"):
        config = SEATS[seat](name, node, request)
        config["routing"]["domainStrategy"] = lesser
        landed = where_a_friend_lands(
            config,
            arriving_on=A_FRIEND,
            destined_for=A_NAME,
            resolves_to=THE_ENTRY_ON_THE_HOP,
        )
        assert landed["protocol"] != REACHES_NOTHING, (
            f"{lesser} refused the name, so this test no longer shows why the rendered "
            f"value has to be IpOnDemand: {landed}"
        )


@pytest.mark.parametrize("name", PROXIES)
def test_even_the_outbound_that_dials_nothing_is_bound_to_the_hop(
    name: str, node, request
) -> None:
    """M3's invariant kept in the strong form rather than in the form with an exception.

    The claim this project asserts about an entry node is that NO outbound in its config
    could leave by the node's own route. A blackhole cannot leave by any route, so it
    would be safe without this — but the invariant is then one that has to be read with a
    case in it, and the next outbound somebody adds is checked against the weaker version.
    ``sendThrough`` costs nothing here and keeps the sentence absolute.
    """
    for outbound in hop_config(name, node, request)["outbounds"]:
        assert outbound.get("sendThrough") == HOP_ADDRESS, outbound


# --- and what the refusal must NOT take with it -------------------------------------

@pytest.mark.parametrize("name", PROXIES)
def test_the_nodes_own_lookup_is_not_refused_even_to_a_private_resolver(
    name: str, node, request
) -> None:
    """M16, which a rule one notch wider would have taken away in silence.

    ``resolver_problem`` deliberately allows a node record to name a PRIVATE resolver: the
    query is source-routed into the hop whatever its destination, so a resolver inside the
    far end's own network is reached through the hop like anything else. That address is
    in the ranges refused above, and the refusal names the FRIEND's inbound — so what
    tells the two apart is whose connection it is, not where it is going.

    Scoped that way rather than by an address and a port, which is what the kernel tunnels
    had to use: there the resolver is named in a friend's own config file and the packet
    is the friend's own, so only a destination could carve it out. Here the node's lookup
    is a different inbound, so the carve-out can be about the asker — and an exception
    that names no address can never become a hole for one.
    """
    on_this_side = dataclasses.replace(node, resolver=THE_LEAF_ON_THE_HOP)
    config = json.loads(
        rendered(name, on_this_side, request, egress=Egress.HOP, exit_via=HOP_ADDRESS)
    )
    assert not ipaddress.ip_address(config["dns"]["servers"][0]).is_global, (
        "this test's resolver is on the internet, so nothing would refuse it and this "
        "would pass without the carve-out it is about"
    )

    landed = where_a_friend_lands(
        config,
        arriving_on=config["dns"]["tag"],
        destined_for=config["dns"]["servers"][0],
    )

    assert landed["sendThrough"] == HOP_ADDRESS, landed
    assert landed["protocol"] != REACHES_NOTHING, landed


@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_the_refused_destinations_are_the_one_list_this_project_keeps(
    name: str, seat: str, node, request
) -> None:
    """One copy, shared with the data plane that expresses it as firewall rules.

    A second list is how the two answers drift: the ranges are IANA's, and
    ``tests/edge/test_a_tunnel_carries_traffic_off_the_node.py`` holds that one copy
    against the standard library's own registry in both directions. A copy here would be
    outside everything that checks it.
    """
    rules = SEATS[seat](name, node, request)["routing"]["rules"]
    refused = [rule["ip"] for rule in rules if rule.get("ip")]
    assert refused, "no rule carries a destination at all"
    for destinations in refused:
        assert tuple(destinations) == NOT_THE_INTERNET, destinations


@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("name", PROXIES)
def test_the_refusal_records_nothing_about_what_it_refused(
    name: str, seat: str, node, request
) -> None:
    """The charter's one absolute rule, at the place a refusal invites breaking it.

    A rule that drops is exactly where somebody reaches for a log line to find out what
    it dropped, and a destination is the one record this project must never create. Both
    seats, and ``dnsLog`` on both: since the tenth round a leaf resolves a friend's names
    too — through its own host's resolver, where they have always gone — so the key that
    would write them down is one every config this project renders must answer for.
    """
    config = SEATS[seat](name, node, request)
    assert config["log"]["access"] == "none"
    assert config["log"]["dnsLog"] is False
    assert "log" not in json.dumps(config["routing"]).lower()


# --- and the daemon takes it --------------------------------------------------------

@pytest.mark.parametrize(
    "policy",
    [
        pytest.param({"egress": Egress.HOP, "exit_via": HOP_ADDRESS}, id="an entry with a hop"),
        pytest.param({"egress": Egress.LOCAL}, id="a leaf with no hop"),
    ],
)
@pytest.mark.parametrize("name", PROXIES)
def test_the_pinned_xray_accepts_a_config_that_refuses(
    name: str, policy: dict, node, request, tmp_path
) -> None:
    """The upstream checker over the config with the refusal in it.

    Necessary and not sufficient, like every use of the checker in this zone: Xray accepts
    keys it does not know and ignores them, so "it loads" says the file parses and says
    nothing about where a connection goes. What the assertions above are for.

    Both seats, and the leaf is the one worth the second run: it is the config that now
    carries a ``routing`` section with a ``domainStrategy`` and NO ``dns`` object beside
    it, which is the one combination nothing had ever handed the daemon.
    """
    if xray_binary() is None:
        pytest.skip(
            "xray not present — that the daemon accepts the config refusing a node's own "
            "neighbourhood is NOT proven by this run. Install it: "
            "scripts/fetch-upstream-checkers.sh"
        )
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    materialise = request.getfixturevalue("checkable_params_for")
    validated = transport.validate(materialise(fixture(name, "params"), tmp_path))
    config = transport.profile.render_server(
        node, validated, fixture(name, "credentials"), **policy
    )

    result = validate(config, config_format=transport.meta.config_format)
    assert result.ok, f"{name}: xray rejected the config with the refusal\n{result.output}"
