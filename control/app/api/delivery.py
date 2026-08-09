"""The delivery endpoint — the only route a friend ever touches.

WHAT: ``GET /sub/{token}`` returns that friend's subscription document.
WHY:  backlog item 8, charter criterion 5. This is the single artefact a friend
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

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.dependencies import session_dependency
from control.app.services import subscriptions

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/sub/{token}")
async def deliver_subscription(
    # Bounded so an absurd path cannot become an expensive digest computation, and
    # so the route does not accept something that could never be a real token.
    token: str = Path(min_length=16, max_length=512),
    session: AsyncSession = Depends(session_dependency),
) -> Response:
    """Return the base64 subscription document for this token, or 404."""
    subscription = await subscriptions.find_by_token(session, token)

    if subscription is None:
        # Deliberately identical for unknown, revoked, and revoked-friend. Note there
        # is no logging here at all: a "subscription not found" log line with the
        # path attached would be the leak this whole module is written to avoid.
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    document = await subscriptions.render(session, subscription.friend)

    return Response(
        content=document,
        # text/plain is what stock clients expect for a base64 subscription; a JSON
        # content type makes some of them refuse the response outright.
        media_type="text/plain; charset=utf-8",
        headers={
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
        },
    )
