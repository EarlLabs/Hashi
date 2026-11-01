"""The bot acts on the owner's commands and on nothing else — M37.2.

WHAT: that ``/adduser`` from the owner's own account adds the people named, pushes them
      and replies with links that answer on ``/sub/``; that a refusal is the panel's
      sentence and creates nothing; that everything else the owner sends gets the usage
      line; that a stranger — any other id, the owner's id in a group, a forward, an
      edit — gets no call, no user and no log record naming them; that no reply text
      reaches a log; and that a reply too long for one Telegram message is split where
      a person's links stay together.
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
from typing import Any

import httpx
import pytest

from control.app.main import configure_logging
from control.app.models import AuditAction, AuditEntry
from control.app.services import apply, onboarding, telegram_bot
from control.app.services.telegram_api import TelegramApi, TelegramCallFailed
from control.app.services.telegram_bot import (
    ADDING,
    NOTHING_ADDED,
    TELEGRAM_MESSAGE_LIMIT,
    USAGE,
    handle_update,
)
from edge.bootstrap.ssh import NodeUnreachable

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


async def a_serving_node(client, reality_params, *, name: str, address: str) -> str:
    """One node with one transport, applied and in service."""
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
    node_id = created.json()["id"]
    enabled = await client.post(
        f"/api/nodes/{node_id}/transports",
        json={"transport_name": "vless-reality", "params": reality_params},
    )
    assert enabled.status_code == 201, enabled.text
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
    # The ordinary add carries no summary: the links arriving is the confirmation.
    assert "node(s) updated" not in reply and "pushed" not in reply, reply


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


async def test_a_node_that_could_not_be_told_is_named_in_the_reply(
    client, session, settings, api, telegram, reality_params, hosts_down
) -> None:
    """The outcome's own summary follows the links, and the links are still there."""
    await a_serving_node(client, reality_params, name="entry-ru", address=ENTRY_ADDRESS)
    await a_serving_node(client, reality_params, name="leaf-ams", address=LEAF_ADDRESS)
    hosts_down.add(LEAF_ADDRESS)

    await the_bot_gets(session, api, settings, an_update("/adduser mira"))

    reply = telegram.texts[-1]
    assert len(links_in(reply, settings.public_base_url)) == 1
    assert "'leaf-ams'" in reply and "could not be reached" in reply, reply
    assert "1 node(s) could NOT be updated" in reply, reply
    assert LEAF_ADDRESS not in reply and "connection timed out" not in reply


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
    assert refusal.endswith(NOTHING_ADDED), refusal
    assert "/sub/" not in refusal, "an existing user's link was re-sent"
    assert await nicknames(client) == ["mira"]


async def test_a_refused_list_is_the_services_sentence_and_writes_nothing(
    client, session, settings, api, telegram
) -> None:
    """The same validation as the dialog — here, a name on the list twice."""
    await the_bot_gets(session, api, settings, an_update("/adduser mira\nmira"))

    assert telegram.texts[1].startswith("'mira' is in this list twice\n")
    assert await nicknames(client) == []


@pytest.mark.parametrize(
    "text",
    ["/start", "/help", "/adduser", "/adduser   \n  \n", "hello", "/nodes", "/Adduser mira"],
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
