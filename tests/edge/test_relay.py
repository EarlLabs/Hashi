"""The entry→leaf hop — backlog item 16.

WHAT: what ``edge.relay`` renders for the two ends of one node-to-node tunnel, and
      what it refuses to render.
WHY:  this hop is the topology the charter is built on — a Russian entry node fronting
      foreign leaves — and every failure it can have is silent. A tunnel whose two ends
      disagree is a pair of perfectly valid config files, a daemon that starts, a node
      that reports healthy, and no traffic. So the refusals are as much the subject
      here as the rendering.
HOW:  pure, like everything in this zone: two fixed ends built from the same frozen
      fixtures the golden files use, and no node is contacted.

      The boundary, stated plainly: nothing here proves two hosts formed a tunnel. It
      proves each end is told to expect exactly the other, that only the entry dials,
      and that mismatched ends are refused instead of rendered.
"""

import pytest

from edge import relay
from edge.node import NodeView
from edge.registry import discover, profile

HOP_TRANSPORT = "amneziawg"


@pytest.fixture
def entry_node() -> NodeView:
    """The Russian entry node. Reserved address (RFC 5737), like every fixture here."""
    return NodeView(
        id="eeeeeeee-0000-4000-8000-00000000000e",
        address="192.0.2.20",
        location_label="entry",
        display_name="entry-1",
        resolver=None,
    )


@pytest.fixture
def leaf_node(node) -> NodeView:
    """The foreign leaf. Reuses the shared node fixture so addresses stay frozen."""
    return node


def directives(config: str) -> str:
    """A rendered config without its comments.

    Every assertion about what a config says has to read this rather than the file: the
    templates explain their own decisions at length, so matching the raw text would make
    an assertion pass for a comment that describes the opposite of what is rendered.
    """
    return "\n".join(
        line for line in config.splitlines() if line and not line.startswith("#")
    )


def ends(entry_node, leaf_node, amneziawg_params, **leaf_overrides):
    """The two ends of one hop, each validated by the transport's own model."""
    validate = profile(HOP_TRANSPORT).validate
    entry_params = validate(
        {**amneziawg_params, "tunnel_address": "10.44.0.1/24",
         "peer_tunnel_address": "10.44.0.2/24"}
    )
    leaf_params = validate(
        {**amneziawg_params, "tunnel_address": "10.44.0.2/24",
         "peer_tunnel_address": "10.44.0.1/24", **leaf_overrides}
    )
    return (
        relay.HopEnd(node=entry_node, params=entry_params),
        relay.HopEnd(node=leaf_node, params=leaf_params),
    )


def test_each_end_authorises_exactly_the_other(entry_node, leaf_node, amneziawg_params) -> None:
    """One peer each, and it is the far end's public key.

    The property that makes this a hop rather than a public server: a second peer
    block would be a second node able to source traffic into our tunnel.
    """
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    assert entry_config.count("[Peer]") == 1
    assert leaf_config.count("[Peer]") == 1
    assert f"PublicKey = {leaf.public_key}" in entry_config
    assert f"PublicKey = {entry.public_key}" in leaf_config


def test_only_the_entry_dials(entry_node, leaf_node, amneziawg_params) -> None:
    """The direction is forced, not chosen.

    The entry sits behind a Russian carrier NAT and cannot be dialled. A leaf given an
    endpoint would try anyway, and the tunnel would come up only when the entry
    happened to have spoken first — which reads as "works, sometimes".
    """
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    assert f"Endpoint = {leaf_node.address}:{leaf.params['port']}" in entry_config
    assert "Endpoint" not in leaf_config


