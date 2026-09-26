"""No two buttons on one screen answer to one name — M26, the third acceptance walk.

WHAT: that with any dialog open, the button which SUBMITS it is addressable — its name is
      not the name of some other button on the page, and no name is a substring of
      another's — and that the two tall dialogs keep their actions in view rather than
      below the fold.
WHY:  the walk could not submit "Add a node" in a 1440x900 window. The form is taller
      than the viewport, its submit button is below the fold, and that button was called
      "add node" — the same name as the header button on the screen behind it, which is
      still in the document while the dialog is open. Pressing "add node" re-opened the
      form. It is the second walk a form has cost: walk 2 ran its budget out inside the
      establish-hop dialog and never reached the milestone's fourth "done when".

      Both halves are here because either one alone still loses the walk. A button that
      is reachable but ambiguous is pressed and does the wrong thing; an unambiguous one
      below the fold is never pressed at all.
HOW:  the browser's own view of the page: a screen, plus the dialog markup htmx swaps
      into its ``#dialog-slot``. Every ``<button>`` in each is collected with its visible
      text, and the dialog's names are compared against the screen's — ACROSS the two and
      never within either, because two rows of one table legitimately carry two buttons
      called "apply" and a press picks the row first.

      NAMES ARE COMPARED THE WAY THE THING THAT PRESSES THEM MATCHES — case-insensitively
      and by CONTAINMENT, not equality. That is Playwright's ``get_by_role(name=…)``
      without ``exact``, which is what ``scripts/acceptance/drive.py`` calls and therefore
      what an acceptance walk meets, and it is also close to how a person skims a page.
      So "tear down" and "tear down the hop" are one name for this file's purposes, and
      renaming a button by appending to it fixes nothing.

      Boundary: this proves a name is unique, not that it is GOOD, and it proves a CSS
      rule exists rather than that a browser drew it. Whether a button says the right
      thing is a person's judgement on a dialog, and the fold is measured by a walk.
"""

import html.parser
import re

import pytest

from control.app.services import transports as transports_service

# Where each dialog is fetched from, and the screen it is opened over. Both halves are
# needed: a dialog is judged against the buttons that stay on the page behind it, and the
# screen is where the button that opened it lives.
#
# The dialogs reached from INSIDE another dialog are deliberately absent — withdrawing or
# removing a transport is opened from the transports dialog and swapped into the same
# slot, so its opener is gone from the document by the time its confirmation is drawn and
# no two buttons are ever on screen together. This file is about the pairs that are.
CREATION_DIALOGS = (
    ("/panel/nodes", "/panel/nodes/new"),
    ("/panel/users", "/panel/users/new"),
    ("/panel/hops", "/panel/hops/new"),
)


