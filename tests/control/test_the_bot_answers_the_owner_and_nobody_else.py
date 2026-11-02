"""The bot acts on the owner's commands and on nothing else — M37.2, M38.1, M38.2.

WHAT: that ``/adduser`` from the owner's own account adds the people named, pushes them
      and replies with links that answer on ``/sub/``; that a refusal is the panel's
      sentence, creates nothing and points at the panel only when the name is taken;
      that ``/adduser@<bot>`` is ``/adduser``; that a node the add could not update is
      named with the panel's sentence and ``/apply`` under it, and a node it did update
      is not; that ``/nodes`` names exactly the serving nodes that are behind, each with
      its ``/apply``, or says in one sentence that none is, and dials nothing for it;
      that ``/apply <name>`` is the Nodes screen's Apply — the node ends in the state
      and with the trail the API's apply leaves, the reply is the panel's sentence for
      what was applied and what could not be measured, a refusal or a failure is the
      sentence the API envelope carries, and nothing of a checker's words or a key ever
      reaches the chat, even when the envelope's own sentence quotes one; that an
      unknown name is refused naming what was typed; that everything else the owner
      sends gets the usage line; that a stranger — any other id, the owner's id in a
      group, a forward, an edit — gets no call, no user, no apply and no log record
      naming them; that no reply text reaches a log; and that a reply too long for one
      Telegram message is split where a person's links stay together.
WHY:  anyone can find a bot by name and message it. The gate and the silence are what
      make a bot that creates VPN users safe to leave reachable, and silence is the one
      property a green run cannot show by accident: these tests record every request the
      fake Telegram was given and every log record the process wrote, and assert on
      both being empty.
HOW:  ``handle_update`` is driven directly with updates shaped as Telegram shapes them,
      against the suite's real schema and a ``TelegramApi`` on an ``httpx.MockTransport``
      that records what was sent. Nodes are ``accepting_nodes`` so the add's push lands,
      with one host turned unreachable where the test is about a node that could not be
      told. Logging is configured as the process configures it and driven to DEBUG at
      the root, the way the client's own test does.
"""

import base64
import json
import logging
import types
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from control.app.main import configure_logging
from control.app.models import AuditAction, AuditEntry, NodeTransport
from control.app.services import apply, console, nodes, onboarding, telegram_bot, users
from control.app.services.apply import NotUpdated
from control.app.services.telegram_api import TelegramApi, TelegramCallFailed
from control.app.services.telegram_bot import (
    ADDING,
    APPLY_DID_NOT_COMPLETE,
    APPLY_IT,
    APPLYING,
    NOTHING_ADDED,
    NOTHING_BEHIND,
    SEE_THE_PANEL,
    TELEGRAM_MESSAGE_LIMIT,
    USAGE,
    handle_update,
)
from edge.bootstrap.ssh import NodeUnreachable
from edge.health import listening

from .conftest import GENERATED_SSH_KEY, AcceptingNode, a_user_no_node_was_told_about

TOKEN = "110201543:TEST-TOKEN-NEVER-REAL-9f3b2c1d8e7a6b5c4d3e2f1a0b9c8d7e"
API_URL = "https://bot-api.test"
OWNER = 424242
STRANGER = 777001

# RFC 5737 documentation addresses — nothing is dialled; IP literals so neither node is a
# delivery host in this suite.
ENTRY_ADDRESS = "192.0.2.71"
LEAF_ADDRESS = "192.0.2.72"


