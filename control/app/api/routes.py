"""The operator API — nodes, transports, users, revocation, health.

WHAT: JSON endpoints for everything the owner can do, behind one router-level
      auth dependency.
WHY:  the panel is built on these, and so is anything the owner scripts. Keeping
      them thin — validate, call a service, shape a response — is the control
      rulebook's rule for this directory: a route that queries the database
      directly is a violation, not a shortcut.
HOW:  the whole router carries ``require_operator``, so a route added here is
      guarded by default. That is deliberate: the failure mode of per-handler checks
      is a public admin endpoint, and it is silent.
"""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from control.app.api import schemas
from control.app.auth import require_operator
from control.app.dependencies import session_dependency
from control.app.models import NodeState
from control.app.services import (
    apply,
    health,
    nodes,
    relay,
    revocation,
    rotation,
    transports,
    users,
)
from edge.registry import discover

router = APIRouter(prefix="/api", dependencies=[Depends(require_operator)])


# --- transports the image ships ---------------------------------------------

@router.get("/transports", response_model=list[schemas.TransportMetaResponse])
async def list_transports() -> list[schemas.TransportMetaResponse]:
    """What this image can do, discovered rather than listed.

    The panel builds its "enable a transport" form from this, which is what lets a
    new protocol appear in the UI with no change to the panel — criterion 4's
    "selectable in the panel without modifying the control plane's core".

    EVERY transport, including one the registry has retired, because this endpoint
    answers "what does this image ship" and a list that silently dropped a package would
    leave an operator reading a node's existing row against an inventory that does not
    contain it. Which of them may be PROPOSED is the ``retired`` flag's answer, so a
    chooser built from this list filters on a declaration rather than on a name — the
    same rule the HTML forms follow.
    """
    listed = []
    for name, meta in sorted(discover().items()):
        listed.append(
            schemas.TransportMetaResponse(
                name=meta.name,
                family=meta.family,
                needs_tls=meta.needs_tls,
                port_range=meta.port_range,
                subscription_expressible=meta.subscription_expressible,
                # Sorted so the panel's column and any script reading this endpoint see
                # a stable order rather than a set's iteration order.
                subscription_formats=sorted(str(f) for f in meta.subscription_formats),
                blocked_by_inspection=meta.blocked_by_inspection,
                # The derived answer and not the raw permission — see the field's own
                # note in ``schemas``. A caller builds a hop form out of this, and the
                # permission alone said yes to transports whose renderer refuses them.
                hop_capable=meta.hop_expressible,
                # The retirement, passed through in both halves — M20. A caller building
                # a chooser reads the flag; a caller showing a person why an option is
                # missing reads the sentence, which is the transport's own.
                retired=meta.retired is not None,
                retired_because=meta.retired.reason if meta.retired else None,
                # Required fields the operator must fill in: everything the model
                # requires minus everything we mint for them. Shared with the panel's
                # rotation form so the two screens cannot drift apart.
                operator_params=transports.operator_params(name),
            )
        )
    return listed


# --- nodes -------------------------------------------------------------------

@router.get("/nodes", response_model=list[schemas.NodeResponse])
async def list_nodes(session: AsyncSession = Depends(session_dependency)):
    return await nodes.list_nodes(session)


@router.post("/nodes", response_model=schemas.NodeResponse, status_code=status.HTTP_201_CREATED)
async def create_node(
    payload: schemas.NodeCreate, session: AsyncSession = Depends(session_dependency)
):
    """Register a node. It starts in ``draft`` and reaches nobody until applied."""
    return await nodes.create_node(session, **payload.model_dump())


@router.get("/nodes/{node_id}", response_model=schemas.NodeResponse)
async def get_node(node_id: str, session: AsyncSession = Depends(session_dependency)):
    return await nodes.get_node(session, node_id)


