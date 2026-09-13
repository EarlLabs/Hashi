"""The admin panel — the screen the owner lives in.

WHAT: login, the console (Overview, Users, Nodes, Hops, Transports, Keys & configs,
      Audit log, Settings), and every action on each.
WHY:  criteria 2 and 3 are both phrased "from the panel", so this is not a
      convenience layer over the API — it is where those criteria are met.
HOW:  full pages for navigations, HTML FRAGMENTS for HTMX actions. The control
      rulebook names the trap: returning a full document from a partial route nests
      ``<html>`` inside the page and the bug looks like CSS.

      Autoescaping stays on everywhere. Node names, friend nicknames and error
      strings are attacker-influenced text — a friend's nickname is typed by the
      operator, but a node's ``state_detail`` can contain text from a remote host —
      and a ``|safe`` on any of them is an injection.

ONE panel, since M9.6. The CONSOLE is the redesign in ``design/`` — a persistent
sidebar over a swappable ``#main``, one screen per route, every creation flow in a
dialog. Overview, Users, Nodes, Hops, Transports, Keys & configs, Audit log and
Settings are its eight screens — the last two read-only, with no action on either —
and every action the pre-redesign fleet page carried has a home on one of them: enabling,
withdrawing and offering a transport and moving a node between states on the Nodes
screen, both rotations on Keys & configs, both halves of a hop on Hops.

``pages/index.html`` and ``pages/node.html`` are gone, and with them the two fragments
only they rendered into, ``panel/outcome.html`` and ``panel/health.html``. Every route
that had taken a longer name to keep out of theirs has the short one back:
``/nodes/{id}/apply``, ``POST /panel/hops`` and ``/hops/{id}/dissolve``,
``/nodes/{id}/state``, and ``/transports/{id}/withdraw`` + ``/offer`` — two routes
rather than the one toggle that name used to be, because one of them is destructive
and confirms first and the other is not and does not.

WHAT DID NOT GO WITH THEM. The two routes that answered a plain browser form with a
303 — ``POST /panel/nodes`` and ``POST /panel/nodes/{id}/transports`` — no longer
redirect: the console is the only caller and it asks with htmx. What is kept is the
REFUSAL split in ``_refuse_node`` and ``_refuse_the_form``: a caller that is not htmx
has nowhere to render a field error, so it still gets the ``DomainError`` envelope
rather than a dialog fragment it could not use.
"""

