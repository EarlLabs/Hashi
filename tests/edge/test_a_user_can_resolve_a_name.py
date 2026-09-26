"""A user's device has somewhere to send a lookup — M23.

WHAT: the ``DNS`` line in the configuration file a user imports, where its value comes
      from, and what the file says when there is no value to write.
WHY:  measured on the owner's real leaf on 2026-09-14, with two real clients:

          $ nslookup example.com       ;; connection timed out; no servers could be reached
          $ ip route get 10.129.0.2    10.129.0.2 dev awg0 table 51820 src 10.99.7.2

      Handshake green, exit at the leaf confirmed, five megabytes downloaded by each
      user — and not one name resolved, for both of them, identically. The config
      carried no ``DNS`` line and ``AllowedIPs = 0.0.0.0/0, ::/0``, so every address went
      into the tunnel INCLUDING the resolver the device already used, which on that
      network was a private address unreachable from Amsterdam.

      And the file said the opposite, on purpose: *"this device keeps its own resolver,
      and its queries do not go through the tunnel"*. ``ip route get`` disproved the
      second half for every destination. A config that explains itself incorrectly is
      worse than one that says nothing, so both halves are asserted here — that a
      resolver is written when there is one, and that the absence is described truthfully
      when there is not.
HOW:  pure renders over the family DERIVED from what a transport declares — the set that
      serialises a user's material into a config FILE. Every address is from a
      documentation range.

What this does NOT prove is that a name resolves. That is a field observation with a real
client on a real network, and no assertion here stands in for it.
"""

import dataclasses

import pytest

from edge.egress import EgressNotRenderable, client_resolvers
from edge.registry import SubscriptionFormat, discover, profile

# Derived the way tests/edge/test_golden_configs.py derives it: the transports that hand
# a user a whole file. Never a hardcoded transport name.
CONFIG_FILE_TRANSPORTS = sorted(
    name
    for name, meta in discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
)

DIRECTIVE = "DNS = "

# The route that makes a missing resolver fatal rather than merely unset: everything the
# device sends goes into the tunnel, which is the charter's point and not a bug to fix by
# narrowing it.
ROUTES_EVERYTHING = "AllowedIPs = 0.0.0.0/0, ::/0"

# A second documentation resolver, used only to show the value tracks the record.
ANOTHER_RESOLVER = "198.51.100.53"

# The sentence the real leaf disproved, kept here as the exact text it must never say
# again. Not a synonym: this is the claim that was made, and re-introducing it in these
# words is the regression being guarded.
THE_CLAIM_THAT_WAS_FALSE = "keeps its own resolver"


def rendered(name: str, node, request, **params_overrides) -> str:
    """One user's configuration file, for the first fixture credential."""
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    params = transport.validate({**fixture(name, "params"), **params_overrides})
    return transport.profile.render_client_config(
        node, params, fixture(name, "credentials")[0]
    ).content


def prose(config: str) -> str:
    """Every comment in the file as one line of running text.

    The templates wrap at eighty columns, so a sentence a user reads as one sentence is
    several lines in the bytes. Asserting on the raw text would make these tests pass or
    fail on where a word happened to wrap, which is not the property — what the file SAYS
    is.
    """
    return " ".join(
        line.lstrip("#").strip() for line in config.splitlines() if line.startswith("#")
    )


def resolvers_in(config: str) -> list[str]:
    """The addresses the ``DNS`` line names, or an empty list when there is no line."""
    for line in config.splitlines():
        if line.startswith(DIRECTIVE):
            return [entry.strip() for entry in line[len(DIRECTIVE):].split(",")]
    return []


# --- there is a resolver, and it comes from the operator's own record ----------------

@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_users_config_names_the_resolver_the_node_record_holds(
    name: str, node, request
) -> None:
    """The fallback, and the one an operator actually reaches for.

    The owner set the node's resolver during the walk and the rendered file was
    byte-identical afterwards — the field existed, the panel offered it, and nothing
    user-facing read it. It is the same question M16 already answered for this node
    ("where are the names this node's traffic asks for looked up"), asked one consumer
    further out, so it gets the same answer rather than a second field to keep in step.
    """
    assert resolvers_in(rendered(name, node, request)) == [node.resolver]


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_transports_own_setting_wins_over_the_nodes(name: str, node, request) -> None:
    """Most specific first, and all of them, in the order the operator gave.

    ``client_dns`` is per node × transport, so an operator who answered it has said
    something more particular than the node's record does and must not be overruled by
    it. Two values rather than one, because a renderer that wrote only the first would
    take a user's fallback resolver away with nobody noticing.
    """
    chosen = (ANOTHER_RESOLVER, "203.0.113.53")

    config = rendered(name, node, request, client_dns=chosen)

    assert resolvers_in(config) == list(chosen)


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_resolver_is_never_a_value_this_project_chose(
    name: str, node, request
) -> None:
    """``CLAUDE.md``: a hardcoded address is one the fleet could never rotate away from.

    Asserted by moving the record and watching the file follow, which a constant — or a
    "sensible default" written in when the record is empty — could not survive.
    """
    moved = dataclasses.replace(node, resolver=ANOTHER_RESOLVER)

    assert resolvers_in(rendered(name, moved, request)) == [ANOTHER_RESOLVER]
    assert resolvers_in(rendered(name, node, request)) == [node.resolver]


