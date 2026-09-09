"""The admin panel — the screen the owner lives in.

WHAT: login, the console (Overview and Users), the fleet page, and the actions on each.
WHY:  criteria 2 and 3 are both phrased "from the panel", so this is not a
      convenience layer over the API — it is where those criteria are met.
HOW:  full pages for navigations, HTML FRAGMENTS for HTMX actions. The control
      rulebook names the trap: returning a full document from a partial route nests
      ``<html>`` inside the page and the bug looks like CSS.

      Autoescaping stays on everywhere. Node names, friend nicknames and error
      strings are attacker-influenced text — a friend's nickname is typed by the
      operator, but a node's ``state_detail`` can contain text from a remote host —
      and a ``|safe`` on any of them is an injection.

Two panels live here at once, on purpose and temporarily. The CONSOLE is the
redesign in ``design/`` — a persistent sidebar over a swappable ``#main``, one screen
per route, every creation flow in a dialog. Overview and Users are ported; the fleet
screens follow in M9. Until they do, ``/panel/fleet`` serves the original single
page and the sidebar has an honest entry pointing at it, because a dead nav link is
worse than an ugly one. M9.5 retires that page once every action it carries has a new
home — do not delete it before then.
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
from control.app.panel import wording
from control.app.services import (
    apply,
    console,
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


# --- the console -------------------------------------------------------------

# The sidebar, in the order the design lists it. Every screen the console can reach
# is here and nothing else is: an entry pointing nowhere is the failure this list
# exists to prevent.
#
# ``boost`` false means an ordinary browser navigation to a page that has not been
# redesigned yet — it leaves the console shell rather than swapping into it, and the
# entry says so under its label instead of pretending otherwise.
#
# There is no Traffic entry, and its slot is given to nothing. That is decision 6's
# sharper half: a screen that exists to say "we do not measure this" is an invitation
# to add the measurement later.
NAV = (
    {"key": "overview", "label": "Overview", "url": "/panel/", "boost": True, "note": ""},
    {"key": "friends", "label": "Users", "url": "/panel/friends", "boost": True, "note": ""},
    {
        "key": "fleet",
        "label": "Fleet",
        "url": "/panel/fleet",
        "boost": False,
        "note": "nodes · hops · transports",
    },
)


def _is_htmx(request: Request) -> bool:
    """Whether htmx asked for this, rather than a browser navigating or reloading.

    A HISTORY RESTORE is the exception, and it is why this is a function rather than
    one header lookup. When the operator presses Back, htmx re-asks the server for
    the URL with ``HX-Request: true`` AND ``HX-History-Restore-Request: true``, then
    swaps what comes back into the HISTORY ELEMENT — the whole ``<body>``, not
    ``#main``. Answering that with a fragment replaces the shell with a bare screen:
    no sidebar, no header, no dialog slot. So a restore is served the whole document,
    exactly like a browser navigation, and htmx takes the body out of it.
    """
    if request.headers.get("HX-History-Restore-Request") == "true":
        return False
    return request.headers.get("HX-Request") == "true"


def _screen(
    request: Request,
    *,
    screen: str,
    current: str,
    title: str,
    subtitle: str,
    context: dict | None = None,
) -> Response:
    """One console screen, as a whole page or as the fragment ``#main`` takes.

    Both branches include the SAME screen template, so a reload and a sidebar click
    cannot render different things — which is the way this kind of shell usually
    rots. The fragment additionally carries the nav list out of band, because the
    sidebar sits outside ``#main`` and would otherwise keep highlighting the screen
    the operator just left.
    """
    payload = {
        "screen": screen,
        "current": current,
        "title": title,
        "subtitle": subtitle,
        "nav": NAV,
        "operator": request.app.state.settings.operator_username,
        **(context or {}),
    }
    if _is_htmx(request):
        return TEMPLATES.TemplateResponse(
            request, "panel/screen.html", {**payload, "oob": True}
        )
    return TEMPLATES.TemplateResponse(request, "pages/console.html", payload)


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request, session: AsyncSession = Depends(session_dependency)):
    """Overview — the fleet's health, in facts about the fleet and never about a person."""
    return _screen(
        request,
        screen="panel/screens/overview.html",
        current="overview",
        title="Overview",
        subtitle=(
            "what is serving, who can dial it, and whether the nodes are running "
            "what you told them to"
        ),
        context={"overview": await console.overview(session)},
    )


