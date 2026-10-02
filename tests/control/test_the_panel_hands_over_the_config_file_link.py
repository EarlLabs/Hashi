"""The link dialog and the API hand an operator the URL that delivers a config file — M24.

WHAT: for every combination of offered transports a user can hold, what the link dialog
      (``/panel/users/{id}/subscription``, the one the Users screen's "show link" and the
      add-user exchange both open) and ``GET /api/users/{id}/subscription`` hand over:
      the subscription link always, and the config-file link beside it when — and only
      when — the user holds a credential on an offered transport that declares the
      client-config-file shape. Each labelled with the app it is for and what it carries.
WHY:  M24. ``GET /sub/{token}?format=client-config-file`` existed and worked, and no
      screen ever showed it, so an operator following the panel handed a user on a
      WireGuard-family-only node a link that answers an empty document. The owner chose
      one URL per config shape over one link that answers by what a node serves
      (``docs/decisions.md``, 2026-10-02).
HOW:  every URL asserted on is then FETCHED, anonymously, exactly as shown — "the panel
      shows a URL" is not the done-when; "following only what the panel shows gets a
      user something that works" is. The transports used are chosen from the registry by
      what they DECLARE (``subscription_formats``), never by name, so a transport added
      later is exercised by arriving.

Every test here is red on the commit before M24: the API had no ``config_file_url``, and
the dialog printed one URL and the words "One URL, every serving node" whatever the user
held.
"""

import html
import io
import logging
import re
import zipfile
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select

from control.app.models import AuditEntry, NodeState
from control.app.services import console as console_service
from control.app.services import nodes as nodes_service
from control.app.services import transports as transports_service
from edge import registry
from edge.registry import SubscriptionFormat

# Offerable transports that are a config file and not a link, and offerable ones that
# ride in the link — by declaration.
FILE_ONLY = sorted(
    name
    for name, meta in registry.discover().items()
    if SubscriptionFormat.CLIENT_CONFIG_FILE in meta.subscription_formats
    and not meta.subscription_expressible
    and name in transports_service.offerable_transports()
)

pytestmark = pytest.mark.skipif(
    not FILE_ONLY, reason="this image ships no offerable config-file transport"
)

# A superset of the operator-supplied knobs a config-file transport may declare, filtered
# per transport against its own model — the same literal ``test_the_console.py`` uses,
# for the same reason: one per protocol would be a list to extend.
_FILE_KNOBS: dict[str, object] = {
    "port": 51821,
    "mtu": 1280,
    "tunnel_address": "10.91.0.1/24",
    "peer_tunnel_address": "10.91.0.2/24",
    "junk_packet_count": 4,
    "junk_packet_min_size": 40,
    "junk_packet_max_size": 80,
    "init_packet_magic_header": 1020327352,
    "response_packet_magic_header": 2060487442,
    "underload_packet_magic_header": 3679305607,
    "transport_packet_magic_header": 1436947798,
}

FILE_HEADING = console_service.LINK_HEADINGS[SubscriptionFormat.CLIENT_CONFIG_FILE]
LINK_HEADING = console_service.LINK_HEADINGS[SubscriptionFormat.V1_URI_LIST]


def _reading(markup: str) -> str:
    """What a person reads in a fragment: tags dropped, entities decoded, spaces collapsed."""
    text = re.sub(r"\{#.*?#\}", " ", markup, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


async def _a_node(client, session, name: str, address: str) -> str:
    created = await client.post(
        "/api/nodes",
        json={"name": name, "address": address, "location_label": "Testland"},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _offer_file(client, node_id: str) -> str:
    transport = FILE_ONLY[0]
    declared = set(registry.profile(transport).params_model.model_fields)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": transport,
            "params": {k: v for k, v in _FILE_KNOBS.items() if k in declared},
            "pool_size": 50,
        },
    )
    assert enabled.status_code == 201, enabled.text
    return enabled.json()["id"]


