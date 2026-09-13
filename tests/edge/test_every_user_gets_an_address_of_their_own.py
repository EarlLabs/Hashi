"""One tunnel, one address each — M17.1a.

WHAT: the arithmetic in ``edge/addressing.py``, the rule both WireGuard-family
      packages gained with it — a resolver written into a friend's config may not be an
      address inside the tunnel itself — and the refusal underneath all of it: two peers
      holding one address are refused at render, in each package.
WHY:  a WireGuard-family transport used to hold ONE ``peer_tunnel_address``, so it
      served one friend and the second was refused at render (``AmbiguousPeerRoute``,
      found in the field). The refusal is right and is unchanged by this milestone —
      and it is pinned here, in each package, because it is the one property with a
      victim: what it prevents is one friend's return traffic arriving at another
      friend's device. What these tests add around it is where the second address comes
      from, and that the first one is still byte-for-byte the address the renderers
      already fall back to — a transport enabled before M17 must render the same bytes
      afterwards.
HOW:  pure calls, no Docker and no database. Tunnel addresses are RFC 1918, matching
      the fixtures in ``conftest.py`` and what both packages' own validators require.
"""

import ipaddress
import sys
from collections.abc import Iterator
from dataclasses import replace
from itertools import islice

import pytest
from pydantic import ValidationError

from edge.addressing import (
    carriage_problem,
    host_of,
    networks_overlap,
    pool,
    pool_problem,
)
from edge.node import Credential
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


# --- two peers on one address: the refusal this whole milestone stands on ------
#
# ``AllowedIPs`` is WireGuard's authorisation list AND its routing table, so two peers
# holding one address is not a duplicate the daemon merges — the later peer silently
# takes over the earlier one's route. Rendered, that is one friend's return traffic
# arriving at another friend's device, with nothing anywhere saying so and both devices
# still looking configured. Each package refuses it at render (``AmbiguousPeerRoute``),
# and the pool this milestone adds exists so that it never has to fire. These are the tests that
# keep it firing: they are asked of every kernel tunnel, so a package cannot lose the
# refusal and be caught only by `control`.


def _holding(credential: Credential, name: str, address: str | None) -> Credential:
    """The same credential, holding ``address`` — or holding none of its own at all.

    ``None`` is the pre-M17 shape rather than a broken credential: before this milestone
    nothing minted a per-peer address, so every credential on a row fell back to the
    single address in ``params``. That is the state the refusal was found in, in the
    field, on the second friend.
    """
    secrets = {key: value for key, value in credential.secrets.items() if key != name}
    if address is not None:
        secrets[name] = address
    return replace(credential, secrets=secrets)


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_two_peers_holding_one_address_are_refused_rather_than_rendered(
    name: str, node, request
) -> None:
    """The allocator's own bug, were it ever to hand one address out twice."""
    transport = profile(name)
    declared = transport.meta.peer_address
    validated = transport.validate(request.getfixturevalue(f"{name}_params"))
    first, second = request.getfixturevalue(f"{name}_credentials")[:2]
    shared = next(iter(pool(validated[declared.name], 1)))

    with pytest.raises(transport.profile.AmbiguousPeerRoute) as refused:
        transport.profile.render_server(
            node,
            validated,
            [
                _holding(first, declared.name, shared),
                _holding(second, declared.name, shared),
            ],
        )

    assert shared in str(refused.value), refused.value
    assert "own tunnel address" in str(refused.value), refused.value


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_two_peers_with_no_address_of_their_own_collide_on_the_one_in_params(
    name: str, node, request
) -> None:
    """The field failure verbatim: a pre-pool row, a second friend, no allocation.

    Nothing here is malformed — this is what every credential on a row enabled before
    M17 looks like — which is exactly why the renderer has to be the one to refuse it.
    """
    transport = profile(name)
    declared = transport.meta.peer_address
    validated = transport.validate(request.getfixturevalue(f"{name}_params"))
    first, second = request.getfixturevalue(f"{name}_credentials")[:2]

    with pytest.raises(transport.profile.AmbiguousPeerRoute) as refused:
        transport.profile.render_server(
            node,
            validated,
            [
                _holding(first, declared.name, None),
                _holding(second, declared.name, None),
            ],
        )

    assert str(validated[declared.name]) in str(refused.value), refused.value


@pytest.mark.parametrize("name", KERNEL_TUNNELS)
def test_two_peers_from_one_pool_render_two_routes_of_their_own(
    name: str, node, request
) -> None:
    """The other half, without which a package could pass by refusing everything.

    A refusal that fires on two peers whatever their addresses would be a transport
    serving one friend — the state M17 exists to leave behind — and the test above
    could not tell the difference.
    """
    transport = profile(name)
    declared = transport.meta.peer_address
    validated = transport.validate(request.getfixturevalue(f"{name}_params"))
    first, second = request.getfixturevalue(f"{name}_credentials")[:2]
    allocated = list(pool(validated[declared.name], 2))

    config = transport.profile.render_server(
        node,
        validated,
        [
            _holding(first, declared.name, allocated[0]),
            _holding(second, declared.name, allocated[1]),
        ],
    )

    routes = [f"AllowedIPs = {host_of(address)}/32" for address in allocated]
    assert len(set(routes)) == 2, routes
    for route in routes:
        assert route in config, config

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


