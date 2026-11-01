"""The polling task starts with the app, acknowledges after one attempt, and backs off — M37.3.

WHAT: that both settings set starts the task in the lifespan and both blank starts
      nothing and says nothing; that an update is handled with its own session and the
      next poll asks past it, whether the attempt returned or raised; that a handler's
      failure is one log line carrying no text from the message; that Telegram being
      unreachable — at boot or mid-polling — is one line when it starts and one when it
      answers again across many retries, with the wait doubling to a minute and no
      further; that the panel answers while that is going on; that stopping the task
      returns promptly, mid-poll, with the client closed; and that no record written
      along the way holds the token, the API URL, the message's text or the sender.
WHY:  this loop runs with nobody watching, on a box where Telegram may or may not answer.
      The two properties that keep it harmless — a failed update does not come back as
      the same failure on every poll, and a failing Telegram is not a line per retry —
      are both invisible on a green run where everything answers, which is why each is
      driven here with a fake that fails on purpose.
HOW:  ``poll_forever`` is run as a task against the suite's real schema and a
      ``TelegramApi`` on an async ``httpx.MockTransport`` that plays Telegram: answers
      ``getMe``, long-polls ``getUpdates`` from a queue and holds an empty poll open the
      way Telegram does, records ``sendMessage``, and fails every call while ``down``.
      The backoff's clock is the loop's injectable sleeper, so a minute of retries costs
      nothing. The lifespan tests build the app with the bot on and patch the client the
      poller constructs onto the same fake. Logging is configured as the process
      configures it and driven to DEBUG at the root, the way the bot's own tests do.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Iterable
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from control.app.main import configure_logging, create_app
from control.app.services import telegram_bot, telegram_poller
from control.app.services.telegram_api import TelegramApi
from control.app.services.telegram_bot import ADDING, USAGE
from control.app.services.telegram_poller import (
    BACKOFF_FIRST_SECONDS,
    BACKOFF_MAX_SECONDS,
    poll_forever,
    start_poller,
    stop_poller,
)

TOKEN = "110201543:TEST-TOKEN-NEVER-REAL-9f3b2c1d8e7a6b5c4d3e2f1a0b9c8d7e"
API_URL = "https://bot-api.test"
OWNER = 424242
BOT_USERNAME = "hashi_test_bot"

# Nothing a log record may hold, whatever happened: the credential, where it was sent,
# the path it is sent in, the one nickname these tests type, and who typed it.
NEVER_LOGGED = (TOKEN, API_URL, "/bot", "mira", str(OWNER))


def ok(result: object) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


class FakeTelegram:
    """Telegram as the poller sees it, recording every request it was given.

    ``queue`` holds the updates still to deliver, in order; a poll answers every queued
    update at or past its offset, and an empty poll is held open for the long-poll
    timeout — or until ``nudge`` — the way Telegram holds one. ``down`` fails every call
    the way an unreachable host does. ``failing_sends`` are the 0-based ``sendMessage``
    calls answered with a 502.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.queue: list[dict[str, Any]] = []
        self.down = False
        self.failing_sends: set[int] = set()
        self._wake = asyncio.Event()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        is_send = request.url.path.endswith("/sendMessage")
        index = len(self.sends)
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("Telegram is unreachable in this test", request=request)
        if request.url.path.endswith("/getMe"):
            return ok({"id": 110201543, "is_bot": True, "username": BOT_USERNAME})
        if is_send:
            if index in self.failing_sends:
                return httpx.Response(502, text="bad gateway")
            return ok({"message_id": len(self.requests)})
        assert request.url.path.endswith("/getUpdates"), request.url.path
        payload = json.loads(request.content)
        due = self._due(payload.get("offset"))
        if not due:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), payload["timeout"])
            self._wake.clear()
            if self.down:
                raise httpx.ConnectError("Telegram went away in this test", request=request)
            due = self._due(payload.get("offset"))
        return ok(due)

    def _due(self, offset: int | None) -> list[dict[str, Any]]:
        return [
            update
            for update in self.queue
            if offset is None
            or type(update.get("update_id")) is not int
            or update["update_id"] >= offset
        ]

    def nudge(self) -> None:
        """Let a held-open poll answer now, with whatever ``down`` and ``queue`` say."""
        self._wake.set()

    @property
    def methods(self) -> list[str]:
        return [request.url.path.rsplit("/", 1)[-1] for request in self.requests]

    @property
    def polls(self) -> list[dict[str, Any]]:
        return [
            json.loads(request.content)
            for request in self.requests
            if request.url.path.endswith("/getUpdates")
        ]

    @property
    def offsets(self) -> list[int | None]:
        return [poll.get("offset") for poll in self.polls]

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


