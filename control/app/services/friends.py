"""Issuing and withdrawing a friend's access — backlog items 7 and 9.

WHAT: creating a friend with a subscription, granting them credentials on every
      serving node, and revoking them everywhere.
WHY:  the charter's fifth criterion ("onboarding is one link") and sixth
      ("revocation is total") are both about this module. Granting means minting
      one credential per node × transport; revoking means removing every one of
      them and re-rendering every node they were on.
HOW:  ``grant_everywhere`` is called both when a friend is created and when a new
      node is enabled, so a node added later is not a node existing friends cannot
      reach. Revocation is a database change here; pushing the new configs is
      ``services/apply.py``, and ``revoke`` returns which nodes need it so the
      caller cannot forget.

      Since M17 granting has a second half: on a transport that gives each person an
      address of their own, the credential is not complete until it holds one. That is
      ``services/addresses.py``, called from inside this module's own transaction — so a
      pool with no room refuses the operation instead of producing a node that cannot be
      rendered afterwards.
"""

import datetime
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict, DomainError, NotFound
from control.app.models import AuditAction, Credential, Friend, NodeTransport, Subscription
from control.app.services import addresses, audit, keymaterial, nodes, subscriptions
from edge.registry import KeyScope, discover

logger = logging.getLogger(__name__)

# The width of ``Friend.nickname``. Stated here because this is the layer that
# refuses a value the column could not hold; the model is the other half of the pair.
NICKNAME_MAX_LENGTH = 64

# What the operator is told when two changes reached one address at the same instant —
# M17. The allocator takes the lowest address nobody holds, which is a READ, and nothing
# serialises two of them; ``uq_credential_tunnel_address`` is what stops the second one
# landing, so this is the sentence the constraint's own error becomes.
#
# IT SAYS NOTHING WAS CHANGED, and that is a promise this module keeps rather than a
# reassurance: the rollback below is what makes it true, and it runs before the refusal
# is raised precisely so the surface that catches it is looking at a session it can still
# read — the console re-renders its dialog in the same session, and a ``PendingRollbackError``
# there would turn a refusal into an internal error.
ADDRESS_TAKEN_MEANWHILE = (
    "another change took that address at the same moment; nothing was changed. Try again."
)


async def get_friend(session: AsyncSession, friend_id: str) -> Friend:
    friend = await session.get(Friend, friend_id)
    if friend is None:
        raise NotFound("no such friend")
    return friend


async def list_friends(session: AsyncSession) -> list[Friend]:
    result = await session.execute(select(Friend).order_by(Friend.created_at, Friend.id))
    return list(result.scalars().unique())


async def create_friend(session: AsyncSession, *, nickname: str) -> Friend:
    """Register a friend, mint their subscription, and grant them every node.

    All three in one operation because a friend without a subscription cannot be
    given anything, and a subscription with no credentials resolves to an empty
    config — which a client reports as a broken link. There is no partially
    onboarded state an operator can observe, on purpose.
    """
    # Checked here rather than in a route so both surfaces get the same answer, and so
    # a nickname that cannot be stored is refused with a sentence instead of arriving
    # at the database and coming back as an opaque 500. NICKNAME_MAX_LENGTH is the
    # column's own width — the two must not drift.
    nickname = nickname.strip()
    if not nickname:
        raise DomainError("a nickname is required — it is the only thing that identifies them")
    if len(nickname) > NICKNAME_MAX_LENGTH:
        raise DomainError(
            f"a nickname must be {NICKNAME_MAX_LENGTH} characters or fewer"
        )

    existing = await session.execute(select(Friend).where(Friend.nickname == nickname))
    if existing.scalars().first() is not None:
        raise Conflict(f"a friend called {nickname!r} already exists")

    # BEFORE ANY WRITE — M17. A transport that gives each person an address of their own
    # would refuse this friend when ``settle`` ran, which is correct but late: the
    # refusal would arrive with the friend, their subscription and their credentials
    # already built in this transaction, and the operator would be told "nothing was
    # changed" by a path that had to roll back to make it true. Asked here, the pool is
    # measured against the fleet the friend is about to join (``extra=1``) and the answer
    # names which pool and by how much, while nothing has been touched at all.
    short = await addresses.shortfalls(session, extra=1)
    if short:
        raise Conflict(addresses.too_small(short))

    friend = Friend(nickname=nickname)
    session.add(friend)
    # Flushed rather than committed: the friend, their token and their credentials
    # are one unit of work, and a crash between them would leave a friend the
    # operator believes has access.
    await session.flush()

    subscriptions.issue(session, friend)
    await grant_everywhere(session, friend)

    # In the same transaction as the friend, their token and their credentials, so the
    # trail cannot name somebody the database does not have. The label is the nickname
    # the operator just chose, copied whole — never the subscription URL, which is the
    # one artefact of this operation that must never reach a durable record.
    audit.record(session, AuditAction.FRIEND_ADDED, first_label=friend.nickname)

    await session.commit()
    logger.info("friend created: %s", friend.id)
    return friend


