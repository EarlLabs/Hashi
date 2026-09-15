"""A duplicated magic header is refused on the box that repeats — M23, round 3.

WHAT: that the distinctness rule over AmneziaWG's four magic headers attributes its
      refusal to one of the two fields that actually collide, and names the other.
WHY:  measured on the real hosts on 2026-09-15. Every duplicate — init = response,
      transport = underload, init = transport — came back as an error on
      ``transport_packet_magic_header``, because that is where the validator lived and
      Pydantic attributes an error to the field whose validator raised it. On two of
      those three the named box holds the one value the operator got right, and the
      panel draws the message under it: the operator is sent to correct a number that
      is correct while the pair that is wrong says nothing.
HOW:  by provoking each pair through the model, and by comparing the declaration order
      the rule reads against the fields the model actually declares — the one thing
      that can drift, because the validator is applied before ``model_fields`` exists.

Nothing here asserts any header's VALUE, and the refusal must not quote one either:
these four numbers are a node's fingerprint, and a field's refusal is rendered by
surfaces that did not choose to render it.
"""

import pytest
from pydantic import ValidationError

from edge.transports.amneziawg.params import MAGIC_HEADERS, Params


def _refusal(params: dict[str, object]) -> ValidationError:
    with pytest.raises(ValidationError) as raised:
        Params(**params)
    return raised.value


def test_the_rule_reads_the_headers_in_the_order_the_model_declares_them() -> None:
    """The one drift this file exists to catch, asserted before anything depends on it.

    ``MAGIC_HEADERS`` is hand-written because a field validator is applied in the class
    body, where the model's own field list does not exist yet. A fifth header declared
    without being added here would simply never be compared to anything, and every
    assertion below would still pass.
    """
    declared = tuple(
        name for name in Params.model_fields if name.endswith("_magic_header")
    )

    assert MAGIC_HEADERS == declared, (
        "the distinctness rule's list of magic headers no longer matches the ones this "
        "model declares, so at least one of them is compared against nothing"
    )


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        (MAGIC_HEADERS[0], MAGIC_HEADERS[1]),
        (MAGIC_HEADERS[2], MAGIC_HEADERS[3]),
        (MAGIC_HEADERS[0], MAGIC_HEADERS[3]),
    ],
)
def test_a_repeated_header_is_refused_on_the_box_that_repeats_it(
    amneziawg_params: dict[str, object], earlier: str, later: str
) -> None:
    """The finding itself: the refusal lands on the later box and names the earlier one.

    The three pairs are the three the walk provoked. Red against the previous commit on
    the first two, where the field reported was ``transport_packet_magic_header``
    whichever pair collided.
    """
    amneziawg_params[later] = amneziawg_params[earlier]

    refusal = _refusal(amneziawg_params)

    fields = [error["loc"][0] for error in refusal.errors()]
    assert fields == [later], (
        f"a collision between {earlier} and {later} was reported against {fields} — "
        "the operator is sent to a box that may be the one they got right"
    )
    assert earlier in str(refusal), (
        "the refusal does not say which header this one repeats, so the operator has "
        "four boxes and one sentence naming none of them"
    )


def test_the_refusal_does_not_echo_the_value_it_refused(
    amneziawg_params: dict[str, object],
) -> None:
    """A node's fingerprint is not quoted back by a message this zone does not render.

    The same rule ``decoy_host`` and the four field descriptions already follow: the
    hazard is the VALUES being recognisable, so a refusal states which two boxes are
    equal and never what they are equal to.
    """
    amneziawg_params[MAGIC_HEADERS[1]] = amneziawg_params[MAGIC_HEADERS[0]]

    refusal = _refusal(amneziawg_params)

    said = " ".join(error["msg"] for error in refusal.errors())
    assert str(amneziawg_params[MAGIC_HEADERS[0]]) not in said, (
        "the refusal quotes the repeated header's value, which is part of what makes "
        "this node's handshake recognisable"
    )


def test_four_distinct_headers_are_accepted(
    amneziawg_params: dict[str, object],
) -> None:
    """The rule still only refuses a repeat — the case every other test here assumes."""
    model = Params(**amneziawg_params)

    assert len({getattr(model, name) for name in MAGIC_HEADERS}) == len(MAGIC_HEADERS)