@router.post(
    "/nodes/{node_id}/transports",
    response_model=schemas.TransportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enable_transport(
    node_id: str,
    payload: schemas.TransportEnable,
    session: AsyncSession = Depends(session_dependency),
):
    """Enable a transport, minting whatever key material it declared it needs.

    Then grant it to every active user, so enabling a protocol appears in every
    subscriber's config at their next refresh with no further action — which is
    criterion 3 stated as an operation.

    Both halves are ONE transaction since M17, which is why this route no longer runs
    the fan-out itself: granting now allocates an address per person on a transport that
    gives each of them one, and a pool too small must refuse with nothing written rather
    than leave a committed row nobody can be granted on. See ``nodes.enable_and_grant``.
    """
    return await nodes.enable_and_grant(
        session,
        node_id=node_id,
        transport_name=payload.transport_name,
        params=payload.params,
        pool_size=payload.pool_size,
    )


@router.post("/nodes/{node_id}/state", response_model=schemas.NodeResponse)
async def set_node_state(
    node_id: str,
    payload: schemas.NodeStateChange,
    session: AsyncSession = Depends(session_dependency),
):
    """Move a node between states — backlog item 17.

    Exists as an operator action, not only as something ``apply`` does, because the two
    transitions an operator needs most cannot come from an apply: taking a node OUT of
    rotation without destroying it (``active -> draft``, so it stops reaching users
    immediately) and retiring one whose host is gone. Illegal transitions are refused
    with a 409 naming what is allowed — see ``NodeState.allowed_from``.
    """
    return await nodes.set_node_state(
        session,
        node_id=node_id,
        state=NodeState(payload.state),
        detail=payload.detail,
    )


@router.post("/nodes/{node_id}/resolver", response_model=schemas.NodeResponse)
async def set_node_resolver(
    node_id: str,
    payload: schemas.ResolverChange,
    session: AsyncSession = Depends(session_dependency),
):
    """Set the resolver a node's lookups are sent to through its hop — M16.

    The one field on a node record that can change after registration: the upgrade that
    added it gave every existing node none, and a node that dials a hop does not render
    without one. A value ``edge`` would refuse is a 400 with its sentence, exactly as at
    registration. It changes the record, not the host — apply the node afterwards.
    """
    return await nodes.set_resolver(session, node_id=node_id, resolver=payload.resolver)


@router.post("/nodes/{node_id}/apply", response_model=schemas.ApplyResponse)
async def apply_node(node_id: str, session: AsyncSession = Depends(session_dependency)):
    """Render, validate, push and verify. Marks the node degraded on any failure.

    A node with no transports enabled is answered 409 ``nothing_to_apply`` instead —
    M18.1. Nothing is dialled, nothing is pushed and the node's state is untouched: it
    is not a failure, it is a node that has nothing to serve yet.

    A node the state machine will not let serve is answered 409 ``node_cannot_serve``,
    on the same terms and for a different reason: applying a node is what puts it into
    service, and ``retired -> active`` is the transition ``NodeState.allowed_from``
    refuses. This endpoint wrote the column itself and so used to answer 200 and leave a
    retired node active — see ``apply.apply_node``, which now asks the machine first.
    """
    applied = await apply.apply_node(session, node_id=node_id)
    return schemas.ApplyResponse(
        node_id=node_id,
        transports_applied=sorted(applied.configs),
        serving_unmeasured=list(applied.unmeasured),
        serving_port_only=list(applied.port_only),
        restarted_to_serve=list(applied.restarted),
    )


@router.get("/nodes/{node_id}/health", response_model=schemas.HealthResponse)
async def node_health(node_id: str, session: AsyncSession = Depends(session_dependency)):
    """Probe a node. Reports whether it serves, never who used it."""
    return await health.check_node(session, node_id=node_id)


# --- users -----------------------------------------------------------------

@router.get("/users", response_model=list[schemas.UserResponse])
async def list_users(session: AsyncSession = Depends(session_dependency)):
    return await users.list_users(session)


@router.post(
    "/users", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED
)
async def create_user(
    payload: schemas.UserCreate, session: AsyncSession = Depends(session_dependency)
):
    """Create a user, mint their subscription, and grant every serving node."""
    return await users.create_user(session, nickname=payload.nickname)


@router.get("/users/{user_id}/subscription", response_model=schemas.SubscriptionIssued)
async def user_subscription(
    user_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The URL to send this user.

    Re-displayable rather than one-shot: a user who lost their link needs the same
    one back, because issuing a new one means they must re-import — and "users never
    re-add anything" is the charter's promise.
    """
    user = await users.get_user(session, user_id)
    live = [s for s in user.subscriptions if s.is_active]
    if not live:
        from control.app.errors import NotFound

        raise NotFound("this user has no live subscription")
    settings = request.app.state.settings
    return schemas.SubscriptionIssued(
        url=f"{settings.public_base_url}/sub/{live[0].token}"
    )


@router.post("/users/{user_id}/revoke", response_model=schemas.RevocationResponse)
async def revoke_user(user_id: str, session: AsyncSession = Depends(session_dependency)):
    """Withdraw access everywhere, and report honestly if a node could not be reached.

    ``complete`` carries ``outcome.confirmed`` and not ``outcome.complete`` — M23, round
    8. The schema says why; the short version is that the field an integration polls was
    true on the retry that changed nothing, which is the one moment it must not be.
    """
    outcome = await revocation.revoke_user(session, user_id=user_id)
    return schemas.RevocationResponse(
        user_id=outcome.user_id,
        complete=outcome.confirmed,
        withdrew=outcome.withdrew,
        nodes_updated=outcome.nodes_updated,
        nodes_failed=outcome.nodes_failed,
        summary=outcome.summary(),
    )


# --- hops between nodes (item 16) -------------------------------------------

@router.get("/hops", response_model=list[schemas.HopResponse])
async def list_hops(session: AsyncSession = Depends(session_dependency)):
    """Every hop, entry end first. A half-hop is listed, not hidden."""
    return [
        schemas.HopResponse(
            entry=schemas.HopEndResponse.model_validate(entry),
            leaf=schemas.HopEndResponse.model_validate(leaf) if leaf else None,
        )
        for entry, leaf in await relay.list_hops(session)
    ]


@router.post("/hops", response_model=schemas.HopResponse, status_code=status.HTTP_201_CREATED)
async def create_hop(
    payload: schemas.HopCreate, session: AsyncSession = Depends(session_dependency)
):
    """Configure both ends of one entry→leaf tunnel.

    Neither end is written unless the pair would form a working tunnel — see
    ``services/relay.py`` for why a half-established hop is the failure worth spending
    a validation pass to avoid.
    """
    entry, leaf = await relay.establish_hop(
        session,
        entry_node_id=payload.entry_node_id,
        leaf_node_id=payload.leaf_node_id,
        transport_name=payload.transport_name,
        entry_params=payload.entry_params,
        leaf_params=payload.leaf_params,
    )
    return schemas.HopResponse(
        entry=schemas.HopEndResponse.model_validate(entry),
        leaf=schemas.HopEndResponse.model_validate(leaf),
    )


@router.delete("/hops/{node_transport_id}", status_code=status.HTTP_200_OK)
async def dissolve_hop(
    node_transport_id: str, session: AsyncSession = Depends(session_dependency)
):
    """Remove both ends. Returns the nodes that now need re-applying.

    Re-applying is the CALLER's next step rather than something done here: the two
    nodes may be unreachable, and a delete that reported failure because a node was
    down would leave the operator unable to remove a hop to a host that no longer
    exists — which is exactly when they need to.
    """
    return {"needs_apply": await relay.dissolve_hop(session, node_transport_id=node_transport_id)}


# --- rotation (items 23 and 24) ---------------------------------------------

@router.post(
    "/transports/{node_transport_id}/rotate-keys",
    response_model=schemas.RotationResponse,
)
async def rotate_keys(
    node_transport_id: str,
    include_clients: bool = True,
    session: AsyncSession = Depends(session_dependency),
):
    """Re-mint this transport's key material and push it.

    Users' subscription URLs are untouched: they re-fetch the same link and receive
    the new material, which is what makes rotation possible without anyone touching
    their device.
    """
    outcome = await rotation.rotate_keys(
        session, node_transport_id=node_transport_id, include_clients=include_clients
    )
    return schemas.RotationResponse(
        node_transport_id=outcome.node_transport_id,
        rotated=outcome.rotated,
        complete=outcome.complete,
        summary=outcome.summary(),
    )


@router.post(
    "/transports/{node_transport_id}/state", response_model=schemas.TransportResponse
)
async def set_transport_enabled(
    node_transport_id: str,
    payload: schemas.TransportEnabledChange,
    session: AsyncSession = Depends(session_dependency),
):
    """Put a transport into, or take it out of, what users are offered.

    Criterion 3 in both directions. Enabling grants every active user material for
    it, so it appears at their next refresh; disabling removes it from every
    subscription — and neither requires anyone to touch a device.

    It does not reconfigure the node: re-apply to stop the daemon serving what it was
    already given. See the service's docstring for why that distinction is not a
    detail.
    """
    return await nodes.set_transport_enabled(
        session, node_transport_id=node_transport_id, enabled=payload.enabled
    )


@router.delete("/transports/{node_transport_id}", status_code=status.HTTP_200_OK)
async def remove_transport(
    node_transport_id: str, session: AsyncSession = Depends(session_dependency)
):
    """Remove one user-facing transport, with every credential minted under it — M15.2.

    Answers in ``dissolve_hop``'s shape, because it is the same kind of answer: what is
    left for the caller is to re-apply, and the node may be unreachable right now. A
    delete that pushed would report failure for a host that is down — which is exactly
    when an operator needs to free a port on a machine that no longer exists.

    ``DELETE`` here and ``DELETE /hops/{id}`` there, addressed by the same kind of id:
    one end of a hop is refused on this path (409) and names the other.
    """
    node_id = await nodes.remove_transport(session, node_transport_id=node_transport_id)
    return {"needs_apply": [node_id]}


@router.post(
    "/transports/{node_transport_id}/params", response_model=schemas.RotationResponse
)
async def replace_params(
    node_transport_id: str,
    payload: schemas.ParamsReplace,
    session: AsyncSession = Depends(session_dependency),
):
    """Replace operator-supplied parameters — a blocked Reality decoy, for instance.

    Not named after any protocol's field, deliberately: a ``/rotate-decoy`` route would
    be this control plane knowing what a decoy is.

    AND THE POOL SIZE, since M17.1c, on this route rather than one of its own: resizing is
    replacing a parameter of the row, it is audited as the same action, and it re-renders
    and pushes the node exactly as any other replacement does. A ``/resize`` endpoint
    would be a second way to change the same row with its own refusals to keep in step.
    """
    outcome = await rotation.replace_params(
        session,
        node_transport_id=node_transport_id,
        params=payload.params,
        pool_size=payload.pool_size,
    )
    return schemas.RotationResponse(
        node_transport_id=outcome.node_transport_id,
        rotated=outcome.rotated,
        complete=outcome.complete,
        summary=outcome.summary(),
    )
