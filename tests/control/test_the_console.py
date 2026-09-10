"""The redesigned console — the screens M8 and M9 port, and what they may not show.

WHAT: the shell, Overview, Users, Nodes, Hops, the add-user, subscription, add-node,
      establish-hop and tear-down dialogs, the states the design did not draw, and the
      four cells the charter forbids.
WHY:  the design (``design/README.md``) is right about the layout and wrong about
      four cells, because it was drawn without the charter in hand. ``docs/decisions.md``
      decision 6 replaced them. A decision recorded in a document decays; a decision
      with a test over it does not, which is what most of this file is.
HOW:  the in-process client from conftest, already holding an operator session. These
      are ordinary unit tests over rendered HTML — they prove what the templates put
      on screen, not that a browser lays it out, which is what the acceptance walk is
      for.
"""

import html.parser
import json
import pathlib
import re
import typing

import jinja2
import pydantic
import pytest
from sqlalchemy import select

from control.app.api import schemas
from control.app.errors import Conflict, NodeOperationFailed, ParamsRefused
from control.app.models import Credential, Node, NodeTransport, TransportPurpose
from control.app.panel import wording
from control.app.services import apply as apply_service
from control.app.services import console as console_service
from control.app.services import friends as friends_service
from control.app.services import health as health_service
from control.app.services import keymaterial
from control.app.services import nodes as nodes_service
from control.app.services import relay as relay_service
from control.app.services import rotation as rotation_service
from control.app.services import transports as transports_service
from edge.registry import profile

TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "control" / "app" / "templates"

STATIC = pathlib.Path(__file__).resolve().parents[2] / "control" / "app" / "static"

# Jinja's own lexer, so the banner scan below reads a template as markup rather than
# as text. Nothing is ever rendered: the branch this environment cannot take is
# exactly the branch a scan over rendered pages would never look at. The trailing
# newline is kept so that _html_only hands back exactly what it was given.
JINJA = jinja2.Environment(keep_trailing_newline=True)

# A whole opening tag, on any element, quote-aware so that neither a `>` inside an
# attribute value nor an unquoted value can end it early. Group 1 is the element
# name, which _element_body needs to find the matching close.
TAG = re.compile(r"""<([a-zA-Z][a-zA-Z0-9-]*)(?:"[^"]*"|'[^']*'|[^>"'])*>""")

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


# --- Nodes (M9.1) -------------------------------------------------------------

# Every console screen, fragment and dialog M9.1 adds. THE LIST IS THE TEST
# (docs/tracker/M8/step-notes.md): a surface that is not on a list is a surface nothing
# walks, and the runtime half of this rule lives in
# tests/e2e/control/test_the_panel_fetches_nothing_from_a_third_party.py.
NODE_SURFACES = ("/panel/nodes", "/panel/nodes/table", "/panel/nodes/new")


async def test_the_nodes_screen_lists_the_fleet(client, reality_params) -> None:
    """The design's Nodes table: what a node is called, where it exits, what it runs."""
    await a_serving_node(client, reality_params)

    response = await client.get("/panel/nodes")

    assert response.status_code == 200
    body = response.text
    assert "Nodes" in body
    assert "leaf-1" in body
    assert "192.0.2.10" in body
    assert "Testland" in body
    # The transport is named because it is DATA on the row, not because this screen
    # knows any protocol: whatever was enabled is what appears.
    assert "vless-reality" in body
    # UI-PATTERNS §2: the screen's own creation action is secondary, above its table.
    assert "add node" in body


async def test_the_nodes_screen_measures_the_fleet_and_never_the_people(
    client, reality_params
) -> None:
    """Decision 6 on the screen it was written about.

    The design's Nodes table has a "load" column. A node's load is a measurement of the
    people on it, so it is not here and never will be; ``config`` reads drift against
    the digest we last applied, which is a measurement of us.
    """
    await a_serving_node(client, reality_params)

    body = (await client.get("/panel/nodes")).text

    assert ">config<" in body
    assert ">load<" not in body
    assert "never applied" in body
    for cell in FORBIDDEN_CELLS:
        assert cell not in body.lower(), (
            f"the Nodes screen shows {cell!r}, which the charter says must not exist"
        )


async def test_an_empty_nodes_screen_names_the_next_action(client) -> None:
    """M8.6's rule on M9's first screen: a first-time operator meets this one early."""
    body = (await client.get("/panel/nodes")).text

    assert "No nodes yet" in body
    assert "add node" in body
    assert "<table" not in body


async def test_the_overview_sends_a_new_operator_to_the_nodes_screen(client) -> None:
    """The Overview's node links pointed at the pre-redesign page until this screen
    existed. M9.1 creates it, so M9.1 repoints them — a link to the page being retired
    is a link that teaches the operator the wrong route to the job.

    The Overview's BODY, not the whole document: the sidebar still has its honest Fleet
    entry, because hops and the transports table have not moved yet. M9.6 removes that.
    """
    body = (await client.get("/panel/overview/body")).text

    assert 'href="/panel/nodes"' in body
    assert "/panel/fleet" not in body


async def test_a_degraded_node_says_why_on_its_row(client, session) -> None:
    """An unexplained degraded node is a node nobody fixes."""
    from control.app.models import NodeState

    created = await client.post(
        "/api/nodes",
        json={"name": "leaf-2", "address": "192.0.2.12", "location_label": "Testland"},
    )
    await nodes_service.set_node_state(
        session,
        node_id=created.json()["id"],
        state=NodeState.DEGRADED,
        detail="the host refused the key",
    )

    body = (await client.get("/panel/nodes/table")).text

    assert "degraded" in body
    assert "the host refused the key" in body


# --- the add-node dialog ------------------------------------------------------

async def test_the_add_node_dialog_shows_its_defaults_without_naming_them(client) -> None:
    """M9's own rule: no template names a port.

    The two SSH defaults are declared in services/nodes.py and rendered from there, so
    the value the form suggests and the value the service applies to an empty box are
    the same one — and changing it is a change in one place.
    """
    dialog = await client.get("/panel/nodes/new")

    assert dialog.status_code == 200
    assert "Add a node" in dialog.text
    assert f'placeholder="{nodes_service.DEFAULT_SSH_PORT}"' in dialog.text
    assert f'placeholder="{nodes_service.DEFAULT_SSH_USER}"' in dialog.text
    # …and the template it came from names neither. Comments stripped first: this
    # repository explains itself in prose, and the prose legitimately carries numbers.
    source = re.sub(
        r"\{#.*?#\}",
        "",
        (TEMPLATES / "panel" / "add_node_dialog.html").read_text(),
        flags=re.S,
    )
    assert str(nodes_service.DEFAULT_SSH_PORT) not in source
    assert nodes_service.DEFAULT_SSH_USER not in source


