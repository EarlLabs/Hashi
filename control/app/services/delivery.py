"""What a node is handed so a user can refresh against it — M27.2.

WHAT: ``artifacts_for_node`` — the pre-rendered subscription material for one node,
      narrowed to that node's own users, under the name each artifact is placed by.
WHY:  M27. `/sub/{token}` is served by the host the control plane lives on, so the
      one endpoint a user needs at the moment a node is blocked is behind whichever
      border the control plane is on. Rendering a subscription needs the database, so
      what moves to a node is the rendered result, pushed on apply over the channel
      that already exists — control plane to node, never the reverse.
HOW:  the two shapes ``services/subscriptions`` already produces, rendered over the
      rows one apply is pushing to one node, and nothing else.

THE NAME IS A ONE-WAY DIGEST OF THE TOKEN, AND THAT IS THIS MODULE'S ONE DECISION.

A stateless server can look a request up only by what the path carries, so the naive
store is one file per token — and a seized delivery host would then yield the live
bearer credential of every user it serves, in the clear, in a form the control
database never holds it in (``Subscription.token`` is ``EncryptedText``, and lookup
goes through a keyed digest). Those tokens open the control plane's own route as
well, where the answer is the un-narrowed subscription; a subscription token has no
expiry, and the URL is the only artefact a user holds, so the repair would be
re-issuing every affected URL.

So no token is written to a node. ``artifact_name`` derives the name with SHA-256
over a fixed label and the token, and a seized host yields digests it cannot invert:
the token is 32 bytes of this control plane's own entropy (``TOKEN_BYTES``), which is
the same argument ``SecretBox.digest`` makes for not using a slow KDF, pointed the
other way — there is no dictionary to run against these.

UNKEYED, deliberately. A keyed digest (``SecretBox.digest``) would be stronger against
an attacker who already holds a token and wants to know whether this host serves that
user — and it would put the derivation out of reach of anything that does not hold the
master key, which is every node and every future reader of this material, for ever.

AND PER HOST, which is M27.3's decision and the one this module's name derivation
carries. The listener a delivery host runs is a file server: it answers the path it is
given and hashes nothing, so the NAME is what a user's client sends and therefore the
credential that fetches an artifact. Salted with the node's own id, one seized host's
names fetch nothing on any other delivery host — which is the whole of what this
milestone's narrowing is for, applied to the fetch as well as to the contents. What it
costs is that a delivery URL is per host: the path a user holds for host H is not the
path for host J, and it is not ``/sub/{token}`` either, so the two URLs a user may hold
cannot be moved by changing a DNS record alone. That cost is M27.7's to carry, and is
recorded in ``docs/decisions.md`` under 2026-09-26.

WHICH HOSTS SERVE DELIVERY IS ``is_delivery_host`` BELOW, and it is derived rather than
asked for (M27.4). What this module still does not do: it does not stand up a listener —
that is ``edge.bootstrap.delivery_site``, which nothing wires in yet, because a site
block needs an address and a port and both are M27.6's — and it does not put a delivery
URL in front of a user (M27.7). What it produces is placed on the node by
``services/apply``.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.models import (
    Credential,
    Node,
    NodeTransport,
    Subscription,
    TransportPurpose,
)
from control.app.services import subscriptions
from edge.bootstrap import NodeConnection, delivery, node_stack
from edge.registry import SubscriptionFormat

# Domain separation, in the shape ``crypto.py``'s derivation labels use and for the
# same reason: a digest computed here can then never coincide with a digest of the
# same token computed anywhere else, now or later. It is not a secret — whatever
# serves this material has to be able to be handed the same value, and it cannot hold
# a key.
#
# ``v2`` since M27.3, and the version in a label is exactly what it is for: the name is
# now derived per HOST as well as per token, so the same subscription is a different
# file on every delivery host. A host handed v2 names by an apply that follows a v1 one
# is not a migration to worry about — the push REPLACES the directory, so the previous
# names are gone in the same call (``edge.bootstrap.delivery.place_delivery``).
_ARTIFACT_NAME_LABEL = b"hashi/delivery-artifact-name/v2"

# The compose project this control plane's own stack is deployed as — ``name:`` in
# ``deploy/docker-compose.yml``, which sets it explicitly so that it is a property of
# this product rather than of whatever directory somebody cloned into.
# A test in ``tests/control`` reads that file and holds the two together — the way this
# zone already holds its own route and the delivery site's together. A value copied
# across a zone boundary that nothing compares is a value that drifts, and this one
# would drift silently in the direction that looks safe: every co-located box would
# start being told it is a stranger.
CONTROL_STACK_PROJECT = "hashi"


def artifact_name(node_id: str, token: str) -> str:
    """The name one subscription's material is placed and fetched under on ONE host.

    One way: see this module's header for why the name is derived from the token
    rather than being it, and why the derivation is unkeyed.

    PER HOST, and that is M27.3's decision rather than a detail of this function. The
    name is what a request carries — the listener a delivery host runs serves the file
    the path names and cannot hash anything — so the name IS the credential that fetches
    the artifact. Without the node's own id in it, one seized host's names would fetch
    the same users' artifacts from every other delivery host, which is the cross-host
    narrowing this milestone exists to provide. The id is not a secret and is not
    holding anything shut: what it buys is that two hosts' names for one subscription
    are unrelatable without the token, which nothing outside this control plane has.

    The node's ID and never its address: an address is operator-editable and a node
    legitimately changes one, which would rename every artifact on that host on the
    next apply and dead-link every URL a user holds for it.

    Deterministic, so a user's artifact keeps the same name across applies on one host
    and a push replaces the file it replaced last time instead of accumulating one per
    apply.

    The separator is what keeps the two fields from running together: a node id is
    fixed-width today (``models.new_id``) and this does not depend on it, because a
    byte that cannot occur in either field is cheaper than an assumption about one.
    """
    return hashlib.sha256(
        _ARTIFACT_NAME_LABEL + node_id.encode() + b"\x00" + token.encode()
    ).hexdigest()


async def is_delivery_host(
    connection: NodeConnection, *, enabled: list[NodeTransport]
) -> bool:
    """Should this host serve its own users their subscriptions — M27.4.

    DERIVED, NEVER ASKED FOR, and that is the whole of this function. The three roles
    this product has — control plane, entry, leaf — are placed on one, two or three
    machines in any combination, and which country each sits in is not the product's
    business; a setting for "this one is a delivery host" would be a way to get the
    arrangement wrong, and an operator who has never read M27 would have to know to
    leave it off. So both halves below are read off things that are already true.

    FIRST HALF: does anyone fetch from this host at all. A node with no user-facing row
    carries nobody — the far end of a hop is not a user's to hold — so there is nothing
    for a listener here to answer and nobody who would ask. That covers the leaf in
    every arrangement, and it is asked off the row's own PURPOSE rather than off any
    transport's name.

    SECOND HALF: is this host already the one a user refreshes against. Where the
    control plane sits on this box, ``/sub/{token}`` is served from it already, and a
    second answer for the same document would be a second name, a second certificate
    and a second listener on one machine — the feature INERT rather than absent, which
    is what M27.4 forbids.

    It is measured on the host rather than compared between records, and that is not
    fastidiousness. ``docs/deploy/runbook.md`` has the operator register a co-located
    box with its public IP, while ``HASHI_PUBLIC_HOST`` must be a NAME with a real DNS
    record (``.env.example`` says so, because a public CA will not issue for an
    address) — so the two truthful values for one machine are two different strings,
    and a comparison of them would answer "not co-located" for the arrangement this
    milestone is most careful about. What cannot be spelled two ways is the host: a box
    that holds this control plane's own compose project is that control plane's box.

    WHAT THIS ASSUMES, named because it is the expensive failure direction: that this
    control plane is deployed by compose, under the name above, on the engine the node's
    own SSH account talks to. A control plane run some other way — outside compose, or
    under a daemon that account does not reach, a rootless one or a non-default context —
    is invisible here, and its own box then reads as a stranger and is offered delivery.
    That is a supported-install assumption rather than a check, and there is nothing on
    the host to check it against: the alternative is a setting, which is the one thing
    this function exists not to have.

    A HOST THAT CANNOT ANSWER IS NOT AN EMPTY ANSWER. ``compose_projects`` raises rather
    than returning nothing, and that is not caught here: a reading this control plane
    could not take is the caller's to answer for, and an empty set invented here would
    mean "nothing of ours is on this box" — the one answer that puts a second listener
    on the machine that already has one.

    The false answer costs nothing on a box that already has everything — the control
    plane's own host holds the database and the master key, so a host judged co-located
    that is not simply keeps no second copy — and the true one is what keeps a second
    listener off a machine that already answers.
    """
    if not any(row.purpose == TransportPurpose.USERS for row in enabled):
        return False
    return CONTROL_STACK_PROJECT not in await node_stack.compose_projects(connection)


async def artifacts_for_node(
    session: AsyncSession, node: Node, enabled: list[NodeTransport]
) -> list[delivery.Artifact]:
    """Both shapes of every subscription this node's own users would fetch from it.

    ``enabled`` is the rows this apply is pushing, handed in rather than queried
    again: the material has to describe the configuration the host is being given in
    the same call, and a node going into service is not yet in
    ``nodes.serving_transports`` while that apply is running.

    NARROWED TO THIS NODE'S OWN MATERIAL, which is the 2026-09-26 decision in
    ``docs/decisions.md``: the artifact for host H holds only the client entries whose
    node is H, so no other node's address is written to a host that may be seized.
    The narrowing is the row set, not a filter over a rendered document — a shorter
    list is a valid subscription in both shapes.

    AND NOTHING IS ADDED TO SAY SO — M27.5, and it is the answer to both ways this
    differs from what ``/sub/{token}`` would hand the same person. No marker naming when
    it was rendered, no entry saying what is missing, no note beside the entries.

    A SNAPSHOT of what, is the first half. This is rendered over the rows one apply is
    placing, and the node's own server configs are rendered over the same rows in the
    same call — so the material a host serves describes the configuration that host is
    RUNNING, and it can only be behind the database in the state where the daemon is
    behind it too. There is nothing true to tell a user there: the answer they get is the
    one they can actually connect on. The panel's sentence for that state names nodes,
    states and two buttons, and none of the three is a user's.

    A SLICE is the second half, and it gets the same silence for a different reason. From
    the second user-facing node onward this returns strictly less than the whole
    subscription, which a user cannot tell apart from a revocation. Saying so in the
    artifact would mean this function learning, per user, whether that user holds
    material on some other host — and writing that onto a host that may be seized is
    worse than the addresses the narrowing above removes, because it says "this person
    has other nodes" once per person. An unconditional sentence learns nothing per user
    and for that reason is not this function's to write: it is a property of the product
    and belongs with the URL, not in the document. See ``docs/decisions.md``, 2026-09-27.

    RELAY ROWS ARE NOT IN IT, on the purpose the row already carries rather than on
    any transport's name: the far end of a hop is not a user's to hold, and no
    credential points at one.

    Returns an empty list for a node whose enabled rows carry nobody, and the empty
    list is not a no-op downstream: ``place_delivery`` replaces the directory with an
    empty one. That is what empties a host that still has a transport enabled and has
    stopped carrying users — a delivery host with nobody on it, which is a different
    state from a host that does not serve delivery and is not asked for here. Which of
    the two a host is, and what a host with NOTHING enabled gets, is ``apply``'s: it
    reads ``is_delivery_host`` above and never calls this for the second one.

    A TOKEN THIS CONTROL PLANE CANNOT DECRYPT RAISES OUT OF HERE and is not skipped.
    The column is decrypted as the row is loaded, so the ``select`` below raises
    ``SecretUnreadable`` for the whole node; it is in ``apply._NOT_PER_NODE`` and is
    answered as "this control plane cannot read its own secrets" rather than as a
    fault of this node. Catching it per subscription is not available at this seam,
    and would be the wrong answer anyway: a node handed material for some of its users
    and silently not others is worse than an apply that says the key is wrong.
    """
    # THE NARROWING, HELD AT THE SEAM rather than assumed of the caller. Everything
    # below is rendered over these rows, so a row belonging to another node would put
    # that node's address into this host's artifact — the one thing the decision above
    # forbids, and a mistake nothing downstream could see. It raises rather than
    # filtering: a caller passing rows from two nodes has asked for something this
    # function cannot answer, and quietly answering for one of them would hide it.
    elsewhere = sorted({row.node_id for row in enabled if row.node_id != node.id})
    if elsewhere:
        raise ValueError(
            f"delivery material for node {node.id} was asked for over rows belonging "
            f"to {len(elsewhere)} other node(s) — the artifact a host is given holds "
            "that host's own material and nothing else"
        )

    user_facing = [row for row in enabled if row.purpose == TransportPurpose.USERS]
    if not user_facing:
        return []

    # Everyone this node actually carries. Read off the credentials rather than off the
    # user table, so a user who holds nothing on this host contributes nothing to it —
    # which is the same narrowing one level up from the entries themselves.
    held = await session.execute(
        select(Credential).where(
            Credential.node_transport_id.in_([row.id for row in user_facing])
        )
    )
    users = {
        credential.user.id: credential.user
        for credential in held.scalars().unique()
        # A revoked user's credential rows are deleted rather than flagged, so this is
        # the belt-and-braces filter ``render_for_node`` applies to the same rows.
        if credential.user.is_active
    }
    if not users:
        return []

    live = await session.execute(
        select(Subscription).where(Subscription.user_id.in_(users))
    )
    by_user: dict[str, list[Subscription]] = {}
    for subscription in live.scalars().unique():
        if subscription.is_active:
            by_user.setdefault(subscription.user_id, []).append(subscription)

    artifacts: list[delivery.Artifact] = []
    for user_id, held_subscriptions in by_user.items():
        user = users[user_id]
        # Rendered once per user and placed under each of their live subscriptions'
        # names: two links to one person are two names for one document, and re-rendering
        # per link would mean the same fleet could produce two different answers inside
        # one apply.
        document = await subscriptions.render(session, user, over=user_facing)
        archive = subscriptions.archive_of(
            await subscriptions.config_files_for(session, user, over=user_facing)
        )
        for subscription in held_subscriptions:
            name = artifact_name(node.id, subscription.token)
            artifacts.append(
                delivery.Artifact(
                    name=name,
                    shape=SubscriptionFormat.V1_URI_LIST,
                    content=document.encode(),
                )
            )
            # BOTH SHAPES, always, including the empty archive's note. It is about the
            # SHAPE and not the contents, which the row set above has already narrowed:
            # a user who asks this host for the archive and finds no file has been
            # answered something different from an archive saying there is nothing in it
            # right now, and the second is what this product decided that state says.
            artifacts.append(
                delivery.Artifact(
                    name=name,
                    shape=SubscriptionFormat.CLIENT_CONFIG_FILE,
                    content=archive,
                )
            )
    return artifacts
