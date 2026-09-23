"""Nothing M28 added records who connected to what — M28.7.

WHAT: the audit of every surface this milestone put on a host that writes, prints or
      stores something: ``scripts/backup.sh``, ``scripts/backup-run.sh``,
      ``scripts/backup-schedule.sh`` and the cron entry it installs, and
      ``deploy/backup/upload.py``. What each of them emits, on success and on the failure
      paths, and where that output ends up.
WHY:  the charter's one absolute prohibition — no connection, traffic or DNS logs, at any
      level, including debug and including temporarily while debugging — applies to a
      backup job and a restore unchanged, and both are new. A backup dump is a copy of the
      whole database, so anything that prints a path, an artifact name, a row count or a
      store's error message is somewhere a fact about a person could surface.

      And the destination matters as much as the text. A ``tick`` runs unattended every
      fifteen minutes for the life of the host, and **cron mails whatever a job writes** —
      to a spool file, or to syslog, depending on the host. That is a persistent log
      nobody in this repository can see, so the check is not "is this line harmless to
      read" but "is this line written at all".
HOW:  three kinds of check, and the third is the one with teeth.

      * What cannot be exercised is read as text: no surface may APPEND to anything, which
        is the shape a log has, and none may reach for syslog or a shell trace.
      * The verbs that only read are run, and the tree they ran in is compared before and
        after, so a new sidecar file fails here rather than being discovered on a host.
      * A tick with nothing owed is run and its two streams must be EMPTY. Ninety-five of
        every ninety-six ticks a day are that one, so a single ``echo`` on that path is
        thirty-five thousand pieces of mail a year, each of them a place a path lands.

      What is NOT here: anything needing a docker engine. The behavioural half of the
      env-file finding below lives in ``tests/e2e/infra/test_restore_proves_the_backup.py``
      because reproducing it means running compose.
"""

import json
import pathlib
import re
import subprocess
import sys

import pytest

from tests.infra.test_backup_schedule import env_file, run, seed, verdict

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKUP = REPO / "scripts" / "backup.sh"
RUNNER = REPO / "scripts" / "backup-run.sh"
INSTALLER = REPO / "scripts" / "backup-schedule.sh"
UPLOADER = REPO / "deploy" / "backup" / "upload.py"
# The gate below moved into a library in M28.8, when `scripts/panel-bootstrap.sh` turned
# out to have the same leak and the choice was one implementation or two scrubbers that
# drift. Sourced by both callers; executed by neither.
GATE = REPO / "scripts" / "lib" / "env-file-gate.sh"
BOOTSTRAP = REPO / "scripts" / "panel-bootstrap.sh"

SURFACES = (BACKUP, RUNNER, INSTALLER, UPLOADER, GATE)


@pytest.fixture(scope="module")
def uploader() -> str:
    return UPLOADER.read_text()


def _code(script: pathlib.Path) -> str:
    """A shell script with its comments and its heredoc bodies taken out.

    Both are full of prose about logs, appends and mail, and a text check that reads them
    measures the explanation rather than the program. Heredocs go because every operator
    message in these scripts is one, and they legitimately contain ``>>`` and the word
    ``log``.
    """
    text = script.read_text()
    text = re.sub(r"<<'?(\w+)'?\n.*?^\1$", "", text, flags=re.S | re.M)
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


# --- nothing here keeps a log of its own ---------------------------------------------


def test_no_backup_surface_appends_to_anything() -> None:
    """A log is a file something appends to, and none of these appends to anything.

    Stated as the shape rather than as a list of forbidden filenames, because the next
    person to add one will not call it ``backup.log``. Every file these surfaces write —
    the artifact, the record, the lock, the two ``.partial`` files — is created whole and
    replaced whole, so an append is by construction something new.
    """
    for script in (BACKUP, RUNNER, INSTALLER):
        # Double-quoted literals go as well, and only for this one check: the crontab
        # block's own idempotency markers are `# >>> hashi backup schedule >>>` held in a
        # shell variable, which is a string this script PRINTS and not a redirection.
        # They stay in place for the destination check below, where a quoted `/var/log/…`
        # would be exactly the thing worth catching.
        program = re.sub(r'"[^"\n]*"', '""', _code(script))
        assert ">>" not in program, (
            f"{script.name} appends to a file. Nothing in the backup path keeps a running "
            "record of its own runs beyond backups/state/last-run.json, which is rewritten "
            "whole every time (CLAUDE.md — never log who connected to what)."
        )


