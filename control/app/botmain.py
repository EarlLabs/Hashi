"""Bot-only entry point — the Telegram poller as its own process — M39.1.

WHAT: builds the ``Settings``, the ``Database`` and the same bindings ``create_app`` wires
      onto the web process, then runs ONLY the Telegram poller
      (``services/telegram_poller``) against that database until it is told to stop. It
      starts no uvicorn, no web app, and none of the lifespan's other background tasks.
WHY:  the bot used to run in-process in the control plane (M37.3, in ``main.py``'s
      lifespan). It now lives in its own container beside the control plane, tied to it
      by the shared Postgres on the local docker network — nothing new between them, the
      same host and the same trust boundary. Only its hosting changes: the loop, the
      commands and the words are reused verbatim. Moving the poll OUT of the web process
      is the point — two pollers on one bot token is a 409 from Telegram and every update
      handled twice — so the web process no longer polls and this process is the only one
      that does.
HOW:  the startup here mirrors the parts of ``create_app`` the bot's own code reaches:
      ``configure_logging`` (its httpx/httpcore pin is what keeps the bot token out of the
      log, so it is imported, never re-stated), the ``SecretBox`` bound so encrypted
      columns read and write, and ``apply.bind_settings`` so a ``/adduser`` push and an
      ``/apply`` can reach a node. SIGTERM — what ``docker stop`` sends — is caught and the
      poller cancelled and the pool disposed, so a stop is graceful rather than a kill.
      This container serves no HTTP, so its healthcheck reads a heartbeat file this
      supervisor rewrites while the poll loop is alive (see ``HEARTBEAT_PATH``).
"""

import asyncio
import contextlib
import logging
import pathlib
import signal
import time

from control.app.crypto import SecretBox
from control.app.db import Database
from control.app.main import configure_logging
from control.app.models.base import bind_secret_box
from control.app.services import apply, telegram_poller
from control.app.settings import Settings

logger = logging.getLogger(__name__)

# The liveness signal for this container's healthcheck. The process serves no HTTP, so
# there is no ``/healthz`` to probe; instead the supervisor below rewrites this file on a
# fixed beat while the poll loop is alive, and the healthcheck in deploy/docker-compose.yml
# calls the service unhealthy once the file goes stale. The path is named in both places
# and the two have to agree. ``/tmp`` because it is a directory the non-root ``hashi`` user
# in the control image can always write.
HEARTBEAT_PATH = pathlib.Path("/tmp/hashi-telegram-bot.alive")
HEARTBEAT_INTERVAL_SECONDS = 15.0


async def _beat_while_polling(poller: asyncio.Task, stop: asyncio.Event) -> None:
    """Rewrite the heartbeat on a beat; ask for shutdown if the poll loop ever ends.

    ``poll_forever`` only returns when it is cancelled — its own contract — so a poller that
    is ``done()`` while we did not cancel it is a bug that has taken the bot off the air. It
    ends two ways and the log says which: it RAISED (its exception is re-raised from
    ``stop_poller`` during the shutdown below, so the process exits non-zero WITH the
    traceback — it did not stop cleanly) or it RETURNED (a clean exit). Either way
    ``restart: unless-stopped`` brings a fresh one up; this only takes the wedged process
    down so that can happen, rather than a container that is up with nothing polling behind it.
    """
    while not stop.is_set():
        if poller.done():
            if poller.cancelled() or poller.exception() is None:
                logger.error("telegram-bot: the poll loop ended on its own; exiting to restart.")
            else:
                logger.error("telegram-bot: the poll loop crashed; exiting to restart.")
            stop.set()
            return
        HEARTBEAT_PATH.write_text(str(time.time()))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)


async def _run() -> None:
    configure_logging()
    settings = Settings()
    if settings.telegram_bot_token is None:
        # This container exists only to run the bot. With no token there is nothing to run,
        # and an idle container would be a bot the owner believes is on. The web process
        # tolerates a blank token (it simply starts no poller); here it is refused, loudly.
        raise SystemExit(
            "telegram-bot: HASHI_TELEGRAM_BOT_TOKEN is not set, so there is no bot to run. "
            "Set the token and the owner id, or do not start the telegram-bot service."
        )

    # The same wiring create_app does for the web process, and for the same reasons: the
    # box has to be bound before any encrypted column is read or written (a node's SSH key,
    # a user's token), and apply has to hold the settings before a node is pushed to.
    bind_secret_box(SecretBox(settings.secret_key))
    apply.bind_settings(settings)
    database = Database(settings.database_url)

    poller = telegram_poller.start_poller(database, settings)
    if poller is None:
        # Unreachable: the token is set, so start_poller returns a task. Guarded so a future
        # change to its contract fails here, not as a None awaited two lines down.
        raise SystemExit("telegram-bot: the poll loop did not start despite a configured token.")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signalnum in (signal.SIGTERM, signal.SIGINT):
        # `docker stop` sends SIGTERM; catching it is what makes shutdown graceful rather
        # than the ten-second kill a process that ignores it gets. SIGINT so a foreground
        # run (a developer, the smoke check) stops on Ctrl-C the same way.
        loop.add_signal_handler(signalnum, stop.set)

    heartbeat = asyncio.create_task(_beat_while_polling(poller, stop), name="bot-heartbeat")
    try:
        await stop.wait()
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        # Cancel the poll loop before the pool is disposed — telegram_poller.stop_poller's
        # and audit.stop_sweeper's rule: the loop may hold a session, and disposing the
        # engine out from under it turns a clean shutdown into a traceback nobody reads. If
        # the loop already ended by crashing, stop_poller re-raises its exception here on
        # purpose — the failure belongs in the log and in the non-zero exit, not swallowed —
        # and dispose still runs, from the inner finally.
        try:
            await telegram_poller.stop_poller(poller)
        finally:
            await database.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
