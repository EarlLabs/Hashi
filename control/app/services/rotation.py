"""Rotating what gets blocked — backlog items 23 and 24.

WHAT: re-minting a node-transport's key material (item 23), and replacing a Reality
      decoy or any other operator-supplied parameter (item 24).
WHY:  the charter's job for the owner is "rotate anything that gets blocked, all from
      one admin panel". Rotation is the operation that makes a node survivable without
      being replaced — and it is the one operation that changes what users' devices
      are currently using, which is why it is not just an UPDATE.
HOW:  every rotation follows the same three steps, and the order is the point:

      1. mint or accept the new values and validate them through the transport's own
         model — before anything is written, so an invalid rotation changes nothing;
      2. write them;
      3. re-render and push every affected node, and report honestly if that failed.

      Step 3 is not optional and not deferred. Between the write and the push, the
      database says one thing and the node is still running the old material — which
      for a key rotation means users' current configs still work, and for a decoy
      rotation means the blocked decoy is still in use. Either way the operator must be
      told whether the push landed.

Note what rotation deliberately does NOT do: change a user's subscription URL. Their
token is untouched, so they re-fetch the same link and receive the new material. That
is the whole reason rotation is possible without "a user touching their device".
"""

import json
import logging
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict, DomainError, NotFound, ParamsRefused
from control.app.models import (
    AuditAction,
    Credential,
    Node,
    NodeTransport,
    TransportPurpose,
)
from control.app.services import (
    addresses,
    apply,
    audit,
    keymaterial,
    nodes,
    placement,
    relay,
)
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

# What an operator is told when the tunnel they typed would leave users who are already
# on this transport holding an address it cannot carry — M17.1c. COUNTS and never an
# address: which person holds which address is the one record this project does not keep,
# and this sentence reaches an operator through the API's envelope and the console's
# dialog. It names the action that is refused rather than only the state, because the
# operator's next move is a different range — or taking those people off first.
#
# THE CAUSE IS NAMED PER CASE, and the first version of this sentence did not do that: it
# said "would fall outside {within}" for all five of the conditions ``stranded_by``
# counts, three of which are addresses INSIDE the range — the node's own address, the
# network address and the broadcast address. The worst of those is the one with a victim
# (whoever holds the node's own address is authorised to send as the node), and the
# obvious answer to "falls outside" is a wider prefix, which does not clear it: the
# operator was sent round a loop by a diagnosis that was false. ``edge.carriage_problem``
# writes each clause and names nothing it was handed, so the causes can be stated without
# the sentence ever carrying an address somebody holds.
POOL_WOULD_STRAND = (
    "a tunnel at {within} could not carry addresses already handed out on this "
    "transport: {causes}. Moving an address a device already holds is the one thing this "
    "cannot do — the device is configured with it and nobody is going to reconfigure it. "
    "Nothing has been changed — leave this tunnel where it is, or take them off this "
    "transport first."
)

