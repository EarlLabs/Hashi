"""What the operator has to type, per transport, and how a form of it is read.

WHAT: ``operator_params(name)`` — the fields a transport requires that `control`
      does NOT mint for the operator — ``parse_form(name, items)``, which turns a
      flat HTML form into the mapping that transport's model expects, and, since M9.2,
      ``hop_transports()``, ``hop_parameters(name)`` and ``hop_tuning(name)``: which
      transports may carry an entry→leaf hop, which of their fields an operator may
      supply, and what each of those boxes should say before it is filled.
WHY:  two screens need exactly this list and must not disagree: the "enable a
      transport" form (item 7) and the "replace parameters" form (item 24). When the
      two were computed separately, a transport could offer a field on one screen and
      not the other, and the operator would read that as a bug in the protocol.
HOW:  required fields of the transport's own model, minus every name the transport
      declared as key material — including the public counterpart of a secret, which
      is derived and never typed.

      ``hop_tuning`` adds one thing on top of that list, and it is the whole of M9's
      "an empty box visibly means use the default": what each box should SAY before
      anybody types in it. The answer is read out of the transport's own declaration
      and is never written here — the default the transport declares, or, when it
      declares none, the shape it says it will accept. See ``tuning_field`` for the
      order those are tried in, and for the one case where the answer comes from
      ``TransportMeta`` rather than from the field.

      Nothing here names a protocol. The answer comes from the transport's own
      declaration, so a new package under ``edge/transports/`` gets working forms with
      no edit to this file. ONE field name appears, and it is the hop contract's
      rather than any protocol's — see ``tuning_field``.
"""

import dataclasses
import types
import typing
from collections.abc import Iterable, Sequence

from pydantic.fields import FieldInfo

from edge.registry import discover, profile

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


# --- hops (M9.2) --------------------------------------------------------------

# The one parameter name this module knows, and it belongs to the HOP CONTRACT rather
# than to any protocol: ``edge.relay.endpoint_of`` builds the address the far end dials
# out of ``params["port"]``, and ``TransportMeta.port_range`` is the transport's own
# statement of what it may listen on. Joining those two is what lets a box that the
# transport itself gives no bounds for still say what it will take. The pre-redesign
# node page has done exactly this since item 7 (``pages/node.html``, in JavaScript);
# this is that line moved to the server, where a test can read it.
PORT_FIELD = "port"


@dataclasses.dataclass(frozen=True, slots=True)
class TuningField:
    """One box in the establish-hop dialog's advanced-tuning disclosure.

    ``default`` is the value the transport itself applies when the box is left empty,
    or ``None`` when it declares none — in which case the parameter must be answered
    and ``placeholder`` says what it will take rather than what it will assume. The two
    are kept apart deliberately: a placeholder that shows a value the transport would
    not actually use is worse than no placeholder at all, because it reads as a promise
    the form does not keep.
    """

    name: str
    placeholder: str
    hint: str
    default: str | None

    @property
    def required(self) -> bool:
        """Whether leaving this box empty refuses the hop rather than defaulting it."""
        return self.default is None


def hop_transports() -> list[str]:
    """Every installed transport that may carry an entry→leaf hop, sorted.

    Two conditions, and neither implies the other. A hop's configuration is consumed as
    a FILE by a node rather than as a link by a phone, which is what
    ``subscription_expressible`` being false has always meant here — offering the URI
    ones would invite the operator to build a tunnel out of a friend-facing link. And
    since item 28 a transport may declare that it cannot carry a hop AT ALL, which is a
    charter constraint rather than a capability: the hop crosses the border by
    definition, so a protocol-blocked transport there would leave both ends configured
    correctly and no tunnel between them. Plain WireGuard is a config file too, so the
    first condition alone would have offered it and the renderer would have refused it
    after the operator had filled in a form.

    Note the overlap this allows, and which is correct: a transport can be on this list
    AND offerable to friends.
    """
    return sorted(
        meta.name
        for meta in discover().values()
        if not meta.subscription_expressible and meta.hop_capable
    )


def hop_parameters(transport_name: str) -> list[str]:
    """Every field of ``transport_name`` an operator may supply, sorted.

    ``operator_params`` minus its ``is_required`` filter, and the difference is the
    whole point rather than a nuance. That filter is right for its own two callers —
    the enable and rotate forms ask what an operator MUST supply — and wrong here: a
    field with a declared default is by definition not required, so filtering on it
    would drop exactly the parameters whose box can honestly promise something. The
    dialog would then show no box at all for a field the transport defaults, and adding
    a default to a transport field would make its box vanish rather than gain a
    placeholder.

    Still minus every name the transport declares as key material, including the public
    counterpart of a secret: those are minted, never typed, and a hop must not become
    the place they surface.
    """
    transport = profile(transport_name)
    generated = {spec.name for spec in transport.meta.key_material}
    generated |= {
        spec.public_name for spec in transport.meta.key_material if spec.public_name
    }
    return sorted(
        field
        for field in transport.params_model.model_fields
        if field not in generated
    )


