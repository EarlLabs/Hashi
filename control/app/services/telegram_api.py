"""A thin client for the Telegram Bot API that never shows its token — M37.1.

WHAT: ``TelegramApi`` — the three calls the owner's bot needs (``get_me``,
      ``get_updates``, ``send_message``) over ``httpx``, and ``TelegramCallFailed``, the
      one exception every failure of those calls becomes.
WHY:  every Bot API call is ``<api url>/bot<token>/<method>``: the token is a bearer
      credential in a URL path, which is the trap this project already has with
      ``/sub/`` — now on an OUTBOUND call. An HTTP library's own exception names the
      URL it was sent to, and its own logger writes the request line. So this module
      composes every sentence it raises itself, from the method name, a status code, a
      number of seconds or an exception's TYPE, never from the URL or from text a remote
      host sent; and it writes no log line at all. The one fact worth a line — that a
      call failed — travels as the exception, to a caller who knows whether it is the
      first failure or the hundredth. (``httpx``'s own request-line logger is pinned
      quiet in ``main.configure_logging``, beside asyncssh's.)
HOW:  one ``httpx.AsyncClient`` per instance, bound to the token's base URL, with the
      transport injectable so a test can fail it without a network. Plain JSON in,
      Telegram's ``{"ok": true, "result": ...}`` out; anything else is the exception.
      ``send_message`` is plain text — no parse mode, so a nickname containing ``_`` or
      ``*`` is sent as typed rather than refused as bad markup — and asks Telegram not
      to preview the links it carries: a preview is Telegram's crawler fetching the
      subscription itself, which is more of the credential's content leaving the fleet
      than the link already does.
"""

from collections.abc import Sequence
from typing import Any, Self

import httpx

from control.app.errors import DomainError

# Ceilings, in seconds, on one call. Connect is short because a blocked endpoint hangs
# rather than refusing (``settings.node_connect_timeout``'s reason); the read ceiling on
# an ordinary call is what a ``sendMessage`` to Telegram reasonably takes from a slow
# link. Constants rather than settings, for now: the milestone adds three settings and
# names them, and a field run from the entry box — not a stand — is what would show
# whether these need to move. ``LONG_POLL_GRACE`` is how much longer than the long-poll
# ``timeout`` the HTTP read waits: Telegram holds the request open for exactly that many
# seconds and then answers, so a read ceiling at or under it would time out every empty
# poll and read a healthy bot as a failing one.
CONNECT_TIMEOUT = 10.0
CALL_TIMEOUT = 30.0
LONG_POLL_GRACE = 10.0

# What ``get_updates`` asks for unless told otherwise. ``message`` only, so Telegram does
# not even deliver edits, channel posts, joins or callbacks — the bot acts on one kind of
# update from one account, and not receiving the rest is cheaper and safer than
# ignoring them (docs/PLAN.md, M37). A tuple, because a list default is shared state.
DEFAULT_ALLOWED_UPDATES: tuple[str, ...] = ("message",)


class TelegramCallFailed(DomainError):
    """A Bot API call did not complete, in a sentence that carries neither URL nor token.

    One type for every way a call fails — unreachable, timed out, an error status, a body
    that is not the Bot API's — because every caller does the same thing with all of
    them: say so once and try again later. The sentence tells the four apart for the
    person reading it; nothing branches on them.

    502 and its own code, ``NodeOperationFailed``'s shape: the far side did not answer
    as it should, and that is not a bad request of the operator's. No route raises it
    today — the poller catches it — but a ``DomainError`` is what every service here
    raises, and one that ever reaches a route renders as the envelope instead of a 500.
    """

    status_code = 502
    code = "telegram_call_failed"


