"""Rotating what gets blocked — backlog items 23 and 24.

WHAT: re-minting a node-transport's key material (item 23), and replacing a Reality
      decoy or any other operator-supplied parameter (item 24).
WHY:  the charter's job for the owner is "rotate anything that gets blocked, all from
      one admin panel". Rotation is the operation that makes a node survivable without
      being replaced — and it is the one operation that changes what friends' devices
      are currently using, which is why it is not just an UPDATE.
HOW:  every rotation follows the same three steps, and the order is the point:

      1. mint or accept the new values and validate them through the transport's own
         model — before anything is written, so an invalid rotation changes nothing;
      2. write them;
      3. re-render and push every affected node, and report honestly if that failed.

      Step 3 is not optional and not deferred. Between the write and the push, the
      database says one thing and the node is still running the old material — which
      for a key rotation means friends' current configs still work, and for a decoy
      rotation means the blocked decoy is still in use. Either way the operator must be
      told whether the push landed.

Note what rotation deliberately does NOT do: change a friend's subscription URL. Their
token is untouched, so they re-fetch the same link and receive the new material. That
is the whole reason rotation is possible without "a user touching their device".
"""

import json
import logging
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import DomainError, NotFound, ParamsRefused
from control.app.models import Credential, NodeTransport
from control.app.services import apply, keymaterial, relay
from edge.registry import KeyScope, discover, profile

logger = logging.getLogger(__name__)

# Why a rotation's refusal names its parameters and repeats none of their messages.
# The message on a ``ParamsRefused`` is rendered by a caller that never chose to — the
# API's error envelope, and the pre-redesign page's outcome fragment until M9.6 deleted
# it — so the path that validates freshly minted material states the rule there instead,
# exactly as the console does on screen (UI-PATTERNS §9). It is not about which field
# was named: the
# operator's own parameters are validated alongside the new key, so a complaint about
# any of them is a complaint about a mapping that held one.
MATERIAL_NOT_REPEATED = (
    "The transport's own message for each is not repeated here: this check includes "
    "the material just minted for the node, and a refusal can quote the value it "
    "rejected."
)

# What a refusal with no field to its name is called, in the code's own vocabulary.
# Pydantic reports a model-level validator at an empty location, which is a complaint
# about the mapping rather than about any one parameter.
WHOLE_MAPPING = "the parameters as a whole"


@dataclass
class RotationOutcome:
    """What was rotated, and whether the nodes accepted it."""

    node_transport_id: str
    rotated: list[str] = field(default_factory=list)
    node_pushed: bool = False
    failure: str | None = None

    @property
    def complete(self) -> bool:
        return self.node_pushed and self.failure is None

    def summary(self) -> str:
        if self.complete:
            return (
                f"rotated {', '.join(self.rotated)} and pushed to the node; friends pick "
                "it up at their next refresh, with no action on their part"
            )
        return (
            f"rotated {', '.join(self.rotated)} in the database, but the node could NOT "
            f"be updated: {self.failure}. Until it is, the node is still running the OLD "
            f"material — apply the node again from {apply.WHERE_TO_RETRY} once it can be "
            "reached."
        )


async def get_node_transport(session: AsyncSession, node_transport_id: str) -> NodeTransport:
    node_transport = await session.get(NodeTransport, node_transport_id)
    if node_transport is None:
        raise NotFound("no such transport on any node")
    return node_transport


