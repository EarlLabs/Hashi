"""What a restore says it did, and that it is one account — M31.6, M31.7, M31.8, M31.9, M31.2.

WHAT: static checks over ``scripts/backup.sh`` and the ``Makefile`` for five things the
      restore walk of 2026-10-02 read on a real screen, plus the one guard that can be run
      here (the Makefile's bash check, under a PATH with no bash).
WHY:  each was a sentence that was false, or missing, on the one machine it is for:
      * a host without bash died on ``env: can't execute 'bash'`` (exit 127) before any
        of the script's own checks could speak (M31.7);
      * the confirmation named "compose project: <default: the directory name>" while the
        project was ``hashi`` (M31.9);
      * an artifact with nothing in it was "back, with the users, nodes and tokens that
        artifact held" — no counts, so a backup older than the fleet looked like a good one
        (M31.6);
      * mid-run "restart the control plane: make restart-control" and "the app will say so
        loudly", against a closing screen that said one command did the rest and a wrong
        key shows in the panel (M31.8);
      * a control plane rebuilt from the bucket would start dialling nodes with findings
        before its operator had looked (M31.2).
HOW:  read, not run, except the bash guard. The run itself is
      ``tests/e2e/infra/test_restore_proves_the_backup.py`` (S16), which reads the counts,
      the restart and the hold off a real rebuild's screen.
"""

import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKUP = REPO / "scripts" / "backup.sh"
MAKEFILE = REPO / "Makefile"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"


@pytest.fixture(scope="module")
def backup() -> str:
    return BACKUP.read_text()


def function(script: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n((?:.*\n)*?)^\}}$", script, re.M)
    assert match, f"{name} is no longer a function in scripts/backup.sh"
    return match.group(1)


def recipes(makefile: str) -> dict[str, list[str]]:
    """Target name → its recipe lines, for the plain `target:` rules this file uses."""
    found: dict[str, list[str]] = {}
    current = None
    for line in makefile.splitlines():
        header = re.match(r"^([a-z][a-z0-9-]*):(?!=)", line)
        if header:
            current = header.group(1)
            found[current] = []
        elif line.startswith("\t") and current:
            found[current].append(line)
        elif line.strip() and not line.startswith("#"):
            current = None
    return found


# --- M31.7 ------------------------------------------------------------------------------


def test_every_target_that_runs_a_bash_script_checks_for_bash_first() -> None:
    makefile = MAKEFILE.read_text()
    unguarded = []
    for target, lines in recipes(makefile).items():
        for at, line in enumerate(lines):
            if re.match(r"^\t@?scripts/[a-z-]+\.sh", line) and "\t$(need_bash)" not in lines[:at]:
                unguarded.append(target)
    assert unguarded == [], (
        f"these targets run a bash script with no bash check before it: {unguarded}"
    )


def test_the_bash_check_says_what_is_missing_on_a_host_without_bash(tmp_path) -> None:
    """Run the guard itself, in /bin/sh, with nothing on PATH. Red before M31.7: there was
    no guard, and the script's `#!/usr/bin/env bash` was the first thing to fail."""
    body = re.search(r"^define need_bash\n(.*?)^endef$", MAKEFILE.read_text(), re.M | re.S)
    assert body, "the Makefile no longer defines need_bash"
    command = body.group(1).lstrip("@").replace("\\\n", "\n")
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        env={"PATH": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "no bash" in result.stdout


def test_the_runbook_lists_bash_among_what_the_box_must_have() -> None:
    text = RUNBOOK.read_text()
    section = text[text.index("### What every box must already have"):]
    section = section[: section.index("\n### ", 10)]
    assert "`bash`" in section, "the prerequisite list still does not name bash"


# --- M31.9 ------------------------------------------------------------------------------


def test_the_confirmation_names_the_project_the_database_belongs_to(backup: str) -> None:
    assert "<default: the directory name>" not in backup
    assert "com.docker.compose.project" in function(backup, "compose_project")
    assert "compose project: $(compose_project)" in function(backup, "command_restore")


# --- M31.6 ------------------------------------------------------------------------------


def test_a_restore_counts_what_the_artifact_held(backup: str) -> None:
    restore = function(backup, "command_restore")
    assert restore.index('echo "restored."') < restore.index("held_counts"), (
        "the count is not taken after the restore"
    )
    assert "NO nodes and NO users" in restore
    assert "users, nodes and tokens that artifact held" not in backup
    closing = function(backup, "command_restore_from_bucket")
    assert "${RESTORED_NODES} node(s)" in closing


# --- M31.8 and M31.2 --------------------------------------------------------------------


def test_the_restore_restarts_the_control_plane_itself_and_says_one_thing(backup: str) -> None:
    restore = function(backup, "command_restore")
    assert "restart_control" in restore
    assert "loudly on first use" not in backup
    assert "Restart the control plane so it reconnects" not in backup
    # One sentence about the wrong key, printed by both paths.
    assert backup.count('"${WRONG_KEY_SENTENCE}"') == 1
    assert "${WRONG_KEY_SENTENCE}" in function(backup, "command_restore_from_bucket")


def test_a_rebuild_from_the_bucket_holds_the_remeasure_loop(backup: str) -> None:
    restart = function(backup, "restart_control")
    assert "HASHI_FINDING_REMEASURE_INTERVAL=0" in restart
    assert "up -d --no-deps --no-build control" in restart
    assert "restart control" in restart, "the ordinary restore no longer just restarts"
    assert re.search(
        r"HOLD_REMEASURE=1 (?:[A-Z_]+=\S+ )*command_restore ",
        function(backup, "command_restore_from_bucket"),
    )


# --- M31.10, found in the real-host re-walk of 2026-10-02 --------------------------------


def test_the_bucket_path_says_the_wrong_key_sentence_once(backup: str) -> None:
    """The re-walk read "One thing no restore can check…" twice, word for word.

    ``command_restore`` printed it after the restart, and the bucket path's closing screen
    — which ``command_restore`` runs inside — printed it again as its last paragraph. M31.8
    asks for one account, said once. The file restore has no closing screen, so it keeps
    saying it; the bucket path tells ``command_restore`` a closing screen follows, and the
    sentence is said there and only there.
    """
    restore = function(backup, "command_restore")
    printed = restore.index('"${WRONG_KEY_SENTENCE}"')
    guard = restore.rfind('if [ "${CLOSING_SCREEN_FOLLOWS:-0}" != "1" ]; then', 0, printed)
    assert guard != -1 and "fi" not in restore[guard:printed].split(), (
        "command_restore prints the wrong-key sentence even when the bucket's closing "
        "screen is about to print it again"
    )
    bucket = function(backup, "command_restore_from_bucket")
    assert "CLOSING_SCREEN_FOLLOWS=1 command_restore" in bucket
    assert "${WRONG_KEY_SENTENCE}" in bucket, "and then neither path would say it"