class ClosingTransport(httpx.MockTransport):
    """A ``MockTransport`` that remembers being closed: ``AsyncClient.aclose`` closes it."""

    closed = False

    async def aclose(self) -> None:
        self.closed = True
        await super().aclose()


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def transport(telegram: FakeTelegram) -> ClosingTransport:
    return ClosingTransport(telegram)


@pytest.fixture
async def api(transport: ClosingTransport):
    async with TelegramApi(token=TOKEN, api_url=API_URL, transport=transport) as client:
        yield client


@pytest.fixture
def bot_settings(settings):
    """The suite's settings with the bot on: both halves set, the API URL a fake's."""
    return settings.model_copy(
        update={
            "telegram_bot_token": SecretStr(TOKEN),
            "telegram_owner_id": OWNER,
            "telegram_api_url": API_URL,
        }
    )


class Built:
    """What ``start_poller`` built its client with — proof it unwrapped the secret."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []


@pytest.fixture
def fake_bot_api(monkeypatch: pytest.MonkeyPatch, transport: ClosingTransport) -> Built:
    """Every client the poller constructs is on the fake, the way ``apply.NodeConnection``
    is pointed at an accepting node: the module attribute, not a parameter the lifespan
    would have to carry for tests alone."""
    built = Built()

    def on_the_fake(**kwargs: Any) -> TelegramApi:
        built.calls.append(kwargs)
        return TelegramApi(**kwargs, transport=transport)

    monkeypatch.setattr(telegram_poller, "TelegramApi", on_the_fake)
    return built


@pytest.fixture(autouse=True)
def restore_levels():
    """``configure_logging`` pins loggers for the process; put back what this file moves."""
    names = ("", "httpx", "httpcore", "control", "edge", "asyncssh", "sqlalchemy.engine")
    before = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)


def an_update(text: str, *, update_id: int, sender: int = OWNER) -> dict[str, Any]:
    """One message update as Telegram shapes it, in the owner's private chat unless told."""
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1_700_000_000,
            "chat": {"id": sender, "type": "private"},
            "from": {"id": sender, "is_bot": False, "first_name": "Someone"},
            "text": text,
        },
    }


async def until(condition: Callable[[], bool], what: str, *, seconds: float = 5.0) -> None:
    """Wait for the task under test to get somewhere, or fail saying where it did not."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not condition():
        if loop.time() > deadline:
            pytest.fail(f"gave up waiting for {what}")
        await asyncio.sleep(0.005)


@contextlib.asynccontextmanager
async def polling(app, settings, api: TelegramApi, *, sleep=asyncio.sleep):
    task = asyncio.create_task(poll_forever(app.state.database, settings, api, sleep=sleep))
    try:
        yield task
    finally:
        await stop_poller(task)


def sleeper(telegram: FakeTelegram, *, back_after: Iterable[int] = ()) -> tuple[list[float], Any]:
    """The backoff's clock: records each wait, and brings Telegram back after so many."""
    delays: list[float] = []
    comebacks = set(back_after)

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        if len(delays) in comebacks:
            telegram.down = False
        await asyncio.sleep(0)

    return delays, sleep


