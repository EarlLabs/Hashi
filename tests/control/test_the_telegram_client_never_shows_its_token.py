"""The Bot API client's three calls, and that no failure of theirs shows the token — M37.1.

WHAT: what ``services.telegram_api.TelegramApi`` sends for ``get_me``, ``get_updates``
      and ``send_message``; what it raises when the far side fails to answer, times out,
      answers an error or answers nonsense; and that neither the exception nor any log
      record written while it failed carries the bot token or the API URL.
WHY:  every Bot API call is ``<api url>/bot<token>/<method>`` — a credential in a URL
      path, dialled out. ``httpx``'s own exceptions name the URL and its own logger
      writes the request line at INFO, so a client that let either through would put
      the token into the log the poller writes on every failure, with nobody watching.
      The plan's rule: one domain exception, and a fake transport that fails after
      which no log record and no exception string contains the token.
HOW:  an ``httpx.MockTransport`` plays Telegram, answering or raising without a socket,
      and records the request it was given. Logging is configured the way the process
      configures it (``main.configure_logging``) and then driven to DEBUG at the root,
      because the question is not whether the token is logged at the level an operator
      runs, it is whether any line anywhere writes it down.
"""

import json
import logging
from collections.abc import Callable

import httpx
import pytest

from control.app.main import configure_logging
from control.app.services.telegram_api import (
    CONNECT_TIMEOUT,
    LONG_POLL_GRACE,
    TelegramApi,
    TelegramCallFailed,
)

# The shape BotFather hands out, and an API host that is plainly not Telegram's — so the
# assertions below can look for both and would fail on a client that put either in a
# sentence.
TOKEN = "110201543:TEST-TOKEN-NEVER-REAL-9f3b2c1d8e7a6b5c4d3e2f1a0b9c8d7e"
API_URL = "https://bot-api.test"


def ok(result: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"ok": True, "result": result})


def a_client(handler: Callable[[httpx.Request], httpx.Response]) -> TelegramApi:
    return TelegramApi(token=TOKEN, api_url=API_URL, transport=httpx.MockTransport(handler))


class Recorded:
    """The last request the fake Telegram was given, as the test reads it."""

    request: httpx.Request | None = None

    @property
    def payload(self) -> dict:
        assert self.request is not None
        return json.loads(self.request.content)

    @property
    def read_timeout(self) -> float:
        assert self.request is not None
        return self.request.extensions["timeout"]["read"]


@pytest.fixture
def recorded() -> Recorded:
    return Recorded()


@pytest.fixture(autouse=True)
def restore_levels():
    """``configure_logging`` pins loggers for the process; put back what this file moves."""
    names = ("", "httpx", "httpcore", "control", "edge", "asyncssh", "sqlalchemy.engine")
    before = {name: logging.getLogger(name).level for name in names}
    yield
    for name, level in before.items():
        logging.getLogger(name).setLevel(level)


# --- what each call sends ------------------------------------------------------------


async def test_get_me_posts_to_the_tokens_url_and_returns_the_bots_account(recorded) -> None:
    def telegram(request: httpx.Request) -> httpx.Response:
        recorded.request = request
        return ok({"id": 110201543, "is_bot": True, "username": "hashi_test_bot"})

    async with a_client(telegram) as api:
        me = await api.get_me()

    assert me["username"] == "hashi_test_bot"
    assert recorded.request.method == "POST"
    assert str(recorded.request.url) == f"{API_URL}/bot{TOKEN}/getMe"


async def test_a_trailing_slash_on_the_api_url_does_not_double_up(recorded) -> None:
    def telegram(request: httpx.Request) -> httpx.Response:
        recorded.request = request
        return ok({"id": 1, "username": "x"})

    async with TelegramApi(
        token=TOKEN, api_url=API_URL + "/", transport=httpx.MockTransport(telegram)
    ) as api:
        await api.get_me()
    assert str(recorded.request.url) == f"{API_URL}/bot{TOKEN}/getMe"