class _Buttons(html.parser.HTMLParser):
    """Every ``<button>`` in a document, as the text a person and a driver address it by."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: list[str] = []
        self._depth = 0
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "button":
            self._depth += 1
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._depth:
            self._depth -= 1
            name = " ".join("".join(self._text).split())
            if name:
                self.names.append(name.lower())

    def handle_data(self, data: str) -> None:
        if self._depth:
            self._text.append(data)


def button_names(markup: str) -> list[str]:
    parser = _Buttons()
    parser.feed(markup)
    return parser.names


async def a_node(client, *, name: str, address: str, resolver: str | None = None) -> str:
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": address,
            "location_label": "Testland",
            # The runbook requires one on a node that dials a hop, and without it this
            # fleet's entry end cannot be rendered — the Nodes screen then draws its
            # drift cell from a failure, which is a different scenario than this file's.
            **({"resolver": resolver} if resolver else {}),
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def a_fleet_with_a_row_on_every_screen(client, reality_params) -> None:
    """One of everything, so every row's own buttons are drawn behind the dialog.

    An empty screen is the one place this cannot fail, which is exactly why the fixture
    is not empty: the walk's collision was between a dialog and a ROW-level button's
    neighbourhood, and a table with no rows renders neither.
    """
    entry_id = await a_node(
        client, name="entry-1", address="192.0.2.20", resolver="192.0.2.53"
    )
    leaf_id = await a_node(client, name="exit-1", address="192.0.2.10")
    enabled = await client.post(
        f"/api/nodes/{entry_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    await client.post(f"/api/nodes/{entry_id}/state", json={"state": "active"})

    transport = transports_service.hop_transports()
    assert transport, "this image ships nothing that can carry a hop"
    side = {
        "port": 51820,
        "mtu": 1280,
        "junk_packet_count": 4,
        "junk_packet_min_size": 40,
        "junk_packet_max_size": 70,
        "init_packet_magic_header": 1020327031,
        "response_packet_magic_header": 979482666,
        "underload_packet_magic_header": 1030002620,
        "transport_packet_magic_header": 1859490837,
    }
    hop = await client.post(
        "/api/hops",
        json={
            "entry_node_id": entry_id,
            "leaf_node_id": leaf_id,
            "transport_name": transport[0],
            "entry_params": {
                **side,
                "tunnel_address": "10.44.0.1/24",
                "peer_tunnel_address": "10.44.0.2/24",
            },
            "leaf_params": {
                **side,
                "tunnel_address": "10.44.0.2/24",
                "peer_tunnel_address": "10.44.0.1/24",
            },
        },
    )
    assert hop.status_code == 201, hop.text

    user = await client.post("/api/users", json={"nickname": "mira"})
    assert user.status_code == 201, user.text


# What every dialog's two closing buttons are called. They are excluded from the
# comparison below because they are the one name this console deliberately repeats — a
# walk pressing "cancel" wants whichever dialog is open, and a screen carries none.
CLOSING = ("cancel", "close")


def also_addresses(dialog: list[str], screen: list[str]) -> list[tuple[str, str]]:
    """Every (dialog button, screen button) pair one name would address at once.

    Only across the two, never within either. Two rows of one table legitimately carry
    two buttons called "apply" — a person and a driver alike pick the row first, by the
    node's own name in the cell beside it — and a rule that refused that would be a rule
    against tables. What no press can recover from is a dialog's own action sharing its
    name with something on the page the dialog is drawn over.
    """
    return sorted(
        (inside, behind)
        for inside in dialog
        if inside not in CLOSING
        for behind in screen
        if behind not in CLOSING and (inside in behind or behind in inside)
    )


@pytest.mark.parametrize(("screen", "dialog"), CREATION_DIALOGS)
async def test_a_dialogs_own_buttons_are_not_the_screens(
    client, reality_params, screen: str, dialog: str
) -> None:
    """The walk's finding, over every dialog an operator creates something in.

    Red against the previous commit on all three: "add node", "add user" and "establish
    hop" each named both the button that opens the dialog and the button that submits it.
    """
    await a_fleet_with_a_row_on_every_screen(client, reality_params)

    behind = await client.get(screen)
    assert behind.status_code == 200, behind.text
    opened = await client.get(dialog)
    assert opened.status_code == 200, opened.text

    # What the browser is holding: the screen, with the dialog swapped into its slot.
    inside = button_names(opened.text)
    on_screen = button_names(behind.text)
    assert inside and on_screen, (
        "no buttons were found at all, so this test is reading the wrong thing"
    )

    collisions = also_addresses(inside, on_screen)

    assert not collisions, (
        f"with {dialog} open, these names address a button inside it AND one on the "
        f"screen behind it: {collisions} — a press aimed at the dialog's own action "
        "lands on the screen behind it, which is what cost M26's third walk its budget"
    )


async def test_the_confirmation_dialogs_do_not_share_their_rows_name(
    client, reality_params
) -> None:
    """The same shape one screen over, and the two pairs that had it.

    A confirmation is opened from a row and swapped into the dialog slot while the table
    stays on the page — so "revoke" beside "revoke" and "tear down" beside "tear down"
    were the same ambiguity as the walk's, on the two actions that cannot be undone.
    """
    await a_fleet_with_a_row_on_every_screen(client, reality_params)

    users = await client.get("/panel/users")
    user_id = re.search(r"/panel/users/([0-9a-f-]{36})/revoke", users.text)
    assert user_id, "no revoke button was rendered, so this test proves nothing"
    revoke = await client.get(f"/panel/users/{user_id.group(1)}/revoke")

    hops = await client.get("/panel/hops")
    hop_id = re.search(r"/panel/hops/([0-9a-f-]{36})/dissolve", hops.text)
    assert hop_id, "no tear-down button was rendered, so this test proves nothing"
    tear_down = await client.get(f"/panel/hops/{hop_id.group(1)}/dissolve")

    for screen, dialog, what in (
        (users, revoke, "revoke"),
        (hops, tear_down, "tear down"),
    ):
        collisions = also_addresses(button_names(dialog.text), button_names(screen.text))
        assert not collisions, (
            f"with the {what} confirmation open, {collisions} addresses a button in the "
            "dialog and one in the table it was opened from"
        )


def test_a_tall_dialog_keeps_its_actions_in_view() -> None:
    """The other half of the walk's finding: the submit was below the fold.

    The two dialogs that can outgrow a laptop's viewport already cap their height and
    scroll (``.dialog-wide``, ``.dialog-hop``), which keeps the BOX on the page and says
    nothing about its buttons — the operator meets a form whose only visible control is
    the field they last filled in, which is indistinguishable from a form that does not
    submit.

    Asserted on the stylesheet because that is where the rule lives. It is a weaker claim
    than "a browser drew it in 1440x900", and the acceptance walk is what makes the
    stronger one.
    """
    css = (
        " ".join(
            open("control/app/static/app.css", encoding="utf-8").read().split()
        )
    )

    for scrolls in (".dialog-wide", ".dialog-hop"):
        assert f"{scrolls} {{ width:" in css or f"{scrolls} {{" in css, (
            f"{scrolls} is no longer a rule in this stylesheet, so this test is reading "
            "the wrong file"
        )

    sticky = re.search(
        r"\.dialog-wide \.dialog-actions,\s*\.dialog-hop \.dialog-actions \{([^}]*)\}",
        css,
    )
    assert sticky, (
        "the tall dialogs' actions carry no rule of their own, so nothing keeps the "
        "submit button on screen when the form is taller than the window"
    )
    assert "position: sticky" in sticky.group(1), sticky.group(1)
    assert "bottom: 0" in sticky.group(1), sticky.group(1)
    assert "background:" in sticky.group(1), (
        "the pinned actions are transparent, so the form scrolls through them"
    )
