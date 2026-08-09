"""The operator API — nodes, transports, friends, revocation, health.

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
from control.app.services import apply, friends, health, nodes, revocation
from edge.registry import discover, profile

router = APIRouter(prefix="/api", dependencies=[Depends(require_operator)])


# --- transports the image ships ---------------------------------------------

@router.get("/transports", response_model=list[schemas.TransportMetaResponse])
async def list_transports() -> list[schemas.TransportMetaResponse]:
    """What this image can do, discovered rather than listed.

    The panel builds its "enable a transport" form from this, which is what lets a
    new protocol appear in the UI with no change to the panel — criterion 4's
    "selectable in the panel without modifying the control plane's core".
    """
    listed = []
    for name, meta in sorted(discover().items()):
        transport = profile(name)
        generated = {spec.name for spec in meta.key_material}
        generated |= {spec.public_name for spec in meta.key_material if spec.public_name}
        listed.append(
            schemas.TransportMetaResponse(
                name=meta.name,
                family=meta.family,
                needs_tls=meta.needs_tls,
                port_range=meta.port_range,
                subscription_expressible=meta.subscription_expressible,
                # Required fields the operator must fill in: everything the model
                # requires minus everything we mint for them.
                operator_params=sorted(
                    field
                    for field, info in transport.params_model.model_fields.items()
                    if info.is_required() and field not in generated
                ),
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

    Then grant it to every active friend, so enabling a protocol appears in every
    subscriber's config at their next refresh with no further action — which is
    criterion 3 stated as an operation.
    """
    node_transport = await nodes.enable_transport(
        session,
        node_id=node_id,
        transport_name=payload.transport_name,
        params=payload.params,
    )
    for friend in await friends.list_friends(session):
        if friend.is_active:
            await friends.grant_everywhere(session, friend)
    await session.commit()
    return node_transport


@router.post("/nodes/{node_id}/apply", response_model=schemas.ApplyResponse)
async def apply_node(node_id: str, session: AsyncSession = Depends(session_dependency)):
    """Render, validate, push and verify. Marks the node degraded on any failure."""
    applied = await apply.apply_node(session, node_id=node_id)
    return schemas.ApplyResponse(node_id=node_id, transports_applied=sorted(applied))


@router.get("/nodes/{node_id}/health", response_model=schemas.HealthResponse)
async def node_health(node_id: str, session: AsyncSession = Depends(session_dependency)):
    """Probe a node. Reports whether it serves, never who used it."""
    return await health.check_node(session, node_id=node_id)


# --- friends -----------------------------------------------------------------

@router.get("/friends", response_model=list[schemas.FriendResponse])
async def list_friends(session: AsyncSession = Depends(session_dependency)):
    return await friends.list_friends(session)


@router.post(
    "/friends", response_model=schemas.FriendResponse, status_code=status.HTTP_201_CREATED
)
async def create_friend(
    payload: schemas.FriendCreate, session: AsyncSession = Depends(session_dependency)
):
    """Create a friend, mint their subscription, and grant every serving node."""
    return await friends.create_friend(session, nickname=payload.nickname)


@router.get("/friends/{friend_id}/subscription", response_model=schemas.SubscriptionIssued)
async def friend_subscription(
    friend_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The URL to send this friend.

    Re-displayable rather than one-shot: a friend who lost their link needs the same
    one back, because issuing a new one means they must re-import — and "friends never
    re-add anything" is the charter's promise.
    """
    friend = await friends.get_friend(session, friend_id)
    live = [s for s in friend.subscriptions if s.is_active]
    if not live:
        from control.app.errors import NotFound

        raise NotFound("this friend has no live subscription")
    settings = request.app.state.settings
    return schemas.SubscriptionIssued(
        url=f"{settings.public_base_url}/sub/{live[0].token}"
    )


@router.post("/friends/{friend_id}/revoke", response_model=schemas.RevocationResponse)
async def revoke_friend(friend_id: str, session: AsyncSession = Depends(session_dependency)):
    """Withdraw access everywhere, and report honestly if a node could not be reached."""
    outcome = await revocation.revoke_friend(session, friend_id=friend_id)
    return schemas.RevocationResponse(
        friend_id=outcome.friend_id,
        complete=outcome.complete,
        nodes_updated=outcome.nodes_updated,
        nodes_failed=outcome.nodes_failed,
        summary=outcome.summary(),
    )