async def rotate_keys(
    session: AsyncSession, *, node_transport_id: str, include_clients: bool = True
) -> RotationOutcome:
    """Re-mint a node-transport's key material — item 23.

    ``include_clients`` also re-mints every friend's per-client material on this
    transport. On by default, and the reasoning matters: rotation is what you do after
    a node may have been compromised, and a node that was compromised may have leaked
    the client credentials it was authenticating. Rotating only the server key would
    leave every friend's identity on that node unchanged.

    Friends' subscription URLs are not touched, so nobody re-imports anything.
    """
    node_transport = await get_node_transport(session, node_transport_id)

    installed = discover()
    meta = installed.get(node_transport.transport_name)
    if meta is None:
        raise DomainError(
            "this node runs a transport that is not installed in this image, so its "
            "material cannot be rotated here"
        )

    transport = profile(node_transport.transport_name)
    outcome = RotationOutcome(node_transport_id=node_transport.id)

    minted = keymaterial.rotate(meta.key_material, KeyScope.NODE)
    if not minted.params and not minted.secrets:
        raise DomainError(
            f"transport {node_transport.transport_name!r} declares no node-scoped key "
            "material, so there is nothing to rotate"
        )

    # Existing operator-supplied parameters, with the freshly minted values over the
    # top. Validated BEFORE anything is written, so a rotation that would produce an
    # invalid config leaves the node exactly as it was.
    surviving = {
        key: value
        for key, value in node_transport.params.items()
        if key not in minted.params
    }
    merged = {**surviving, **minted.params, **minted.secrets}
    try:
        validated = transport.validate(merged)
    except ValidationError as exc:
        # ``ParamsRefused`` rather than a plain ``DomainError``, and it matters MORE
        # here than on the replacement path: this mapping was validated together with
        # the private key minted three lines up, and a validator's message may quote
        # what it rejected. Carrying the complaint per field is what lets a caller
        # decide which of them it may print.
        #
        # THE MESSAGE ITSELF NAMES THE PARAMETERS AND REPEATS NONE OF THEIR SENTENCES,
        # which is the difference between this raise and the one in ``replace_params``
        # below. The message is the one part of a refusal that every caller renders
        # without choosing to — the console draws it as a banner, and
        # ``POST /api/transports/{id}/rotate-keys`` returns it in the envelope — so
        # on the one path whose mapping holds freshly minted material it may not carry
        # words the transport wrote about a value. Nothing is lost by that: no field
        # here was offered to the operator to correct, so the actionable content is
        # WHICH parameters were refused, and the sentences are still on ``fields`` for a
        # caller that has somewhere it may safely put them.
        #
        # Only the first error travelled before, so a rotation refused on two values
        # reported one of them.
        #
        # ``relay.refused_fields`` strikes the material out of the sentences as well, so
        # what is on ``fields`` is safe for a caller that has somewhere to put it. That
        # is belt and braces on this path rather than the whole guard — the message here
        # repeats no sentence at all — and it is the same call the replacement path
        # below depends on completely. Both the freshly minted secrets and the ones the
        # row still holds: the second set is not in ``merged``, and passing it costs a
        # line rather than an argument about whether a validator could reach it.
        fields = relay.refused_fields(
            exc,
            withholding=[
                *minted.secrets.values(),
                *json.loads(node_transport.secrets).values(),
            ],
        )
        raise ParamsRefused(
            f"the rotated parameters are not valid for "
            f"{node_transport.transport_name!r} — refused: {_named(fields)}. "
            f"{MATERIAL_NOT_REPEATED}",
            fields=fields,
        ) from exc

    secret_keys = set(minted.secrets)
    node_transport.params = {k: v for k, v in validated.items() if k not in secret_keys}
    node_transport.secrets = json.dumps(
        {k: v for k, v in validated.items() if k in secret_keys}
    )
    outcome.rotated.extend(sorted(minted.params) + sorted(minted.secrets))

    if include_clients:
        client_specs = [
            spec for spec in meta.key_material if spec.scope is KeyScope.CLIENT
        ]
        if client_specs:
            held = await session.execute(
                select(Credential).where(
                    Credential.node_transport_id == node_transport.id
                )
            )
            for credential in held.scalars().unique():
                fresh = keymaterial.rotate(client_specs, KeyScope.CLIENT)
                subject = fresh.secrets.pop("subject", None) or fresh.params.pop(
                    "subject", None
                )
                if subject:
                    credential.subject = subject
                credential.secrets = json.dumps({**fresh.secrets, **fresh.params})
            outcome.rotated.append("per-friend credentials")

    await session.commit()
    logger.info("rotated material on node-transport %s", node_transport.id)

    return await _push(session, node_transport, outcome)


