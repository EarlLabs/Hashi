"""What the operator has to type, per transport, and how a form of it is read.

WHAT: ``operator_params(name)`` — the fields a transport requires that `control`
      does NOT mint for the operator — ``parse_form(name, items)``, which turns a
      flat HTML form into the mapping that transport's model expects, and, since M9.2,
      ``hop_transports()``, ``hop_parameters(name)`` and ``hop_tuning(name)``: which
      transports may carry an entry→leaf hop, which of their fields an operator may
      supply, and what each of those boxes should say before it is filled. M9.4 adds
      ``replaceable_params(name, current)``, the same question for a transport that is
      already enabled somewhere and is being retyped rather than filled in. M9.5 adds
      ``offerable_transports()`` and ``operator_tuning(name)``: which transports a
      person can be handed at all, and what the box for each of their required fields
      should say — and lifts ``supplied_params(name)`` out of ``hop_parameters``, since
      "every field an operator may supply" is now asked by the enable route too.
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
from collections.abc import Iterable, Mapping, Sequence

from pydantic.fields import FieldInfo

from edge.registry import discover, profile

# Container annotations a comma-separated form field should become. ``str`` is a
# Sequence too, which is exactly the confusion this tuple exists to avoid.
_SEQUENCES = (list, tuple, set, frozenset, Sequence)


def key_material_names(transport_name: str) -> frozenset[str]:
    """Every parameter name of ``transport_name`` that is MINTED rather than typed.

    Both halves: the value the transport declared as material, and — when it is
    asymmetric — the ``public_name`` its public counterpart is delivered under. One
    function because three callers subtract exactly this set and must not disagree
    about it: the two forms an operator fills in, and the refusal path that decides
    whether a transport's own complaint may be printed. A form that subtracted one
    name fewer would ask the operator to type a key.
    """
    material = profile(transport_name).meta.key_material
    return frozenset(
        {spec.name for spec in material}
        | {spec.public_name for spec in material if spec.public_name}
    )


def supplied_params(transport_name: str) -> frozenset[str]:
    """Every field of ``transport_name`` an operator MAY supply, as a set.

    The model's own fields minus everything the transport declares as key material and
    minus every public counterpart of one (``key_material_names``) — so this is the
    widest set a form of ours may accept, and a minted value is not in it whatever a
    caller names in a submission.

    Deliberately WIDER than ``operator_params``, which adds an ``is_required`` filter: a
    field the transport DEFAULTS is one an operator may legitimately answer, and a route
    that only accepted the required ones discarded such an answer in silence. It is the
    same set ``hop_parameters`` has always returned, and it is defined here once so that
    "what may an operator supply" has one answer rather than one per caller.
    """
    generated = key_material_names(transport_name)
    return frozenset(
        field
        for field in profile(transport_name).params_model.model_fields
        if field not in generated
    )


def operator_params(transport_name: str) -> list[str]:
    """Required fields the operator must supply for ``transport_name``, sorted."""
    transport = profile(transport_name)
    generated = key_material_names(transport_name)

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

    ``supplied_params`` sorted, and nothing else. That set was lifted out of this
    function when the enable route needed the same question answered for a node rather
    than for a hop end; the answer is the same one and it is computed once, so a
    transport cannot offer a field on one form and have it dropped by another.
    """
    return sorted(supplied_params(transport_name))


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


# --- replacing what is already in place (M9.4) --------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ParamBox:
    """One box in the replace-parameters dialog — item 24's form, in the console.

    Deliberately NOT a ``TuningField``. That type's ``required`` is "leaving this empty
    refuses the request", which is the opposite of what an empty box means here: this
    form replaces values that are already in place, so empty means KEEP. Reusing it
    would have put a property on screen that reads backwards.

    ``placeholder`` is the value in place now, written the way this form would take it
    back — which is what makes "leave it empty to keep it" a statement the operator can
    check rather than one they have to trust.
    """

    name: str
    placeholder: str
    hint: str


def replaceable_params(
    transport_name: str, current: Mapping[str, object]
) -> tuple[ParamBox, ...]:
    """Every field an operator may retype on a transport already enabled, with its box.

    The list is ``operator_params`` — the same one the enable form asks for, so a
    transport cannot offer a field on one screen and not the other. That list already
    subtracts everything the transport declares as key material and every public
    counterpart of it (see ``key_material_names``), so **no box on this form can exist
    for a minted value, and no minted value can become a placeholder.** That is the
    charter's rule made structural here rather than checked at the template.

    ``hint`` is the field's own ``description``, in full, exactly as ``hop_tuning``
    renders it. ``placeholder`` is the value the row currently holds; a field with no
    value stored gets an empty box rather than a suggestion, because the one thing this
    placeholder means is "this is what you are replacing".
    """
    fields = profile(transport_name).params_model.model_fields
    return tuple(
        ParamBox(
            name=name,
            placeholder=_as_typed(current.get(name)),
            hint=(fields[name].description or "").strip(),
        )
        for name in operator_params(transport_name)
    )


def _as_typed(value: object) -> str:
    """A stored value as this form would take it back.

    A sequence becomes the comma-separated run ``parse_form`` splits again, so what the
    box shows is what the box accepts. Anything absent is an empty string — never the
    word "None", which an operator would reasonably retype.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(item) for item in value)
    return str(value)


# --- enabling one on a node (M9.5) --------------------------------------------


def offerable_transports() -> list[str]:
    """Every installed transport a user's client could actually receive, sorted.

    The question the "enable a transport" form asks of the image, and the same one
    ``nodes.enable_transport`` refuses on: a transport that declares no format a
    client can consume would be enabled and then silently missing from every
    subscription, so it is refused out loud (charter amendment A, backlog item 7 S2a).
    Offering it and then refusing it is the shape this list exists to prevent — the
    form must not present an action whose only outcome is a refusal.

    Sibling of ``hop_transports`` above and deliberately not merged with it: that one
    answers "may this carry a tunnel between two of our own nodes", this one answers
    "may a person be handed this", and a transport can honestly be on both lists or on
    neither. Nothing here names a protocol; both answers come from what each transport
    declares about itself.
    """
    return sorted(
        meta.name for meta in discover().values() if meta.subscription_formats
    )


def operator_tuning(transport_name: str) -> tuple[TuningField, ...]:
    """Every box the enable form asks for, with what each of them should say.

    ``operator_params`` decides which boxes exist — what an operator MUST supply, which
    is what the pre-redesign page's form has always asked for — and ``tuning_field``
    decides what each of them says, out of the transport's own declaration. Two existing
    answers joined, so the enable form cannot disagree with the replace form about which
    fields are the operator's, nor with the hop dialog about what a box may promise.

    ``TuningField`` and NOT ``ParamBox``, and the difference is the reason M9.4 refused
    to reuse it the other way round: on this form an empty box is REFUSED, exactly as on
    the hop dialog, because nothing is in place yet to keep. Every field here is required
    by construction — ``operator_params`` filters on it — so ``required`` is true of all
    of them, and the placeholder can only ever be the shape the field will accept.

    The narrowing that follows from ``operator_params``, stated rather than discovered:
    a parameter the transport DEFAULTS gets no box here, so it cannot be set while
    enabling. That is parity with the form this replaces and with the replace form
    beside it; ``POST /api/nodes/{id}/transports`` still takes either.
    """
    transport = profile(transport_name)
    fields = transport.params_model.model_fields
    return tuple(
        tuning_field(name, fields[name], transport.meta.port_range)
        for name in operator_params(transport_name)
    )