async def test_adding_a_node_names_it_and_refreshes_the_table(client) -> None:
    """The console's answer: the dialog closes, a toast names the node, the list
    re-fetches itself. And what it says is what a draft node actually is."""
    response = await client.post(
        "/panel/nodes",
        data={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Add a node" not in response.text
    assert "leaf-1 added — a draft until you apply it" in response.text
    assert "nodes-changed" in response.headers.get("HX-Trigger", "")

    listed = (await client.get("/api/nodes")).json()
    assert [node["name"] for node in listed] == ["leaf-1"]
    assert listed[0]["state"] == "draft"


async def test_the_pre_redesign_form_still_gets_its_redirect(client) -> None:
    """/panel/fleet's plain form posts to this same route and must keep working.

    The old page is not deleted until M9.6, and until then it is the only home for
    hops, for the transports table and for half the per-node actions. A browser POST
    gets a 303 so a reload does not re-post; the console asks with htmx and gets the
    console's answer. Deleting this branch before the page is what would break it.
    """
    response = await client.post(
        "/panel/nodes",
        data={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/panel/fleet"


async def test_a_refused_node_comes_back_on_the_field_with_what_was_typed(
    client,
) -> None:
    """M8.6 field-level validation, on a dialog with seven fields instead of one."""
    payload = {
        "name": "leaf-1",
        "address": "192.0.2.10",
        "location_label": "Testland",
        "ssh_user": "operator",
    }
    await client.post("/panel/nodes", data=payload, headers={"HX-Request": "true"})

    duplicate = await client.post(
        "/panel/nodes", data=payload, headers={"HX-Request": "true"}
    )

    assert duplicate.status_code == 422
    assert "already exists" in duplicate.text
    assert 'aria-invalid="true"' in duplicate.text
    # Still the add dialog, with everything the operator typed still in it.
    assert "Add a node" in duplicate.text
    for value in ("leaf-1", "192.0.2.10", "Testland", "operator"):
        assert f'value="{value}"' in duplicate.text
    assert len((await client.get("/api/nodes")).json()) == 1


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("name", "", "required"),
        ("address", "", "required"),
        ("location_label", "", "required"),
        ("name", "n" * 65, "64 characters or fewer"),
        ("ssh_port", "not-a-number", "a whole number"),
    ],
)
async def test_a_node_that_cannot_be_stored_is_refused_with_a_sentence(
    client, field: str, value: str, expected: str
) -> None:
    """The defect M8 fixed for a nickname, closed here before it can happen.

    Without this the panel trusted the form and an over-long name reached the column,
    coming back as an opaque 500. The limits are the API schema's own — checked here
    through that same model, so the two surfaces cannot drift about what a node is.
    """
    payload = {
        "name": "leaf-1",
        "address": "192.0.2.10",
        "location_label": "Testland",
        field: value,
    }

    response = await client.post(
        "/panel/nodes", data=payload, headers={"HX-Request": "true"}
    )

    assert response.status_code == 422
    assert expected in response.text
    assert (await client.get("/api/nodes")).json() == []


async def test_the_private_key_never_comes_back_out_of_the_dialog(client) -> None:
    """The one key the panel accepts is write-only.

    Every other field is refilled when the dialog comes back, because retyping them is
    the annoyance that makes an operator paste from somewhere worse. The key is not:
    putting submitted key material back into markup would make the panel a place key
    material appears, which is the one thing CLAUDE.md says it must never become.
    """
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nnot-a-real-key\n"
    payload = {
        "name": "leaf-1",
        "address": "192.0.2.10",
        "location_label": "Testland",
        "ssh_private_key": key,
    }
    await client.post("/panel/nodes", data=payload, headers={"HX-Request": "true"})

    duplicate = await client.post(
        "/panel/nodes", data=payload, headers={"HX-Request": "true"}
    )

    assert duplicate.status_code == 422
    assert "not-a-real-key" not in duplicate.text
    assert "BEGIN OPENSSH PRIVATE KEY" not in duplicate.text


async def test_a_dropped_key_says_so_at_the_moment_it_is_dropped(client) -> None:
    """A silent trap, closed where it happens.

    Emptying the box is right. Saying so only in the static hint is not: the operator
    whose NAME was refused is reading the message under the name, fixes it, resubmits,
    and registers a node with no key at all — which surfaces much later as an apply
    that cannot connect and reads as a broken host.

    And it is said only when there was something to drop. "Your key was not kept" about
    a key that was never pasted is a second confusion in place of the first.
    """
    payload = {
        "name": "leaf-1",
        "address": "192.0.2.10",
        "location_label": "Testland",
    }
    await client.post("/panel/nodes", data=payload, headers={"HX-Request": "true"})

    with_key = await client.post(
        "/panel/nodes",
        data={**payload, "ssh_private_key": "not-a-real-key"},
        headers={"HX-Request": "true"},
    )
    without_key = await client.post(
        "/panel/nodes", data=payload, headers={"HX-Request": "true"}
    )

    assert with_key.status_code == 422
    assert "was not kept" in with_key.text
    assert "not-a-real-key" not in with_key.text
    assert without_key.status_code == 422
    assert "was not kept" not in without_key.text


# --- applying and probing from the console ------------------------------------

async def test_applying_a_node_names_it_in_a_toast(client, monkeypatch) -> None:
    """UI-PATTERNS §8's own example: `config applied to fra-1`, not `Success!`.

    The push itself is monkeypatched — there is no host behind a node in this suite,
    and what is under test is what the console does with the answer.
    """
    node_id = (
        await client.post(
            "/api/nodes",
            json={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
        )
    ).json()["id"]

    async def applied(session, *, node_id):
        return {"vless-reality": "config"}

    monkeypatch.setattr(apply_service, "apply_node", applied)

    response = await client.post(f"/panel/nodes/{node_id}/push")

    assert response.status_code == 200
    assert "config applied to leaf-1" in response.text
    assert "nodes-changed" in response.headers.get("HX-Trigger", "")


async def test_a_failed_apply_stays_on_screen_in_plain_words(client, monkeypatch) -> None:
    """The outcome a toast must not carry, and M9's acceptance walk in one test.

    Applying fails on a stand with no real host behind the node. A failed apply marks
    the node degraded, so the reason has to still be readable while the operator acts
    on it — a message that removes itself after 2200ms is the wrong carrier, and a raw
    error or a blank page is worse than either.
    """
    node_id = (
        await client.post(
            "/api/nodes",
            json={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
        )
    ).json()["id"]

    async def refuse(session, *, node_id):
        raise NodeOperationFailed("this node has no SSH key, so nothing could be pushed")

    monkeypatch.setattr(apply_service, "apply_node", refuse)

    response = await client.post(f"/panel/nodes/{node_id}/push")

    assert response.status_code == 200
    assert 'hx-swap-oob="innerHTML:#banner-slot"' in response.text
    assert "banner-failure" in response.text
    assert "no SSH key" in response.text
    assert "toast" not in response.text


@pytest.mark.parametrize(
    "healthy,reachable,detail,carrier",
    [
        (True, True, None, "toast"),
        (False, False, "the node did not answer", "banner"),
    ],
)
async def test_a_probe_answers_in_the_carrier_its_answer_deserves(
    client, monkeypatch, healthy: bool, reachable: bool, detail: str | None, carrier: str
) -> None:
    """Good news disappears; a fault does not.

    A node that cannot be reached, or one running a configuration older than the file
    on it, is something the operator has to still be able to read while they fix it.
    """
    node_id = (
        await client.post(
            "/api/nodes",
            json={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
        )
    ).json()["id"]

    async def probed(session, *, node_id):
        return schemas.HealthResponse(
            node_id=node_id,
            reachable=reachable,
            healthy=healthy,
            running=["vless-reality"] if healthy else [],
            missing=[],
            drifted=[],
            stale=[],
            detail=detail,
        )

    monkeypatch.setattr(health_service, "check_node", probed)

    response = await client.post(f"/panel/nodes/{node_id}/probe")

    assert response.status_code == 200
    assert "leaf-1" in response.text
    if carrier == "toast":
        assert "is serving" in response.text
        assert "banner-failure" not in response.text
    else:
        assert "banner-failure" in response.text
        assert "the node did not answer" in response.text
        assert "toast" not in response.text


async def test_no_probe_answer_says_anything_about_who_connected(
    client, monkeypatch
) -> None:
    """Health means "is this node serving what we told it to", on every screen.

    The value does not exist upstream, which is the real guarantee; this holds the
    console's own sentence to it, because a summary is exactly where somebody would
    one day add "and 4 clients".
    """
    node_id = (
        await client.post(
            "/api/nodes",
            json={"name": "leaf-1", "address": "192.0.2.10", "location_label": "Testland"},
        )
    ).json()["id"]

    async def probed(session, *, node_id):
        return schemas.HealthResponse(
            node_id=node_id,
            reachable=True,
            healthy=False,
            running=["vless-reality"],
            missing=[],
            drifted=[],
            stale=["vless-reality"],
            detail="a container is up on an older configuration",
        )

    monkeypatch.setattr(health_service, "check_node", probed)

    body = (await client.post(f"/panel/nodes/{node_id}/probe")).text

    for cell in (*FORBIDDEN_CELLS, "client", "connected"):
        assert cell not in _visible_text(body).lower()


def test_no_console_template_names_a_transport_a_country_an_address_or_a_port() -> None:
    """M9's own done-when, held over every console template rather than the new ones.

    A hardcoded value is a node you cannot rotate away from (CLAUDE.md), and a template
    is where one hides best: it is not code, so no zone invariant reads it, and it is
    not configuration, so nobody looks for it there. The shapes checked are the ones
    these values actually take in markup — a dotted quad, a literal in a `value` or
    `placeholder` attribute, a `:port` suffix, a country, an installed transport's own
    name. The pre-redesign pages under templates/pages are deliberately not scanned:
    they carry all four and M9.6 deletes them.
    """
    from edge.registry import discover

    address = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
    port = re.compile(r'(?:value|placeholder)\s*=\s*"\s*\d+\s*"|:\d{2,5}\b')
    country = re.compile(
        r"\b(?:Netherlands|Germany|Iceland|Finland|Russia|Amsterdam|Frankfurt)\b",
        re.IGNORECASE,
    )
    named = tuple(discover())

    offenders = []
    for path in sorted((TEMPLATES / "panel").rglob("*.html")):
        markup = re.sub(r"\{#.*?#\}", "", path.read_text(), flags=re.S)
        for pattern in (address, port, country):
            offenders += [f"{path.name}: {found}" for found in pattern.findall(markup)]
        offenders += [f"{path.name}: {name}" for name in named if name in markup]

    assert offenders == [], (
        f"a console template names a value that belongs in a node record: {offenders}"
    )


# --- Hops (M9.2) --------------------------------------------------------------

# THE LIST IS THE TEST. Every hop surface, so the decision-9 sweep below walks them
# and a later screen cannot quietly drop one. The tear-down dialog needs a hop and is
# added to that sweep separately.
HOP_SURFACES = ("/panel/hops", "/panel/hops/table", "/panel/hops/new")

# The three questions the design says this dialog may ask, in the order it asks them.
# Written out rather than derived, because THIS is the claim: a later screen that adds
# a fourth question has to change this line, in front of a reviewer.
THE_THREE_QUESTIONS = ("entry_node_id", "leaf_node_id", "transport_name")


def a_hop_transport() -> str:
    """Whichever installed transport may carry a hop. Never a literal.

    The suite discovers it the same way the panel does, so this file does not become
    the place a protocol name is written down — and a fleet whose hop transport is
    replaced does not need this file edited.
    """
    installed = transports_service.hop_transports()
    assert installed, "this image ships nothing that can carry a hop"
    return installed[0]


def hop_side(address: str, peer: str, port: int = 51820) -> dict:
    """One end's operator-supplied parameters, as the API takes them.

    The same block ``tests/e2e/control/test_a_hop_never_reaches_a_friend.py`` uses.
    RFC 5737 documentation addresses are not private, so the tunnel addresses are
    RFC 1918 — the transport's own model refuses a public range, for the reason it
    states there.
    """
    return {
        "port": port,
        "tunnel_address": address,
        "peer_tunnel_address": peer,
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 80,
        "init_packet_magic_header": 1020327352,
        "response_packet_magic_header": 2060487442,
        "underload_packet_magic_header": 3679305607,
        "transport_packet_magic_header": 1436947798,
    }


async def two_nodes(client) -> tuple[str, str]:
    """An entry and a leaf. Named so they cannot collide with ``a_serving_node``'s,
    which the decision-9 sweep creates in the same database."""
    ids = []
    for name, address, label in (
        ("entry-1", "192.0.2.20", "Entryland"),
        ("exit-1", "192.0.2.10", "Exitland"),
    ):
        created = await client.post(
            "/api/nodes",
            json={"name": name, "address": address, "location_label": label},
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    return ids[0], ids[1]


async def a_hop(client) -> str:
    """One established hop. Returns the ENTRY end's id, which is what addresses it."""
    entry_id, leaf_id = await two_nodes(client)
    created = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": a_hop_transport(),
            "entry_params": hop_side("10.44.0.1/24", "10.44.0.2/24"),
            "leaf_params": hop_side("10.44.0.2/24", "10.44.0.1/24"),
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["entry"]["id"]


class _Controls(html.parser.HTMLParser):
    """Every named form control in a document, and whether it is behind a disclosure.

    Written here rather than pulled in, because adding a dependency to `control`'s test
    path is an architect decision and the stdlib parser is enough: this reads RENDERED
    markup, not a template, so none of the Jinja that defeats it is present.

    ``opened`` collects the disclosures that carry the ``open`` ATTRIBUTE, by the group
    they belong to. Read as an attribute and not as a substring: `" open" in document`
    matches the word anywhere in any prose the dialog happens to contain, so it would
    pass a refusal that came back behind a shut summary the day someone writes a
    sentence with "open" in it — which this dialog now does.

    ``visible`` is the same idea for ``hidden``: which groups a browser would actually
    draw. With one carrier installed every rule looks alike, so this is read rather
    than assumed.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.controls: list[tuple[str, dict, bool]] = []
        self.opened: set[str] = set()
        self.visible: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "details":
            self._depth += 1
            if "open" in attributes:
                self.opened.add(attributes.get("data-transport-group", ""))
            if "hidden" not in attributes:
                self.visible.append(attributes.get("data-transport-group", ""))
        if tag in {"input", "select", "textarea"} and attributes.get("name"):
            self.controls.append((attributes["name"], attributes, self._depth > 0))

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "details" and self._depth:
            self._depth -= 1


def _read(markup: str) -> _Controls:
    parser = _Controls()
    parser.feed(markup)
    return parser


def _form_controls(markup: str) -> list[tuple[str, dict, bool]]:
    return _read(markup).controls


def _described(response, kind: str, prefix: str = "hop") -> dict[str, str]:
    """Each row's hint or error, by the control it belongs to.

    Read off the id the macro wires into ``aria-describedby``, so this asserts the
    thing a screen reader is actually handed rather than a div that happens to sit
    nearby. ``prefix`` is the dialog's own id prefix — M9.4's replace-parameters form
    wires its boxes the same way under ``param-``, and one reader for both is what
    stops the second dialog's wiring from being asserted more loosely than the first's.
    """
    return {
        name: html.unescape(re.sub(r"\s+", " ", text)).strip()
        for name, text in re.findall(
            rf'id="{prefix}-([^"]+)-{kind}"[^>]*>(.*?)</div>', response.text, re.S
        )
    }


def _hints(response) -> dict[str, str]:
    return _described(response, "hint")


def _field_errors(response) -> dict[str, str]:
    return _described(response, "error")


async def test_the_hops_screen_lists_the_fleet_s_tunnels(client) -> None:
    """design/README.md §4: entry, leaf, transport, state, established, tear down."""
    await a_hop(client)

    response = await client.get("/panel/hops")

    assert response.status_code == 200
    body = response.text
    assert "Hops" in body
    assert "entry-1" in body and "exit-1" in body
    # The transport is named because it is DATA on the row, not because this screen
    # knows any protocol: whatever carries the hop is what appears.
    assert a_hop_transport() in body
    # Neither end has been applied, so the hop is not established and must not say it
    # is — nothing is carrying traffic until both nodes are pushed.
    assert "pending" in body
    assert "not yet — apply both nodes" in body
    assert "establish hop" in body
    assert "tear down" in body


async def test_an_empty_hops_screen_says_what_no_hop_means(client) -> None:
    """A first-time operator meets this one before they have two nodes."""
    body = (await client.get("/panel/hops")).text

    assert "No hops yet" in body
    assert "establish hop" in body
    assert "<table" not in body


async def test_the_hops_screen_measures_the_fleet_and_never_the_people(client) -> None:
    """Decision 6 on a screen it was not written about, which is the point of it."""
    await a_hop(client)

    body = (await client.get("/panel/hops")).text.lower()

    for cell in FORBIDDEN_CELLS:
        assert cell not in body, (
            f"the Hops screen shows {cell!r}, which the charter says must not exist"
        )
    assert "throughput" not in body


async def test_establishing_a_hop_asks_three_questions(client) -> None:
    """M9's own done-when, held mechanically rather than by looking at a screenshot.

    "Asks three questions" is not a claim about how the dialog LOOKS. It is a claim
    about where its form controls are: exactly three outside the disclosure, and every
    other parameter — both ends of them — inside one. A later screen that adds a fourth
    question, or that lifts one knob out of the disclosure "just this once", fails
    here, which is the only way this claim survives four more screens.
    """
    await two_nodes(client)
    transport = a_hop_transport()

    dialog = await client.get("/panel/hops/new")

    assert dialog.status_code == 200
    assert "Establish a hop" in dialog.text
    controls = _form_controls(dialog.text)

    outside = [name for name, _, behind in controls if not behind]
    assert tuple(outside) == THE_THREE_QUESTIONS, (
        f"the hop dialog asks {len(outside)} questions before the disclosure: {outside}"
    )

    # And every remaining parameter is inside it, for BOTH ends — a hop's two ends are
    # not interchangeable, so one shared set of boxes would be a different bug. Over
    # EVERY hop-capable transport, because the dialog renders a group per transport and
    # hides all but the chosen one: expecting only the first one's boxes would fail
    # against a correct dialog the day a second carrier ships.
    inside = {name for name, _, behind in controls if behind}
    expected = {
        f"{side}-{parameter.name}"
        for side in ("entry", "leaf")
        for carrier in transports_service.hop_transports()
        for parameter in transports_service.hop_tuning(carrier)
    }
    assert inside == expected

    # The summary is what an operator sees while the disclosure is SHUT, so it carries
    # both numbers: how many boxes there are, and how many of them this transport
    # declares no default for. Derived from the transport, so it cannot go stale.
    boxes = transports_service.hop_tuning(transport)
    must_fill = [parameter for parameter in boxes if parameter.required]
    assert f"advanced tuning — {len(boxes)} parameters per end" in dialog.text
    assert f"{len(must_fill)} of them required by this transport" in dialog.text
    # …and the same warning survives with the disclosure closed, in the dialog's body.
    assert "Open advanced tuning before you submit" in dialog.text


async def test_every_tuning_box_says_what_its_own_transport_declares(client) -> None:
    """The other half of the claim: an empty box has to mean something visible.

    A placeholder that is ABSENT leaves the operator with a bare box and no way to
    know what it takes; one that shows a value the transport would not actually use is
    worse, because it reads as a promise the form does not keep. So every box carries
    the transport's own declaration, and this test recomputes what that is from the
    model rather than from the function under test.
    """
    await two_nodes(client)
    transport = a_hop_transport()
    fields = profile(transport).params_model.model_fields

    dialog = await client.get("/panel/hops/new")
    behind = {
        name: attrs for name, attrs, is_behind in _form_controls(dialog.text) if is_behind
    }
    assert behind, "nothing is behind the disclosure at all"

    described = _hints(dialog)

    for name, attrs in behind.items():
        parameter = name.split("-", 1)[1]
        info = fields[parameter]
        placeholder = attrs.get("placeholder", "")
        # Either string may carry the guidance — a value goes in the box, prose goes
        # under the row where it can be read — but a box that says NEITHER leaves the
        # operator with no way to know what it takes.
        assert placeholder or described.get(name), (
            f"{name} carries neither a placeholder nor a hint, so an empty box says "
            "nothing at all"
        )

        if not info.is_required():
            # The transport declares a default, so the box may promise it — and the
            # promise is kept: an empty box is dropped before the model sees it
            # (services/transports.py:parse_form) and the model fills it with this.
            default = info.get_default(call_default_factory=True)
            expected = (
                (", ".join(str(item) for item in default) or "none")
                if isinstance(default, (list, tuple, set, frozenset))
                else str(default)
            )
            assert placeholder == expected, name
            continue

        # No default to promise, so a placeholder — if there is one — is the range the
        # field or its transport declared, and every number in it has to come from one
        # of those two. Never from a value written into a template.
        declared = {
            str(getattr(constraint, edge, None))
            for constraint in info.metadata
            for edge in ("ge", "le", "gt", "lt")
        }
        declared |= {str(bound) for bound in profile(transport).meta.port_range}
        for number in re.findall(r"\d+", placeholder):
            assert number in declared, (
                f"{name}'s placeholder shows {number}, which its transport declares "
                "nowhere"
            )

        # And where the transport describes the field, that description reaches the
        # operator IN FULL, under the row, rather than being truncated inside a 136px
        # box — these are the two longest strings in the form and the two fields most
        # easily got wrong.
        if info.description:
            assert described.get(name) == info.description.strip(), name


def _render_hop_dialog(**context) -> str:
    """The establish-hop dialog rendered directly, so a second carrier can be tried.

    One hop-capable transport ships today, and every rule about "which group is shown"
    looks correct with one. This renders the real template against a synthetic fleet of
    two — no application, no database — because the day a second carrier lands is
    exactly when nobody re-reads this file.
    """
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True
    )
    return environment.get_template("panel/establish_hop_dialog.html").render(
        {
            "nodes": [],
            "sides": (
                {"prefix": "entry", "label": "entry end", "note": "dials"},
                {"prefix": "leaf", "label": "leaf end", "note": "listens"},
            ),
            "values": {},
            "errors": {},
            "failure": None,
            "open_tuning": False,
            **context,
        }
    )


TWO_CARRIERS = {
    "alpha": (transports_service.TuningField("a", "0–1", "", None),),
    "beta": (
        transports_service.TuningField("b", "0–1", "", None),
        transports_service.TuningField("c", "0–1", "", None),
    ),
}


@pytest.mark.parametrize(
    "chosen,shown",
    [
        ({}, "alpha"),                              # nothing chosen yet: the first
        ({"transport_name": "beta"}, "beta"),       # …the chosen one, not the first
        ({"transport_name": "gone"}, "alpha"),      # …a transport no longer installed
    ],
)
def test_exactly_one_transport_s_tuning_is_ever_on_screen(chosen, shown) -> None:
    """Two visible disclosures state two different counts, and the dialog's own body
    says "the summary above says how many" — which, with two summaries above, names
    neither. The claim this whole screen rests on is a count, so it cannot be allowed
    to have two answers.
    """
    markup = _render_hop_dialog(
        transports=sorted(TWO_CARRIERS), tuning=TWO_CARRIERS, values=chosen
    )

    assert _read(markup).visible == [shown]


async def test_a_mistyped_value_is_refused_under_the_box_it_was_typed_in(
    client,
) -> None:
    """The other mistake a rotation produces, and it is not an empty box.

    The transport's own model refuses a value per field, and this form has a box for
    each of them. Flattened into one sentence at the top — which is what a plain
    ``DomainError`` would give — the operator scrolls twenty-four boxes hunting for the
    parameter the prose names. What they get instead is the transport's own sentence
    under the box, with neither the database's word for the end (``relay-entry``) nor
    Pydantic's label for its own internals (``Value error,``) in it.
    """
    entry_id, leaf_id = await two_nodes(client)
    transport = a_hop_transport()

    for prefix, other in (("entry", "leaf"), ("leaf", "entry")):
        form = {
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": transport,
        }
        for side, address, peer in (
            ("entry", "10.44.0.1/24", "10.44.0.2/24"),
            ("leaf", "10.44.0.2/24", "10.44.0.1/24"),
        ):
            for key, value in hop_side(address, peer).items():
                form[f"{side}-{key}"] = str(value)
        # One digit off RFC 1918 — the mistake a rotation actually produces — and a
        # public range, which the transport refuses out loud: it would route the node's
        # own traffic into the tunnel. (The documentation ranges every other fixture
        # here uses are `is_private` to Python's ipaddress, so they pass.)
        form[f"{prefix}-tunnel_address"] = "172.15.0.1/24"

        response = await client.post(
            "/panel/hops/establish", data=form, headers={"HX-Request": "true"}
        )

        assert response.status_code == 422
        controls = {name: attrs for name, attrs, _ in _form_controls(response.text)}
        assert controls[f"{prefix}-tunnel_address"].get("aria-invalid") == "true", prefix
        # …and only that one. A refusal that marks both ends teaches the operator to
        # ignore the marking.
        invalid = [
            name for name, attrs in controls.items() if attrs.get("aria-invalid")
        ]
        assert invalid == [f"{prefix}-tunnel_address"], invalid

        refusals = _field_errors(response)
        assert "is not a private address" in refusals.get(
            f"{prefix}-tunnel_address", ""
        ), refusals
        # The transport's own sentence, whole — including the reason, which is the part
        # that stops the operator retyping the same thing.
        assert "route the node's own traffic into the tunnel" in refusals[
            f"{prefix}-tunnel_address"
        ]
        # Neither the column's word for the end nor Pydantic's word for itself.
        assert "relay-entry" not in response.text
        assert "relay-leaf" not in response.text
        assert "Value error" not in response.text
        # The far end keeps what was typed in it.
        assert controls[f"{other}-tunnel_address"].get("value")
        assert _read(response.text).opened == {transport}

    assert (await client.get("/api/hops")).json() == []


async def test_a_refusal_with_no_box_to_land_on_is_still_read(client) -> None:
    """The fallback that cannot be seen while it works.

    A complaint about a parameter this dialog does not render has nowhere to go, and a
    message addressed to a box that does not exist is a message nobody reads. It is
    stated above the form instead — asserted here by driving the mapping directly,
    because reaching it through a transport would mean shipping one that refuses a
    field it never offers.
    """
    from control.app.errors import HopEndRefused
    from control.app.panel import routes

    tuning = transports_service.hop_tuning(a_hop_transport())
    placed = routes._on_their_boxes(
        HopEndRefused(
            "flattened",
            purpose=str(TransportPurpose.RELAY_LEAF),
            fields={"mtu": "too small", "nothing_we_render": "also wrong"},
        ),
        tuning,
    )

    assert placed["errors"] == {"leaf-mtu": "too small"}
    assert "nothing_we_render: also wrong" in placed["failure"]
    assert "leaf end was refused" in placed["failure"]


async def test_the_hop_dialog_never_asks_for_key_material(client) -> None:
    """A hop mints keys at both ends, and the panel must not become where they surface.

    Absent by construction rather than by omission: the list comes from
    ``operator_params``, which subtracts everything the transport declared as key
    material — including the public counterpart of a secret, which is derived and never
    typed. The value the two ends must share is minted once for both
    (``KeySpec.shared_between_peers``), so there is nothing here for an operator to
    keep consistent by hand and nothing to type.
    """
    await two_nodes(client)
    transport = a_hop_transport()
    minted = set()
    for spec in profile(transport).meta.key_material:
        minted.add(spec.name)
        if spec.public_name:
            minted.add(spec.public_name)
    assert minted, "this transport declares no key material, so this proves nothing"

    dialog = await client.get("/panel/hops/new")

    asked = {
        name.split("-", 1)[-1] for name, _, _ in _form_controls(dialog.text)
    }
    assert not (asked & minted), f"the hop dialog asks for key material: {asked & minted}"
    for name in minted:
        assert name not in dialog.text, f"{name} is named in the hop dialog"


async def test_establishing_a_hop_names_what_is_left_to_do(client) -> None:
    """The console's answer: the dialog closes, a toast says the hop is not up YET.

    "hop established" would be the panel telling the operator a tunnel is carrying
    traffic when nothing has been pushed to either host — UI-PATTERNS §8 asks an action
    with a delayed real-world effect to say so.
    """
    entry_id, leaf_id = await two_nodes(client)
    form = {
        "entry_node_id": entry_id,
        "leaf_node_id": leaf_id,
        "transport_name": a_hop_transport(),
    }
    for side, address, peer in (
        ("entry", "10.44.0.1/24", "10.44.0.2/24"),
        ("leaf", "10.44.0.2/24", "10.44.0.1/24"),
    ):
        for key, value in hop_side(address, peer).items():
            form[f"{side}-{key}"] = str(value)

    response = await client.post(
        "/panel/hops/establish", data=form, headers={"HX-Request": "true"}
    )

    assert response.status_code == 200, response.text
    assert "Establish a hop" not in response.text
    assert "hop establishing — apply both nodes to bring it up" in response.text
    triggered = response.headers.get("HX-Trigger", "")
    assert "hops-changed" in triggered
    # The Nodes screen tags a hop end on both of its nodes, so its table refreshes too.
    assert "nodes-changed" in triggered

    listed = (await client.get("/api/hops")).json()
    assert len(listed) == 1
    assert listed[0]["entry"]["node_id"] == entry_id


async def test_a_box_left_empty_is_refused_under_that_box(client) -> None:
    """Twenty-two parameters cannot be corrected from one sentence at the top.

    Per field, at 422, with everything else the operator typed still in the form —
    which is the pattern M9.1 set and the one status static/app.js allows to swap.
    """
    entry_id, leaf_id = await two_nodes(client)
    transport = a_hop_transport()
    # A box the transport declares no default for — one it defaults would be correctly
    # accepted empty, which is a different test.
    parameter = next(
        box.name for box in transports_service.hop_tuning(transport) if box.required
    )

    form = {
        "entry_node_id": entry_id,
        "leaf_node_id": leaf_id,
        "transport_name": transport,
    }
    for side, address, peer in (
        ("entry", "10.44.0.1/24", "10.44.0.2/24"),
        ("leaf", "10.44.0.2/24", "10.44.0.1/24"),
    ):
        for key, value in hop_side(address, peer).items():
            form[f"{side}-{key}"] = str(value)
    kept = form[f"leaf-{parameter}"]
    form[f"entry-{parameter}"] = ""

    response = await client.post(
        "/panel/hops/establish", data=form, headers={"HX-Request": "true"}
    )

    assert response.status_code == 422
    assert "Establish a hop" in response.text
    controls = {name: attrs for name, attrs, _ in _form_controls(response.text)}
    assert controls[f"entry-{parameter}"].get("aria-invalid") == "true"
    # The far end's value is untouched: a refusal about one box may not empty another.
    assert controls[f"leaf-{parameter}"].get("value") == kept
    # …and the disclosure comes back OPEN, or the message is behind a shut summary.
    # The attribute on the chosen transport's own group, not the word anywhere in the
    # document — the dialog's own body now contains "Open advanced tuning…".
    assert _read(response.text).opened == {transport}

    assert (await client.get("/api/hops")).json() == []


async def test_a_pair_that_would_not_form_a_tunnel_is_refused_in_the_dialog(
    client,
) -> None:
    """Everything ``edge.relay`` refuses is about the PAIR, so it has no field.

    Two ends on different tunnel networks render as two perfectly valid files and no
    tunnel, which is why it is refused before either row is written. The operator reads
    it beside what they typed rather than as an error page.
    """
    entry_id, leaf_id = await two_nodes(client)
    form = {
        "entry_node_id": entry_id,
        "leaf_node_id": leaf_id,
        "transport_name": a_hop_transport(),
    }
    for side, address, peer in (
        ("entry", "10.44.0.1/24", "10.44.0.2/24"),
        ("leaf", "10.99.0.2/24", "10.99.0.1/24"),
    ):
        for key, value in hop_side(address, peer).items():
            form[f"{side}-{key}"] = str(value)

    response = await client.post(
        "/panel/hops/establish", data=form, headers={"HX-Request": "true"}
    )

    assert response.status_code == 422
    assert "different tunnel networks" in response.text
    # Stated as a refusal, in the dialog the operator is looking at.
    assert 'class="field-error" role="alert"' in response.text
    assert (await client.get("/api/hops")).json() == []


async def test_tearing_down_a_hop_confirms_first_then_says_what_is_left(client) -> None:
    """UI-PATTERNS §3, and decision 3 stated where it can still be acted on.

    The confirmation says what the operator will see afterwards — an entry node that
    fails CLOSED reads from the outside exactly like a node that has stopped working —
    because that is the sentence they need before they press it, not after.
    """
    entry_end = await a_hop(client)

    confirmation = await client.get(f"/panel/hops/{entry_end}/tear-down")

    assert confirmation.status_code == 200
    assert "Tear down this hop?" in confirmation.text
    assert "entry-1" in confirmation.text and "exit-1" in confirmation.text
    assert "no exit at all" in confirmation.text

    done = await client.post(
        f"/panel/hops/{entry_end}/tear-down", headers={"HX-Request": "true"}
    )

    assert done.status_code == 200
    assert "hop torn down — re-apply 2 nodes" in done.text
    assert "hops-changed" in done.headers.get("HX-Trigger", "")
    assert (await client.get("/api/hops")).json() == []


def test_a_box_promises_a_default_only_when_its_transport_declares_one() -> None:
    """The rule ``tuning_field`` applies, over a model this suite writes itself.

    The dialog above exercises this branch through exactly one shipped field, so the
    rule that matters most is nearly uncovered by it: ``docs/decisions.md``
    (2026-09-10) records that no transport declares a default for a hop parameter it
    REQUIRES, and that none may be manufactured in `control`. This is what happens the
    day one does — which is the correction that entry points at — written against a
    model of this test's own so the branch holds whatever the image ships.
    """
    from pydantic import BaseModel, Field

    class Model(BaseModel):
        bounded: int = Field(ge=2, le=9)
        floor_only: int = Field(gt=4)
        described: str = Field(description="what this one takes")
        defaulted: int = 7
        listed: tuple[str, ...] = ()
        unbounded: int

    fields = Model.model_fields
    port_range = (1024, 65535)

    def box(name):
        return transports_service.tuning_field(name, fields[name], port_range)

    assert box("bounded").placeholder == "2–9"
    assert box("bounded").required
    # `gt` is not `ge`: the first value the field accepts is the one after it.
    assert box("floor_only").placeholder == "5 or more"
    # A description is the ROW's hint and never the box's text: 136px truncates it, and
    # guidance the operator cannot read is guidance they do not have.
    assert box("described").placeholder == ""
    assert box("described").hint == "what this one takes"
    # A declared default is the one case where the placeholder is a promise, so it is
    # also the one case where it must be the value the transport would actually use.
    assert box("defaulted").placeholder == "7"
    assert not box("defaulted").required
    assert box("defaulted").default == "7"
    # A declared "none of these" is a real state and has to read as one rather than as
    # a box nobody filled in.
    assert box("listed").placeholder == "none"
    # Nothing declared and nothing to fall back on — the transport's problem, said out
    # loud rather than papered over here.
    assert box("unbounded").placeholder == ""
    assert box("unbounded").hint == ""


def test_the_port_is_the_one_field_name_the_console_knows() -> None:
    """And it belongs to the hop contract rather than to any protocol.

    ``edge.relay.endpoint_of`` builds the address the far end dials out of
    ``params["port"]`` and ``TransportMeta.port_range`` is what a transport may listen
    on; joining those is what lets the one box with no bounds of its own still say what
    it takes. Held as a test because it is the single place `control` reads a parameter
    by name, and a second one must not appear without somebody noticing.
    """
    from pydantic import BaseModel

    class Model(BaseModel):
        port: int

    assert transports_service.PORT_FIELD == "port"
    assert transports_service.tuning_field(
        "port", Model.model_fields["port"], (1024, 65535)
    ).placeholder == "1024–65535"


# --- Transports (M9.3) --------------------------------------------------------

# THE LIST IS THE TEST, and this screen contributes exactly one entry. It has no
# dialog and no self-swapping fragment: nothing this panel can do changes which
# protocols the image ships, so a refresh URL here would exist only to be listed.
TRANSPORT_SURFACES = ("/panel/transports",)


def _identified() -> list[str]:
    """Whichever installed transports declare themselves identified on the wire.

    Discovered, never a literal — the same rule as ``a_hop_transport``. A test that
    named the protocol would be the branch this whole screen exists to avoid, and it
    would go green for the wrong reason the day that package is replaced.
    """
    from edge.registry import discover

    return sorted(
        name for name, meta in discover().items() if meta.blocked_by_inspection
    )


def _reading(markup: str) -> str:
    """``_visible_text`` with entities turned back into what a person actually reads.

    The sentences on this screen contain apostrophes and Jinja escapes them, so an
    assertion written in the operator's own words has to compare against those words
    rather than against ``&#39;``.
    """
    return html.unescape(_visible_text(markup))


async def test_the_transports_screen_lists_every_protocol_the_image_ships(
    client,
) -> None:
    """One row per installed transport, and every value on it read from the image.

    Asserted against ``discover()`` rather than against a written list, because that IS
    the claim the screen makes about itself: a new protocol is one package and appears
    here on its own.
    """
    from edge.registry import discover

    installed = discover()
    assert installed, "no transports discovered — this assertion would be vacuous"

    body = (await client.get("/panel/transports")).text

    for name, meta in installed.items():
        assert name in body, f"{name} is not on the transports screen at all"
        assert meta.family in body, name
        low, high = meta.port_range
        assert f"{low}–{high}" in body, name
    assert "Discovered from the image" in body


async def test_the_screen_names_a_protocol_it_refuses_as_an_exit_and_says_why(
    client,
) -> None:
    """M9's acceptance line, held as a test rather than as a walk.

    *"Open the transports screen: it must name a protocol the panel refuses to offer as
    an exit and say why, in words."* Both halves are asserted, and the second one is
    the one that rots: a screen can keep a label long after the sentence explaining it
    has been edited into decoration.

    Skips loudly rather than passing vacuously if this image ships no such transport —
    a green run would otherwise mean "the warning is correct" when it means "there was
    nothing to warn about".
    """
    blocked = _identified()
    if not blocked:
        pytest.skip(
            "this image ships no transport that declares itself identified on the "
            "wire, so the screen has nothing to warn about and this proves nothing"
        )

    reads = _reading((await client.get("/panel/transports")).text)

    for name in blocked:
        assert name in reads, f"{name} is not named on the transports screen"
    # The label, in the words the pre-redesign page used and acceptance already knows.
    assert console_service.TRANSPORT_IDENTIFIED in reads
    # And the reason, in words, which is the half the milestone was written about.
    assert f"why: {console_service.TRANSPORT_WHY_IDENTIFIED}" in reads


async def test_the_warning_follows_a_declaration_and_never_a_protocol_s_name(
    client, monkeypatch
) -> None:
    """The hard rule of this step, held where breaking it would be invisible.

    Two fleets of one, identical in every declared value but the two booleans, and
    neither transport is one this image ships. If any part of the path from
    ``TransportMeta`` to the rendered cell recognised a protocol by name, the warning
    would follow the name and neither of these rows would move.
    """
    from edge.registry import TransportMeta

    def a_fleet_of_one(**declared) -> None:
        meta = TransportMeta(
            name="unshipped-shape",
            family="udp",
            needs_tls=False,
            port_range=(1024, 65535),
            **declared,
        )
        monkeypatch.setattr(console_service, "discover", lambda: {meta.name: meta})

    a_fleet_of_one(blocked_by_inspection=True, hop_capable=False)
    loud = _reading((await client.get("/panel/transports")).text)

    a_fleet_of_one()
    calm = _reading((await client.get("/panel/transports")).text)

    assert "unshipped-shape" in loud and "unshipped-shape" in calm
    assert console_service.TRANSPORT_IDENTIFIED in loud
    assert console_service.TRANSPORT_NO_HOP in loud
    assert console_service.TRANSPORT_WHY_IDENTIFIED in loud

    assert console_service.TRANSPORT_CAMOUFLAGED in calm
    assert console_service.TRANSPORT_IDENTIFIED not in calm
    assert console_service.TRANSPORT_NO_HOP not in calm
    assert "why:" not in calm


async def test_a_transport_this_panel_cannot_hand_over_says_so(client) -> None:
    """"How a user receives it" is two questions, and the screen answers both.

    A transport declares which subscription shapes it serialises into; whether this
    panel actually delivers any of them is ``subscription_expressible``, and today it
    is False for the config-file shape (backlog item 27). Collapsing the two would tell
    the operator a user is holding something they have never been sent.

    Skipped rather than asserted blindly if every installed transport is deliverable —
    that is a legitimate image and this scenario would prove nothing about it.
    """
    from edge.registry import discover

    undelivered = [
        meta
        for meta in discover().values()
        if meta.subscription_formats and not meta.subscription_expressible
    ]
    if not undelivered:
        pytest.skip("every installed transport rides in the subscription this panel serves")

    reads = _reading((await client.get("/panel/transports")).text)

    for meta in undelivered:
        for shape in meta.subscription_formats:
            assert str(shape) in reads, meta.name
    assert console_service.TRANSPORT_UNDELIVERED in reads


async def test_the_transports_screen_measures_the_image_and_never_the_people(
    client,
) -> None:
    """Decision 6 on the one screen that could not have carried those cells anyway.

    Asserted all the same: this table is where a "sessions" or "bandwidth" column would
    look most at home, because a capability table reads like a place to say how much a
    protocol is used.
    """
    body = (await client.get("/panel/transports")).text.lower()

    for cell in FORBIDDEN_CELLS:
        assert cell not in body, (
            f"the Transports screen shows {cell!r}, which the charter says must not "
            "exist"
        )


async def test_the_sidebar_no_longer_sends_the_operator_to_the_old_page_for_a_list(
    client,
) -> None:
    """The Fleet entry's note is what is LEFT on that page, and it is now empty.

    Nodes went in M9.1, hops in M9.2 and the capability table here, so every LIST that
    page carried has its own screen. The entry itself stays until M9.6 — the actions it
    carries have no home yet — but a note naming a list that has moved would send the
    operator to the wrong screen.
    """
    from control.app.panel.routes import NAV

    body = (await client.get("/panel/")).text

    assert "/panel/transports" in body
    assert next(item for item in NAV if item["key"] == "fleet")["note"] == ""
    # Fleet is the only entry that can render a note at all, so this is the same claim
    # said in markup. A later screen that wants one changes this line in front of a
    # reviewer, which is the point of writing it out rather than deriving it.
    assert "nav-note" not in body
    # The page itself is still there and still works: M9.6 retires it, not this step.
    assert (await client.get("/panel/fleet")).status_code == 200


# --- Keys & configs (M9.4) ----------------------------------------------------

# THE LIST IS THE TEST. The two surfaces that need no id; the two dialogs that do are
# built by ``every_console_surface`` below, which is what both sweeps walk.
KEY_SURFACES = ("/panel/keys", "/panel/keys/table")

# The shape UI-PATTERNS §9 draws: four hex characters, an ellipsis, four more. Written
# out rather than derived from the constant, because THIS is the claim — a fingerprint
# that grew back towards the value it names has to change this line.
FINGERPRINT = re.compile(r"^[0-9a-f]{4}…[0-9a-f]{4}$")


async def a_node_holding_material(client, reality_params) -> str:
    """A serving node with a protocol enabled and one user holding a credential on it.

    Returns the NODE-TRANSPORT id, which is what every rotation route addresses and
    what ``a_serving_node`` does not hand back — it returns the node, and two dozen
    tests depend on that. The user is created last, deliberately: a friend is granted
    every SERVING node at the moment they are created, so this is what puts a
    credential on the row and gives the rotate dialog a blast radius to state.
    """
    node = await client.post(
        "/api/nodes",
        json={"name": "keys-1", "address": "192.0.2.30", "location_label": "Testland"},
    )
    node_id = node.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await client.post(f"/api/nodes/{node_id}/state", json={"state": "active"})
    await client.post("/api/friends", json={"nickname": "mira"})
    return enabled.json()["id"]


async def every_console_surface(client, reality_params) -> list[str]:
    """Every console URL that renders markup, and the fleet it takes to reach them.

    THE LIST IS THE TEST (docs/tracker/M8/step-notes.md), in the one shape that keeps
    it honest: TWO sweeps walk this list — decision 9's, which reads every surface for
    the code's word, and M9.4's, which reads every surface for key material — so a
    screen, fragment or dialog that is not here is walked by neither. A new one joins
    this function in the change that adds it, which is the same rule the e2e scenario's
    ``PANEL_PAGES``/``PANEL_FRAGMENTS`` lists carry.

    It creates what it lists: three of these surfaces do not exist without a friend, a
    hop or a transport enabled on a node.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    entry_end = await a_hop(client)
    friend_id = (await client.get("/api/friends")).json()[0]["id"]

    return [
        "/panel/",
        "/panel/friends",
        "/panel/overview/body",
        "/panel/friends/table",
        "/panel/friends/new",
        f"/panel/friends/{friend_id}/subscription",
        f"/panel/friends/{friend_id}/revoke",
        *NODE_SURFACES,
        *HOP_SURFACES,
        *TRANSPORT_SURFACES,
        *KEY_SURFACES,
        f"/panel/hops/{entry_end}/tear-down",
        # Both rotation dialogs, on both kinds of row: one friend-facing transport and
        # one end of a hop. They are the surfaces closest to the material, so a sweep
        # that skipped them would skip the place a value would first appear.
        f"/panel/keys/{node_transport_id}/rotate",
        f"/panel/keys/{node_transport_id}/params",
        f"/panel/keys/{entry_end}/rotate",
        f"/panel/keys/{entry_end}/params",
    ]


async def stored_material(session) -> dict[str, str]:
    """Every value this fleet actually holds that no surface may ever render.

    Read out of the database and DECRYPTED, which is what makes the sweep exact rather
    than a guess at what key material looks like in markup: it hunts for the real
    bytes, so it catches one in a `title=`, a `data-` attribute, a comment or a hidden
    input as readily as in a cell.

    The keys of this mapping are field and node names, safe to print in a failure
    message. The values never are — see the sweep, which names the LABEL and never the
    value, for the same reason ``offenders()`` in the e2e scenario returns origins
    rather than URLs: a test that leaked a key into a CI log would be a worse defect
    than the one it closes.
    """
    # Read fresh every time, and this line is load-bearing: SQLAlchemy hands back the
    # instance it already has for a row rather than re-reading it, so calling this
    # twice around a rotation returned the material from BEFORE it, twice — and a test
    # comparing an answer against stale values passes over the leak it exists to find.
    # Caught by running the sweep below against a deliberately leaking rotation.
    session.expunge_all()

    held: dict[str, str] = {}
    rows = (await session.execute(select(NodeTransport))).scalars().unique()
    for row in rows:
        for name, value in json.loads(row.secrets).items():
            held[f"{row.transport_name}'s {name} on node-transport {row.id}"] = value
    credentials = (await session.execute(select(Credential))).scalars().unique()
    for credential in credentials:
        held[f"credential {credential.id}'s subject"] = credential.subject
        for name, value in json.loads(credential.secrets).items():
            held[f"credential {credential.id}'s {name}"] = value
    for node in (await session.execute(select(Node))).scalars().unique():
        if node.ssh_private_key:
            held[f"the SSH private key for node {node.name}"] = node.ssh_private_key
    return held


async def test_the_keys_screen_lists_what_each_node_holds(
    client, reality_params
) -> None:
    """design/README.md §7, with the two columns this schema can honestly fill."""
    await a_node_holding_material(client, reality_params)

    response = await client.get("/panel/keys")

    assert response.status_code == 200
    body = response.text
    assert "Keys &amp; configs" in body or "Keys & configs" in body
    assert "keys-1" in body
    # The transport is named because it is DATA on the row, not because this screen
    # knows any protocol.
    assert "vless-reality" in body
    for column in ("node", "transport", "scope", "fingerprint", "on the node"):
        assert f">{column}<" in body, column
    # The design's own two columns that this schema cannot fill honestly. `minted` has
    # no column to read — a row's timestamps move whenever anything on it changes — and
    # `rotates` would promise a schedule nothing in this product keeps.
    assert ">minted<" not in body
    assert ">rotates<" not in body
    # Both actions the milestone's "done when" homes here.
    assert "rotate keys" in body
    assert "replace params" in body


async def test_a_fingerprint_is_short_and_is_not_the_value_it_names(
    client, session, reality_params
) -> None:
    """UI-PATTERNS §9: fingerprints are truncated — and derived from what is published.

    Two assertions, and the second is the one that matters. The cell shows eight
    characters of a SHA-256 digest, and the PUBLISHED value that digest was computed
    over is itself absent from the screen: the panel names material rather than
    displaying it, even when the material in question is the half that already travels
    to every device.
    """
    await a_node_holding_material(client, reality_params)
    row = (
        (await session.execute(select(NodeTransport)))
        .scalars()
        .unique()
        .__iter__()
        .__next__()
    )

    body = (await client.get("/panel/keys")).text

    shown = re.findall(r"([0-9a-f]{4}…[0-9a-f]{4})", body)
    assert len(shown) == 1, shown
    assert FINGERPRINT.match(shown[0])
    assert shown[0] == keymaterial.fingerprint(
        profile(row.transport_name).meta.key_material, row.params
    )
    published = [
        row.params[spec.public_name]
        for spec in profile(row.transport_name).meta.key_material
        if spec.public_name and spec.public_name in row.params
    ]
    assert published, "this transport publishes nothing, so this proves nothing"
    for value in published:
        if value in body:
            # Same instrument as the sweep below, for a milder reason: this half is
            # published to every device that uses it, but a CI log is still not where
            # a fleet's public keys belong.
            pytest.fail("the screen shows a published value rather than naming it")


async def test_the_fingerprint_moves_when_the_material_does(
    client, reality_params
) -> None:
    """The cell's whole job: telling the operator that a rotation actually happened.

    A fingerprint that did not move after a rotation would be a fingerprint of
    something else — a row id, a name — dressed up as one, and nothing else on the
    screen would give that away.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    before = re.findall(r"[0-9a-f]{4}…[0-9a-f]{4}", (await client.get("/panel/keys")).text)

    await client.post(f"/panel/keys/{node_transport_id}/rotate")

    after = re.findall(r"[0-9a-f]{4}…[0-9a-f]{4}", (await client.get("/panel/keys")).text)
    assert len(before) == len(after) == 1
    assert before != after


async def test_a_transport_with_no_published_half_prints_the_rule_instead(
    client, ws_params
) -> None:
    """UI-PATTERNS §9's actual instruction, in the cell where it bites.

    A transport whose node material is secret at both ends has nothing that may be
    hashed: its values are short or private, and a digest of a short one is recoverable
    by trying every candidate. So the cell says what is true — it is held and it is not
    shown — instead of inventing a fingerprint from something that must not go into one.
    """
    node_id = (
        await client.post(
            "/api/nodes",
            json={
                "name": "ws-1",
                "address": "192.0.2.31",
                "location_label": "Testland",
            },
        )
    ).json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-ws-tls", "params": ws_params},
    )
    assert enabled.status_code == 201, enabled.text

    body = (await client.get("/panel/keys")).text

    assert console_service.KEY_HELD_NOT_SHOWN in _reading(body)
    assert not re.findall(r"[0-9a-f]{4}…[0-9a-f]{4}", body)


async def test_no_console_surface_ever_shows_key_material(
    client, session, reality_params
) -> None:
    """M9's acceptance walk — "hunt for a private key anywhere in the console" — as a
    test, so it is hunted on every run rather than once by a person.

    It sweeps every console surface with the REAL values this fleet holds, decrypted
    out of the database: node private keys, the pre-shared key both ends of a hop
    carry, and every user credential minted on either. A substring search over the
    whole response is what makes it stronger than reading: it catches a value in a
    `title=`, a `data-` attribute, a hidden input, an HTML comment or a URL as readily
    as one in a cell, and it does not need to know what a key looks like.

    The failure message names the LABEL and never the value — one of these surfaces
    also renders a live subscription token, and a scenario that put a credential into a
    CI log would be a worse defect than the one it closes.
    """
    surfaces = await every_console_surface(client, reality_params)
    # The pre-redesign pages are swept too. They are still part of the panel until M9.6
    # retires them, and "anywhere in the console" is the claim.
    node_id = (await client.get("/api/nodes")).json()[0]["id"]
    surfaces += ["/panel/fleet", f"/panel/nodes/{node_id}"]

    held = await stored_material(session)
    # Non-vacuous by construction: a fleet holding nothing would pass this sweep for
    # the wrong reason. Two node keys, a pre-shared key at each hop end and a user
    # credential is the floor.
    assert len(held) >= 5, sorted(held)

    for surface in surfaces:
        response = await client.get(surface)
        assert response.status_code == 200, surface
        for label, value in held.items():
            if value in response.text:
                # ``pytest.fail`` and not ``assert``: pytest rewrites a failing
                # assertion into a message containing BOTH operands, so an
                # ``assert value not in body`` puts the key it just found into the CI
                # log — which is a worse defect than the one this sweep closes, and is
                # the same rule ``offenders()`` follows in the e2e scenario. Found by
                # running this test red, which is the only way it could have been.
                pytest.fail(
                    f"{surface} rendered {label} — key material is minted here, "
                    "stored encrypted and never displayed (UI-PATTERNS §9)"
                )


async def test_no_answer_to_a_rotation_shows_what_it_minted(
    client, session, reality_params
) -> None:
    """The other half of the sweep, and the half a list of URLs cannot reach.

    A mutation answers with a toast or a banner composed from a service's own words,
    and the rotation path is the one place in this panel where those words are about
    values that were just minted. Both sides are checked — what the row held before
    the rotation and what it holds after — because either would be a leak, and the
    first one is the one an "it only prints the new material" reading would miss.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    before = await stored_material(session)

    answer = await client.post(
        f"/panel/keys/{node_transport_id}/rotate", headers={"HX-Request": "true"}
    )

    assert answer.status_code == 200
    after = await stored_material(session)
    assert before and after
    for held in (before, after):
        for label, value in held.items():
            if value in answer.text:
                # The label, never the value — see the sweep above for why an ordinary
                # assertion is the wrong instrument here.
                pytest.fail(f"the rotation's answer rendered {label}")


async def test_rotating_keys_confirms_first_and_says_what_it_costs(
    client, reality_params
) -> None:
    """UI-PATTERNS §3, and the three facts an operator cannot recover afterwards.

    A rotation re-mints every user credential on the transport as well as the node's
    own material, and it is one click from "probe". The count is in the sentence so the
    blast radius is read before the button, not inferred after it.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)

    dialog = await client.get(f"/panel/keys/{node_transport_id}/rotate")

    assert dialog.status_code == 200
    reading = _reading(dialog.text)
    assert "Rotate these keys?" in reading
    assert "keys-1" in reading
    assert "1 user credential" in reading
    # The link does not move — which is the whole reason a rotation is possible at all
    # without anyone touching their device.
    assert "same link" in reading
    assert "rotate keys" in dialog.text
    assert "cancel" in dialog.text


async def test_rotating_one_end_of_a_hop_says_what_it_does_to_the_other(
    client,
) -> None:
    """The decision of 2026-08-09, stated where it can still be acted on.

    A transport may declare that some of its material is SYMMETRIC — both ends of a hop
    must hold the same copy — and `control` mints each end separately, so re-minting at
    one end produces two configuration files that are individually valid and a handshake
    that never completes. Nothing in the wire behaviour says so; the operator only sees
    a tunnel that stopped.

    Read from the DECLARATION rather than from a name: this asserts the sentence appears
    on a hop end whose transport declares symmetric material, and does not appear on a
    friend-facing row, which is the same distinction the code makes.
    """
    entry_end = await a_hop(client)
    carrier = profile(a_hop_transport()).meta
    assert any(
        spec.shared_between_peers for spec in carrier.key_material
    ), "this image's hop carrier declares nothing symmetric, so this proves nothing"

    dialog = await client.get(f"/panel/keys/{entry_end}/rotate")

    assert dialog.status_code == 200
    reading = _reading(dialog.text)
    assert console_service.KEY_SHARED_WITH_PEER in reading
    # And what a hop end is NOT: nobody's credential rides on it.
    assert "No user holds anything on it" in reading
    assert "user credential" not in reading


async def test_a_rotation_that_could_not_reach_the_node_stays_on_screen(
    client, reality_params
) -> None:
    """The failure that must never be reported as success.

    Nothing behind these nodes answers, so the push cannot land: the material is in the
    database and the node is still running the old one. That is a banner rather than a
    toast — it has to survive the operator's next click, because until it is applied
    the blocked value is still what the node serves.

    The real push runs rather than a monkeypatched one, unlike the apply tests above:
    what is under test IS the failure branch, and both ways a documentation address can
    fail — refused or dropped — arrive at it identically. Nothing here asserts a
    duration, which is the one thing that would make the difference matter (conftest's
    ``LoopbackSSH`` says why).
    """
    node_transport_id = await a_node_holding_material(client, reality_params)

    answer = await client.post(
        f"/panel/keys/{node_transport_id}/rotate", headers={"HX-Request": "true"}
    )

    assert answer.status_code == 200
    reading = _reading(answer.text)
    assert "banner-failure" in answer.text
    assert "toast" not in answer.text
    assert "still running the old material" in reading
    assert answer.headers["HX-Trigger"] == "keys-changed, nodes-changed"


async def test_a_hop_end_is_never_told_what_its_users_will_pick_up(
    client, reality_params
) -> None:
    """The dialog and its answer must agree about who holds this row.

    ``rotate_keys_dialog.html`` branches on ``for_friends`` and tells the operator, in
    so many words, *"No user holds anything on it: this is a tunnel between two of our
    own nodes"*. The answer then reported what users would pick up the next time their
    client refreshed — so the operator confirmed having read that no user is involved
    and was immediately told about users' links. Every other string on this screen makes
    that distinction; these two did not.

    Driven at the surface rather than through the service, because the wiring is half
    the claim: the row this answer is composed from has to be the row the dialog was.
    The push cannot land here (nothing answers at these addresses), which is the
    half-done branch — the one that used to end "users on it are unaffected" about a
    tunnel with no user on either end.

    The REPLACE action rather than rotate, and not by preference: rotating one end of a
    hop on this image's carrier re-mints a value the far end holds a copy of, and the
    re-render that follows refuses the pair — see ``carry-over.md``, where that is a
    deferred Medium of its own. ``transports.PORT_FIELD`` is the one field name the
    console is allowed to know.
    """
    entry_end = await a_hop(client)
    boxes = {
        name for name, _, _ in _form_controls(
            (await client.get(f"/panel/keys/{entry_end}/params")).text
        )
    }
    assert transports_service.PORT_FIELD in boxes, boxes

    answer = await client.post(
        f"/panel/keys/{entry_end}/params",
        data={transports_service.PORT_FIELD: "51999"},
        headers={"HX-Request": "true"},
    )

    assert answer.status_code == 200
    reading = _reading(answer.text)
    assert "no user holds anything on it" in reading
    assert "users on it are unaffected" not in reading
    assert "same link" not in reading


async def test_every_rotation_sentence_branches_on_who_holds_the_row(
    client, session, reality_params
) -> None:
    """Both sentences, both outcomes, both kinds of row — the whole four.

    ``rotation_summary`` and ``replacement_summary`` each have a landed and a half-done
    form, and the half-done one is shared (``_unpushed``). Composed here rather than
    driven through a route because a successful push needs a host: what is under test is
    the prose, which lives in ``services/console.py`` by this milestone's own rule, and
    the surface above is what proves it is wired to the right row.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    entry_end = await a_hop(client)
    session.expunge_all()
    for_friends = await console_service.key_row(session, node_transport_id)
    hop_end = await console_service.key_row(session, entry_end)
    assert for_friends.for_friends and not hop_end.for_friends

    landed = rotation_service.RotationOutcome(
        node_transport_id=node_transport_id, rotated=["decoy_host"], node_pushed=True
    )
    half_done = rotation_service.RotationOutcome(
        node_transport_id=node_transport_id,
        rotated=["decoy_host"],
        failure="the host refused the connection",
    )

    for compose in (console_service.rotation_summary, console_service.replacement_summary):
        for outcome in (landed, half_done):
            what = f"{compose.__name__} on a {'landed' if outcome.complete else 'half-done'} push"
            hop_sentence = compose(hop_end, outcome)
            assert "no user holds anything on it" in hop_sentence, what
            assert "same link" not in hop_sentence, what
            assert "users on it are unaffected" not in hop_sentence, what
            # And the friend-facing row still says what it always said, so this is a
            # branch rather than a sentence that stopped mentioning people.
            friends_sentence = compose(for_friends, outcome)
            assert ("same link" in friends_sentence) or (
                "users on it are unaffected" in friends_sentence
            ), what


async def test_the_replace_dialog_offers_no_box_for_key_material(
    client, reality_params
) -> None:
    """Absent by construction, not by omission.

    The box list is the transport's required fields MINUS everything it declares as
    material and every public counterpart of one, so this form cannot ask for a key,
    cannot show one as a placeholder, and cannot hand one back on a refusal. Asserted
    against the transport's OWN declaration rather than a written list, so a protocol
    that declares a new piece of material is covered the day it ships.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)

    dialog = await client.get(f"/panel/keys/{node_transport_id}/params")

    assert dialog.status_code == 200
    boxes = {name for name, _, _ in _form_controls(dialog.text)}
    assert boxes, "a dialog with no boxes proves nothing"
    material = transports_service.key_material_names("vless-reality")
    assert material, "this transport mints nothing, so this proves nothing"
    assert boxes & material == set()
    # And the rule is stated, rather than the absence being left to be noticed.
    assert "never can be" in _reading(dialog.text)


async def test_replacing_a_parameter_names_what_changed(
    client, reality_params
) -> None:
    """Item 24's real case: a decoy that has been blocked, replaced from the console.

    The field NAMES are in the answer, unlike a key rotation's — these are values the
    operator typed themselves, so naming them back is how they confirm the right box
    landed.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)

    answer = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={"decoy_host": "www.wikipedia.example"},
        headers={"HX-Request": "true"},
    )

    assert answer.status_code == 200
    reading = _reading(answer.text)
    assert "decoy_host" in reading
    assert "keys-1" in reading
    # The push cannot land in this suite, so this is the half-done sentence rather than
    # a toast. What matters is that it names the change and says what is still true.
    assert "still running the old material" in reading


async def test_a_refused_parameter_lands_under_its_own_box(
    client, reality_params
) -> None:
    """M9.1's rule on M9.4's form: a refusal is a 422 with the message under the field.

    Flattened to a sentence at the top, the operator has to work out which of the boxes
    the prose is about — during a rotation, which is the moment this form exists for.

    The box picked is one the transport DECLARES it requires, found through the same
    service call the form is built from rather than written down: this form offers the
    required fields and no others, so a test naming a defaulted one would be refused
    for having typed nothing and would pass for the wrong reason.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    box = transports_service.PORT_FIELD
    assert box in transports_service.operator_params("vless-reality")

    refused = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={box: "70000"},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422
    errors = _described(refused, "error", prefix="param")
    assert box in errors, errors
    # What the operator typed comes back with it, so nothing has to be retyped.
    assert 'value="70000"' in refused.text


# Every SHAPE Pydantic reports a location in, as this panel would receive it. Written
# out because the guard is keyed on the shape and not on the value: an allow-list that
# only handles the first of these is one `loc` away from printing a message about a
# field nobody typed. `""` is what a model-level validator produces, `x.0` a nested one,
# and the last is a field this form has no box for.
#
# The message on each carries a value that must never reach the page. Only the first
# entry is a box on the replace form, and it is the only one whose sentence may be read.
REFUSAL_SHAPES = {
    "port": "must be inside the range — QUOTED-BOX-VALUE",
    "private_key": "is not usable — QUOTED-MATERIAL-VALUE",
    "": "these parameters disagree with each other — QUOTED-MODEL-VALUE",
    "server_names.0": "is not a hostname — QUOTED-NESTED-VALUE",
    "decoy_port": "is out of range — QUOTED-UNRENDERED-VALUE",
}


async def test_a_refusal_prints_the_transport_s_words_only_under_a_box(
    client, monkeypatch, reality_params
) -> None:
    """The case that cannot be seen while it works, closed as a class rather than twice.

    A transport's own validation message may quote the value it rejected, and what is
    validated on this path includes the material the node holds. The first version of
    this guard named the key material it knew about and printed everything else, which
    covers the two shapes anybody thinks of and leaves the rest: Pydantic reports a
    model-level validator at an EMPTY location and a nested one at ``field.0``, and
    neither is a declared parameter name.

    So the rule is an allow-list — a message is printed only under a box, because a box
    holds a value the operator typed — and this plants one refusal of every shape at
    once to hold it. Each carries a distinct value; only the box's may be read.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    assert "port" in transports_service.operator_params("vless-reality")

    async def refuse(session, *, node_transport_id, params):
        raise ParamsRefused("transport rejected these parameters", fields=REFUSAL_SHAPES)

    monkeypatch.setattr(rotation_service, "replace_params", refuse)

    refused = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={"decoy_host": "www.wikipedia.example"},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422
    reading = _reading(refused.text)
    for name, message in REFUSAL_SHAPES.items():
        quoted = message.rsplit(" ", 1)[-1]
        if name == "port":
            # The one the operator typed: its sentence lands under its own box.
            assert _described(refused, "error", prefix="param")["port"] == message
            continue
        if quoted in refused.text:
            # ``pytest.fail`` and not ``assert``, for the reason the sweep below gives:
            # a rewritten assertion prints both operands, and one of these stands in
            # for key material.
            pytest.fail(f"the refusal about {name or 'the whole mapping'} was printed")
        # Named, so the operator knows what was refused, with the rule in its place.
        assert (name or console_service.KEY_UNNAMED_REFUSAL) in reading
    assert "never displays" in reading


async def test_a_rotation_refused_by_the_transport_prints_none_of_its_words(
    client, monkeypatch, reality_params
) -> None:
    """The other rotation path, whose answer has no box for anything.

    ``rotate_keys`` validates the operator's existing parameters TOGETHER WITH the
    material it has just minted, so a validator that quotes its input may be quoting a
    private key whichever field it names — and the answer here is a banner, with nowhere
    for a message about one parameter to belong. Both facts say the same thing, and an
    empty set of boxes is how the route says it. (Note what is NOT the reason: that
    nothing in the mapping was typed. Some of it was, which is exactly the reading that
    would talk a later change into printing these.)

    Latent rather than live, which is why it is guarded instead of watched: no shipped
    transport's validator quotes its input today, and the day one does there is no
    second chance to notice.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)

    async def refuse(session, *, node_transport_id, **rest):
        raise ParamsRefused("the rotated parameters are not valid", fields=REFUSAL_SHAPES)

    monkeypatch.setattr(rotation_service, "rotate_keys", refuse)

    answer = await client.post(
        f"/panel/keys/{node_transport_id}/rotate", headers={"HX-Request": "true"}
    )

    assert answer.status_code == 200
    reading = _reading(answer.text)
    for name, message in REFUSAL_SHAPES.items():
        if message.rsplit(" ", 1)[-1] in answer.text:
            pytest.fail(f"the rotation refusal about {name or 'the whole mapping'} was printed")
        assert (name or console_service.KEY_UNNAMED_REFUSAL) in reading
    # A refusal, so it is drawn as one and stays until the next successful request.
    assert "banner-failure" in answer.text


async def test_an_empty_replace_form_is_refused_without_a_box_to_blame(
    client, reality_params
) -> None:
    """The one refusal on this form that is deliberately NOT per field.

    An empty box here is a meaningful answer — keep this value — so there is no single
    box the message belongs under. It is the form as a whole that said nothing, and the
    sentence says so rather than marking every field invalid.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)

    refused = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={"decoy_host": ""},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422
    assert "nothing was typed" in _reading(refused.text)
    assert _described(refused, "error", prefix="param") == {}


async def test_nothing_this_screen_serves_may_be_stored_or_remembered(
    client, reality_params
) -> None:
    """Checked deliberately here rather than inherited, because of what this screen is.

    ``docs/decisions.md`` (2026-09-09): htmx's history cache writes the whole body to
    ``localStorage``, and that entry exists because a dialog body once held a live
    subscription URL. Every response under ``/panel`` gets ``no-store`` from one
    middleware, so this screen's fragments are covered — but "covered by a prefix"
    is exactly what was true of the fragment that carried the credential, and the
    screen whose subject is key material is the wrong one to take on trust.

    The screen itself is in ``TWO_REPRESENTATION_URLS`` above, which additionally
    proves the ``Vary``. This walks the fragments a browser is handed and the two
    dialogs, which have ids and so cannot be parameterised into that list.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    fragments = (
        "/panel/keys/table",
        f"/panel/keys/{node_transport_id}/rotate",
        f"/panel/keys/{node_transport_id}/params",
    )

    for path in fragments:
        response = await client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store", path

    # And nothing on the screen is written to localStorage at all: the console opts out
    # of htmx's history cache entirely, which is the other half of that decision.
    assert 'hx-history="false"' in (await client.get("/panel/keys")).text


@pytest.mark.parametrize(
    "fields",
    (
        # A validator that raised ``ValueError("")``: Pydantic reports ``Value error, ``
        # and ``relay._plainly`` strips it to nothing. It landed under the box as an
        # empty string, which the template's `{% if %}` skipped — a 422 that re-rendered
        # the form with no message anywhere, which reads as a form that will not submit.
        {"port": ""},
        # And a refusal carrying no field at all, which had nothing to name.
        {},
    ),
    ids=("an empty message on a box", "no field at all"),
)
async def test_a_refusal_is_never_silent(
    client, monkeypatch, reality_params, fields: dict
) -> None:
    """Every refusal says something, and the sorting function is what guarantees it.

    The rotation path had a fallback for this shape and the replacement path did not,
    which is the wrong place for the rule to live: a caller can forget it. It is now an
    invariant of ``_refused_parameters`` — a message that cannot be printed is treated
    exactly like one that may not be, and a refusal with nothing to name is stated as a
    complaint about the parameters as a whole.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)

    async def refuse(session, *, node_transport_id, params):
        raise ParamsRefused("transport rejected these parameters", fields=fields)

    monkeypatch.setattr(rotation_service, "replace_params", refuse)

    refused = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={"decoy_host": "www.wikipedia.example"},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422
    # Said where a person will read it, and drawn as a refusal rather than as a notice.
    assert 'role="alert"' in refused.text
    assert "field-error" in refused.text
    assert "never displays" in _reading(refused.text)


# Two transports that refuse the way a real one could, for the test below. They exist
# because everything above plants a ``ParamsRefused`` by hand: that proves the CONSUMER
# handles each location shape and proves nothing about the shapes its PRODUCER emits.
# Narrowing rotation.py's ``".".join(...)`` to ``error["loc"][0]`` would collapse
# ``server_names.0`` onto the real ``server_names`` box and start printing a nested
# validator's sentence, with every hand-planted test still green.
#
# Both quote their input, which no shipped transport does — that is the whole hazard
# being modelled. The assertion looks for a marker that can only have come from the
# MESSAGE: the value itself is the operator's own text and is legitimately handed back
# into its box on a refusal, so finding that in the response proves nothing either way.
VALIDATOR_SAID = "QUOTED-BY-A-VALIDATOR"


def _quoting_item(value: str) -> str:
    raise ValueError(f"is not a name this decoy can present: {VALIDATOR_SAID} {value}")


class _RefusesAnItem(pydantic.BaseModel):
    """A per-item validator: Pydantic locates this at ``("server_names", 0)``."""

    model_config = pydantic.ConfigDict(extra="allow")

    server_names: list[typing.Annotated[str, pydantic.AfterValidator(_quoting_item)]]


class _RefusesTheMapping(pydantic.BaseModel):
    """A model-level validator: Pydantic locates this at ``()``, which joins to ``""``."""

    model_config = pydantic.ConfigDict(extra="allow")

    decoy_host: str

    @pydantic.model_validator(mode="after")
    def _refuse(self):
        raise ValueError(f"these parameters disagree: {VALIDATOR_SAID} {self.decoy_host}")


class _RefusingProfile:
    """Whatever ``profile()`` hands back, narrowed to the one call rotation makes."""

    def __init__(self, model) -> None:
        self._model = model

    def validate(self, values: dict) -> dict:
        self._model(**values)
        raise AssertionError("this model was supposed to refuse and did not")


@pytest.mark.parametrize(
    ("model", "field", "named"),
    (
        (_RefusesAnItem, "server_names", "server_names.0"),
        (_RefusesTheMapping, "decoy_host", console_service.KEY_UNNAMED_REFUSAL),
    ),
    ids=("a nested location", "no location at all"),
)
async def test_the_locations_a_real_refusal_carries_are_the_ones_that_are_withheld(
    client, monkeypatch, reality_params, model, field: str, named: str
) -> None:
    """The guard, against its OWN producer rather than a hand-built stand-in.

    ``rotation.replace_params`` runs for real here — only the transport's model is
    swapped, for one that refuses the way a real one could — so what the route sorts is
    the location string the service actually composed. That is the half the planted
    refusals above cannot reach: they prove the console handles ``server_names.0`` and
    ``""``, not that anything ever produces them.

    Both models quote their input, which is the hazard being modelled. Neither sentence
    may reach the page; both parameters must be named, so the operator still knows what
    was refused.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    monkeypatch.setattr(rotation_service, "profile", lambda name: _RefusingProfile(model))

    refused = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={field: "www.wikipedia.example"},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422
    if VALIDATOR_SAID in refused.text:
        # The label, never the value — the same instrument the sweep uses, for the same
        # reason: a rewritten assertion prints both operands.
        pytest.fail(f"a refusal located at {named!r} was printed with its own words")
    reading = _reading(refused.text)
    assert named in reading
    assert "never displays" in reading


class _QuotesAFieldItWasValidatedWith(pydantic.BaseModel):
    """The shape the console's allow-list cannot see, and the reason it is not the guard.

    A ``field_validator`` on a field this form DOES have a box for, reading the fields
    validated before it through ``info.data`` — which on the replacement path is the
    merged mapping, decrypted ``secrets`` column and all. Pydantic locates the complaint
    at ``("decoy_host",)``, which IS a box, so the sorter prints the sentence verbatim
    and the node's private key becomes visible text on this screen's own dialog. The
    field order is load-bearing: ``private_key`` is declared first, so it is in
    ``info.data`` by the time ``decoy_host`` is checked.

    Closed by redaction in the service instead of by sorting here —
    ``docs/decisions.md`` (2026-09-10) and ``relay.refused_fields``.
    """

    model_config = pydantic.ConfigDict(extra="allow")

    private_key: str
    decoy_host: str

    @pydantic.field_validator("decoy_host")
    @classmethod
    def _refuse(cls, value: str, info: pydantic.ValidationInfo) -> str:
        raise ValueError(
            f"does not match the key {VALIDATOR_SAID} {info.data.get('private_key')}"
        )


async def test_no_answer_to_a_replacement_shows_what_the_node_holds(
    client, session, monkeypatch, reality_params
) -> None:
    """The half of the sweep nothing walked, which is how the leak above survived.

    ``every_console_surface`` covers every GET, and ``test_no_answer_to_a_rotation_...``
    covers the ROTATE post's answer. Nothing swept the answer to the one POST that
    prints a transport's own sentence on purpose — so the surface with the only path
    from the encrypted column to visible text was the surface with no sweep over it.

    Driven by a model that refuses the way a real one could and quotes what it was
    given, because no shipped transport's validator does: the hazard is latent, and a
    latent hazard on the screen whose acceptance line reads "hunt for a private key —
    you must not find one" is guarded rather than watched.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    monkeypatch.setattr(
        rotation_service,
        "profile",
        lambda name: _RefusingProfile(_QuotesAFieldItWasValidatedWith),
    )

    refused = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={"decoy_host": "www.wikipedia.example"},
        headers={"HX-Request": "true"},
    )

    assert refused.status_code == 422
    held = await stored_material(session)
    # Non-vacuous by construction, the way the GET sweep is: a fleet holding nothing
    # would pass this for the wrong reason.
    assert held
    for label, value in held.items():
        if value in refused.text:
            # The label, never the value — a rewritten assertion prints both operands.
            pytest.fail(f"the answer to a replacement rendered {label}")

    # And the message DID arrive under its box: this is a redaction, not a message that
    # went missing. A guard that dropped the whole sentence would pass the sweep above
    # and cost the operator the only actionable answer this form gives them.
    under_its_box = _described(refused, "error", prefix="param")["decoy_host"]
    assert VALIDATOR_SAID in under_its_box
    assert relay_service.WITHHELD in under_its_box