def said_by_the_poller(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == telegram_poller.__name__]


def said_after_polling_as(caplog) -> list[logging.LogRecord]:
    """The poller's records after the one line every reachable start writes."""
    first, *rest = said_by_the_poller(caplog)
    assert (first.levelno, first.getMessage()) == (
        logging.INFO,
        f"telegram: polling as @{BOT_USERNAME}",
    )
    return rest


def assert_nothing_leaked(caplog) -> None:
    leaked = sorted(
        {
            f"{record.name}: {needle}"
            for record in caplog.records
            for needle in NEVER_LOGGED
            if needle in record.getMessage()
        }
    )
    assert leaked == [], f"a log record holds what it never may: {leaked}"


async def nicknames(client) -> list[str]:
    return [user["nickname"] for user in (await client.get("/api/users")).json()]


# --- the lifespan -----------------------------------------------------------------------


async def test_with_both_settings_set_the_application_polls_for_as_long_as_it_is_up(
    bot_settings, fake_bot_api, telegram, transport, caplog
) -> None:
    """Started in the lifespan with the secret unwrapped, one ``getMe``, one line naming
    the bot, then a poll; cancelled with the lifespan, its client closed behind it."""
    app = create_app(bot_settings)
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with app.router.lifespan_context(app):
            task = app.state.telegram_poller
            await until(lambda: "getUpdates" in telegram.methods, "the first poll")
            assert not task.done(), "the poller stopped on its own"
            assert telegram.methods == ["getMe", "getUpdates"]
        assert task.done(), "the poller outlived the application that started it"
    assert fake_bot_api.calls == [{"token": TOKEN, "api_url": API_URL}]
    assert transport.closed, "the lifespan ended with the Bot API client still open"
    assert len(telegram.requests) == 2, "a poll was sent after the cancel"

    lines = said_by_the_poller(caplog)
    assert [(line.levelno, line.getMessage()) for line in lines] == [
        (logging.INFO, f"telegram: polling as @{BOT_USERNAME}")
    ]
    assert_nothing_leaked(caplog)


async def test_with_both_settings_blank_nothing_starts_and_nothing_is_said(
    app, fake_bot_api, telegram, caplog
) -> None:
    """The stand's default and every existing install's: no task, no call, no line."""
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with app.router.lifespan_context(app):
            assert app.state.telegram_poller is None
            await asyncio.sleep(0.02)

    assert fake_bot_api.calls == [], "a client was built with the bot off"
    assert telegram.requests == []
    mentioned = [
        record.name
        for record in caplog.records
        if record.name == telegram_poller.__name__ or "telegram" in record.getMessage().lower()
    ]
    assert mentioned == [], f"the log mentions Telegram with the bot off: {mentioned}"


async def test_the_panel_answers_while_telegram_is_unreachable(
    bot_settings, fake_bot_api, telegram
) -> None:
    """The task is on its own: a Telegram that never answers is a line in the log and
    nothing a request can feel."""
    telegram.down = True
    app = create_app(bot_settings)
    async with app.router.lifespan_context(app):
        await until(lambda: telegram.methods == ["getMe"], "the first, failing, getMe")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://control.test"
        ) as http:
            assert (await http.get("/healthz")).status_code == 200
            assert (await http.get("/panel/")).status_code == 303
        assert not app.state.telegram_poller.done(), "the poller died on a failed getMe"


async def test_stopping_returns_promptly_mid_poll_and_closes_the_client(
    app, bot_settings, fake_bot_api, telegram, transport
) -> None:
    """A poll Telegram is holding open is where the task usually is when the process
    stops; the cancel lands there and the client is closed on the way out."""
    task = start_poller(app.state.database, bot_settings)
    await until(lambda: "getUpdates" in telegram.methods, "the first poll")

    await asyncio.wait_for(stop_poller(task), timeout=5)

    assert task.done() and task.cancelled()
    assert transport.closed
    await asyncio.sleep(0.02)
    assert telegram.methods == ["getMe", "getUpdates"], "a poll was sent after the cancel"
    await stop_poller(None)  # the bot-off case: nothing to stop, nothing raised


