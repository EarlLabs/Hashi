"""Issuing and withdrawing a user's access — backlog items 7 and 9.

WHAT: creating a user with a subscription, granting them credentials on every
      serving node, and revoking them everywhere.
WHY:  the charter's fifth criterion ("onboarding is one link") and sixth
      ("revocation is total") are both about this module. Granting means minting
      one credential per node × transport; revoking means removing every one of
      them and re-rendering every node they were on.
HOW:  ``grant_everywhere`` is called both when a user is created and when a new
      node is enabled, so a node added later is not a node existing users cannot
      reach. Revocation is a database change here; pushing the new configs is
      ``services/apply.py``, and ``revoke`` returns which nodes need it so the
      caller cannot forget.

      Nothing here dials a node. Since M32 an add is the database half of
      ``services/onboarding.py``'s operation, and ``create_users`` returns the nodes it
      granted on so that caller cannot forget them — ``revoke``'s arrangement, the other
      way.

      Since M17 granting has a second half: on a transport that gives each person an
      address of their own, the credential is not complete until it holds one. That is
      ``services/addresses.py``, called from inside this module's own transaction — so a
      pool with no room refuses the operation instead of producing a node that cannot be
      rendered afterwards.
"""

import datetime
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict, DomainError, NotFound
from control.app.models import AuditAction, Credential, NodeTransport, Subscription, User
from control.app.services import addresses, audit, keymaterial, nodes, subscriptions
from edge.registry import KeyScope, discover

logger = logging.getLogger(__name__)

# The width of ``User.nickname``. Stated here because this is the layer that
# refuses a value the column could not hold; the model is the other half of the pair.
NICKNAME_MAX_LENGTH = 64

# How many people one add may register — M32. A bound so a pasted file cannot become one
# transaction minting thousands of credentials; sized to the whole user base this product
# is built for (the charter's 30–50), so no real add ever meets it.
MAX_USERS_PER_ADD = 50


class NicknameTaken(Conflict):
    """A name on the list already belongs to somebody — revoked or not.

    A ``Conflict`` (409) like every other refusal about what already exists, with the
    same sentence, code and status as before it had a type, so no caller sees a change.
    Its own type so that a caller can tell "this person exists" from the add's other
    conflicts (a name twice on one list, a pool with no room) without reading the
    sentence: the Telegram bot points at the panel for exactly this one, because the
    panel is where an existing person's links are and the bot never re-sends them.
    """


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


async def get_user(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("no such user")
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at, User.id))
    return list(result.scalars().unique())


async def create_user(session: AsyncSession, *, nickname: str) -> User:
    """Register one user — ``create_users`` with a list of one. Pushes nothing.

    Kept for the callers that add one person and read back one row. What reaches the
    nodes afterwards is ``services/onboarding.py``'s, not this function's.
    """
    created = await create_users(session, nicknames=[nickname])
    return created.users[0]


@dataclass(frozen=True)
class Created:
    """The users one add registered, and the nodes that now hold something for them.

    ``node_ids`` is what makes the add reach the nodes (M32): every SERVING node on which
    this add minted a credential, each once, in the order the fleet is listed in. Taken
    from the rows the grant actually wrote on, not from "every serving node", so a node
    whose only transport this image does not ship — skipped by the grant — is not dialled
    for nothing.
    """

    users: list[User]
    node_ids: list[str]


