"""One tunnel, one address each — M17.1a.

WHAT: the arithmetic in ``edge/addressing.py``, and the rule both WireGuard-family
      packages gained with it: a resolver written into a friend's config may not be an
      address inside the tunnel itself.
WHY:  a WireGuard-family transport used to hold ONE ``peer_tunnel_address``, so it
      served one friend and the second was refused at render (``AmbiguousPeerRoute``,
      found in the field). The refusal is right and is untouched here; what these tests
      pin is where the second address comes from, and that the first one is still
      byte-for-byte the address the renderers already fall back to — a transport
      enabled before M17 must render the same bytes afterwards.
HOW:  pure calls, no Docker and no database. Tunnel addresses are RFC 1918, matching
      the fixtures in ``conftest.py`` and what both packages' own validators require.
"""

import ipaddress
import sys
from collections.abc import Iterator
from itertools import islice

import pytest
from pydantic import ValidationError

from edge.addressing import host_of, networks_overlap, pool, pool_problem
from edge.registry import ConfigFormat, discover, profile

# The formats a wg-quick-style tool runs. Derived from the config-format vocabulary
# rather than from protocol names, because the property being asserted is about the
# data plane: a kernel tunnel identifies its consumers BY ADDRESS, so every one of them
# needs an address of their own. A VLESS transport identifies them by UUID and needs no
# pool at all.
WG_QUICK_FORMATS = {ConfigFormat.WG_QUICK, ConfigFormat.WG_QUICK_PLAIN}

KERNEL_TUNNELS = sorted(
    name for name, meta in discover().items() if meta.config_format in WG_QUICK_FORMATS
)


# --- what a transport declares ------------------------------------------------


def test_every_kernel_tunnel_says_each_user_needs_an_address_of_their_own() -> None:
    """The declaration is what makes the pool possible without naming a protocol."""
    assert KERNEL_TUNNELS, "no wg-quick-family transport is installed"

    for name in KERNEL_TUNNELS:
        declared = discover()[name].peer_address
        assert declared is not None, (
            f"{name} renders one address per peer and declares no peer_address, so "
            "`control` has nowhere to put the address it allocated"
        )
        fields = profile(name).params_model.model_fields
        assert declared.name in fields and declared.within in fields


# --- the pool -----------------------------------------------------------------


def test_a_pool_hands_out_consecutive_addresses_keeping_the_prefix() -> None:
    """Three users, three addresses, each written the way the operator wrote the first."""
    assert list(pool("10.66.0.2/24", 3)) == ["10.66.0.2/24", "10.66.0.3/24", "10.66.0.4/24"]


def test_a_pool_carries_the_first_address_across_a_byte_boundary() -> None:
    """The arithmetic is over the address, not over its last octet."""
    assert list(pool("10.66.0.255/16", 2)) == ["10.66.0.255/16", "10.66.1.0/16"]


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_the_first_address_is_exactly_what_the_renderer_already_falls_back_to(
    name: str, request
) -> None:
    """Byte-identical, which is the whole promise made to a row enabled before M17.

    The renderers read ``secrets.get(<name>) or params[<name>]``, and ``params`` holds
    whatever the transport's own validator normalised the operator's typing to. So the
    claim is not "looks the same" but "is the same string".
    """
    declared = discover()[name].peer_address
    validated = profile(name).validate(request.getfixturevalue(f"{name}_params"))
    fallback = validated[declared.name]

    assert next(iter(pool(fallback, 1))) == fallback
    assert next(iter(pool(fallback, 1))) == str(ipaddress.ip_interface(fallback))


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_a_pool_of_one_renders_the_same_config_as_no_pool_at_all(
    name: str, node, request
) -> None:
    """The same claim, made where it is actually spent: in the rendered file.

    One peer with the pool's first address in its own secrets, against one peer with
    nothing — the pre-M17 shape, which falls back to the single typed parameter.
    """
    from dataclasses import replace

    transport = profile(name)
    declared = transport.meta.peer_address
    validated = transport.validate(request.getfixturevalue(f"{name}_params"))
    credential = request.getfixturevalue(f"{name}_credentials")[0]

    first = next(iter(pool(validated[declared.name], 1)))
    allocated = replace(
        credential, secrets={**credential.secrets, declared.name: first}
    )

    assert transport.profile.render_server(node, validated, [allocated]) == (
        transport.profile.render_server(node, validated, [credential])
    )


