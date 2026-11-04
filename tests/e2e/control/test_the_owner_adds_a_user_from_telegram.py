"""The owner adds a user from Telegram, and a stranger gets nothing — M37, M38.

WHAT: through the stand's fake Telegram, the owner's id sends ``/adduser``; the bot's
      reply is read back, the link in it is fetched the way a client would fetch it,
      and the user is found through the API. Then a stranger's id sends the same, and
      nothing is sent back and nobody is created. Then the owner sends ``/apply`` with
      a name no node has and is refused in a sentence naming it (M38.2). Then the owner
      sends ``/nodes`` and gets what the Nodes screen's own block says — on the stand
      the plan describes, which has no node, the one sentence (M38.1).
WHY:  M37's three control steps are each proven against a transport they fake
      themselves. What none of them can say is that the real poller, the real client,
      the real add and the real delivery endpoint compose inside the BOOTED control
      plane — that the container reads the three variables, dials the configured URL,
      and the message that comes back carries a link the stand answers. This is that
      loop, once, with only the far end replaced.
HOW:  the fake's test-only side is published on the e2e block (``telegram_url``); an
      update is injected there and the recorded ``sendMessage`` bodies are polled until
      the one that matters appears. The stranger case needs a way to know the bot has
      SEEN the stranger's update and chosen silence, which silence cannot signal — so
      the owner's ``/help`` is injected behind it: updates are handled in order, and the
      usage reply to that one is the proof the stranger's was handled first and answered
      nothing.

Boundary: real control + postgres + caddy; Telegram is STUBBED by .e2e/fake_telegram.py.
No node on this stand is ever reachable: the stand starts with none, and the scenarios
that run before this one leave stub nodes nothing answers on. So the push never
completes, and the reply carries the add's own summary of what the push did — this file
asserts the summary is there and never which nodes it names, because the e2e database is
shared by every scenario in a run and "which nodes" is whatever ran first.
"""

import asyncio
import html
import re
import time
import uuid
from collections.abc import Callable

import httpx
import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# The container the poller runs in — M39. The bot left the control plane's process and is
# now its own service (deploy/docker-compose.yml, switched on for the stand by the e2e
# overlay), so its readiness line and any line that might name a sender live in THIS log,
# not control's. The control plane no longer polls, so reading its log for either would be
# reading a log the bot never writes to.
BOT = "telegram-bot"

# The line the poller writes once Telegram — here the fake — has answered ``getMe``.
# Without it an injected update sits in the fake's queue with nobody polling for it,
# and every assertion below would be about a bot that was never up.
READY = "telegram: polling as @"

# Not the owner, and not a number that could turn up in a log line by accident: the
# last assertion of this file is that the control plane's log never names it.
STRANGER = 987654321


