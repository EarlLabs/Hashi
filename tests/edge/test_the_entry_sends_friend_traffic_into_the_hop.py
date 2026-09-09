"""A friend on an entry node must exit at the leaf — M3, the charter's core claim.

WHAT: what an entry node's friend-facing transport renders once that node has a hop, and
      — the half that matters more — what it must no longer render.
WHY:  before M3 the answer was one hardcoded outbound: the node dialled the internet
      itself, from Russia, whatever the topology said. **The failure is invisible.** The
      friend connects, pages load, the panel shows two active nodes and a live hop, and
      the protection the whole topology exists to provide is simply absent. Nothing logs
      it, and nothing should — logging who connected to what is the one record the
      charter forbids.

      So the assertions here are written the way the failure would have to be caught: not
      "the hop outbound is present" but "there is NO outbound that could leave by this
      node's own route". A config that grew a direct outbound beside the hop one would
      pass the first and is exactly the silent regression.
HOW:  pure, and parametrised over the transports that TERMINATE a connection rather than
      over a list of names — derived as the complement of M14's kernel tunnels, because
      what decides whether "where do I dial from" is even expressible is the data plane,
      not the protocol. A transport added later is covered by arriving.

What this does NOT prove is the whole of M3's first "done when": that a friend's traffic
actually emerges at the leaf's address. That is a field observation on two real hosts with
a real client, and no assertion in this file stands in for it.
"""

import json

import pytest

from edge.bootstrap.node_stack import DATA_PLANES
from edge.egress import Egress, EgressNotRenderable, exit_origin
from edge.registry import ConfigFormat, discover, profile

# The transports whose data plane terminates a connection and opens a new one, rather than
# handing packets to the kernel. Derived from the same declaration M14 derived the kernel
# tunnels from, and inverted: a tool that takes its interface name from a config file
# makes an interface, and everything else is a proxy.
PROXIES = sorted(
    name
    for name, meta in discover().items()
    if not DATA_PLANES[meta.config_format].interface_from_config_filename
)

INSTALLED = sorted(discover())

# The hop's near end, as an entry node would have it: an address on THIS node, inside the
# tunnel. RFC 1918, like every tunnel address in this zone's fixtures.
HOP_ADDRESS = "10.44.0.1"