def test_a_pool_is_lazy_and_is_never_built_to_be_measured() -> None:
    """A /8 sized in the millions costs what a /29 costs.

    ``getsizeof`` rather than a stopwatch: a generator is a couple of hundred bytes
    whatever its length, so this says "nothing was materialised" deterministically
    instead of "it was quick on this machine".
    """
    run = pool("10.0.0.2/8", 2**20)

    assert isinstance(run, Iterator)
    assert sys.getsizeof(run) < 1000
    assert list(islice(run, 3)) == ["10.0.0.2/8", "10.0.0.3/8", "10.0.0.4/8"]


@pytest.mark.parametrize(
    ("description", "first", "within", "size"),
    [
        ("an ordinary tunnel", "10.66.0.2/24", "10.66.0.1/24", 200),
        # RFC 3021: a /31 is two addresses and BOTH are hosts — it has no network or
        # broadcast address to keep clear of. So the node takes one and a single user
        # takes the other, and that user's address is the one a /24 would have called
        # the broadcast. This is the only case that exercises ``has_edges`` being False:
        # mutating it to an unconditional True refuses this pool, which is a working
        # point-to-point tunnel turned away.
        ("a two-address tunnel, which has no edges to keep clear of", "10.66.0.1/31",
         "10.66.0.0/31", 1),
    ],
)
def test_a_workable_pool_has_no_problem(
    description: str, first: str, within: str, size: int
) -> None:
    assert pool_problem(first, within, size) is None, description


@pytest.mark.parametrize(
    ("description", "first", "within", "size", "phrase"),
    [
        ("a pool holding nobody", "10.66.0.2/24", "10.66.0.1/24", 0, "at least one"),
        ("a negative pool", "10.66.0.2/24", "10.66.0.1/24", -3, "at least one"),
        ("a first address that is not one", "ten.sixty.six", "10.66.0.1/24", 4, "not an address"),
        ("a tunnel address with no prefix", "10.66.0.2/24", "nonsense", 4, "not an address"),
        ("an IPv6 tunnel", "fd00::2/64", "fd00::1/64", 4, "IPv4 only"),
        ("a pool outside the tunnel", "10.67.0.2/24", "10.66.0.1/24", 4, "is outside"),
        ("a pool over the node's own address", "10.66.0.1/24", "10.66.0.1/24", 4, "node's own"),
        ("a pool reaching the node's address", "10.66.0.8/24", "10.66.0.10/24", 4, "node's own"),
        ("a pool on the network address", "10.66.0.0/24", "10.66.0.200/24", 4, "network address"),
        ("a pool past the end", "10.66.0.250/24", "10.66.0.1/24", 20, "runs past the end"),
        ("a pool ending on the broadcast", "10.66.0.250/24", "10.66.0.1/24", 6, "broadcast"),
        ("a pool leaving private space", "172.31.255.250/8", "172.31.0.1/8", 20, "private"),
    ],
)
def test_a_pool_that_cannot_work_says_why(
    description: str, first: str, within: str, size: int, phrase: str
) -> None:
    """One sentence an operator can act on, for each way a pool fails.

    Each of these is a silent failure standing behind a plausible-looking number: a
    device that never receives a packet, a user holding the node's own address, or a
    pool that quietly runs off the end of the range the operator sized.
    """
    problem = pool_problem(first, within, size)

    assert problem is not None, f"{description} was accepted"
    assert phrase in problem, f"{description}: {problem}"


def test_a_pool_is_measured_arithmetically_rather_than_by_building_it() -> None:
    """A pool too large for its network is refused without a millionth string.

    The same ``getsizeof`` trick is not available for a function that returns a string,
    so this leans on the size: enumerating a /8's worth of addresses to discover they
    do not fit would take seconds and hundreds of megabytes.
    """
    problem = pool_problem("10.0.0.2/8", "10.0.0.1/8", 2**30)

    assert problem is not None
    assert "runs past the end" in problem


