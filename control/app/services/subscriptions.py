"""Minting subscription tokens and rendering what a friend's client fetches.

WHAT: ``issue`` (a new token for a friend) and the two shapes the delivery endpoint
      returns — ``render`` (the base64 document) and ``config_files_for`` /
      ``archive_of`` (per-client configuration files).
WHY:  backlog item 8, charter criterion 5, and amendment A: a v1 subscription is a
      base64-encoded list of client-entry URIs. This module is `control`'s ENTIRE
      half of the transport contract — order the entries, compose the display text,
      append it as the fragment, join, encode.

      The second shape is backlog item 27, and it is the charter's largest open
      question of phase 1 answered: the owner chose option (b) on 2026-08-09 —
      per-client config files behind the same token, rather than betting on what a
      third party's client will accept. Both shapes live here, behind ONE token and
      ONE route, because the token in the path is a bearer credential and every rule
      that protects it is written for that one route.
HOW:  the arithmetic that proves the contract: adding a transport adds ZERO lines
      to this file. Nothing here parses ``entry`` or a file's contents, branches on a
      transport name, or compares a label to a literal. It cannot, because it never
      learns which protocol produced any given line. Adding a FORMAT adds one
      function; adding a protocol adds none.
"""

import base64
import io
import logging
import secrets as secrets_module
import zipfile
from collections.abc import Sequence
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.models import Credential, Friend, Subscription
from control.app.services import addresses, nodes
from edge.node import Credential as EdgeCredential
from edge.registry import ClientConfig, ClientEntry, SubscriptionFormat, profile

logger = logging.getLogger(__name__)

# A fixed date for every archive entry. Not "now": see ``archive_of``. 1980-01-01 is
# the earliest a ZIP entry can express, so it reads as "deliberately none" rather than
# as a plausible-but-wrong build time.
ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

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
        if SubscriptionFormat.V1_URI_LIST not in transport.meta.subscription_formats:
            # Not this shape. Necessary since item 27 and not before it: until the
            # endpoint could deliver a file, a transport with no URI form could not be
            # enabled for friends at all, so this loop only ever met URI transports.
            # Now one node can carry both, and without this line a friend holding a
            # file transport would get a 500 on their ordinary subscription link —
            # their whole access broken by a node they were merely also given.
            continue

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


async def config_files_for(session: AsyncSession, friend: Friend) -> list[ClientConfig]:
    """Every configuration FILE this friend should currently receive — item 27.

    The second representation, and `control`'s whole half of it: ask each transport
    that declared it produces a file to produce one, then order and name the results.
    Nothing here reads a file's contents, and nothing compares a transport name to a
    literal — the arithmetic is the same as ``entries_for``'s, and adding a transport
    still adds zero lines.

    A friend on only URI transports gets an empty list, which is correct rather than an
    error: they have nothing in this shape, and the endpoint says so with an empty
    archive for the same reason ``render`` returns an empty document.
    """
    serving = {node_transport.id for node_transport in await nodes.serving_transports(session)}

    result = await session.execute(
        select(Credential).where(Credential.friend_id == friend.id)
    )

    produced: list[ClientConfig] = []
    for credential in result.scalars().unique():
        if credential.node_transport_id not in serving:
            continue

        node_transport = credential.node_transport
        transport = profile(node_transport.transport_name)
        if SubscriptionFormat.CLIENT_CONFIG_FILE not in transport.meta.subscription_formats:
            # Not this shape. Skipped rather than refused: a friend with one URI
            # transport and one file transport must get the file, not an error about
            # the other one.
            continue

        produced.append(
            transport.serialise(
                SubscriptionFormat.CLIENT_CONFIG_FILE,
                nodes.node_view(node_transport.node),
                nodes.render_params(node_transport),
                # THE SAME BUILDER the node's own config is rendered from — M17. This
                # file's ``Address`` line and that config's ``AllowedIPs`` are two
                # renders of one allocation, and a second builder here is exactly how a
                # person ends up authorised for an address their device does not use:
                # a tunnel that comes up and carries nothing, with every screen green.
                addresses.edge_credential(
                    credential, addresses.spec_for(node_transport.transport_name)
                ),
            )
        )

    # Same ordering rule, and the same reason, as ``entries_for``: a list that reorders
    # itself between refreshes looks like nodes appearing and disappearing.
    produced.sort(key=lambda config: (config.country_label, config.display_label, config.filename))
    return produced


def archive_of(configs: Sequence[ClientConfig]) -> bytes:
    """Several config files as one deterministic ZIP.

    One response body can hold one artefact, and a friend may have several nodes — so
    the choice is an archive or a path per file. An archive keeps the public surface at
    exactly one route, which is the property this endpoint is most careful about: every
    logging rule, every cache header and the 404-for-everything behaviour are written
    once for ``/sub/{token}`` and would have to be re-established for anything new.

    Deterministic on purpose. ``ZipInfo`` defaults to the current clock, which would
    make two refreshes of an unchanged fleet return different bytes — noise that hides
    a real change, and a timestamp inside a file a friend stores. Fixed entry dates and
    a sorted order instead.

    Names come from the transports (``ClientConfig.filename``), because a name is part
    of what makes a config importable. A collision between two nodes is resolved by
    suffixing rather than by overwriting: a ZIP with two identical names is one a client
    unpacks into a single file, and the friend would silently be missing an exit.
    """
    buffer = io.BytesIO()
    used: set[str] = set()

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for config in configs:
            name = config.safe_filename()
            if name in used:
                stem, _, suffix = name.rpartition(".")
                # The node id, not a counter: a counter depends on iteration order, so
                # the same fleet could name the same file differently between refreshes.
                marker = config.node_id.replace("-", "")[:8]
                name = f"{stem}-{marker}.{suffix}" if stem else f"{name}-{marker}"
            used.add(name)

            entry = zipfile.ZipInfo(filename=name, date_time=ARCHIVE_TIMESTAMP)
            # 0o600: this file is a credential on the friend's disk, and an archive that
            # unpacks world-readable on a shared machine is one more copy than intended.
            entry.external_attr = 0o600 << 16
            archive.writestr(entry, config.content)

    return buffer.getvalue()


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
