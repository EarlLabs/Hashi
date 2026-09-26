"""The delivery endpoint — the only route a user ever touches.

WHAT: ``GET /sub/{token}`` returns that user's subscription — the base64 document by
      default, or their configuration files as one archive with
      ``?format=client-config-file`` (item 27).
WHY:  backlog item 8, charter criterion 5. This is the single artefact a user
      holds, and the reason a node or protocol can be swapped without them acting:
      their client re-fetches this URL and gets the new fleet.
HOW:  unauthenticated by design — the token IS the credential — which makes this the
      most exposed route in the system and the one with the most rules:

      * **404 for unknown AND revoked.** A 403 would confirm that a token once
        existed, which is more than a stranger should learn. Both go through the same
        path so they are also indistinguishable by timing.
      * **The token is never logged.** Not by uvicorn (``--no-access-log``), not by
        Caddy (``output discard``), and not here — no logger call in this module
        includes the path or the token, and the exception handler for the app is
        written the same way.
      * **No cache headers that would let a proxy keep it.** A cached subscription is
        a credential-bearing response sitting in someone else's storage, and it also
        defeats the whole rotation mechanism.
"""

import logging

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.dependencies import session_dependency
from control.app.services import subscriptions
from edge.registry import SubscriptionFormat

logger = logging.getLogger(__name__)

router = APIRouter()


# The headers every shape of this response carries. One mapping rather than one per
# branch: a second shape that quietly lost ``no-store`` would be a bearer-credential
# body sitting in a proxy's cache, and nothing would fail.
DELIVERY_HEADERS = {
    # no-store rather than no-cache: no-cache still permits storage with
    # revalidation, and this body is a bearer credential.
    "Cache-Control": "no-store, max-age=0",
    # The response is not a document a browser should ever render or sniff.
    "X-Content-Type-Options": "nosniff",
    # Nothing here is embeddable, and this is the one route an attacker can
    # cause a victim's browser to fetch.
    "X-Frame-Options": "DENY",
    # Keeps the token out of the Referer header if the body is ever opened in
    # a browser context that follows a link.
    "Referrer-Policy": "no-referrer",
}

# What the archive is called when a browser saves it. Fixed, and deliberately carrying
# nothing about the user or the token: this string ends up in a downloads folder and
# in a browser's own history.
ARCHIVE_FILENAME = "hashi-configs.zip"


@router.get("/sub/{token}")
async def deliver_subscription(
    # Bounded so an absurd path cannot become an expensive digest computation, and
    # so the route does not accept something that could never be a real token.
    token: str = Path(min_length=16, max_length=512),
    # WHICH shape, asked for explicitly. Never inferred from the User-Agent or from
    # what the user happens to have: a response that changes with who is asking is
    # one nobody can reproduce, and the user reporting a problem would be describing
    # a different document than the operator sees.
    #
    # Typed as the `edge` vocabulary, so this route gains one arm per FORMAT and none
    # per protocol. An unknown value is a 422 about the parameter — it says nothing
    # about whether the token exists, because it is refused before any lookup.
    subscription_format: SubscriptionFormat = Query(
        default=SubscriptionFormat.V1_URI_LIST,
        alias="format",
    ),
    session: AsyncSession = Depends(session_dependency),
) -> Response:
    """Return this user's subscription in the requested shape, or 404.

    Two shapes, one token, one route (item 27). Without ``?format=`` the response is
    byte for byte what it has always been — the link a user already holds must not
    change meaning because a second shape was added.
    """
    subscription = await subscriptions.find_by_token(session, token)

    if subscription is None:
        # Deliberately identical for unknown, revoked, and revoked-user — and
        # identical across shapes, so which formats a token supports cannot be probed
        # either. Note there is no logging here at all: a "subscription not found" log
        # line with the path attached would be the leak this whole module is written
        # to avoid.
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    user = subscription.user

    if subscription_format is SubscriptionFormat.CLIENT_CONFIG_FILE:
        configs = await subscriptions.config_files_for(session, user)
        # An empty archive rather than a 404, for the same reason ``render`` returns an
        # empty document: a user whose nodes are momentarily degraded has not been
        # revoked, and their client must not report it as though they had been.
        return Response(
            content=subscriptions.archive_of(configs),
            media_type="application/zip",
            headers={
                **DELIVERY_HEADERS,
                # A fixed name with nothing identifying in it. Quoted because the
                # header's grammar requires it for anything but a bare token.
                "Content-Disposition": f'attachment; filename="{ARCHIVE_FILENAME}"',
            },
        )

    return Response(
        content=await subscriptions.render(session, user),
        # text/plain is what stock clients expect for a base64 subscription; a JSON
        # content type makes some of them refuse the response outright.
        media_type="text/plain; charset=utf-8",
        headers=DELIVERY_HEADERS,
    )
