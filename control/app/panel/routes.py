"""The admin panel — the screen the owner lives in.

WHAT: login, the console (Overview, Users, Nodes, Hops, Transports, Keys & configs),
      the fleet page, and the actions on each.
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
per route, every creation flow in a dialog. Overview, Users, Nodes, Hops, Transports
and Keys & configs are ported; the rest of M9 is what is left. Until it lands,
``/panel/fleet`` serves the original single page and the sidebar has an honest entry
pointing at it, because a dead nav link is worse than an ugly one — and its note names
only what is still there, which is now nothing: every LIST that page carried has its
own screen. M9.6 retires it once every ACTION it carries has a new home too: still on
it are enabling and withdrawing a transport and moving a node between states. Key
rotation and parameter replacement moved to the Keys & configs screen in M9.4, and
that page's own two rotation routes stay until the page goes — it drives them with
htmx, so they cannot be told apart from the console's by a header. Do not delete
either before then.
"""

import logging
import pathlib

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from control.app import auth
from control.app.api import schemas
from control.app.dependencies import session_dependency
from control.app.errors import DomainError, HopEndRefused, ParamsRefused
from control.app.models import NodeState, TransportPurpose
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
    {"key": "nodes", "label": "Nodes", "url": "/panel/nodes", "boost": True, "note": ""},
    {"key": "hops", "label": "Hops", "url": "/panel/hops", "boost": True, "note": ""},
    {
        "key": "transports",
        "label": "Transports",
        "url": "/panel/transports",
        "boost": True,
        "note": "",
    },
    {
        "key": "keys",
        "label": "Keys & configs",
        "url": "/panel/keys",
        "boost": True,
        "note": "",
    },
    # Shrinking as M9 ports it. The note is what is LEFT on the old page, so an
    # operator can tell from the sidebar which jobs have moved and which have not —
    # nodes came out of it in M9.1, hops in M9.2, the capability table in M9.3 and both
    # rotations in M9.4, and the note is empty because the three THINGS that page
    # listed have all moved. What is still only there is a pair of ACTIONS on a node —
    # enable and withdraw a transport, move a node between states — which M9.5 homes
    # and M9.6 removes this entry with the page.
    {
        "key": "fleet",
        "label": "Fleet",
        "url": "/panel/fleet",
        "boost": False,
        "note": "",
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


# --- Nodes (M9.1) ------------------------------------------------------------

# These three come BEFORE ``/nodes/{node_id}`` further down the file, and the order is
# load-bearing: FastAPI matches in registration order, so a literal path declared after
# a path parameter would be swallowed by it.

@router.get("/nodes", response_class=HTMLResponse)
async def nodes_screen(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Nodes — the machines that serve traffic and the machines that exit it."""
    return _screen(
        request,
        screen="panel/screens/nodes.html",
        current="nodes",
        title="Nodes",
        subtitle=(
            "the machines a user's link resolves to, and whether each is running "
            "what you told it to"
        ),
        context={"nodes": await console.node_rows(session)},
    )


@router.get("/nodes/table", response_class=HTMLResponse)
async def nodes_table(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The nodes table on its own, for the refresh after a mutation."""
    return TEMPLATES.TemplateResponse(
        request, "panel/nodes_table.html", {"nodes": await console.node_rows(session)}
    )


@router.get("/nodes/new", response_class=HTMLResponse)
async def add_node_dialog(request: Request) -> Response:
    """The empty add-node dialog. No session work: it asks for a record, not a fleet."""
    return TEMPLATES.TemplateResponse(request, "panel/add_node_dialog.html", _node_form())


def _node_form(
    values: dict | None = None,
    errors: dict | None = None,
    *,
    key_dropped: bool = False,
) -> dict:
    """What the add-node dialog needs, in one place so first paint and refusal agree.

    ``defaults`` comes from ``services/nodes.py`` rather than from the template because
    M9 forbids a template naming a port — and because the value the form suggests and
    the value the service applies when the box is left empty must be the same one.

    ``key_dropped`` is true when the operator pasted a private key into a submission
    that was then refused. The key is deliberately not put back into the markup, and
    saying so AT THAT MOMENT is the difference between a rule and a trap: otherwise
    somebody fixes the field that was wrong, resubmits, and registers a node with no
    key at all — a failure that surfaces much later as an apply that cannot connect.
    It is false when they pasted nothing, because "your key was not kept" about a key
    that never existed is its own confusion.
    """
    return {
        "values": values or {},
        "errors": errors or {},
        "key_dropped": key_dropped,
        "defaults": {
            "ssh_user": nodes.DEFAULT_SSH_USER,
            "ssh_port": nodes.DEFAULT_SSH_PORT,
        },
    }


# --- Hops (M9.2) -------------------------------------------------------------

# The two ends of a hop, in the order the topology forces: the entry is the node
# friends dial and the one that DIALS OUT, because a node behind a Russian carrier NAT
# cannot be dialled. ``prefix`` is what each end's parameters are named with in the
# form, and it is the same prefix ``create_hop`` below has always stripped — declared
# once here so the dialog that writes it and the route that reads it cannot drift.
#
# ``purpose`` is the same end in the vocabulary ``services/relay.py`` speaks, so a
# refusal that names one end can be put back on that end's boxes. One table, so the two
# mappings cannot disagree about which end is which.
HOP_SIDES = (
    {
        "prefix": "entry",
        "label": "entry end",
        "note": "the node users dial",
        "purpose": TransportPurpose.RELAY_ENTRY,
    },
    {
        "prefix": "leaf",
        "label": "leaf end",
        "note": "the node traffic leaves from",
        "purpose": TransportPurpose.RELAY_LEAF,
    },
)

# What a box that was left empty is answered with when the transport declares no
# default for it. Field-level, at 422, like every other refusal in the console: a hop
# with twenty-four parameters cannot be corrected from one sentence at the top.
NO_DEFAULT = "required — this transport declares no default to fall back on"


@router.get("/hops", response_class=HTMLResponse)
async def hops_screen(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Hops — the tunnel a node's traffic leaves through, and where it comes out."""
    return _screen(
        request,
        screen="panel/screens/hops.html",
        current="hops",
        title="Hops",
        subtitle=(
            "which node a user's traffic arrives at, and which node it leaves from"
        ),
        context={"hops": await console.hop_rows(session)},
    )


@router.get("/hops/table", response_class=HTMLResponse)
async def hops_table(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The hops table on its own, for the refresh after a mutation."""
    return TEMPLATES.TemplateResponse(
        request, "panel/hops_table.html", {"hops": await console.hop_rows(session)}
    )


@router.get("/hops/new", response_class=HTMLResponse)
async def establish_hop_dialog(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """The empty establish-hop dialog. It needs the fleet: two of its three questions
    are which node."""
    return TEMPLATES.TemplateResponse(
        request, "panel/establish_hop_dialog.html", await _hop_form(session)
    )


async def _hop_form(
    session: AsyncSession,
    values: dict | None = None,
    errors: dict | None = None,
    *,
    failure: str | None = None,
) -> dict:
    """What the establish-hop dialog needs, in one place so first paint and refusal
    agree.

    ``tuning`` is per transport and comes from ``services/transports.py``, which reads
    it out of the transport's own declaration. That is M9's "no template names a
    transport, a country, an address or a port" made structural rather than checked:
    this dialog has twenty-two boxes and not one of them has a value written into the
    markup.

    Everything the operator typed comes back on a refusal, all of it — unlike the
    add-node dialog, which drops the private key. There is no key in this form to drop:
    a hop's material is minted at both ends and the value the two must share is minted
    once for both, so the panel never asks for one.
    """
    installed = transports.hop_transports()
    return {
        "nodes": await nodes.list_nodes(session),
        "transports": installed,
        "tuning": {name: transports.hop_tuning(name) for name in installed},
        "sides": HOP_SIDES,
        "values": values or {},
        "errors": errors or {},
        # A refusal the transport or the hop renderer composed, about the pair rather
        # than about one box. Shown inside the dialog because that is where the
        # operator is, and app.js clears it on the next attempt.
        "failure": failure,
        # A refusal is worthless behind a closed disclosure: the operator would read
        # "11 parameters per end" and no message at all. Open it for a refusal that
        # landed on a tuning box, and for one about the PAIR as well — everything the
        # hop renderer refuses is a disagreement between two values that are in there.
        "open_tuning": failure is not None or any("-" in key for key in (errors or {})),
    }


@router.post("/hops/establish", response_class=HTMLResponse)
async def establish_hop(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Establish both ends of an entry→leaf tunnel from the console's dialog.

    ``/hops/establish`` and not ``/hops`` only because ``POST /panel/hops`` still
    belongs to the pre-redesign page below, which asks for it with htmx too and
    answers into ``panel/outcome.html`` — so unlike the add-node form the two cannot
    be told apart by a header. M9.6 takes the shorter name back when it deletes that
    page.

    The form is read the same way ``create_hop`` reads it: each end's parameters
    arrive prefixed, the prefix is stripped, and below that line this function still
    names no field of any protocol. What is added here is that the fields are
    FILTERED to the chosen transport's own list before they are parsed — the dialog
    renders a group per hop-capable transport and only hides the ones not chosen, so
    without the filter a second transport's boxes would arrive and be refused by a
    model that forbids extras.
    """
    form = await request.form()
    typed = {key: str(value).strip() for key, value in form.multi_items()}
    transport_name = typed.get("transport_name", "")

    errors: dict[str, str] = {}
    for question in ("entry_node_id", "leaf_node_id", "transport_name"):
        if not typed.get(question):
            errors[question] = "required — a hop cannot be established without it"

    tuning = (
        transports.hop_tuning(transport_name)
        if transport_name in transports.hop_transports()
        else ()
    )
    for side in HOP_SIDES:
        for parameter in tuning:
            field = f"{side['prefix']}-{parameter.name}"
            if parameter.required and not typed.get(field):
                errors[field] = NO_DEFAULT

    if errors:
        return await _refuse_hop(request, session, values=typed, errors=errors)

    def supplied(prefix: str) -> dict:
        return transports.parse_form(
            transport_name,
            (
                (parameter.name, typed.get(f"{prefix}-{parameter.name}", ""))
                for parameter in tuning
            ),
        )

    try:
        await relay.establish_hop(
            session,
            entry_node_id=typed.get("entry_node_id", ""),
            leaf_node_id=typed.get("leaf_node_id", ""),
            transport_name=transport_name,
            entry_params=supplied("entry"),
            leaf_params=supplied("leaf"),
        )
    except HopEndRefused as exc:
        # The transport refused one end's parameters, field by field, and this form has
        # a box for each of them — so each complaint goes under the box it is about,
        # exactly like an empty one. Flattened into a sentence at the top it would send
        # the operator scrolling twenty-four boxes hunting for the parameter the prose
        # names, mid-rotation, which is the moment this dialog exists for.
        return await _refuse_hop(
            request, session, values=typed, **_on_their_boxes(exc, tuning)
        )
    except DomainError as exc:
        # Everything else a hop refuses is about the PAIR — two ends on different tunnel
        # networks, a node that is its own exit, a transport that cannot cross the
        # border. There is no one box to put those under, so they are stated once, above
        # the form, beside what the operator typed.
        return await _refuse_hop(
            request, session, values=typed, failure=wording.for_the_page(exc.message)
        )

    return _mutation(
        request,
        # UI-PATTERNS §8: an action with a delayed real-world effect says so. Nothing
        # is carrying traffic until both nodes are applied — until then the hop exists
        # only in the database, and a toast reading "hop established" would be the
        # panel telling the operator a tunnel is up that has never been pushed.
        toast="hop establishing — apply both nodes to bring it up",
        # Both, because a hop is two node-transport rows: the Nodes screen tags them on
        # the two nodes it lists, and its table is refreshed by the other event.
        events="hops-changed, nodes-changed",
    )


def _on_their_boxes(exc: HopEndRefused, tuning: tuple) -> dict:
    """One end's per-field refusal, sorted into the boxes that can show it.

    A parameter with a box on this form gets the message under it. Anything else — a
    complaint about a field this dialog does not render, or one Pydantic located
    somewhere other than a top-level field — falls back to the sentence above the form,
    because a message addressed to a box that does not exist is a message nobody reads.
    That fallback is the whole reason this is a function: it is the case that cannot be
    seen while it works.
    """
    prefix = next(
        side["prefix"] for side in HOP_SIDES if side["purpose"] == exc.purpose
    )
    boxes = {parameter.name for parameter in tuning}
    errors = {
        f"{prefix}-{field}": wording.for_the_page(message)
        for field, message in exc.fields.items()
        if field in boxes
    }
    homeless = [
        f"{field}: {message}"
        for field, message in exc.fields.items()
        if field not in boxes
    ]
    return {
        "errors": errors,
        "failure": (
            wording.for_the_page(
                f"the {prefix} end was refused — {'; '.join(homeless)}"
            )
            if homeless
            else None
        ),
    }


async def _refuse_hop(
    request: Request,
    session: AsyncSession,
    *,
    values: dict,
    errors: dict | None = None,
    failure: str | None = None,
) -> Response:
    """The establish-hop dialog again, at 422, with what was typed still in it."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/establish_hop_dialog.html",
        await _hop_form(session, values=values, errors=errors, failure=failure),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


@router.get("/hops/{node_transport_id}/tear-down", response_class=HTMLResponse)
async def tear_down_hop_dialog(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """The confirmation. UI-PATTERNS §3: destructive actions confirm in a dialog."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/tear_down_hop_dialog.html",
        {"hop": await console.hop_row(session, node_transport_id)},
    )


@router.post("/hops/{node_transport_id}/tear-down", response_class=HTMLResponse)
async def tear_down_hop(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Remove both ends of a hop from the console, and say what is left to do.

    Its own route rather than the ``/dissolve`` one below for the same reason as the
    node's ``/push``: that one answers the pre-redesign page with a different
    fragment. M9.6 takes the shorter name back.

    A toast and not a banner: tearing a hop down is the operator's own deliberate act
    and it succeeded. What it leaves behind — two nodes still holding a tunnel to an
    exit that is gone — is in the sentence, and the row it names is gone from the table
    behind it.
    """
    try:
        affected = await relay.dissolve_hop(session, node_transport_id=node_transport_id)
    except DomainError as exc:
        # Shown, not raised: a hop that could not be torn down is a fault the operator
        # has to still be able to read while they act on it.
        return _mutation(request, banner=wording.for_the_page(exc.message))
    return _mutation(
        request,
        toast=console.tear_down_summary(affected),
        events="hops-changed, nodes-changed",
    )


# --- Transports (M9.3) -------------------------------------------------------

@router.get("/transports", response_class=HTMLResponse)
async def transports_screen(request: Request) -> Response:
    """Transports — what this image can speak, and what each protocol survives.

    Read-only, and the only console screen that takes no session: its whole content is
    discovered from the packages under ``edge/transports/``, so there is nothing about
    the fleet on it and nothing a query could add. It also has no self-swapping
    fragment for the same reason — the other three screens have one so a mutation can
    refresh them, and no mutation in this panel can change which protocols the image
    ships. A ``/panel/transports/table`` URL would exist only to be listed.

    Note that ``GET /panel/transports`` cannot collide with the pre-redesign page's
    ``POST /panel/transports/{node_transport_id}/...`` routes further down: different
    method, different shape. M9.5 homes those actions and M9.6 deletes the page.
    """
    return _screen(
        request,
        screen="panel/screens/transports.html",
        current="transports",
        title="Transports",
        subtitle=(
            "the protocols this image can speak, and which of them survives a network "
            "that inspects traffic"
        ),
        context={"transports": console.transport_rows()},
    )


# --- Keys & configs (M9.4) ---------------------------------------------------

# What a form with every box empty is answered with. Field-level would be wrong here
# and it is the one place in the console where it is: an empty box on this form is a
# meaningful answer — "keep this value" — so there is no single box to put the message
# under. It is the form as a whole that said nothing.
NOTHING_TYPED = (
    "nothing was typed, so there is nothing to replace — an empty box keeps the value "
    "that is already in place"
)


@router.get("/keys", response_class=HTMLResponse)
async def keys_screen(request: Request, session: AsyncSession = Depends(session_dependency)):
    """Keys & configs — what each node holds, and how to replace it.

    The screen the charter's "rotate anything that gets blocked, all from one admin
    panel" lands on, and the one screen in this console whose whole subject is material
    that may never be displayed. UI-PATTERNS §9 is therefore its layout rule rather than
    a detail of it: every cell that could have held a value holds a fingerprint or the
    rule instead, and both come from services/console.py already composed.
    """
    return _screen(
        request,
        screen="panel/screens/keys.html",
        current="keys",
        title="Keys & configs",
        subtitle=(
            "what each node holds, and how to replace it without anyone re-importing "
            "their link"
        ),
        context={"keys": await console.key_rows(session)},
    )


@router.get("/keys/table", response_class=HTMLResponse)
async def keys_table(request: Request, session: AsyncSession = Depends(session_dependency)):
    """The keys table on its own, for the refresh after a rotation."""
    return TEMPLATES.TemplateResponse(
        request, "panel/keys_table.html", {"keys": await console.key_rows(session)}
    )


@router.get("/keys/{node_transport_id}/rotate", response_class=HTMLResponse)
async def rotate_keys_dialog(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """The confirmation. UI-PATTERNS §3: a destructive action confirms in a dialog."""
    key = await console.key_row(session, node_transport_id)
    return TEMPLATES.TemplateResponse(
        request,
        "panel/rotate_keys_dialog.html",
        {
            "key": key,
            # Composed in services/console.py from the transport's own declaration, so
            # the dialog states it without knowing which protocol declared it.
            "shared_with_peer": (
                console.KEY_SHARED_WITH_PEER if key.shared_with_peer else None
            ),
        },
    )


@router.post("/keys/{node_transport_id}/rotate", response_class=HTMLResponse)
async def rotate_keys_from_the_console(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Re-mint this transport's material and push it — item 23, from the console.

    Its own route rather than the pre-redesign page's ``/transports/{id}/rotate-keys``
    below, which answers with ``panel/outcome.html`` and is asked for with htmx too — so
    unlike the add-node form the two cannot be told apart by a header. M9.6 deletes that
    page and may take the older name back.

    A half-done rotation is a BANNER, not a toast. Between the write and a successful
    push the database and the node disagree, and for a decoy that means the blocked
    value is still what the node is serving: that sentence has to survive the operator's
    next click rather than vanish after 2200ms.
    """
    key = await console.key_row(session, node_transport_id)
    try:
        outcome = await rotation.rotate_keys(session, node_transport_id=node_transport_id)
    except ParamsRefused as exc:
        # The transport refused what we just minted for it, and NONE of its sentences
        # may be printed here. Not because nothing in that mapping was ever typed — the
        # operator's own parameters are validated alongside the new material, so some of
        # it was — but because this answer is a confirmation dialog with NO BOXES: there
        # is nothing on screen for a message to belong to, and the mapping it complains
        # about was checked together with a private key minted three lines earlier, so a
        # complaint may be quoting material whichever field it names. An empty box set
        # is what says both. Latent rather than live today (no shipped validator quotes
        # its input), which is precisely why it is guarded rather than watched.
        return _mutation(
            request,
            # Never ``None``: ``_refused_parameters`` guarantees a refusal says
            # something, so a rotation that did nothing cannot also say nothing.
            banner=_refused_parameters(exc, boxes=set())["failure"],
            keeping=key.node,
            events="keys-changed",
        )
    except DomainError as exc:
        # Shown rather than raised: the operator is on the screen this is about, and
        # nothing was changed. These are this panel's own sentences — a transport the
        # image no longer ships, or one that declares nothing to rotate.
        return _mutation(
            request, banner=exc.message, keeping=key.node, events="keys-changed"
        )
    if not outcome.complete:
        return _mutation(
            request,
            banner=console.rotation_summary(key, outcome),
            keeping=key.node,
            events="keys-changed, nodes-changed",
        )
    return _mutation(
        request,
        toast=console.rotation_summary(key, outcome),
        keeping=key.node,
        # Both: the push moves this node's applied timestamp and can move its state, so
        # the Nodes table is as stale as this one. Copied from the hop mutations, which
        # is the established shape for a mutation touching two collections.
        events="keys-changed, nodes-changed",
    )


@router.get("/keys/{node_transport_id}/params", response_class=HTMLResponse)
async def replace_params_dialog(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """The replace-parameters form — item 24's, in the console."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/replace_params_dialog.html",
        await _params_form(session, node_transport_id),
    )


@router.post("/keys/{node_transport_id}/params", response_class=HTMLResponse)
async def replace_params_from_the_console(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Replace operator-supplied parameters — a blocked decoy being the case.

    Reads the form the way ``enable_transport`` does and for the same reason: this
    function must not know any protocol's field names. Two things it adds. The fields
    are FILTERED to the boxes this dialog actually rendered, so nothing else in a
    submission can reach the transport's model — and every one of those boxes is a value
    the operator typed, never a minted one, because ``replaceable_params`` subtracts key
    material before a box exists. And an empty box is dropped by ``parse_form``, which
    is what makes "leave it alone" expressible at all.
    """
    key = await console.key_row(session, node_transport_id)
    if not key.installed:
        # 422 with the dialog re-rendered, like every other refusal in this console —
        # the sentence comes from ``_params_form``, which is the one place that decides
        # what an uninstalled transport can be told.
        return await _refuse_params(request, session, node_transport_id, values={})
    node_transport = await rotation.get_node_transport(session, node_transport_id)
    boxes = transports.replaceable_params(key.transport, node_transport.params)
    names = {box.name for box in boxes}

    form = await request.form()
    typed = {
        name: str(value).strip()
        for name, value in form.multi_items()
        if name in names
    }
    supplied = transports.parse_form(key.transport, typed.items())
    if not supplied:
        return await _refuse_params(
            request, session, node_transport_id, values=typed, failure=NOTHING_TYPED
        )

    try:
        outcome = await rotation.replace_params(
            session, node_transport_id=node_transport_id, params=supplied
        )
    except ParamsRefused as exc:
        # Each complaint under the box it is about — the same treatment the hop dialog
        # gives one, and for the same reason: a sentence at the top of a form naming a
        # parameter sends the operator hunting for it mid-rotation.
        return await _refuse_params(
            request,
            session,
            node_transport_id,
            values=typed,
            **_refused_parameters(exc, names),
        )
    except DomainError as exc:
        # Everything else this refuses is about the request rather than about one value
        # — values that are already in place, most likely. Stated once, above the form.
        return await _refuse_params(
            request,
            session,
            node_transport_id,
            values=typed,
            failure=wording.for_the_page(exc.message),
        )

    if not outcome.complete:
        return _mutation(
            request,
            banner=console.replacement_summary(key, outcome),
            keeping=key.node,
            events="keys-changed, nodes-changed",
        )
    return _mutation(
        request,
        toast=console.replacement_summary(key, outcome),
        keeping=key.node,
        events="keys-changed, nodes-changed",
    )


async def _params_form(
    session: AsyncSession,
    node_transport_id: str,
    values: dict | None = None,
    errors: dict | None = None,
    *,
    failure: str | None = None,
) -> dict:
    """What the replace-parameters dialog needs, in one place so first paint and refusal
    agree.

    ``boxes`` comes from services/transports.py, which reads them out of the transport's
    own model — so this dialog names no field, no port and no address, and it cannot
    render a box for a value the control plane minted.
    """
    node_transport = await rotation.get_node_transport(session, node_transport_id)
    key = await console.key_row(session, node_transport_id)
    return {
        "key": key,
        # A node running a protocol this image no longer ships has nothing to build a
        # box from: the registry lookup would raise. The dialog says so instead — the
        # table offers no button for such a row, so this is only reachable by a typed
        # URL, and a raised domain error would answer that with a 400 the console never
        # swaps (static/app.js allows one status through, and it is 422). The operator
        # would get an open dialog with nothing in it and no message anywhere.
        "boxes": (
            transports.replaceable_params(
                node_transport.transport_name, node_transport.params
            )
            if key.installed
            else ()
        ),
        "values": values or {},
        "errors": errors or {},
        "failure": failure or (None if key.installed else console.KEY_NOT_IN_THIS_IMAGE),
    }


def _refused_parameters(exc: ParamsRefused, boxes: set[str]) -> dict:
    """One refusal, sorted into what may be shown and what may only be NAMED.

    The rule is an allow-list, and it is written that way after the first version got it
    the wrong way round. That one printed the transport's own sentence for anything that
    was not a declared piece of key material, which closed two instances and left the
    class open: Pydantic reports a model-level validator at an EMPTY location and a
    nested one at ``field.0``, neither of which is a name in that set, so both fell
    through to the branch that prints the message — the one place the message may quote
    the value it rejected, on a path where the mapping being validated holds this node's
    minted material.

    So: a complaint located at EXACTLY one of this form's boxes gets its message under
    that box, because a box holds a value the operator typed and nothing else. Every
    other shape — key material, a field this form does not render, a nested location, no
    location at all — is stated above the form by name, with the rule in place of the
    sentence. Erring this way costs a reason on a refusal about a field the operator
    cannot edit anyway; erring the other way prints key material.

    ``boxes`` may be empty, which is the key-rotation path: that answer is a banner and
    has no boxes at all, so there is nowhere for a message to land whatever it names.

    A falsy message counts as unprintable and is treated like a withheld one. It is
    reachable — a validator raising ``ValueError("")`` produces ``Value error, ``, which
    ``relay._plainly`` strips to nothing — and it landed under a box as an empty string,
    which the template's ``{% if %}`` then skipped: a 422 that re-rendered the dialog
    with no message anywhere, which reads as a form that simply will not submit.

    For the same reason this function, and not its callers, guarantees that a refusal
    says SOMETHING: a ``ParamsRefused`` carrying no field at all is still stated, as a
    complaint about the parameters as a whole.
    """
    errors = {}
    withheld = []
    for field, message in exc.fields.items():
        if field in boxes and message:
            errors[field] = wording.for_the_page(message)
        else:
            withheld.append(field)
    if not errors and not withheld:
        withheld.append("")
    return {
        "errors": errors,
        "failure": console.withheld_note(withheld) if withheld else None,
    }


async def _refuse_params(
    request: Request,
    session: AsyncSession,
    node_transport_id: str,
    *,
    values: dict,
    errors: dict | None = None,
    failure: str | None = None,
) -> Response:
    """The replace-parameters dialog again, at 422, with what was typed still in it."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/replace_params_dialog.html",
        await _params_form(
            session, node_transport_id, values=values, errors=errors, failure=failure
        ),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
            # Which transports may carry a hop, and why both of its conditions are
            # needed, is ``transports.hop_transports``. It moved there in M9.2 because
            # the console's own establish-hop dialog asks the same question, and two
            # copies of "may this protocol cross the border" is the drift that would
            # offer a blocked one on one screen and not the other.
            "hop_transports": transports.hop_transports(),
            "hop_params": {
                name: transports.operator_params(name)
                for name in transports.hop_transports()
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
    name: str = Form(""),
    address: str = Form(""),
    location_label: str = Form(""),
    ssh_host: str = Form(""),
    ssh_user: str = Form(""),
    ssh_port: str = Form(""),
    ssh_private_key: str = Form(""),
    session: AsyncSession = Depends(session_dependency),
):
    """Register a node — from the console's dialog, or from the old page's form.

    ONE route with two answers, because two panels are live at once (see the module
    docstring). The console asks with htmx and gets the console's answer: the dialog
    closes, a toast names the node, and the table refreshes itself. The pre-redesign
    form at /panel/fleet is a plain browser POST and still gets its 303 back to the
    page it was submitted from, so a reload does not re-post. M9.6 deletes that page
    and the redirect branch with it.

    Every field arrives as text, including the port, and every one of them is checked
    by ``schemas.NodeCreate`` — the API's own model, so the two surfaces cannot drift
    about what a node record may contain. Before M9 this route trusted the form: an
    over-long name reached the column and came back as an opaque 500, which is exactly
    the defect M8 fixed one screen over for a nickname.
    """
    typed = {
        "name": name.strip(),
        "address": address.strip(),
        "location_label": location_label.strip(),
        "ssh_host": ssh_host.strip(),
        "ssh_user": ssh_user.strip(),
        "ssh_port": ssh_port.strip(),
    }
    try:
        payload = schemas.NodeCreate(
            name=typed["name"],
            address=typed["address"],
            location_label=typed["location_label"],
            # An empty box means "the usual one", and the usual one is declared in
            # services/nodes.py. Empty string means "not supplied" for the key too —
            # storing "" would encrypt an empty key and make the failure look like a
            # wrong key rather than a missing one.
            ssh_host=typed["ssh_host"] or None,
            ssh_user=typed["ssh_user"] or nodes.DEFAULT_SSH_USER,
            ssh_port=typed["ssh_port"] or nodes.DEFAULT_SSH_PORT,
            ssh_private_key=ssh_private_key or None,
        )
    except ValidationError as exc:
        return _refuse_node(
            request,
            values=typed,
            errors={
                str(error["loc"][0]): _refused_field(error) for error in exc.errors()
            },
            key_dropped=bool(ssh_private_key),
        )

    try:
        node = await nodes.create_node(session, **payload.model_dump())
    except DomainError as exc:
        # ``create_node`` refuses exactly one thing — a name already in the fleet — so
        # the message goes under the name field rather than being guessed at. Through
        # ``wording.for_the_page`` like every other sentence a service composes.
        return _refuse_node(
            request,
            values=typed,
            errors={"name": wording.for_the_page(exc.message)},
            key_dropped=bool(ssh_private_key),
        )

    if not _is_htmx(request):
        return RedirectResponse(url="/panel/fleet", status_code=status.HTTP_303_SEE_OTHER)

    return _mutation(
        request,
        toast=f"{node.name} added — a draft until you apply it",
        keeping=node.name,
        events="nodes-changed",
    )


def _refuse_node(
    request: Request, *, values: dict, errors: dict, key_dropped: bool = False
) -> Response:
    """A refused node form, in whichever panel asked.

    The console gets its dialog back at 422 with the message under the field it is
    about — M8.6, and static/app.js allows exactly that one status to swap. The
    pre-redesign form has nowhere to render a field error, so it keeps the behaviour it
    has always had: a ``DomainError``, which the one exception handler turns into the
    envelope every other refusal on that page already produces.
    """
    if not _is_htmx(request):
        raise DomainError(" ".join(errors.values()))
    return TEMPLATES.TemplateResponse(
        request,
        "panel/add_node_dialog.html",
        _node_form(values=values, errors=errors, key_dropped=key_dropped),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def _refused_field(error) -> str:
    """One validation error as the sentence that goes under the field it is about.

    Written here rather than passed through from Pydantic: its own messages are about
    types ("String should have at most 64 characters"), and the panel speaks to an
    operator. The limits themselves are never repeated — they are read back out of the
    error, so the schema stays the only place they are declared.

    Nothing in here names a port, a country or an address, including in the sentence
    about a port being out of range: what the operator needs to know is that the value
    is not one a node can listen on, and the range is the schema's business.
    """
    kind = error["type"]
    if kind in {"missing", "string_too_short"}:
        return "required — a node cannot be registered without it"
    if kind == "string_too_long":
        return f"{(error.get('ctx') or {}).get('max_length')} characters or fewer"
    if kind in {"int_parsing", "int_type", "greater_than_equal", "less_than_equal"}:
        return "a whole number, and one a node can listen on"
    return "not a value this field can take"


@router.post("/nodes/{node_id}/probe", response_class=HTMLResponse)
async def probe_node_from_the_console(
    node_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Ask a node what it is actually running, and say so on the console.

    A healthy answer is a toast: it is good news and it does not need to survive the
    next click. Anything else is a BANNER, which stays until the next successful
    action — an unreachable node, or one running a configuration older than the file
    on it, is a fault the operator has to still be able to read while they act on it.

    Its own route rather than the ``/health`` one below because the two panels want
    different answers to the same question: that one renders the old page's fragment
    into ``#outcome``, this one is a console mutation. M9.6 deletes the other.
    """
    node = await nodes.get_node(session, node_id)
    result = await health.check_node(session, node_id=node_id)
    summary = console.health_summary(node.name, result)
    return _mutation(
        request,
        toast=summary if result.healthy else None,
        banner=None if result.healthy else summary,
        keeping=node.name,
        # A probe changes nothing, but it is the moment the operator most wants the
        # row's own reading of the node refreshed beside the answer.
        events="nodes-changed",
    )


@router.post("/nodes/{node_id}/push", response_class=HTMLResponse)
async def push_node_from_the_console(
    node_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Push this node's configuration to its host — the console's "apply".

    ``push`` and not ``apply`` in the URL only because ``/apply`` still belongs to the
    pre-redesign page below, which answers it with a different fragment; the word is
    the codebase's own for the operation either way. M9.6 takes the shorter name back.

    A failure is a banner rather than a toast, and that is the point of this button on
    the stand: a failed apply marks the node degraded, and the operator has to be able
    to read why while they fix it instead of watching it disappear after 2200ms.
    """
    node = await nodes.get_node(session, node_id)
    try:
        applied = await apply.apply_node(session, node_id=node_id)
    except DomainError as exc:
        # Shown, not raised: apply_node has already recorded the failure and marked the
        # node degraded, and what the operator needs is the reason on the screen they
        # are on rather than an error envelope.
        return _mutation(
            request,
            banner=exc.message,
            keeping=node.name,
            events="nodes-changed",
        )
    return _mutation(
        request,
        toast=(
            f"config applied to {node.name} — {', '.join(sorted(applied))}"
            if applied
            else f"{node.name} has nothing enabled to apply"
        ),
        keeping=node.name,
        events="nodes-changed",
    )


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


# --- hops between nodes (item 16), from the PRE-REDESIGN page -----------------
#
# The console's own hop routes are in the Hops section further up. These two stay
# because /panel/fleet still carries a hop form and asks for them with htmx, so unlike
# the add-node form they cannot be told apart from the console's by a header. M9.6
# deletes the page and takes the two shorter names back.

@router.post("/hops", response_class=HTMLResponse)
async def create_hop(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Establish both ends of an entry→leaf tunnel from one form — the OLD page's.

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