@router.get("/overview/body", response_class=HTMLResponse)
async def overview_body(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The Overview's content on its own, for the refresh after a mutation."""
    return TEMPLATES.TemplateResponse(
        request, "panel/overview_body.html", {"overview": await console.overview(session)}
    )


@router.get("/friends", response_class=HTMLResponse)
async def friends_screen(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Users — the people who can dial the mesh.

    The screen says "users" and this function, its route and everything under it say
    ``friend``. Decision 9: the rename stops at the rendered page.
    """
    return _screen(
        request,
        screen="panel/screens/friends.html",
        current="friends",
        title="Users",
        subtitle="who can dial the mesh, and the one URL each of them holds",
        context=await _friends_context(session),
    )


@router.get("/friends/table", response_class=HTMLResponse)
async def friends_table(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The users table on its own, for the refresh after a mutation."""
    return TEMPLATES.TemplateResponse(
        request, "panel/friends_table.html", await _friends_context(session)
    )


async def _friends_context(session: AsyncSession) -> dict:
    """What the users table needs, in one place so the screen and the refresh agree."""
    return {
        "friends": await console.friend_rows(session),
        "serving": len(await nodes.serving_transports(session)),
    }


@router.get("/friends/new", response_class=HTMLResponse)
async def add_friend_dialog(request: Request) -> Response:
    """The empty add-user dialog. No session work: it asks for one field."""
    return TEMPLATES.TemplateResponse(
        request, "panel/add_friend_dialog.html", {"nickname": "", "error": None}
    )


# --- the fleet page (pre-redesign; M9 ports its three screens) -----------------

@router.get("/fleet", response_class=HTMLResponse)
async def fleet(request: Request, session: AsyncSession = Depends(session_dependency)):
    """The original single page: nodes, the hops between them, and what the image ships.

    Still the screen that owns all three of those facts until M9 gives each its own.
    It is reached from the sidebar's one honest entry, and it is deliberately NOT
    inside the console shell — half-porting it would leave the operator unable to tell
    which parts had been redesigned.
    """
    installed = sorted(discover().values(), key=lambda meta: meta.name)
    return TEMPLATES.TemplateResponse(
        request,
        "pages/index.html",
        {
            "nodes": await nodes.list_nodes(session),
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
    """Register a node from the panel. Redirects so a reload does not re-post.

    Back to the fleet page rather than to ``/panel/``, which is the console's Overview
    now: the operator was on the page carrying the form and that is where the new node
    appears.
    """
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
    return RedirectResponse(url="/panel/fleet", status_code=status.HTTP_303_SEE_OTHER)


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


def _mutation(
    request: Request,
    *,
    dialog: str | None = None,
    toast: str | None = None,
    banner: str | None = None,
    events: str | None = None,
    context: dict | None = None,
    keeping: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    """The one answer shape every console mutation gives.

    Something for the dialog slot (a new dialog, or ``None`` — which closes the open
    one), plus at most one out-of-band toast or banner, plus the events that tell the
    screen's tables to refresh themselves. Routed through one function so
    "every mutation emits a toast naming its object" (UI-PATTERNS §8) is checkable by
    reading the call sites rather than every template.

    Both sentences pass through ``wording.for_the_page``: they are composed in
    ``services/``, which speaks the code's vocabulary, and decision 9 says that word
    stops before the rendered page. ``keeping`` is the operator's own text inside the
    sentence — a nickname — which is handed back exactly as they typed it.
    """
    response = TEMPLATES.TemplateResponse(
        request,
        "panel/mutation_result.html",
        {
            "dialog": dialog,
            "toast": wording.for_the_page(toast, keeping=keeping) if toast else None,
            "banner": wording.for_the_page(banner, keeping=keeping) if banner else None,
            **(context or {}),
        },
        status_code=status_code,
    )
    if events:
        response.headers["HX-Trigger"] = events
    return response


@router.post("/friends", response_class=HTMLResponse)
async def create_friend(
    request: Request,
    nickname: str = Form(""),
    session: AsyncSession = Depends(session_dependency),
):
    """Create a user and hand back their link, in one exchange.

    M8.5's whole behaviour is in the return values: on success the response REPLACES
    the add-user dialog with the subscription-link dialog, so the operator never has
    to go looking for the thing they just created — which is the primary job the
    design optimises for. ``friends-created`` additionally routes the console to
    Users, and ``friends-changed`` refreshes whichever tables are on screen.

    A refusal comes back as the same dialog with the message under the field it is
    about, at 422. Field-level and not a toast: a toast is gone in 2200ms and would
    leave the operator staring at a form that will not submit.
    """
    nickname = nickname.strip()
    try:
        friend = await friends.create_friend(session, nickname=nickname)
    except DomainError as exc:
        return TEMPLATES.TemplateResponse(
            request,
            "panel/add_friend_dialog.html",
            # Decision 9 in the direction the console had been leaking: the refusal
            # is composed in the service, which says ``friend``, and the operator
            # reads ``user``. No ``keeping`` here — a service quotes the nickname
            # (``{value!r}``), and quoted text is data the boundary never rewrites.
            {"nickname": nickname, "error": wording.for_the_page(exc.message)},
            # 422 rather than 200, and htmx is configured in static/app.js to swap
            # this one status: an invalid form is not a success, and saying so is
            # what keeps the failure banner from firing on it as well.
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    return _mutation(
        request,
        dialog="panel/subscription_dialog.html",
        toast=f"{friend.nickname} added",
        keeping=friend.nickname,
        # Only ``friends-created``. It routes the console to Users (see the listener
        # on #main in pages/console.html), and the screen it lands on renders the
        # table fresh — so also firing ``friends-changed`` would start a second
        # refresh of a table that is about to be replaced under it.
        events="friends-created",
        context={
            "friend": friend,
            "url": await console.subscription_url(
                session, request.app.state.settings.public_base_url, friend
            ),
        },
    )


@router.get("/friends/{friend_id}/subscription", response_class=HTMLResponse)
async def friend_subscription(
    friend_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Show the URL to send this friend, in its own dialog.

    On demand rather than as a column in the users table: the table is the page the
    operator leaves open, and a live bearer credential should not sit on screen — or
    in a screenshot — the whole time. UI-PATTERNS §9 gives the URL its own dialog with
    a copy button for exactly this reason.
    """
    friend = await friends.get_friend(session, friend_id)
    return TEMPLATES.TemplateResponse(
        request,
        "panel/subscription_dialog.html",
        {
            "friend": friend,
            "url": await console.subscription_url(
                session, request.app.state.settings.public_base_url, friend
            ),
        },
    )


@router.get("/friends/{friend_id}/revoke", response_class=HTMLResponse)
async def revoke_friend_dialog(
    friend_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The confirmation. UI-PATTERNS §3: destructive actions confirm in a dialog."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/revoke_dialog.html",
        {"friend": await friends.get_friend(session, friend_id)},
    )


@router.post("/friends/{friend_id}/revoke", response_class=HTMLResponse)
async def revoke_friend(
    friend_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Revoke everywhere, and report the honest outcome — including partial success.

    The nickname is read BEFORE the revocation so the message names the person even
    if the revocation path detaches the row.

    A complete revocation gets a toast. An incomplete one gets a BANNER instead, and
    the difference is deliberate: a revocation that could not reach every node leaves
    somebody still connected, and a message that removes itself after 2200ms is the
    wrong carrier for that. The banner stays until the next successful action.
    """
    friend = await friends.get_friend(session, friend_id)
    nickname = friend.nickname
    outcome = await revocation.revoke_friend(session, friend_id=friend_id)
    return _mutation(
        request,
        toast=f"{nickname} revoked — link is dead" if outcome.complete else None,
        banner=None if outcome.complete else outcome.summary(),
        events="friends-changed",
        keeping=nickname,
    )
