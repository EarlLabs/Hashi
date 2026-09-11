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


class HopEndRefused(DomainError):
    """One end of a hop was refused by the transport's own model, field by field.

    A subclass rather than a new envelope, so every existing caller keeps the answer it
    has always had: same status, same code, same ``message``. What it adds is
    ``fields`` — the transport's own complaint, per parameter — for the one caller that
    has somewhere to put it.

    It exists because the console's establish-hop dialog has twenty-four boxes behind a
    disclosure. Flattening a per-field complaint into one sentence at the top of that
    form makes the operator scroll it hunting for the parameter the prose names, during
    a rotation, which is the moment this form was designed for. Everything ELSE a hop
    refuses is genuinely about the pair — two ends on different tunnel networks, a node
    that is its own exit — and has no field to land on; those stay a plain
    ``DomainError`` and are stated once, above the form.

    ``purpose`` is the ``TransportPurpose`` of the end that was refused, as its string
    value. Carried rather than folded into the field names because which end a
    parameter belongs to is the caller's vocabulary, not this module's.

    Status and code are deliberately INHERITED. A caller that has always seen a 400
    with ``bad_request`` still does, envelope for envelope — this type adds a way to
    read the same refusal, and changes nothing for anybody who does not.

    Both ``fields`` and ``message`` are composed through ``relay.refused_fields`` and so
    carry no held value; see ``ParamsRefused``, whose note explains why that is done
    where the exception is raised and not where it is rendered.
    """

    def __init__(self, message: str, *, purpose: str, fields: dict[str, str]) -> None:
        super().__init__(message)
        self.purpose = purpose
        self.fields = fields


class ParamsRefused(DomainError):
    """A transport refused the parameters on one node-transport, field by field.

    ``HopEndRefused``'s sibling and built to the same pattern (see it for the full
    reasoning): a subclass that INHERITS status and code, so ``POST /api/transports/
    {id}/params`` answers exactly as it always did, and adds ``fields`` for the one
    caller that has a box per parameter to put a message in.

    Not the same type, and not merged with it, because ``purpose`` is hop vocabulary:
    a hop has two ends and a refusal has to say which one it is about. A transport
    enabled on a node has one, so there is nothing to disambiguate, and carrying an
    end's name on a refusal that has no end would be the console's own confusion.

    What ``fields`` and ``message`` may carry is narrower than what Pydantic reports,
    and the narrowing happens where they are BUILT — ``relay.refused_fields``, which
    strikes every held value out of every sentence while those values are still in
    scope. A validator's message can quote the value it rejected, and the mapping being
    validated contains this node's key material, so a surface that renders this
    exception without choosing to — the API envelope, and the pre-redesign outcome
    fragment until M9.6 deleted it — cannot be left to sort it out. The panel narrows
    again on top of that, printing a
    message only for a field it actually has a box for. See ``docs/decisions.md``
    (2026-09-10).
    """

    def __init__(self, message: str, *, fields: dict[str, str]) -> None:
        super().__init__(message)
        self.fields = fields


class NodeOperationFailed(DomainError):
    """A node operation failed or half-succeeded; the node is now degraded."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "node_operation_failed"


class ConfigRefused(NodeOperationFailed):
    """A node's configuration could not be produced, or was refused before it was pushed.

    Nothing reached the host, and trying again changes nothing until the node's record or
    its topology does. That is a different fact from a node that could not be reached, and
    a caller telling the operator what to do next has to be able to tell the two apart
    without reading the message — which may quote an upstream checker's output. Same status
    and code as its parent: to the API it is still a node operation that failed.
    """


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
