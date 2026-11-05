"""The polling task that lives and dies with the application — M37.3.

WHAT: ``start_poller`` / ``stop_poller``, the lifespan's fourth background task, and
      ``poll_forever``, the loop it runs: long-poll Telegram for updates, hand each one
      to ``telegram_bot.handle_update`` in turn, and keep going until cancelled.
WHY:  its own module rather than a corner of ``telegram_bot``: that module is the words
      and the gate, and is tested by calling it with one update and a session the test
      holds. Everything here is the other kind of code — a task, a session factory, a
      clock, a client that dials out — and keeping it apart is what lets the commands
      stay testable without a loop around them.

      TWO RULES SHAPE THE LOOP, and both are about what happens with nobody watching.

      An update is ACKNOWLEDGED AFTER ONE ATTEMPT, whether that attempt returned or
      raised. Telegram re-delivers every update the bot has not acknowledged, for a day;
      a handler that raised on an update would otherwise be handed the same one on every
      poll — a poison update, one ``/adduser`` of a name that trips something, that stops
      every command behind it. So the offset moves past an update the moment its attempt
      is over, and a failure is one log line. Only the process dying between the attempt
      and the next poll makes Telegram send it again, and then the nickname's uniqueness
      turns the second attempt into an "already exists" reply, not a second user.

      WHEN TELEGRAM CANNOT BE REACHED, the loop backs off — doubling, capped at a minute
      — and the log gets one line when polling starts failing and one when it answers
      again, not one per retry. This process sits on the entry box, in Russia; whether
      the Bot API answers from there at all, and for how long at a stretch, is a field
      fact, and a loop that wrote a line every few seconds for a night would be the
      loudest thing in the log about the least interesting event in it. The same rule
      covers the first call: if ``getMe`` fails at boot the task does not die and does
      not take the application with it — it is the same unreachable Telegram, and the
      "polling as" line is written when it first answers. The panel and ``/sub/`` are
      never affected: this task holds no session across a poll and shares nothing with a
      request but the pool.

HOW:  one ``TelegramApi`` for the task's life, built in ``start_poller`` and closed when
      the task ends; one ``AsyncSession`` per update, from the application's own factory
      and never a request's, released before the next poll. The loop is one plain
      coroutine with an injectable sleeper, so a test can walk the backoff without
      waiting a minute; cancellation is never caught — ``CancelledError`` is not an
      ``Exception`` — so the lifespan's ``cancel()`` ends the loop wherever it is,
      mid-poll included.

      THE LOG never gets the token, the API URL, an update's text, a nickname, a link or
      a sender's id. What it gets: the bot's username once; a failing poll's own sentence
      (``TelegramCallFailed`` composes it with none of the above); and, for a handler that
      raised, the sentence when it is a domain error — ours, written to be shown — and the
      TYPE only when it is anything else, ``health``'s rule: an arbitrary error's text can
      quote a bound parameter, which here is a nickname typed into the message, or a
      node's address.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from control.app.db import Database
from control.app.errors import DomainError
from control.app.services import telegram_bot
from control.app.services.telegram_api import TelegramApi, TelegramCallFailed
from control.app.settings import Settings

logger = logging.getLogger(__name__)

# How long one ``getUpdates`` is held open by Telegram before it answers empty. Thirty
# seconds is the Bot API's own customary value; the client reads for ten seconds longer
# than this (``telegram_api.LONG_POLL_GRACE``). A constant and not a setting, with the
# client's own timeouts: nothing on a stand can say what the entry box needs.
LONG_POLL_SECONDS = 30

# The wait after a failed call, in seconds: the first one, then doubling, up to the cap.
# One second first because the common failure is a blip and a minute is a long time to
# leave the owner's command unanswered; a minute at most because beyond that the bot is
# not noticeably more polite to a host that is down, only slower to notice it is back.
BACKOFF_FIRST_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 60.0

Sleep = Callable[[float], Awaitable[None]]


async def poll_forever(
    database: Database, settings: Settings, api: TelegramApi, *, sleep: Sleep = asyncio.sleep
) -> None:
    """Poll, handle, acknowledge, repeat — until cancelled.

    ``getMe`` first, once it answers: the one line saying which bot this is, so an
    operator reading the log can tell a token for the wrong bot from a bot nobody
    messages. ``sleep`` is the backoff's clock, injectable for the test that walks it.
    """
    username: str | None = None
    offset: int | None = None
    # Whether the LAST call to Telegram failed — the one bit that turns "every retry
    # fails" into one line when it starts and one when it stops.
    failing = False
    delay = BACKOFF_FIRST_SECONDS
    while True:
        try:
            if username is None:
                username = str((await api.get_me()).get("username"))
                # Not a separate "answers again" line here, even after a failed boot:
                # polling has not resumed, it has started, and this line says so.
                failing = False
                delay = BACKOFF_FIRST_SECONDS
                logger.info("telegram: polling as @%s", username)
                continue
            updates = await api.get_updates(offset, timeout=LONG_POLL_SECONDS)
            _each_has_an_id(updates)
        except TelegramCallFailed as exc:
            # The failure's own sentence, which names the method and a type or a status
            # and nothing else — the client's contract, not this module's assumption.
            what, level = str(exc), logging.WARNING
        except Exception as exc:
            # The last resort, for the header's promise that this task does not die.
            # The client wraps every failure of a call, so nothing is expected here —
            # which is why it is an ERROR, and why it is the type only: a sentence
            # nobody composed can carry anything. Same backoff, same one line per
            # episode. ``CancelledError`` is not an ``Exception`` and is not caught.
            what, level = f"An unexpected {type(exc).__name__}.", logging.ERROR
        else:
            if failing:
                logger.info("telegram: Telegram answers again; polling resumed")
                failing = False
            delay = BACKOFF_FIRST_SECONDS
            for update in updates:
                await _attempt(database, settings, api, update)
                # Acknowledged here, after the one attempt, whatever it did: the next
                # poll asks for everything after this one. See the header for why a
                # failure does not hold the offset back.
                offset = update["update_id"] + 1
            continue
        if not failing:
            logger.log(
                level,
                "telegram: polling is failing: %s Retrying, up to a minute apart, "
                "until Telegram answers; this is said once, not per retry.",
                what,
            )
            failing = True
        await sleep(delay)
        delay = min(delay * 2, BACKOFF_MAX_SECONDS)


def _each_has_an_id(updates: list[dict[str, Any]]) -> None:
    """Refuse a batch the loop could not acknowledge, as a failed call.

    ``update_id`` is the one field every Bot API update carries and the only one this
    loop reads. An answer without it is not the Bot API's — a relay answering with
    something else — and is treated as the call having failed: one line, backoff, retry.
    Handling such a batch and then not advancing past it would be the poison update
    the header rules out, one poll after another.
    """
    if any(
        not isinstance(update, dict) or type(update.get("update_id")) is not int
        for update in updates
    ):
        raise TelegramCallFailed("Telegram answered getUpdates with an update that has no id.")


async def _attempt(
    database: Database, settings: Settings, api: TelegramApi, update: dict[str, Any]
) -> None:
    """One attempt at one update, with its own session; a failure is one line, not a raise."""
    try:
        async for session in database.session():
            await telegram_bot.handle_update(
                session,
                api,
                update,
                owner_id=settings.telegram_owner_id,
                base_url=settings.public_base_url,
            )
    except Exception as exc:
        # The sentence for a domain error — composed by this project to be shown; the
        # TYPE for anything else (``health.remeasure_findings``' rule, and why the
        # header says so). Nothing from the update itself, ever: not its text, not who
        # sent it.
        what = exc.message if isinstance(exc, DomainError) else type(exc).__name__
        logger.error(
            "telegram: an update was not handled (%s). It is acknowledged and not retried; "
            "a command the owner sent is theirs to send again.",
            what,
        )


def start_poller(database: Database, settings: Settings) -> asyncio.Task | None:
    """The loop as a task for the lifespan to hold, or ``None`` when the bot is off.

    Off is both settings blank; the validator on ``Settings`` has already refused one
    without the other, so the token alone decides here. The client is built here and
    closed by the task itself when it ends, so a cancelled task leaves no open client
    behind for asyncio to complain about at shutdown.
    """
    if settings.telegram_bot_token is None:
        return None
    api = TelegramApi(
        token=settings.telegram_bot_token.get_secret_value(),
        api_url=settings.telegram_api_url,
    )

    async def run() -> None:
        async with api:
            await poll_forever(database, settings, api)

    return asyncio.create_task(run(), name="telegram-poll")


async def stop_poller(task: asyncio.Task | None) -> None:
    """Cancel the loop and wait for it, for ``audit.stop_sweeper``'s reason."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
