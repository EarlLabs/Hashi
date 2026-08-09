"""Domain exceptions and the one handler that turns them into responses.

WHAT: the exception type services raise, and the envelope it becomes.
WHY:  core invariants §4 — outward API errors use ``{"error": {"code", "message"}}``
      and a raw exception string never crosses the boundary. No stack traces, no
      SQL, no paths, no host names: this API is reachable from inside Russia by
      anyone who guesses the host, and an error that names a node's address or the
      framework's version is free reconnaissance.
HOW:  services raise ``DomainError`` with a stable machine code and a message
      written for the operator. Routes never build error responses by hand.
"""

import logging

from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Something the operator asked for cannot be done, with a reason they can act on."""

    # Overridden by subclasses. 400 by default: a DomainError means the request was
    # answerable and wrong, not that the server broke.
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Conflict(DomainError):
    """The request contradicts something that already exists."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class NotDeliverable(DomainError):
    """A transport cannot be expressed in the subscription format friends use.

    Its own type because the charter requires this to be refused OUT LOUD rather
    than producing a quietly incomplete subscription (amendment A, and backlog item
    7 S2a). A friend whose subscription silently lacks a node has no way to know.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "not_deliverable"


class NodeOperationFailed(DomainError):
    """A node operation failed or half-succeeded; the node is now degraded."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "node_operation_failed"


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Render a domain error as the typed envelope."""
    # Logged at info with the CODE only — deliberately not the request path, which
    # for a delivery request contains a live subscription token, and not the
    # message, which may name a node.
    logger.info("domain error: %s", exc.code)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything unexpected becomes an opaque 500.

    The traceback goes to the application log — with no request path attached, for
    the reason above — and the client is told nothing but "internal_error". An echo
    of ``str(exc)`` here is the most common way a database URL, a node address or a
    decrypted secret reaches a stranger.
    """
    logger.exception("unhandled error in %s", request.scope.get("endpoint", "unknown"))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": {"code": "internal_error", "message": "internal error"}},
    )