def test_the_leaf_routes_no_more_than_the_entrys_own_address(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """AllowedIPs is the authorisation list as well as the routing table.

    On the leaf a wide entry would let the far end source traffic as any address in the
    range, and it buys nothing: everything the leaf sends back into the hop is addressed
    to the entry's own tunnel address.
    """
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    _, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    assert "AllowedIPs = 10.44.0.1/32" in leaf_config
    assert "/0" not in directives(leaf_config)


def test_the_entry_routes_everything_into_the_hop_and_installs_no_route(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """The entry's half is the opposite, and both halves of that are load-bearing — M3.

    ``AllowedIPs`` is WireGuard's crypto-routing table: a friend's packet is encrypted to
    a peer only if that peer's list covers the DESTINATION, and the reply is accepted only
    if it covers the SOURCE. So an entry whose exit is the far end cannot route a friend
    anywhere with the narrow form — the interface drops the packet, and nothing logs it.

    What made a wide list dangerous is the ROUTE wg-quick derives from it, which would put
    a default route in the main table and take the node's own SSH session — the one the
    control plane manages it over — with it. That is a separate switch, and this asserts
    both together: everything is allowed INTO the tunnel, and the tool installs nothing.
    """
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, _ = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    assert "AllowedIPs = 0.0.0.0/0" in entry_config
    assert "Table = off" in directives(entry_config)
    # The way out is source-routed from the tunnel's own address, so nothing else on the
    # node — SSH above all — can be pulled into the hop by it.
    assert "from 10.44.0.1 lookup" in entry_config


def test_the_hop_never_names_a_node_in_a_way_a_person_could_be_read_from(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """A file on a remote host must not carry the fleet's operator-facing names."""
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    for config in (entry_config, leaf_config):
        assert entry_node.display_name not in config
        assert leaf_node.display_name not in config


def test_the_way_out_is_the_entrys_own_tunnel_address(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """The address a friend's traffic leaves the entry through, without the prefix.

    The ENTRY's, not the leaf's, and that is M3's one correction to its own plan: nothing
    listens at the leaf's in-tunnel address for the entry to dial. What the leaf offers is
    a route, and the only way to hand a packet to it is to send it through the tunnel — so
    what the entry's data plane needs is an address to send FROM. See ``relay.exit_via``.
    """
    entry, _ = ends(entry_node, leaf_node, amneziawg_params)
    assert relay.exit_via(entry) == "10.44.0.1"


# --- what it refuses, and why each refusal is a silent failure otherwise -----

def test_a_node_cannot_be_its_own_exit(entry_node, amneziawg_params) -> None:
    entry, leaf = ends(entry_node, entry_node, amneziawg_params)
    with pytest.raises(relay.HopNotRenderable):
        relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)


def test_two_ends_claiming_one_tunnel_address_are_refused(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """Both ends on one address renders fine and routes nothing."""
    entry, leaf = ends(
        entry_node, leaf_node, amneziawg_params,
        tunnel_address="10.44.0.1/24", peer_tunnel_address="10.44.0.1/24",
    )
    with pytest.raises(relay.HopNotRenderable):
        relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)


def test_ends_on_different_tunnel_networks_are_refused(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """Neither end would have a route to the other, and neither daemon would say so."""
    entry, leaf = ends(
        entry_node, leaf_node, amneziawg_params,
        tunnel_address="10.99.0.2/24", peer_tunnel_address="10.99.0.1/24",
    )
    with pytest.raises(relay.HopNotRenderable):
        relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)


def test_mismatched_preshared_keys_are_refused(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """A symmetric key that is not shared means a handshake that never completes."""
    # A different but equally well-formed key: the refusal must come from the two ends
    # disagreeing, not from one of them being malformed.
    entry, leaf = ends(
        entry_node, leaf_node, amneziawg_params, preshared_key=amneziawg_params["public_key"]
    )
    with pytest.raises(relay.HopNotRenderable):
        relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)


def test_both_ends_of_a_hop_still_carry_the_one_key_they_agree_on(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """M23 gave every friend a pre-shared key of their own; a hop must not get two.

    The peer at each end of a hop is a NODE, and its pre-shared key is declared at node
    scope and ``shared_between_peers`` precisely because two independently minted values
    are two valid files and a handshake that never completes — the refusal above exists
    for that. ``relay`` synthesises each end's peer from parameters alone and gives it no
    per-pair material, so the renderer's fallback is what keeps this true. Asserted here
    because the owner's live hop runs these bytes and nothing else would notice them
    changing.
    """
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    shared = f"PresharedKey = {amneziawg_params['preshared_key']}"
    assert shared in directives(entry_config)
    assert shared in directives(leaf_config)


# Every transport in this image that declares parameters both ends must carry
# identically. Parametrised off the registry rather than written down, so a fifth
# transport arriving with such a declaration is covered by arriving — and an empty list
# means no shipped transport makes the claim, not that the rule went untested.
MATCHED_PARAMS = sorted(
    (name, field)
    for name, meta in discover().items()
    for field in meta.hop_matched_params
)


@pytest.mark.parametrize("name,field", MATCHED_PARAMS, ids=lambda value: str(value))
def test_two_ends_disagreeing_about_a_matched_parameter_are_refused(
    name: str, field: str, entry_node, leaf_node, amneziawg_params
) -> None:
    """M26's first acceptance walk, and the same silent failure as the key above.

    Establishing one hop is 22 empty boxes, 11 per end, and four of them per end are
    values that mean nothing unless they are identical at both ends — obfuscation magic
    headers, typed by hand twice, with the panel's own note telling the operator not to
    copy them out of the protocol's documentation. Get one digit wrong on one end and
    both files are valid, both daemons start, and the tunnel carries nothing.

    The value is moved by ONE, deliberately: what is refused is the two ends disagreeing,
    not a value being out of range, and a wildly different number would be refused by the
    transport's own model before this check was reached.
    """
    if name != HOP_TRANSPORT:  # pragma: no cover - one hop-capable transport ships today
        pytest.skip(f"{name} is not the transport these fixtures are built for")

    entry, leaf = ends(
        entry_node, leaf_node, amneziawg_params, **{field: amneziawg_params[field] + 1}
    )

    with pytest.raises(relay.HopNotRenderable) as refused:
        relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    assert field in str(refused.value), (
        "the refusal does not name the box to correct, and there are four of them that "
        "look alike"
    )


def test_two_ends_that_agree_about_every_matched_parameter_render(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """The accept direction, without which the refusal above could refuse every hop."""
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    assert entry_config and leaf_config


def test_an_ipv6_endpoint_is_bracketed(leaf_node, entry_node, amneziawg_params) -> None:
    """Otherwise the daemon reads the last group of the address as the port."""
    leaf_v6 = NodeView(
        id=leaf_node.id,
        # RFC 3849 documentation prefix.
        address="2001:db8::1",
        location_label=leaf_node.location_label,
        display_name=leaf_node.display_name,
        resolver=leaf_node.resolver,
    )
    entry, leaf = ends(entry_node, leaf_v6, amneziawg_params)
    assert relay.endpoint_of(leaf) == f"[2001:db8::1]:{leaf.params['port']}"


# --- the charter's constraint on WHICH transports may carry a hop (item 28) -----

NOT_HOP_CAPABLE = sorted(
    name for name, meta in discover().items() if not meta.hop_capable
)


@pytest.mark.parametrize("name", NOT_HOP_CAPABLE)
def test_a_transport_that_cannot_carry_a_hop_is_refused_before_anything_is_written(
    name: str, entry_node, leaf_node, request
) -> None:
    """The charter's constraint, and the reason it is checked here and not in `control`.

    This hop crosses the Russian border by definition. A protocol that is identified and
    blocked there produces two nodes each holding a valid configuration file and no
    tunnel between them — the exact silent failure every other refusal in this module
    exists for, except that no inspection of either file reveals it.

    Refused inside ``edge.relay``, which means it happens BEFORE either end is written:
    `control` renders the pair for validation before committing, and converts
    ``HopNotRenderable`` into a 400 with this message in it. So the operator reads a
    sentence and loses a form submission, rather than acquiring half a topology.

    Parametrised over the registry: the list being empty would mean no such transport
    ships, not that the rule went untested.
    """
    validated = profile(name).validate(
        request.getfixturevalue("transport_fixture")(name, "params")
    )
    entry = relay.HopEnd(node=entry_node, params=validated)
    leaf = relay.HopEnd(node=leaf_node, params=validated)

    with pytest.raises(relay.HopNotRenderable) as refused:
        relay.render_hop(name, entry=entry, leaf=leaf)

    message = str(refused.value)
    assert name in message
    # The message has to say WHY, or an operator reads it as a bug in hashi and retries.
    assert "hop" in message and "blocked" in message


def test_the_hop_transport_this_module_uses_is_actually_hop_capable() -> None:
    """Guard for every other test here: they would all pass vacuously otherwise.

    If the transport these scenarios are written against ever declared itself unusable
    on a hop, the refusal above would fire first and every assertion in this file would
    be testing that refusal instead of the rendering it claims to test.

    Both halves, since M20's acceptance: ``hop_expressible`` is the permission AND the
    ability, and a transport that lost either would take every scenario here with it.
    """
    assert profile(HOP_TRANSPORT).meta.hop_expressible


# --- the other half of that question: CAN a hop be built out of this? ------------

# Permitted on a hop and shaped like nothing that could be one — the gap M20's
# acceptance walk fell into. Derived from the two declarations rather than named, so a
# future package lands in this list by declaring, never by being listed here.
PERMITTED_BUT_UNSHAPED = sorted(
    name
    for name, meta in discover().items()
    if meta.hop_capable and meta.peer_address is None
)


@pytest.mark.parametrize("name", PERMITTED_BUT_UNSHAPED)
def test_a_transport_with_no_address_of_its_own_is_refused_and_not_a_crash(
    name: str, entry_node, leaf_node, request
) -> None:
    """The refusal that was a ``KeyError``, and why the difference is the whole point.

    ``hop_capable`` is a permission — it defaults to True and says only that this
    protocol is not identified at the border it would cross. It is not the ability, and
    a transport that has simply never been shaped like a hop end declares nothing at all
    about being one: the two VLESS packages sailed past the check above and reached the
    tunnel-address reads, where a parameter they had never declared came back as
    ``KeyError: 'tunnel_address'``. `control` turns ``HopNotRenderable`` into a 400 that
    names the reason and lets everything else become a 500, so that gap reached the
    operator as a crash on a path ``GET /api/transports`` advertised as capable.

    What is asserted is therefore the TYPE as much as the sentence: anything other than
    ``HopNotRenderable`` here is a 500 one zone over.

    Parametrised over the registry, and an empty list means no such transport ships
    rather than that the rule went untested.
    """
    validated = profile(name).validate(
        request.getfixturevalue("transport_fixture")(name, "params")
    )
    entry = relay.HopEnd(node=entry_node, params=validated)
    leaf = relay.HopEnd(node=leaf_node, params=validated)

    with pytest.raises(relay.HopNotRenderable) as refused:
        relay.render_hop(name, entry=entry, leaf=leaf)

    message = str(refused.value)
    assert name in message
    # It has to say WHY, or the operator reads a refusal they cannot act on.
    assert "address" in message and "hop" in message
