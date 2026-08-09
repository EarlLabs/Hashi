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
from control.app.models import NodeState
from control.app.services import (
    apply,
    friends,
    health,
    nodes,
    relay,
    revocation,
    rotation,
    transports,
)
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
    installed = sorted(discover().values(), key=lambda meta: meta.name)
    return TEMPLATES.TemplateResponse(
        request,
        "pages/index.html",
        {
            "nodes": await nodes.list_nodes(session),
            "friends": await friends.list_friends(session),
            "transports": installed,
            "hops": await relay.list_hops(session),
            # A hop's transport is one whose configuration is consumed as a FILE by a
            # node rather than as a link by a phone — which is what
            # ``subscription_expressible`` being false has always meant here, and it
            # still means it after item 27. Offering the URI ones would invite the
            # operator to build a tunnel out of a friend-facing link; offering only
            # these makes the form say what it is for.
            #
            # Note the overlap this now allows and which is correct: a transport can be
            # in this list AND offerable to friends. AmneziaWG is exactly that — it runs
            # the border-crossing hop, and since item 26 it also serialises a file a
            # friend can import.
            #
            # Since item 28 the filter also drops transports that declare they cannot
            # carry a hop at all. Both conditions are needed and neither implies the
            # other: plain WireGuard is a config file too, so the first alone would have
            # offered it here — and the renderer would refuse it, after the operator had
            # filled in a form.
            "hop_transports": [
                meta.name
                for meta in installed
                if not meta.subscription_expressible and meta.hop_capable
            ],
            "hop_params": {
                meta.name: transports.operator_params(meta.name)
                for meta in installed
                if not meta.subscription_expressible and meta.hop_capable
            },
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
            # Only the transitions this node may actually make, so the page cannot
            # offer a button whose only outcome is a 409. ``retired`` is absent from
            # a retired node's list for the reason in ``NodeState.allowed_from``:
            # bringing back a record whose host is gone puts an address that may now
            # belong to a stranger into every friend's subscription.
            "state_options": NodeState.allowed_from(node.state),
            # What the operator may retype on a transport already enabled here —
            # item 24's rotation form. Only transports still installed in this image
            # get one: a node running something this image no longer ships cannot be
            # re-validated here, and offering the form would promise otherwise.
            "editable": {
                t.transport_name: transports.operator_params(t.transport_name)
                for t in node.transports
                if t.transport_name in installed
            },
            # Only transports not already on this node, so the form cannot offer an
            # action that is guaranteed to conflict.
            "available": sorted(
                meta.name
                for meta in installed.values()
                if meta.name not in {t.transport_name for t in node.transports}
                # A transport a friend could not receive in ANY shape is not offered at
                # all, rather than offered and then refused. Since item 27 that is a
                # narrower set than "not a URI": a transport whose configuration is a
                # file is deliverable now, and the panel has to stop hiding it or the
                # second format exists and nobody can switch it on.
                and meta.subscription_formats
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

    # Reading the form is shared with the rotation form below: a field the transport
    # declared as a sequence becomes a list whether or not the operator typed a comma.
    params = transports.parse_form(
        transport_name,
        (
            (key, str(value))
            for key, value in form.multi_items()
            if key != "transport_name"
        ),
    )

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


@router.post("/nodes/{node_id}/state", response_class=HTMLResponse)
async def set_node_state(
    node_id: str,
    request: Request,
    state: str = Form(...),
    detail: str = Form(""),
    session: AsyncSession = Depends(session_dependency),
):
    """Move a node between states from the panel — charter criterion 2.

    The API has had this since item 17; the panel had not, which made "the
    replacement node is raised FROM THE PANEL" unprovable — an operator could create
    the node and enable its protocol on a screen, then had to reach for curl to put
    it into service. The criterion is written about the panel, so it is met here.

    A fragment rather than a redirect: putting a node into service hands every
    existing friend a credential on it, and how many is what the operator wants to
    read without navigating away.
    """
    try:
        node = await nodes.set_node_state(
            session,
            node_id=node_id,
            state=NodeState(state),
            detail=detail or None,
        )
        message, ok = f"{node.name} is now {node.state}.", True
    except ValueError:
        # An unknown string, before the service ever sees it. Names the vocabulary
        # rather than echoing what was typed — the value came from a form.
        message, ok = (
            f"{state!r} is not a state a node can be in. Known states: "
            f"{', '.join(sorted(NodeState))}."
        ), False
    except DomainError as exc:
        message, ok = exc.message, False
    return TEMPLATES.TemplateResponse(
        request, "panel/outcome.html", {"message": message, "ok": ok}
    )


@router.post("/transports/{node_transport_id}/state", response_class=HTMLResponse)
async def set_transport_enabled(
    node_transport_id: str,
    request: Request,
    enabled: str = Form(...),
    session: AsyncSession = Depends(session_dependency),
):
    """Offer a protocol to friends, or withdraw it — charter criterion 3.

    Read as an explicit wanted value ("true"/"false") rather than a toggle, so a
    double-submitted form does not put the fleet in the state the operator was
    trying to leave. Anything that is not truthy is read as off, which is the safe
    direction to be wrong in: it withdraws an offer rather than making one.
    """
    wanted = enabled.strip().lower() in {"1", "true", "on", "yes"}
    try:
        node_transport = await nodes.set_transport_enabled(
            session, node_transport_id=node_transport_id, enabled=wanted
        )
        message, ok = (
            (
                f"{node_transport.transport_name} is offered to friends again — it is "
                "in every active friend's subscription at their next refresh."
            )
            if wanted
            else (
                f"{node_transport.transport_name} is out of every subscription. The "
                "node is still configured to serve it: re-apply the node to stop that."
            )
        ), True
    except DomainError as exc:
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


# --- hops between nodes (item 16), from the panel -----------------------------

@router.post("/hops", response_class=HTMLResponse)
async def create_hop(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Establish both ends of an entry→leaf tunnel from one form.

    The form carries each end's parameters prefixed with ``entry-`` / ``leaf-``. The
    prefix is stripped here and nowhere else: below this line the two mappings are
    ordinary transport parameters, validated by the transport's own model, and this
    function still names no field of any protocol.
    """
    form = await request.form()
    transport_name = str(form.get("transport_name", ""))

    def side(prefix: str) -> dict:
        return transports.parse_form(
            transport_name,
            (
                (key.removeprefix(prefix), str(value))
                for key, value in form.multi_items()
                if key.startswith(prefix)
            ),
        )

    try:
        await relay.establish_hop(
            session,
            entry_node_id=str(form.get("entry_node_id", "")),
            leaf_node_id=str(form.get("leaf_node_id", "")),
            transport_name=transport_name,
            entry_params=side("entry-"),
            leaf_params=side("leaf-"),
        )
        message, ok = (
            "hop established. Apply BOTH nodes to bring the tunnel up — until then it "
            "exists only in the database."
        ), True
    except DomainError as exc:
        message, ok = exc.message, False
    return TEMPLATES.TemplateResponse(
        request, "panel/outcome.html", {"message": message, "ok": ok}
    )


@router.post("/hops/{node_transport_id}/dissolve", response_class=HTMLResponse)
async def dissolve_hop(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Remove both ends of a hop, and say which nodes now need re-applying."""
    try:
        affected = await relay.dissolve_hop(session, node_transport_id=node_transport_id)
        message, ok = (
            f"hop removed. Re-apply {len(affected)} node(s) so they stop holding a "
            "tunnel to an exit that is no longer configured."
        ), True
    except DomainError as exc:
        message, ok = exc.message, False
    return TEMPLATES.TemplateResponse(
        request, "panel/outcome.html", {"message": message, "ok": ok}
    )


# --- rotation (items 23 and 24), from the panel -------------------------------

@router.post("/transports/{node_transport_id}/rotate-keys", response_class=HTMLResponse)
async def rotate_keys(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Re-mint this transport's key material and push it — item 23.

    A fragment, not a redirect: the outcome of a rotation is the whole point of
    pressing the button. "Rotated, but the node could not be updated" has to be
    readable on the page, because until it is retried the node still runs the old
    material.
    """
    try:
        outcome = await rotation.rotate_keys(session, node_transport_id=node_transport_id)
        message, ok = outcome.summary(), outcome.complete
    except DomainError as exc:
        message, ok = exc.message, False
    return TEMPLATES.TemplateResponse(
        request, "panel/outcome.html", {"message": message, "ok": ok}
    )


@router.post("/transports/{node_transport_id}/params", response_class=HTMLResponse)
async def replace_params(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Replace operator-supplied parameters — item 24, a blocked decoy being the case.

    Reads the form the same way ``enable_transport`` does, and for the same reason:
    this function must not know any protocol's field names. Only fields the operator
    actually filled in are sent, so an untouched box means "leave it alone" rather
    than "set it to empty".
    """
    form = await request.form()
    try:
        node_transport = await rotation.get_node_transport(session, node_transport_id)
        params = transports.parse_form(
            node_transport.transport_name,
            ((key, str(value)) for key, value in form.multi_items()),
        )
        if not params:
            raise DomainError("nothing was filled in, so there is nothing to change")
        outcome = await rotation.replace_params(
            session, node_transport_id=node_transport_id, params=params
        )
        message, ok = outcome.summary(), outcome.complete
    except DomainError as exc:
        message, ok = exc.message, False
    return TEMPLATES.TemplateResponse(
        request, "panel/outcome.html", {"message": message, "ok": ok}
    )


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