async def _offer_link(client, node_id: str, reality_params) -> str:
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    return enabled.json()["id"]


async def _serve(session, node_id: str) -> None:
    """In service without an SSH push — what is under test is the panel, not the apply."""
    await nodes_service.set_node_state(session, node_id=node_id, state=NodeState.ACTIVE)


async def _user(client, nickname: str) -> str:
    created = await client.post("/api/users", json={"nickname": nickname})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _path(url: str) -> str:
    """The URL as the anonymous client asks for it: path and query, host dropped."""
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def _shown_urls(dialog: str) -> list[str]:
    """Every URL the dialog prints as text inside a code block, in order."""
    return [
        html.unescape(found).strip()
        for found in re.findall(r'class="mono dialog-code"[^>]*>([^<]*)<', dialog)
    ]


async def _a_real_archive(anonymous, url: str) -> list[str]:
    fetched = await anonymous.get(_path(url))
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers["content-type"] == "application/zip"
    held = zipfile.ZipFile(io.BytesIO(fetched.content))
    names = held.namelist()
    assert names and all(held.read(name).strip() for name in names), names
    assert console_service.LINK_CARRIES_NOTHING_YET not in names
    return names


async def test_a_config_file_only_user_is_handed_a_link_that_works(
    client, session, anonymous
) -> None:
    """The acceptance line, without the device: follow only what the panel shows.

    A user on a node serving only a config-file transport. The dialog shows two links;
    the one labelled for the config file, fetched exactly as printed, is an archive with
    this user's configuration in it. The subscription link is still shown — the owner's
    decision puts the second BESIDE it — and says, under itself, that it carries nothing
    for this person today, which the fetch then confirms.
    """
    node_id = await _a_node(client, session, "by-file-only", "192.0.2.61")
    await _offer_file(client, node_id)
    await _serve(session, node_id)
    user_id = await _user(client, "anna")

    dialog = await client.get(f"/panel/users/{user_id}/subscription")
    assert dialog.status_code == 200, dialog.text
    said = _reading(dialog.text)
    shown = _shown_urls(dialog.text)

    assert len(shown) == 2, shown
    subscription, config_file = shown
    assert config_file == f"{subscription}?format=client-config-file"
    assert said.index(LINK_HEADING) < said.index(FILE_HEADING), said

    # Labelled: which app takes each, and what each carries for THIS person.
    assert console_service.LINK_USES[SubscriptionFormat.CLIENT_CONFIG_FILE] in said
    assert console_service.LINK_USES[SubscriptionFormat.V1_URI_LIST] in said
    assert (
        console_service.LINK_CARRIES.format(nickname="anna", transports=FILE_ONLY[0])
        in said
    )
    assert console_service.LINK_CARRIES_NOTHING_YET.format(nickname="anna") in said
    # And the sentence that was false on this screen is gone from it.
    assert console_service.LINKS_ONE not in said
    assert console_service.LINKS_SEVERAL.format(count=2) in said
    assert f"copy {FILE_HEADING}" in said and f"copy {LINK_HEADING}" in said

    await _a_real_archive(anonymous, config_file)
    plain = await anonymous.get(_path(subscription))
    assert plain.status_code == 200 and plain.text == "", (
        "the subscription link was labelled as carrying nothing and carried something"
    )

    # The API hands over the same two, from the same composer.
    issued = (await client.get(f"/api/users/{user_id}/subscription")).json()
    assert issued == {"url": subscription, "config_file_url": config_file}