def test_no_backup_surface_reaches_for_a_log_the_host_keeps() -> None:
    """syslog, a shell trace and `tee` are the three ways this grows a second destination.

    ``set -x`` is on the list because it is the one that arrives by accident: somebody
    debugging a tick leaves it in, and every expansion of every variable — the artifact's
    path, the object name, the store's address — goes to cron's mail for ever. That is the
    "including temporarily, while debugging" half of the charter's rule, and it is exactly
    the half a reviewer cannot see in a diff that is otherwise about something else.
    """
    forbidden = re.compile(r"\blogger\b|\bsyslog\b|/var/log|\btee\b|set -x|bash -x|sh -x")
    for script in SURFACES:
        found = forbidden.findall(_code(script) if script.suffix == ".sh" else script.read_text())
        assert found == [], f"{script.name} writes to a log the host keeps: {found}"


def test_the_uploader_writes_no_file_but_the_one_it_unlinks() -> None:
    """One temporary file, created unlinked, in a container that is deleted after one PUT.

    The artifact is staged because the signature covers the payload hash and the request
    needs a length, and both are known only after the last byte. That is the only thing
    this program is allowed to put on a disk; an ``open(..., "w")`` appearing here would be
    a copy of the database's ciphertext left somewhere nobody is looking after it.
    """
    source = UPLOADER.read_text()
    assert source.count("tempfile.TemporaryFile()") == 1
    assert not re.search(r"open\([^)]*['\"][wa]", source), "the uploader writes a file"
    assert ".write_text(" not in source and ".write_bytes(" not in source


# --- what a run actually emits ---------------------------------------------------------


def test_a_tick_with_nothing_owed_says_nothing_at_all(tmp_path) -> None:
    """Ninety-five ticks out of ninety-six, and every one of them must be silent.

    cron mails what a job writes, so this is not tidiness: a line printed here is a line
    written to a spool or to syslog ninety-six times a day, on a host whose operator is
    not reading it. A working schedule is therefore quiet, and the record — which is
    rewritten whole and holds no person — is the channel that does not depend on anybody
    opening mail.

    The empty streams are asserted rather than the exit code because the exit code was
    already right on the day a stray ``echo`` would be added.
    """
    state = tmp_path / "state"
    path = env_file(tmp_path, HASHI_BACKUP_AT="04:00", HASHI_BACKUP_TZ="Etc/UTC")
    # The day the script itself thinks is owed, asked of the script rather than computed
    # here: a test that works out the date for itself is a second implementation of the
    # thing under test, and it goes wrong across midnight.
    state.mkdir()
    today = verdict(run("due", path, state))["due"]
    seed(state, due_date=today,
         last_attempt={"at": f"{today}T04:00:00Z", "due_date": today,
                       "exit_code": 0, "outcome": "on-this-host-only"})

    quiet = run("tick", path, state)

    assert quiet.returncode == 0
    assert quiet.stdout == "", f"a tick with nothing owed printed to stdout: {quiet.stdout!r}"
    assert quiet.stderr == "", f"a tick with nothing owed printed to stderr: {quiet.stderr!r}"


def test_the_verbs_that_only_read_leave_the_disk_exactly_as_they_found_it(tmp_path) -> None:
    """``due`` and ``status`` answer questions; neither may write down having been asked.

    The whole directory is compared, not just the record, because the failure this guards
    against is a NEW file — a cache, a last-asked marker, a debug dump — rather than a
    change to the one file whose keys are already fenced. ``due`` is the verb M28.5 built
    as a seam and the one a later step will reach for first.
    """
    state = tmp_path / "state"
    path = env_file(tmp_path, HASHI_BACKUP_AT="04:00", HASHI_BACKUP_TZ="Etc/UTC")
    seed(state)

    def tree() -> dict[str, bytes]:
        return {
            str(item.relative_to(tmp_path)): item.read_bytes()
            for item in sorted(tmp_path.rglob("*")) if item.is_file()
        }

    before = tree()
    run("due", path, state)
    run("status", path, state)
    assert tree() == before, "a read-only verb changed something on the disk"


