"""Total revocation — backlog item 9, charter criterion 6.

WHAT: one operation that withdraws a user's access and pushes the consequence to
      every node they were on.
WHY:  it exists as its own module because the criterion is "their credentials stop
      working on EVERY node and EVERY protocol", and that is two systems: the
      database and the running daemons. A revocation that only did the first is the
      failure the criterion was written against, and the control rulebook names it
      as a trap explicitly.
HOW:  ``revoke_user`` calls the database half, then the push half, and reports
      honestly on both. It does not raise when a node is unreachable — it returns
      which nodes still carry the credential, because the operator must know that a
      revocation is INCOMPLETE rather than be told it failed and left guessing.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.models import AuditAction, Node
from control.app.services import apply, audit, users
from control.app.services.apply import NotUpdated

logger = logging.getLogger(__name__)

# What the banner says about one node a revocation could not update, by kind. A node's
# NAME and these words are the whole of it — see ``RevocationOutcome.summary`` for why
# nothing a node itself said may join them. Acceptance judges this wording, and
# tests/control/test_a_revocation_says_why_a_node_kept_the_credential.py holds it
# literally.
#
# EVERY SENTENCE HERE HAS TO END SOMEWHERE THE OPERATOR CAN ACTUALLY GO — M23, round 12,
# which is the round that found one that did not. A node the state machine will not put
# back into service was reported as ``REFUSED``, whose sentence ends "apply it from the
# Nodes screen to read why"; apply on that node answers that applying is the one move it
# is refused. Every fact in the report was correct and the last clause sent the operator
# to a button that cannot complete it. So ``CANNOT_SERVE`` is its own kind below, and its
# sentence ends where the answer actually is — which, for a host the record says is gone,
# is not on this panel at all.
_WHY_NOT_UPDATED: dict[NotUpdated, str] = {
    NotUpdated.NO_RESOLVER: (
        "{node} has no resolver on its record, so its configuration cannot be rendered "
        "and retrying will not change that — set its resolver on {where}, then apply it"
    ),
    NotUpdated.REFUSED: (
        "{node} could not be given a configuration: it was refused before anything was "
        "pushed, and retrying will not change that — apply it from {where} to read why"
    ),
    NotUpdated.NOT_SERVING: (
        "{node} was reached and its configuration WAS replaced on it, but it did not come "
        "back running that configuration — so the process on it may still be serving the "
        "file that carries this credential. Retrying will not change that on its own: "
        "apply it from {where} and read what did not come up"
    ),
    NotUpdated.OUT_OF_SERVICE: (
        "{node} is not in service, so nothing was pushed to it — and nothing about this "
        "press put it back into service, which is a decision only an apply of that node "
        "makes. It is serving nobody by this control plane's records, but whatever its "
        "host was last given is still running there and may still authorise this "
        "credential: apply it from {where} once its host is ready, and that is what ends it"
    ),
    NotUpdated.CANNOT_SERVE: (
        "{node} is in the state an operator records a host as GONE in, so nothing was "
        "pushed to it and no apply will push to it again — putting a node in that state "
        "back into service is the one move it is refused, and no screen in this panel "
        "finishes this. Whatever its host was last given is still running there and may "
        "still authorise this credential; nothing this control plane pushes reaches it. "
        "If that host is genuinely back, register it again as a new node and apply that "
        "one — otherwise it is the host being gone that ends this"
    ),
    NotUpdated.UNREACHED: (
        "{node} could not be reached — apply it again from {where} once it can be"
    ),
}

# What the operator is told when they press revoke on somebody who has already been
# revoked — M23, and it exists because the honest answer to the SECOND press was the
# reassuring one. The walk pressed revoke twice on a node that could not be updated: the
# first press said so correctly, and the second said "the link is dead" because the
# credential rows were already gone and the fan-out therefore had nothing to fail on. An
# operator cutting somebody off in a hurry presses again after a failure — that is the
# natural gesture — and was told the thing they were checking for.
#
# So the second press says what is true of it: the database half was already done, this
# request pushed nothing, and nothing about it can confirm that a node stopped serving
# the credential. It ends where the incomplete report ends, at the screen where a node is
# probed and applied, because that is the only place the answer actually lives.
#
# It names no node. A node that failed the first time is not knowable from here — the
# rows that said which ones were affected are what the first press deleted — and naming
# the ones that happen to be degraded now would be a guess about a different question.
#
# WHICH IS WHY ITS LAST CLAUSE HAD TO STOP BEING UNCONDITIONAL — M23, round 13, which
# found the same instruction on the Users screen's standing note being given about a host
# where both buttons refuse it. That note names its nodes and can now say which of them
# probe and apply still finish (``console.WITHDRAWAL_UNCONFIRMABLE``); this sentence names
# none and cannot, so it states the exception instead of promising the rule. The clause is
# written for every caller, like the rest of this sentence: it names a STATE the record is
# in and no screen, which is what keeps it answerable in a JSON envelope too.
ALREADY_WITHDRAWN = (
    "nothing changed — this access was already withdrawn, so nothing was pushed to any "
    "node and this press cannot tell you that any node has stopped serving it. A node "
    "still running an older configuration goes on serving anyone withdrawn while it was "
    "in that state: probe it on {where}, and apply it there — unless its record says its "
    "host is gone, which is the one state a node is neither probed nor applied in, and "
    "nothing pushed from here reaches such a host at all."
)


@dataclass
class RevocationOutcome:
    """What actually happened, in enough detail for the operator to act.

    ``confirmed`` is the field that matters, and ``complete`` is the field that used to
    be mistaken for it. Anything else being reported as success would be the "revoked in
    the database, still connected on a node" state the charter forbids.
    """

    user_id: str

    # Whether THIS request withdrew anything at all — M23. False when the user was
    # already revoked before it ran, which is what a second press of the revoke button is.
    # Kept apart from ``complete`` rather than folded into it: ``complete`` answers "did
    # every affected node accept", and with no affected node that is vacuously true and
    # stays true, which is what made the second press read as a success. See ``confirmed``
    # below for the pair a caller should actually act on.
    withdrew: bool = True

    # Nodes whose configuration was re-pushed successfully. The user's credential
    # is gone from the running daemon on each of these.
    nodes_updated: list[str] = field(default_factory=list)

    # Node id -> why the push failed, in the failure's own words. The user may STILL BE
    # CONNECTED through these until the node is updated — which, for a node that cannot
    # be rendered, reachability alone will not bring. Returned by the API as they are, and
    # NEVER composed into the banner below: see ``why_failed``.
    nodes_failed: dict[str, str] = field(default_factory=dict)

    # Node id -> which kind of failure it was (``apply.NotUpdated``). What the banner is
    # built from INSTEAD of the words above: a refusal's message can carry an upstream
    # checker's output, and that output is known to quote the node's private key.
    why_failed: dict[str, NotUpdated] = field(default_factory=dict)

    # Node id -> the node's name, for every node in ``nodes_failed``: read off the rows,
    # so the banner names a node the way the Nodes screen does.
    names: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """True only when every affected node accepted the new configuration.

        A COMPONENT OF THE ANSWER AND NOT THE ANSWER, and since M23's eighth round no
        surface serialises it or renders it: both the panel and the API report
        ``confirmed``. It stays because ``summary`` below branches on it — "nothing
        failed" and "this request settled anything" are two different facts, and the
        sentence needs them apart — but a reader reaching for a field to reassure on
        wants the one below.
        """
        return not self.nodes_failed

    @property
    def confirmed(self) -> bool:
        """True only when THIS request withdrew access AND every node accepted it — M23.

        The one property a surface may draw a reassurance from. ``complete`` is not it and
        never was: it is vacuously true for a request that had nothing to push, so a
        second press on an already-revoked person satisfied it while the node that failed
        the first press was still serving them.

        BOTH SURFACES NOW, since round 8. Round 6 taught the panel this and left the API's
        ``complete`` field carrying the vacuous one, so the machine-readable half went on
        answering ``true`` to the retry that is the natural thing for an integration to
        do — the same defect, on the surface nobody watches.
        """
        return self.withdrew and self.complete

    def summary(self) -> str:
        """One line for the operator. Says the uncomfortable thing when it is true.

        The incomplete half is drawn as a banner on the Users screen, and it is the most
        load-bearing sentence this codebase composes: it is read at the one moment a
        person who should be cut off is still connected. So it ends by naming where the
        push is finished — ``apply.WHERE_TO_RETRY``, a screen, never a page. It named
        ``pages/node.html`` until M9.6 deleted that page and left this pointing at a 404.

        Since M16 it names EACH node and what to do about that one, because "until they are
        reachable" was false for a node that cannot be rendered — no retry reaches it until
        its record changes. What it says comes from ``why_failed`` and the node's name, and
        from nothing else: a node's own failure message can carry an upstream checker's
        output, which is known to quote that node's private key, and this sentence has no
        safe place for it. The name is the only text in it the operator did not read here.
        """
        if not self.withdrew:
            # Said before ``complete`` is consulted, because ``complete`` is TRUE here:
            # nothing was affected, so nothing failed. M23.
            return ALREADY_WITHDRAWN.format(where=apply.WHERE_TO_RETRY)
        if self.complete:
            return (
                f"access withdrawn everywhere; {len(self.nodes_updated)} node(s) updated"
            )
        clauses = sorted(
            _WHY_NOT_UPDATED[self.why_failed.get(node_id, NotUpdated.UNREACHED)].format(
                node=repr(self.names.get(node_id, node_id)), where=apply.WHERE_TO_RETRY
            )
            for node_id in self.nodes_failed
        )
        return (
            f"access withdrawn in the database and on {len(self.nodes_updated)} node(s), "
            f"but {len(self.nodes_failed)} node(s) could NOT be updated and the credential "
            f"is still live on each until it is: {'; '.join(clauses)}."
        )


async def revoke_user(session: AsyncSession, *, user_id: str) -> RevocationOutcome:
    """Withdraw access, then make it true on every node.

    The database change is committed FIRST, before any node is contacted. That order
    is deliberate: if the process dies midway, the durable state is "revoked, not yet
    pushed", which a retry completes. The other order would leave a user revoked on
    some nodes and live in the database, and the next apply would put them back.
    """
    # Recorded BEFORE the database half runs, and deliberately not committed here: the
    # entry sits pending in this session until ``users.revoke`` commits, so both land
    # in one transaction and a revocation that raises leaves no entry behind. Written
    # from this module rather than from ``users.revoke`` because this is the operation
    # the operator performed — both surfaces call it — and because the nickname has to
    # be read while the user row is still the one being withdrawn.
    #
    # The label is the nickname, copied whole. Nothing about which nodes were reached is
    # recorded: a push that failed is not a change that committed, the outcome sentence
    # already tells the operator, and the node's own state carries it afterwards.
    #
    # A user already revoked is recorded once and not again: withdrawing access from
    # somebody who has none changes nothing, and a trail that grows on a retried request
    # is a trail that says a thing happened twice.
    user = await users.get_user(session, user_id)
    # Taken BEFORE the rest of the database half runs, and it is what separates a
    # revocation from a second press of the same button — M23. After ``users.revoke``
    # the two are indistinguishable from here: the credential rows are deleted either way,
    # so an empty fan-out means "nobody to push" in one case and "already pushed, or
    # already failed to push" in the other.
    #
    # A WRITE AND NOT A READ SINCE ROUND 8. This was ``user.is_active``, asked of the
    # object this session was holding, so two revocations of one person in the same
    # instant both saw an active user and both claimed to have withdrawn the access —
    # and the second one had pushed nothing. ``claim_withdrawal`` asks the row and can
    # only be answered once.
    withdrawing = await users.claim_withdrawal(session, user_id=user_id)
    if withdrawing:
        audit.record(session, AuditAction.USER_REVOKED, first_label=user.nickname)

    affected = await users.revoke(session, user_id=user_id)

    outcome = RevocationOutcome(user_id=user_id, withdrew=withdrawing)
    if not affected:
        # A user who held no credentials — never granted, or already revoked.
        # Complete by definition, and worth returning as such rather than as an error.
        return outcome

    results = await apply.apply_many(session, affected)
    for node_id, failure in results.items():
        if failure is None:
            outcome.nodes_updated.append(node_id)
        else:
            outcome.nodes_failed[node_id] = failure.reason
            outcome.why_failed[node_id] = failure.why
    if outcome.nodes_failed:
        # Read fresh by id rather than through the rows the fan-out touched: a node the
        # fan-out rolled back past is detached, and reaching its name through a
        # relationship is lazy I/O on an async session.
        named = await session.execute(
            select(Node.id, Node.name).where(Node.id.in_(list(outcome.nodes_failed)))
        )
        outcome.names = {row.id: row.name for row in named}

    if not outcome.complete:
        logger.error(
            "INCOMPLETE revocation for user %s: %d node(s) still carry the credential",
            user_id,
            len(outcome.nodes_failed),
        )
    return outcome
