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


class SecretsUnreadable(DomainError):
    """A stored secret cannot be decrypted with the configured key.

    Its own type, and the message names ``HASHI_SECRET_KEY``, because of one specific
    moment: the operator has just restored a database onto a new host — the very
    situation backups exist for — and got the key wrong. Everything else about the
    restore looks perfect. Their friends and nodes are all listed.

    Before this existed the failure was an opaque 500, and the only reading available to
    them was "the restore lost my data". They would then reasonably go looking for
    another dump, or start over, when what they needed was one line in an env file. That
    is the difference between a recoverable afternoon and an unrecoverable one, and it is
    entirely down to what this response says.

    Note what it does NOT say: not the ciphertext, not which row, not which node. A
    stranger who reaches this endpoint learns only that a key does not match.
    """

    # 409 rather than 500: nothing broke. The request was answerable and the answer is
    # that this application is configured with the wrong key for this data.
    status_code = status.HTTP_409_CONFLICT
    code = "secrets_unreadable"


async def secret_unreadable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert the crypto layer's own exception into the readable domain error.

    A handler rather than try/except at each call site, because the raise happens inside
    SQLAlchemy's type decorator — every read of an encrypted column, from any service, on
    any route. There is no single call site to wrap, and wrapping every one of them is a
    list that would go out of date on the next feature.
    """
    return await domain_error_handler(
        request,
        SecretsUnreadable(
            "a stored secret could not be decrypted, so this operation was refused. "
            "HASHI_SECRET_KEY does not match the one this data was encrypted with — "
            "which is what a database restored with the wrong key looks like. The data "
            "is intact; the key is wrong. Nothing has been changed."
        ),
    )


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
