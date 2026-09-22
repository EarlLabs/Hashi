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


class TransportRetired(DomainError):
    """A transport the registry has withdrawn cannot be enabled on anything — M20.

    Its own type, and the only refusal in this file that is about the PROTOCOL rather
    than about the request: the transport is installed, its parameters are fine and it
    would serialise into a friend's configuration perfectly. What is wrong with it is
    that it does not work on the hosts this project prepares — a handshake that completes
    and carries nothing — which is the silent failure the charter calls the worst kind,
    and minting fresh material for it would hand a friend a dead tunnel with nothing on
    their device saying so.

    422 rather than 400, and the same status the console's own form answers with: the
    request was well-formed and was understood, and the reason it cannot be carried out
    is a property of what it names. One fact, one status, one sentence, whichever surface
    asked — see ``transports.NO_LONGER_OFFERED``, which both of them format.

    It refuses the CREATION and nothing else. A row already on a node keeps rendering,
    keeps serving the people granted on it and can still be withdrawn or removed; that
    asymmetry is the whole of done-when 3 and is asserted rather than described (see
    ``tests/control/test_a_retired_transport_is_not_offered.py``).
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "transport_retired"


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


class NothingToApply(Conflict):
    """An apply was asked for on a node that has no transports enabled.

    Its own type because this is NOT a node operation that failed — M18.1. A node with
    nothing enabled renders no configs, and the empty compose file that used to be built
    from them was pushed and rejected by the daemon with ``services must be a mapping``:
    a 502 about YAML, and a node left ``degraded``, for the most ordinary first-run
    mistake there is — register a node, press the obvious next button. Nothing was wrong
    with the node, nothing had been attempted on it, and nothing about that answer told
    the operator to enable a transport.

    ``Conflict`` rather than ``NodeOperationFailed``: the request was answerable and the
    answer is about the RECORD, not the host. Nothing is dialled, nothing is pushed and
    the node's state is left exactly as it was — which is what the raise being outside
    ``apply_node``'s try blocks buys, and it is the half of M18.1 that a status code
    alone would not give (an ``active`` node applied by mistake keeps serving).

    Its own code as well as its own type, so a script can tell "you have not enabled
    anything yet" from every other 409 this API answers with — all of which are the
    node state machine refusing a transition.
    """

    code = "nothing_to_apply"


class NodeCannotServe(Conflict):
    """A node the state machine will not let serve again was asked to do something.

    ``NothingToApply``'s sibling on the same endpoint, and the one refusal here that is
    about the node's STATE rather than about what it runs. An apply is what puts a node
    into service: it ends by writing ``active``, and since M23 it hands every active
    friend a credential on the way in. On a ``retired`` node that is the transition
    ``NodeState.allowed_from`` exists to refuse — the row is how an operator records that
    a host is gone, sold on or seized, and bringing it back would put an address that may
    now answer for a stranger into every friend's subscription and mint key material for
    everybody on it.

    The state endpoint has refused that move since backlog item 17; ``apply`` wrote the
    column itself and so never asked. This type is what the asking answers with.

    ``Conflict`` rather than ``NodeOperationFailed`` for ``NothingToApply``'s reason,
    and it is the same fact here: nothing is dialled, nothing is pushed, nobody is
    granted anything, and the node's state is left exactly as the operator set it —
    which is what the raise being above everything ``apply_node`` writes buys.

    Its own code so a script can tell this from the node having nothing enabled: the two
    are both 409s on one endpoint and the operator's next move differs completely.
    Deliberately NOT named for ``retired``, because what refuses is the machine rather
    than a literal state — see ``apply.cannot_serve_again``, which asks it rather than
    restating it.

    SINCE M23's ROUND 12 IT IS ALSO THE PROBE'S REFUSAL, and one type for the two is the
    decision rather than an economy. The walk found the buttons disagreeing about one
    address: apply turned away because the address "may now answer for somebody else",
    and the probe beside it on the same row opened an SSH session to it. Both doors now
    ask one predicate and raise this — the machine's answer is one answer — while the
    MESSAGE differs, because what each button would have done differs. The second is
    ``apply.CANNOT_BE_DIALLED``, which is where the cost of the probe yielding rather
    than the apply is written down.
    """

    code = "node_cannot_serve"


class NodeNotInService(Conflict):
    """A FAN-OUT reached a node that is not serving, and a fan-out never puts one there.

    ``NodeCannotServe``'s sibling and not its subclass, because the two refuse different
    things. That one is the state machine: ``retired`` may not serve again whoever asks.
    This one is about WHO ASKED — an apply is what puts a node into service, and the only
    caller entitled to that is an operator who pressed apply on that node. A revocation
    and a rotation reach ``apply_many`` as a consequence of something done to a PERSON,
    and round 4's walk measured what that cost: withdrawing one user's access took a
    ``draft`` node back into service, minted key material on it for a different user who
    had never been near it, and ran ``docker compose up`` on a host the operator had
    parked to rebuild it. Every one of those was legal — ``draft -> active`` is in the
    machine, and it is supposed to be — and not one of them was asked for.

    What it costs, named rather than hidden: the node is not re-pushed, so a host that is
    out of service goes on running whatever file it was last given, which may still
    authorise somebody just withdrawn. That is the same fact a retired node has carried
    since round 7, and it is the fan-out's caller's job to say so — see
    ``revocation.RevocationOutcome.summary``, which reports such a node as NOT updated.
    Nobody is routed onto a node that is not serving, so nothing new arrives there; what
    is already there is the operator's to end by applying the node themselves.

    ``Conflict`` for ``NodeCannotServe``'s reason, and the same facts hold: nothing is
    dialled, nothing is pushed, nobody is granted anything, and the node's state is left
    exactly as the operator set it. Its own code so a script can tell a node that is
    merely parked from one that is written off — the first comes back with an apply and
    the second never does.
    """

    code = "node_not_in_service"


class NoExitThroughTheHop(Conflict):
    """A node's friends would have been put on a transport that cannot reach its hop.

    M25. A node that dials a hop gives its friends ``Egress.HOP`` — out through the hop
    and nowhere else — and only a transport that terminates their connection and
    re-originates it can honour that (``TransportMeta.serves_users_through_a_hop``). A
    kernel tunnel hands what it decrypts to the node's own routing table, and the only way
    out this project renders for a hop is a source route from the node's own address,
    which a friend's packets do not carry. ``edge`` refuses to render it; this is the same
    refusal moved to the two doors that create the combination, so that nothing is minted
    and nothing is delivered in between.

    ``Conflict`` rather than ``TransportRetired``'s 422, and the difference is what is
    wrong. A retired transport is refused for a property of the PROTOCOL, wherever it is
    named; this one is refused for how what was asked for meets what the node already has
    — the same transport is correct on a node with no hop, and this node's other
    transports are correct beside the hop. That is "the request contradicts something that
    already exists", which is what 409 says and 422 does not.

    Its own code so a script can tell it from every other 409 this API answers with: those
    are a port already bound, a pool too small or the node state machine, and the move
    that fixes each is different. The operator's move here is to choose the other kind of
    transport, or to take one of the two rows away — which is what the message says, in
    ``edge``'s own words about why (``transports.NO_EXIT_THROUGH_THE_HOP``,
    ``transports.NO_HOP_OVER_WHAT_IT_OFFERS`` and — for a friend-facing row the operator
    has withdrawn rather than offered, which this refusal counts and which the other two
    sentences would describe wrongly — ``transports.NO_HOP_OVER_WHAT_IT_HOLDS``).

    It refuses the CREATION and nothing else — ``TransportRetired``'s own asymmetry, and
    the same reason. A node already carrying both rows keeps every row it has, renders
    every config it could render before, and serves everyone it was serving; what it could
    not do before and still cannot is render the friend-facing one, which is where the
    operator meets it and where the sentence has always been.
    """

    code = "no_exit_through_the_hop"


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


class ConfigNotServing(NodeOperationFailed):
    """The configuration reached the host and the host is not running it — M23.

    The third fact in this family, and it is neither of the other two. ``ConfigRefused``
    means nothing was written; a bare ``NodeOperationFailed`` out of the push covers a
    node that could not be reached at all. This one is the node that WAS reached, whose
    files WERE replaced, and whose daemon then did not come back on them — a container
    that never started, or one still running the configuration it was started with
    before.

    Its own type because the revocation fan-out has to tell the operator what to do about
    it and must not find out by reading the message (``apply.NotUpdated``). Without it,
    the walk on the owner's real leaf was told *"could not be reached — apply it again
    once it can be"* about a node whose peer count had just gone 2 → 1 on disk: the push
    landed, the restart is what failed, and the sentence sent the operator to debug the
    wrong half. Same status and code as its parent: to the API it is still a node
    operation that failed.
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