async def create_users(session: AsyncSession, *, nicknames: Sequence[str]) -> Created:
    """Register users, mint each a subscription, and grant each every serving node.

    All of it in one operation because a user without a subscription cannot be given
    anything, and a subscription with no credentials resolves to an empty config — which a
    client reports as a broken link. There is no partially onboarded state an operator can
    observe, on purpose.

    SEVERAL AT ONCE, AND ALL OR NONE — M32. Each node an add touches is restarted by the
    apply that follows, which drops everyone connected to it for a second or two, so the
    add dialog takes a list and the nodes are applied once for all of it. One transaction
    for the whole list, so a nickname refused on line three refuses the add rather than
    leaving lines one and two registered with an error the operator reads as "nothing
    happened". The refusal names the line's nickname; nothing was written.

    It pushes nothing: the database half only, exactly as before M32, and the reason it
    stays that way is the order revocation keeps too — the durable state is committed
    before any host is dialled, so a crash mid-push leaves "added, not yet pushed", which
    the screens say and an apply completes.
    """
    # Checked here rather than in a route so both surfaces get the same answer, and so
    # a nickname that cannot be stored is refused with a sentence instead of arriving
    # at the database and coming back as an opaque 500. NICKNAME_MAX_LENGTH is the
    # column's own width — the two must not drift.
    wanted = [nickname.strip() for nickname in nicknames]
    wanted = [nickname for nickname in wanted if nickname]
    if not wanted:
        raise DomainError("a nickname is required — it is the only thing that identifies them")
    if len(wanted) > MAX_USERS_PER_ADD:
        raise DomainError(
            f"at most {MAX_USERS_PER_ADD} users can be added at once; this was "
            f"{len(wanted)} — split the list and add the rest next"
        )
    for nickname in wanted:
        if len(nickname) > NICKNAME_MAX_LENGTH:
            raise DomainError(
                f"a nickname must be {NICKNAME_MAX_LENGTH} characters or fewer — "
                f"{nickname[:NICKNAME_MAX_LENGTH]!r}… is longer"
                if len(wanted) > 1
                else f"a nickname must be {NICKNAME_MAX_LENGTH} characters or fewer"
            )
    seen: set[str] = set()
    for nickname in wanted:
        if nickname in seen:
            raise Conflict(f"{nickname!r} is in this list twice")
        seen.add(nickname)

    existing = await session.execute(select(User.nickname).where(User.nickname.in_(wanted)))
    taken = sorted(existing.scalars())
    if taken:
        raise NicknameTaken(
            f"a user called {taken[0]!r} already exists"
            if len(taken) == 1
            else "users called " + ", ".join(repr(name) for name in taken) + " already exist"
        )

    # BEFORE ANY WRITE — M17. A transport that gives each person an address of their own
    # would refuse this add when ``settle`` ran, which is correct but late: the refusal
    # would arrive with the users, their subscriptions and their credentials already built
    # in this transaction, and the operator would be told "nothing was changed" by a path
    # that had to roll back to make it true. Asked here, the pool is measured against the
    # fleet these users are about to join (``extra`` is how many) and the answer names
    # which pool and by how much, while nothing has been touched at all.
    short = await addresses.shortfalls(session, extra=len(wanted))
    if short:
        raise Conflict(addresses.too_small(short))

    serving = await nodes.serving_transports(session)
    created: list[User] = []
    granted_on: set[str] = set()
    for nickname in wanted:
        user = User(nickname=nickname)
        session.add(user)
        # Flushed rather than committed: the users, their tokens and their credentials
        # are one unit of work, and a crash between them would leave a user the
        # operator believes has access.
        await session.flush()

        subscriptions.issue(session, user)
        granted = await grant_on(session, user, serving)
        granted_on.update(credential.node_transport_id for credential in granted)

        # In the same transaction as the user, their token and their credentials, so the
        # trail cannot name somebody the database does not have. The label is the
        # nickname the operator just chose, copied whole — never the subscription URL,
        # which is the one artefact of this operation that must never reach a durable
        # record. One entry per person, because each is one person added.
        audit.record(session, AuditAction.USER_ADDED, first_label=user.nickname)
        created.append(user)

    # Read off the rows BEFORE the commit, while they are plain loaded objects.
    node_ids = list(dict.fromkeys(row.node_id for row in serving if row.id in granted_on))

    await session.commit()
    for user in created:
        logger.info("user created: %s", user.id)
    return Created(users=created, node_ids=node_ids)


async def grant_everywhere(session: AsyncSession, user: User) -> list[Credential]:
    """Give a user a credential on every serving node × transport.

    Does NOT commit: callers compose it with other work in one transaction.

    Idempotent by design — it skips node-transports the user already holds a
    credential for. That is what lets it be called again after a new node is
    enabled, which is how "a replacement node needs no action from any user"
    (criterion 2) actually happens.
    """
    return await grant_on(session, user, await nodes.serving_transports(session))


