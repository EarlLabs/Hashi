"""The hop form fills in the boxes that must match — M26, the second walk.

WHAT: that the establish-hop dialog opens with a value already in every box the chosen
      transport declares both ends must carry identically, that the two ends get the
      SAME value, that two hops get DIFFERENT ones, that a hop can be established from
      what the form arrived with, and that nothing else on the form is filled in.
WHY:  the walk prepared two bare hosts with one command each, registered both, enabled a
      friend-facing transport on the entry — and then ran out of action budget inside
      this dialog's advanced tuning, which wanted eleven parameters per end with no
      defaults. The milestone's fourth "done when" was not reached because of an empty
      box. Four of those boxes per end are obfuscation magic headers that must be typed
      IDENTICALLY at both ends, and round 1 had just made ``edge.relay`` refuse a pair
      that disagrees — so the product was inviting a typo and then refusing it.
HOW:  through the real dialog and the real POST, because what has to hold is a property
      of the page an operator actually meets: the values it arrives with, submitted
      unchanged, establish a hop. A test that asked the service for a mapping would pass
      on a form that never rendered them.

      Boundary: nothing here says the numbers are good obfuscation, and nothing can — a
      value's worth against a censor is a field observation. What it holds is that they
      are per hop, drawn rather than typed, and identical where identical is required.
"""

import re

import pytest

from control.app.services import transports
from edge.registry import profile

HOP_TRANSPORT = "amneziawg"
HTMX = {"HX-Request": "true"}

# What the transport itself says must match at both ends. Read from the declaration, not
# written down: a transport that adds a fifth matched parameter is covered by adding it,
# and one that drops all four turns this file into a set of vacuous truths — which the
# first test below refuses outright.
MATCHED = profile(HOP_TRANSPORT).meta.hop_matched_params


@pytest.fixture
def hop_params() -> dict[str, object]:
    """The half of one hop end an operator still types, with the matched four left out.

    Deliberately missing the magic headers: what the form supplies is what this fixture
    does not, and a test that supplied them itself would prove nothing about the form.
    """
    return {
        "port": 51820,
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
    }