async def test_a_rotation_refusal_repeats_no_sentence_wherever_it_is_rendered(
    client, monkeypatch, reality_params
) -> None:
    """The one part of a refusal every caller renders without choosing to.

    ``ParamsRefused.message`` goes into the error envelope and into the pre-redesign
    page's ``outcome.html`` — a PANEL surface — with no filtering possible at either.
    The console's own screen sorts ``fields`` and prints none of them on this path, but
    that is a decision the console makes and those two surfaces cannot. So the ROTATION
    path composes its message from the parameter NAMES and states the rule in place of
    their sentences: that mapping is validated together with material minted moments
    earlier, and a validator can quote what it rejected.

    Driven through the old page deliberately, because that is the surface the rule is
    written about and the one this file's screen sweep cannot reach.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    monkeypatch.setattr(
        rotation_service, "profile", lambda name: _RefusingProfile(_RefusesTheMapping)
    )

    outcome = await client.post(f"/panel/transports/{node_transport_id}/rotate-keys")

    assert outcome.status_code == 200
    if VALIDATOR_SAID in outcome.text:
        pytest.fail("a rotation's refusal carried the transport's own words")
    reading = _reading(outcome.text)
    # Named, so the operator still knows what was refused, and told why the rest is not
    # here rather than left to wonder whether the panel simply lost it.
    assert rotation_service.WHOLE_MAPPING in reading
    assert "not repeated here" in reading


async def test_a_transport_this_image_no_longer_ships_says_so_in_the_dialog(
    client, monkeypatch, reality_params
) -> None:
    """A row whose protocol has left the image, asked for by a typed URL.

    The table offers no button for it, so this is only reachable deliberately — but the
    answer still has to arrive where the operator is looking. Raising a domain error
    here produced a 400, and ``static/app.js`` swaps exactly one status (422): the
    dialog would have opened empty with the explanation in a response body nothing
    rendered. So the dialog states it, offers no submit, and the POST refuses at the one
    status the console can show.
    """
    node_transport_id = await a_node_holding_material(client, reality_params)
    # An image that ships nothing, which is what a package removed from the tree looks
    # like to a row that still names it. M9.3's own trick, on the same function.
    monkeypatch.setattr(console_service, "discover", lambda: {})

    dialog = await client.get(f"/panel/keys/{node_transport_id}/params")
    refused = await client.post(
        f"/panel/keys/{node_transport_id}/params",
        data={"decoy_host": "www.wikipedia.example"},
        headers={"HX-Request": "true"},
    )

    assert dialog.status_code == 200
    assert console_service.KEY_NOT_IN_THIS_IMAGE in _reading(dialog.text)
    assert 'type="submit"' not in dialog.text
    assert refused.status_code == 422
    assert console_service.KEY_NOT_IN_THIS_IMAGE in _reading(refused.text)


def test_the_replace_form_gives_its_boxes_the_room_the_value_needs() -> None:
    """Which half of the row is being READ decides which half is wide.

    The hop dialog's ``.tuning-field`` caps its input at 136px and gives the label the
    rest, which is right for twenty-four short numeric knobs whose boxes are empty. On
    this form the input carries the value being replaced — "leave one empty to keep it"
    is only an affordance if the operator can see what they would be keeping — and a
    hostname or a comma-joined list shows about seventeen characters in 136px.

    Asserted where the rule is written, since no browser runs here: the acceptance walk
    is what proves it lays out.
    """
    rules = _css_rules()

    assert ".param-field" in rules, "the replace form has no row rule of its own"
    columns = rules[".param-field"]
    assert "minmax(0, 1fr)" in columns
    assert "136px" not in columns
    # The label is the column that gives way, not the box.
    assert "auto" in columns

    markup = (TEMPLATES / "panel" / "replace_params_dialog.html").read_text()
    assert "param-field" in markup
    assert "tuning-field" not in re.sub(r"\{#.*?#\}", "", markup, flags=re.S)
    # And no breakpoint was added for it — there is one, at 900px (UI-PATTERNS §12).
    assert _served("app.css").count("@media (max-width") == 1


async def test_the_keys_screen_measures_the_fleet_and_never_the_people(
    client, reality_params
) -> None:
    """Decision 6 on the one screen that counts something per user.

    ``users on it`` counts credentials WE minted on this transport — the blast radius
    of the button beside it. It moves when the operator adds or revokes a user and
    never when anybody connects, which is the test docs/decisions.md sets.
    """
    await a_node_holding_material(client, reality_params)

    body = (await client.get("/panel/keys")).text

    assert ">users on it<" in body
    for cell in FORBIDDEN_CELLS:
        assert cell not in body.lower(), (
            f"the Keys screen shows {cell!r}, which the charter says must not exist"
        )


async def test_an_empty_keys_screen_says_where_material_comes_from(client) -> None:
    """M8.6's rule on the screen a first-time operator reaches with nothing enabled."""
    body = (await client.get("/panel/keys")).text

    assert "Nothing minted yet" in body
    assert "<table" not in body


