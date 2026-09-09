"""The redesigned console — the two screens M8 ports, and what they may not show.

WHAT: the shell, Overview, Users, the add-user and subscription dialogs, the states
      the design did not draw, and the four cells the charter forbids.
WHY:  the design (``design/README.md``) is right about the layout and wrong about
      four cells, because it was drawn without the charter in hand. ``docs/decisions.md``
      decision 6 replaced them. A decision recorded in a document decays; a decision
      with a test over it does not, which is what most of this file is.
HOW:  the in-process client from conftest, already holding an operator session. These
      are ordinary unit tests over rendered HTML — they prove what the templates put
      on screen, not that a browser lays it out, which is what the acceptance walk is
      for.
"""

import pathlib
import re

import pytest

from control.app.errors import Conflict
from control.app.panel import wording
from control.app.services import friends as friends_service

STATIC = pathlib.Path(__file__).resolve().parents[2] / "control" / "app" / "static"

# The four cells decision 6 removed, as the words that would appear on screen if any
# of them came back. Written as a table so a reader can see the whole prohibition at
# once — and so adding a fifth is one line.
FORBIDDEN_CELLS = (
    "last seen",
    "throughput",
    "sessions",
    "busiest node",
    "bandwidth",
)


async def a_serving_node(client, reality_params) -> str:
    """One node with a protocol enabled and put into service."""
    node = await client.post(
        "/api/nodes",
        json={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
    )
    node_id = node.json()["id"]
    await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    await client.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
    return node_id


# --- the shell (M8.2) ---------------------------------------------------------

async def test_the_panel_opens_on_the_console(client) -> None:
    """/panel/ is the Overview, inside the shell, with the design's own stylesheets."""
    response = await client.get("/panel/")

    assert response.status_code == 200
    body = response.text
    assert '<link rel="stylesheet" href="/static/styles.css">' in body
    assert '<link rel="stylesheet" href="/static/fonts.css">' in body
    assert 'class="sidenav"' in body
    assert 'id="main"' in body
    assert "Overview" in body


async def test_the_sidebar_leads_only_to_screens_that_exist(client) -> None:
    """Every nav target answers. A dead nav link is worse than an honest one."""
    body = (await client.get("/panel/")).text
    targets = re.findall(r'<a href="(/panel/[^"]*)"', body)

    assert "/panel/friends" in targets
    assert "/panel/fleet" in targets
    for target in set(targets):
        assert (await client.get(target)).status_code == 200, target


async def test_there_is_no_traffic_screen(client) -> None:
    """Decision 6's sharper half: the slot is given to nothing, not to a placeholder.

    A screen that exists to say "we do not measure this" is an invitation to add the
    measurement later.
    """
    body = (await client.get("/panel/")).text
    assert "Traffic" not in body
    assert (await client.get("/panel/traffic")).status_code == 404


async def test_an_htmx_navigation_returns_a_fragment_not_a_document(client) -> None:
    """The control rulebook's trap: a full document swapped into #main nests <html>.

    Also asserts the sidebar comes back out-of-band — without it the highlight would
    stay on the screen the operator just left, which is the specific bug this shape
    of shell always has.
    """
    response = await client.get("/panel/friends", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "<!doctype html>" not in response.text.lower()
    assert "<body" not in response.text
    assert 'hx-swap-oob="outerHTML:#console-nav"' in response.text
    assert 'aria-current="page"' in response.text


# --- Overview (M8.4) ----------------------------------------------------------

async def test_the_overview_carries_only_facts_about_the_fleet(
    client, reality_params
) -> None:
    """The four stat cards are decision 6's, and none of the removed cells is back."""
    await a_serving_node(client, reality_params)
    await client.post("/api/friends", json={"nickname": "mira"})

    body = (await client.get("/panel/")).text

    for kicker in ("nodes online", "active users", "hops established", "transports enabled"):
        assert kicker in body, f"the Overview lost the {kicker!r} card"
    for cell in FORBIDDEN_CELLS:
        assert cell not in body.lower(), (
            f"the Overview shows {cell!r}, which the charter says must not exist"
        )


async def test_the_node_preview_reports_drift_rather_than_load(
    client, reality_params
) -> None:
    """Decision 6's replacement for "load", and it must say something true.

    Nothing has been pushed to this node — there is no SSH key and no host — so the
    honest answer is "never applied", not a number about the people on it.
    """
    await a_serving_node(client, reality_params)

    body = (await client.get("/panel/")).text

    assert "never applied" in body
    assert ">load<" not in body


async def test_a_node_with_nothing_switched_on_does_not_read_as_healthy(client) -> None:
    """The drift cell must not give a clean bill of health to a node serving nobody.

    "in sync" is true of a node with no transports in the arithmetic sense and false
    in every sense the operator cares about, which is the kind of true that costs an
    evening.
    """
    await client.post(
        "/api/nodes",
        json={"name": "bare-1", "address": "192.0.2.11", "location_label": "Testland"},
    )

    body = (await client.get("/panel/")).text

    assert "nothing enabled" in body
    assert "in sync" not in body


async def test_a_fresh_install_says_what_to_do_next(client) -> None:
    """M8.6, and the first thing the acceptance stand's seed ever shows."""
    body = (await client.get("/panel/")).text

    assert "Nothing is configured yet" in body
    assert "Start with a node" in body
    # Not a broken table: the empty state stands INSTEAD of the preview tables.
    assert "<table" not in body


# --- Users (M8.5) -------------------------------------------------------------

async def test_the_users_screen_says_users_and_the_route_says_friends(
    client, reality_params
) -> None:
    """Decision 9: the rename stops at the rendered page."""
    await a_serving_node(client, reality_params)
    await client.post("/api/friends", json={"nickname": "mira"})

    response = await client.get("/panel/friends")

    assert response.status_code == 200
    body = response.text
    assert "Users" in body
    assert "mira" in body
    # The visible copy never calls them friends…
    assert "friend" not in _visible_text(body).lower()
    # …and the machinery under it never calls them anything else.
    assert "/panel/friends/" in body


async def test_the_users_table_shows_added_and_never_last_seen(
    client, reality_params
) -> None:
    await a_serving_node(client, reality_params)
    await client.post("/api/friends", json={"nickname": "mira"})

    body = (await client.get("/panel/friends")).text

    assert ">added<" in body
    for cell in FORBIDDEN_CELLS:
        assert cell not in body.lower()


async def test_an_empty_users_screen_names_the_next_action(client) -> None:
    body = (await client.get("/panel/friends")).text

    assert "No users yet" in body
    assert "add user" in body


async def test_adding_a_user_hands_back_their_link_in_one_exchange(
    client, reality_params, settings
) -> None:
    """M8.5's whole behaviour: create, close, and open the link dialog by itself."""
    await a_serving_node(client, reality_params)

    response = await client.post("/panel/friends", data={"nickname": "mira"})

    assert response.status_code == 200
    body = response.text
    # The add dialog has been replaced by the subscription dialog, in one response.
    assert "Add a user" not in body
    assert "copy link" in body
    assert f"{settings.public_base_url}/sub/" in body
    # A toast, naming its object — UI-PATTERNS §8.
    assert "mira added" in body
    # …and the console is told to route to Users.
    assert "friends-created" in response.headers.get("HX-Trigger", "")


async def test_a_refused_nickname_comes_back_on_the_field(client) -> None:
    """M8.6 field-level validation, and no second user created."""
    await client.post("/panel/friends", data={"nickname": "mira"})

    duplicate = await client.post("/panel/friends", data={"nickname": "mira"})

    assert duplicate.status_code == 422
    assert "already exists" in duplicate.text
    assert 'aria-invalid="true"' in duplicate.text
    # Still the add dialog, with what was typed still in the field.
    assert "Add a user" in duplicate.text
    assert 'value="mira"' in duplicate.text
    assert len((await client.get("/api/friends")).json()) == 1


@pytest.mark.parametrize(
    "nickname,expected",
    [("", "a nickname is required"), ("x" * 65, "64 characters or fewer")],
)
async def test_a_nickname_that_cannot_be_stored_is_refused_with_a_sentence(
    client, nickname: str, expected: str
) -> None:
    """Without this, an over-long nickname reached the column and came back a 500."""
    response = await client.post("/panel/friends", data={"nickname": nickname})

    assert response.status_code == 422
    assert expected in response.text


# --- the subscription link, and where it may not appear -----------------------

async def test_the_link_appears_in_its_dialog_and_nowhere_else(
    client, reality_params
) -> None:
    """A bearer credential in a URL path: it lives in one dialog, on demand.

    The table the operator leaves open must not carry it — nor must the Overview,
    which is the screen a shoulder or a screenshot is most likely to catch.
    """
    await a_serving_node(client, reality_params)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "mira"})
    ).json()["id"]
    token = (
        await client.get(f"/api/friends/{friend_id}/subscription")
    ).json()["url"].rsplit("/", 1)[-1]

    assert token not in (await client.get("/panel/friends")).text
    assert token not in (await client.get("/panel/")).text

    dialog = await client.get(f"/panel/friends/{friend_id}/subscription")
    assert dialog.status_code == 200
    assert token in dialog.text
    # Never in an attribute a browser would keep or a person would hover: not an
    # href, not a title, not an input value.
    assert f'href="{token}' not in dialog.text
    assert "title=" not in dialog.text
    assert not re.search(rf'value="[^"]*{re.escape(token)}', dialog.text)


