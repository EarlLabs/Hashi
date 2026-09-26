"""The box an operator types a pool's first address into says what goes in it — M25.

WHAT: that every transport declaring each consumer needs an address of its own gives
      that parameter a ``description`` which says both what the value MEANS and what it
      LOOKS LIKE — and that it declares no default, which is why the sentence has to
      carry the shape.
WHY:  M25's walk, on the enable dialog. ``peer_tunnel_address`` is required, declares no
      default and has no bounds, so ``TuningField`` has nothing to put in the box's
      placeholder — it renders empty. The sentence under it said what the value was for
      ("the first address given out when this transport is offered to users") and
      never what to type, so an operator meeting the family for the first time had one
      empty box, one sentence about hops, and a refusal that pointed back at the same
      box. The same finding M20 answered for the obfuscation headers, one field over:
      a box that says nothing is where the mistake is made.
HOW:  over every installed transport that declares a ``PeerAddress``, found through the
      declaration rather than through a list of field names — so a transport added later
      is held to this by arriving. Nothing here names a protocol.

It proves a sentence exists and says two particular things. Whether that sentence is
GOOD is a person's judgement on a dialog, and no test stands in for it.
"""

import re

import pytest

from edge.registry import discover, profile

# Every (transport, field) pair where a consumer's own address is typed in. Read off
# ``TransportMeta.peer_address``, which is the same declaration `control` allocates from.
POOLED_ADDRESS_FIELDS = sorted(
    (name, meta.peer_address.name)
    for name, meta in discover().items()
    if meta.peer_address is not None
)


def test_this_image_ships_a_transport_that_hands_out_addresses() -> None:
    """The premise, stated first: without it every assertion below is vacuous."""
    assert POOLED_ADDRESS_FIELDS, (
        "no transport in this image gives each consumer an address of its own, so "
        "nothing here proves that the box for one says anything"
    )


@pytest.mark.parametrize(("name", "field"), POOLED_ADDRESS_FIELDS)
def test_the_box_says_what_shape_the_value_takes(name: str, field: str) -> None:
    """A hint that explains the meaning and not the form leaves an empty box empty.

    Two things, because the operator needs both and the old sentence had only the first:
    that the value is an address carrying a PREFIX — the validator refuses a bare one —
    and an example of that shape to copy. The example is checked as a shape rather than
    quoted, because a real range written into a package would be a range every node in
    the fleet borrows.
    """
    described = (profile(name).params_model.model_fields[field].description or "").strip()

    assert described, f"{name}.{field} has no hint, so its box says nothing at all"
    assert "prefix" in described, (
        f"{name}.{field} does not say the value carries a prefix, which is the half its "
        f"validator refuses on: {described}"
    )
    assert re.search(r"e\.g\.\s*\S+/\d+", described), (
        f"{name}.{field} shows no example of the shape to type, and its box has no "
        f"placeholder to show one either: {described}"
    )


@pytest.mark.parametrize(("name", "field"), POOLED_ADDRESS_FIELDS)
def test_no_pooled_address_declares_a_default(name: str, field: str) -> None:
    """Why the sentence has to carry the shape, kept structural as well as written down.

    A default here would be one tunnel range on every node this product ever configures —
    two nodes handing two people the same address, and a fleet identified by the value
    nobody typed. It is required instead, so an empty box is refused; and because it is
    required with no declared default and no declared bounds, the console has nothing to
    put in its placeholder. The hint is the only thing that box can say.
    """
    assert profile(name).params_model.model_fields[field].is_required(), (
        f"{name}.{field} declares a default, so every node this image configures could "
        "hand out addresses out of one range nobody chose"
    )