async def test_a_link_only_user_is_handed_one_link_and_no_config_file_link(
    client, session, reality_params
) -> None:
    """The other half of "only when": nothing about a file for a person who holds none."""
    node_id = await _a_node(client, session, "by-link-only", "192.0.2.62")
    await _offer_link(client, node_id, reality_params)
    await _serve(session, node_id)
    user_id = await _user(client, "boris")

    dialog = (await client.get(f"/panel/users/{user_id}/subscription")).text
    said = _reading(dialog)
    shown = _shown_urls(dialog)

    assert len(shown) == 1 and "?" not in shown[0], shown
    assert "format=" not in dialog
    assert FILE_HEADING not in said
    assert console_service.LINKS_ONE in said
    assert (
        console_service.LINK_CARRIES.format(nickname="boris", transports="vless-reality")
        in said
    )
    assert "copy link" in said

    issued = (await client.get(f"/api/users/{user_id}/subscription")).json()
    assert issued == {"url": shown[0], "config_file_url": None}


async def test_a_user_holding_both_shapes_is_told_which_link_carries_which(
    client, session, anonymous, reality_params
) -> None:
    """One node serving both families: each link names only what is really in it."""
    node_id = await _a_node(client, session, "by-both", "192.0.2.63")
    await _offer_link(client, node_id, reality_params)
    await _offer_file(client, node_id)
    await _serve(session, node_id)
    user_id = await _user(client, "carla")

    dialog = (await client.get(f"/panel/users/{user_id}/subscription")).text
    said = _reading(dialog)
    subscription, config_file = _shown_urls(dialog)

    link_says = said[said.index(LINK_HEADING) : said.index(FILE_HEADING)]
    file_says = said[said.index(FILE_HEADING) :]
    assert "vless-reality" in link_says and FILE_ONLY[0] not in link_says, link_says
    assert FILE_ONLY[0] in file_says and "vless-reality" not in file_says, file_says
    assert console_service.LINK_CARRIES_NOTHING_YET.format(nickname="carla") not in said

    await _a_real_archive(anonymous, config_file)
    plain = await anonymous.get(_path(subscription))
    assert plain.status_code == 200 and plain.text, "the link said it carried vless-reality"


async def test_a_withdrawn_config_file_row_takes_its_link_away_and_a_degraded_node_does_not(
    client, session
) -> None:
    """Which rows count: offered ones on nodes that may serve again.

    Withdrawing keeps the credential minted (``nodes.set_transport_enabled``) but the
    token answers nothing from that row, so the link goes. A node that is merely degraded
    keeps it: the person's tunnel will be there again, and an operator handing over the
    link during a bad minute must not hand over the wrong one for good. A retired node
    takes it away, because nothing serves from it again.
    """
    node_id = await _a_node(client, session, "by-file-states", "192.0.2.64")
    row_id = await _offer_file(client, node_id)
    await _serve(session, node_id)
    user_id = await _user(client, "dana")

    async def config_file_url() -> str | None:
        return (await client.get(f"/api/users/{user_id}/subscription")).json()[
            "config_file_url"
        ]

    assert await config_file_url()

    await nodes_service.set_node_state(session, node_id=node_id, state=NodeState.DEGRADED)
    assert await config_file_url(), "a degraded node's user lost the link that will work again"

    withdrawn = await client.post(f"/api/transports/{row_id}/state", json={"enabled": False})
    assert withdrawn.status_code == 200, withdrawn.text
    assert await config_file_url() is None
    dialog = _reading((await client.get(f"/panel/users/{user_id}/subscription")).text)
    assert FILE_HEADING not in dialog

    restored = await client.post(f"/api/transports/{row_id}/state", json={"enabled": True})
    assert restored.status_code == 200, restored.text
    assert await config_file_url()

    await nodes_service.set_node_state(session, node_id=node_id, state=NodeState.RETIRED)
    assert await config_file_url() is None


async def test_the_add_user_exchange_hands_over_the_config_file_link_too(
    client, session
) -> None:
    """The dialog is opened from more than one place; the one that creates the user counts."""
    node_id = await _a_node(client, session, "by-file-add", "192.0.2.65")
    await _offer_file(client, node_id)
    await _serve(session, node_id)

    added = await client.post("/panel/users", data={"nickname": "emil"})
    assert added.status_code == 200, added.text
    shown = _shown_urls(added.text)
    assert len(shown) == 2 and shown[1].endswith("?format=client-config-file"), shown
    assert FILE_HEADING in _reading(added.text)


