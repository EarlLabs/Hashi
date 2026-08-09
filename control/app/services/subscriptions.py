"""Minting subscription tokens and rendering what a friend's client fetches.

WHAT: ``issue`` (a new token for a friend) and ``render`` (the base64 document the
      delivery endpoint returns).
WHY:  backlog item 8, charter criterion 5, and amendment A: a v1 subscription is a
      base64-encoded list of client-entry URIs. This module is `control`'s ENTIRE
      half of the transport contract — order the entries, compose the display text,
      append it as the fragment, join, encode.
HOW:  the arithmetic that proves the contract: adding a transport adds ZERO lines
      to this file. Nothing here parses ``entry``, branches on a transport name, or
      compares a label to a literal. It cannot, because it never learns which
      protocol produced any given line.
"""

import base64
import logging
import secrets as secrets_module
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.models import Credential, Friend, Subscription
from control.app.services import nodes
from edge.node import Credential as EdgeCredential
from edge.registry import ClientEntry, profile

logger = logging.getLogger(__name__)

# 32 bytes of urlsafe entropy, per the control rulebook's ">= 32 bytes" rule. This
# is the ONLY authentication on the delivery route, so it is sized to be
# unguessable rather than convenient.
TOKEN_BYTES = 32


def token_digest(token: str) -> str:
    """The indexed lookup key for a token.

    Delegates to the bound ``SecretBox``, which owns the derived digest key — this
    module never holds the secret. See ``SecretBox.digest`` for why the digest is
    keyed rather than a plain hash.
    """
    from control.app.models.base import secret_box

    return secret_box().digest(token)


def issue(session: AsyncSession, friend: Friend) -> Subscription:
    """Mint a fresh subscription for a friend. Does not commit.

    The digest is derived through the bound secret box rather than from a key passed
    in, so a caller cannot accidentally use a different key than lookups will —
    that would produce a subscription that exists and can never be found.
    """
    token = secrets_module.token_urlsafe(TOKEN_BYTES)
    subscription = Subscription(
        friend_id=friend.id,
        token=token,
        token_digest=token_digest(token),
    )
    session.add(subscription)
    return subscription


async def find_by_token(session: AsyncSession, token: str) -> Subscription | None:
    """Resolve a token to a live subscription, or ``None``.

    Returns None for unknown, revoked, and revoked-friend alike. The caller answers
    404 for all three — the control rulebook is explicit that a 403 would confirm a
    token once existed, which is more than a stranger should learn.

    The lookup is by digest, which is a single indexed equality comparison inside
    Postgres. That is what makes it constant-time with respect to the token's
    VALUE: there is no prefix scan and no early exit that a timing attack could
    measure to recover the token character by character.
    """
    digest = token_digest(token)
    result = await session.execute(
        select(Subscription).where(Subscription.token_digest == digest)
    )
    subscription = result.scalars().first()
    if subscription is None or not subscription.is_active:
        return None
    return subscription


def compose_label(entry: ClientEntry) -> str:
    """The display text a client shows for one entry.

    `control`'s job, not a transport's, because the fragment is a property of the
    subscription FORMAT that every scheme in it shares — writing it here means the
    charter's "pick an exit country" behaviour exists once instead of once per
    protocol.

    Country first: in a client's list, the country is what a friend is choosing by.
    """
    if entry.country_label and entry.country_label != entry.display_label:
        return f"{entry.country_label} · {entry.display_label}"
    return entry.display_label or entry.country_label


async def entries_for(session: AsyncSession, friend: Friend) -> list[ClientEntry]:
    """Every client entry this friend should currently receive.

    Built from their credentials, so a revoked friend yields nothing (their rows are
    gone) and a friend on a draft or degraded node yields nothing for it (the
    node-transport is not serving).
    """
    serving = {node_transport.id for node_transport in await nodes.serving_transports(session)}

    result = await session.execute(
        select(Credential).where(Credential.friend_id == friend.id)
    )

    rendered: list[ClientEntry] = []
    for credential in result.scalars().unique():
        if credential.node_transport_id not in serving:
            continue

        node_transport = credential.node_transport
        transport = profile(node_transport.transport_name)
        rendered.append(
            transport.profile.render_client(
                nodes.node_view(node_transport.node),
                nodes.render_params(node_transport),
                EdgeCredential(subject=credential.subject),
            )
        )

    # Sorted by the label a friend actually reads, so the list in their client does
    # not reorder itself between refreshes — a reordering list looks like nodes
    # appearing and disappearing.
    rendered.sort(key=lambda entry: (entry.country_label, entry.display_label, entry.entry))
    return rendered


async def render(session: AsyncSession, friend: Friend) -> str:
    """The subscription document, exactly as a client receives it.

    Base64 of newline-joined URIs — charter amendment A. Standard base64 with
    padding, because that is what the stock clients accept.

    An empty result is returned as an empty document rather than an error: a friend
    whose every node is temporarily degraded gets a subscription that resolves to
    nothing, and their client keeps its last-known config. A 500 here would make a
    node outage look like a revocation.
    """
    entries = await entries_for(session, friend)
    # The label is percent-encoded: it contains a space and a separator, and an
    # unencoded fragment is not a valid URI. Clients are forgiving about it, but a
    # friend's client is the one thing we cannot debug remotely.
    lines = [f"{entry.entry}#{quote(compose_label(entry))}" for entry in entries]
    document = "\n".join(lines)
    return base64.b64encode(document.encode()).decode()