import dataclasses
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
from control.app.errors import DomainError, HopEndRefused, NothingToApply, ParamsRefused
from control.app.models import NodeState, TransportPurpose
from control.app.panel import wording
from control.app.services import (
    addresses,
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
# Every entry is a boosted navigation that swaps ``#main``. The ``boost`` and ``note``
# keys that let one entry be an ordinary browser navigation to a not-yet-redesigned
# page went with the Fleet entry in M9.6: there is no such page left, and a flag no
# entry ever sets is a flag the next screen has to guess the meaning of.
#
# There is no Traffic entry, and its slot is given to nothing. That is decision 6's
# sharper half: a screen that exists to say "we do not measure this" is an invitation
# to add the measurement later.
NAV = (
    {"key": "overview", "label": "Overview", "url": "/panel/"},
    {"key": "friends", "label": "Users", "url": "/panel/friends"},
    {"key": "nodes", "label": "Nodes", "url": "/panel/nodes"},
    {"key": "hops", "label": "Hops", "url": "/panel/hops"},
    {"key": "transports", "label": "Transports", "url": "/panel/transports"},
    {"key": "keys", "label": "Keys & configs", "url": "/panel/keys"},
    # M10.4's, in the design's own order: before Settings, so the two screens that are
    # about this control plane rather than about the fleet sit together at the bottom.
    {"key": "audit", "label": "Audit log", "url": "/panel/audit"},
    {"key": "settings", "label": "Settings", "url": "/panel/settings"},
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
async def add_friend_dialog(
    request: Request, session: AsyncSession = Depends(session_dependency)
) -> Response:
    """The empty add-user dialog — and, since M17.2, whether there is room for one.

    IT TAKES A SESSION NOW, which the "it asks for one field" version deliberately did
    not. Creating a user grants them an address on every serving transport that hands out
    one, so a full pool anywhere in the fleet refuses every submission of this form. The
    dialog asks the same question the service asks (``console.full_pools``, which is
    ``addresses.shortfalls(extra=1)``) and draws no submit button when the answer is not
    empty: a control whose only outcome is a refusal is worse than the sentence that
    explains why there is no control.
    """
    return TEMPLATES.TemplateResponse(
        request, "panel/add_friend_dialog.html", await _add_friend_form(session)
    )


async def _add_friend_form(
    session: AsyncSession, *, nickname: str = "", error: str | None = None
) -> dict:
    """What the add-user dialog needs, in one place so first paint and refusal agree.

    The same shape ``_enable_form`` and ``_params_form`` have, and for the same reason:
    this dialog is rendered by two routes, and a context built twice is two dialogs that
    drift. It became worth having when the dialog gained a second state — M17.2's, where
    a full pool means there is no form at all.

    Every sentence in it is composed in ``services/console.py``; the only thing decided
    here is that a nickname refused by name gets its message under the field, while "the
    fleet has no room" is not a complaint about anything the operator typed.
    """
    full = await console.full_pools(session)
    return {
        "nickname": nickname,
        "error": error,
        "full_pools": full,
        # Composed from the length of the list it introduces, so the sentence cannot say
        # "one of those pools" over two of them — M17.2's acceptance.
        "no_room": console.no_room_for_another_user(len(full)),
        "what_to_do": console.NO_ROOM_WHAT_TO_DO,
    }


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


# --- Nodes: what one offers, and what state it is in (M9.5) -------------------
#
# The three actions the pre-redesign node page was the only home for — enable a
# transport, withdraw one, move a node between states — reached from the Nodes screen's
# own row actions. Until they were here, M9's acceptance walk ("every step from the new
# screens, with no URL typed by hand") could not be completed, and M9.6 could not delete
# the page that still carries them.
#
# WHERE THEY LIVE, AND WHY THERE. A node's transports are a LIST inside a row, and a row
# has one actions cell: a withdraw button beside every chip would put controls in a data
# cell, which nothing else in this console does (UI-PATTERNS §3 — actions are the
# actions column). So the row's ``transports`` button opens a dialog about exactly one
# subject, what this node offers, where each transport gets its own line and its own
# button and the form that adds another sits under them. Moving a node between states is
# its own dialog because it is about the node rather than about what it runs.
#
# M15.2 added a FOURTH action to the same dialog — removing the row altogether, which is
# the only thing that frees the port and the config name it holds — and it lives beside
# withdraw for the same reason: it is about one node-transport, and the list of them is
# already here. Two buttons on a row rather than one toggle with a mode, because
# withdrawing and removing differ in what survives them and each states its own reach.
#
# The dialogs are on ``/nodes/{node_id}/...`` and the two mutations on
# ``/transports/{node_transport_id}/...``, because they are about different subjects: a
# dialog is about a NODE and asks what it offers, while withdrawing or offering is about
# one NODE-TRANSPORT row. Both of those mutations wore a ``/nodes/`` prefix until M9.6,
# only to stay clear of the pre-redesign page's ``POST /transports/{id}/state``, which
# drove the same job with htmx and so could not be told apart from them by a header.

# What a required box that was left empty is answered with. Field-level, at 422, like
# every other refusal in this console: a form with a box per parameter the transport
# declares cannot be corrected from one sentence at the top — and how many that is, is
# the transport's business and not a number to write down here. Shared with the
# establish-hop route below, which asks the same question of the same kind of box: a
# parameter the transport declares no default for is refused when it is left empty,
# whichever form it was left empty on.
NO_DEFAULT = "required — this transport declares no default to fall back on"

# What a form submitted with no protocol chosen is answered with, under the one control
# that was not answered. Its own sentence rather than the one above because nothing was
# left empty here that a transport declares anything about: this is the choice the rest
# of the form is built from.
NO_TRANSPORT_CHOSEN = "required — choose which protocol this node should offer"

# What the pool box is answered with when what arrived is not a count — M17. The panel's
# own refusal rather than the service's, because the service's parameter is a number and
# a form gives it text: there is nothing to hand over. It echoes nothing back and names no
# figure, since the box's own placeholder already says what it will take.
POOL_NOT_A_NUMBER = "a whole number — how many people this transport hands an address to"

# The longest a typed box may be, and what it is answered with over that — M17.2's
# acceptance. THE CAUSE, where ``relay.TOO_LONG_TO_REPEAT`` is the symptom: a transport's
# validator quotes the value it rejected, so a thousand characters pasted into an address
# box came back as a thousand characters under it and pushed the form off the screen. The
# echo is bounded in the service for every path at once; this is the box saying no first,
# in a sentence of its own, so what the operator reads is a limit rather than a
# validator's complaint about a value they can see is wrong.
#
# NO ``maxlength`` IN THE MARKUP, which this console has already learned once
# (``panel/add_friend_dialog.html``): the attribute silently clips a paste and the record
# is then written under something other than what the operator typed. Refused, not
# trimmed.
#
# 255 is what ``api/schemas.py`` bounds a node's own address and host at, and no parameter
# any shipped transport declares takes more — the longest is a hostname. It echoes nothing
# back: the value is in the box beside the sentence, and repeating it is the defect.
VALUE_MAX_LENGTH = 255
VALUE_TOO_LONG = (
    f"{VALUE_MAX_LENGTH} characters or fewer — nothing was enabled, and the value is not "
    "repeated here"
)

# What a submission naming something this form cannot read is answered with. Above the
# form and not under a box, because the name it is about has no box — that is the whole
# complaint.
#
# REFUSED RATHER THAN DROPPED, and that is the same rule as the one above it: a value an
# operator supplied is used or refused, never quietly ignored. Before this route filtered
# anything, an unknown name reached the transport's model, which declares
# ``extra="forbid"`` and refused it — so a misspelled parameter came back as a refusal
# rather than as a node silently enabled with the transport's default in its place. That
# is worth keeping, and the sentence covers a minted name in the same breath: a
# submission cannot name one either, and being told why beats being told nothing.
#
# No rendered box can produce this. The console's own boxes are named for their group and
# every one of them is a field its transport declares, and another group's boxes are
# ignored rather than refused — a hidden input is the dialog's own doing, not the
# operator's.
NOT_ITS_PARAMETER = (
    "nothing was enabled — this form cannot read: {names}. A parameter this transport "
    "does not declare, or one the control plane mints for you, is never taken from a "
    "submission."
)


@router.get("/transports/{node_transport_id}/withdraw", response_class=HTMLResponse)
async def withdraw_transport_dialog(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """The confirmation. UI-PATTERNS §3: a destructive action confirms in a dialog."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/withdraw_transport_dialog.html",
        {"offer": await console.offer_row(session, node_transport_id)},
    )


@router.post("/transports/{node_transport_id}/withdraw", response_class=HTMLResponse)
async def withdraw_transport(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Take one transport out of every user's subscription — criterion 3's other half.

    On this path rather than the pre-redesign page's ``POST /transports/{id}/state``
    only until M9.6 deleted that page; the direction stays in the URL rather than in a
    field for the reason ``_set_offered`` gives.
    """
    return await _set_offered(request, session, node_transport_id, offered=False)


@router.post("/transports/{node_transport_id}/offer", response_class=HTMLResponse)
async def offer_transport(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Put a withdrawn transport back into every user's link. No confirmation: it takes
    nothing away, and what it gives is stated on the row the button sits on."""
    return await _set_offered(request, session, node_transport_id, offered=True)


async def _set_offered(
    request: Request,
    session: AsyncSession,
    node_transport_id: str,
    *,
    offered: bool,
) -> Response:
    """Both directions, one implementation, and the direction in the URL rather than in
    a field.

    The service reads an explicit wanted value rather than toggling, so that a
    double-submitted form cannot put the fleet into the state the operator was trying to
    leave (``nodes.set_transport_enabled``). Two routes keep that property while the
    console gains what a toggle cannot have: one of them is destructive and confirms
    first, the other is not and does not.

    A toast rather than a banner, the same call the tear-down makes: this is the
    operator's own deliberate act and it succeeded. What it LEAVES BEHIND — a node still
    configured to serve what nobody is being offered — is in the sentence, and the
    confirmation said it before they pressed.
    """
    offer = await console.offer_row(session, node_transport_id)
    try:
        await nodes.set_transport_enabled(
            session, node_transport_id=node_transport_id, enabled=offered
        )
    except DomainError as exc:
        # Shown rather than raised: nothing was changed, and the operator is on the
        # screen this is about. Reachable only by a typed URL — the dialog offers no
        # button on a hop end, which is the one thing this refuses.
        #
        # IN THE CONSOLE'S OWN WORDS for that one thing, and not the service's. The
        # service sentence ends by naming a raw API call — with its path placeholder
        # unsubstituted — which is the opposite of the milestone whose acceptance line is
        # "no URL typed by hand", and it disagrees with what the dialog behind this
        # button says about the same row. It is not this route's to reword: the API is
        # its other caller and that envelope is what a script reads. So the console picks
        # the sentence the dialog already uses, from the same constant, and the two
        # cannot drift. Anything else this ever refuses keeps the service's words.
        return _mutation(
            request,
            banner=(
                console.OFFER_HOP_END
                if not offer.for_friends
                else wording.for_the_page(exc.message)
            ),
            keeping=offer.node,
            events="nodes-changed",
        )
    if offered:
        # Offering again runs the same grant fan-out ``enable_transport`` does, so the
        # material a user holds moves and the Keys screen's "users on it" count with it.
        events = "nodes-changed, keys-changed, friends-changed"
        toast = console.offer_summary(offer.node, offer.transport)
    else:
        # Withdrawing fires two as well. What it does NOT take away is a MINTED
        # CREDENTIAL — that stays minted, which is why the Keys screen is left alone —
        # but the Users table's own columns are derived from ``serving_transports``,
        # which counts only ENABLED rows, so both of them move the moment this commits.
        events = "nodes-changed, friends-changed"
        # Asked AFTER the flag moved, because the sentence is about what is true now:
        # withdrawing the node's last enabled row leaves the apply it would otherwise
        # send the operator to with nothing to push — M18.1's review.
        toast = console.withdrawal_summary(
            offer.node,
            offer.transport,
            nothing_left_enabled=await console.nothing_left_enabled_on(
                session, offer.node_id
            ),
        )
    return _mutation(
        request,
        toast=toast,
        keeping=offer.node,
        events=events,
    )


@router.get("/transports/{node_transport_id}/remove", response_class=HTMLResponse)
async def remove_transport_dialog(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """The confirmation for the one destructive action on this row — M15.2.

    Its own dialog rather than a second button on the withdraw one: UI-PATTERNS §3 asks
    a destructive action to state its blast radius, and these two have different ones.
    The subject is ``console.offer_row``, so the title names the row the way every other
    screen does — qualified by the config name where a node runs two instances of one
    transport, which is the only thing telling them apart.
    """
    return TEMPLATES.TemplateResponse(
        request,
        "panel/remove_transport_dialog.html",
        {"offer": await console.offer_row(session, node_transport_id)},
    )


@router.post("/transports/{node_transport_id}/remove", response_class=HTMLResponse)
async def remove_transport(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Delete one transport from a node, with the material minted under it — M15.2.

    The row is read BEFORE the service runs, which is not the ordering the neighbouring
    withdraw route merely happens to use: after this commits there is no row to project,
    so the toast's subject has to have been taken while it existed.

    A toast rather than a banner, like every other deliberate act that succeeded. What it
    leaves behind — a host still serving what this panel no longer knows about — is in
    the sentence, and the confirmation said it before they pressed.
    """
    offer = await console.offer_row(session, node_transport_id)
    try:
        await nodes.remove_transport(session, node_transport_id=node_transport_id)
    except DomainError as exc:
        # Nothing was changed and the operator is on the screen this is about, so it is
        # shown rather than raised. The one thing this refuses is a hop end, and the
        # console answers that in its own words: the service's sentence ends by naming a
        # raw API path, which is the opposite of what this panel promises. Anything else
        # it ever refuses keeps the service's words. Same SPLIT as ``_set_offered``, and
        # deliberately not the same plumbing: the service's sentence is handed over raw,
        # because ``_mutation`` translates it already and does so with ``keeping``, where
        # pre-translating it — as the neighbour does — runs the rule once over a sentence
        # with the node's name unprotected. One translation, not two. Do not align this
        # backwards.
        return _mutation(
            request,
            banner=console.REMOVE_HOP_END if not offer.for_friends else exc.message,
            keeping=offer.node,
            events="nodes-changed",
        )
    return _mutation(
        request,
        # Asked after the delete, on the node the deleted row was on — which is why
        # ``offer`` carries a node id and not only the operator's name for it.
        toast=console.removal_summary(
            offer.node,
            offer.transport,
            nothing_left_enabled=await console.nothing_left_enabled_on(
                session, offer.node_id
            ),
        ),
        keeping=offer.node,
        # Three, because a row leaving takes three collections with it: the node's chips,
        # the Keys screen's row for it, and the Users table's counts, which are derived
        # from ``serving_transports``.
        events="nodes-changed, keys-changed, friends-changed",
    )


@router.get("/nodes/{node_id}/transports", response_class=HTMLResponse)
async def node_transports_dialog(
    node_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """What this node offers, and the form that adds one more.

    Two things in one dialog on purpose, and it is the one dialog in this console that
    holds both a list and a creation form: they are a single subject — which protocols
    this node hands to a user — and the operator reading the list is almost always about
    to act on it. Splitting them would put the same node's answer behind two buttons in
    one row's actions cell.

    ``GET`` and ``POST`` of this path are two different jobs and that is not a collision:
    the POST is the enable route further down, which this dialog's form submits to.
    """
    return TEMPLATES.TemplateResponse(
        request, "panel/node_transports_dialog.html", await _enable_form(session, node_id)
    )


async def _enable_form(
    session: AsyncSession,
    node_id: str,
    values: dict | None = None,
    errors: dict | None = None,
    *,
    failure: str | None = None,
) -> dict:
    """What the transports dialog needs, in one place so first paint and refusal agree.

    ``tuning`` is per transport and comes from ``services/transports.py``, which reads
    every box out of the transport's own model — so this dialog names no protocol, no
    field and no port, exactly as the establish-hop dialog does not. The list of
    protocols it may offer is the image's own answer (``offerable_transports``) and
    nothing is subtracted from it.

    IT USED TO SUBTRACT what the node already ran, on the reasoning that the form should
    not present an action whose only outcome is a refusal. That reasoning went with the
    rule it was built on: since M15 a node may carry two instances of one transport —
    the runbook asks for exactly that, a friend-facing AmneziaWG and a hop over
    AmneziaWG on one box — and the subtraction counted hop ends too, so hop-then-friends
    was impossible from the only surface an operator has while friends-then-hop worked.
    A filter cannot answer "is a second one legal here" without repeating the port rule,
    which is ``services.placement``'s single answer; so it does not try, and a genuine
    collision arrives as a refusal on this dialog with the port named.

    NO BOX CAN EXIST FOR KEY MATERIAL and that is structural: ``operator_tuning`` is
    built from ``operator_params``, which subtracts everything the transport declares as
    material and every public counterpart of one. Enabling is the moment material is
    MINTED, which is exactly why the form it is minted from may not ask for any.
    """
    node = await nodes.get_node(session, node_id)
    offers = await console.offers_on(session, node_id)
    installed = list(transports.offerable_transports())
    return {
        "node": node,
        "offers": offers,
        "transports": installed,
        "tuning": {
            name: _in_the_pages_words(transports.operator_tuning(name))
            for name in installed
        },
        # ONE MORE BOX, and only for the transports that declare each person needs an
        # address of their own — M17. Keyed by transport so the template renders it in
        # that group and nowhere else, and composed in ``services/console.py`` so the
        # number in its placeholder is not a literal in markup. It is deliberately NOT in
        # ``tuning`` above: that list is the transport's own required parameters, and the
        # pool size is a column on the node-transport record rather than anything the
        # transport declares or validates.
        "pools": await console.pool_boxes(session, installed),
        "values": values or {},
        "errors": errors or {},
        # A refusal about the request rather than about one box — a transport this image
        # cannot deliver, a port this node already binds, a node that is gone. Shown
        # inside the dialog because that is where the operator is.
        "failure": failure,
        # …and the pointer to a refusal that IS about a box, because this dialog is
        # taller than the window and comes back from a 422 at the top of itself, with the
        # pool box last — M17.2's acceptance. Composed here rather than in the template so
        # the count agrees with the list and the group prefix is stripped once.
        "refused": console.refused_under_boxes(sorted(errors)) if errors else None,
    }


async def _refuse_enable(
    request: Request,
    session: AsyncSession,
    node_id: str,
    *,
    values: dict,
    errors: dict | None = None,
    failure: str | None = None,
) -> Response:
    """The transports dialog again, at 422, with what was typed still in it.

    Every caller of this has already established that htmx asked: a caller that did not
    has nowhere to render a field error and gets the error envelope instead.
    """
    return TEMPLATES.TemplateResponse(
        request,
        "panel/node_transports_dialog.html",
        await _enable_form(session, node_id, values=values, errors=errors, failure=failure),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def _on_its_boxes(exc: ParamsRefused, transport_name: str, boxes: set[str]) -> dict:
    """One transport's per-field refusal, on the boxes this dialog rendered for it.

    Every decision is ``_refused_parameters``' — which sentence may be printed at all
    (an allow-list: only a complaint located at exactly one of this form's boxes, since
    a box holds a value the operator typed), and what is said in place of one that may
    not be. What this adds is the group prefix and nothing else: the dialog renders a set
    of boxes per transport and names each one for its own group, so an error keyed by a
    bare field name would land nowhere. No message is read here.
    """
    sorted_out = _refused_parameters(exc, boxes)
    return {
        "errors": {
            f"{transport_name}-{field}": message
            for field, message in sorted_out["errors"].items()
        },
        "failure": sorted_out["failure"],
    }


@router.get("/nodes/{node_id}/resolver", response_class=HTMLResponse)
async def node_resolver_dialog(
    node_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Where this node's lookups go through its hop — the one edit a node record admits."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/node_resolver_dialog.html",
        {"node": await nodes.get_node(session, node_id), "values": {}, "errors": {}},
    )


@router.post("/nodes/{node_id}/resolver", response_class=HTMLResponse)
async def set_node_resolver(
    node_id: str,
    request: Request,
    resolver: str = Form(""),
    session: AsyncSession = Depends(session_dependency),
):
    """Set a node's resolver from the console — M16, after the node was registered.

    It exists because a node that dials a hop does not render without one and the upgrade
    that added the field gave every existing node none: without it, the field's own entry
    node could not be applied again, nor reached by a revocation. Everything else on a
    node record stays fixed, and a new host is still a new node.

    Both refusals land under the one box at 422 — an empty box, and a value ``edge`` would
    never render — with what was typed kept, because an address is not a secret.
    """
    node = await nodes.get_node(session, node_id)
    typed = {"resolver": resolver.strip()}
    if not typed["resolver"]:
        return _refuse_resolver(
            request, node, values=typed, errors={"resolver": console.RESOLVER_REQUIRED}
        )
    try:
        node = await nodes.set_resolver(
            session, node_id=node_id, resolver=typed["resolver"]
        )
    except DomainError as exc:
        return _refuse_resolver(
            request,
            node,
            values=typed,
            errors={"resolver": wording.for_the_page(exc.message)},
        )
    return _mutation(
        request,
        toast=console.resolver_set(node.name),
        keeping=node.name,
        events="nodes-changed",
    )


def _refuse_resolver(
    request: Request, node, *, values: dict, errors: dict
) -> Response:
    """The resolver dialog again, at 422, with the message under the box it is about."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/node_resolver_dialog.html",
        {"node": node, "values": values, "errors": errors},
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


@router.get("/nodes/{node_id}/state", response_class=HTMLResponse)
async def node_state_dialog(
    node_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Where this node may go from where it is, and what each of those does to a link."""
    return TEMPLATES.TemplateResponse(
        request,
        "panel/node_state_dialog.html",
        await _state_form(session, await nodes.get_node(session, node_id)),
    )


async def _state_form(
    session: AsyncSession, node, values: dict | None = None, errors: dict | None = None
) -> dict:
    """What the state dialog needs, in one place so first paint and refusal agree.

    ``choices`` is ``NodeState.allowed_from`` projected through ``services/console.py``,
    never restated here: a dialog offering a transition the service refuses is a button
    whose only outcome is a 409. ``retired`` is absent from a retired node's list for the
    reason the state machine gives — bringing back a record whose host is gone puts an
    address that may now belong to a stranger into every user's subscription.

    ASYNC SINCE M17.2, because one more transition can now be refused for a reason the
    state machine knows nothing about: a node that starts serving gives every active user
    an address on each transport it offers, and a pool too small to hold them refuses the
    move. ``state_choices`` measures that against the node's own enabled rows, which is a
    query, and withholds the serving option with the pool named instead of offering a
    control whose outcome is already known.
    """
    return {
        "node": node,
        "choices": await console.state_choices(session, node),
        "values": values or {},
        "errors": errors or {},
    }


@router.post("/nodes/{node_id}/state", response_class=HTMLResponse)
async def set_node_state(
    node_id: str,
    request: Request,
    state: str = Form(""),
    detail: str = Form(""),
    session: AsyncSession = Depends(session_dependency),
):
    """Move a node between states from the console — charter criterion 2.

    ``GET`` and ``POST`` of this path are two different jobs and that is not a collision:
    the GET above renders the dialog, this answers what it was submitted with. The name
    was ``/set-state`` until M9.6, only because the pre-redesign page drove the short one
    with htmx and so could not be told apart from the console by a header.

    Both refusals land on the ``state`` control at 422 rather than becoming a banner, and
    both are about that control: an unknown word, or a transition this node may not make.
    The second is only reachable from a dialog opened before somebody else moved the node
    — which is exactly when the operator needs to see the current answer, and re-rendering
    the dialog is what gives them one.
    """
    typed = {"state": state, "detail": detail}
    if not state:
        return await _refuse_state(
            request, session, node_id, values=typed, errors={"state": NO_STATE_CHOSEN}
        )
    try:
        wanted = NodeState(state)
    except ValueError:
        # An unknown word, before the service ever sees it. The message names no value:
        # this one came from a form, and the states themselves are on screen already.
        return await _refuse_state(
            request, session, node_id, values=typed, errors={"state": NO_SUCH_STATE}
        )

    try:
        moved = await nodes.set_node_state(
            session, node_id=node_id, state=wanted, detail=detail or None
        )
    except DomainError as exc:
        return await _refuse_state(
            request,
            session,
            node_id,
            values=typed,
            errors={"state": wording.for_the_page(exc.message)},
        )

    return _mutation(
        request,
        toast=f"{moved.name} is now {moved.state}",
        keeping=moved.name,
        # Both, and the second is not decoration: a node becoming serving hands every
        # active user a credential on it, which is what criterion 2 rests on and what
        # the Users table's own column counts.
        events="nodes-changed, friends-changed",
    )


# The two answers to a state that cannot be acted on, both landing on the one control
# they are about. Neither echoes what arrived: it came from a form, and the dialog behind
# this answer already lists the states this node may actually move to.
NO_STATE_CHOSEN = "required — choose the state to move this node into"
NO_SUCH_STATE = "that is not a state this node can be moved into"


async def _refuse_state(
    request: Request, session: AsyncSession, node_id: str, *, values: dict, errors: dict
) -> Response:
    """The state dialog again, at 422, with the message under the control it is about.

    IT RE-READS THE NODE, like ``_refuse_enable`` and ``_refuse_params`` do, and that is
    required rather than symmetrical — M17. Since this milestone, moving a node to
    serving grants every active friend inside the same transaction, and a pool with no
    room refuses by ROLLING BACK (``friends.grant_everywhere``). A rollback expires every
    object in the session's identity map whatever ``expire_on_commit`` says, so a ``Node``
    this route had fetched before the call is a husk afterwards: reading ``node.state``
    to compose this dialog would emit a SELECT from a plain frame on an async session —
    ``MissingGreenlet``, which is not a ``DomainError``, so it escapes as a 500 and the
    console swaps nothing at all. The operator would watch the spinner stop and never see
    the refusal. Re-reading inside the answer is what makes every refusal on this route
    renderable, whatever the service did to the session on its way out.
    """
    return TEMPLATES.TemplateResponse(
        request,
        "panel/node_state_dialog.html",
        await _state_form(
            session,
            await nodes.get_node(session, node_id),
            values=values,
            errors=errors,
        ),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


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


def _in_the_pages_words(boxes: tuple) -> tuple:
    """Every box's hint in the words the operator reads, not the code's.

    A box's hint is the FIELD'S OWN ``description``, written in the transport's package
    and rendered straight onto a console dialog — which makes it a server-composed
    sentence a console template renders, and decision 9 says every one of those comes
    through ``wording.for_the_page``. It was the one that did not, and it went unnoticed
    while no shipped transport's description used the word: the moment one did (M17
    widened ``peer_tunnel_address``'s description to say what it means on a transport
    offered to friends), three dialogs started saying ``friends`` to an operator whose
    every other word is ``user``.

    Applied here rather than in ``services/transports.py`` for the reason ``wording``'s
    own header gives: a service writes in the code's vocabulary by design, and the
    translation belongs at the moment the sentence becomes page copy. It is the hint and
    never the NAME: a box is labelled with the field the transport declared, and renaming
    that would be renaming a parameter the operator may have to type.
    """
    return tuple(
        dataclasses.replace(box, hint=wording.for_the_page(box.hint)) for box in boxes
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
        "tuning": {
            name: _in_the_pages_words(transports.hop_tuning(name)) for name in installed
        },
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


@router.post("/hops", response_class=HTMLResponse)
async def establish_hop(
    request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Establish both ends of an entry→leaf tunnel from the console's dialog.

    ``/hops/establish`` until M9.6, only because the pre-redesign page owned
    ``POST /panel/hops`` and asked for it with htmx too — so unlike the add-node form
    the two could not be told apart by a header.

    Each end's parameters arrive prefixed, the prefix is stripped, and below that line
    this function names no field of any protocol. The fields are also
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


@router.get("/hops/{node_transport_id}/dissolve", response_class=HTMLResponse)
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


@router.post("/hops/{node_transport_id}/dissolve", response_class=HTMLResponse)
async def tear_down_hop(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Remove both ends of a hop from the console, and say what is left to do.

    ``/tear-down`` until M9.6, for the same reason ``establish_hop`` above had a longer
    name: ``/dissolve`` belonged to the pre-redesign page, which drove it with htmx.
    ``GET`` and ``POST`` of this path are the confirmation and the act.

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

    Note that ``GET /panel/transports`` cannot collide with the withdraw and offer
    routes on ``/panel/transports/{node_transport_id}/...`` further up: different shape,
    and a different subject — this screen is about the protocols the IMAGE ships, those
    are about one row on one node.
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
            # The one sentence about what a hop-end push leaves behind, shared with the
            # replace dialog and with the answer both of them produce — see
            # console.HOP_PUSH_OUTCOME for why it is a constant and not prose.
            "hop_push_outcome": console.HOP_PUSH_OUTCOME,
        },
    )


@router.post("/keys/{node_transport_id}/rotate", response_class=HTMLResponse)
async def rotate_keys(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Re-mint this transport's material and push it — item 23, from the console.

    A half-done rotation is a BANNER, not a toast. Between the write and a successful
    push the database and the nodes disagree, and for a decoy that means the blocked
    value is still what the node is serving: that sentence has to survive the operator's
    next click rather than vanish after 2200ms.

    NODES, plural, on a hop end: this action re-keys both ends in one transaction and
    pushes two hosts, so the banner may be about a push that landed at one of them and
    left the tunnel down. ``console.rotation_summary`` is what says which.
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
        #
        # The service has already struck every held value out of these sentences
        # (``relay.refused_fields``). That does not make an empty box set redundant:
        # there is still no box on this answer for a per-parameter message to land in.
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
async def replace_params(
    node_transport_id: str,
    request: Request,
    session: AsyncSession = Depends(session_dependency),
):
    """Replace operator-supplied parameters, and resize the pool — a blocked decoy, or M17.

    Reads the form the way ``enable_transport`` does and for the same reason: this
    function must not know any protocol's field names. Two things it adds. The fields
    are FILTERED to the boxes this dialog actually rendered, so nothing else in a
    submission can reach the transport's model — and every one of those boxes is a value
    the operator typed, never a minted one, because ``replaceable_params`` subtracts key
    material before a box exists. And an empty box is dropped by ``parse_form``, which
    is what makes "leave it alone" expressible at all.

    THE POOL BOX IS THE ONE BOX ON THIS FORM THE TRANSPORT KNOWS NOTHING ABOUT — M17.1c.
    It is a column on the node-transport record, so it is filtered in with the rest and
    then lifted out before the mapping reaches the transport's model, converted here
    because a form gives text where the service takes a count. This is the console's only
    way to size a row that has served since before pools existed, which is what migration
    0006 promises an operator in writing; there is deliberately no second action and no
    second endpoint for it.
    """
    key = await console.key_row(session, node_transport_id)
    if not key.installed:
        # 422 with the dialog re-rendered, like every other refusal in this console —
        # the sentence comes from ``_params_form``, which is the one place that decides
        # what an uninstalled transport can be told.
        return await _refuse_params(request, session, node_transport_id, values={})
    node_transport = await rotation.get_node_transport(session, node_transport_id)
    boxes = _replaceable_boxes(node_transport)
    names = {box.name for box in boxes}

    form = await request.form()
    typed = {
        name: str(value).strip()
        for name, value in form.multi_items()
        if name in names
    }
    # The pool size is not a parameter of the transport and must not reach its model,
    # which forbids what it did not declare — so it is lifted out here, exactly as the
    # enable route keeps it out of ``parse_form``'s input. Left in ``typed`` all the same,
    # because that is what re-fills the boxes on a refusal and this one has a box.
    pool_typed = typed.get(addresses.POOL_BOX, "")
    # THE TRANSPORT'S OWN NAME, never ``key.transport``, which is what the SCREEN calls
    # this row: ``console.placed_as`` qualifies a second instance on one node as
    # "amneziawg (amneziawg-2)", and ``parse_form`` looks the name up in the registry and
    # falls back to an empty field map when it cannot resolve one. That fallback is
    # silent, and what it disables is the comma-split for sequence parameters — so on the
    # second instance of a transport on one node (which M15 exists to allow, and which the
    # runbook's entry box has) a list typed correctly arrived as one string and the
    # transport refused a value the operator had got right.
    supplied = transports.parse_form(
        node_transport.transport_name,
        ((name, value) for name, value in typed.items() if name != addresses.POOL_BOX),
    )
    if not supplied and not pool_typed:
        return await _refuse_params(
            request, session, node_transport_id, values=typed, failure=NOTHING_TYPED
        )

    pool_size = None
    if pool_typed:
        try:
            pool_size = int(pool_typed)
        except ValueError:
            # The panel's own refusal, for the enable form's reason: the service's
            # parameter is a count and a form gives it text, so there is nothing to hand
            # over. Under the box, quoting nothing back.
            return await _refuse_params(
                request,
                session,
                node_transport_id,
                values=typed,
                errors={addresses.POOL_BOX: POOL_NOT_A_NUMBER},
            )

    try:
        outcome = await rotation.replace_params(
            session,
            node_transport_id=node_transport_id,
            params=supplied,
            pool_size=pool_size,
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


def _replaceable_boxes(node_transport) -> tuple:
    """Every box the replace-parameters dialog renders for one row.

    The transport's own replaceable parameters, and — M17.1c — the pool size, for exactly
    the transports that declare each of their consumers needs an address
    (``TransportMeta.peer_address``, through ``addresses.spec_for``). One function because
    the dialog and the route that reads its submission back must agree about which names
    exist: the route filters the form to these names, and a box the route did not know
    about is a value an operator typed into a control that silently does nothing.

    The pool box is LAST, after the transport's own parameters, which is where it belongs
    on a form whose pool starts at one of those parameters — the size is read counting
    upwards from the address above it, and the hint says so.

    AND NOT AT ALL ON A HOP END, which is the row's own fact and not the transport's. The
    transport the runbook mandates for the hop is also the one it recommends for friends,
    so deciding from the declaration alone put this box on both ends of every hop: a
    control hinted "how many users this protocol may hand an address to" on a tunnel
    between two of the owner's own nodes, two lines above this same dialog's "No user
    holds anything on it: this is one end of a hop". The plan's done-when is that hop ends
    keep the same dialog boxes, and ``rotation._resize`` refuses a size on such a row from
    the other side, so the API cannot store what this no longer offers.

    ``placeholder`` is the size in place now, empty on a row enabled before pools existed,
    exactly as every other box on this form shows what it is replacing. It is a
    ``ParamBox`` and not the enable dialog's ``TuningField`` for that dialog's own reason:
    here an empty box means KEEP.
    """
    boxes = transports.replaceable_params(
        node_transport.transport_name, node_transport.params
    )
    if (
        addresses.spec_for(node_transport.transport_name) is None
        or node_transport.purpose in TransportPurpose.relays()
    ):
        return boxes
    return (
        *boxes,
        transports.ParamBox(
            name=addresses.POOL_BOX,
            placeholder=str(node_transport.pool_size or ""),
            hint=console.POOL_BOX_RESIZE_HINT,
        ),
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
            _in_the_pages_words(_replaceable_boxes(node_transport))
            if key.installed
            else ()
        ),
        "values": values or {},
        "errors": errors or {},
        "failure": failure or (None if key.installed else console.KEY_NOT_IN_THIS_IMAGE),
        # Shared with the rotate dialog and with the answer both of them produce — see
        # console.HOP_PUSH_OUTCOME. Rendered only on the hop branch, which the template
        # already decides from ``key.for_friends``.
        "hop_push_outcome": console.HOP_PUSH_OUTCOME,
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

    IT IS NO LONGER THE ONLY GUARD, and it is kept anyway. Sorting closes the class of
    LOCATIONS and not the class of MESSAGES: a ``field_validator`` on a field this form
    does have a box for can read the rest of the mapping through ``info.data``, so the
    complaint arrives at a real box name and this allow-list passes it. That class is
    closed in the service now, where the values are still in scope — see
    ``relay.refused_fields`` and ``docs/decisions.md`` (2026-09-10) — and this stays as
    the second line of defence, because a message can still be about something the
    operator never typed and a box is the only place a message has anywhere to belong.
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


# --- actions (HTMX fragments) ------------------------------------------------

@router.post("/nodes", response_class=HTMLResponse)
async def create_node(
    request: Request,
    name: str = Form(""),
    address: str = Form(""),
    location_label: str = Form(""),
    resolver: str = Form(""),
    ssh_host: str = Form(""),
    ssh_user: str = Form(""),
    ssh_port: str = Form(""),
    ssh_private_key: str = Form(""),
    session: AsyncSession = Depends(session_dependency),
):
    """Register a node from the console's dialog.

    Until M9.6 this one route had two answers: the console's, and a 303 back to the
    pre-redesign form at ``/panel/fleet``, which was a plain browser POST and so could
    be told apart by a header. The page is gone and so is the redirect — the console
    asks with htmx and gets the console's answer: the dialog closes, a toast names the
    node, and the table refreshes itself.

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
        "resolver": resolver.strip(),
        "ssh_host": ssh_host.strip(),
        "ssh_user": ssh_user.strip(),
        "ssh_port": ssh_port.strip(),
    }
    try:
        payload = schemas.NodeCreate(
            name=typed["name"],
            address=typed["address"],
            location_label=typed["location_label"],
            # Empty means "this node will never dial a hop", and is stored as nothing.
            resolver=typed["resolver"] or None,
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

    # Asked before the service is called only so the answer lands under the box it is
    # about: ``create_node`` refuses the same key with the same sentence, through the
    # same helper, for every caller that is not this form. The predicate is in one
    # place; which surface can place it is what differs.
    if ssh_private_key and not nodes.ssh_key_is_usable(ssh_private_key):
        return _refuse_node(
            request,
            values=typed,
            errors={"ssh_private_key": nodes.SSH_KEY_UNUSABLE},
            # The box is emptied on every refusal, so it is emptied on this one too —
            # and the operator is told, exactly as they are when some OTHER field was
            # the problem. A dialog that kept the rejected key would be the one place
            # this panel renders key material.
            key_dropped=True,
        )

    # The resolver, asked the same way and for the same reason as the key: the service
    # refuses it with this sentence for every other caller, and asking first is only so
    # the answer lands under its own box. Kept in the form when refused — an address the
    # operator chose is not a secret, and retyping it is how a second mistake gets in.
    problem = typed["resolver"] and nodes.resolver_problem(typed["resolver"])
    if problem:
        return _refuse_node(
            request,
            values=typed,
            errors={"resolver": wording.for_the_page(problem)},
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
    about — M8.6, and static/app.js allows exactly that one status to swap. A caller
    that is not htmx has nowhere to put a field error, so it gets a ``DomainError``,
    which the one exception handler turns into this codebase's error envelope. That
    split outlived the pre-redesign form it was written for: the bare shape of this
    POST is still reachable, and a dialog fragment is not an answer to it.
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
async def probe_node(
    node_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Ask a node what it is actually running, and say so on the console.

    A healthy answer is a toast: it is good news and it does not need to survive the
    next click. Anything else is a BANNER, which stays until the next successful
    action — an unreachable node, or one running a configuration older than the file
    on it, is a fault the operator has to still be able to read while they act on it.

    Until M9.6 there was a second probe route, ``/nodes/{id}/health``, answering the
    pre-redesign page with a ``panel/health.html`` fragment. It went with the page; the
    judgement it made in markup is ``console.health_summary``, which composes it as text.

    A node whose record cannot produce an SSH session at all — no address, or a stored
    key that will not load — never reaches the probe: ``check_node`` builds its target
    through ``apply.target_for``, which refuses those two before dialling. That refusal
    is an answer to the operator, not a fault, so it is shown here the way a failed
    apply is. Without this arm it was a 500, and a 500 on this button is the one outcome
    the screen has no way to explain.
    """
    node = await nodes.get_node(session, node_id)
    try:
        result = await health.check_node(session, node_id=node_id)
    except DomainError as exc:
        return _mutation(
            request, banner=exc.message, keeping=node.name, events="nodes-changed"
        )
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


@router.post("/nodes/{node_id}/apply", response_class=HTMLResponse)
async def apply_node(
    node_id: str, request: Request, session: AsyncSession = Depends(session_dependency)
):
    """Push this node's configuration to its host — the console's "apply".

    ``/nodes/{id}/push`` until M9.6, only because ``/apply`` belonged to the
    pre-redesign page, which answered it with a different fragment.

    A failure is a banner rather than a toast, and that is the point of this button on
    the stand: a failed apply marks the node degraded, and the operator has to be able
    to read why while they fix it instead of watching it disappear after 2200ms.

    THE BANNER NOW ALSO CARRIES A REFUSAL — M18.1 — and it is deliberately the same
    element. A node with nothing enabled is refused before anything is dialled and is
    NOT degraded, so that one message is not about a broken node; it still has to stay
    on the screen while the operator goes and enables a transport on it, which is the
    one thing a toast could not do for it.

    The same element, but NOT the same word above it — M18.1's review. The banner said
    `failed` over both, and the first-run answer it says it over is a healthy draft that
    has never been dialled; on this button `failed` additionally means "the node is now
    degraded", which is the one thing the refusal exists to stop the operator believing.
    """
    node = await nodes.get_node(session, node_id)
    try:
        applied = await apply.apply_node(session, node_id=node_id)
    except NothingToApply as exc:
        # A REFUSAL, and the label says so. Caught ahead of its own base class rather
        # than branching inside one handler, because the two differ in what happened to
        # the node as well as in the word: nothing was dialled, nothing was pushed and
        # the node's state has not moved.
        return _mutation(
            request,
            banner=exc.message,
            banner_label="refused",
            keeping=node.name,
            events="nodes-changed",
        )
    except DomainError as exc:
        # Shown, not raised: a failed apply has already recorded its reason and marked
        # the node degraded, and what the operator needs is the sentence on the screen
        # they are on rather than an error envelope.
        return _mutation(
            request,
            banner=exc.message,
            keeping=node.name,
            events="nodes-changed",
        )
    # ``applied`` cannot be empty: since M18.1 a node with nothing enabled is refused
    # above rather than pushed, and that was the only way this line was ever reached with
    # an empty mapping. The branch that used to toast "nothing enabled to apply" went
    # with it — it described an outcome this button never actually had, since the push it
    # was written for failed and degraded the node instead.
    return _mutation(
        request,
        toast=f"config applied to {node.name} — {', '.join(sorted(applied))}",
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

    The console asks with htmx and gets the console's answer — the dialog closes, a
    toast names what was enabled, the tables refresh. Until M9.6 this route also
    answered the pre-redesign page's plain browser POST with a 303; that page is gone
    and so is the redirect, and with it the BARE field names that form submitted.

    The form is read as a flat mapping and handed to the transport's own validator
    untouched. That is what makes a NEW protocol appear in this panel with no change
    here: this function does not know any protocol's field names, and the ``params``
    it forwards are whatever that transport declared it needs.

    EVERY BOX IS NAMED ``<transport>-<field>``. The dialog renders a group of boxes per
    transport and hides all but the chosen one — a hidden input is still submitted, so
    with every group naming its boxes plainly a second transport's ``port`` would arrive
    under the same name and the last one would win. Until M9.6 a bare name was accepted
    as a fallback, because the pre-redesign page built only the chosen transport's boxes
    in JavaScript and named them plainly; that page is gone, and a bare name is now one
    this form cannot read like any other.
    """
    form = await request.form()
    typed = {key: str(value).strip() for key, value in form.multi_items()}
    transport_name = typed.get("transport_name", "")

    if not transport_name:
        return await _refuse_the_form(
            request, session, node_id, typed, {"transport_name": NO_TRANSPORT_CHOSEN}
        )

    # Which boxes this transport declares it needs, and — wider — every field it lets an
    # operator answer at all. Both are empty for a transport this image cannot deliver or
    # does not ship, and EVERY CHECK BELOW IS SKIPPED for one: with nothing declared,
    # a name-by-name complaint would be a complaint about every name submitted, and it
    # would arrive INSTEAD of the answer the operator needs, which is that there is no
    # such transport here (or that nothing could receive it). The service refuses those
    # two by name and says so far better than a guess here would, so the submission is
    # carried straight to it.
    offerable = transport_name in transports.offerable_transports()
    boxes = transports.operator_tuning(transport_name) if offerable else ()
    declared = transports.supplied_params(transport_name) if offerable else frozenset()

    # The pool box, for exactly the transports that declare each person needs an address
    # of their own — M17, and asked of the transport's own declaration rather than of its
    # name. ``None`` for every other transport, which is what makes every check below
    # skip it: the box is not rendered for them, so a submission naming it is a name this
    # form cannot read, like any other.
    pool_spec = addresses.spec_for(transport_name) if offerable else None
    pool_field = f"{transport_name}-{addresses.POOL_BOX}"

    def supplied(field: str) -> str:
        return typed.get(f"{transport_name}-{field}", "")

    # A name this form cannot read. THE GROUP PREFIX IS PART OF THE NAME, which is what
    # changed in M9.6: a bare ``port`` was looked up as a fallback while the pre-redesign
    # page still built its boxes that way, and now that the page is gone it is a name
    # like any other this form does not have. Not merely dropped — ``supplied`` would
    # return "" for it and the operator would be told a box they filled was left empty.
    #
    # Another GROUP's boxes are skipped rather than refused: the dialog renders one group
    # per transport and a hidden input is still submitted, so those arrive on every
    # submission and are the markup's doing rather than the operator's.
    #
    # Not asked at all when the transport is not offerable, per the note above: there is
    # no declared set to measure a name against, so every name would be unreadable and
    # this complaint would displace the service's own — which is the one the operator
    # needs.
    def its_own_box(field: str) -> bool:
        # ``declared`` is every field the TRANSPORT lets an operator supply; the pool box
        # is neither a field of the transport nor something it validates, so it is
        # admitted here explicitly and only for a transport that declares it needs one.
        # Written as an addition rather than by widening ``declared`` because that set is
        # also what ``parse_form`` reads, and the pool size must not reach the
        # transport's model — which forbids what it did not declare.
        readable = declared | ({addresses.POOL_BOX} if pool_spec else frozenset())
        return (
            field.startswith(f"{transport_name}-")
            and field.removeprefix(f"{transport_name}-") in readable
        )

    def another_group(field: str) -> bool:
        return any(
            field.startswith(f"{other}-")
            for other in transports.offerable_transports()
            if other != transport_name
        )

    unreadable = sorted(
        field
        for field in typed
        if field != "transport_name"
        and not its_own_box(field)
        and not another_group(field)
    ) if offerable else []
    if unreadable:
        return await _refuse_the_form(
            request,
            session,
            node_id,
            typed,
            failure=NOT_ITS_PARAMETER.format(names=", ".join(unreadable)),
        )

    # The pool box is in this list when the transport declares one, so an empty one is
    # refused UNDER ITSELF rather than as a sentence above the form — the same treatment
    # every other box on this dialog gets, and the same sentence: nothing defaults it,
    # because a default pool size would be a number this project chose for somebody
    # else's node.
    empty = [box.name for box in boxes if not supplied(box.name)]
    if pool_spec and not supplied(addresses.POOL_BOX):
        empty.append(addresses.POOL_BOX)
    if empty:
        return await _refuse_the_form(
            request,
            session,
            node_id,
            typed,
            {f"{transport_name}-{name}": NO_DEFAULT for name in empty},
            plainly="; ".join(f"{name}: {NO_DEFAULT}" for name in empty),
        )

    # A value longer than any parameter this image ships takes — refused HERE, before the
    # transport's own validator sees it, because that one quotes what it rejected and the
    # quote is the defect (``VALUE_TOO_LONG``). Over the boxes this dialog actually drew,
    # which is what an operator can type into; anything else that reaches the validator is
    # bounded on the way back out, in ``relay.refused_fields``.
    over_long = [box.name for box in boxes if len(supplied(box.name)) > VALUE_MAX_LENGTH]
    if pool_spec and len(supplied(addresses.POOL_BOX)) > VALUE_MAX_LENGTH:
        over_long.append(addresses.POOL_BOX)
    if over_long:
        return await _refuse_the_form(
            request,
            session,
            node_id,
            typed,
            {f"{transport_name}-{name}": VALUE_TOO_LONG for name in over_long},
            plainly="; ".join(f"{name}: {VALUE_TOO_LONG}" for name in over_long),
        )

    pool_size = None
    if pool_spec:
        try:
            pool_size = int(supplied(addresses.POOL_BOX))
        except ValueError:
            # Refused here rather than passed on, because the service's parameter is a
            # count and a form gives it text. The sentence says what the box takes and
            # quotes nothing back: what arrived is not a number, and echoing it would put
            # unvalidated text in the markup for no gain.
            return await _refuse_the_form(
                request,
                session,
                node_id,
                typed,
                {pool_field: POOL_NOT_A_NUMBER},
                plainly=f"{addresses.POOL_BOX}: {POOL_NOT_A_NUMBER}",
            )

    # Reading the form is shared with the rotation form below: a field the transport
    # declared as a sequence becomes a list whether or not the operator typed a comma.
    #
    # EVERY FIELD THE TRANSPORT DECLARES, not only the ones this dialog renders a box
    # for, and the difference is a value an operator can lose. The dialog draws a box per
    # REQUIRED field; a transport also has fields it defaults, and a submission may
    # answer one — it must reach the model rather than be dropped in silence. For the
    # shipped Reality transport
    # the discarded field would have been its decoy port, silently replaced by the value
    # every other node uses, which is the one substitution CLAUDE.md names outright: a
    # fleet that borrows one handshake is a fleet that can be enumerated.
    #
    # What the lookup DOES skip is another group's boxes. The console renders a group per
    # transport and a hidden input is still submitted, so a second transport's ``port``
    # arrives too — it is named ``<other>-port``, which is never a name looked up here.
    # Anything ELSE this form cannot read was refused above rather than skipped, so the
    # only thing dropped in silence is markup the dialog itself produced.
    #
    # Key material is not in ``supplied_params`` at all, so no submission can name one —
    # asserted, not asserted-in-a-comment: see
    # ``test_no_submission_can_name_a_value_the_control_plane_mints`` and
    # ``test_no_form_may_supply_what_a_transport_declares_as_material``.
    params = transports.parse_form(
        transport_name, ((field, supplied(field)) for field in sorted(declared))
    )

    try:
        node_transport = await nodes.enable_and_grant(
            session,
            node_id=node_id,
            transport_name=transport_name,
            params=params,
            pool_size=pool_size,
        )
    except ParamsRefused as exc:
        # The transport refused what it was given, field by field, and this dialog has a
        # box for each of them — so each complaint goes under the box it is about, the
        # same treatment the hop dialog gives one. Which of them may be PRINTED is not
        # decided here: ``_refused_parameters`` allows a sentence only under a box, and
        # the service has already struck every minted value out of every sentence
        # (``relay.refused_fields``). Both matter on this path, because enabling is the
        # moment material is minted and the mapping that was validated held it.
        if not _is_htmx(request):
            raise
        # The pool box is in the allowed set for the transports that have one, so a
        # refusal about the SIZE lands under the number it is about. Without it the
        # sentence would be withheld as a complaint with no box — which is the right
        # default for a name this form does not render, and wrong for the one it does.
        return await _refuse_enable(
            request,
            session,
            node_id,
            values=typed,
            **_on_its_boxes(
                exc,
                transport_name,
                {box.name for box in boxes}
                | ({addresses.POOL_BOX} if pool_spec else set()),
            ),
        )
    except DomainError as exc:
        # Everything else is about the request rather than about one value: a transport
        # this image does not ship, one no client could receive, a listening port this
        # node already uses. Stated once, above the form.
        if not _is_htmx(request):
            raise
        return await _refuse_enable(
            request,
            session,
            node_id,
            values=typed,
            failure=wording.for_the_page(exc.message),
        )

    # NO SECOND FAN-OUT HERE, and its absence is the point — M17. This route used to
    # grant every active friend again, in a second transaction, after the enable had
    # committed. ``nodes.enable_and_grant`` above does that INSIDE the transaction it
    # commits, which is what makes a pool with no room a refusal that changed nothing;
    # a second pass afterwards could still raise ``Conflict`` — outside this route's
    # try/except, so htmx would get a bare 409 envelope it does not swap — for an
    # operation that had already succeeded. ``api/routes.py`` has no such loop either.
    node = await nodes.get_node(session, node_id)
    return _mutation(
        request,
        # UI-PATTERNS §8: an action with a delayed real-world effect says so. Nothing is
        # on the host until it is applied — the row exists, the material is minted, and
        # the node is serving none of it yet.
        toast=(
            f"{node_transport.transport_name} enabled on {node.name} — apply the node "
            "to push it"
        ),
        keeping=node.name,
        # Three collections move: this node's chips, the material that was just minted,
        # and every active user's coverage count. Comma-separated in one HX-Trigger, the
        # shape M9.2 established for a mutation touching more than one.
        events="nodes-changed, keys-changed, friends-changed",
    )


async def _refuse_the_form(
    request: Request,
    session: AsyncSession,
    node_id: str,
    typed: dict,
    errors: dict | None = None,
    *,
    failure: str | None = None,
    plainly: str | None = None,
) -> Response:
    """A submission this panel refused before the service saw it, in whichever panel.

    The console gets its dialog back at 422, with the message under the control it is
    about when there is one and above the form when the complaint is about a name that
    has no box. A caller that is not htmx has nowhere to render a field error and gets a
    ``DomainError`` instead, which the one exception handler turns into this codebase's
    error envelope — the same split as ``_refuse_node``, and it outlived the pre-redesign
    form it was written for. ``plainly`` is what that envelope says: the box NAMES
    without the group prefix, which is markup a caller with no form knows nothing about.
    """
    if not _is_htmx(request):
        raise DomainError(plainly or failure or " ".join((errors or {}).values()))
    return await _refuse_enable(
        request, session, node_id, values=typed, errors=errors, failure=failure
    )


def _mutation(
    request: Request,
    *,
    dialog: str | None = None,
    toast: str | None = None,
    banner: str | None = None,
    banner_label: str | None = None,
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

    ``banner_label`` is the word above the banner and defaults to ``failed`` — the only
    other value this console has a use for is ``refused``, for an answer where nothing
    was attempted and nothing changed. It is a caller's choice rather than something the
    template works out because only the caller knows which of the two it is holding: the
    same element carries a node whose apply failed and a node that was never dialled.
    """
    response = TEMPLATES.TemplateResponse(
        request,
        "panel/mutation_result.html",
        {
            "dialog": dialog,
            "toast": wording.for_the_page(toast, keeping=keeping) if toast else None,
            "banner": wording.for_the_page(banner, keeping=keeping) if banner else None,
            "banner_label": banner_label,
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
            #
            # THE POOLS ARE ASKED ABOUT AGAIN HERE, after the service — M17.2, and it is
            # required rather than tidy. A refusal from ``grant_everywhere`` rolls the
            # session back, so this dialog has to be composed from what the database says
            # AFTERWARDS; ``_add_friend_form`` does that in fresh queries and reads no
            # object this route was holding. It is also the one refusal whose honest
            # answer is "there is no room at all", which renders the dialog with no form
            # rather than with a message under the nickname.
            await _add_friend_form(
                session, nickname=nickname, error=wording.for_the_page(exc.message)
            ),
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


# --- Audit log (M10.4) -------------------------------------------------------

@router.get("/audit", response_class=HTMLResponse)
async def audit_screen(request: Request, session: AsyncSession = Depends(session_dependency)):
    """Audit log — what the operator changed, in plain words.

    Three columns, and the design's fourth one — ``source`` — does not exist:
    ``docs/decisions.md`` (2026-09-11) drops it outright rather than leaving it blank,
    because an address of a person against a time is the record the charter says is
    absent here. TIME is when the change committed, ACTOR is the configured operator
    RENDERED rather than stored (there is one, so the column cannot vary), and EVENT is
    a sentence composed in ``panel/wording.py`` from a machine key and two labels.

    Every cell passes the test this console applies to every cell (``docs/decisions.md``,
    2026-09-09): *does it move when a friend connects?* None of them does, and that is a
    property of the table rather than of this route — the delivery endpoint writes no row
    at all, which has a scenario of its own in both suites.

    It reads the trail through ``console.trail_entries`` rather than through
    ``services/audit``, and the reason is mechanical as well as tidy:
    ``test_no_route_writes_the_trail`` refuses the audit service and the model anywhere
    under ``api/`` or ``panel/``, so a route that reached for the table directly would go
    red whether it read it or wrote it. The rule is stronger than the thing it is aimed
    at, deliberately.

    THE FIRST CONSOLE SCREEN SINCE M9.5 WITH A SESSION AGAIN. Transports and Settings
    have none; this one is a fact about the fleet, so it queries. No self-swapping
    fragment and no ``-changed`` trigger: nothing an operator can do from this screen
    changes what is on it, and every mutation that WOULD is on another screen, which
    they will navigate back from — a refresh URL here would exist only to be listed.
    """
    entries = await console.trail_entries(session)
    return _screen(
        request,
        screen="panel/screens/audit.html",
        current="audit",
        title="Audit log",
        subtitle="what you changed, and when — never who connected to what",
        context={
            "entries": wording.the_trail(entries),
            # The screen's three standing sentences — the lead, the empty state and
            # the footnote — composed in ``services/console.py`` like every other piece
            # of console prose, so the tests assert a constant rather than a copy of the
            # words. The last one is derived from this process's own retention setting
            # and sweep interval, so it cannot go false the day either moves.
            "records": console.TRAIL_WHAT_IT_HOLDS,
            "nothing_yet": console.TRAIL_NOTHING_YET,
            "window": console.trail_window(
                request.app.state.settings, shown=len(entries)
            ),
        },
    )


# --- Settings (M10.2) --------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def settings_screen(request: Request) -> Response:
    """Settings — what this control plane is running with, and where each value changes.

    READ-ONLY, and there is no POST beside it. ``docs/decisions.md`` (2026-09-11): the
    design's Panel form is dropped whole rather than drawn and refused, because a form
    that saves a value the process only reads from the environment at boot is a lie
    told in a text field, and the narrower reading — draw it, refuse the save — is the
    same lie with a worse error message.

    It renders ``request.app.state.settings``: the live object this application was
    built with, never ``os.environ`` and never a file. That is what makes the screen
    true of the process the operator is signed into rather than of an env file that
    may have been edited since boot — and it is what stops the screen going stale,
    since there is no second copy of a value here to drift from the one in use.

    The SECOND console screen with no session dependency (the Transports screen was
    the first, and M9.3's note calling it "the only" one is superseded here). Nothing
    on it is a fact about the fleet, so there is no query to make; it is on ``router``,
    so it is still operator-only. A later step wanting a fleet fact on this screen adds
    the session back — and at that point *"does it move when a friend connects?"*
    applies to whatever it wants to put here.

    No self-swapping fragment and no ``-changed`` trigger, for the Transports screen's
    reason: nothing this panel can do changes what this process was started with, so a
    ``/panel/settings/table`` URL would exist only to be listed.
    """
    settings = request.app.state.settings
    return _screen(
        request,
        screen="panel/screens/settings.html",
        current="settings",
        title="Settings",
        subtitle=(
            "what this control plane is running with, and where each value is changed"
        ),
        context={
            "configuration": console.settings_rows(settings),
            "admins": console.admin_rows(settings),
            # The screen's three standing sentences, handed over rather than written
            # in the template, for the reason every other console sentence lives in
            # ``services/console.py``: they are the panel's claims about what it can
            # and cannot do with a value, and a test asserts them against the constant
            # rather than against a copy of the words.
            "read_at_boot": console.SETTINGS_READ_AT_BOOT,
            "secrets_withheld": console.SETTINGS_SECRETS_WITHHELD,
            "one_operator": console.ONE_OPERATOR,
        },
    )