async def two_nodes(client) -> tuple[str, str]:
    """An entry node and a leaf node, both draft. RFC 5737 addresses, never dialled."""
    ids = []
    for name, address, label in (
        ("entry-ru", "192.0.2.20", "Russia"),
        ("leaf-nl", "192.0.2.10", "Netherlands"),
    ):
        created = await client.post(
            "/api/nodes",
            json={"name": name, "address": address, "location_label": label},
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    return ids[0], ids[1]


def value_in(page: str, field: str) -> str | None:
    """What the dialog put in one box, read off the markup the operator is served.

    Off the page rather than off the service, because the claim is about the form: a
    value the service minted and the template dropped is exactly the failure this file
    exists to catch.
    """
    match = re.search(
        rf'<input[^>]*name="{re.escape(field)}"[^>]*value="([^"]*)"', page
    )
    if match is None:
        match = re.search(
            rf'<input[^>]*value="([^"]*)"[^>]*name="{re.escape(field)}"', page
        )
    return match.group(1) if match else None


async def test_this_transport_still_declares_parameters_that_have_to_match(
    client,
) -> None:
    """The premise, asserted first, because everything below is vacuous without it."""
    assert MATCHED, (
        f"{HOP_TRANSPORT} no longer declares any parameter both ends must carry "
        "identically, so every assertion in this file passes by having nothing to check"
    )


async def test_both_ends_open_with_the_same_value_in_every_matched_box(client) -> None:
    """One draw, written into both ends.

    Red before this change: both boxes were empty and the operator typed the number
    twice, which is the mistake ``edge.relay`` was taught to refuse in round 1.
    """
    await two_nodes(client)

    page = (await client.get("/panel/hops/new")).text

    for field in MATCHED:
        entry = value_in(page, f"entry-{field}")
        leaf = value_in(page, f"leaf-{field}")
        assert entry, f"entry-{field} arrived empty, so it is still typed by hand"
        assert entry == leaf, (
            f"{field} arrived with {entry!r} at the entry and {leaf!r} at the leaf — a "
            "hop whose ends disagree about this comes up and carries nothing"
        )


async def test_the_values_differ_from_each_other(client) -> None:
    """Within one set, because a transport can refuse a set that collides.

    AmneziaWG's four headers must be distinct — two equal ones make two message types
    indistinguishable — so a form that drew the same number twice would arrive already
    refused by the very rule it exists to spare the operator.
    """
    await two_nodes(client)

    page = (await client.get("/panel/hops/new")).text
    drawn = [value_in(page, f"entry-{field}") for field in MATCHED]

    assert len(set(drawn)) == len(drawn), f"two boxes arrived with one number: {drawn}"


async def test_two_hops_are_not_given_the_same_numbers(client) -> None:
    """Per hop, never fleet-wide — the difference between a minted value and a default.

    ``CLAUDE.md``'s shared-decoy rule, generalised and applied to the one place this
    product could have broken it by being helpful: a set of numbers every hop borrows is
    the signature the fleet is enumerable by.
    """
    await two_nodes(client)

    first = (await client.get("/panel/hops/new")).text
    second = (await client.get("/panel/hops/new")).text

    for field in MATCHED:
        assert value_in(first, f"entry-{field}") != value_in(second, f"entry-{field}"), (
            f"{field} is the same number on two openings of this dialog, so it is a "
            "fleet-wide constant rather than a value drawn for one hop"
        )


async def test_a_hop_can_be_established_from_what_the_form_arrived_with(
    client, session, hop_params
) -> None:
    """The whole claim, end to end, and the reason this file drives the real page.

    Everything the operator did not type comes from the dialog; everything they did is
    the fixture. If the minted values were wrong in any way the transport cares about —
    out of range, colliding, disagreeing between the ends — this is where it shows,
    because ``edge.relay`` and the transport's own model both run.
    """
    from control.app.services import relay

    entry_id, leaf_id = await two_nodes(client)
    page = (await client.get("/panel/hops/new")).text

    form = {
        "entry_node_id": entry_id,
        "leaf_node_id": leaf_id,
        "transport_name": HOP_TRANSPORT,
    }
    for side, own, far in (("entry", "10.44.0.1/24", "10.44.0.2/24"),
                           ("leaf", "10.44.0.2/24", "10.44.0.1/24")):
        for key, value in hop_params.items():
            form[f"{side}-{key}"] = str(value)
        form[f"{side}-tunnel_address"] = own
        form[f"{side}-peer_tunnel_address"] = far
        for field in MATCHED:
            form[f"{side}-{field}"] = value_in(page, f"{side}-{field}")

    created = await client.post("/panel/hops", data=form, headers=HTMX)

    assert created.status_code == 200, created.text
    assert len(await relay.list_hops(session)) == 1


async def test_a_refusal_gives_the_operator_their_own_numbers_back(
    client, hop_params
) -> None:
    """A re-render must not draw again.

    Replacing what somebody typed while telling them one of their boxes is wrong is how
    a form loses an operator's trust — and on this form it would also silently undo a
    matched pair they had deliberately chosen.
    """
    entry_id, _ = await two_nodes(client)
    chosen = {field: str(4096 + index) for index, field in enumerate(MATCHED)}

    form = {
        "entry_node_id": entry_id,
        # Its own exit, which ``relay`` refuses about the PAIR — so the dialog comes
        # back with everything in it rather than with one field marked.
        "leaf_node_id": entry_id,
        "transport_name": HOP_TRANSPORT,
    }
    for side, own, far in (("entry", "10.44.0.1/24", "10.44.0.2/24"),
                           ("leaf", "10.44.0.2/24", "10.44.0.1/24")):
        for key, value in hop_params.items():
            form[f"{side}-{key}"] = str(value)
        form[f"{side}-tunnel_address"] = own
        form[f"{side}-peer_tunnel_address"] = far
        for field, value in chosen.items():
            form[f"{side}-{field}"] = value

    refused = await client.post("/panel/hops", data=form, headers=HTMX)

    assert refused.status_code == 422, refused.status_code
    for field, value in chosen.items():
        assert value_in(refused.text, f"entry-{field}") == value, (
            f"the refusal redrew {field} over the number the operator had typed"
        )


async def test_nothing_the_transport_did_not_declare_matched_is_filled_in(
    client,
) -> None:
    """The boxes that stay empty, and the form's own account of why.

    A port, a tunnel address and an MTU are properties of these hosts and of this path;
    the junk sizes carry a rule between two of them that no generic draw can honour. A
    value invented for any of them would be either a fleet-wide constant or a form that
    arrives already refused, and the dialog says so rather than leaving a blank box
    looking like an oversight.
    """
    await two_nodes(client)
    unmatched = [
        box.name
        for box in transports.hop_tuning(HOP_TRANSPORT)
        if box.name not in MATCHED
    ]

    page = (await client.get("/panel/hops/new")).text

    assert unmatched, "this transport has no unfilled parameters left to check"
    for field in unmatched:
        assert not value_in(page, f"entry-{field}"), (
            f"{field} arrived with a value the transport never declared shareable"
        )
    said = " ".join(page.split())
    assert "empty because nothing here can know them" in said, (
        "the form leaves boxes blank and does not say why, which reads as an oversight"
    )