class FakeTelegram:
    """Every request the bot made, and the text of every message it sent, in order."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.failing: set[int] = set()  # which sendMessage calls (1-based) fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        is_send = request.url.path.endswith("/sendMessage")
        index = len(self.sends)
        self.requests.append(request)
        if is_send and index in self.failing:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.requests)}})

    @property
    def sends(self) -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in self.requests
            if request.url.path.endswith("/sendMessage")
        ]

    @property
    def texts(self) -> list[str]:
        return [payload["text"] for payload in self.sends]


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
async def api(telegram: FakeTelegram):
    async with TelegramApi(
        token=TOKEN, api_url=API_URL, transport=httpx.MockTransport(telegram)
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def restore_levels():
    """``configure_logging`` pins loggers for the process; put back what this file moves."""
    names = ("", "httpx", "httpcore", "control", "edge", "asyncssh", "sqlalchemy.engine")
    before = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)


def an_update(
    text: str | None = "/adduser mira",
    *,
    sender: Any = OWNER,
    chat: int = OWNER,
    chat_type: str = "private",
    key: str = "message",
    **extra: Any,
) -> dict[str, Any]:
    """One update as Telegram shapes it; ``key`` is ``message`` or ``edited_message``."""
    message: dict[str, Any] = {
        "message_id": 1,
        "date": 1_700_000_000,
        "chat": {"id": chat, "type": chat_type},
        **extra,
    }
    if sender is not None:
        message["from"] = {"id": sender, "is_bot": False, "first_name": "Someone"}
    if text is not None:
        message["text"] = text
    return {"update_id": 100, key: message}


async def the_bot_gets(session, api, settings, update: dict[str, Any], owner: Any = OWNER):
    await handle_update(
        session, api, update, owner_id=owner, base_url=settings.public_base_url
    )


class UnreachableNode:
    """A host the control plane cannot open a session to: refused before anything is sent."""

    learned_host_key = None

    async def __aenter__(self):
        raise NodeUnreachable("could not connect to the node: connection timed out")

    async def __aexit__(self, *_exc_info) -> bool:
        return False


@pytest.fixture
def hosts_down(accepting_nodes, monkeypatch) -> set[str]:
    """``accepting_nodes``, except for the addresses a test puts in the returned set."""
    down: set[str] = set()

    def connection_for(target):
        return UnreachableNode() if target.host in down else AcceptingNode()

    monkeypatch.setattr(apply, "NodeConnection", connection_for)
    return down


async def a_node(client, *, name: str, address: str) -> str:
    """One node registered with a key and nothing enabled on it — a draft."""
    created = await client.post(
        "/api/nodes",
        json={
            "name": name,
            "address": address,
            "location_label": "Testland",
            "ssh_host": address,
            "ssh_private_key": GENERATED_SSH_KEY,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def a_node_with_a_transport(client, reality_params, *, name: str, address: str) -> str:
    """One node with one transport enabled and never applied — still a draft."""
    node_id = await a_node(client, name=name, address=address)
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
    return node_id


async def a_serving_node(client, reality_params, *, name: str, address: str) -> str:
    """One node with one transport, applied and in service."""
    node_id = await a_node_with_a_transport(client, reality_params, name=name, address=address)
    applied = await client.post(f"/api/nodes/{node_id}/apply")
    assert applied.status_code == 200, applied.text
    return node_id


async def nicknames(client) -> list[str]:
    return [user["nickname"] for user in (await client.get("/api/users")).json()]


def links_in(text: str, base_url: str) -> list[str]:
    """The ``/sub/`` paths a reply holds, as the anonymous client can fetch them."""
    return [
        word.removeprefix(base_url)
        for word in text.split()
        if word.startswith(f"{base_url}/sub/")
    ]


# --- the owner adds -------------------------------------------------------------------


async def test_the_owner_adds_and_the_reply_holds_a_link_that_answers(
    client, anonymous, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """Add, push, reply — and the link in the reply resolves. The plan's first test."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)

    await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    assert telegram.texts[0] == ADDING, "the owner was not told to wait first"
    assert len(telegram.texts) == 2, telegram.texts
    assert all(payload["chat_id"] == OWNER for payload in telegram.sends)
    reply = telegram.texts[1]
    assert reply.startswith("mira\n"), reply
    assert "subscription link: " in reply
    links = links_in(reply, settings.public_base_url)
    assert len(links) == 1, reply
    fetched = await anonymous.get(links[0])
    assert fetched.status_code == 200, fetched.text
    assert "vless://" in base64.b64decode(fetched.content).decode()
    assert await nicknames(client) == ["mira"]
    entries = (await session.execute(
        AuditEntry.__table__.select().where(
            AuditEntry.__table__.c.action == AuditAction.USER_ADDED
        )
    )).all()
    assert len(entries) == 1, "the add through the bot is not on the trail"
    # The ordinary add carries no summary: the links arriving is the confirmation —
    # and no offer to apply, since the one node took them.
    assert "node(s) updated" not in reply and "pushed" not in reply, reply
    assert "/apply" not in reply, reply