@pytest.fixture
def unique() -> str:
    """A per-run suffix, so a second run against a warm stack does not collide."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def telegram(telegram_url: str):
    """A client for the fake's test-only side — injecting updates, reading what was sent."""
    async with httpx.AsyncClient(base_url=telegram_url, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
def polling(logs_of) -> None:
    """Block until the bot container reports that it is polling, once per module."""
    deadline = time.monotonic() + 90
    while READY not in logs_of(BOT):
        assert time.monotonic() < deadline, (
            "the bot container never wrote `telegram: polling as` — is the telegram-bot "
            "profile up and pointed at the fake in deploy/docker-compose.e2e.yml?"
        )
        time.sleep(1)


async def inject(telegram: httpx.AsyncClient, *, sender: int, text: str) -> int:
    """Put one private message from ``sender`` in front of the bot; the update's id."""
    answer = await telegram.post(
        "/_test/updates",
        json={"from_id": sender, "chat_id": sender, "chat_type": "private", "text": text},
    )
    assert answer.status_code == 200, answer.text
    return answer.json()["result"]["update_id"]


async def sent(telegram: httpx.AsyncClient) -> list[dict]:
    """Every ``sendMessage`` body the bot has sent since the stand came up, in order."""
    answer = await telegram.get("/_test/sent")
    assert answer.status_code == 200, answer.text
    return answer.json()["result"]


async def replies_after(
    telegram: httpx.AsyncClient,
    count: int,
    *,
    until: Callable[[list[dict]], bool],
    timeout: float = 120.0,
) -> list[dict]:
    """The bodies recorded after the first ``count``, once ``until`` holds of them.

    Polled rather than awaited on an event: the bot's side of this is the real poller
    in the real container, and the only thing a scenario can observe is the fake's
    record. An injected update wakes the poller's long poll at once, so the wait here
    is the add itself, not a poll period — and the add pushes to every stub node earlier
    scenarios left, each of which runs out its own connect timeout before the reply can
    be sent. The ceiling is sized for that, the way the ``client`` fixture's is.
    """
    deadline = time.monotonic() + timeout
    while True:
        new = (await sent(telegram))[count:]
        if until(new):
            return new
        assert time.monotonic() < deadline, (
            f"the bot did not answer within {timeout:.0f}s; recorded so far: {new}"
        )
        await asyncio.sleep(0.5)


async def logged_in(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """The same client, now holding a real operator session from the login form."""
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, (
        f"the operator could not log in ({response.status_code}) — check "
        "deploy/e2e.env against deploy/docker-compose.e2e.yml"
    )
    return client


async def nicknames(operator: httpx.AsyncClient) -> list[str]:
    listed = await operator.get("/api/users")
    assert listed.status_code == 200, listed.text
    return [user["nickname"] for user in listed.json()]


# The Nodes screen's not-pushed block, one "Apply <name>" button per node it names. The
# row's own button is lowercase "apply", so the capital is what tells the block's apart.
APPLY_BUTTON = re.compile(r'<span class="when-idle">Apply ([^<]+)</span>')


async def the_nodes_screens_behind_block(operator: httpx.AsyncClient) -> list[str]:
    """The node names the Nodes screen's block offers an Apply for, as the owner reads it."""
    table = await operator.get("/panel/nodes/table")
    assert table.status_code == 200, table.text
    return [html.unescape(name) for name in APPLY_BUTTON.findall(table.text)]


def offered_in(text: str) -> list[str]:
    """The node names a bot reply offers ``/apply`` for, one line each, in order."""
    offer = "apply it: /apply "
    return [line.removeprefix(offer) for line in text.splitlines() if line.startswith(offer)]


async def test_the_owner_adds_a_user_and_the_link_in_the_reply_answers(
    polling, telegram, telegram_owner_id: int, client, unique: str
) -> None:
    nickname = f"tgowner-{unique}"
    before = len(await sent(telegram))

    await inject(telegram, sender=telegram_owner_id, text=f"/adduser {nickname}")

    # "adding…" comes first, the links follow, and the add's own summary is the LAST
    # block the bot sends — so waiting for it is waiting for the add to finish talking,
    # and nothing of this add can land in the fake's record after this test returns.
    # That is what keeps the stranger test below exact. The push could not have
    # completed — nothing on this stand answers — so the summary is always there; its
    # first words are the same whichever way the push fell short, and which nodes it goes
    # on to name is the fleet other scenarios left behind, which is not asserted.
    replies = await replies_after(
        telegram,
        before,
        until=lambda new: any("user(s) added" in reply["text"] for reply in new),
    )
    assert all(reply["chat_id"] == telegram_owner_id for reply in replies), replies
    links = next(reply["text"] for reply in replies if "/sub/" in reply["text"])
    assert nickname in links, links

    # Fetched with NO session, exactly as the friend's client would: the token in the
    # path is the whole credential.
    token = next(word for word in links.split() if "/sub/" in word).rsplit("/", 1)[-1]
    delivered = await client.get(f"/sub/{token}")
    assert delivered.status_code == 200, delivered.text

    operator = await logged_in(client)
    assert nickname in await nicknames(operator), (
        "the bot replied with a link to a user the API does not list"
    )


async def test_a_stranger_gets_no_reply_and_creates_nobody(
    polling, telegram, telegram_owner_id: int, client, logs_of, unique: str
) -> None:
    assert STRANGER != telegram_owner_id
    nickname = f"tgstranger-{unique}"
    before = len(await sent(telegram))

    await inject(telegram, sender=STRANGER, text=f"/adduser {nickname}")
    # The marker: handled after the stranger's, and answered — see the module header.
    # "After" is control/app/services/telegram_poller.py's promise, one update at a time
    # in the order Telegram numbered them; if it ever handled a batch concurrently this
    # would prove a race rather than silence.
    await inject(telegram, sender=telegram_owner_id, text="/help")

    replies = await replies_after(
        telegram,
        before,
        until=lambda new: any(reply["chat_id"] == telegram_owner_id for reply in new),
    )
    to_anyone_else = [reply for reply in replies if reply["chat_id"] != telegram_owner_id]
    assert to_anyone_else == [], (
        f"the bot answered an account that is not the owner: {to_anyone_else}"
    )
    assert len(replies) == 1, f"more than the owner's one usage reply was sent: {replies}"
    assert nickname not in replies[0]["text"], replies

    operator = await logged_in(client)
    assert nickname not in await nicknames(operator), "a stranger's /adduser created a user"
    log = logs_of(BOT)
    assert READY in log, "the log being read is not the bot's — the ready line is missing"
    assert str(STRANGER) not in log, (
        "a line in the bot container's log names the stranger — a record of who tried is "
        "a record about a person, and this product keeps none"
    )


async def test_apply_of_a_name_the_stand_does_not_have_is_refused_in_words(
    polling, telegram, telegram_owner_id: int, unique: str
) -> None:
    """``/apply`` of a node that does not exist: exactly one reply, the sentence naming
    what was typed, and no "applying" before it. The name carries the run's suffix so no
    node an earlier scenario left can be the one it names; nothing is dialled for an
    unknown name, so the ceiling is for the poll."""
    name = f"no-such-node-{unique}"
    before = len(await sent(telegram))

    await inject(telegram, sender=telegram_owner_id, text=f"/apply {name}")

    replies = await replies_after(
        telegram,
        before,
        until=lambda new: any(reply["chat_id"] == telegram_owner_id for reply in new),
        timeout=30,
    )
    assert len(replies) == 1, replies
    assert replies[0]["text"] == f"no node named '{name}'", replies[0]["text"]


async def test_nodes_answers_what_the_nodes_screens_block_says(
    polling, telegram, telegram_owner_id: int, client
) -> None:
    """On the stand the plan describes — no node — ``/nodes`` is the one sentence. In a
    full run this file is not the first, and earlier scenarios leave stub nodes, some of
    them serving and, once this file's own add has failed to reach them, behind; so what
    is held is the milestone's own claim: the bot offers ``/apply`` for exactly the nodes
    the Nodes screen's block names at that moment, and when the block is empty it says
    the sentence. It dials nothing, so the ceiling is for the poll, not for a push."""
    before = len(await sent(telegram))

    await inject(telegram, sender=telegram_owner_id, text="/nodes")

    replies = await replies_after(
        telegram,
        before,
        until=lambda new: any(reply["chat_id"] == telegram_owner_id for reply in new),
        timeout=30,
    )
    assert len(replies) == 1, replies
    text = replies[0]["text"]
    operator = await logged_in(client)
    behind = await the_nodes_screens_behind_block(operator)
    assert sorted(offered_in(text)) == sorted(behind), (text, behind)
    if not behind:
        assert text == "Every serving node holds the configuration it would be given.", text