def test_the_status_it_prints_is_the_schedule_and_not_the_record_tipped_out(tmp_path) -> None:
    """``make backup-status`` puts the record on a screen, so it inherits the record's fence.

    It reads the file and prints SENTENCES from named fields — not the file. That
    distinction is the whole of it: a ``cat`` of the record would be harmless today,
    because the writer's key set is closed and holds nothing about a person, and would stop
    being harmless the moment anything ever adds a sixteenth key. Printing named fields
    means a new key is invisible here until somebody decides to show it.

    The zone is asserted because it is the one value that came out of the operator's env
    file, and it is printed as the IANA NAME it is — never turned into a country or an
    offset, here or on the panel (M28.6).
    """
    state = tmp_path / "state"
    path = env_file(tmp_path, HASHI_BACKUP_AT="04:00", HASHI_BACKUP_TZ="Etc/UTC")
    seed(state, zone="Etc/UTC", offsite="yes")

    said = run("status", path, state)

    assert said.returncode == 0, said.stderr
    assert "Etc/UTC" in said.stdout
    assert (
        "What this does NOT say: whether any of those artifacts is still in the bucket."
        in said.stdout
    )
    for key in json.loads((state / "last-run.json").read_text()):
        assert f'"{key}"' not in said.stdout, (
            f"status is printing the record's raw JSON ({key}), not sentences from it"
        )


# --- the credential, and the store's own words -----------------------------------------


PLANTED_SECRET = "PLANTED-S3-SECRET-THAT-MUST-NEVER-BE-PRINTED"
PLANTED_KEY_ID = "PLANTEDACCESSKEYID"


def _preflight(**environment: str) -> subprocess.CompletedProcess:
    """The uploader, on a path that makes no network call, with a planted credential."""
    return subprocess.run(
        [sys.executable, str(UPLOADER), "preflight"],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        # A stripped environment, the way the one-off container gets one: only what
        # compose put there. PATH is not needed — the interpreter is named in full.
        env=dict(environment),
    )


CONFIGURED = {
    "HASHI_BACKUP_ENABLED": "1",
    "HASHI_BACKUP_S3_ENDPOINT": "https://store.example",
    "HASHI_BACKUP_S3_REGION": "somewhere",
    "HASHI_BACKUP_S3_BUCKET": "a-bucket",
    "HASHI_BACKUP_S3_ACCESS_KEY_ID": PLANTED_KEY_ID,
    "HASHI_BACKUP_S3_SECRET_ACCESS_KEY": PLANTED_SECRET,
}


@pytest.mark.parametrize(
    "environment, why",
    [
        ({"HASHI_BACKUP_ENABLED": "0"}, "switched off"),
        ({"HASHI_BACKUP_ENABLED": "1"}, "switched on and nothing configured"),
        ({**CONFIGURED, "HASHI_BACKUP_S3_ENDPOINT": "not-a-url"}, "an endpoint that is not one"),
        ({**CONFIGURED, "HASHI_BACKUP_S3_BUCKET": ""}, "half configured"),
        (CONFIGURED, "configured, and it resolves"),
    ],
)
def test_the_uploader_keeps_stdout_empty_and_the_credential_to_itself(
    environment: dict, why: str
) -> None:
    """Run, not read: every refusal the operator can reach, and the one success.

    Two properties at once, and they fail for different reasons. **stdout stays empty**
    because in a dump this program's stdout is a stage of the pipeline that writes the
    artifact, and one polluting byte corrupts it (M28.2) — so "all output is on stderr" is
    a correctness rule and not a style. **The secret never appears** because the whole
    point of a write-only key is that the box holding it is the box that gets seized, and
    the place that key would surface is the mail a failed nightly run sends.

    The key ID is checked as well as the secret: it is not a secret, but it names the
    account the fleet's backups live under, and there is no reason for it to be in a
    message an operator forwards to somebody.
    """
    answered = _preflight(**environment)

    assert answered.stdout == "", f"{why}: the uploader wrote to stdout: {answered.stdout!r}"
    assert PLANTED_SECRET not in answered.stderr, f"{why}: the secret was printed"
    assert PLANTED_KEY_ID not in answered.stderr, f"{why}: the key id was printed"


def test_the_stores_own_error_is_reduced_to_what_helps(uploader: str) -> None:
    """A store's XML error is somebody else's text arriving in ours, and it is trimmed.

    ``<Code>`` and ``<Message>`` are what tell an operator which of their two credentials
    is wrong; ``RequestId`` and ``HostId`` are the store's own naming and would put it into
    whatever reads this output afterwards — a terminal, or cron's mail. Capped as well, so
    a store that answers with a megabyte cannot make a backup run mail one.
    """
    body = re.search(r"def refusal_from\(.*?\n(?=\n\ndef |\n\nclass )", uploader, re.S)
    assert body, "refusal_from is gone; what a store says is no longer reduced anywhere"
    assert 'for tag in ("Code", "Message")' in body.group(0)
    assert "RequestId" not in body.group(0) and "HostId" not in body.group(0)
    assert "[:200]" in body.group(0), "a store's message is no longer capped"