# --- what a tunnel could not carry (M17.1c) -----------------------------------
#
# The other side of ``pool_problem``: not "can this pool be handed out" but "is an
# address somebody is ALREADY using still carried by the tunnel the operator has just
# retyped". Same rules, different answer — a clause naming the cause, for a refusal that
# counts people rather than listing them.


@pytest.mark.parametrize(
    ("description", "address", "within"),
    [
        ("an ordinary user's address", "10.66.0.2", "10.66.0.1/24"),
        ("written with its prefix", "10.66.0.2/24", "10.66.0.1/24"),
        ("the last host in the range", "10.66.0.254", "10.66.0.1/24"),
        ("the other end of a /31, which has no edges", "10.66.0.0", "10.66.0.1/31"),
    ],
)
def test_an_address_a_tunnel_can_still_carry_has_no_problem(
    description: str, address: str, within: str
) -> None:
    assert carriage_problem(address, within) is None, description


@pytest.mark.parametrize(
    ("description", "address", "within", "phrase"),
    [
        ("outside the range", "10.67.0.2", "10.66.0.1/24", "outside the range"),
        ("the node's own address", "10.66.0.1", "10.66.0.1/24", "node's own address"),
        ("the network address", "10.66.0.0", "10.66.0.1/24", "network address"),
        ("the broadcast address", "10.66.0.255", "10.66.0.1/24", "broadcast address"),
        ("out of private space", "11.0.0.2", "11.0.0.1/8", "private address space"),
        ("an IPv6 tunnel", "fd00::2", "fd00::1/64", "IPv6"),
        ("a tunnel address with no prefix", "10.66.0.2", "nonsense", "not an address"),
        ("a stored value that is not an address", "ten.sixty.six", "10.66.0.1/24",
         "not an address"),
    ],
)
def test_what_a_tunnel_cannot_carry_says_which_of_the_causes_it_is(
    description: str, address: str, within: str, phrase: str
) -> None:
    """The cause, not a catch-all — the operator's next move differs for each.

    "Outside the range" is fixed with a wider prefix; "the node's own address" is fixed
    by moving the node, and a wider prefix does not touch it. A single sentence covering
    both sends the operator round a loop on the second one, which is the case with a
    victim: whoever holds the node's own address is authorised to send as the node.
    """
    problem = carriage_problem(address, within)

    assert problem is not None, f"{description} was accepted"
    assert phrase in problem, f"{description}: {problem}"


@pytest.mark.parametrize(
    ("address", "within"),
    [
        ("10.66.0.2", "10.66.0.1/24"),
        ("10.66.0.1", "10.66.0.1/24"),
        ("10.66.0.0", "10.66.0.1/24"),
        ("10.66.0.255", "10.66.0.1/24"),
        ("10.67.0.2", "10.66.0.1/24"),
        ("11.0.0.2", "11.0.0.1/8"),
        ("10.66.0.0", "10.66.0.1/31"),
        ("fd00::2", "fd00::1/64"),
        ("10.66.0.2", "nonsense"),
    ],
)
def test_what_a_tunnel_cannot_carry_is_what_a_pool_of_one_refuses(
    address: str, within: str
) -> None:
    """Two functions, one set of rules — and this is what keeps them that way.

    A held address is a pool of exactly one at that address, so the two must never
    disagree about WHETHER there is a problem. They differ only in what the answer may
    say: ``pool_problem`` quotes the address it was asked about, which is why a refusal
    counting the people on a row cannot use it.
    """
    assert (carriage_problem(address, within) is None) == (
        pool_problem(address, within, 1) is None
    ), f"{address} in {within}"


def test_what_a_tunnel_cannot_carry_names_neither_the_address_nor_the_tunnel() -> None:
    """The clause is about the tunnel's shape and quotes no value at all.

    Its caller composes a refusal an operator reads about addresses other people hold,
    and the tunnel is already named in that sentence. A clause repeating either is a
    second place a held address can appear verbatim — which is the one record this
    project does not keep.
    """
    for address, within in (
        ("10.66.0.1", "10.66.0.1/24"),
        ("10.66.0.0", "10.66.0.1/24"),
        ("10.66.0.255", "10.66.0.1/24"),
        ("10.67.0.2", "10.66.0.1/24"),
    ):
        problem = carriage_problem(address, within)
        assert problem is not None
        assert address not in problem, problem
        assert within not in problem, problem
        assert "10.66.0." not in problem, problem


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
