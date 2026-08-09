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
    )


@pytest.fixture
def leaf_node(node) -> NodeView:
    """The foreign leaf. Reuses the shared node fixture so addresses stay frozen."""
    return node


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


def test_neither_end_routes_more_than_the_far_ends_own_address(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """AllowedIPs is the authorisation list as well as the routing table.

    A wide entry here would let the far end source traffic as any address in the range,
    and a default route would send the node's own SSH session — the one the control
    plane manages it over — into the tunnel.
    """
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    assert "AllowedIPs = 10.44.0.2/32" in entry_config
    assert "AllowedIPs = 10.44.0.1/32" in leaf_config
    # Directives only: the template's own comment explains why a default route is
    # wrong, and matching that comment would make this assertion pass for the text
    # rather than for the configuration.
    for config in (entry_config, leaf_config):
        directives = [
            line for line in config.splitlines() if line and not line.startswith("#")
        ]
        assert not [line for line in directives if "/0" in line]


def test_the_hop_never_names_a_node_in_a_way_a_person_could_be_read_from(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """A file on a remote host must not carry the fleet's operator-facing names."""
    entry, leaf = ends(entry_node, leaf_node, amneziawg_params)

    entry_config, leaf_config = relay.render_hop(HOP_TRANSPORT, entry=entry, leaf=leaf)

    for config in (entry_config, leaf_config):
        assert entry_node.display_name not in config
        assert leaf_node.display_name not in config


def test_the_exit_address_is_the_leafs_tunnel_address(
    entry_node, leaf_node, amneziawg_params
) -> None:
    """Where traffic goes once it is inside the tunnel, without the prefix."""
    _, leaf = ends(entry_node, leaf_node, amneziawg_params)
    assert relay.exit_address(leaf) == "10.44.0.2"


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


def test_an_ipv6_endpoint_is_bracketed(leaf_node, entry_node, amneziawg_params) -> None:
    """Otherwise the daemon reads the last group of the address as the port."""
    leaf_v6 = NodeView(
        id=leaf_node.id,
        # RFC 3849 documentation prefix.
        address="2001:db8::1",
        location_label=leaf_node.location_label,
        display_name=leaf_node.display_name,
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
    """
    assert profile(HOP_TRANSPORT).meta.hop_capable