# What an operator is told when they type a pool size into a hop end's replace dialog —
# M17.1c. A hop is a pair of peers and the far end's single address is what the row's own
# parameter already means there, so a size on such a row is a number that would describe
# nothing. It stands beside ``nodes.POOL_SIZE_NOT_TAKEN`` rather than reusing it: that one
# is about a TRANSPORT that identifies its users by material, and saying it here would be
# untrue of a transport that does hand users addresses on its other row.
POOL_SIZE_NOT_ON_A_HOP = (
    "this row is one end of a hop, and no user holds anything on it — the far end is "
    "another of your own nodes, at the single address this row already names. There is "
    "no pool to size here."
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
                f"{', '.join(self.nodes_updated)}; users pick it up at their next "
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

    ``include_clients`` also re-mints every user's per-client material on this
    transport. On by default, and the reasoning matters: rotation is what you do after
    a node may have been compromised, and a node that was compromised may have leaked
    the client credentials it was authenticating. Rotating only the server key would
    leave every user's identity on that node unchanged.

    Users' subscription URLs are not touched, so nobody re-imports anything.

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
            outcome.rotated.append("per-user credentials")

    # Which node and which transport, and nothing about WHAT was rotated: ``outcome``
    # names the fields for the operator who is standing there, and a list of field
    # names in a durable record is a map of which material a transport holds. The far
    # end of a hop gets no entry of its own — one operator action is one entry, and the
    # peer's copy is part of this one change rather than a second one.
    # The node is fetched by id rather than reached through the relationship, for the
    # reason ``users.grant_everywhere`` gives: eager configuration does not help on a
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
    session: AsyncSession,
    *,
    node_transport_id: str,
    params: dict,
    pool_size: int | None = None,
) -> RotationOutcome:
    """Replace operator-supplied parameters, and the size of the pool — item 24 and M17.1c.

    The decoy-rotation case (a Reality decoy that has been blocked or has changed its
    TLS fingerprint) is just this with ``decoy_host`` in ``params`` — which is why there
    is no ``rotate_decoy`` function. A function named after one protocol's field would
    be a branch on that protocol; this one knows only that the transport validates its
    own parameters.

    Existing key material is PRESERVED. Replacing a decoy must not silently re-key the
    node: those are two different operations with two different consequences for
    users, and conflating them means an operator changing a hostname cannot predict
    what happens.

    On one end of a hop the pair is re-rendered before the change is written, exactly as
    ``rotate_keys`` does it and for the same reason: a value that leaves the two ends
    unable to form a tunnel is refused here, where the operator still has the form in
    front of them, rather than on the way to the node — where it is not a refusal at all
    but an unhandled failure over a change that has already been committed. Nothing is
    copied to the far end on this path: these are values the operator typed for THIS
    end, and a parameter one end holds is not one the other must.

    RESIZING IS THIS, AND NOT AN ACTION OF ITS OWN — M17.1c. ``pool_size`` is how many
    people this row may hand an address to, and it rides here rather than on a
    ``/resize`` endpoint because it is the same operation: the operator is changing what
    this transport is configured to do, it is audited as ``params-replaced``, and the
    node is re-rendered and pushed afterwards exactly as a replaced decoy is. Migration
    ``0006`` promises in writing that a row serving since before M17 is sized by
    replacing that row's parameters; this is that promise. ``None`` leaves the size
    alone, so replacing a blocked decoy on a sized row asks for no number.

    THE ORDER OF THE THREE THINGS IT DOES TO ADDRESSES IS THE WHOLE CORRECTNESS ARGUMENT:

    1. ``addresses.pin_in_use`` writes down the address the row is ALREADY handing out,
       before a single parameter moves. On a pre-M17 row that address exists only as a
       parameter and a fallback, so without this step replacing that parameter moves a
       configured device's address with nothing to notice;
    2. the proposed pool is measured — by ``edge``, through ``nodes.sized_pool``, and
       against every address now in hand, through ``addresses.stranded_by``. The pin is
       first precisely so that the working device's address is one of those measured;
    3. only then is anything stored, and ``addresses.settle`` gives an address to
       everybody still without one — which is what repairs the field's own row: the
       person who arrived second, and has never had an address of their own, gets one.

    Every refusal between the pin and the commit rolls the session back before it leaves,
    because the pin and the store are writes in this transaction and "Nothing has been
    changed" has to be true of the database rather than of the intent.
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

    # The size is one of the things that can change, so it counts as one — otherwise a
    # submission that only widened the pool would be refused as "nothing to change", and
    # a row sized at the same number it already has would be pushed for nothing. Named
    # with the box's own name, and sorted in with the rest so two identical replacements
    # report identically.
    resized = pool_size is not None and pool_size != node_transport.pool_size
    changed = sorted(
        [key for key in params if node_transport.params.get(key) != validated.get(key)]
        + ([addresses.POOL_BOX] if resized else [])
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
    node = await nodes.get_node(session, node_transport.node_id)
    await placement.port_is_free(
        session,
        node=node,
        transport_name=node_transport.transport_name,
        port=placement.port_of(validated),
        excluding=node_transport.id,
    )
    # And the tunnel's own range against every other tunnel on that node — M17.1c, the
    # third path this rule is asked on (the other two are enabling a transport and
    # establishing a hop, both through ``placement.claim``). Excluding this row for the
    # port rule's reason: a form resubmitted with the range unchanged must not be refused
    # by its own value. Before anything is stored, and before the addresses are touched:
    # a range that collides with another interface on the host is refused whether or not
    # anybody holds an address in it yet.
    #
    # ONLY WHEN THE RANGE IS ACTUALLY MOVING, and that is the same carve-out
    # ``nodes.sized_pool``'s ``against_the_fleet`` makes, for the same reason. A node
    # whose two rows already overlap — enabled before this rule existed, which is every
    # node in the field — would otherwise have EVERY replacement on either row refused,
    # with a sentence about a range on a form where the operator retyped a port. That
    # takes away the charter's first job for them (rotate what gets blocked) and the
    # sizing migration 0006 promises them in writing, on a state they cannot otherwise
    # repair: the refusal's own instruction is to give this tunnel a range of its own, and
    # typing one is refused in turn by ``_resize``, because the addresses in hand are in
    # the old one. The only exit left was removing the row, which takes its credentials —
    # or the mandated hop end — with it. Every NEW overlap is still refused: a range that
    # is not moving cannot be the one that created the collision.
    if placement.tunnel_of(
        node_transport.transport_name, validated
    ) != placement.tunnel_of(node_transport.transport_name, node_transport.params):
        await placement.tunnel_network_is_free(
            session,
            node=node,
            transport_name=node_transport.transport_name,
            params=validated,
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

    # EVERYTHING FROM HERE WRITES, so every refusal below rolls back before it leaves.
    # ``_resize`` pins an address and ``settle`` allocates them; both are writes in this
    # transaction, and a caller told "nothing has been changed" over a session holding a
    # pinned address would be told a lie the next commit makes true.
    try:
        await _resize(
            session,
            node_transport=node_transport,
            node=node,
            validated=validated,
            pool_size=pool_size,
        )

        _store(node_transport, validated, secret_names=set(stored_secrets))
        if pool_size is not None:
            node_transport.pool_size = pool_size

        # The node and the transport, never the parameters: ``changed`` holds the names of
        # the fields the operator retyped and their new values are in ``validated``, and
        # neither a port nor a decoy host belongs in a record that outlives the change.
        # The pool size is no different — it is a count of people, which is why it is
        # named in ``changed`` and not recorded here.
        # Past the "nothing to change" refusal above, so a form submitted unaltered leaves
        # no entry.
        audit.record(
            session,
            AuditAction.PARAMS_REPLACED,
            first_label=node.name,
            second_label=node_transport.transport_name,
        )

        # AFTER the store, because the pool it draws from is the one just written. This is
        # the half that repairs rather than merely permits: on a row sized for the first
        # time, everybody who has been waiting without an address of their own is given
        # one here, inside this transaction, so a pool that still cannot hold them refuses
        # the whole replacement instead of committing half a repair.
        #
        # A FULL POOL REFUSES THE SIZING AND NOT THE ROTATION, which is what makes
        # ``sized_pool(against_the_fleet=False)`` above mean anything at all. That
        # carve-out exists so a row whose pool is already smaller than the fleet can still
        # have a blocked value rotated away from it — and on a SERVING row the two
        # conditions are one condition: every active user holds a credential there, so a
        # short pool means credentials without addresses, and ``settle`` raised
        # ``PoolFull`` a few lines later and rolled the whole rotation back. The escape
        # hatch was dead in exactly the state it was written for: the field's own row
        # after migration 0006.
        #
        # Swallowed only when the operator is NOT sizing. Then the size has not changed,
        # so any shortfall is one this replacement did not cause and does not worsen:
        # ``settle`` writes NOTHING when it refuses (its own docstring promises a caller
        # may catch this and go on), so the addresses in hand are exactly as they were.
        # What the operator is still told is the truth by a different route — the push
        # that follows cannot render a row whose users have no address of their own, and
        # ``_push`` reports that node as not updated. A replacement that DOES carry a size
        # is refused as before: somebody asking for a number that cannot hold the row's
        # own people must hear so.
        try:
            await addresses.settle(session, node_transport)
        except addresses.PoolFull:
            if pool_size is not None:
                raise
            logger.info(
                "the pool on node-transport %s is still short after a replacement that "
                "did not size it; nobody new was given an address",
                node_transport.id,
            )

        await session.commit()
    except DomainError:
        await session.rollback()
        raise
    except IntegrityError as exc:
        if "uq_credential_tunnel_address" not in str(exc.orig):
            raise
        # The race the constraint exists for, on this path too: ``settle`` read which
        # addresses were free and somebody else took one before this flush. The loser is
        # refused rather than given a shared address — and it is refused in the SAME words
        # ``users.grant_everywhere`` uses, because it is the same event and an operator
        # meeting it twice must not have to learn two sentences. Without this it would
        # leave as an ``IntegrityError``: a 500, which the console does not swap, so the
        # operator sees a spinner stop and nothing else.
        #
        # Imported here rather than at the top for the reason this module's neighbours
        # give: ``users`` reaches back into these services, and a module-level import
        # both ways is a cycle waiting for its first new call.
        from control.app.services import users  # noqa: PLC0415

        await session.rollback()
        raise Conflict(users.ADDRESS_TAKEN_MEANWHILE) from exc
    logger.info("replaced parameters on node-transport %s", node_transport.id)

    outcome = RotationOutcome(node_transport_id=node_transport.id, rotated=changed)
    return await _push(session, ends, outcome)


async def _resize(
    session: AsyncSession,
    *,
    node_transport: NodeTransport,
    node: Node,
    validated: dict,
    pool_size: int | None,
) -> None:
    """Pin what is already in use, then refuse a pool that could not carry it — M17.1c.

    Split out of ``replace_params`` because it is a rule rather than a step: three
    questions asked in one order, and the order is what the correctness rests on.

    A transport that hands out no address at all is asked nothing and refuses a size, in
    ``nodes.sized_pool``'s own words — the same answer the enable path gives, from the
    same function, so the two surfaces cannot drift about what a pool size means.

    THE SIZE MEASURED IS THE ONE THE ROW WILL HAVE: what the operator typed, or what the
    row already holds when they typed nothing. Asking ``edge`` about it on EVERY
    replacement is the defect M17.1b left behind — the tunnel's own address is an ordinary
    replaceable parameter, so a row could be moved to a different range, or given a longer
    prefix, with the pool never re-measured and the people in it left outside. ``None``
    for a pre-pool row is one address, which is what such a row hands out.

    The fleet question is asked only when the operator is actually sizing — see
    ``nodes.sized_pool``.

    A HOP END IS ASKED NOTHING AND REFUSES A SIZE. The plan's done-when is that hop ends
    are unchanged by this milestone — no address, no pool, the same dialog boxes — and a
    hop end is a row of a transport that DOES declare each consumer needs an address, so
    deciding from the transport's declaration alone put a pool on the runbook's own entry
    box. Nothing downstream reads it (``nodes.serving_transports`` filters on ``USERS``,
    so no user is ever granted there and ``settle`` finds nobody to place), which is
    exactly why it had to be refused here: a number stored on a relay row is a fact about
    that row that is not true, and the fleet refusal it can produce — "every one of them
    is granted a credential here the moment this node serves" — is false of a hop. The two
    addresses on a hop end are judged as a pair by ``relay.check_renders_as_a_pair``,
    which ``replace_params`` calls; the range rule above still applies to it in full.
    """
    if node_transport.purpose in TransportPurpose.relays():
        if pool_size is not None:
            raise ParamsRefused(
                f"transport {node_transport.transport_name!r} on node {node.name!r} "
                f"rejected these parameters — {addresses.POOL_BOX}: "
                f"{POOL_SIZE_NOT_ON_A_HOP}",
                fields={addresses.POOL_BOX: POOL_SIZE_NOT_ON_A_HOP},
            )
        return

    spec = addresses.spec_for(node_transport.transport_name)
    if spec is None:
        if pool_size is not None:
            await nodes.sized_pool(
                session,
                node=node,
                transport_name=node_transport.transport_name,
                params=validated,
                pool_size=pool_size,
            )
        return

    # First, and before a parameter moves: the address this row is already handing out.
    await addresses.pin_in_use(session, node_transport)

    await nodes.sized_pool(
        session,
        node=node,
        transport_name=node_transport.transport_name,
        params=validated,
        pool_size=pool_size if pool_size is not None else node_transport.pool_size or 1,
        against_the_fleet=pool_size is not None,
    )

    within = str(validated[spec.within])
    stranded = await addresses.stranded_by(session, node_transport, within=within)
    if stranded:
        refusal = POOL_WOULD_STRAND.format(within=within, causes=_causes(stranded))
        # UNDER THE BOX THE RANGE IS TYPED IN, not under the pool's size: the size cannot
        # cause this — it is the tunnel that moved out from under the addresses — and a
        # complaint under a number the operator did not touch sends them to change the
        # wrong thing. The name is the transport's own declaration (``PeerAddress.within``)
        # rather than a literal, so a transport that calls it something else is answered
        # at its own box; one that does not offer a box for it gets the sentence above the
        # form instead, which is what the console does with every complaint it cannot
        # place.
        raise ParamsRefused(
            f"transport {node_transport.transport_name!r} on node {node.name!r} "
            f"rejected these parameters — {spec.within}: {refusal}",
            fields={spec.within: refusal},
        )


def _causes(stranded: dict[str, int]) -> str:
    """Each reason a tunnel could not carry what is in hand, with how many it applies to.

    A count per cause rather than one total, because the causes are not interchangeable:
    "outside the range" is answered with a wider prefix and "the node's own address" is
    answered by moving the node, and an operator given the wrong one of those retypes the
    same box twice. The clauses are ``edge``'s, in ``edge``'s order; nothing here parses
    an address or decides what a cause is.
    """
    return "; ".join(
        f"{count} {'is' if count == 1 else 'are'} {cause}"
        for cause, count in stranded.items()
    )


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
            # The operator's sentence, as rotation has always reported it. The kind of
            # failure travelling beside it (``apply.NotUpdated``) is revocation's to use.
            outcome.nodes_failed[named[node_id]] = failure.reason
    if outcome.nodes_failed:
        logger.error(
            "rotation on node-transport %s was not pushed to %d node(s); each is still "
            "running the material it had",
            outcome.node_transport_id,
            len(outcome.nodes_failed),
        )
    return outcome
