"""What the operator has to type, per transport, and how a form of it is read.

WHAT: ``operator_params(name)`` — the fields a transport requires that `control`
      does NOT mint for the operator — and ``parse_form(name, items)``, which turns a
      flat HTML form into the mapping that transport's model expects.
WHY:  two screens need exactly this list and must not disagree: the "enable a
      transport" form (item 7) and the "replace parameters" form (item 24). When the
      two were computed separately, a transport could offer a field on one screen and
      not the other, and the operator would read that as a bug in the protocol.
HOW:  required fields of the transport's own model, minus every name the transport
      declared as key material — including the public counterpart of a secret, which
      is derived and never typed.

      Nothing here names a protocol or a field. The answer comes from the transport's
      declaration, so a new package under ``edge/transports/`` gets working forms with
      no edit to this file.
"""

import types
import typing
from collections.abc import Iterable, Sequence

from edge.registry import profile

# Container annotations a comma-separated form field should become. ``str`` is a
# Sequence too, which is exactly the confusion this tuple exists to avoid.
_SEQUENCES = (list, tuple, set, frozenset, Sequence)


def operator_params(transport_name: str) -> list[str]:
    """Required fields the operator must supply for ``transport_name``, sorted."""
    transport = profile(transport_name)
    generated = {spec.name for spec in transport.meta.key_material}
    generated |= {
        spec.public_name for spec in transport.meta.key_material if spec.public_name
    }

    return sorted(
        field
        for field, info in transport.params_model.model_fields.items()
        if info.is_required() and field not in generated
    )


def _is_sequence_field(annotation: object) -> bool:
    """Does this field want several values rather than one?"""
    origin = typing.get_origin(annotation) or annotation
    if origin in (typing.Union, types.UnionType):
        return any(_is_sequence_field(arg) for arg in typing.get_args(annotation))
    return isinstance(origin, type) and issubclass(origin, _SEQUENCES) \
        and not issubclass(origin, (str, bytes))


def parse_form(transport_name: str, items: Iterable[tuple[str, str]]) -> dict:
    """Read a flat HTML form into the mapping ``transport_name``'s model expects.

    Two conversions, and both are properties of HTML forms rather than of any
    protocol — which is why they live here and not in a transport:

    * an empty box is dropped, so "leave this alone" is expressible;
    * a field whose model annotation is a sequence becomes a list, split on commas.

    The second one is asked of the MODEL, not guessed from the value. Splitting only
    when a comma happens to be present is the bug this replaced: an operator giving a
    single decoy name typed no comma, got a bare string, and the transport rejected a
    perfectly valid rotation.

    Values are not otherwise coerced. Numbers arrive as strings and the transport's own
    model converts them — duplicating its rules here is how the two drift apart.
    """
    try:
        fields = profile(transport_name).params_model.model_fields
    except KeyError:
        # An unknown transport is a real answer the CALLER must give — "this image does
        # not ship that" — not a parse failure. Hand the values back untouched so the
        # service layer produces that message instead of a traceback from here.
        fields = {}

    parsed: dict[str, object] = {}
    for key, value in items:
        if value == "":
            continue
        info = fields.get(key)
        if info is not None and _is_sequence_field(info.annotation):
            parsed[key] = [part.strip() for part in value.split(",") if part.strip()]
        else:
            parsed[key] = value
    return parsed