async def test_several_names_one_per_line_are_added_together(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """The panel's split: a line is a nickname, blank lines and edges are nothing."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)

    await the_bot_gets(session, api, settings, an_update("/adduser mira\n\n  kolya  \ndima"))

    assert sorted(await nicknames(client)) == ["dima", "kolya", "mira"]
    reply = telegram.texts[1]
    blocks = reply.split("\n\n")
    assert [block.splitlines()[0] for block in blocks] == ["mira", "kolya", "dima"], reply
    assert len(links_in(reply, settings.public_base_url)) == 3
    assert len(reply) <= TELEGRAM_MESSAGE_LIMIT


@pytest.mark.parametrize(
    "text",
    ["/adduser@hashi_e2e_bot hank", "/adduser@hashi_e2e_bot\nhank"],
    ids=["on the same line", "on the next line"],
)
async def test_a_command_addressed_to_the_bot_by_name_is_the_same_command(
    client, session, settings, api, telegram, text
) -> None:
    """``/adduser@<bot>`` is Telegram's form for a command aimed at one bot: the ``@…``
    is dropped, not taken as the nickname — the M37 acceptance walk had it add a user
    called ``@hashi_e2e_bot``. The token ends at the first whitespace, newline included."""
    await the_bot_gets(session, api, settings, an_update(text))

    assert telegram.texts[0] == ADDING, telegram.texts
    assert await nicknames(client) == ["hank"], telegram.texts
    reply = telegram.texts[1]
    assert reply.startswith("hank\n"), reply
    assert len(links_in(reply, settings.public_base_url)) == 1, reply


async def test_a_node_that_could_not_be_told_is_named_with_why_and_its_apply(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """After the links: the add's numbers, then the node not updated — the panel's
    sentence for it with ``/apply`` under it — and nothing for the node that took them.
    The numbers line keeps the summary's opening words, which the e2e scenario waits on."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    hosts_down.add(LEAF_ADDRESS)

    await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    assert len(telegram.texts) == 2, telegram.texts
    reply = telegram.texts[-1]
    assert len(links_in(reply, settings.public_base_url)) == 1
    blocks = reply.split("\n\n")
    assert blocks[0].startswith("mira\n"), reply
    assert blocks[1] == (
        "1 user(s) added and pushed to 1 node(s), but 1 node(s) could NOT be updated and "
        "do not know them yet:"
    ), reply
    why = onboarding.why_not_reached(NotUpdated.UNREACHED, name="leaf-ams")
    assert "'leaf-ams'" in why and "could not be reached" in why, why
    assert blocks[2] == f"{why}\napply it: /apply leaf-ams", reply
    assert len(blocks) == 3, reply
    assert "/apply entry-ru" not in reply and reply.count("/apply") == 1, reply
    assert LEAF_ADDRESS not in reply and "connection timed out" not in reply


async def test_every_node_the_add_could_not_update_gets_its_own_offer(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """Two nodes down: two blocks, sorted by name, one offer each, no offer for anything
    else — and the headline counts them."""
    await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    hosts_down.update({ENTRY_ADDRESS, LEAF_ADDRESS})

    await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    reply = telegram.texts[-1]
    blocks = reply.split("\n\n")
    assert blocks[1].startswith("1 user(s) added and pushed to 0 node(s), but 2 node(s)"), reply
    assert [block.splitlines()[-1] for block in blocks[2:]] == [
        APPLY_IT.format(name="entry-ru"),
        APPLY_IT.format(name="leaf-ams"),
    ], reply
    assert blocks[2].startswith("'entry-ru' ") and blocks[3].startswith("'leaf-ams' "), reply


async def test_an_add_no_node_is_serving_says_the_link_resolves_to_nothing(
    client, session, settings, api, telegram
) -> None:
    await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    reply = telegram.texts[-1]
    assert len(links_in(reply, settings.public_base_url)) == 1
    assert "no node is serving" in reply, reply


# --- refusals, and everything that is not an add ---------------------------------------


async def test_a_duplicate_name_gets_the_panels_sentence_and_no_second_user(
    client, session, settings, api, telegram
) -> None:
    await a_user_no_node_was_told_about(session, "mira")

    await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    assert telegram.texts[0] == ADDING
    refusal = telegram.texts[1]
    assert refusal.startswith("a user called 'mira' already exists\n"), refusal
    assert refusal.endswith(f"{NOTHING_ADDED} {SEE_THE_PANEL}"), refusal
    assert "/sub/" not in refusal, "an existing user's link was re-sent"
    assert await nicknames(client) == ["mira"]


async def test_a_name_too_long_is_refused_without_the_pointer_at_the_panel(
    client, session, settings, api, telegram
) -> None:
    """Every refusal says nothing was added; only one about a name that exists goes on
    to say where. Under this one the panel sentence was a non-sequitur (M37 acceptance)."""
    too_long = "x" * (users.NICKNAME_MAX_LENGTH + 1)

    await the_bot_gets(session, api, settings, an_update(f"/adduser {too_long}"))

    assert telegram.texts[0] == ADDING, telegram.texts
    refusal = telegram.texts[1]
    assert refusal.startswith(
        f"a nickname must be {users.NICKNAME_MAX_LENGTH} characters or fewer\n"
    ), refusal
    assert refusal.endswith(NOTHING_ADDED), refusal
    assert SEE_THE_PANEL not in refusal, refusal
    assert await nicknames(client) == []


async def test_a_refused_list_is_the_services_sentence_and_writes_nothing(
    client, session, settings, api, telegram
) -> None:
    """The same validation as the dialog — here, a name on the list twice. Nobody exists,
    so nothing points at the panel: a conflict, but not the one the pointer is for."""
    await the_bot_gets(session, api, settings, an_update("/adduser mira\nmira"))

    refusal = telegram.texts[1]
    assert refusal.startswith("'mira' is in this list twice\n"), refusal
    assert refusal.endswith(NOTHING_ADDED), refusal
    assert SEE_THE_PANEL not in refusal, refusal
    assert await nicknames(client) == []


@pytest.mark.parametrize(
    "text",
    [
        "/start",
        "/help",
        "/adduser",
        "/adduser   \n  \n",
        "hello",
        "/Adduser mira",
        # Addressed to the bot by name, as a client does for a menu pick: still bare.
        "/adduser@hashi_e2e_bot",
        "/help@hashi_e2e_bot",
        "/apply",
        "/apply   \n",
        "/apply@hashi_e2e_bot",
    ],
)
async def test_everything_else_from_the_owner_gets_the_usage_line(
    client, session, settings, api, telegram, text
) -> None:
    await the_bot_gets(session, api, settings, an_update(text))

    assert telegram.texts == [USAGE], text
    assert telegram.sends[0]["chat_id"] == OWNER
    assert await nicknames(client) == []


async def test_a_message_with_no_text_gets_the_usage_line(
    client, session, settings, api, telegram
) -> None:
    """A sticker or a photo from the owner is not a command, and not silence either."""
    await the_bot_gets(session, api, settings, an_update(None, sticker={"file_id": "x"}))

    assert telegram.texts == [USAGE]


# --- /nodes: which serving nodes are behind, each with its apply ------------------------


async def a_node_left_behind(client, hosts_down: set[str], *, address: str) -> None:
    """Leave the serving node at ``address`` behind what would be pushed, through the API.

    An add whose push could not reach it: the user is on its record and not on its host,
    which is the state ``/nodes`` is about. Through the API rather than the suite's
    session on purpose — a node the bot then reads is loaded fresh, not from an identity
    map that saw it before the push.
    """
    hosts_down.add(address)
    created = await client.post("/api/users", json={"nickname": "mira"})
    assert created.status_code == 201, created.text
    hosts_down.discard(address)


async def test_nodes_names_exactly_the_serving_node_that_is_behind(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """One of two serving nodes does not hold what would be pushed: the reply is that
    node in the console's own sentence with ``/apply`` under it, nothing of the one in
    sync — and nothing is dialled, which every host being unreachable would show."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    await a_node_left_behind(client, hosts_down, address=ENTRY_ADDRESS)
    hosts_down.update({ENTRY_ADDRESS, LEAF_ADDRESS})

    await the_bot_gets(session, api, settings, an_update("/nodes"))

    assert telegram.texts == [
        "entry-ru is still on the old configuration: your changes have not reached it.\n"
        "apply it: /apply entry-ru"
    ], telegram.texts
    assert telegram.sends[0]["chat_id"] == OWNER
    assert ENTRY_ADDRESS not in telegram.texts[0]


async def test_nodes_with_nothing_behind_is_one_sentence(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """With no node at all, with a serving node holding what it would be given, and
    addressed to the bot by name with a stray word after it: the same one sentence."""
    await the_bot_gets(session, api, settings, an_update("/nodes"))
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    hosts_down.add(ENTRY_ADDRESS)
    await the_bot_gets(session, api, settings, an_update("/nodes"))
    await the_bot_gets(session, api, settings, an_update("/nodes@hashi_e2e_bot please"))

    assert telegram.texts == [NOTHING_BEHIND] * 3, telegram.texts
    assert "/apply" not in NOTHING_BEHIND


async def test_a_node_that_is_behind_is_named_in_the_reply_and_in_no_log_record(
    client, session, settings, api, telegram, reality_params, hosts_down, caplog
) -> None:
    """``/nodes`` naming a node, at DEBUG: no record carries the node's name or the reply."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    await a_node_left_behind(client, hosts_down, address=ENTRY_ADDRESS)
    configure_logging()

    with caplog.at_level(logging.DEBUG):
        await the_bot_gets(session, api, settings, an_update("/nodes"))

    assert len(telegram.texts) == 1 and "apply it: /apply entry-ru" in telegram.texts[0]
    leaked = sorted(
        {
            record.name
            for record in caplog.records
            if "entry-ru" in record.getMessage()
            or telegram.texts[0] in record.getMessage()
            or "apply it" in record.getMessage()
        }
    )
    assert leaked == [], f"a node's name or the reply reached a log record from: {leaked}"


def test_the_usage_line_names_every_command_the_bot_dispatches() -> None:
    """What the owner is told the bot does is what it dispatches — and the command every
    ``apply it`` line promises is one of them."""
    for command in telegram_bot._COMMANDS:
        assert command in USAGE, command
    assert "/apply <name>" in USAGE, USAGE
    assert "/apply" in telegram_bot._COMMANDS
    assert APPLY_IT.format(name="leaf-ams") == "apply it: /apply leaf-ams"


# --- /apply <name>: the Nodes screen's Apply, from the phone ----------------------------


async def trail_for(session, name: str) -> list[tuple[AuditAction, str | None]]:
    """Every trail entry about the node called ``name``, as a sorted list.

    Sorted by content rather than by time: one apply writes its two entries in one
    transaction with one timestamp, and ids are random, so a time order is not one."""
    table = AuditEntry.__table__
    rows = await session.execute(table.select().where(table.c.first_label == name))
    return sorted((row.action, row.second_label or "") for row in rows.all())


async def the_node(client, node_id: str) -> dict[str, Any]:
    shown = await client.get(f"/api/nodes/{node_id}")
    assert shown.status_code == 200, shown.text
    return shown.json()


async def test_an_apply_from_the_bot_leaves_the_node_as_the_apis_apply_would(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """Two drafts, one applied through the API and one through the bot: both end active
    with the same trail — a node taken INTO service, which is the move the add's fan-out
    refuses — and the reply is "applying" first, then the panel's sentence naming what
    the API says was applied, and nothing else."""
    entry = await a_node_with_a_transport(
        client, reality_params, name="entry-ru", address=ENTRY_ADDRESS
    )
    leaf = await a_node_with_a_transport(
        client, reality_params, name="leaf-ams", address=LEAF_ADDRESS
    )
    through_the_api = await client.post(f"/api/nodes/{entry}/apply")
    assert through_the_api.status_code == 200, through_the_api.text

    await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert telegram.texts == [
        "applying leaf-ams — about a minute",
        console.applied_toast("leaf-ams", through_the_api.json()["transports_applied"]),
    ], telegram.texts
    assert telegram.texts[1] == "config applied to leaf-ams — vless-reality"
    assert all(payload["chat_id"] == OWNER for payload in telegram.sends)
    by_api, by_bot = await the_node(client, entry), await the_node(client, leaf)
    assert by_bot["state"] == "active" == by_api["state"], (by_bot, by_api)
    for field in ("state_detail", "last_probe_finding", "last_probe_at"):
        assert by_bot[field] == by_api[field], field
    trail = await trail_for(session, "leaf-ams")
    assert trail == await trail_for(session, "entry-ru"), trail
    assert {(AuditAction.NODE_STATE_CHANGED, "active"), (AuditAction.NODE_APPLIED, "")} <= set(
        trail
    ), trail


async def test_an_apply_that_could_not_measure_a_transport_says_so_in_the_panels_sentence(
    client, session, settings, api, telegram, reality_params, hosts_down, monkeypatch
) -> None:
    """A host whose socket table cannot be read: the apply lands and the node is active,
    and the reply is the panel's qualified sentence, not the one for a measured apply."""
    node_id = await a_node_with_a_transport(
        client, reality_params, name="leaf-ams", address=LEAF_ADDRESS
    )

    async def unreadable(connection):
        return None

    monkeypatch.setattr(listening, "bound_ports", unreadable)

    await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert len(telegram.texts) == 2, telegram.texts
    reply = telegram.texts[1]
    assert reply == console.applied_unmeasured("leaf-ams", ["vless-reality"], ("vless-reality",))
    assert reply.startswith(
        "config applied to leaf-ams — vless-reality. Not measured serving: vless-reality."
    ), reply
    assert (await the_node(client, node_id))["state"] == "active"


@pytest.mark.parametrize("parked", ["nothing enabled", "retired"])
async def test_a_refusal_is_the_sentence_the_api_envelope_carries_and_moves_nothing(
    client, session, settings, api, telegram, reality_params, hosts_down, parked
) -> None:
    """The two refusals the plan names, each answered with the very sentence the API's
    own apply of the same node answers — and the node as it was, both times."""
    node_id = await a_node(client, name="leaf-ams", address=LEAF_ADDRESS)
    if parked == "retired":
        retired = await client.post(f"/api/nodes/{node_id}/state", json={"state": "retired"})
        assert retired.status_code == 200, retired.text
    envelope = await client.post(f"/api/nodes/{node_id}/apply")
    assert envelope.status_code == 409, envelope.text
    before = await the_node(client, node_id)

    await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert telegram.texts == [
        APPLYING.format(name="leaf-ams"),
        envelope.json()["error"]["message"],
    ], telegram.texts
    assert SEE_THE_PANEL not in telegram.texts[1] and NOTHING_ADDED not in telegram.texts[1]
    assert await the_node(client, node_id) == before


async def test_a_host_that_could_not_be_reached_is_answered_as_the_api_answers_it(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """A serving node the apply cannot reach: the API's own sentence, which says the node
    stays in users' links — and it does. The reply names no address."""
    node_id = await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    hosts_down.add(LEAF_ADDRESS)
    envelope = await client.post(f"/api/nodes/{node_id}/apply")
    assert envelope.status_code == 502, envelope.text

    await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert telegram.texts == [
        APPLYING.format(name="leaf-ams"),
        envelope.json()["error"]["message"],
    ], telegram.texts
    assert telegram.texts[1].startswith("the node could not be reached, so nothing was pushed")
    assert LEAF_ADDRESS not in telegram.texts[1]
    assert (await the_node(client, node_id))["state"] == "active"


def fragments(secret: str, size: int = 12) -> list[str]:
    """Every run of ``size`` characters in ``secret`` — what a partial leak looks like."""
    return [secret[i : i + size] for i in range(len(secret) - size + 1)]


async def test_a_failure_whose_message_quotes_a_key_reaches_the_chat_without_it(
    client, session, settings, api, telegram, reality_params, hosts_down, monkeypatch, caplog
) -> None:
    """The premise first — the API's envelope for this apply really does carry the node's
    private key, the shape ``apply.validate_before_push`` warns of — then the claim: the
    bot's reply is the panel's sentence for the KIND and holds neither a fragment of the
    key nor the checker's words. ``pytest.fail`` with a label rather than ``assert`` on
    the reply, so a failure never prints the value into the CI log."""
    node_id = await a_node_with_a_transport(
        client, reality_params, name="leaf-ams", address=LEAF_ADDRESS
    )
    row = (
        await session.execute(select(NodeTransport).where(NodeTransport.node_id == node_id))
    ).scalars().one()
    secret = nodes.render_params(row)["private_key"]

    def the_checker(config: str, *, config_format):
        # What Xray's own checker prints about a Reality key, the key first so the
        # 300-character cut in ``apply.validate_before_push`` keeps all of it.
        return types.SimpleNamespace(
            available=True, ok=False, output=f'invalid "privateKey": {secret}'
        )

    monkeypatch.setattr(apply.checker, "validate", the_checker)
    envelope = await client.post(f"/api/nodes/{node_id}/apply")
    assert envelope.status_code == 502, envelope.status_code
    if secret not in envelope.json()["error"]["message"]:
        pytest.fail("premise failed: the API's envelope did not carry the key; nothing is proven")
    configure_logging()

    with caplog.at_level(logging.DEBUG):
        await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert len(telegram.texts) == 2, len(telegram.texts)
    for text in telegram.texts:
        if "privateKey" in text or any(fragment in text for fragment in fragments(secret)):
            pytest.fail("a reply carries the checker's words or part of the node's private key")
    for record in caplog.records:
        if any(fragment in record.getMessage() for fragment in fragments(secret)):
            pytest.fail(f"a log record from {record.name} carries part of the node's key")
    reply = telegram.texts[1]
    assert reply == onboarding.why_not_reached(NotUpdated.REFUSED, name="leaf-ams"), reply
    assert reply.startswith("'leaf-ams' could not be given a configuration"), reply
    assert "the Nodes screen" in reply, reply
    assert (await the_node(client, node_id))["state"] == "draft"


MARKER = "MARKER-a-private-key-would-be-in-here-7f3a9c"


async def test_a_failure_that_is_not_in_words_gets_the_fixed_sentence_and_propagates(
    client, session, settings, api, telegram, reality_params, hosts_down, monkeypatch, caplog
) -> None:
    """A non-domain failure out of the apply: the one fixed sentence naming the node and
    the Nodes screen, then the failure itself for the caller to log — and its text, at
    root DEBUG, in no reply and no log record."""
    await a_node_with_a_transport(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)

    async def broken(session, *, node_id, only_if_serving=False):
        raise RuntimeError(MARKER)

    monkeypatch.setattr(apply, "apply_node", broken)
    configure_logging()

    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError):
        await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert telegram.texts == [
        APPLYING.format(name="leaf-ams"),
        "applying leaf-ams did not complete — the Nodes screen shows the state it was "
        "left in; what failed is in the control plane's log.",
    ], telegram.texts
    assert telegram.texts[1] == APPLY_DID_NOT_COMPLETE.format(name="leaf-ams")
    leaked = sorted({r.name for r in caplog.records if MARKER in r.getMessage()})
    assert leaked == [], f"the failure's text reached a log record from: {leaked}"

    # And when that sentence cannot be sent either, what propagates is still the apply's
    # own failure, not Telegram's.
    telegram.failing.add(3)  # the fourth sendMessage: the second command's fixed sentence
    with pytest.raises(RuntimeError):
        await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))
    assert len(telegram.texts) == 4, telegram.texts


async def test_the_name_is_the_whole_argument_matched_exactly_and_an_unknown_one_is_refused(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """A name with a space in it applies when typed as it is — addressed to the bot by
    name too — and any other spelling is refused in a sentence naming what was typed,
    with no "applying" before it and nothing dialled, which the host being down for the
    refused two would otherwise show."""
    node_id = await a_node_with_a_transport(
        client, reality_params, name="leaf ams", address=LEAF_ADDRESS
    )

    await the_bot_gets(session, api, settings, an_update("/apply@hashi_e2e_bot leaf ams"))
    hosts_down.add(LEAF_ADDRESS)
    await the_bot_gets(session, api, settings, an_update("/apply Leaf ams"))
    await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert telegram.texts == [
        "applying leaf ams — about a minute",
        "config applied to leaf ams — vless-reality",
        "no node named 'Leaf ams'",
        "no node named 'leaf-ams'",
    ], telegram.texts
    assert (await the_node(client, node_id))["last_probe_finding"] is None


async def test_a_strangers_apply_changes_nothing_and_answers_nothing(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """The gate sits before the dispatch; asserted on the command that changes a host."""
    node_id = await a_node_with_a_transport(
        client, reality_params, name="leaf-ams", address=LEAF_ADDRESS
    )

    await the_bot_gets(
        session, api, settings, an_update("/apply leaf-ams", sender=STRANGER, chat=STRANGER)
    )

    assert telegram.requests == [], "the bot called Telegram about a stranger"
    assert (await the_node(client, node_id))["state"] == "draft"
    actions = {action for action, _ in await trail_for(session, "leaf-ams")}
    assert AuditAction.NODE_APPLIED not in actions and AuditAction.NODE_STATE_CHANGED not in actions


async def test_an_apply_is_named_in_the_reply_and_in_no_log_record(
    client, session, settings, api, telegram, reality_params, hosts_down, caplog
) -> None:
    """``/apply`` at DEBUG: no record carries the node's name or either reply."""
    await a_node_with_a_transport(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    configure_logging()

    with caplog.at_level(logging.DEBUG):
        await the_bot_gets(session, api, settings, an_update("/apply leaf-ams"))

    assert len(telegram.texts) == 2 and telegram.texts[1].startswith("config applied to")
    leaked = sorted(
        {
            record.name
            for record in caplog.records
            if "leaf-ams" in record.getMessage()
            or any(sent in record.getMessage() for sent in telegram.texts)
        }
    )
    assert leaked == [], f"a node's name or a reply reached a log record from: {leaked}"


# --- silence for everyone else ---------------------------------------------------------


STRANGERS = {
    "another id": an_update(sender=STRANGER, chat=STRANGER),
    "the owner's id in a group": an_update(sender=OWNER, chat=-100_424_242, chat_type="group"),
    "the owner's id in a supergroup": an_update(
        sender=OWNER, chat=-100_424_242, chat_type="supergroup"
    ),
    "the owner as sender but another chat": an_update(sender=OWNER, chat=STRANGER),
    # Telegram never sends this shape (a chat with a user's id is private); it pins the
    # third fact of the gate on its own, since a group's id already fails the second.
    "the owner's chat id, not private": an_update(sender=OWNER, chat=OWNER, chat_type="group"),
    "another sender in the owner's chat": an_update(sender=STRANGER, chat=OWNER),
    "an edit of the owner's own message": an_update(key="edited_message"),
    "a forward in the owner's chat": an_update(
        forward_origin={"type": "user", "sender_user": {"id": STRANGER}, "date": 1}
    ),
    "a forward, the older shape": an_update(forward_date=1, forward_from={"id": STRANGER}),
    "no sender at all": an_update(sender=None),
    # The gate sits before the dispatch, so a command added later gets it for free —
    # asserted anyway on the one that reads the fleet and the one that changes a host.
    "a stranger's /nodes": an_update("/nodes", sender=STRANGER, chat=STRANGER),
    "a stranger's /apply": an_update("/apply entry-ru", sender=STRANGER, chat=STRANGER),
    "an id that is a string": an_update(sender=str(OWNER)),
    "no message at all": {"update_id": 100, "channel_post": {"text": "/adduser mira"}},
}


@pytest.mark.parametrize("update", STRANGERS.values(), ids=STRANGERS.keys())
async def test_a_stranger_gets_no_call_no_user_and_no_log_record_naming_them(
    client, session, settings, api, telegram, caplog, update
) -> None:
    """Returns before any call and before any log line. Asserted on both."""
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        await the_bot_gets(session, api, settings, update)

    assert telegram.requests == [], "the bot called Telegram about a stranger"
    assert await nicknames(client) == []
    naming = [
        record.name
        for record in caplog.records
        if str(STRANGER) in record.getMessage()
        or str(OWNER) in record.getMessage()
        or "mira" in record.getMessage()
    ]
    assert naming == [], f"a log record names the sender or their text: {naming}"


async def test_a_bot_given_no_owner_answers_nobody(
    client, session, settings, api, telegram
) -> None:
    """The setting refuses half a pair at boot; this is the same refusal one layer down."""
    for owner in (None, 0, True):
        await the_bot_gets(session, api, settings, an_update(), owner=owner)
    assert telegram.requests == []
    assert await nicknames(client) == []


# --- what the log never holds ---------------------------------------------------------


async def test_no_reply_text_reaches_a_log(
    client, session, settings, api, telegram, reality_params, hosts_down, caplog
) -> None:
    """An add and a refusal, at DEBUG: no record carries a reply, a nickname or a link."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        await the_bot_gets(session, api, settings, an_update("/adduser mira"))
        await the_bot_gets(session, api, settings, an_update("/adduser mira"))
        await the_bot_gets(session, api, settings, an_update("/help"))

    assert len(telegram.texts) == 5, telegram.texts
    links = links_in(telegram.texts[1], settings.public_base_url)
    assert links, telegram.texts[1]
    leaked = sorted(
        {
            record.name
            for record in caplog.records
            for sent in telegram.texts
            if sent in record.getMessage()
            or "mira" in record.getMessage()
            or links[0] in record.getMessage()
            or "/sub/" in record.getMessage()
        }
    )
    assert leaked == [], f"reply text, a nickname or a link reached a log record from: {leaked}"


# --- when a reply cannot be sent --------------------------------------------------------


async def test_an_acknowledgement_that_cannot_be_sent_starts_no_add(
    client, session, settings, api, telegram
) -> None:
    """Telegram down before the add: the owner re-sends later; nobody was created."""
    telegram.failing.add(0)  # the first sendMessage

    with pytest.raises(TelegramCallFailed):
        await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    assert await nicknames(client) == []


async def test_a_reply_that_fails_after_the_add_is_one_log_line_without_the_links(
    client, session, settings, api, telegram, reality_params, hosts_down, caplog
) -> None:
    """The add stands; the log says so once, naming nobody and no link; nothing raised."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    telegram.failing.add(1)  # the second sendMessage — the links
    configure_logging()

    with caplog.at_level(logging.DEBUG):
        await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    assert await nicknames(client) == ["mira"]
    lines = [
        record for record in caplog.records if record.name == telegram_bot.__name__
    ]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING, lines
    said = lines[0].getMessage()
    assert "could not be sent" in said and "HTTP 502" in said, said
    assert "mira" not in said and "/sub/" not in said and TOKEN not in said, said


async def test_a_failure_that_is_not_a_refusal_answers_nothing_and_propagates(
    client, session, settings, api, telegram, monkeypatch
) -> None:
    """Never a raw exception's text as a reply: the caller logs it, the owner gets no
    sentence composed from it."""

    async def broken(session, *, nicknames):
        raise RuntimeError("a database URL would be in here")

    monkeypatch.setattr(onboarding, "add_users", broken)

    with pytest.raises(RuntimeError):
        await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    assert telegram.texts == [ADDING]


# --- a reply longer than one message ---------------------------------------------------


def test_a_long_reply_is_split_where_a_persons_links_stay_together() -> None:
    """Blocks are packed whole, in order, with a blank line between; only a block that
    would not fit a message on its own is cut, at its lines, then at the limit."""
    blocks = [f"user-{n}\nsubscription link: https://x.test/sub/{'t' * 60}" for n in range(60)]
    messages = telegram_bot._messages(blocks, limit=TELEGRAM_MESSAGE_LIMIT)

    assert len(messages) > 1
    assert all(len(message) <= TELEGRAM_MESSAGE_LIMIT for message in messages)
    assert "\n\n".join(messages) == "\n\n".join(blocks), "text was lost or reordered"
    for message in messages:
        for block in message.split("\n\n"):
            assert block in blocks, "a person's links were split across two messages"

    # A single block too long for a message is cut at its lines, and a single line too
    # long for a message at the limit — no character is lost either way.
    lines = [f"line {n} " + "x" * 50 for n in range(10)]
    long_block = "\n".join(lines)
    cut = telegram_bot._messages([long_block], limit=200)
    assert all(len(message) <= 200 for message in cut)
    assert "\n".join(cut) == long_block
    sliced = telegram_bot._messages(["y" * 450], limit=200)
    assert sliced == ["y" * 200, "y" * 200, "y" * 50]
    assert telegram_bot._messages([], limit=200) == []
