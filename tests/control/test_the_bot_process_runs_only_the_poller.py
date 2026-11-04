"""The bot-only process does the web process's wiring, then polls — M39.1.

WHAT: that control/app/botmain refuses to run with no token (this container exists only to
      run the bot), binds the ``SecretBox`` and apply's settings BEFORE it polls — so an
      ``/adduser`` can read an encrypted column and reach a node, exactly as the web
      process's ``create_app`` arranges — and that a poll loop which ends on its own
      surfaces its failure and still closes the pool, rather than exiting as though it had
      stopped cleanly.
WHY:  this process has no HTTP surface and no lifespan the application tests exercise, so
      without this nothing asserts the bot container is wired like the control plane it
      stands in for. The refusal and the two bind calls are the difference between a bot
      that answers and one that raises on the first command.
HOW:  the heavy collaborators — ``Settings``, ``SecretBox``, ``Database`` and the poller —
      are replaced with recorders, and the supervisor's beat interval is shrunk so a poll
      task that ends is noticed at once instead of after fifteen seconds. ``_run`` is the
      process's body; ``main`` only wraps it in ``asyncio.run``.
"""

import asyncio
import types

import pytest

from control.app import botmain


@pytest.fixture
def wiring(monkeypatch, tmp_path):
    """Replace botmain's collaborators with recorders; return what they saw."""
    seen: dict = {
        "secret_key": None,
        "bound_box": None,
        "bound_settings": None,
        "db_url": None,
        "started_with": None,
        "disposed": False,
    }
    # Not under test here, and it has process-wide side effects (it reconfigures logging);
    # a no-op keeps these tests from moving every logger's level.
    monkeypatch.setattr(botmain, "configure_logging", lambda: None)
    monkeypatch.setattr(botmain, "HEARTBEAT_PATH", tmp_path / "alive")
    monkeypatch.setattr(botmain, "HEARTBEAT_INTERVAL_SECONDS", 0.01)

    box = object()

    def fake_secretbox(key):
        seen["secret_key"] = key
        return box

    def fake_bind_box(bound):
        seen["bound_box"] = bound

    def fake_bind_settings(bound):
        seen["bound_settings"] = bound

    class FakeDatabase:
        def __init__(self, url):
            seen["db_url"] = url

        async def dispose(self):
            seen["disposed"] = True

    monkeypatch.setattr(botmain, "SecretBox", fake_secretbox)
    monkeypatch.setattr(botmain, "bind_secret_box", fake_bind_box)
    monkeypatch.setattr(botmain.apply, "bind_settings", fake_bind_settings)
    monkeypatch.setattr(botmain, "Database", FakeDatabase)
    return seen


def _poller_returning(coroutine_factory):
    """A ``start_poller`` stand-in that runs ``coroutine_factory`` as the poll task."""

    def start_poller(database, settings):
        return asyncio.create_task(coroutine_factory())

    return start_poller


def test_a_blank_token_refuses_to_run(wiring, monkeypatch) -> None:
    """With no token there is nothing to run, and it is refused before anything is bound —
    an idle bot container would be a bot the owner believes is on."""
    monkeypatch.setattr(
        botmain, "Settings", lambda: types.SimpleNamespace(telegram_bot_token=None)
    )

    with pytest.raises(SystemExit):
        asyncio.run(botmain._run())

    assert wiring["bound_box"] is None, "it bound the secret box before refusing"
    assert wiring["started_with"] is None, "it started a poller with no token"


def test_it_binds_the_box_and_the_settings_before_it_polls(wiring, monkeypatch) -> None:
    """The same wiring create_app does: the box bound from the secret key, apply holding the
    settings, the database built from its URL, and the poller handed both."""
    settings = types.SimpleNamespace(
        telegram_bot_token="a-token", secret_key="a-secret-key", database_url="the-db-url"
    )
    monkeypatch.setattr(botmain, "Settings", lambda: settings)

    async def ends_cleanly():
        return None

    def start_poller(database, started_settings):
        wiring["started_with"] = (database, started_settings)
        return asyncio.create_task(ends_cleanly())

    monkeypatch.setattr(botmain.telegram_poller, "start_poller", start_poller)

    asyncio.run(botmain._run())

    assert wiring["secret_key"] == "a-secret-key"
    assert wiring["bound_box"] is not None, "the secret box was never bound"
    assert wiring["bound_settings"] is settings, "apply was not given the settings"
    assert wiring["db_url"] == "the-db-url"
    assert wiring["started_with"][1] is settings, "the poller was not handed the settings"
    assert wiring["started_with"][0] is not None, "the poller was not handed a database"
    assert wiring["disposed"] is True, "the pool was not closed on shutdown"


def test_a_poll_loop_that_crashes_surfaces_its_failure_and_still_disposes(
    wiring, monkeypatch
) -> None:
    """A loop that ends by raising must not look like a clean stop: its exception reaches the
    non-zero exit, and the pool is closed on the way out regardless."""
    settings = types.SimpleNamespace(
        telegram_bot_token="a-token", secret_key="k", database_url="u"
    )
    monkeypatch.setattr(botmain, "Settings", lambda: settings)

    async def crashes():
        raise RuntimeError("boom in the poll loop")

    monkeypatch.setattr(
        botmain.telegram_poller, "start_poller", _poller_returning(crashes)
    )

    with pytest.raises(RuntimeError, match="boom in the poll loop"):
        asyncio.run(botmain._run())

    assert wiring["disposed"] is True, "the pool was not closed when the loop crashed"