# --- revocation ---------------------------------------------------------------

async def test_revoking_confirms_first_then_names_the_object(client) -> None:
    """UI-PATTERNS §3 and §8, and the design's own note that revoke is not a toggle.

    No node in this fleet, so the revocation has nothing to push and completes — which
    is the path that produces the toast. The other path is the test below.
    """
    friend_id = (
        await client.post("/api/friends", json={"nickname": "mira"})
    ).json()["id"]

    confirm = await client.get(f"/panel/friends/{friend_id}/revoke")
    assert confirm.status_code == 200
    assert "Revoke mira?" in confirm.text
    assert "cannot be undone" in confirm.text

    done = await client.post(f"/panel/friends/{friend_id}/revoke")
    assert done.status_code == 200
    assert "mira revoked — link is dead" in done.text
    assert "friends-changed" in done.headers.get("HX-Trigger", "")

    # The row is inert afterwards, with no way back — the design's revoke/restore
    # toggle would be a lie here, because the key material is gone.
    table = (await client.get("/panel/friends/table")).text
    assert "revoked" in table
    assert "restore" not in table


async def test_an_incomplete_revocation_stays_on_screen(client, reality_params) -> None:
    """The one outcome a toast must not carry.

    A revocation that could not reach every node leaves somebody still connected. The
    node in this fleet has no SSH host, so the re-push fails and the revocation is
    partial — and the operator gets a banner that stays until their next successful
    action, not a message that removes itself after 2200ms.
    """
    await a_serving_node(client, reality_params)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "mira"})
    ).json()["id"]

    done = await client.post(f"/panel/friends/{friend_id}/revoke")

    assert done.status_code == 200
    assert 'hx-swap-oob="innerHTML:#banner-slot"' in done.text
    assert "still live" in done.text
    assert "toast" not in done.text