# --- there is none, and the file says so truthfully ----------------------------------

@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_config_with_no_resolver_anywhere_says_what_that_costs(
    name: str, node, request
) -> None:
    """The lie, pinned as the exact words that may not come back.

    Nobody can write a resolver the operator has not given — there is no default and
    there may not be one — so the only honest thing left is to say what the user is
    holding. The file used to say the opposite as a deliberate reassurance, and the
    reassurance is what made the failure hard to find: the user reads that their
    lookups stay at home, so nothing about the tunnel looks responsible.
    """
    config = rendered(name, dataclasses.replace(node, resolver=None), request)

    assert resolvers_in(config) == []
    assert ROUTES_EVERYTHING in config, "the file no longer routes everything"
    said = prose(config)
    assert THE_CLAIM_THAT_WAS_FALSE not in said, (
        "the file tells a user their own resolver stays outside a tunnel that routes "
        "every address into it"
    )
    assert "no name will resolve" in said, (
        "the file leaves the user to discover the consequence from nslookup"
    )


@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_answer_is_never_a_narrower_route(name: str, node, request) -> None:
    """The fix that would have been wrong, refused in advance.

    Keeping the device's own resolver reachable by leaving its network outside
    ``AllowedIPs`` is a split tunnel, and the charter's whole point is that a user's
    traffic exits abroad. So the route stays wide in every branch, and the resolver is
    what changes.
    """
    for policy in ({}, {"client_dns": (ANOTHER_RESOLVER,)}):
        assert ROUTES_EVERYTHING in rendered(name, node, request, **policy)
    assert ROUTES_EVERYTHING in rendered(
        name, dataclasses.replace(node, resolver=None), request
    )


# --- and one resolver is worse than none ---------------------------------------------

@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_a_resolver_inside_the_tunnels_own_range_is_refused(
    name: str, node, request
) -> None:
    """Every address in that range is one a user's device holds.

    So a resolver there sends every user's lookups to whichever person was given it —
    the one record this project must never create, produced by a field nobody typed for
    that purpose. The transport's own model already refuses it where it is TYPED; this is
    the value arriving from the node record instead, where nothing had checked it against
    this tunnel.
    """
    transport = profile(name)
    fixture = request.getfixturevalue("transport_fixture")
    params = transport.validate(fixture(name, "params"))
    inside = str(params["peer_tunnel_address"]).split("/")[0]

    with pytest.raises(EgressNotRenderable) as refusal:
        transport.profile.render_client_config(
            dataclasses.replace(node, resolver=inside),
            params,
            fixture(name, "credentials")[0],
        )

    assert inside in str(refusal.value)


def test_a_resolver_that_is_a_name_is_refused() -> None:
    """Resolving it is the very thing the setting is for, so it cannot be a name."""
    with pytest.raises(EgressNotRenderable):
        client_resolvers((), "resolver.example.com", "10.44.0.1/24")


def test_nothing_set_is_nothing_written() -> None:
    """The empty answer is a real state and is not an error — the template describes it."""
    assert client_resolvers((), None, "10.44.0.1/24") == ()
    assert client_resolvers((), "   ", "10.44.0.1/24") == ()


# --- and the operator is told which box this is --------------------------------------

@pytest.mark.parametrize("name", CONFIG_FILE_TRANSPORTS)
def test_the_field_an_operator_fills_in_says_what_it_is_for(name: str) -> None:
    """The panel renders a parameter's own ``description`` and has no other source.

    ``docs/decisions.md`` (2026-09-10) recorded this field as the trap on the hop dialog:
    it is offered there, it does nothing there, and it declared no description, so the box
    explained nothing to the one operator most likely to type in it. The same string is
    what an enable dialog would show the day a box for it exists.
    """
    description = profile(name).params_model.model_fields["client_dns"].description or ""

    assert description.strip(), f"{name}'s client_dns box would say nothing at all"
    assert "hop" in description, "the box does not say where it is inert"
