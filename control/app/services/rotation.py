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
from control.app.models import AuditAction, Credential, NodeTransport, TransportPurpose
from control.app.services import apply, audit, keymaterial, nodes, placement, relay
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
    """What was rotated, and whether every node it had to reach accepted it.

    NODES, plural, and that is the shape rather than a generalisation for its own sake:
    one end of a hop cannot be rotated alone (see ``rotate_keys``), so the commonest
    rotation on an entry node writes two rows and has to push two hosts. An outcome that
    could only describe one of them would report half of what happened.

    Keyed by node NAME rather than id, unlike ``RevocationOutcome``: both readers of this
    are composing a sentence for a person — the console's banner and the API's
    ``summary`` — and an id in it tells them nothing they can act on.
    """

    node_transport_id: str
    rotated: list[str] = field(default_factory=list)

    # Nodes that took the push. What is in the database is now on these.
    nodes_updated: list[str] = field(default_factory=list)

    # Node name -> why its push did not land. These are still running what they had.
    nodes_failed: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Every node this rotation had to reach took it.

        ``nodes_updated`` has to be non-empty rather than merely ``not nodes_failed``:
        an outcome is built before the push and returned after it, and "nothing failed
        yet" is not the same claim as "it landed".
        """
        return bool(self.nodes_updated) and not self.nodes_failed

    def summary(self) -> str:
        if self.complete:
            return (
                f"rotated {', '.join(self.rotated)} and pushed to "
                f"{', '.join(self.nodes_updated)}; friends pick it up at their next "
                "refresh, with no action on their part"
            )
        return (
            f"rotated {', '.join(self.rotated)} in the database, but "
            f"{', '.join(sorted(self.nodes_failed))} could NOT be updated: "
            f"{reasons(self.nodes_failed)}. Until then what is in the database is not "
            f"on every node — apply them again from {apply.WHERE_TO_RETRY} once they "
            "can be reached."
        )


def reasons(nodes_failed: dict[str, str]) -> str:
    """Each node that was not updated, with the reason it gave, in a stable order.

    Public because the console composes its own sentence around the same list and must
    not compose this part of it differently — the API envelope and the banner name the
    same nodes for the same reasons.
    """
    return "; ".join(
        f"{node}: {reason.rstrip('.')}" for node, reason in sorted(nodes_failed.items())
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

    ONE END OF A HOP IS NOT ROTATED ALONE. A hop is two rows that render as a pair: the
    far end's configuration is built from this end's public half, and a transport may
    also declare material both ends must hold the same copy of
    (``KeySpec.shared_between_peers``, docs/decisions.md 2026-08-09). So a rotation here
    re-mints this end, copies whatever is declared symmetric into the far end, checks
    that the two still render as a working tunnel, writes BOTH rows in one transaction,
    and pushes both nodes.

    Both rows in one transaction is the part that is not negotiable, and it is why this
    is not merely a reordering of the commit and the push. Until this function did that,
    the rotation was committed at one end and the pair was re-rendered on the way to the
    node — where ``edge.relay`` refused it, out of reach of every handler, so the
    operator was shown a 500 reading "Nothing was changed" over a hop that had just been
    broken. Material committed at one end only is that state on disk; there is no
    sentence that makes it safe.

    Refused rather than half-done, before anything is written: a far end that is gone
    (``relay.peer_of``), and a pair that would not render.
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

    # The far end, read before anything is validated so a half hop is refused rather
    # than re-keyed into one. ``peer_of`` says which of the two it is.
    peer = (
        await relay.peer_of(session, node_transport)
        if node_transport.purpose in TransportPurpose.relays()
        else None
    )
    held = json.loads(node_transport.secrets)
    peer_held = json.loads(peer.secrets) if peer is not None else {}

    # Existing operator-supplied parameters, with the freshly minted values over the
    # top. Validated BEFORE anything is written, so a rotation that would produce an
    # invalid config leaves the node exactly as it was.
    surviving = {
        key: value
        for key, value in node_transport.params.items()
        if key not in minted.params
    }
    # Every secret in play, at both ends: a refusal at either one is composed from a
    # mapping that holds one of them, and a symmetric value is the same string in both.
    withheld = [*minted.secrets.values(), *held.values(), *peer_held.values()]
    validated = _validated(
        transport,
        {**surviving, **minted.params, **minted.secrets},
        transport_name=node_transport.transport_name,
        withholding=withheld,
    )

    peer_validated: dict = {}
    if peer is not None:
        # Only what the transport DECLARED as symmetric crosses to the far end. Its own
        # private half is not re-minted here: rotating this end is about this node's
        # material, and the far end's key was not exposed by anything that happened to
        # this one. Nothing recognises a field by name, so a future transport with a
        # different symmetric value works unchanged — the same loop ``establish_hop``
        # runs when it mints the pair in the first place.
        shared = {}
        for spec in meta.key_material:
            if spec.scope is not KeyScope.NODE or not spec.shared_between_peers:
                continue
            for side in (minted.params, minted.secrets):
                if spec.name in side:
                    shared[spec.name] = side[spec.name]
        peer_validated = _validated(
            transport,
            {**peer.params, **peer_held, **shared},
            transport_name=peer.transport_name,
            withholding=withheld,
        )
        # The pair, rendered from what is about to be written. This is the check that
        # ``edge.relay`` used to make on the way to the node, after the commit.
        relay.check_renders_as_a_pair(
            node_transport, peer, end_params=validated, peer_params=peer_validated
        )

    _store(node_transport, validated, secret_names=set(minted.secrets))
    outcome.rotated.extend(sorted(minted.params) + sorted(minted.secrets))
    if peer is not None:
        _store(peer, peer_validated, secret_names=set(peer_held) | set(minted.secrets))

    if include_clients:
        client_specs = [
            spec for spec in meta.key_material if spec.scope is KeyScope.CLIENT
        ]
        if client_specs:
            held_credentials = await session.execute(
                select(Credential).where(
                    Credential.node_transport_id == node_transport.id
                )
            )
            for credential in held_credentials.scalars().unique():
                fresh = keymaterial.rotate(client_specs, KeyScope.CLIENT)
                subject = fresh.secrets.pop("subject", None) or fresh.params.pop(
                    "subject", None
                )
                if subject:
                    credential.subject = subject
                credential.secrets = json.dumps({**fresh.secrets, **fresh.params})
            outcome.rotated.append("per-friend credentials")

    # Which node and which transport, and nothing about WHAT was rotated: ``outcome``
    # names the fields for the operator who is standing there, and a list of field
    # names in a durable record is a map of which material a transport holds. The far
    # end of a hop gets no entry of its own — one operator action is one entry, and the
    # peer's copy is part of this one change rather than a second one.
    # The node is fetched by id rather than reached through the relationship, for the
    # reason ``friends.grant_everywhere`` gives: eager configuration does not help on a
    # row this session has not loaded, and the lazy read raises.
    audit.record(
        session,
        AuditAction.KEYS_ROTATED,
        first_label=(await nodes.get_node(session, node_transport.node_id)).name,
        second_label=node_transport.transport_name,
    )

    # One commit for both ends. A second commit between them would be exactly the state
    # this function refuses to produce.
    await session.commit()
    logger.info("rotated material on node-transport %s", node_transport.id)

    ends = [node_transport] if peer is None else [node_transport, peer]
    return await _push(session, ends, outcome)


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

    On one end of a hop the pair is re-rendered before the change is written, exactly as
    ``rotate_keys`` does it and for the same reason: a value that leaves the two ends
    unable to form a tunnel is refused here, where the operator still has the form in
    front of them, rather than on the way to the node — where it is not a refusal at all
    but an unhandled failure over a change that has already been committed. Nothing is
    copied to the far end on this path: these are values the operator typed for THIS
    end, and a parameter one end holds is not one the other must.
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

    # A retyped port is a port, and it collides with the node's other transports exactly
    # as a new one does — M15. Excluding this row, because a form resubmitted with the
    # port unchanged must not be refused by its own value. Checked before anything is
    # stored, and this is the ONLY place it is checked on this path: there is no database
    # constraint behind the port rule, deliberately (``services.placement``'s header says
    # why), so a caller that skipped this would write a node that cannot start rather
    # than meet a refusal.
    await placement.port_is_free(
        session,
        node=await nodes.get_node(session, node_transport.node_id),
        transport_name=node_transport.transport_name,
        port=placement.port_of(validated),
        excluding=node_transport.id,
    )

    ends = [node_transport]
    if node_transport.purpose in TransportPurpose.relays():
        peer = await relay.peer_of(session, node_transport)
        relay.check_renders_as_a_pair(
            node_transport,
            peer,
            end_params=validated,
            peer_params={**peer.params, **json.loads(peer.secrets)},
        )
        # Pushed as well as checked: the far end renders the pair too, so its file can
        # change because of a value typed at this one.
        ends.append(peer)

    _store(node_transport, validated, secret_names=set(stored_secrets))
    # The node and the transport, never the parameters: ``changed`` holds the names of
    # the fields the operator retyped and their new values are in ``validated``, and
    # neither a port nor a decoy host belongs in a record that outlives the change.
    # Past the "nothing to change" refusal above, so a form submitted unaltered leaves
    # no entry.
    audit.record(
        session,
        AuditAction.PARAMS_REPLACED,
        first_label=(await nodes.get_node(session, node_transport.node_id)).name,
        second_label=node_transport.transport_name,
    )
    await session.commit()
    logger.info("replaced parameters on node-transport %s", node_transport.id)

    outcome = RotationOutcome(node_transport_id=node_transport.id, rotated=changed)
    return await _push(session, ends, outcome)


def _validated(
    transport, merged: dict, *, transport_name: str, withholding: list
) -> dict:
    """One mapping through the transport's own model, or the rotation path's refusal.

    A function rather than two copies because a hop rotation validates TWO mappings —
    this end's freshly minted material, and the far end's with the symmetric half copied
    into it — and both are refused the same way. What is refused at either end refuses
    the whole rotation, before anything is written.

    ``ParamsRefused`` rather than a plain ``DomainError``, and it matters MORE here than
    on the replacement path: this mapping was validated together with a private key
    minted moments earlier, and a validator's message may quote what it rejected.
    Carrying the complaint per field is what lets a caller decide which of them it may
    print.

    THE MESSAGE ITSELF NAMES THE PARAMETERS AND REPEATS NONE OF THEIR SENTENCES, which
    is the difference between this refusal and the one in ``replace_params`` below. The
    message is the one part of a refusal that every caller renders without choosing to —
    the console draws it as a banner, and ``POST /api/transports/{id}/rotate-keys``
    returns it in the envelope — so on the one path whose mapping holds freshly minted
    material it may not carry words the transport wrote about a value. Nothing is lost
    by that: no field here was offered to the operator to correct, so the actionable
    content is WHICH parameters were refused, and the sentences are still on ``fields``
    for a caller that has somewhere it may safely put them.

    Only the first error travelled before, so a rotation refused on two values reported
    one of them.

    ``relay.refused_fields`` strikes the material out of the sentences as well, so what
    is on ``fields`` is safe for a caller that has somewhere to put it. That is belt and
    braces on this path rather than the whole guard — the message here repeats no
    sentence at all — and it is the same call the replacement path below depends on
    completely. ``withholding`` is every secret in play at both ends of a hop, not only
    the ones in this mapping: passing them costs a line rather than an argument about
    whether a validator could reach one.
    """
    try:
        return transport.validate(merged)
    except ValidationError as exc:
        fields = relay.refused_fields(exc, withholding=withholding)
        raise ParamsRefused(
            f"the rotated parameters are not valid for {transport_name!r} — refused: "
            f"{_named(fields)}. {MATERIAL_NOT_REPEATED}",
            fields=fields,
        ) from exc


def _store(node_transport: NodeTransport, validated: dict, *, secret_names: set) -> None:
    """Split one validated mapping back into the clear column and the encrypted one.

    Which names are secret is the caller's to say: it is what the transport DECLARED as
    secret and minted, plus — at the far end of a hop — what that row already held
    encrypted and is keeping.
    """
    node_transport.params = {
        key: value for key, value in validated.items() if key not in secret_names
    }
    node_transport.secrets = json.dumps(
        {key: value for key, value in validated.items() if key in secret_names}
    )


def _named(fields: dict[str, str]) -> str:
    """The parameters a refusal is about, named and sorted, with no sentence attached.

    A name is safe to print anywhere — it is a field of the transport's own model, and
    it is what tells the operator where to look. The message beside it is not, on the
    path this is used from. Sorted so two refusals about the same parameters read
    identically.
    """
    return ", ".join(sorted(field or WHOLE_MAPPING for field in fields))


async def _push(
    session: AsyncSession, ends: list[NodeTransport], outcome: RotationOutcome
) -> RotationOutcome:
    """Re-render and push every node this rotation touched.

    Failures are recorded on the outcome rather than raised, for the same reason as in
    revocation: the operator needs to know the database and the nodes now disagree,
    which is a different and more urgent fact than "the request failed".

    Through ``apply.apply_many`` — one node's failure never costs the other node's
    outcome, which for a hop is the difference between "the far end is fine" and no
    answer at all. It also contains what escaped this function before: anything a render
    or a push raises that is not a ``DomainError`` was, until now, a 500 over a change
    that had already been committed.
    """
    named = {end.node_id: end.node.name for end in ends}
    for node_id, failure in (await apply.apply_many(session, ends)).items():
        if failure is None:
            outcome.nodes_updated.append(named[node_id])
        else:
            outcome.nodes_failed[named[node_id]] = failure
    if outcome.nodes_failed:
        logger.error(
            "rotation on node-transport %s was not pushed to %d node(s); each is still "
            "running the material it had",
            outcome.node_transport_id,
            len(outcome.nodes_failed),
        )
    return outcome