# --- the env file is compose's to read, and its lines are nobody's to print -------------


def test_a_line_of_the_env_file_never_reaches_the_output_of_a_run() -> None:
    """The finding this step actually made, pinned from the static side.

    ``docker compose`` is the one thing allowed to open the env file, and when it cannot
    PARSE that file it quotes the offending line's whole value back — ``unterminated quoted
    value "…"``, ``Invalid template: "…"``, ``unexpected character … in variable name
    "…"``. A single unclosed quote on the ``HASHI_SECRET_KEY`` line therefore put the
    secret key into what a scheduled run printed, and a scheduled run's output is what cron
    mails, on every retry, for ever.

    It is gated ONCE, in the script's dispatch, because every compose call in that file
    produces the same message. The assertion below is on the DISPATCH rather than on a
    count of call sites, and that is the point: a gate in front of the three verb functions
    covers every compose call any of them can reach, however many there come to be, while a
    count is true until somebody adds one more. The gate CAPTURES compose's complaint and
    never prints it: what is repeated is the file and compose's own line number, taken out
    of a digits-only capture so nothing of the operator's file can ride along inside what
    looks like a number.

    Behaviourally reproduced in ``tests/e2e/infra/test_restore_proves_the_backup.py``,
    which has the docker engine it takes to run compose at all.
    """
    script = BACKUP.read_text()
    gate = GATE.read_text()
    assert "env_file_must_be_readable()" in gate, "the gate is gone"
    # ONE implementation. M28.8 gave it a second caller rather than a second copy, because
    # two scrubbers are two things that drift and the next printer added to either script
    # would be behind whichever one its author remembered.
    assert len(re.findall(r"^env_file_must_be_readable\(\) \{", gate, re.M)) == 1
    for caller in (BACKUP, BOOTSTRAP):
        assert not re.search(
            r"^env_file_must_be_readable\(\) \{", caller.read_text(), re.M
        ), f"{caller.name} defines the gate again instead of sourcing it"

    body = re.search(
        r"env_file_must_be_readable\(\) \{\n(.*?)\n\}\n", gate, re.S
    ).group(1)
    assert 'complaint="$(' in body, "compose's complaint is no longer captured"
    assert not re.search(r'(echo|printf|cat)[^\n]*\$\{complaint\}', body), (
        "the gate prints compose's own complaint, which is the line of the env file it "
        "could not read"
    )
    assert "BASH_REMATCH[1]" in body and "[0-9]+" in body, (
        "the line number is no longer taken out of a digits-only capture"
    )
    # It asks with the CALLER's own compose invocation, which is the one carrying
    # --env-file. A command assembled inside the library would be a second place for the
    # `docker compose` rule to be got wrong, unwatched by either script's own tests.
    assert '"${COMPOSE[@]}" config --quiet' in body
    assert "docker compose" not in body

    # ...and every verb that can reach a compose call goes through it first.
    dispatch = script.split("case \"${1:-}\" in")[-1]
    for verb in ("dump", "upload", "restore"):
        assert re.search(rf"{verb}\)\s*shift; env_file_must_be_readable;", dispatch), (
            f"`{verb}` can reach compose without the env file having been gated"
        )


def test_the_schedule_passes_the_env_file_on_and_reads_nothing_more_of_it() -> None:
    """The scheduler is the one script that opens the env file, and the fence is unchanged.

    Restated here rather than left to M28.5's own test because this step's question is
    "what does each surface emit", and the answer for this one depends entirely on the
    whitelist holding: three settings, all of them in ``.env.example`` in the clear. A
    fourth name is how a secret gets into a file that is rewritten every day for years.
    """
    runner = RUNNER.read_text()
    whitelist = re.search(r'SCHEDULE_KEYS="([^"]*)"', runner)
    assert whitelist, "the whitelist is gone"
    assert whitelist.group(1).split() == [
        "HASHI_BACKUP_AT", "HASHI_BACKUP_TZ", "HASHI_BACKUP_ENABLED"
    ]
    # And the one script that takes the database apart still opens nothing at all.
    assert not re.search(r'(source|\.)\s+"\$\{ENV_FILE\}"', BACKUP.read_text())
