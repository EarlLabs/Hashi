"""The boxes that decide whether this fleet is enumerable say so — M23, round 1's item 9.

WHAT: that every obfuscation header a transport asks an operator for declares a
      ``description``, that the sentence says the value belongs to THIS node, and that no
      such field declares a default.
WHY:  measured on the owner's live hop on 2026-09-14. Its four headers were

          h1: 1431655765  h2: 1717986918  h3: 2004318071  h4: 2290649224

      — the upstream project's published example set, typed by hand, directly beneath the
      rendered file's own comment saying that shared values would themselves be the
      fingerprint. The product does not default them and never has; what it did was ask
      for four numbers and say nothing about them, while ``decoy_host`` — the same hazard
      one layer up — has carried *"per-node decoy site; never a project default"* since
      it was written. A box that says nothing is where an operator reaches for the
      documentation's example.
HOW:  over every installed transport, and by the SUFFIX rather than by a list of four
      names, so a transport that grows a fifth header is held to this by arriving. It is
      not derived from a declaration because there is none to derive it from: nothing in
      ``TransportMeta`` says "this field is part of the fingerprint". That declaration is
      what would let the CONSOLE mark such a box, and it is a milestone rather than a
      line — recorded here so the next person reads the limit rather than rediscovering
      it.

What this does NOT prove is that any node's values are actually distinct from another's.
Nothing in this zone can see a second node, and the values themselves live in `control`'s
database — the product's half of that finding is the sentence on the box, and the owner's
half is rotating the live ones.
"""

import pytest

from edge.registry import discover, profile

# What makes a field one of them. The protocol's own naming, and the only thing available:
# these four are named for the message type each replaces.
HEADER_SUFFIX = "_magic_header"

OBFUSCATION_HEADERS = sorted(
    (name, field)
    for name in discover()
    for field in profile(name).params_model.model_fields
    if field.endswith(HEADER_SUFFIX)
)


def test_this_image_ships_a_transport_with_obfuscation_headers() -> None:
    """The premise, stated first: without it every assertion below is vacuous."""
    assert OBFUSCATION_HEADERS, (
        "no transport in this image asks for an obfuscation header, so nothing here "
        "proves that such a box warns about anything"
    )


@pytest.mark.parametrize(("name", "field"), OBFUSCATION_HEADERS)
def test_an_obfuscation_header_box_says_the_value_belongs_to_this_node(
    name: str, field: str
) -> None:
    """The box carries the warning, because the box is where the value is chosen.

    Red against the previous commit: the four fields declared no ``description`` at all,
    so both forms that draw them rendered a box with a bare range under it.
    """
    described = (profile(name).params_model.model_fields[field].description or "").strip()

    assert described, f"{name}.{field} has no hint, so its box says nothing at all"
    assert "THIS node" in described, (
        f"{name}.{field} does not say the value is this node's own: {described}"
    )
    assert "fleet" in described, (
        f"{name}.{field} does not say what a shared value costs the fleet: {described}"
    )


@pytest.mark.parametrize(("name", "field"), OBFUSCATION_HEADERS)
def test_no_obfuscation_header_declares_a_default(name: str, field: str) -> None:
    """The rule the sentence describes, kept structural as well as written down.

    A default here would be one set of numbers on every node this product ever configures
    — the fleet identified by the thing that exists to hide it, with nobody having typed
    anything. The charter says it of a Reality decoy; it is the same hazard one layer
    down, and the field is required so that an empty box is refused rather than filled in.
    """
    assert profile(name).params_model.model_fields[field].is_required(), (
        f"{name}.{field} declares a default, so every node this image configures could "
        "share one obfuscation value and the fleet becomes enumerable by it"
    )
