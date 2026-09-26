"""The three loggers `configure_logging` pins, and why deleting one is silent — M27.3.

WHAT: asserts that after ``main.configure_logging`` the loggers that write paths, tokens
      and decrypted values are at WARNING or off — asyncssh, uvicorn's access log, and
      SQLAlchemy's engine.
WHY:  the root is WARNING, so each of these three is quiet today by inheritance and each
      is one ``setLevel`` away from being loud. That is the point: raising the root to
      DEBUG is the ordinary way a person debugs, and `CLAUDE.md` forbids this at every
      level "including debug". Without this file the three lines that pin them can be
      tidied out of ``configure_logging`` — or replaced by a ``dictConfig`` that forgets
      one — and nothing anywhere goes red.

      What each of them writes, measured rather than assumed:

      * ``asyncssh`` at DEBUG writes one line per SFTP operation naming the REMOTE PATH.
        Forced against a real OpenSSH 9.6p1 sftp-server on 2026-09-26: every config file
        placed on a node, and since M27.2 every delivery artifact — whose name is derived
        from one user's subscription token and, since M27.3, is how that artifact is
        fetched.
      * ``uvicorn.access`` writes the request line, and a request line here is
        ``/sub/{token}``.
      * ``sqlalchemy.engine`` at INFO writes SQL with its bound parameters, which include
        values this database only ever holds encrypted.
HOW:  the levels are read back through ``getEffectiveLevel`` rather than from the source,
      so a pin that is present but overridden by something later in the function fails
      here too.

Boundary: this says nothing about what any of the three would actually print. It says
that this process has asked them not to, which is the half a test can hold.
"""

import logging

import pytest

from control.app.main import configure_logging

# Every logger this process pins, and the level it may not be louder than. asyncssh is
# M27.3's; the other two were pinned long before and were equally untested.
PINNED = ("asyncssh", "sqlalchemy.engine")


@pytest.fixture(autouse=True)
def restore_levels():
    """Put every level back, because logging is process-global.

    Without this, a suite running after these assertions would inherit whatever
    ``configure_logging`` last set — which is what the application wants and not what a
    neighbouring test asked for.
    """
    before = {
        name: (logging.getLogger(name).level, logging.getLogger(name).disabled)
        for name in (*PINNED, "uvicorn.access", "control", "edge", "")
    }
    yield
    for name, (level, disabled) in before.items():
        logging.getLogger(name).setLevel(level)
        logging.getLogger(name).disabled = disabled


@pytest.mark.parametrize("name", PINNED)
def test_a_library_that_writes_paths_and_parameters_is_never_louder_than_warning(
    name: str,
) -> None:
    """Pinned on the logger itself, so raising the ROOT to DEBUG does not reach it."""
    logging.getLogger().setLevel(logging.DEBUG)
    configure_logging()
    assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, (
        f"{name!r} would write at DEBUG or INFO in this process — see this file's header "
        "for what each of these logs, and CLAUDE.md for why no level is exempt"
    )


def test_the_access_log_is_off_whatever_started_this_process() -> None:
    """uvicorn is also started with ``--no-access-log`` and both are needed: the flag
    covers the server's own invocation, this covers a test harness, gunicorn, or a
    developer's ``uvicorn`` without it."""
    logging.getLogger("uvicorn.access").disabled = False
    configure_logging()
    assert logging.getLogger("uvicorn.access").disabled


def test_the_applications_own_loggers_are_still_raised() -> None:
    """The red half: a ``configure_logging`` that silenced everything would pass every
    assertion above and would also stop this project saying anything at all."""
    configure_logging()
    for name in ("control", "edge"):
        assert logging.getLogger(name).getEffectiveLevel() <= logging.INFO