# --- what a browser is allowed to keep (acceptance round 1) -------------------

# Every console URL a browser can navigate to AND htmx can fetch as a fragment. The
# defect this section stands over needs both halves of that sentence: a URL with two
# representations, and a cache that stores one of them under the other's name.
TWO_REPRESENTATION_URLS = ("/panel/", "/panel/friends")


@pytest.mark.parametrize("path", TWO_REPRESENTATION_URLS)
async def test_a_console_fragment_can_never_be_stored_under_its_page_url(
    client, path: str
) -> None:
    """The acceptance defect: Back left the console as unstyled raw HTML.

    The mechanism is a cache entry, not a swap. A sidebar click fetches this URL with
    ``HX-Request`` and gets the FRAGMENT; with no cache directive the browser stores
    that body under the plain URL, and a back/forward navigation reuses a stored
    entry without revalidating — so Back rendered the fragment as the whole document.
    No ``<head>``, therefore no stylesheets, therefore Times New Roman until reload.

    Both headers are asserted because they close it in different places: ``no-store``
    means no entry exists, ``Vary`` means a document request could not match one if
    it did.
    """
    document = await client.get(path)
    fragment = await client.get(path, headers={"HX-Request": "true"})

    # The premise. Without two different bodies there is nothing to confuse.
    assert "<!doctype html>" in document.text.lower()
    assert "<!doctype html>" not in fragment.text.lower()

    for response in (document, fragment):
        assert response.headers["cache-control"] == "no-store"
        assert "HX-Request" in response.headers["vary"]


@pytest.mark.parametrize(
    "path", (*TWO_REPRESENTATION_URLS, "/panel/friends/table", "/panel/friends/new")
)
async def test_no_panel_response_is_storable(client, path: str) -> None:
    """Wider than the defect, and for a second reason.

    One of these fragments renders a live subscription token, and a bearer credential
    that a browser may write to its disk cache is a credential that outlives the
    session it was shown in.
    """
    assert (await client.get(path)).headers["cache-control"] == "no-store"


