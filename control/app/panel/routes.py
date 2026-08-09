"""The admin panel — the screen the owner lives in.

WHAT: login, the node list, the friend list, and the actions on each.
WHY:  criteria 2 and 3 are both phrased "from the panel", so this is not a
      convenience layer over the API — it is where those criteria are met.
HOW:  full pages for navigations, HTML FRAGMENTS for HTMX actions. The control
      rulebook names the trap: returning a full document from a partial route nests
      ``<html>`` inside the page and the bug looks like CSS.

      Autoescaping stays on everywhere. Node names, friend nicknames and error
      strings are attacker-influenced text — a friend's nickname is typed by the
      operator, but a node's ``state_detail`` can contain text from a remote host —
      and a ``|safe`` on any of them is an injection.
"""

import logging
import pathlib

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from control.app import auth
from control.app.dependencies import session_dependency
from control.app.errors import DomainError
from control.app.services import apply, friends, health, nodes, revocation
from edge.registry import discover

logger = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent
                                          / "templates"))

# Two routers: the login screen must NOT require a session, everything else must.
public = APIRouter(prefix="/panel")
router = APIRouter(prefix="/panel", dependencies=[Depends(auth.require_operator_page)])


# --- login -------------------------------------------------------------------

@public.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> Response:
    return TEMPLATES.TemplateResponse(request, "pages/login.html", {"error": None})


@public.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> Response:
    """Check a login and open a session.

    A failed attempt returns 401 with the same generic message for a wrong username
    and a wrong password. Distinguishing them would confirm the username, and the
    slow KDF in ``authenticate`` means the two paths also take comparable time.
    """
    if not auth.authenticate(request.app.state.settings, username, password):
        logger.info("failed operator login")
        return TEMPLATES.TemplateResponse(
            request,
            "pages/login.html",
            {"error": "Those credentials were not accepted."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    auth.log_in(request, username)
    return RedirectResponse(url="/panel/", status_code=status.HTTP_303_SEE_OTHER)


@public.post("/logout")
async def logout(request: Request) -> Response:
    auth.log_out(request)
    return RedirectResponse(url="/panel/login", status_code=status.HTTP_303_SEE_OTHER)


# --- pages -------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(session_dependency)):
    """The one screen that answers "is my fleet up and who can use it"."""
    return TEMPLATES.TemplateResponse(
        request,
        "pages/index.html",
        {
            "nodes": await nodes.list_nodes(session),
            "friends": await friends.list_friends(session),
            "transports": sorted(discover().values(), key=lambda meta: meta.name),
        },
    )


@router.get("/nodes/{node_id}", response_class=HTMLResponse)
async def node_detail(
    node_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    node = await nodes.get_node(session, node_id)
    installed = discover()
    return TEMPLATES.TemplateResponse(
        request,
        "pages/node.html",
        {
            "node": node,
            # Only transports not already on this node, so the form cannot offer an
            # action that is guaranteed to conflict.
            "available": sorted(
                meta.name
                for meta in installed.values()
                if meta.name not in {t.transport_name for t in node.transports}
                # A transport that cannot be expressed in the subscription format is
                # not offered at all, rather than offered and then refused.
                and meta.subscription_expressible
            ),
        },
    )


# --- actions (HTMX fragments) ------------------------------------------------

@router.post("/nodes", response_class=HTMLResponse)
async def create_node(
    request: Request,
    name: str = Form(...),
    address: str = Form(...),
    location_label: str = Form(...),
    ssh_host: str = Form(""),
    ssh_user: str = Form("root"),
    ssh_port: int = Form(22),
    ssh_private_key: str = Form(""),
    session: AsyncSession = Depends(session_dependency),
):
    """Register a node from the panel. Redirects so a reload does not re-post."""
    await nodes.create_node(
        session,
        name=name,
        address=address,
        location_label=location_label,
        ssh_host=ssh_host or None,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        # Empty string means "not supplied" — storing "" would encrypt an empty key
        # and make the failure look like a wrong key rather than a missing one.
        ssh_private_key=ssh_private_key or None,
    )
    return RedirectResponse(url="/panel/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/nodes/{node_id}/transports", response_class=HTMLResponse)
async def enable_transport(
    node_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Enable a transport, taking its parameters from the submitted form.

    The form is read as a flat mapping and handed to the transport's own validator
    untouched. That is what makes a NEW protocol appear in this panel with no change
    here: this function does not know any protocol's field names, and the ``params``
    it forwards are whatever that transport declared it needs.
    """
    form = await request.form()
    transport_name = str(form.get("transport_name", ""))

    params: dict[str, object] = {}
    for key, value in form.multi_items():
        if key in {"transport_name"} or value == "":
            continue
        # Comma-separated lists are how an HTML form expresses a tuple field such as
        # Reality's server_names. Split here rather than in the transport, because it
        # is a property of HTML forms, not of any protocol.
        params[key] = [part.strip() for part in str(value).split(",")] \
            if "," in str(value) else str(value)

    await nodes.enable_transport(
        session, node_id=node_id, transport_name=transport_name, params=params
    )
    for friend in await friends.list_friends(session):
        if friend.is_active:
            await friends.grant_everywhere(session, friend)
    await session.commit()
    return RedirectResponse(
        url=f"/panel/nodes/{node_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/nodes/{node_id}/apply", response_class=HTMLResponse)
async def apply_node(
    node_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Push configuration to a node and show the outcome as a fragment."""
    try:
        applied = await apply.apply_node(session, node_id=node_id)
        message, ok = f"applied: {', '.join(sorted(applied))}", True
    except DomainError as exc:
        # Shown rather than raised: a failed apply marks the node degraded, and the
        # operator needs to read why on the page they are already on.
        message, ok = exc.message, False
    return TEMPLATES.TemplateResponse(
        request, "panel/outcome.html", {"message": message, "ok": ok}
    )


@router.post("/nodes/{node_id}/health", response_class=HTMLResponse)
async def node_health(
    node_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    result = await health.check_node(session, node_id=node_id)
    return TEMPLATES.TemplateResponse(request, "panel/health.html", {"health": result})


@router.post("/friends", response_class=HTMLResponse)
async def create_friend(
    request: Request,
    nickname: str = Form(...),
    session: AsyncSession = Depends(session_dependency),
):
    await friends.create_friend(session, nickname=nickname)
    return RedirectResponse(url="/panel/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/friends/{friend_id}/subscription", response_class=HTMLResponse)
async def friend_subscription(
    friend_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Show the URL to send this friend.

    A fragment shown on demand rather than a column in the friends table: the table
    is the page the operator leaves open, and a live bearer credential should not sit
    on screen — or in a screenshot — the whole time.
    """
    friend = await friends.get_friend(session, friend_id)
    live = [s for s in friend.subscriptions if s.is_active]
    settings = request.app.state.settings
    return TEMPLATES.TemplateResponse(
        request,
        "panel/subscription.html",
        {
            "friend": friend,
            "url": f"{settings.public_base_url}/sub/{live[0].token}" if live else None,
        },
    )


@router.post("/friends/{friend_id}/revoke", response_class=HTMLResponse)
async def revoke_friend(
    friend_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Revoke everywhere, and show the honest outcome — including partial success."""
    outcome = await revocation.revoke_friend(session, friend_id=friend_id)
    return TEMPLATES.TemplateResponse(
        request,
        "panel/outcome.html",
        {"message": outcome.summary(), "ok": outcome.complete},
    )
