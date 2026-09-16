"""A parameter's hint is written for the person typing into the box — M26, walk 3.

WHAT: that no field ``description`` a transport declares names an identifier out of this
      codebase, and that the hint on a port box states the range that transport declared.
WHY:  the third acceptance walk met *"the port Xray listens on, inside META.port_range"*
      under the port box on the enable dialog. ``META.port_range`` is an internal symbol —
      the operator cannot open it, cannot guess it, and the range it stands for appeared
      nowhere on the form. A hint that names a variable instead of stating its value tells
      the reader only that somebody knows the answer.

      It is one line in one package, and it is here as a rule rather than a fix because
      the rot is systematic: these strings live beside the validator that enforces them,
      which is exactly where a developer's vocabulary is closest to hand and the
      operator's is furthest away. ``control`` renders every one of them verbatim under
      the box (``services/transports.tuning_field``), so there is no layer between this
      declaration and a person.
HOW:  over every installed transport, through ``discover()`` rather than a list, so a
      transport added later is held to this by arriving. Nothing here names a protocol.

      The identifier pattern is deliberately narrow: a dotted name whose left half is at
      least two characters and carries an uppercase letter or an underscore. That catches
      ``META.port_range``, ``TransportMeta.listens_on`` and ``edge_registry.profile``, and
      leaves alone every sentence a hint legitimately contains — ``e.g.``, ``10.x.y.1/24``,
      ``www.example.com`` and any prose ending a clause with a full stop.

      What it cannot check is whether a sentence is any GOOD. That is a person's
      judgement on a dialog, and no test stands in for it.
"""

import re

import pytest

from edge.registry import discover, profile

# Every (transport, field) pair that declares a hint at all. A field with no description
# is a different finding with its own test (``control``'s console refuses an empty hint),
# so this file says nothing about them.
DESCRIBED_FIELDS = sorted(
    (name, field)
    for name in discover()
    for field, info in profile(name).params_model.model_fields.items()
    if (info.description or "").strip()
)

# A dotted identifier out of this codebase. See the module header for why the left half
# must be two characters and carry an uppercase letter or an underscore.
INTERNAL_NAME = re.compile(r"(?<![\w.])(?=[\w]*[A-Z_])\w{2,}\.[a-z_][\w]*")


def test_this_image_ships_transports_whose_boxes_say_something() -> None:
    """The premise, stated first: without it every assertion below is vacuous."""
    assert DESCRIBED_FIELDS, (
        "no installed transport describes any of its parameters, so nothing here proves "
        "anything about what an operator reads"
    )


@pytest.mark.parametrize(("name", "field"), DESCRIBED_FIELDS)
def test_a_hint_names_no_symbol_the_operator_cannot_open(name: str, field: str) -> None:
    """The walk's own finding, as a rule over every box on every form.

    Red against the previous commit on ``vless-reality.port``, whose hint named
    ``META.port_range`` and never said what it holds.
    """
    described = (profile(name).params_model.model_fields[field].description or "").strip()

    found = INTERNAL_NAME.search(described)

    assert found is None, (
        f"{name}.{field}'s hint says {found.group(0)!r} to the operator typing into the "
        "box — an internal name they cannot open. Say what the value is, not where this "
        "codebase keeps it"
    )


# The one parameter name a transport's listening port is known by on both forms that ask
# for one — ``control.app.services.transports.PORT_FIELD``. Spelled again rather than
# imported, because `edge` may not import `control`; that the two agree is what
# ``control``'s own tests hold, by resolving a real row through this name.
PORT_FIELD = "port"

PORT_HINTS = sorted(
    (name, PORT_FIELD)
    for name in discover()
    if (
        PORT_FIELD in profile(name).params_model.model_fields
        and (
            profile(name).params_model.model_fields[PORT_FIELD].description or ""
        ).strip()
    )
)


def test_this_image_ships_a_transport_that_describes_its_port() -> None:
    """The premise for the test below, which would otherwise pass by having nothing to
    run against."""
    assert PORT_HINTS, (
        "no installed transport describes its port field, so nothing here proves a hint "
        "states the range it is talking about"
    )


@pytest.mark.parametrize(("name", "field"), PORT_HINTS)
def test_a_port_hint_says_the_range_its_transport_declared(name: str, field: str) -> None:
    """The other half of the walk's finding, and the reason the fix was not to delete the
    symbol.

    An operator told the value must be "inside the declared range" is no better off than
    one told it must be inside ``META.port_range``: both say a bound exists and neither
    says what it is. So the sentence carries the numbers — interpolated from the same
    declaration the validator enforces, never typed into a package, which is the rule
    (``CLAUDE.md``: no port is written into code) that put a symbol there to begin with.
    """
    described = (profile(name).params_model.model_fields[field].description or "").strip()
    low, high = profile(name).meta.port_range

    assert str(low) in described and str(high) in described, (
        f"{name}.{field}'s hint talks about where the port may sit and never says "
        f"{low}-{high}, which is what its own transport declared"
    )