async def test_static_assets_are_still_cacheable(client) -> None:
    """The guard on the rule above: it must not reach the stylesheets and fonts.

    The console is opened over a management tunnel from a restricted network, and
    re-downloading Barlow on every navigation is a real cost paid for nothing — the
    assets carry no session and no credential.
    """
    response = await client.get("/static/app.css")

    assert response.status_code == 200
    assert response.headers.get("cache-control") != "no-store"


async def test_a_history_restore_is_answered_with_the_whole_document(client) -> None:
    """Back, with nothing in htmx's cache to restore from.

    htmx re-asks the server with ``HX-Request`` *and*
    ``HX-History-Restore-Request``, then swaps the answer into the whole ``<body>``.
    A fragment there replaces the shell with a bare screen — no sidebar, no header,
    no dialog slot — which is the same "the styling is gone" report by another route.
    """
    response = await client.get(
        "/panel/friends",
        headers={"HX-Request": "true", "HX-History-Restore-Request": "true"},
    )

    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()
    assert 'class="sidenav"' in response.text
    assert 'id="main"' in response.text
    assert 'id="dialog-slot"' in response.text


async def test_the_console_is_never_snapshotted_into_local_storage(client) -> None:
    """htmx's history cache writes the whole body to localStorage — including,
    after the add-user flow, an open dialog holding a live subscription URL.

    ``hx-history="false"`` is what stops it. A subscription URL is a bearer
    credential and may not reach anything a browser would remember.
    """
    assert 'hx-history="false"' in (await client.get("/panel/")).text


# --- a nickname the layout was not drawn for (acceptance round 1) -------------

async def test_the_nickname_field_states_its_limit_instead_of_truncating(
    client,
) -> None:
    """``maxlength`` made the field lie: 1002 characters pasted, 64 kept, nothing
    said, and the person created under the clipped name.

    Now the limit is written under the field and the server refuses anything longer
    through the same 422 path a duplicate name takes.
    """
    dialog = await client.get("/panel/friends/new")

    assert "maxlength" not in dialog.text
    assert "64 characters or fewer" in dialog.text


async def test_an_over_long_nickname_creates_nobody(client) -> None:
    """The half that was confirmed against the database: 1002 submitted, 64 stored."""
    response = await client.post("/panel/friends", data={"nickname": "n" * 1002})

    assert response.status_code == 422
    assert "64 characters or fewer" in response.text
    assert (await client.get("/api/friends")).json() == []


async def test_a_row_action_does_not_take_the_whole_list_away(
    client, reality_params
) -> None:
    """htmx inherits ``hx-indicator`` down the tree.

    So "show link" — a button whose request changes nothing about the list — pulled
    the table's own loading skeleton over the entire table while it fetched a dialog.
    ``hx-disinherit`` leaves each button its own indicator, itself.
    """
    await a_serving_node(client, reality_params)
    await client.post("/panel/friends", data={"nickname": "mira"})

    table = await client.get("/panel/friends/table")
    overview = await client.get("/panel/overview/body")

    for response in (table, overview):
        assert 'hx-indicator="this"' in response.text
        assert 'hx-disinherit="hx-indicator"' in response.text


async def test_a_long_nickname_leaves_the_short_columns_alone(
    client, reality_params
) -> None:
    """A 64-character name pushed the Overview's Users card into an inner horizontal
    scroll: the date wrapped onto three lines and the button was clipped to a sliver.

    The columns that must never be squeezed say so in the markup; the wrapping that
    lets the name give way instead is ``.table td { overflow-wrap: anywhere }``.
    """
    await a_serving_node(client, reality_params)
    longest = "n" * 64
    created = await client.post("/panel/friends", data={"nickname": longest})
    assert created.status_code == 200

    for path in ("/panel/friends/table", "/panel/overview/body"):
        body = (await client.get(path)).text
        assert longest in body, path
        assert 'class="text-muted nowrap"' in body, path


# --- acceptance round 3 -------------------------------------------------------

# The console's own stylesheet and script, read as text. There is no browser in this
# suite, so a rule about how something LOOKS is asserted where it is written; the
# acceptance walk is what proves it renders. Comments go first — this repository
# explains its decisions in prose, and that prose quotes the very rules it removed.
def _served(name: str) -> str:
    text = (STATIC / name).read_text()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def _css_rules() -> dict[str, str]:
    """Every rule in app.css as ``selector -> declarations``."""
    return {
        selector.strip(): body
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", _served("app.css"))
    }