async def test_no_new_place_records_either_link(
    client, session, anonymous, caplog
) -> None:
    """A bearer credential in a path: shown in a dialog and nowhere else.

    Every log record raised while the two links are composed, displayed, returned by the
    API and fetched carries neither the token nor the query string; no audit row holds the
    token; and both operator responses forbid storage.
    """
    caplog.set_level(logging.DEBUG)
    node_id = await _a_node(client, session, "by-file-quiet", "192.0.2.66")
    await _offer_file(client, node_id)
    await _serve(session, node_id)
    user_id = await _user(client, "fern")

    dialog = await client.get(f"/panel/users/{user_id}/subscription")
    issued = await client.get(f"/api/users/{user_id}/subscription")
    token = urlsplit(issued.json()["url"]).path.rsplit("/", 1)[-1]
    await _a_real_archive(anonymous, issued.json()["config_file_url"])

    # The application's records only. ``httpx`` and ``httpcore`` are the TEST's client —
    # in production that is a user's device, not this process — and httpx logs every URL
    # it requests at INFO, which is its own business and not a place this server records.
    logged = "\n".join(
        f"{record.name}: {record.getMessage()}"
        for record in caplog.records
        if not record.name.startswith(("httpx", "httpcore"))
    )
    assert "control.app" in logged, "nothing was captured, so nothing was checked"
    assert token not in logged
    assert "format=client-config-file" not in logged

    for response in (dialog, issued):
        assert "no-store" in response.headers["cache-control"]
    # Text inside a block, never an attribute a browser keeps.
    assert not re.search(r'(href|title|value|hx-get)="[^"]*' + re.escape(token), dialog.text)

    rows = (await session.execute(select(AuditEntry))).scalars().all()
    for row in rows:
        assert token not in " ".join(str(value) for value in vars(row).values())


def test_every_shape_a_transport_can_declare_has_a_label() -> None:
    """A shape with no heading or no use would be a link handed over unlabelled."""
    declared = {
        shape for meta in registry.discover().values() for shape in meta.subscription_formats
    }
    assert declared <= set(console_service.LINK_HEADINGS) & set(console_service.LINK_USES)
    assert set(SubscriptionFormat) <= set(console_service.LINK_HEADINGS)


def test_every_sentence_about_a_config_file_transport_names_the_link_that_delivers_it() -> None:
    """The Nodes row, the enable dialog and the re-offer toast used to say "only by asking
    for that shape" — true, and an instruction to compose a credential by hand. Each now
    names the link the dialog actually prints, by the heading it prints it under."""
    for sentence in (
        console_service.OFFER_NOT_IN_THE_LINK,
        console_service.ENABLING_NOT_IN_THE_LINK,
        console_service.offer_summary("n", "t", deliverable=False),
    ):
        assert FILE_HEADING in sentence, sentence
        assert "by asking for" not in sentence, sentence


async def test_no_screen_still_promises_one_url(client, session) -> None:
    """Done-when 2: the screens that described a user's link as ONE URL said so to an
    operator whose users will hold two. Read off the rendered screens, with a serving
    config-file node and nobody on it yet — the state every empty-screen sentence is
    printed in."""
    node_id = await _a_node(client, session, "by-file-empty", "192.0.2.67")
    await _offer_file(client, node_id)
    await _serve(session, node_id)
    for path in ("/panel/users", "/panel/users/table", "/panel/users/new", "/panel/overview/body"):
        body = await client.get(path)
        assert body.status_code == 200, (path, body.status_code)
        said = _reading(body.text).lower()
        assert "one subscription url" not in said, path
        assert "the one url each" not in said, path