# --- what a browser is allowed to keep (acceptance round 1) -------------------

# Every console URL a browser can navigate to AND htmx can fetch as a fragment. The
# defect this section stands over needs both halves of that sentence: a URL with two
# representations, and a cache that stores one of them under the other's name.
#
# It held two of the five that qualify until M9.3, which is the shape of defect this
# comment describes rather than avoids: the three screens M9 added inherited the header
# from main.py's /panel prefix and were therefore untested rather than unheld. Written
# out rather than derived from NAV, because THIS is the claim — a screen that stops
# having two representations, or one added without them, changes this line in front of
# a reviewer.
TWO_REPRESENTATION_URLS = (
    "/panel/",
    "/panel/friends",
    "/panel/nodes",
    "/panel/hops",
    "/panel/transports",
    # M9.4's, and the one on this list whose body is the most sensitive: htmx's history
    # cache writes a stored body to localStorage, which is what decision 9's htmx entry
    # is about. This screen holds fingerprints rather than values, and it is on here so
    # that stays a property of the response and not of the reader.
    "/panel/keys",
)


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
    "path",
    (
        *TWO_REPRESENTATION_URLS,
        "/panel/friends/table",
        "/panel/friends/new",
        "/panel/keys/table",
    ),
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
    of the operator. A new one joins ``every_console_surface`` in the change that adds
    it — one list, walked by this sweep and by M9.4's hunt for key material, so a
    surface cannot be missing from one of them and present in the other.
    """
    for path in await every_console_surface(client, reality_params):
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

    # The whole allow-list of places a word may be broken, written out so a fifth
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
        # A hop parameter's name, in the hop dialog's tuning rows (M9.2). Agreed to
        # rather than slipped in, which is what this list is for: these are the longest
        # names in the panel, they sit in a 1fr column beside a fixed-width input inside
        # a 620px dialog, and a name that cannot wrap prints over the box beside it.
        # It is not a table column, so the min-content collapse this rule exists to
        # prevent cannot happen here — the row grows instead.
        ".tuning-field label",
        # The same name in the replace-parameters dialog (M9.4), agreed to for that
        # reason and one of its own: this row's label column is `auto` and its input
        # takes the rest, so a long parameter name that cannot wrap does not print over
        # the box — it takes the box's width away, and that width is what the value
        # being replaced is read in.
        ".param-field label",
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
    informational message believes the action worked. The weight is a thick edge and the
    word; the COLOUR is the danger hue M9 settled, and the test below is the one that
    holds it.
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
    assert "danger" in rules[".banner-failure"]


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


def test_a_refusal_is_not_drawn_in_the_colour_of_the_button_that_refused_it() -> None:
    """The M8 acceptance finding the owner carried into M9, settled once.

    A refusal had its own weight but no error colour: `.field-error` was drawn in
    --color-accent-700, the same slate blue as the primary "add user" button and as the
    accent on the ordinary NOTE banner, over dark navy text on no background. Nothing
    about the colour said "wrong", and the only signal was the wording.

    Settled in the shared stylesheet rather than on one screen, so every screen M9 and
    M10 add inherits it and no screen gets an error colour of its own. UI-PATTERNS §4's
    "there is no red" still holds everywhere it was written about — a status tag, a
    destructive button — and this is its one exception: a request that was REFUSED or
    FAILED. It supersedes that line of the handoff for that one role and is written
    down as such in docs/decisions.md (2026-09-10), not only here.
    """
    rules = _css_rules()

    # The hue is declared once, as tokens, like everything else in this stylesheet.
    assert "--color-danger-700" in rules[":root"]
    for selector in (".field-error", ".banner-failure"):
        assert "danger" in rules[selector], f"{selector} carries no error colour"
        assert "accent" not in rules[selector], (
            f"{selector} is still drawn in the accent that refused it"
        )
    # And the ordinary notice is untouched: it is not a failure and must not read as one.
    assert "danger" not in rules[".banner"]
    # The three roles UI-PATTERNS §4 gives a status tag stay steel.
    assert not [
        selector
        for selector, body in rules.items()
        if selector.startswith(".tag") and "danger" in body
    ]


async def test_the_sign_in_refusal_is_a_failure_and_not_a_notice(anonymous) -> None:
    """The one refusal outside the console, and the first anybody ever meets.

    It was drawn as the neutral notice — the same frame as "No node is serving yet" —
    on a page that loads the same stylesheet, so the finding M9 settled once was still
    live in the place a person meets it first. The class-level guard is the test below;
    this one holds the page itself, because the sign-in screen has no shell and would
    not be walked by anything else.
    """
    refused = await anonymous.post(
        "/panel/login", data={"username": "owner", "password": "wrong"}
    )

    assert refused.status_code == 401
    assert "banner-failure" in refused.text
    assert "failed" in _visible_text(refused.text)
    assert "Those credentials were not accepted." in refused.text


# Defective banners the scan below must catch, keyed by the shape that hid them, and
# grouped by WHICH version of the scan each one got past. The provenance is per entry
# on purpose: this table is documentation as much as it is a test, and a table claiming
# evidence it does not have is the defect this whole file exists to prevent, one level
# up. Add the next hole here, in the shape that found it, under the group it belongs to.
AWKWARD_BANNERS = {
    # Seven the scan before M9.1's fixes looked at and called fine. Each was pasted
    # into a real template beside a real banner and the suite watched to stay green:
    # that version demanded `class` come first and be double-quoted, then read the file
    # with `<div\b[^>]*>` and split the class attribute on whitespace.
    "on an element that is not a div": (
        '<p class="banner banner-failure" role="status">'
        '<span class="banner-label">failed</span>it failed</p>'
    ),
    "with unquoted attribute values": (
        "<div class=banner role=alert>"
        '<span class="banner-label">failed</span>it failed</div>'
    ),
    "whose opening tag holds a `>` inside a Jinja expression": (
        '<div class="banner{% if 1 > 0 %}{% endif %}" role="alert">'
        '<span class="banner-label">failed</span>it failed</div>'
    ),
    "whose failure class is behind a Jinja conditional": (
        """<div class="banner {{ 'banner-failure' if failed else '' }}" role="status">"""
        '<span class="banner-label">note</span>nothing is wrong</div>'
    ),
    # One the old scan already CAUGHT, kept because it is the rest of the family and a
    # reader should not have to guess where the family's edges are. Its `{% if %}` holds
    # no `>`, so `<div\b[^>]*>` ran straight past it and read the role fine.
    "whose role is behind a Jinja block": (
        '<div class="banner" {% if failed %}role="alert"{% endif %}>'
        '<span class="banner-label">failed</span>it failed</div>'
    ),
    "that borrows its role from a data attribute": (
        '<div data-role="status" class="banner">'
        '<span class="banner-label">note</span>nothing is wrong</div>'
    ),
    "whose opening tag cannot be parsed at all": (
        "<div class=\"banner\" role=\"status\" title=don't>"
        '<span class="banner-label">note</span>nothing is wrong</div>'
    ),
    "whose element is never closed": (
        '<div class="banner" role="status"><span class="banner-label">note</span>'
    ),
    # And three the FIRST version of this rewrite passed: it read one occurrence of each
    # attribute, so an attribute written once per branch was judged on whichever branch
    # came first. Found by review rather than by mutating a template.
    "declaring its role in two Jinja branches": (
        '<div class="banner"{% if failed %} role="status"{% else %} role="alert"'
        '{% endif %}><span class="banner-label">failed</span>it failed</div>'
    ),
    "declaring its role in two Jinja branches beside a failure class": (
        '<div class="banner banner-failure"{% if failed %} role="alert"{% else %}'
        ' role="status"{% endif %}><span class="banner-label">failed</span>x</div>'
    ),
    "declaring its class attribute twice": (
        '<div class="banner" role="status" class="banner-failure">'
        '<span class="banner-label">note</span>nothing is wrong</div>'
    ),
}

# …and the same awkwardness written correctly, because a scan that flags everything is
# a scan the next person loosens. Every one of these must be READ as a banner and pass.
SOUND_BANNERS = {
    "on an element that is not a div": (
        '<p class="banner banner-failure" role="alert">'
        '<span class="banner-label">failed</span>it failed</p>'
    ),
    "with unquoted attribute values": (
        "<div class=banner role=status>"
        '<span class="banner-label">note</span>nothing is wrong</div>'
    ),
    "whose class is assembled by Jinja": (
        """<div class="banner {{ 'banner-failure' if failed else '' }}" role="alert">"""
        '<span class="banner-label">failed</span>it failed</div>'
    ),
    "whose attributes are assembled by Jinja": (
        '<div class="banner banner-failure" {% if 1 > 0 %}role="alert"{% endif %}>'
        '<span class="banner-label">failed</span>it failed</div>'
    ),
    "written with its attributes in the other order and single-quoted": (
        "<div role='status' class='banner'>"
        '<span class="banner-label">note</span>nothing is wrong</div>'
    ),
    "wrapping its label behind a child element": (
        '<div class="banner" role="status"><div class="icon"></div>'
        '<span class="banner-label">note</span>nothing is wrong</div>'
    ),
}


def test_no_refusal_anywhere_in_the_panel_is_drawn_as_an_ordinary_notice() -> None:
    """The class, not the instance.

    Two treatments share one element and the difference between them is a safety
    property: an operator who reads a failure as an informational message believes the
    action worked. The rule is mechanical, so it is checked mechanically —
    ``role="alert"`` is a banner that must wear the failure frame, ``role="status"`` is
    a banner that must not, and every one of them carries the word that says which it
    is (UI-PATTERNS §4: severity is carried by the word as well as the weight).

    Over every template, not just the console's: the sign-in screen is outside the
    shell and is exactly where this was missed.

    HOW IT READS THE MARKUP MATTERS AS MUCH AS WHAT IT CHECKS, and that reading now
    lives in ``_banner_faults`` so that the test below can scan the scan. Three
    versions of this passed while being wrong, every one of them because a banner they
    could not PARSE was skipped in silence instead of flagged — see
    ``AWKWARD_BANNERS`` for the shapes, which are the record of the mutations that
    found them.
    """
    checked = 0
    for path in sorted(TEMPLATES.rglob("*.html")):
        faults, found = _banner_faults(path.name, path.read_text())
        assert not faults, "\n".join(faults)
        checked += found

    assert checked >= 3, "this scan found almost nothing, so it proves almost nothing"


def test_the_banner_scan_is_not_blind_to_a_banner_written_in_an_awkward_shape() -> None:
    """The scan above is worth exactly what its reading of the markup is worth.

    A verification that cannot fail is worse than none, because it is believed, and
    this one has been that three times. So it gets a scan of its own: every shape in
    ``AWKWARD_BANNERS`` is a defective banner some version of the scan looked at and
    called fine, and that table says per entry WHICH version, because "we mutated a
    template and watched it stay green" is a claim about evidence and one of the entries
    never had it. They live in the suite rather than in a review comment because the
    next hole will be found the same way and belongs in the same place.

    The second half matters as much: a scan that flags everything gets loosened by the
    first person it inconveniences. ``SOUND_BANNERS`` holds the same awkward syntax
    written correctly, and every one of them must be read as a banner and pass.
    """
    for shape, markup in AWKWARD_BANNERS.items():
        faults, _ = _banner_faults("shape.html", markup)
        assert faults, f"the scan is blind to a banner {shape}"

    for shape, markup in SOUND_BANNERS.items():
        faults, found = _banner_faults("shape.html", markup)
        assert not faults, f"a sound banner {shape} was reported: {faults}"
        assert found == 1, f"a sound banner {shape} was not read as a banner at all"


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
    # Both halves of the rule, because the banner scan over the templates delegates this
    # one banner here: the live region says which of the two it is, as it must in markup.
    assert 'setAttribute("role", "alert")' in js


def _banner_faults(name: str, source: str) -> tuple[list[str], int]:
    """Every way the banners in one template break the rule, and how many were read.

    The reading, not the rule, is where this has gone wrong before, so it is one
    function that a test can point at markup of its own rather than a loop buried in a
    test that can only ever be given the real templates.

    A template is not HTML and must not be read as though it were. Jinja's own lexer
    reduces every construct to something that can neither open, close nor quote an
    element (``_html_only``); whole tags are then matched on any element, quote-aware,
    and their attributes read out in any order and any quoting. What closes the class
    rather than four instances is ``_unparsed_elements``: anything element-shaped that
    the tag pattern could NOT read is itself a fault, so "it did not match, so it
    vanished" stops being a way to pass.

    What it still cannot see, said out loud so a green run is not read as more than it
    is: a class name that arrives through a variable rather than as a literal names
    nothing here, whether the variable comes from Python (``class="{{ css }}"``) or from
    a ``{% set cls = 'banner-failure' %}`` three lines up in the same template. Write
    the literal into the class attribute. A banner built in JavaScript is not scanned
    here either — ``test_a_failure_inside_a_dialog_is_stated_inside_that_dialog`` holds
    both halves of the rule for that one.
    """
    markup, line_of = _html_only(source)
    openings = list(TAG.finditer(markup))
    faults = _unparsed_elements(name, markup, line_of, openings)
    checked = 0

    for opening in openings:
        # Every occurrence of each attribute, not the first: an attribute written once
        # per Jinja branch is two occurrences of it, and judging the banner on whichever
        # came first passed a refusal drawn as a notice in silence.
        classes = _attributes(opening.group(0), "class")
        declared = " ".join(classes)
        if "banner" not in declared.split():
            continue
        checked += 1
        where = f"{name}:{line_of[opening.start()]}"
        roles = _attributes(opening.group(0), "role")
        role = roles[0].strip().lower() if roles else ""
        # A substring of the whole attribute rather than one of its tokens. Belt and
        # braces after the flattening rather than load-bearing today — nothing in
        # AWKWARD_BANNERS needs it — but it holds if a future construct leaves the class
        # name glued to its neighbour, and the two ways of guessing wrong are not
        # symmetric: calling a notice a failure fails this suite, calling a failure a
        # notice ships an operator a refusal that reads as information.
        failing = "banner-failure" in declared
        # This element's own content, up to ITS closing tag — the word must be on the
        # banner that was found, not merely somewhere in the file it lives in.
        inside = _element_body(markup, opening)

        if len(classes) > 1 or len(roles) > 1:
            faults.append(
                f"{where} — a banner that declares class or role twice. A browser keeps"
                " the first and drops the second, and one element that renders as either"
                " banner cannot have the role it renders paired with the class it"
                " renders beside it; write the two banners as two elements, the way"
                " panel/banner.html and panel/friends_table.html do"
            )
        elif role not in {"alert", "status"}:
            faults.append(f"{where} — a banner that says nothing about which of the two it is")
        elif role == "alert" and not failing:
            faults.append(f"{where} — a refusal drawn as an ordinary notice")
        elif role == "status" and failing:
            faults.append(f"{where} — a notice drawn as a failure")
        if inside is None:
            faults.append(f"{where} — a banner whose element never closes")
        elif "banner-label" not in inside:
            faults.append(f"{where} — a banner with no word on it")

    return faults, checked


def _html_only(source: str) -> tuple[str, list[int]]:
    """A Jinja template with its Jinja reduced to something that cannot fake markup.

    Templates are not HTML, and most of the holes the banner scan has had came from
    reading them as though they were: ``{% if 1 > 0 %}`` ends an opening tag that is
    not over, ``{{ 'banner-failure' if failed }}`` hides a class name behind quotes,
    and a ``{% if %}`` between two attributes hides every attribute after it.

    So the source is lexed by Jinja itself — nothing here guesses where a construct
    starts or ends — and every character of every non-``data`` token that is not part
    of a word becomes a space. What survives is ordinary HTML in which an expression
    still shows its literals, so ``class="banner {{ 'banner-failure' if f }}"`` reads
    as the two class names it can render, and ``class="banner{% if x %}"`` still reads
    as ``banner`` rather than as ``banner{%``. Jinja comments go the same way, which is
    both why a banner drawn inside ``{# … #}`` is not scanned and why one cannot hide
    inside a comment either.

    What is guaranteed is that the markup and the line map are built from the same
    pieces, so an offset into one indexes the other and reports the source line that
    character came from. What is NOT guaranteed — and a later reader reusing this would
    assume it — is that the result is the same length as the source or that an offset
    indexes it: whitespace control (``{%-``) eats characters the source had, and a token
    value need not be its source text. Line numbers therefore come from the lexer's own
    token positions and never from counting newlines.
    """
    html: list[str] = []
    lines: list[int] = []
    for lineno, kind, value in JINJA.lex(source):
        piece = value if kind == "data" else re.sub(r"[^\w-]", " ", value)
        html.append(piece)
        at = lineno
        for character in piece:
            lines.append(at)
            at += character == "\n"
    return "".join(html), lines


def _unparsed_elements(
    name: str, markup: str, line_of: list[int], openings: list[re.Match[str]]
) -> list[str]:
    """Nothing element-shaped may leave this scan in silence.

    Every way the banner scan has passed while being wrong was an element its pattern
    could not match and therefore never looked at. Fixing the shapes that were found
    closes those instances; this closes the class. The gaps between the tags that DID
    match are checked for anything still shaped like an opening tag — so a banner
    written in a syntax nobody has thought of is a red test rather than an unexamined
    refusal.
    """
    faults = []
    cursor = 0
    spans = [(opening.start(), opening.end()) for opening in openings]
    for start, end in [*spans, (len(markup), len(markup))]:
        stray = re.search(r"<[a-zA-Z]", markup[cursor:start])
        if stray:
            at = cursor + stray.start()
            faults.append(
                f"{name}:{line_of[at]} — an element this scan cannot parse, which is "
                f"how a bad banner gets skipped in silence: {markup[at : at + 60]!r}"
            )
        cursor = end
    return faults


def _element_body(markup: str, opening: re.Match[str]) -> str | None:
    """What is inside an element, up to ITS OWN closing tag rather than the first one.

    ``markup[opening.end():].split("</div>", 1)[0]`` stops at the first close in the
    file, so a banner whose first child is a wrapper — an icon, say — reports "no word
    on it" while wearing its label. No banner has one yet; the first to get one would
    have met this. Returns None when the element never closes, which the caller reports
    as itself instead of as a missing label.
    """
    if opening.group(0).endswith("/>"):
        return ""
    depth = 1
    rest = markup[opening.end() :]
    for step in re.finditer(
        rf"""<(/?){opening.group(1)}\b(?:"[^"]*"|'[^']*'|[^>"'])*>""", rest, flags=re.I
    ):
        depth += -1 if step.group(1) else 1
        if depth == 0:
            return rest[: step.start()]
    return None


def _attributes(tag: str, name: str) -> list[str]:
    """EVERY value an attribute is given in one opening tag, in the order written.

    Deliberately forgiving about the markup and unforgiving about the rule: the scan
    above exists to catch a hand-written screen that got a banner wrong, and a screen
    written by hand is exactly where ``role`` comes before ``class``, where a value is
    in single quotes, and where a value has no quotes at all — that last one used to
    return "" and drop the element out of the scan as "not a banner".

    All of them rather than the first, because ``{% if x %}role="status"{% else %}
    role="alert"{% endif %}`` is one element declaring the attribute twice, and reading
    whichever came first judged such a banner on the branch that happened to be written
    first — a refusal drawn as a notice, passing in silence.

    ``data-role=`` is not ``role=``: with a word boundary in front, a banner that
    declared no role at all borrowed one from whichever data attribute came first, and
    passed. Returns [] when the attribute is absent, which the caller reads as "this
    banner declares nothing", not as "this is fine".
    """
    return [
        next(group for group in found.groups() if group is not None)
        for found in re.finditer(
            rf"""(?<![-\w]){name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
            tag,
            flags=re.I,
        )
    ]


def _visible_text(html: str) -> str:
    """The page with its comments, tags and attributes removed.

    Needed because this codebase explains itself in template comments, and those
    comments legitimately say "friend" — the rule decision 9 sets is about what an
    operator READS, not about what the file contains.
    """
    without_comments = re.sub(r"\{#.*?#\}", "", html, flags=re.S)
    return re.sub(r"<[^>]*>", " ", without_comments)