# --- updates: handled in turn, acknowledged after one attempt -----------------------------


async def test_each_update_is_handled_in_turn_and_the_next_poll_asks_past_the_last(
    app, client, bot_settings, api, telegram, caplog
) -> None:
    """Two commands in one batch: both carried out, in order, each with a session of its
    own, and the poll after them carries ``offset = last update_id + 1``."""
    telegram.queue = [
        an_update("/adduser mira", update_id=100),
        an_update("/adduser nika", update_id=101),
    ]
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with polling(app, bot_settings, api):
            await until(lambda: len(telegram.polls) == 2, "the poll after the batch")

    assert sorted(await nicknames(client)) == ["mira", "nika"]
    assert telegram.offsets == [None, 102]
    assert telegram.texts[0] == ADDING and "mira" in telegram.texts[1]
    assert telegram.texts[2] == ADDING and "nika" in telegram.texts[3]
    assert [line.getMessage() for line in said_by_the_poller(caplog)] == [
        f"telegram: polling as @{BOT_USERNAME}"
    ], "a handled update is not a line"
    assert_nothing_leaked(caplog)


async def test_a_reply_that_cannot_be_sent_is_one_line_and_the_update_is_not_retried(
    app, client, bot_settings, api, telegram, caplog
) -> None:
    """The domain failure the bot raises — "adding" could not be sent, so no add — is
    acknowledged like any other attempt: one line with the failure's own sentence, the
    offset past it, and the command behind it handled."""
    telegram.failing_sends.add(0)
    telegram.queue = [an_update("/adduser mira", update_id=100)]
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with polling(app, bot_settings, api):
            await until(lambda: len(telegram.polls) == 2, "the poll after the failure")
            telegram.queue.append(an_update("/help", update_id=101))
            telegram.nudge()
            await until(lambda: len(telegram.polls) == 3, "the poll after /help")

    assert await nicknames(client) == [], "the add ran without its acknowledgement"
    assert telegram.offsets == [None, 101, 102]
    assert telegram.texts == [ADDING, USAGE]
    lines = said_after_polling_as(caplog)
    assert len(lines) == 1 and lines[0].levelno == logging.ERROR, lines
    said = lines[0].getMessage()
    assert "was not handled" in said and "HTTP 502" in said and "sendMessage" in said, said
    assert_nothing_leaked(caplog)


async def test_a_handler_that_raises_is_one_line_naming_its_type_and_the_update_is_acknowledged(
    app, bot_settings, api, telegram, caplog, monkeypatch
) -> None:
    """An arbitrary failure's text can quote a nickname or an address; the line carries
    the type and nothing from the message — and the offset still moves."""

    async def broken(session, api, update, *, owner_id, base_url):
        raise RuntimeError(f"{update['message']['text']} from {owner_id} at {API_URL}")

    monkeypatch.setattr(telegram_bot, "handle_update", broken)
    telegram.queue = [an_update("/adduser mira", update_id=100)]
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with polling(app, bot_settings, api):
            await until(lambda: len(telegram.polls) == 2, "the poll after the failure")

    assert telegram.offsets == [None, 101]
    lines = said_after_polling_as(caplog)
    assert len(lines) == 1 and lines[0].levelno == logging.ERROR, lines
    assert "RuntimeError" in lines[0].getMessage()
    assert_nothing_leaked(caplog)


