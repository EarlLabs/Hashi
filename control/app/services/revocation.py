"""Total revocation — backlog item 9, charter criterion 6.

WHAT: one operation that withdraws a friend's access and pushes the consequence to
      every node they were on.
WHY:  it exists as its own module because the criterion is "their credentials stop
      working on EVERY node and EVERY protocol", and that is two systems: the
      database and the running daemons. A revocation that only did the first is the
      failure the criterion was written against, and the control rulebook names it
      as a trap explicitly.
HOW:  ``revoke_friend`` calls the database half, then the push half, and reports
      honestly on both. It does not raise when a node is unreachable — it returns
      which nodes still carry the credential, because the operator must know that a
      revocation is INCOMPLETE rather than be told it failed and left guessing.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.models import AuditAction, Node
from control.app.services import apply, audit, friends
from control.app.services.apply import NotUpdated

logger = logging.getLogger(__name__)

# What the banner says about one node a revocation could not update, by kind. A node's
# NAME and these words are the whole of it — see ``RevocationOutcome.summary`` for why
# nothing a node itself said may join them. Acceptance judges this wording, and
# tests/control/test_a_revocation_says_why_a_node_kept_the_credential.py holds it
# literally.
_WHY_NOT_UPDATED: dict[NotUpdated, str] = {
    NotUpdated.NO_RESOLVER: (
        "{node} has no resolver on its record, so its configuration cannot be rendered "
        "and retrying will not change that — set its resolver on {where}, then apply it"
    ),
    NotUpdated.REFUSED: (
        "{node} could not be given a configuration: it was refused before anything was "
        "pushed, and retrying will not change that — apply it from {where} to read why"
    ),
    NotUpdated.UNREACHED: (
        "{node} could not be reached — apply it again from {where} once it can be"
    ),
}


@dataclass
class RevocationOutcome:
    """What actually happened, in enough detail for the operator to act.

    ``complete`` is the field that matters. Anything else being reported as success
    would be the "revoked in the database, still connected on a node" state the
    charter forbids.
    """

    friend_id: str

    # Nodes whose configuration was re-pushed successfully. The friend's credential
    # is gone from the running daemon on each of these.
    nodes_updated: list[str] = field(default_factory=list)

    # Node id -> why the push failed, in the failure's own words. The friend may STILL BE
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
        """True only when every affected node accepted the new configuration."""
        return not self.nodes_failed

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


async def revoke_friend(session: AsyncSession, *, friend_id: str) -> RevocationOutcome:
    """Withdraw access, then make it true on every node.

    The database change is committed FIRST, before any node is contacted. That order
    is deliberate: if the process dies midway, the durable state is "revoked, not yet
    pushed", which a retry completes. The other order would leave a friend revoked on
    some nodes and live in the database, and the next apply would put them back.
    """
    # Recorded BEFORE the database half runs, and deliberately not committed here: the
    # entry sits pending in this session until ``friends.revoke`` commits, so both land
    # in one transaction and a revocation that raises leaves no entry behind. Written
    # from this module rather than from ``friends.revoke`` because this is the operation
    # the operator performed — both surfaces call it — and because the nickname has to
    # be read while the friend row is still the one being withdrawn.
    #
    # The label is the nickname, copied whole. Nothing about which nodes were reached is
    # recorded: a push that failed is not a change that committed, the outcome sentence
    # already tells the operator, and the node's own state carries it afterwards.
    #
    # A friend already revoked is recorded once and not again: withdrawing access from
    # somebody who has none changes nothing, and a trail that grows on a retried request
    # is a trail that says a thing happened twice.
    friend = await friends.get_friend(session, friend_id)
    if friend.is_active:
        audit.record(session, AuditAction.FRIEND_REVOKED, first_label=friend.nickname)

    affected = await friends.revoke(session, friend_id=friend_id)

    outcome = RevocationOutcome(friend_id=friend_id)
    if not affected:
        # A friend who held no credentials — never granted, or already revoked.
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
            "INCOMPLETE revocation for friend %s: %d node(s) still carry the credential",
            friend_id,
            len(outcome.nodes_failed),
        )
    return outcome
