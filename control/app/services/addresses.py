"""Who holds which address on a transport that gives each user one — M17.

WHAT: the allocator. ``settle`` gives every credential on a row an address of its own,
      ``pool_of`` says what there is to give, ``edge_credential`` is the one place a
      stored credential becomes the value object ``edge`` renders from, and
      ``shortfalls`` answers "which pools cannot hold everybody" before anything is
      written. ``pin_in_use`` and ``stranded_by`` are M17.1c's pair, and they exist for
      one promise: an address a device already holds never moves — not by rotation, not
      by revocation, not by a resize and not by a replaced parameter. The first writes
      down the address a pre-pool row is already handing out; the second says why a
      proposed tunnel could no longer carry the addresses in hand, and how many of them
      each reason applies to.
WHY:  found in the field. A WireGuard-family transport had one ``peer_tunnel_address``
      for everybody, so it served exactly one friend against a charter scale of ~30-50 —
      and the second friend was refused at RENDER, after the row was committed, which
      blocks every later push to that node including a revocation's. The refusal itself
      is right and is untouched (``AmbiguousPeerRoute``: on a WireGuard server
      ``AllowedIPs`` is the authorisation list and the routing table at once, so two
      peers on one address is a silent hijack of the first one's return path). What this
      module adds is the second address, and a refusal that arrives before the commit.
HOW:  **it reads a transport's declaration and never a transport's name.**
      ``TransportMeta.peer_address`` says which parameter a consumer's own address is
      read from and which parameter's network bounds the pool; `control` writes neither
      name anywhere. A transport that says nothing is handed nothing and asked nothing,
      which is every VLESS row in this image.

      **The arithmetic is ``edge``'s.** ``edge.addressing`` enumerates a pool, says in
      one sentence why one cannot work, and canonicalises a host. Nothing here adds one
      to an address or compares two ranges.

      **Lowest free wins, in ``(created_at, id)`` order.** So allocation is a function of
      the rows rather than of when this ran, a revoked user's address is reused by the
      next person rather than stranded, and nothing a device already holds ever moves.

      **No lock is taken** — the same call as ``services/placement.py`` makes for ports,
      with the opposite backstop: the losing write here is refused by
      ``uq_credential_tunnel_address`` rather than accepted, so a race is a clean refusal
      and never a shared address. See ``friends.grant_everywhere``, which turns the
      constraint's own error into that refusal.

      **Nothing here is logged.** An address against a person is exactly the record the
      charter says is absent; it is not written to a log, an audit label or an exception
      message, and the sentences below name a node, a transport and counts only.
"""

import dataclasses
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.errors import Conflict
from control.app.models import (
    Credential,
    Node,
    NodeTransport,
    TransportPurpose,
    User,
)
from edge.addressing import carriage_problem, host_of, pool
from edge.node import Credential as EdgeCredential
from edge.registry import PeerAddress, discover

# The name of the box an operator sizes a pool in, and the key a refusal about that size
# is reported under. Not a field of any transport's own model — the size is a column on
# the node-transport record (``docs/decisions.md``, 2026-09-11) — so it needs a name of
# its own, defined once here for the service that refuses it, the form that renders it
# and the route that reads it back.
POOL_BOX = "pool_size"