def test_the_room_left_is_named_so_the_operator_can_pick_a_number() -> None:
    """A refusal that says only "too big" sends the operator guessing."""
    problem = pool_problem("10.66.0.250/24", "10.66.0.1/24", 20)

    assert problem is not None
    # .250 through .254 — the broadcast address is not one of them.
    assert "5 are left" in problem


# --- one address's canonical form, and two networks ---------------------------


@pytest.mark.parametrize(
    ("written", "bare"),
    [("10.66.0.2/24", "10.66.0.2"), ("10.66.0.2", "10.66.0.2"), ("10.66.0.2/32", "10.66.0.2")],
)
def test_one_address_has_one_canonical_host(written: str, bare: str) -> None:
    assert host_of(written) == bare


@pytest.mark.parametrize(
    ("a", "b", "overlapping"),
    [
        ("10.66.0.1/24", "10.66.0.9/24", True),
        ("10.66.0.1/24", "10.66.1.1/24", False),
        ("10.66.0.1/16", "10.66.1.1/24", True),
        ("10.66.0.1/24", "fd00::1/64", False),
    ],
)
def test_two_tunnels_are_told_apart_by_their_networks(a: str, b: str, overlapping: bool) -> None:
    """Asked of the whole range, because one address each is not the question.

    Two interfaces on one node share the host's routing table, so a reply to a user on
    one could reach whoever holds the same address on the other.
    """
    assert networks_overlap(a, b) is overlapping
    assert networks_overlap(b, a) is overlapping


# --- a resolver inside the tunnel ---------------------------------------------


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_a_resolver_inside_the_tunnel_is_refused(name: str, request) -> None:
    """With a pool, that address is somebody's device — and it would see every lookup."""
    params = dict(request.getfixturevalue(f"{name}_params"))
    within = ipaddress.ip_interface(params["tunnel_address"])
    params["client_dns"] = (str(within.ip + 5),)

    with pytest.raises(ValidationError) as refused:
        profile(name).validate(params)

    assert "client_dns" in str(refused.value)
    assert str(within.network) in str(refused.value)


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_the_tunnels_own_address_is_refused_as_a_resolver(name: str, request) -> None:
    """The most natural wrong value: the node answers no lookups on that address."""
    params = dict(request.getfixturevalue(f"{name}_params"))
    params["client_dns"] = (host_of(params["tunnel_address"]),)

    with pytest.raises(ValidationError):
        profile(name).validate(params)


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_a_resolver_outside_the_tunnel_is_accepted(name: str, request) -> None:
    """The rule is about the tunnel's own range, not about resolvers in general."""
    params = dict(request.getfixturevalue(f"{name}_params"))
    params["client_dns"] = ("192.0.2.53",)

    assert profile(name).validate(params)["client_dns"] == ("192.0.2.53",)


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_a_resolver_that_is_a_name_still_says_it_cannot_be_a_name(name: str, request) -> None:
    """The older rule keeps its own sentence, which is a question of validator ORDER.

    Both rules sit on ``client_dns`` and pydantic runs them in the order they are
    written. The range check placed first would reach a hostname before anything had
    established it was an address, and report the standard library's complaint instead
    of the reason a name cannot work here.
    """
    params = dict(request.getfixturevalue(f"{name}_params"))
    params["client_dns"] = ("resolver.example.com",)

    with pytest.raises(ValidationError) as refused:
        profile(name).validate(params)

    assert "cannot be a name" in str(refused.value)


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_a_broken_tunnel_address_does_not_hide_itself_behind_the_resolver(
    name: str, request
) -> None:
    """The tunnel address's own failure is the one worth reading.

    A validator that raised on the missing value would report a resolver problem for a
    tunnel address the operator has not yet typed correctly.
    """
    params = dict(request.getfixturevalue(f"{name}_params"))
    params["tunnel_address"] = "not-an-address"
    params["client_dns"] = ("10.66.0.5",)

    with pytest.raises(ValidationError) as refused:
        profile(name).validate(params)

    assert "tunnel_address" in str(refused.value)
    assert "client_dns" not in str(refused.value)