async def test_get_updates_asks_for_messages_only_and_reads_longer_than_it_polls(
    recorded,
) -> None:
    """``allowed_updates`` is ``["message"]`` so Telegram delivers nothing else, and the
    HTTP read ceiling exceeds the long-poll ``timeout``: Telegram holds the request open
    for exactly that long, so a read ceiling at or under it would time out every empty
    poll and read a healthy bot as a failing one."""
    update = {"update_id": 7, "message": {"message_id": 1, "text": "/adduser"}}

    def telegram(request: httpx.Request) -> httpx.Response:
        recorded.request = request
        return ok([update])

    async with a_client(telegram) as api:
        updates = await api.get_updates(offset=8, timeout=30)

    assert updates == [update]
    assert str(recorded.request.url) == f"{API_URL}/bot{TOKEN}/getUpdates"
    assert recorded.payload == {"offset": 8, "timeout": 30, "allowed_updates": ["message"]}
    assert recorded.read_timeout > 30
    assert recorded.read_timeout == 30 + LONG_POLL_GRACE
    assert recorded.request.extensions["timeout"]["connect"] == CONNECT_TIMEOUT


async def test_the_first_poll_sends_no_offset(recorded) -> None:
    """``None`` means "whatever is still unacknowledged", which is what a process that
    has just started has to ask for; sending ``offset: null`` is not the same request."""

    def telegram(request: httpx.Request) -> httpx.Response:
        recorded.request = request
        return ok([])

    async with a_client(telegram) as api:
        assert await api.get_updates(offset=None, timeout=5) == []
    assert "offset" not in recorded.payload


async def test_send_message_is_plain_text_with_no_preview(recorded) -> None:
    """No ``parse_mode``: a nickname with ``_`` or ``*`` in it is sent as typed rather than
    refused as bad markup. No link preview: the text carries subscription links, and a
    preview is Telegram's crawler fetching the subscription itself."""

    def telegram(request: httpx.Request) -> httpx.Response:
        recorded.request = request
        return ok({"message_id": 42})

    async with a_client(telegram) as api:
        assert await api.send_message(987654321, "added: https://x.test/sub/abc *_*") is None

    assert str(recorded.request.url) == f"{API_URL}/bot{TOKEN}/sendMessage"
    payload = recorded.payload
    assert payload["chat_id"] == 987654321
    assert payload["text"] == "added: https://x.test/sub/abc *_*"
    assert "parse_mode" not in payload
    assert payload["link_preview_options"] == {"is_disabled": True}


# --- every failure is one exception, and it says nothing it should not ----------------


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[Errno 61] Connection refused", request=request)


def times_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


def resets(request: httpx.Request) -> httpx.Response:
    raise httpx.RemoteProtocolError("Server disconnected", request=request)


def not_httpx_at_all(request: httpx.Request) -> httpx.Response:
    raise RuntimeError(f"a fake that misbehaves, quoting {request.url}")


def unauthorized(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
    )


def conflict(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        409,
        json={
            "ok": False,
            "error_code": 409,
            "description": "Conflict: terminated by other getUpdates request",
        },
    )


def gateway_html(request: httpx.Request) -> httpx.Response:
    return httpx.Response(502, text=f"<html><body>bad gateway for {request.url}</body></html>")


def ok_but_html(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=f"<html>a relay's login page, mentioning {request.url}</html>")


