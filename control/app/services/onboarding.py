"""Adding users, and pushing the consequence to every node they were given — M32.

WHAT: the add-user half of what ``services/revocation.py`` is for the withdrawal: one
      operation that registers people and then applies every serving node on which they
      were just given a credential, reporting per node what happened.
WHY:  until M32 adding a user wrote to the database and touched no host, while revoking
      one applied every node by itself. The owner added a user, imported the link on a
      phone and got a timeout: the user's credential was not on the entry, and the
      sentence saying so was a grey paragraph under the link. A link that names a node
      which has never heard of its holder is the "every signal green, nothing carried"
      shape this project keeps finding, so the add now carries itself
      (``docs/decisions.md``, 2026-10-03).
HOW:  two halves, because the two surfaces need them apart. ``add_users`` is the whole
      thing — ``users.create_users`` (one transaction, committed BEFORE any host is
      dialled, the order revocation keeps for the same reason) and then ``reach`` over
      the nodes it returned. ``reach`` is public on its own because a caller that has to
      report each node as it lands, or retry one, needs the push without the create;
      ``panel/routes.py``'s ``create_user`` says why the console is such a caller.

      ``reach`` is ``apply.apply_nodes``, the same fan-out revocation uses: every node
      attempted even if an earlier one failed, and a node that is not serving refused
      rather than taken into service — an add is aimed at people, not at a node's state.
      Whether a node it could not reach stays in users' links is decided by the apply
      (the owner's rules of 2026-10-02), not here; nothing in this module moves a node's
      state.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.models import Node, User
from control.app.services import apply, users
from control.app.services.apply import NotUpdated

logger = logging.getLogger(__name__)

# What a node an add could not reach is said to be, by kind — the add direction of
# ``revocation._WHY_NOT_UPDATED``, and composed from the same two things only: the node's
# NAME and the kind. A failure's own message can carry an upstream checker's output, which
# is known to quote the node's private key, so it never joins these (``NotUpdated``).
#
# Each says what the node is doing for the people just added — whether it knows them — and
# ends somewhere the operator can go. None says the node left anybody's link unless it did:
# a node not reached keeps its place in every link (the owner's rule of 2026-10-02), and
# only a node out of service is in nobody's.
_WHY_NOT_REACHED: dict[NotUpdated, str] = {
    NotUpdated.NO_RESOLVER: (
        "{node} has no resolver on its record, so its configuration cannot be rendered "
        "and retrying will not change that — set its resolver on {where}, then apply it"
    ),
    NotUpdated.REFUSED: (
        "{node} could not be given a configuration: it was refused before anything was "
        "pushed, and retrying will not change that — apply it from {where} to read why"
    ),
    NotUpdated.NOT_SERVING: (
        "{node} was given the new configuration and is not confirmed serving it, so it "
        "may not know them yet — retry in a minute, or apply it from {where} and read "
        "what did not come up"
    ),
    NotUpdated.OUT_OF_SERVICE: (
        "{node} is not in service, so nothing was pushed to it and it is in nobody's "
        "link — putting it back into service is an apply on {where}"
    ),
    NotUpdated.CANNOT_SERVE: (
        "{node} is recorded as a host that is gone, so nothing was pushed to it and it is "
        "in nobody's link"
    ),
    NotUpdated.UNREACHED: (
        "{node} was not updated — it could not be reached, or the push did not finish — "
        "so it does not know them yet; retry, and if it fails again apply it from {where} "
        "to read why"
    ),
}

# The kinds a retry can change on its own: a host that was not reached, and a daemon that
# had not come up yet. Every other kind says "retrying will not change that", and a retry
# button beside such a sentence would contradict it.
RETRYABLE = frozenset({NotUpdated.UNREACHED, NotUpdated.NOT_SERVING})


def why_not_reached(kind: NotUpdated, *, name: str) -> str:
    """The sentence for one node an add could not reach, from its kind and name only."""
    return _WHY_NOT_REACHED[kind].format(node=repr(name), where=apply.WHERE_TO_RETRY)


@dataclass
class ReachOutcome:
    """What applying the nodes an add touched did, node by node.

    Shaped like ``revocation.RevocationOutcome`` on purpose — the API returns both and an
    integration reading one should be able to read the other: ``nodes_updated``, then
    ``nodes_failed`` in the failure's own words, then ``why_failed`` as kinds, then the
    names the sentences are built from.
    """

    # Nodes now running a configuration that includes everyone this add registered.
    nodes_updated: list[str] = field(default_factory=list)

    # Node id -> why the apply failed, in the failure's own words. Returned by the API as
    # they are, and NEVER composed into a sentence this module writes: see ``why_failed``.
    nodes_failed: dict[str, str] = field(default_factory=dict)

    # Node id -> which kind of failure it was. What the sentences are built from instead.
    why_failed: dict[str, NotUpdated] = field(default_factory=dict)

    # Node id -> name, for every node attempted, read off the rows after the fan-out.
    names: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """True when every node attempted now runs a configuration that includes them.

        Vacuously true when there was nothing to attempt — no node serving. Unlike a
        revocation's, that case reassures nobody wrongly: an add with no serving node
        hands over a link that resolves to nothing, and ``summary`` says exactly that.
        """
        return not self.nodes_failed

    def clauses(self) -> list[str]:
        """One sentence per node not reached, sorted so a reload does not reshuffle them."""
        return sorted(
            why_not_reached(
                self.why_failed.get(node_id, NotUpdated.UNREACHED),
                name=self.names.get(node_id, node_id),
            )
            for node_id in self.nodes_failed
        )


@dataclass
class AddOutcome(ReachOutcome):
    """``ReachOutcome`` for the add that registered ``users``."""

    users: list[User] = field(default_factory=list)

    def summary(self) -> str:
        """One line for whoever added them. Names each node that does not know them yet."""
        added = f"{len(self.users)} user(s) added"
        if not self.nodes_updated and not self.nodes_failed:
            return (
                f"{added}; no node is serving, so nothing was pushed and their link "
                "resolves to an empty configuration until one is"
            )
        if self.complete:
            return (
                f"{added} and pushed to every node they were given; "
                f"{len(self.nodes_updated)} node(s) updated"
            )
        return (
            f"{added} and pushed to {len(self.nodes_updated)} node(s), but "
            f"{len(self.nodes_failed)} node(s) could NOT be updated and do not know them "
            f"yet: {'; '.join(self.clauses())}."
        )


async def reach(session: AsyncSession, node_ids: Sequence[str]) -> ReachOutcome:
    """Apply these nodes through the fan-out, and say per node what happened.

    Through ``apply.apply_nodes`` and so with ``only_if_serving``: a node an operator took
    out of service between the add and this call is reported, not put back.
    """
    outcome = ReachOutcome()
    if not node_ids:
        return outcome
    results = await apply.apply_nodes(session, node_ids)
    for node_id, failure in results.items():
        if failure is None:
            outcome.nodes_updated.append(node_id)
        else:
            outcome.nodes_failed[node_id] = failure.reason
            outcome.why_failed[node_id] = failure.why
    # Read fresh by id rather than through the rows the fan-out touched: a node the
    # fan-out rolled back past is detached, and reaching its name through a relationship
    # is lazy I/O on an async session. ``revocation.revoke_user`` reads its names so too.
    named = await session.execute(
        select(Node.id, Node.name).where(Node.id.in_(list(results)))
    )
    outcome.names = {row.id: row.name for row in named}
    if outcome.nodes_failed:
        logger.error(
            "an add could not update %d of %d node(s)",
            len(outcome.nodes_failed),
            len(results),
        )
    return outcome


async def add_users(session: AsyncSession, *, nicknames: Sequence[str]) -> AddOutcome:
    """Register these people, then apply every node they were given — each node once.

    The database half commits first and the push runs after it, revocation's order: if
    the process dies between the two, the durable state is "added, not yet pushed", which
    every screen names and an apply completes.
    """
    created = await users.create_users(session, nicknames=nicknames)
    reached = await reach(session, created.node_ids)
    # Re-read, because the fan-out may have rolled the session back past an unexpected
    # error (``apply.apply_nodes``), and a rollback expires every object it holds whatever
    # ``expire_on_commit`` says — the caller serialises these rows next, and an expired
    # attribute read there is lazy I/O on an async session.
    for user in created.users:
        await session.refresh(user)
    return AddOutcome(
        nodes_updated=reached.nodes_updated,
        nodes_failed=reached.nodes_failed,
        why_failed=reached.why_failed,
        names=reached.names,
        users=created.users,
    )