def rendered(name: str, node, request, **policy) -> str:
    """One transport's server config under one exit policy."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    validated = transport.validate(fixture(name, "params"))
    clients = fixture(name, "credentials")
    return transport.profile.render_server(node, validated, clients, **policy)


def outbounds(config: str) -> list[dict]:
    """Every outbound in a rendered Xray config.

    Parsed rather than matched as text, because the assertion below is about what is NOT
    there and a substring search cannot say that. Keyed on the config FORMAT at the call
    site, never on a transport's name — the same dispatch ``edge/checker.py`` uses.
    """
    return json.loads(config)["outbounds"]


# --- M3.1: the traffic leaves through the hop --------------------------------------

@pytest.mark.parametrize("name", PROXIES)
def test_an_entry_with_a_hop_opens_every_connection_from_the_hop(
    name: str, node, request
) -> None:
    """Every outbound is bound to the hop's address, so none can leave by this node.

    Asserted over ALL of them rather than "the hop outbound exists": a config carrying the
    hop outbound and a direct one beside it satisfies the second and is precisely the
    invisible failure — Xray would use whichever the routing sent it to, and a friend
    would exit in Russia with every screen green.
    """
    config = rendered(name, node, request, egress=Egress.HOP, exit_via=HOP_ADDRESS)

    if profile(name).meta.config_format is not ConfigFormat.XRAY_JSON:
        pytest.skip(f"{name} renders a format this assertion cannot read")

    rendered_outbounds = outbounds(config)
    assert rendered_outbounds, "a config with no outbound at all reaches nothing"
    for outbound in rendered_outbounds:
        assert outbound.get("sendThrough") == HOP_ADDRESS, (
            f"{name} renders an outbound that leaves by the node's own route: {outbound}"
        )


@pytest.mark.parametrize("name", PROXIES)
def test_the_friend_facing_inbound_is_routed_into_the_hop(name: str, node, request) -> None:
    """A routing rule ties the inbound to the hop outbound by tag.

    Belt to the braces above: the single outbound already makes a local exit
    unreachable, and this makes the intent explicit in the file an operator may one day
    read on a node at three in the morning.
    """
    config = rendered(name, node, request, egress=Egress.HOP, exit_via=HOP_ADDRESS)

    if profile(name).meta.config_format is not ConfigFormat.XRAY_JSON:
        pytest.skip(f"{name} renders a format this assertion cannot read")

    parsed = json.loads(config)
    tags = {outbound["tag"] for outbound in parsed["outbounds"]}
    rules = parsed["routing"]["rules"]
    assert rules, "friend traffic is routed by whatever happens to be first"
    for rule in rules:
        assert rule["outboundTag"] in tags
    inbound_tags = {inbound["tag"] for inbound in parsed["inbounds"]}
    assert inbound_tags <= {tag for rule in rules for tag in rule["inboundTag"]}, (
        "an inbound no rule names is an inbound routed by default rather than into the hop"
    )


@pytest.mark.parametrize("name", PROXIES)
def test_nothing_rendered_for_a_hop_names_a_protocol_or_an_interface(
    name: str, node, request
) -> None:
    """M3.2: the entry learns an ADDRESS, and nothing else about the hop.

    The rule this milestone was most likely to break. What carries the hop — AmneziaWG
    today, something not yet written tomorrow — must not appear in the config of the
    transport that routes into it, or a new protocol stops being one package.
    """
    config = rendered(name, node, request, egress=Egress.HOP, exit_via=HOP_ADDRESS)

    for other in discover():
        if other == name:
            continue
        assert other not in config, f"{name}'s config names the transport {other}"


# --- M3.2: a node with no hop is untouched -----------------------------------------

@pytest.mark.parametrize("name", INSTALLED)
def test_a_node_with_no_hop_renders_exactly_what_it_always_did(
    name: str, node, request
) -> None:
    """The second "done when", asserted as byte equality rather than as behaviour.

    Every leaf in the fleet, and every single-node deployment, is this case. The golden
    files pin the same bytes from the other side; this pins that ASKING for the policy a
    node without a hop has changes nothing.
    """
    assert rendered(name, node, request, egress=Egress.LOCAL) == rendered(
        name, node, request, egress=Egress.LOCAL, exit_via=None
    )


# --- M3.3: and it fails closed ------------------------------------------------------

@pytest.mark.parametrize("name", INSTALLED)
def test_a_hop_policy_with_no_address_is_refused(name: str, node, request) -> None:
    """Decision 3. The one thing that must never happen is a quiet local exit.

    A caller that says "this node exits through a hop" and does not say through which
    address has described a policy nothing can render. Rendering it anyway would fall back
    to the direct outbound — which is the answer decision 3 exists to forbid.
    """
    with pytest.raises(EgressNotRenderable):
        rendered(name, node, request, egress=Egress.HOP)


@pytest.mark.parametrize("name", INSTALLED)
def test_an_address_without_the_policy_is_refused(name: str, node, request) -> None:
    """Two contradictory answers to "where does this traffic leave" render as neither."""
    with pytest.raises(EgressNotRenderable):
        rendered(name, node, request, egress=Egress.LOCAL, exit_via=HOP_ADDRESS)


def test_the_address_a_proxy_opens_connections_from_is_the_hops_own() -> None:
    """The whole of the contract's second half, stated once, without a transport.

    ``None`` for every policy that is not a hop — which is what every node without one has
    always had, and why enabling this milestone cannot change a leaf's config.
    """
    assert exit_origin(Egress.HOP, "10.44.0.1/24") == "10.44.0.1"
    assert exit_origin(Egress.HOP, "10.44.0.1") == "10.44.0.1"
    assert exit_origin(Egress.LOCAL, None) is None
    assert exit_origin(Egress.NONE, None) is None
