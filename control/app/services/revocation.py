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

from sqlalchemy.ext.asyncio import AsyncSession

from control.app.services import apply, friends

logger = logging.getLogger(__name__)


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

    # Node id -> why the push failed. The friend may STILL BE CONNECTED through
    # these until the node is reachable again.
    nodes_failed: dict[str, str] = field(default_factory=dict)

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
        """
        if self.complete:
            return (
                f"access withdrawn everywhere; {len(self.nodes_updated)} node(s) updated"
            )
        return (
            f"access withdrawn in the database and on {len(self.nodes_updated)} node(s), "
            f"but {len(self.nodes_failed)} node(s) could NOT be updated — the "
            "credential is still live there until they are reachable. Apply those nodes "
            f"again from {apply.WHERE_TO_RETRY} once they can be reached."
        )


async def revoke_friend(session: AsyncSession, *, friend_id: str) -> RevocationOutcome:
    """Withdraw access, then make it true on every node.

    The database change is committed FIRST, before any node is contacted. That order
    is deliberate: if the process dies midway, the durable state is "revoked, not yet
    pushed", which a retry completes. The other order would leave a friend revoked on
    some nodes and live in the database, and the next apply would put them back.
    """
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
            outcome.nodes_failed[node_id] = failure

    if not outcome.complete:
        logger.error(
            "INCOMPLETE revocation for friend %s: %d node(s) still carry the credential",
            friend_id,
            len(outcome.nodes_failed),
        )
    return outcome