def ok_false(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": False, "description": f"echo {request.url}"})


def ok_without_result(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


def result_of_the_wrong_shape(request: httpx.Request) -> httpx.Response:
    return ok(f"a string, not an object or a list, saying {request.url}")


FAILURES = [
    unreachable,
    times_out,
    resets,
    not_httpx_at_all,
    unauthorized,
    conflict,
    gateway_html,
    ok_but_html,
    ok_false,
    ok_without_result,
]


async def each_call(api: TelegramApi):
    yield "get_me", api.get_me()
    yield "get_updates", api.get_updates(offset=None, timeout=1)
    yield "send_message", api.send_message(1, "hello")


@pytest.mark.parametrize("telegram", FAILURES, ids=lambda f: f.__name__)
async def test_every_failure_is_the_one_exception_with_neither_url_nor_token_in_it(
    telegram, caplog
) -> None:
    """The plan's assertion, over every way a call can fail and every call.

    Asserted on the RENDERING — ``str`` and ``repr`` — and on the chain: an ``httpx``
    exception carries the request it was raised for, URL and token included, so a
    ``raise ... from exc`` would hand the token to the next traceback that printed a
    cause, and so would a bare ``raise`` inside an ``except``. A failure raised with no
    exception in flight — an error status, a body of the wrong shape — has no context
    to suppress, which is the other way the chain can be empty.
    """
    configure_logging()
    async with a_client(telegram) as api:
        async for name, call in each_call(api):
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(TelegramCallFailed) as failure:
                    await call
            exc = failure.value
            for rendering in (str(exc), repr(exc)):
                assert TOKEN not in rendering, f"{name} printed the token"
                assert API_URL not in rendering, f"{name} printed the API URL"
                assert "/bot" not in rendering, f"{name} printed part of the token's path"
            assert exc.__cause__ is None, f"{name} chained an exception that holds the URL"
            assert exc.__context__ is None or exc.__suppress_context__, (
                f"{name} left the context to be printed"
            )

    # Reported by LOGGER NAME: naming the record would put the token in the failure
    # message, which is the leak this asserts against.
    said_it = sorted(
        {
            record.name
            for record in caplog.records
            if TOKEN in record.getMessage() or API_URL in record.getMessage()
        }
    )
    assert said_it == [], f"the bot token or the API URL reached a log record from: {said_it}"


async def test_a_result_of_the_wrong_shape_fails_the_calls_that_read_one() -> None:
    """``get_me`` and ``get_updates`` hand the result on, so a result that is not what
    the Bot API promises is a failure — with the same sentence and the same silence about
    what it was. ``send_message`` reads nothing from its result: ``ok`` is the answer, and
    a bot that refused to count a message as sent because of a field it never looks at
    would fail on the day Telegram reshapes the one object it does not use."""
    async with a_client(result_of_the_wrong_shape) as api:
        for name, call in (("get_me", api.get_me()), ("get_updates", api.get_updates(None, 1))):
            with pytest.raises(TelegramCallFailed) as failure:
                await call
            assert TOKEN not in str(failure.value) and API_URL not in str(failure.value), name
            assert "not the Bot API's" in str(failure.value), name
        await api.send_message(1, "sent regardless of the result's shape")


async def test_a_successful_call_writes_nothing_down_either(caplog) -> None:
    """The red half of the pin in ``configure_logging``: without it, ``httpx`` writes the
    request line — URL, token and all — at INFO on every call that got an answer, which
    is every successful one. The client itself has no logger and nothing to say."""
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        async with a_client(lambda request: ok({"id": 1, "username": "x"})) as api:
            await api.get_me()
    assert [record.name for record in caplog.records if TOKEN in record.getMessage()] == []
    assert [record for record in caplog.records if record.name.startswith("control")] == []


async def test_the_sentences_tell_the_failures_apart_for_the_person_reading_them() -> None:
    """One type, four sentences; what the poller logs is this text, so it has to say
    which of the four it was — by the method, a status, the seconds or the TYPE of
    transport failure, which names nothing."""
    async with a_client(unreachable) as api:
        with pytest.raises(TelegramCallFailed) as failure:
            await api.get_me()
    assert str(failure.value) == "Telegram could not be reached for getMe (ConnectError)."

    async with a_client(times_out) as api:
        with pytest.raises(TelegramCallFailed) as failure:
            await api.get_updates(offset=None, timeout=25)
    assert str(failure.value) == (
        f"Telegram did not answer getUpdates within {25 + LONG_POLL_GRACE:.0f} seconds."
    )

    async with a_client(unauthorized) as api:
        with pytest.raises(TelegramCallFailed) as failure:
            await api.send_message(1, "x")
    assert str(failure.value) == "Telegram answered HTTP 401 to sendMessage."

    async with a_client(ok_but_html) as api:
        with pytest.raises(TelegramCallFailed) as failure:
            await api.get_me()
    assert str(failure.value) == (
        "Telegram answered getMe with a body that is not the Bot API's (HTTP 200)."
    )
    # And the one case that is a domain error to the API's envelope, should it ever
    # reach a route: the far side failed, which is not a bad request of the operator's.
    assert failure.value.status_code == 502
    assert failure.value.code == "telegram_call_failed"


async def test_a_message_the_bot_was_never_given_does_not_reach_a_sentence() -> None:
    """Telegram's ``description`` is remote text and is dropped on purpose — it has
    nothing the status does not say, and a relay could put anything in it."""
    async with a_client(conflict) as api:
        with pytest.raises(TelegramCallFailed) as failure:
            await api.get_updates(offset=None, timeout=1)
    assert "terminated" not in str(failure.value)
    assert "409" in str(failure.value)