async def test_an_answer_whose_update_has_no_id_is_a_failed_call_not_a_dead_loop(
    app, bot_settings, api, telegram, caplog
) -> None:
    """Not the Bot API's answer, so handled as Telegram not answering: nothing from it is
    acted on, one line, backoff — and the loop is still there when a real one arrives."""
    telegram.queue = [{"message": an_update("/adduser mira", update_id=100)["message"]}]
    delays, sleep = sleeper(telegram)
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with polling(app, bot_settings, api, sleep=sleep):
            await until(lambda: len(delays) >= 3, "three retries")
            telegram.queue = [an_update("/help", update_id=100)]
            await until(lambda: telegram.texts == [USAGE], "the real update being handled")

    assert delays[:3] == [1, 2, 4]
    lines = [line.getMessage() for line in said_by_the_poller(caplog)]
    assert len(lines) == 3 and "polling as" in lines[0], lines
    assert "polling is failing" in lines[1] and "no id" in lines[1], lines
    assert "answers again" in lines[2], lines
    assert_nothing_leaked(caplog)


# --- Telegram cannot be reached ---------------------------------------------------------


async def test_unreachable_at_boot_is_one_line_and_then_polling_as_when_it_answers(
    app, bot_settings, api, telegram, caplog
) -> None:
    """``getMe`` failing does not kill the task or the app: one line, the wait doubling to a
    minute and no further, and the "polling as" line when Telegram first answers. Exactly
    two lines across nine retries."""
    telegram.down = True
    delays, sleep = sleeper(telegram, back_after=[9])
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with polling(app, bot_settings, api, sleep=sleep):
            await until(lambda: "getUpdates" in telegram.methods, "the first poll")

    assert delays == [1, 2, 4, 8, 16, 32, 60, 60, 60]
    assert delays[0] == BACKOFF_FIRST_SECONDS and max(delays) == BACKOFF_MAX_SECONDS
    assert telegram.methods == ["getMe"] * 10 + ["getUpdates"]
    lines = said_by_the_poller(caplog)
    assert [line.levelno for line in lines] == [logging.WARNING, logging.INFO], lines
    first, second = (line.getMessage() for line in lines)
    assert "polling is failing" in first and "getMe" in first and "ConnectError" in first
    assert second == f"telegram: polling as @{BOT_USERNAME}"
    assert_nothing_leaked(caplog)


async def test_going_away_mid_polling_is_one_line_when_it_starts_and_one_when_it_answers_again(
    app, bot_settings, api, telegram, caplog
) -> None:
    """Across ten failed polls: one line, then one; and after a recovery the wait starts
    over from one second rather than from where the last episode left off."""
    delays, sleep = sleeper(telegram, back_after=[10, 12])
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with polling(app, bot_settings, api, sleep=sleep):
            await until(lambda: len(telegram.polls) == 1, "the first poll")
            telegram.down = True
            telegram.nudge()
            await until(lambda: len(telegram.polls) == 11, "the poll after ten retries")
            telegram.nudge()
            await until(lambda: len(telegram.polls) == 12, "the poll after the recovery")
            # A second, short episode: the backoff is not carried over from the first.
            telegram.down = True
            telegram.nudge()
            await until(lambda: len(telegram.polls) == 14, "the poll after two retries")
            telegram.nudge()
            await until(lambda: len(telegram.polls) == 15, "the poll after the second recovery")

    assert delays == [1, 2, 4, 8, 16, 32, 60, 60, 60, 60, 1, 2]
    lines = [(line.levelno, line.getMessage()) for line in said_by_the_poller(caplog)]
    assert len(lines) == 5, lines
    assert lines[0] == (logging.INFO, f"telegram: polling as @{BOT_USERNAME}")
    for episode in (lines[1:3], lines[3:5]):
        (failing_level, failing), (resumed_level, resumed) = episode
        assert failing_level == logging.WARNING and resumed_level == logging.INFO
        assert "polling is failing" in failing and "getUpdates" in failing, failing
        assert "ConnectError" in failing, failing
        assert resumed == "telegram: Telegram answers again; polling resumed"
    assert_nothing_leaked(caplog)