class TelegramApi:
    """The Bot API, as the three calls the bot makes.

    ``token`` is the plain value: the caller unwraps the ``SecretStr`` at this one
    point of use (``settings.telegram_bot_token.get_secret_value()``), and this object
    keeps it only inside the client's base URL. ``transport`` exists for tests — an
    ``httpx.MockTransport`` that answers or fails without a socket.
    """

    def __init__(
        self,
        *,
        token: str,
        api_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Redirects are NOT followed, which is httpx's default and is kept on purpose:
        # following one would send the token to whatever host the redirect names.
        self._client = httpx.AsyncClient(
            base_url=f"{api_url.rstrip('/')}/bot{token}/",
            transport=transport,
            timeout=httpx.Timeout(CONNECT_TIMEOUT, read=CALL_TIMEOUT),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def get_me(self) -> dict[str, Any]:
        """The bot's own account: ``id``, ``username`` and the rest, as Telegram sent it."""
        result = await self._call("getMe", {}, read_timeout=CALL_TIMEOUT)
        if not isinstance(result, dict):
            raise TelegramCallFailed(_not_the_bot_api("getMe"))
        return result

    async def get_updates(
        self,
        offset: int | None,
        timeout: int,
        allowed_updates: Sequence[str] = DEFAULT_ALLOWED_UPDATES,
    ) -> list[dict[str, Any]]:
        """Long-poll for updates: block up to ``timeout`` seconds, then answer.

        ``offset`` is Telegram's own cursor — one more than the last update id the caller
        has handled — and ``None`` on the first call, which asks for whatever is still
        unacknowledged. Each returned item is one update, exactly as Telegram shaped it.
        """
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": list(allowed_updates)}
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload, read_timeout=timeout + LONG_POLL_GRACE)
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise TelegramCallFailed(_not_the_bot_api("getUpdates"))
        return result

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send ``text`` to ``chat_id`` as plain text. It was sent, or this raised."""
        await self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "link_preview_options": {"is_disabled": True},
            },
            read_timeout=CALL_TIMEOUT,
        )

    async def _call(self, method: str, payload: dict[str, Any], *, read_timeout: float) -> Any:
        """POST one method and return its ``result``, or raise ``TelegramCallFailed``.

        Every ``raise`` below is ``from None``: an ``httpx`` exception carries the request
        it was raised for, URL and token included, and a cause on the chain is printed by
        every traceback. The TYPE's name is kept in the sentence instead — it is what tells
        a refused connection from a reset one, and it names nothing.
        """
        try:
            response = await self._client.post(
                method,
                json=payload,
                timeout=httpx.Timeout(CONNECT_TIMEOUT, read=read_timeout),
            )
        except httpx.TimeoutException:
            raise TelegramCallFailed(
                f"Telegram did not answer {method} within {read_timeout:.0f} seconds."
            ) from None
        except Exception as exc:
            # Broad on purpose, and narrow in reach: the only thing inside the ``try`` is
            # the request, so whatever escapes it is the call not completing — httpx's
            # own family, or a fake transport in a test raising what it likes.
            raise TelegramCallFailed(
                f"Telegram could not be reached for {method} ({type(exc).__name__})."
            ) from None
        # Not ``raise_for_status()``: its message quotes the URL.
        if not response.is_success:
            raise TelegramCallFailed(f"Telegram answered HTTP {response.status_code} to {method}.")
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or body.get("ok") is not True or "result" not in body:
            raise TelegramCallFailed(_not_the_bot_api(method, status=response.status_code))
        return body["result"]


def _not_the_bot_api(method: str, *, status: int | None = None) -> str:
    """The sentence for a body that is not what the Bot API promises for ``method``.

    What the body WAS is deliberately not in it — ``routing.FetchFailed``'s rule: text a
    remote host sent is shown nowhere, and this sentence ends up in a log line written
    with nobody watching. A relay that answers HTML, or a Bot API that changed shape,
    reads the same here, and the status tells the two apart well enough to go and look.
    """
    where = f" (HTTP {status})" if status is not None else ""
    return f"Telegram answered {method} with a body that is not the Bot API's{where}."