async def grant_on(
    session: AsyncSession, user: User, rows: Sequence[NodeTransport]
) -> list[Credential]:
    """The same grant, over rows the caller chose. Does NOT commit.

    Split out of ``grant_everywhere`` in M23's round 3 for one caller: ``apply.apply_node``
    grants on the node it is about to push BEFORE it renders, so the peers in the file are
    the people the file authorises. At that moment the node is still a draft or degraded,
    so it is in nothing ``serving_transports`` returns — the query above is precisely the
    one that cannot answer this case.

    THE ROWS ARE THE CALLER'S RESPONSIBILITY and there is one rule about them:
    user-facing only. ``serving_transports`` filters ``purpose == USERS`` because a
    user handed a hop end would be routed straight past the entry node the topology
    exists to hide behind, and that rule does not stop being true because the rows arrived
    from somewhere else. Nothing here re-filters, deliberately — a second copy of the rule
    is a second place for it to drift — so a caller passing its own list says in its own
    words why the list is user-facing.
    """
    if not user.is_active:
        # Silently granting a revoked user would be the exact failure criterion 6
        # forbids: access returning through a side door.
        raise Conflict("cannot grant access to a revoked user")

    installed = discover()
    granted: list[Credential] = []
    # The rows this call minted something on, by id so a user granted twice in one
    # transaction settles each row once. Keyed rather than a list because ``settle`` is
    # the one operation here that is about the row rather than about the person.
    touched: dict[str, NodeTransport] = {}

    # Queried rather than read off ``user.credentials``. The relationship is
    # configured to load eagerly, but a user created moments ago in this same
    # transaction has never been LOADED — so touching the collection triggers lazy
    # I/O, which in async SQLAlchemy is not a slow query but an immediate
    # MissingGreenlet crash. Explicit queries are the async idiom for a reason.
    existing = await session.execute(
        select(Credential.node_transport_id).where(Credential.user_id == user.id)
    )
    held = set(existing.scalars())

    for node_transport in rows:
        if node_transport.id in held:
            continue

        meta = installed.get(node_transport.transport_name)
        if meta is None:
            # The node runs a transport this image does not ship. Skipped rather
            # than crashed: an operator mid-downgrade must still be able to add a
            # user, and the missing transport is visible in the panel.
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
                "identity, so a user cannot be given access to it individually"
            )

        credential = Credential(
            user_id=user.id,
            node_transport_id=node_transport.id,
            subject=subject,
            secrets=json.dumps({**minted.secrets, **minted.params}),
        )
        session.add(credential)
        granted.append(credential)
        # Settled below rather than here, and only for the rows this call actually
        # granted on: the allocation is a property of the ROW (who already holds what),
        # not of this user, so it is asked once per row after every credential is in.
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


async def claim_withdrawal(session: AsyncSession, *, user_id: str) -> bool:
    """Take the withdrawal of this user's access, and answer whether THIS call took it.

    ONE STATEMENT, AND THE DATABASE DECIDES IT — M23, round 8. Whether a revocation
    withdrew anything was read off ``user.is_active`` before the work started, which is
    a read of the copy the caller's session is holding and not of the row. Two revocations
    of one person in the same instant therefore both found an active user and both
    reported ``withdrew=True``: the second one pushed nothing, could confirm nothing, and
    said it had cut somebody off. That is the failure shape ``nodes._node_to_write`` is
    written against, one table over — a decision taken against a photograph.

    A conditional ``UPDATE ... WHERE revoked_at IS NULL`` cannot be taken twice. The
    second one blocks on the row the first is holding, re-reads it when that commits, and
    matches nothing — so ``rowcount`` is the answer, taken from the database rather than
    inferred.

    IT IS A LOCK where ``_node_to_write`` settles for a read, and the difference is worth
    naming because that docstring declines this deliberately. What it declines is a lock
    on ``nodes``, taken for a whole apply — a host being dialled sits inside that window.
    This one is one row of ``users``, held for the two statements ``revoke_user`` runs
    after it, and the only thing it makes wait is another WRITE to the same person. The
    delivery endpoint does join this table (``Subscription.user`` is ``lazy="joined"``),
    and it is unaffected: a plain read never waits on a row lock, so a user fetching
    their subscription mid-revocation sees the row as it was committed and then, an instant
    later, as revoked — which is the outcome either way.

    ``synchronize_session=False``: with the default, SQLAlchemy would evaluate the
    criteria against objects this session is holding and mark a stale copy revoked in
    memory even where the row matched nothing. ``revoke`` below re-reads the column off
    the row for exactly that reason, and the two must not disagree.

    It does not commit. The caller's transaction is what makes the withdrawal durable —
    ``revocation.revoke_user`` records the audit entry between this and ``revoke``, and
    all three land together or not at all.
    """
    taken = await session.execute(
        update(User)
        .where(User.id == user_id, User.revoked_at.is_(None))
        .values(revoked_at=datetime.datetime.now(datetime.UTC))
        .execution_options(synchronize_session=False)
    )
    return taken.rowcount == 1