async def test_a_refusal_says_user_because_that_is_what_the_screen_says(client) -> None:
    """Decision 9, in the direction the console was leaking.

    The rule has two sides: no rename may travel INTO the code, and the code's own
    word may not travel OUT onto the page. A duplicate nickname was refused with
    "a friend called 'dima' already exists" on a screen where every other word says
    user — the same boundary crossed the other way.
    """
    await client.post("/panel/friends", data={"nickname": "dima"})

    duplicate = await client.post("/panel/friends", data={"nickname": "dima"})

    assert duplicate.status_code == 422
    visible = _visible_text(duplicate.text)
    assert "already exists" in visible
    assert "a user called" in visible
    assert "friend" not in visible.lower()


async def test_no_console_surface_says_friend_where_a_person_can_read_it(
    client, reality_params
) -> None:
    """The audit that goes with the one message, in this milestone's own shape.

    THE LIST IS THE TEST (docs/tracker/M8/step-notes.md): every console screen,
    fragment and dialog is walked, and none of them may put the code's word in front
    of the operator. A new one joins this list in the change that adds it.
    """
    await a_serving_node(client, reality_params)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "mira"})
    ).json()["id"]

    surfaces = (
        "/panel/",
        "/panel/friends",
        "/panel/overview/body",
        "/panel/friends/table",
        "/panel/friends/new",
        f"/panel/friends/{friend_id}/subscription",
        f"/panel/friends/{friend_id}/revoke",
    )

    for path in surfaces:
        response = await client.get(path)
        assert response.status_code == 200, path
        assert "friend" not in _visible_text(response.text).lower(), path


async def test_no_sentence_a_service_composes_reaches_the_page_in_the_code_s_words(
    client, monkeypatch
) -> None:
    """The guard, rather than the one message.

    A sentence written in ``services/`` is written in the code's vocabulary by design,
    and any of them can be put in front of the operator. So the boundary translates
    whatever it is handed — this plants a refusal that has never existed and watches
    it arrive on the page in the panel's words.
    """
    async def refuse(session, *, nickname):
        raise Conflict("another friend already holds that nickname")

    monkeypatch.setattr(friends_service, "create_friend", refuse)

    response = await client.post("/panel/friends", data={"nickname": "dima"})

    assert response.status_code == 422
    visible = _visible_text(response.text)
    assert "another user already holds that nickname" in visible
    assert "friend" not in visible.lower()


async def test_a_nickname_that_is_itself_the_code_s_word_is_handed_back_untouched(
    client,
) -> None:
    """The panel translates its OWN words, never the operator's.

    Somebody may be nicknamed ``friend``. "a user called 'user' already exists" would
    be the panel rewriting the operator's data back at them.
    """
    await client.post("/panel/friends", data={"nickname": "friend"})

    duplicate = await client.post("/panel/friends", data={"nickname": "friend"})

    assert duplicate.status_code == 422
    # The nickname survives the crossing, quoted exactly as the service wrote it…
    assert "&#39;friend&#39;" in duplicate.text
    # …while the sentence around it is the panel's.
    assert "a user called" in duplicate.text


@pytest.mark.parametrize(
    "sentence,expected",
    [
        ("a friend called x already exists", "a user called x already exists"),
        ("in every active friend's subscription", "in every active user's subscription"),
        ("friends pick it up on refresh", "users pick it up on refresh"),
        ("Friends are offered this", "Users are offered this"),
        ("both friends' links", "both users' links"),
        # Not the code's word: a longer word that merely starts the same way.
        ("a friendly name", "a friendly name"),
    ],
)
def test_the_boundary_knows_every_shape_of_the_code_s_word(
    sentence: str, expected: str
) -> None:
    assert wording.for_the_page(sentence) == expected


def test_the_boundary_leaves_the_operator_s_own_text_alone() -> None:
    """Two mechanisms, because operator text arrives in two shapes.

    A service quotes it (``{value!r}``), so quotes alone are enough there. A toast the
    panel composes interpolates it bare, and names it with ``keeping``.
    """
    assert (
        wording.for_the_page("a friend called 'friend' already exists")
        == "a user called 'friend' already exists"
    )
    assert wording.for_the_page("friend added", keeping="friend") == "friend added"