async def replace_params(
    session: AsyncSession, *, node_transport_id: str, params: dict
) -> RotationOutcome:
    """Replace operator-supplied parameters — item 24's mechanism.

    The decoy-rotation case (a Reality decoy that has been blocked or has changed its
    TLS fingerprint) is just this with ``decoy_host`` in ``params`` — which is why there
    is no ``rotate_decoy`` function. A function named after one protocol's field would
    be a branch on that protocol; this one knows only that the transport validates its
    own parameters.

    Existing key material is PRESERVED. Replacing a decoy must not silently re-key the
    node: those are two different operations with two different consequences for
    friends, and conflating them means an operator changing a hostname cannot predict
    what happens.
    """
    node_transport = await get_node_transport(session, node_transport_id)

    if node_transport.transport_name not in discover():
        raise DomainError(
            "this node runs a transport that is not installed in this image, so its "
            "parameters cannot be validated here"
        )

    transport = profile(node_transport.transport_name)
    stored_secrets = json.loads(node_transport.secrets)

    merged = {**node_transport.params, **params, **stored_secrets}
    try:
        validated = transport.validate(merged)
    except ValidationError as exc:
        # Kept PER FIELD as well as flattened into the sentence, exactly as
        # ``relay.establish_hop`` does it and for the same reason: a caller with a box
        # per parameter has somewhere to put "this one, this reason", and one sentence
        # naming a field the operator then has to hunt for is what a rotation cannot
        # afford. Only the first error used to travel at all, so a form refused on two
        # values reported one of them.
        #
        # Never the VALUES of the merged mapping: it holds this node's decrypted key
        # material, and ``relay.refused_fields`` is what makes that true rather than
        # hoped for. Every stored secret is struck out of every sentence HERE, while the
        # values are still in scope — which is what lets the MESSAGE below repeat the
        # transport's complaints at all.
        #
        # The reason it may is not the one this comment used to give. That argument was
        # "every field a caller can act on is a value the operator has just typed", and
        # it was untrue of ``problems``, which is built from ALL of ``fields``: a
        # model-level validator quoting the mapping, or a ``field_validator`` on a real
        # box reading the rest of it through ``info.data``, put the node's private key
        # into the API envelope — and, until M9.6 deleted it, into the pre-redesign
        # page's outcome fragment.
        # The sentences are safe because the VALUES WERE REMOVED, not because of who
        # typed what — ``docs/decisions.md`` (2026-09-10).
        #
        # Which of these complaints may be PRINTED is still decided by the caller, which
        # knows which fields it has boxes for. That allow-list stays; it is now the
        # second line of defence rather than the only one.
        #
        # Reached across modules rather than copied, the way ``relay._plainly`` was and
        # for the same reason M9.2 gave when it wrote that one: two definitions of what
        # a refusal may say is how one of them stops being updated. The hop path raises
        # its own exception type through the very same function.
        fields = relay.refused_fields(exc, withholding=stored_secrets.values())
        problems = "; ".join(f"{where}: {message}" for where, message in fields.items())
        raise ParamsRefused(
            f"transport {node_transport.transport_name!r} rejected these parameters — "
            f"{problems}",
            fields=fields,
        ) from exc

    changed = sorted(
        key for key in params if node_transport.params.get(key) != validated.get(key)
    )
    if not changed:
        raise DomainError("nothing to change — those values are already in place")

    secret_keys = set(stored_secrets)
    node_transport.params = {k: v for k, v in validated.items() if k not in secret_keys}
    node_transport.secrets = json.dumps(
        {k: v for k, v in validated.items() if k in secret_keys}
    )
    await session.commit()
    logger.info("replaced parameters on node-transport %s", node_transport.id)

    outcome = RotationOutcome(node_transport_id=node_transport.id, rotated=changed)
    return await _push(session, node_transport, outcome)


def _named(fields: dict[str, str]) -> str:
    """The parameters a refusal is about, named and sorted, with no sentence attached.

    A name is safe to print anywhere — it is a field of the transport's own model, and
    it is what tells the operator where to look. The message beside it is not, on the
    path this is used from. Sorted so two refusals about the same parameters read
    identically.
    """
    return ", ".join(sorted(field or WHOLE_MAPPING for field in fields))


async def _push(
    session: AsyncSession, node_transport: NodeTransport, outcome: RotationOutcome
) -> RotationOutcome:
    """Re-render and push the node this transport lives on.

    Failures are recorded on the outcome rather than raised, for the same reason as in
    revocation: the operator needs to know the database and the node now disagree, which
    is a different and more urgent fact than "the request failed".
    """
    try:
        await apply.apply_node(session, node_id=node_transport.node_id)
        outcome.node_pushed = True
    except DomainError as exc:
        outcome.failure = exc.message
        logger.error(
            "rotation on node-transport %s was not pushed; the node still runs the old "
            "material",
            node_transport.id,
        )
    return outcome