def hop_tuning(transport_name: str) -> tuple[TuningField, ...]:
    """Every parameter one end of a hop takes, with what its box should say.

    ``hop_parameters`` decides which boxes exist; ``tuning_field`` decides what each of
    them says. The split matters because the two questions fail differently: a missing
    box is a knob the operator cannot reach, and a box with nothing in it is a knob
    they cannot leave alone.

    Note what is NOT filtered here: a parameter a transport happens to ignore at a hop
    end. Nothing declares that machine-readably — the transport says it in a code
    comment — and control guessing it would be control deciding what a protocol does
    with its own field. So it is offered, with the transport's own default in it, which
    is the answer that changes nothing. ``docs/decisions.md`` (2026-09-10) records
    which field this is today, the trap it leaves for an operator who has read that
    journal, and the two ``edge``-side declarations that would close it.
    """
    transport = profile(transport_name)
    fields = transport.params_model.model_fields
    return tuple(
        tuning_field(name, fields[name], transport.meta.port_range)
        for name in hop_parameters(transport_name)
    )


def tuning_field(name: str, info: FieldInfo, port_range: tuple[int, int]) -> TuningField:
    """One box's text, read out of the transport's declaration.

    Two strings, with different jobs, and keeping them apart is the whole of it:

    ``placeholder`` — what an EMPTY box produces, when that is a value. The default the
    transport declares, else the range the field declares, else the range the transport
    declares for its listening port (see ``PORT_FIELD``, the one field name this module
    knows). A placeholder is therefore either a promise the form keeps or a statement
    of what the box will take — never a suggested value the transport would not use,
    which reads as a promise and is not one.

    ``hint`` — the field's own ``description``, always, in full. It sits full-width
    under the row rather than inside the box (see ``.tuning-field`` in app.css): the
    input is 136 characters of nothing at 136px, and a description truncated at
    seventeen characters is guidance the operator cannot read on the two fields most
    easily got wrong.

    A field that declares none of these comes back with both empty, and that is a defect
    in the transport rather than something to paper over here — the console's own test
    refuses it, because a box saying nothing at all is exactly the box an operator
    cannot leave alone.

    **No shipped transport declares a default for a hop parameter today, and none may
    be manufactured here.** Why, field by field, is ``docs/decisions.md`` (2026-09-10),
    which also records that this corrects the plan's M9 line — the short version is that
    a port and an address are values ``CLAUDE.md`` forbids in code, a fleet-wide
    obfuscation value would itself be the fingerprint, and an MTU chosen here would be
    `control` overruling `edge` about a protocol. The order above is what makes that
    correctable elsewhere: the day a transport declares a default, its box promises it
    with no change to this function's callers.
    """
    declared = _declared_default(info)
    description = (info.description or "").strip()
    if declared is not None:
        return TuningField(
            name=name, placeholder=declared, hint=description, default=declared
        )

    bounds = _declared_bounds(info)
    if bounds is None and name == PORT_FIELD:
        bounds = f"{port_range[0]}–{port_range[1]}"
    return TuningField(
        name=name, placeholder=bounds or "", hint=description, default=None
    )


def _declared_default(info: FieldInfo) -> str | None:
    """The transport's own default for a field, as the text a placeholder would show.

    ``None`` for a required field, which is a different answer from "its default is
    empty" and must stay different: one of them means the hop cannot be established
    without an answer and the other means it can.
    """
    if info.is_required():
        return None
    value = info.get_default(call_default_factory=True)
    if value is None:
        return None
    if isinstance(value, (list, tuple, set, frozenset)):
        # A transport's declared "none of these" is a real, documented state — a hop
        # end with no resolvers, say — and it has to read as one rather than as an
        # empty box that was never filled in.
        return ", ".join(str(item) for item in value) or "none"
    return str(value)


def _declared_bounds(info: FieldInfo) -> str | None:
    """A field's declared range as ``low–high``, or the half of it that exists.

    Read off the constraint objects by attribute rather than by importing the library
    that defines them: Pydantic is free to carry its own constraint types here, and a
    duck-typed read keeps working when it does.
    """
    low = high = None
    for constraint in info.metadata:
        for attribute in ("ge", "gt"):
            value = getattr(constraint, attribute, None)
            if value is not None:
                low = value if attribute == "ge" else value + 1
        for attribute in ("le", "lt"):
            value = getattr(constraint, attribute, None)
            if value is not None:
                high = value if attribute == "le" else value - 1
    if low is not None and high is not None:
        return f"{low}–{high}"
    if low is not None:
        return f"{low} or more"
    if high is not None:
        return f"{high} or less"
    return None
