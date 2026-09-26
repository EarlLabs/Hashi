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

UNKEYED, deliberately, and this is the part a later step depends on. A keyed digest
(``SecretBox.digest``) would be stronger against an attacker who already holds a
token and wants to know whether this host serves that user — and it would put the
derivation out of reach of anything on the node, because the key is the master key.
Whatever serves this directory can then never map ``/sub/{token}`` onto a file, so
every user would have to be handed a second, differently-shaped URL. An unkeyed
digest leaves both routes open: a server that hashes the path segment serves the URL
a user already holds, and one that cannot serves the digest as the path. Which of
those M27.3 builds is not decided here, and neither is foreclosed.

WHAT THIS MODULE DOES NOT DO: it does not decide which hosts serve delivery (M27.4),
it does not stand up a listener, and nothing here is reachable by a user yet. What it
produces is placed on the node by ``services/apply`` and read by nothing.
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
from edge.bootstrap import delivery
from edge.registry import SubscriptionFormat

# Domain separation, in the shape ``crypto.py``'s derivation labels use and for the
# same reason: a digest computed here can then never coincide with a digest of the
# same token computed anywhere else, now or later. It is not a secret — whatever
# serves this material has to compute the same value from the same token, and it
# cannot hold a key.
_ARTIFACT_NAME_LABEL = b"hashi/delivery-artifact-name/v1"


def artifact_name(token: str) -> str:
    """The name one subscription's material is placed and fetched under.

    One way: see this module's header for why the name is derived from the token
    rather than being it, and why the derivation is unkeyed.

    Deterministic, so a user's artifact keeps the same name across applies and a push
    replaces the file it replaced last time instead of accumulating one per apply.
    """
    return hashlib.sha256(_ARTIFACT_NAME_LABEL + token.encode()).hexdigest()


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

    RELAY ROWS ARE NOT IN IT, on the purpose the row already carries rather than on
    any transport's name: the far end of a hop is not a user's to hold, and no
    credential points at one.

    Returns an empty list for a node that carries nobody, which is what makes a host
    that stops carrying users stop holding delivery material — ``place_delivery``
    replaces the directory with an empty one rather than skipping the push.

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
            name = artifact_name(subscription.token)
            artifacts.append(
                delivery.Artifact(
                    name=name,
                    shape=SubscriptionFormat.V1_URI_LIST,
                    content=document.encode(),
                )
            )
            # BOTH SHAPES, always, including the empty archive's note: what a user
            # fetches from this host must be what they would have been answered on the
            # same route by the control plane, and an absent file is a different answer
            # from an archive saying there is nothing in it right now.
            artifacts.append(
                delivery.Artifact(
                    name=name,
                    shape=SubscriptionFormat.CLIENT_CONFIG_FILE,
                    content=archive,
                )
            )
    return artifacts