class PoolFull(Conflict):
    """Every address in a transport's pool is already held by somebody.

    A ``Conflict`` (409) because it is the same shape as every other refusal about what
    already exists: the request was answerable, and the answer is that this pool has no
    room. Its own type so that a caller can tell it from an unrelated conflict and roll
    back on it — which is what makes "a pool too small changes nothing" true rather than
    hoped for.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class Shortfall:
    """One transport whose pool cannot hold everybody it would have to.

    Carries names and counts and no address: this is what a refusal is composed from and
    what M17.2 puts on screen, and neither may say who holds what.

    ``row`` is the node-transport's own id — the same opaque id every panel button
    already addresses — so the console can put the sentence beside the row it is about
    rather than working out which of a node's lines a shortfall belongs to. An id is not
    a person and not an address; it is what the operator just clicked.

    ``config_name`` is beside ``transport`` because M15 lets one node run two instances
    of one transport, and the sentence composed below is read where there may be no row
    to look at — the add-user dialog and the state dialog both list pools from across the
    fleet. Without it, two instances on one node produce two identical sentences and the
    operator cannot tell which of them they were sent to resize.
    """

    row: str
    node: str
    transport: str
    config_name: str
    size: int
    needed: int


def spec_for(transport_name: str) -> PeerAddress | None:
    """What this transport declared about giving each consumer an address, or ``None``.

    THE ONE PLACE `control` ASKS. Every other function here, and every caller in this
    zone, takes the answer from this — so no module in `control` writes the name of the
    parameter an address is read from, and a transport that names it something else is
    served without an edit anywhere in this zone.

    ``None`` for a transport this image does not ship, which is the same answer as "it
    hands out no addresses" and is the right one: a row naming a transport we cannot
    resolve gets no allocation, and the operator sees the missing transport where they
    already see it.
    """
    meta = discover().get(transport_name)
    return meta.peer_address if meta is not None else None


def pool_of(node_transport: NodeTransport, spec: PeerAddress | None = None):
    """Every address this row may hand out, lowest first, produced one at a time.

    A pool of ``pool_size`` starting at the address already in ``params`` — which is what
    makes a row enabled before M17 render the same bytes afterwards: ``pool_size`` is
    NULL there, the pool is one address long, and ``pool[0]`` is written exactly as the
    renderers' own fallback writes it.

    Lazy, because an operator may legitimately size a pool in the thousands and the
    caller wants the lowest free address rather than a list. It validates nothing —
    ``edge.addressing.pool_problem`` is the gate and is asked when the size is SET, which
    is the moment the operator is looking at the box.
    """
    spec = spec if spec is not None else spec_for(node_transport.transport_name)
    if spec is None:
        raise ValueError(
            f"transport {node_transport.transport_name!r} hands its consumers no "
            "address of their own, so it has no pool"
        )
    return pool(str(node_transport.params[spec.name]), node_transport.pool_size or 1)


async def held_digests(
    session: AsyncSession, node_transport: NodeTransport
) -> set[str]:
    """Which of this row's addresses are already somebody's, as digests.

    A function of its own rather than three lines inside ``settle`` because it is the
    READ the race is about: everything between this answer and the flush that follows it
    is the window in which another transaction can take the address this one is about to.
    Nothing serialises the two — no lock is taken, by decision — so the window is closed
    by ``uq_credential_tunnel_address`` refusing the loser, and that refusal is the one
    behaviour here a test cannot provoke by timing. Named, it can be made stale on
    purpose, which is how ``tests/control/test_every_user_holds_their_own_address.py``
    proves the refusal deterministically instead of racing two loops and hoping.

    Digests and never addresses: this is the one query that could otherwise decrypt every
    address on a row in order to compare them.
    """
    return set(
        (
            await session.execute(
                select(Credential.tunnel_address_digest)
                .where(Credential.node_transport_id == node_transport.id)
                .where(Credential.tunnel_address_digest.is_not(None))
            )
        ).scalars()
    )


async def settle(session: AsyncSession, node_transport: NodeTransport) -> list[Credential]:
    """Give every address-less credential on this row the lowest free address. No commit.

    Called by whatever granted the credentials, inside that caller's own transaction, so
    that a pool with no room refuses before anything commits.

    THE ORDER IS ``(created_at, id)`` and it is load-bearing three times over. It makes
    the allocation a function of the rows rather than of the order this happened to
    query them in; it means the first person on a row gets ``pool[0]``, which is the
    address a row enabled before M17 has always rendered, so a device already configured
    keeps working; and it makes the second user's address the same one on a replay.

    A credential that pre-dates M17 holds no address, and the ``(created_at, id)`` order
    is what ADOPTS it at ``pool[0]`` — the address its file already carries — rather than
    handing that address to somebody new. Nothing moves; what changes is that the address
    is written down, so the next person cannot be given it. On a row nobody sized the
    adoption is real but never survives, because such a pool is one address long: the
    person who arrived alongside gets nothing and the whole call is refused. Sizing that
    row is a later step (``replace_params``), and until it ships the adoption is visible
    only on a row an operator sized at enable.

    NOTHING IS WRITTEN WHEN IT REFUSES — not "nothing is committed", nothing at all: the
    allocation is planned in full and applied only once every waiting credential has an
    address. So a caller may catch ``PoolFull``, report it and go on with its own
    transaction. ``friends.grant_everywhere`` rolls back anyway, for a different reason
    that still holds (a refusal there poisons four other services' transactions).

    FLUSHES FIRST, and that is required rather than tidy: this application's sessions are
    built with ``autoflush=False`` (``control/app/db.py``), so a credential another
    service added moments ago in this same transaction is invisible to the query below
    until something flushes. Without it the allocator would hand the same address to
    everybody granted in one operation.

    Reads inside ``no_autoflush`` for the caller whose session was built differently: an
    autoflushing session would write the rows the caller has in hand between these two
    queries, and what this needs is one consistent picture of who holds what. The one
    flush that matters is the one at the end, which is where a race loses — see
    ``friends.grant_everywhere``, which turns that loss into a refusal.

    Returns the credentials it placed, which is empty when there was nothing to do — the
    ordinary case for a transport that declares no address at all.
    """
    spec = spec_for(node_transport.transport_name)
    if spec is None:
        return []

    from control.app.models.base import secret_box  # noqa: PLC0415

    await session.flush()

    with session.no_autoflush:
        held = await held_digests(session, node_transport)
        waiting = list(
            (
                await session.execute(
                    select(Credential)
                    .where(Credential.node_transport_id == node_transport.id)
                    .where(Credential.tunnel_address_digest.is_(None))
                    .order_by(Credential.created_at, Credential.id)
                )
            )
            .scalars()
            .unique()
        )

    if not waiting:
        return []

    box = secret_box()
    # ONE pass over the pool for all of them, rather than one search per credential: the
    # pool is lazy and may be thousands of addresses long, and both are the same answer
    # because the addresses come out lowest first and ``held`` only grows.
    #
    # PLANNED FIRST AND WRITTEN AFTERWARDS, which is what makes the refusal's own
    # sentence true at the moment it is raised rather than true because the caller
    # happens to roll back: assigning as it went left the credentials it had already
    # reached dirty in the session while the message said "Nothing has been changed",
    # and a caller that caught ``PoolFull`` to report a shortfall and then committed its
    # own work would have committed half an allocation — some people at a new address,
    # some not, with the node's ``AllowedIPs`` and the users' ``Address`` lines derived
    # from it.
    plan: list[tuple[Credential, str, str]] = []
    for address in pool_of(node_transport, spec):
        if not waiting:
            break
        digest = box.address_digest(node_transport.id, address)
        if digest in held:
            continue
        held.add(digest)
        plan.append((waiting.pop(0), address, digest))

    if waiting:
        node = await session.get(Node, node_transport.node_id)
        # Singular when it is one person, because this sentence is what an operator reads
        # at the moment a pool refuses them and "1 more friends" is the kind of seam that
        # makes a product look machine-written.
        short = len(waiting)
        needing = (
            f"{short} more friend needs one" if short == 1
            else f"{short} more friends need one"
        )
        raise PoolFull(
            f"{node_transport.transport_name} on {node.name if node else '?'} gives "
            f"every friend an address of its own and its pool holds "
            f"{node_transport.pool_size or 1}: {len(held)} are taken and "
            f"{needing}. Nothing has been changed. Make the "
            "pool bigger on that transport, or take somebody off it."
        )

    for credential, address, digest in plan:
        # Stored as the pool wrote it — WITH the prefix — because that is the form the
        # renderer puts in the interface's ``Address`` line. The digest is over the bare
        # host, so a prefix that changes is still the same allocation.
        credential.tunnel_address = address
        credential.tunnel_address_digest = digest

    await session.flush()
    return [credential for credential, _, _ in plan]


async def pin_in_use(
    session: AsyncSession, node_transport: NodeTransport
) -> Credential | None:
    """Write down the address this row is ALREADY handing out, before anything moves it.

    A credential with no address of its own renders the row's own parameter — that is the
    renderers' fallback, and ``pool[0]`` is written byte-identically to it (see
    ``edge.addressing.pool``). So on a row that pre-dates M17 the address a device is
    configured with is not recorded anywhere: it is implied by the parameter, and the
    moment that parameter is replaced the device's address has silently moved. Pinning is
    what makes the promise "nothing moves an address a device holds" checkable at all —
    once it is written down, every rule in this module protects it.

    Called by ``rotation.replace_params`` BEFORE it validates a new pool, which is the
    order the whole repair depends on: the pinned address is then one of the held
    addresses the new pool is measured against, so a resize that would strand the working
    device is refused rather than performed.

    EXACTLY ONE CREDENTIAL CAN BE PINNED, and that is a fact about the row rather than a
    limit chosen here: there is one fallback address, so every address-less credential on
    the row renders THE SAME one. That is the field's broken row — two people issued the
    same address, which is why the node's own config refuses to render (``AmbiguousPeerRoute``).
    The earliest in ``(created_at, id)`` order keeps it, which is ``settle``'s own
    adoption rule and the one that leaves the first person on the row where they were;
    whoever came after has no address that works today and is given a real one from the
    new pool a moment later.

    Nothing is pinned when that address is already somebody's — the row is past the
    upgrade, and the address-less credentials on it are new arrivals ``settle`` will place.

    No commit: the caller owns the transaction, and a refusal after this must leave the
    row exactly as it was.
    """
    spec = spec_for(node_transport.transport_name)
    if spec is None:
        return None

    from control.app.models.base import secret_box  # noqa: PLC0415

    await session.flush()

    with session.no_autoflush:
        held = await held_digests(session, node_transport)
        waiting = (
            (
                await session.execute(
                    select(Credential)
                    .where(Credential.node_transport_id == node_transport.id)
                    .where(Credential.tunnel_address_digest.is_(None))
                    .order_by(Credential.created_at, Credential.id)
                )
            )
            .scalars()
            .unique()
            .first()
        )

    if waiting is None:
        return None

    in_use = next(pool_of(node_transport, spec))
    digest = secret_box().address_digest(node_transport.id, in_use)
    if digest in held:
        return None

    # Stored exactly as the pool writes it, prefix included — the form the renderer puts
    # in the interface's ``Address`` line, so the file this person already has is the file
    # they keep getting.
    waiting.tunnel_address = in_use
    waiting.tunnel_address_digest = digest
    await session.flush()
    return waiting


async def stranded_by(
    session: AsyncSession, node_transport: NodeTransport, *, within: str
) -> dict[str, int]:
    """Why a new tunnel could not carry addresses already handed out here, and how many.

    The other half of "nothing moves an address a device holds": nothing here MOVES one,
    so the danger is not the address changing but the tunnel changing under it. Narrow the
    range, shift it, or move the node's own address onto somebody's, and that person's
    address is still in the database, still in their config file, and no longer reachable
    — or worse, now the node's own, which authorises them to send as the node.

    Each held address is asked of ``edge`` against the proposed tunnel: the same rules the
    operator met when they sized the pool, applied one person at a time. That is
    deliberately not "is it inside the new pool's run" — an address below or above the run
    is still carried by the interface and is never re-handed to anybody else, because
    ``settle`` skips every digest already held, so it costs a slot and nothing else. What
    is refused here is an address the tunnel could not carry at all.

    CAUSES WITH COUNTS, and never an address. A count alone was what shipped first, and
    the refusal built from it had to name ONE cause for five conditions — so an operator
    who had moved the node's own address onto somebody's was told their address "would
    fall outside" a range it was inside, and the obvious response (a wider prefix) left
    the sentence unchanged. ``edge.carriage_problem`` answers with the cause as a clause
    that names nothing it was handed, which is what lets the answer stay counts: which
    person holds which address is the one record this project does not produce.

    Sorted, so two identical refusals read identically — the rows come back in whatever
    order the database liked.

    THE ADDRESS COLUMN AND NOT THE ROW, because a ``select(Credential)`` here would
    decrypt every holder's key material and subject as well (both are ``EncryptedText``,
    and ``Credential.user`` / ``.node_transport`` are joined eagerly) to read one
    address. The module header makes a point of ``held_digests`` being the one query that
    could otherwise decrypt every address on a row; this is the second, and it decrypts
    addresses and nothing else.
    """
    if spec_for(node_transport.transport_name) is None:
        return {}
    with session.no_autoflush:
        held = (
            (
                await session.execute(
                    select(Credential.tunnel_address)
                    .where(Credential.node_transport_id == node_transport.id)
                    .where(Credential.tunnel_address.is_not(None))
                )
            )
            .scalars()
            .all()
        )
    counted: dict[str, int] = {}
    for address in held:
        cause = carriage_problem(host_of(address), within)
        if cause is not None:
            counted[cause] = counted.get(cause, 0) + 1
    return dict(sorted(counted.items()))


def edge_credential(
    credential: Credential, spec: PeerAddress | None
) -> EdgeCredential:
    """One stored credential as the value object ``edge`` renders from.

    THE ONE BUILDER, and that is the whole point of it existing rather than two call
    sites each doing the obvious thing. The node's config authorises a peer by the
    address in its ``AllowedIPs`` and the user's own file configures the same address in
    its ``Address`` line: those are two renders of one fact, produced by two different
    services, and if only one of them overlaid the allocation the person would be
    authorised for an address their device does not use — a tunnel that comes up and
    carries nothing, with every screen green.

    ``spec`` is the transport's own declaration, resolved once per node-transport by the
    caller rather than per credential, and ``None`` for a transport that hands out no
    addresses — in which case this is exactly what both call sites built before M17.

    ONE BUILDER OF THE TWO RENDERS THAT MUST AGREE, which is narrower than "every
    ``EdgeCredential`` in this zone": ``subscriptions.entries_for`` builds its own, with
    no secrets at all, for the URI shape. That is pre-M17 behaviour and is left alone
    here — no transport in this image declares both ``peer_address`` and a URI form, and
    routing it through this function would change the input every URI renderer is given.
    The transport that declares both is the one that has to close it.
    """
    secrets = json.loads(credential.secrets)
    if spec is not None and credential.tunnel_address:
        # Under the name the TRANSPORT declared. The renderers read a consumer's own
        # address from their client-scoped material first and fall back to the row's
        # parameter, so this overlay is what makes the second user's config differ from
        # the first's — and its absence is what keeps a pre-M17 credential rendering the
        # bytes it always did.
        secrets[spec.name] = credential.tunnel_address
    return EdgeCredential(subject=credential.subject, secrets=secrets)


async def fleet_size(session: AsyncSession, *, extra: int = 0) -> int:
    """How many people a pool on a serving row has to hold. ONE definition, three readers.

    Counts ACTIVE FRIENDS rather than credentials held, deliberately: every active friend
    gets a credential on every serving row, so that count is what the pool must hold, and
    reading the credentials instead would answer "is it full now" — which is a different
    question, and the one that lets a row be enabled at a size it can never satisfy.

    A function of its own because three places ask it and they must not drift: the
    refusal when a friend is added (``shortfalls`` below), the refusal when a pool is
    sized at enable (``nodes.sized_pool``), and the floor in the enable dialog's own
    placeholder (``console.pool_boxes``). Each had written the query out again. Change
    who counts as being in the fleet with three copies and the console offers a floor the
    service refuses, with nothing red anywhere.

    ``extra`` is how many people are about to be added — one, for a friend being created.
    """
    return (
        await session.execute(
            select(func.count()).select_from(User).where(User.revoked_at.is_(None))
        )
    ).scalar_one() + extra


async def shortfalls_among(
    session: AsyncSession, rows: list[NodeTransport], *, extra: int = 0
) -> list[Shortfall]:
    """Which of THESE rows cannot hold everybody they would have to — M17.2.

    ONE MEASUREMENT, THREE POPULATIONS. ``shortfalls`` below asks it of the serving
    fleet, which is what somebody being added meets. The console asks it of one node's
    own rows, because an action has to be withheld BEFORE the operator commits to it:
    offering a withdrawn transport and moving a node to serving each grant every active
    friend an address on rows that are not serving yet, so neither is visible to the
    serving query and both used to be refused only after the press. Measuring that in
    the console would have been a third copy of "what a pool has to hold", which is the
    drift ``fleet_size`` and ``nodes.sized_pool`` already exist to prevent.

    FRIEND-FACING ROWS ONLY, and only where the transport declares each consumer needs
    an address. A hop end hands nothing to anybody and is refused a size outright
    (``rotation._resize``), so measuring its absent pool against the fleet would report a
    shortfall on the runbook's own entry box — an action withheld over a number that row
    is not allowed to have. ``serving_transports`` already filters the same way, so this
    is not a change to what ``shortfalls`` answers.
    """
    people = await fleet_size(session, extra=extra)

    short: list[Shortfall] = []
    for row in rows:
        if row.purpose != TransportPurpose.FRIENDS:
            continue
        if spec_for(row.transport_name) is None:
            continue
        size = row.pool_size or 1
        if size >= people:
            continue
        node = await session.get(Node, row.node_id)
        short.append(
            Shortfall(
                row=row.id,
                node=node.name if node else row.node_id,
                transport=row.transport_name,
                config_name=row.config_name,
                size=size,
                needed=people,
            )
        )
    return short


async def shortfalls(session: AsyncSession, *, extra: int = 0) -> list[Shortfall]:
    """Every serving pool whose size is below the friends it would have to hold.

    ``extra`` is how many people are about to be added — one, for a friend being
    created, so the refusal arrives before the friend, their subscription and their
    credentials are written rather than after ``settle`` has already been handed an
    impossible job.

    Serving rows only, which is the whole population a friend is granted on. A row being
    enabled in this transaction is not one of them and is not asked about here: it is
    measured by ``nodes.sized_pool`` while the operator is still looking at the box,
    against the same count this uses.
    """
    from control.app.services import nodes  # noqa: PLC0415

    return await shortfalls_among(
        session, await nodes.serving_transports(session), extra=extra
    )


def named(short: Shortfall) -> str:
    """One pool, in the words every refusal about a pool already uses.

    Its own function because three surfaces now name the same pool and they must not
    drift: the refusal when somebody is added (``too_small`` below), the add-user dialog
    listing what is full, and the two actions the console withholds over a short pool
    (``services/console.py``). The operator meets this phrase in all three and should not
    have to recognise it twice.

    Names the node and the transport — both already on the screen it appears on — and the
    two counts. Nothing about any person, and no address.

    "IS SIZED FOR", not "holds". The Keys & configs screen beside these says ``2 of 10``
    for the same row, where the first number is the people HOLDING an address; a sentence
    here saying "holds 10" would be the same verb for the other quantity, and the
    operator following this sentence's own instruction lands on that screen. One word
    each: a pool is sized, a person holds.

    The transport is qualified the way every screen that lists a node's rows qualifies it
    (``console.placed_as``), because two instances of one transport on one node are
    ordinary since M15 and this sentence is read where the row itself may not be. Imported
    where it is used rather than at the top: ``console`` imports this module, and the one
    string both need to compose is not worth a third module or a second copy of the rule.
    """
    from control.app.services.console import placed_as  # noqa: PLC0415

    return (
        f"{placed_as(short.transport, short.config_name)} on {short.node} is sized for "
        f"{short.size} and would need {short.needed}"
    )


def too_small(short: list[Shortfall]) -> str:
    """What an operator is told about pools that cannot hold everybody.

    One sentence whatever the number of rows, because the operator's next action is the
    same for each: make the pool bigger. Names the node and the transport — both values
    already on screen — and the two counts, and nothing about any person.
    """
    listed = "; ".join(named(row) for row in short)
    return (
        f"a transport that gives every friend an address of its own has too small a "
        f"pool: {listed}. Nothing has been changed — make the pool bigger on that "
        "transport first."
    )
