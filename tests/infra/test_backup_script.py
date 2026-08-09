"""The backup script's contract — backlog item 22.

WHAT: static checks over ``scripts/backup.sh`` and the Make targets that call it.
WHY:  the control database is the one thing whose loss cannot be repaired by
      rebuilding a node (core invariants §3), and a backup routine is only ever tested
      by an emergency. The properties here are the ones whose absence would be
      discovered at exactly the wrong moment: a restore that half-succeeds, a dump left
      world-readable, or a dump silently useless because nobody was told the key is
      needed to restore it.
HOW:  the script is read, not run — running it needs a booted stack, and that belongs to
      the e2e tier. What is provable by the tree is proven here, which is the rule this
      project's acceptance follows.

      Stated plainly: nothing here proves a dump restores. It proves the script cannot
      quietly do the dangerous version of each step.
"""

import pathlib
import re
import stat

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "backup.sh"
MAKEFILE = REPO / "Makefile"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


def test_the_script_exists_and_is_executable() -> None:
    """A backup script that has to be invoked via `bash` is one an operator mistypes."""
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_it_fails_the_whole_run_on_any_error(script: str) -> None:
    """``set -euo pipefail``.

    Without ``pipefail`` the dump is the case that bites: ``pg_dump | gzip`` reports
    gzip's exit status, so a failed dump writes a small, valid, EMPTY archive and the
    script says it succeeded.
    """
    assert re.search(r"^set -euo pipefail$", script, re.MULTILINE)


def test_the_dump_is_not_world_readable(script: str) -> None:
    """It holds every node's credentials and every friend's token, encrypted.

    Encrypted at rest is not a reason to leave the file readable by every account on
    the host — it is one layer, and the charter's threat model includes a host that is
    not exclusively ours.
    """
    assert "chmod 600" in script


def test_every_run_says_the_dump_needs_the_secret_key(script: str) -> None:
    """The one thing an operator can get catastrophically wrong.

    A dump without ``HASHI_SECRET_KEY`` restores nothing, and the moment that is
    discovered is the moment it cannot be fixed. So the warning is unconditional
    output, not documentation.
    """
    assert "HASHI_SECRET_KEY" in script
    assert "cannot be restored" in script


def test_a_restore_is_all_or_nothing(script: str) -> None:
    """``ON_ERROR_STOP`` and ``--single-transaction``.

    Without both, a failed restore leaves a half-populated database that looks
    restored: some friends back, some not, and no error anywhere.
    """
    assert "ON_ERROR_STOP=on" in script
    assert "--single-transaction" in script


def test_a_restore_asks_before_replacing_live_data(script: str) -> None:
    """Destructive and undoable, so it is confirmed — and skippable only deliberately."""
    assert "FORCE:-0" in script
    assert "read -r" in script


def test_the_script_never_reads_the_env_file_itself(script: str) -> None:
    """Hard rule: never read or print ``.env``.

    Connection details come from ``printenv`` inside the container via compose, so the
    real file is never opened, sourced or echoed by this script.
    """
    assert "printenv" in script
    # Over CODE only: the script's own header explains at length why it must not touch
    # .env, and that explanation names the file.
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in (r"cat\s+\.env", r"source\s+\.env", r"^\s*\.\s+\.env", r"grep.*\.env"):
        assert not re.search(forbidden, code, re.MULTILINE), forbidden


def test_compose_is_always_invoked_with_an_env_file(script: str) -> None:
    """Without ``--env-file`` every ``${VAR}`` silently becomes an empty string."""
    for line in script.splitlines():
        if "docker compose" in line and "--env-file" not in line:
            pytest.fail(f"compose without --env-file: {line.strip()}")


def test_make_restore_refuses_to_guess_which_dump(script: str) -> None:
    """"The newest one" is not a decision a Makefile should make during an incident."""
    makefile = MAKEFILE.read_text()
    assert "restore:" in makefile
    assert 'test -n "$(FROM)"' in makefile
    assert "backup:" in makefile