async def revoke(session: AsyncSession, *, user_id: str) -> list[NodeTransport]:
    """Withdraw a user's access everywhere, and report what must be re-pushed.

    Charter criterion 6. Three things happen, and all three are necessary:

    1. the user is marked revoked, so nothing can grant them access again;
    2. their subscriptions are revoked, so the URL they hold stops resolving;
    3. every credential is DELETED, so no node config can be rendered that still
       authorises them.

    Deleting rather than flagging is the point. A flag means every renderer must
    remember to filter on it, and the one that forgets leaves a user connected —
    which is precisely the failure the criterion is written against. With the rows
    gone, a re-render cannot include them even by mistake.

    Returns the node-transports whose configs changed. The database half alone does
    NOT complete a revocation: until those configs are pushed, the user's
    credential is still live in the running daemon on each node. The caller pushes;
    see ``services/apply.py``.

    THE ADDRESS IS FREED AT THIS COMMIT — M17 — which is strictly earlier than "no node
    still authorises it", and the difference is the window this note exists for.
    ``addresses.held_digests`` reads credential rows and nothing else, so the moment the
    rows above are deleted the address is the lowest free one and the next person granted
    takes it, while the node the revoked person was on may still carry their peer entry.
    What keeps that window shut today is the push and not the allocator: a failed apply
    marks the node DEGRADED (``apply._record_failure``), and a degraded node is not in
    ``nodes.serving_transports`` — so nobody is granted anything on it at all until it is
    applied successfully, and the address cannot be re-let in the meantime. What is NOT
    covered is an operator moving such a node back to serving by hand without applying
    it, where the console shows drift and the allocator does not read it. Closing that
    properly needs state this schema does not carry — which addresses a node was last
    applied with, not just a digest of the whole file.

    M17.1c DID NOT CLOSE IT, and that is a decision rather than an oversight: the column
    it needs is not in this schema and adding one is not what that step was written to do
    (``docs/decisions.md``, 2026-09-13). This note stays because the window is still open,
    and the next step that gives a node a record of what it was last applied WITH is the
    one that can shut it — not the next step that touches addresses.
    """
    user = await get_user(session, user_id)
    now = datetime.datetime.now(datetime.UTC)

    # The withdrawal time is decided against the ROW — M23, round 8, and the same lesson
    # ``nodes._node_to_write`` states for a node record. These sessions keep what they
    # loaded (``expire_on_commit=False``), so a user another session has already
    # withdrawn still reads ``revoked_at = NULL`` here, and the line below would then
    # overwrite that withdrawal's own timestamp with this call's. One named column rather
    # than a whole-object refresh, for ``_node_to_write``'s reason: these sessions are
    # ``autoflush=False`` and a refresh discards a pending edit instead of writing it
    # first.
    await session.refresh(user, ["revoked_at"])

    # Explicit queries for the same reason as in ``grant_everywhere``: lazy access on
    # an async session raises rather than loading.
    held = await session.execute(
        select(Credential).where(Credential.user_id == user.id)
    )
    credentials = list(held.scalars().unique())
    affected = [credential.node_transport for credential in credentials]

    for credential in credentials:
        await session.delete(credential)

    issued = await session.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    for subscription in issued.scalars().unique():
        subscription.revoked_at = subscription.revoked_at or now

    user.revoked_at = user.revoked_at or now

    await session.commit()
    logger.info("user revoked: %s (%d node configs to re-push)", user.id, len(affected))
    # De-duplicated by id: a user can hold two credentials on one node (two
    # transports), and pushing that node twice is wasted work on the one operation
    # that must complete quickly.
    unique: dict[str, NodeTransport] = {t.id: t for t in affected}
    return list(unique.values())