async def grant_everywhere(session: AsyncSession, friend: Friend) -> list[Credential]:
    """Give a friend a credential on every serving node × transport.

    Does NOT commit: callers compose it with other work in one transaction.

    Idempotent by design — it skips node-transports the friend already holds a
    credential for. That is what lets it be called again after a new node is
    enabled, which is how "a replacement node needs no action from any user"
    (criterion 2) actually happens.
    """
    if not friend.is_active:
        # Silently granting a revoked friend would be the exact failure criterion 6
        # forbids: access returning through a side door.
        raise Conflict("cannot grant access to a revoked friend")

    installed = discover()
    granted: list[Credential] = []
    # The rows this call minted something on, by id so a friend granted twice in one
    # transaction settles each row once. Keyed rather than a list because ``settle`` is
    # the one operation here that is about the row rather than about the person.
    touched: dict[str, NodeTransport] = {}

    # Queried rather than read off ``friend.credentials``. The relationship is
    # configured to load eagerly, but a friend created moments ago in this same
    # transaction has never been LOADED — so touching the collection triggers lazy
    # I/O, which in async SQLAlchemy is not a slow query but an immediate
    # MissingGreenlet crash. Explicit queries are the async idiom for a reason.
    existing = await session.execute(
        select(Credential.node_transport_id).where(Credential.friend_id == friend.id)
    )
    held = set(existing.scalars())

    for node_transport in await nodes.serving_transports(session):
        if node_transport.id in held:
            continue

        meta = installed.get(node_transport.transport_name)
        if meta is None:
            # The node runs a transport this image does not ship. Skipped rather
            # than crashed: an operator mid-downgrade must still be able to add a
            # friend, and the missing transport is visible in the panel.
            logger.warning(
                "node-transport %s names a transport not installed here", node_transport.id
            )
            continue

        minted = keymaterial.mint(meta.key_material, KeyScope.CLIENT)

        # "subject" is the transport's declared name for a client's identity. Pulled
        # out of the minted material rather than generated here, so `control` never
        # decides what a client identity looks like.
        subject = minted.secrets.pop("subject", None) or minted.params.pop("subject", None)
        if subject is None:
            raise Conflict(
                f"transport {node_transport.transport_name!r} declares no client-scoped "
                "identity, so a friend cannot be given access to it individually"
            )

        credential = Credential(
            friend_id=friend.id,
            node_transport_id=node_transport.id,
            subject=subject,
            secrets=json.dumps({**minted.secrets, **minted.params}),
        )
        session.add(credential)
        granted.append(credential)
        # Settled below rather than here, and only for the rows this call actually
        # granted on: the allocation is a property of the ROW (who already holds what),
        # not of this friend, so it is asked once per row after every credential is in.
        touched[node_transport.id] = node_transport

    await session.flush()

    # An address of their own, on every row whose transport says each consumer needs one
    # — M17. Inside the caller's transaction, which is what makes a pool with no room a
    # refusal that changed nothing rather than a render failure discovered after the
    # commit, on a node that then cannot be pushed to at all.
    try:
        for node_transport in touched.values():
            await addresses.settle(session, node_transport)
    except addresses.PoolFull as exc:
        # Rolled back HERE rather than left to the route, because this function is called
        # from inside four other services' transactions and each of them would otherwise
        # have to know that a refusal from here poisons the session. The message was
        # composed before the rollback, so it survives it.
        await session.rollback()
        raise Conflict(exc.message) from exc
    except IntegrityError as exc:
        if "uq_credential_tunnel_address" not in str(exc.orig):
            raise
        # The race the constraint exists for: two changes read the same free address and
        # both tried to take it. The loser is refused, never given a shared address.
        await session.rollback()
        raise Conflict(ADDRESS_TAKEN_MEANWHILE) from exc

    return granted


async def revoke(session: AsyncSession, *, friend_id: str) -> list[NodeTransport]:
    """Withdraw a friend's access everywhere, and report what must be re-pushed.

    Charter criterion 6. Three things happen, and all three are necessary:

    1. the friend is marked revoked, so nothing can grant them access again;
    2. their subscriptions are revoked, so the URL they hold stops resolving;
    3. every credential is DELETED, so no node config can be rendered that still
       authorises them.

    Deleting rather than flagging is the point. A flag means every renderer must
    remember to filter on it, and the one that forgets leaves a friend connected —
    which is precisely the failure the criterion is written against. With the rows
    gone, a re-render cannot include them even by mistake.

    Returns the node-transports whose configs changed. The database half alone does
    NOT complete a revocation: until those configs are pushed, the friend's
    credential is still live in the running daemon on each node. The caller pushes;
    see ``services/apply.py``.
    """
    friend = await get_friend(session, friend_id)
    now = datetime.datetime.now(datetime.UTC)

    # Explicit queries for the same reason as in ``grant_everywhere``: lazy access on
    # an async session raises rather than loading.
    held = await session.execute(
        select(Credential).where(Credential.friend_id == friend.id)
    )
    credentials = list(held.scalars().unique())
    affected = [credential.node_transport for credential in credentials]

    for credential in credentials:
        await session.delete(credential)

    issued = await session.execute(
        select(Subscription).where(Subscription.friend_id == friend.id)
    )
    for subscription in issued.scalars().unique():
        subscription.revoked_at = subscription.revoked_at or now

    friend.revoked_at = friend.revoked_at or now

    await session.commit()
    logger.info("friend revoked: %s (%d node configs to re-push)", friend.id, len(affected))
    # De-duplicated by id: a friend can hold two credentials on one node (two
    # transports), and pushing that node twice is wasted work on the one operation
    # that must complete quickly.
    unique: dict[str, NodeTransport] = {t.id: t for t in affected}
    return list(unique.values())
