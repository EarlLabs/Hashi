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

import re

import pytest

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


def _visible_text(html: str) -> str:
    """The page with its comments, tags and attributes removed.

    Needed because this codebase explains itself in template comments, and those
    comments legitimately say "friend" — the rule decision 9 sets is about what an
    operator READS, not about what the file contains.
    """
    without_comments = re.sub(r"\{#.*?#\}", "", html, flags=re.S)
    return re.sub(r"<[^>]*>", " ", without_comments)