async def test_a_status_word_never_breaks_mid_word(client, reality_params) -> None:
    """The regression the long-nickname fix caused, and the rule that ends it.

    ``overflow-wrap: anywhere`` on every cell let ``active`` break into ``activ`` /
    ``e`` on every row of the Users card the moment one 64-character nickname existed
    — a column that may break has a min-content width of one character. Breaking is
    now opt-in, and only a cell carrying the operator's own text opts in.
    """
    rules = _css_rules()

    # The whole allow-list of places a word may be broken, written out so a fourth
    # cannot be added without a reader of this test agreeing to it.
    may_break = {
        selector
        for selector, body in rules.items()
        if "overflow-wrap" in body or "word-break" in body
    }
    assert may_break == {
        ".table td.wraps",              # the operator's own text, in a table…
        ".dialog-title, .dialog-body",  # …and in a dialog that quotes it
        ".dialog-code",                 # the subscription URL: one unbroken token
    }
    # And a status tag is a single word we wrote, wherever it is put.
    assert "nowrap" in rules[".tag"]

    await a_serving_node(client, reality_params)
    longest = "n" * 64
    assert (await client.post("/panel/friends", data={"nickname": longest})).status_code == 200

    for path in ("/panel/friends/table", "/panel/overview/body"):
        body = (await client.get(path)).text
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", body, flags=re.S)
        wrapping = [attrs for attrs, content in cells if "wraps" in attrs]
        assert wrapping, f"{path}: no cell carries the operator's text"
        for attrs, content in cells:
            if 'class="tag' in content:
                assert "wraps" not in attrs, f"{path}: a status cell may not break"
        assert f'<td class="wraps">{longest}</td>' in body, path


async def test_a_failure_does_not_read_like_a_notice(client, reality_params) -> None:
    """A safety property, not a taste one.

    The failure banner and the "no node is serving yet" notice were the same neutral
    frame, stacked one above the other — an operator who reads a failure as an
    informational message believes the action worked. Still no red (UI-PATTERNS §4):
    the weight is the accent ramp, the thick edge and the word.
    """
    await a_serving_node(client, reality_params)
    friend_id = (
        await client.post("/api/friends", json={"nickname": "mira"})
    ).json()["id"]

    # The node has no reachable host, so the revocation is partial — a failure.
    failed = await client.post(f"/panel/friends/{friend_id}/revoke")
    assert "banner-failure" in failed.text
    assert "failed" in _visible_text(failed.text)

    rules = _css_rules()
    assert "background" not in rules[".banner"]
    assert "background" in rules[".banner-failure"]
    assert "accent" in rules[".banner-failure"]


async def test_the_notice_is_the_quiet_one_and_says_which_it_is(client) -> None:
    """The two can be on screen at once, one above the other, which is why they may
    not look alike. Nothing is serving here, so the notice is the one on show."""
    await client.post("/panel/friends", data={"nickname": "mira"})

    table = (await client.get("/panel/friends/table")).text

    assert "No node is serving yet" in table
    assert "banner-failure" not in table
    assert "note" in _visible_text(table)


def test_a_refused_field_does_not_read_like_the_hint_beside_it() -> None:
    """Both sat under the nickname field at 12px in a muted tone, and the refusal
    disappeared into the help text. It is now weighted and edged."""
    rules = _css_rules()

    assert "font-weight" in rules[".field-error"]
    assert "border-left" in rules[".field-error"]
    assert "font-weight" not in rules[".field-hint"]


def test_a_failure_inside_a_dialog_is_stated_inside_that_dialog() -> None:
    """A 5xx during add-user explained itself on the banner BEHIND the modal.

    Asserted in the script because this suite has no browser; the acceptance walk is
    what proves it on screen. The three parts are: the failing element is passed to
    the handler, a dialog around it is found, and the message is put inside it.
    """
    js = _served("app.js")

    assert "showFailure(message, event.detail.elt)" in js
    assert 'origin.closest(".dialog")' in js
    assert "dialogFailure" in js
    # And every failure — banner or dialog — wears the failure frame, not the notice's.
    assert '"banner banner-failure"' in js
    assert 'className = "banner"' not in js


def _visible_text(html: str) -> str:
    """The page with its comments, tags and attributes removed.

    Needed because this codebase explains itself in template comments, and those
    comments legitimately say "friend" — the rule decision 9 sets is about what an
    operator READS, not about what the file contains.
    """
    without_comments = re.sub(r"\{#.*?#\}", "", html, flags=re.S)
    return re.sub(r"<[^>]*>", " ", without_comments)
