"""What the command line is entitled to say about one record — M28.15.

WHAT: the fifth and sixth surfaces of one defect, and the guards that keep them shut.
      ``make backup-status`` may not say a schedule exists without asking the thing that
      knows; ``scripts/backup-run.sh due`` may not read facts out of a record it could not
      parse; both must say out loud that a record dated ahead of this host's clock has
      stopped the backups; the exit-3 advice may not outlive the failure it is about; the
      missed-days label may not be printed with nothing after it; a record that was merely
      re-indented is a good record; and ``HASHI_BACKUP_ENABLED`` is answered from the env
      file for the uploader exactly as it already is for the recorder.
WHY:  every fix in this milestone has been correct and none has generalised, because
      several independent readers each decide for themselves what this one file entitles
      them to say. Round 1 found two of them asserting things the record does not license;
      round 2 found two more, on the channel the panel sends the operator to. These tests
      are written per READER rather than per symptom for that reason — the question asked
      of each one is the same question.
HOW:  the verbs are RUN, against records written the way the writer writes them, with no
      Docker anywhere: ``status`` and ``due`` read a file and an env file and start
      nothing.

      The crontab is a FAKE one on ``PATH`` — twelve lines of shell holding a file — so the
      three answers (installed, not installed, no crontab at all) are all reachable on any
      machine, and so that the sequence acceptance actually walked can be walked here:
      install, status, unschedule, status. Nothing touches the account's real crontab, and
      a test that used it would depend on whoever is running it.
"""

import datetime
import json
import os
import pathlib
import re
import subprocess

import pytest

from tests.infra.test_backup_schedule import PLANTED, env_file, seed, today_in

# The ceiling, read out of the script rather than typed out here — and the module it comes
# from is the one that pins it against the panel's own constant (M28.17). Both fixtures
# below are positioned relative to it, one under and one over, so a copy of the number kept
# here would stop testing the boundary the day the boundary moved.
from tests.infra.test_the_command_line_says_what_the_panel_says import MOST_OF_A_RECORD

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts" / "backup-run.sh"
INSTALLER = REPO / "scripts" / "backup-schedule.sh"
BACKUP = REPO / "scripts" / "backup.sh"
RECORD_LIB = REPO / "scripts" / "lib" / "backup-record.sh"
# Every shell surface, the same list the other audits keep — the guards below sweep all
# of them rather than the one script that holds the readers today.
SHELL_SURFACES = sorted((REPO / "scripts").glob("*.sh")) + sorted(
    (REPO / "scripts" / "lib").glob("*.sh")
)

# A crontab of this account's own, in a file, under a `crontab` command that behaves like
# the real one in the two ways anything here depends on: `-l` exits non-zero when there is
# nothing, and `-` replaces the whole thing from stdin.
FAKE_CRONTAB = """#!/usr/bin/env bash
set -eu
TABLE="${FAKE_CRONTAB_FILE}"
case "${1:-}" in
  -l) [ -s "${TABLE}" ] || { echo "no crontab for nobody" >&2; exit 1; }
      cat "${TABLE}" ;;
  -)  cat > "${TABLE}" ;;
  -r) rm -f "${TABLE}" ;;
  *)  echo "fake crontab: ${*}" >&2; exit 2 ;;
esac
"""


def a_host(tmp_path: pathlib.Path, *, crontab: bool) -> dict[str, str]:
    """The environment one of these commands gets, with or without a `crontab` on PATH.

    ``PATH`` is built rather than inherited: the point of the no-crontab case is that the
    real one must not be found, and on a developer's machine it is on the path.
    """
    binaries = tmp_path / "bin"
    binaries.mkdir(exist_ok=True)
    table = tmp_path / "crontab.txt"
    if crontab:
        command = binaries / "crontab"
        command.write_text(FAKE_CRONTAB)
        command.chmod(0o755)
    inherited = os.environ.get("PATH", "/usr/bin:/bin")
    return {
        "PATH": (
            f"{binaries}:{inherited}" if crontab
            else _path_without_crontab(inherited, tmp_path / "nocron")
        ),
        "FAKE_CRONTAB_FILE": str(table),
    }


def _path_without_crontab(inherited: str, shadow: pathlib.Path) -> str:
    """The real ``PATH`` with every ``crontab`` on it taken away and nothing else.

    A host with no cron still has ``bash``, ``sed``, ``awk`` and ``date``, and they live in
    the same directory as ``crontab`` — so dropping that directory would test a host with
    no shell rather than a host with no cron. Each directory that holds one is replaced by
    a shadow of itself: the same names, symlinked, minus the one.
    """
    parts = []
    for part in inherited.split(":"):
        directory = pathlib.Path(part) if part else None
        if directory is None or not (directory / "crontab").exists():
            parts.append(part)
            continue
        shadow.mkdir(parents=True, exist_ok=True)
        for entry in directory.iterdir():
            if entry.name == "crontab":
                continue
            link = shadow / entry.name
            if not link.is_symlink():
                link.symlink_to(entry)
        parts.append(str(shadow))
    return ":".join(parts)


def run(
    verb: str, env: pathlib.Path, state: pathlib.Path, host: dict[str, str] | None = None,
    *, script: pathlib.Path = RUNNER,
) -> subprocess.CompletedProcess:
    """One invocation, with the environment cron gives it — and nothing leaked.

    The same planted-secret assertion as ``test_backup_schedule.run``: this file adds a
    command that SHELLS OUT to another script, and every new place output is produced is a
    new place the env file can reach a cron mail from.
    """
    environment = {"ENV_FILE": str(env), "HASHI_BACKUP_STATE_DIR": str(state)}
    environment.update(host or {"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    environment.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    result = subprocess.run(
        [str(script), verb],
        capture_output=True, text=True, timeout=60, cwd=REPO,
        stdin=subprocess.DEVNULL, env=environment,
    )
    said = result.stdout + result.stderr
    for secret in PLANTED:
        assert secret not in said, f"`{verb}` printed a value out of the env file"
    return result


def a_record(tmp_path: pathlib.Path, **fields) -> pathlib.Path:
    state = tmp_path / "state"
    seed(state, **fields)
    return state


def an_env(tmp_path: pathlib.Path, **values) -> pathlib.Path:
    values.setdefault("HASHI_BACKUP_TZ", "Etc/UTC")
    return env_file(tmp_path, **values)


A_GOOD_RUN = {
    "at": "2026-01-01T04:00:00Z", "due_date": "2026-01-01",
    "exit_code": 0, "outcome": "on-this-host-only",
}


# --- 1. the three commands in this family agree about one host ----------------


def test_the_status_line_is_asked_of_the_crontab_and_not_assumed(tmp_path) -> None:
    """The sequence acceptance walked, in one test, because that is where the lie was.

    The entry was installed and the output diffed byte-identical against a host with no
    entry at all; then ``make backup-unschedule`` answered *"removed. Nothing runs a backup
    on this host now."* and the next ``backup-status`` printed the schedule line again.
    Three commands in one family and one of them contradicting another about the same host
    in the same minute.
    """
    host = a_host(tmp_path, crontab=True)
    env, state = an_env(tmp_path), a_record(tmp_path)

    bare = run("status", env, state, host)
    assert bare.returncode == 0, bare.stderr
    assert "scheduled:    NO" in bare.stdout, bare.stdout

    installed = run("install", env, state, host, script=INSTALLER)
    assert installed.returncode == 0, installed.stderr
    scheduled = run("status", env, state, host)
    assert scheduled.returncode == 0, scheduled.stderr
    assert "scheduled:    yes" in scheduled.stdout, scheduled.stdout
    assert scheduled.stdout != bare.stdout, (
        "a host with the cron entry and a host without it printed byte-identical output, "
        "which is the finding: this command is not asking whether anything runs"
    )

    removed = run("remove", env, state, host, script=INSTALLER)
    assert "Nothing runs a backup on this host now" in removed.stderr
    after = run("status", env, state, host)
    assert "scheduled:    NO" in after.stdout, (
        "`make backup-unschedule` said nothing runs a backup and `make backup-status` "
        f"said this in the same minute:\n{after.stdout}"
    )
    assert after.stdout == bare.stdout, "removing the entry did not put the host back"


def test_a_host_with_no_crontab_is_told_that_this_cannot_be_known(tmp_path) -> None:
    """The third answer, and it is not "no".

    ``docs/deploy/runbook.md`` documents a systemd timer for exactly this host, running the
    same script on the same tick. Collapsing "there is nothing here to ask" into "nothing
    is backing you up" would tell an operator whose backups are working that they are not,
    which is the same class of wrong answer in the other direction.
    """
    host = a_host(tmp_path, crontab=False)
    answered = run("status", an_env(tmp_path), a_record(tmp_path), host)

    assert answered.returncode == 0, answered.stderr
    assert "scheduled:    NOT KNOWN" in answered.stdout, answered.stdout
    assert "systemctl list-timers" in answered.stdout, (
        "the one host that cannot be asked is not told where its answer is"
    )


def test_the_installer_answers_the_question_with_its_exit_code(tmp_path) -> None:
    """0 installed, 1 no entry, 3 nothing here to ask — the contract `status` reads.

    Pinned because it is now an interface between two scripts rather than a message to a
    person: collapsing 1 and 3 back into one code would silently turn the answer above
    into "nothing is backing you up" on every host without cron.
    """
    host = a_host(tmp_path, crontab=True)
    env, state = an_env(tmp_path), a_record(tmp_path)

    assert run("show", env, state, host, script=INSTALLER).returncode == 1
    run("install", env, state, host, script=INSTALLER)
    assert run("show", env, state, host, script=INSTALLER).returncode == 0
    run("remove", env, state, host, script=INSTALLER)
    assert run("show", env, state, host, script=INSTALLER).returncode == 1

    nowhere = a_host(tmp_path, crontab=False)
    assert run("show", env, state, nowhere, script=INSTALLER).returncode == 3


def test_the_appointed_time_is_still_the_env_files_and_says_so(tmp_path) -> None:
    """The half of the old line that was always honest keeps its source named.

    ``scheduled:`` is now about the crontab and ``appointed:`` about the env file. They are
    two sentences because they have two sources, and the failure they replace was one
    sentence that read as though it had both.
    """
    answered = run(
        "status", an_env(tmp_path, HASHI_BACKUP_AT="05:30"), a_record(tmp_path),
        a_host(tmp_path, crontab=True),
    )
    appointed = [line for line in answered.stdout.splitlines() if "appointed:" in line]
    assert appointed and "05:30 Etc/UTC (configured)" in appointed[0], answered.stdout
    assert "checked every 15 minutes" not in answered.stdout, (
        "the sentence that promised a schedule this command had not looked for is back"
    )


# --- 2. `due` reads nothing out of a record it could not parse ----------------


DAMAGE = {
    "schema": {"schema": 99},
    "offsite": {"offsite": 3},
    "last_success": {"last_success": {"at": "yesterday", "exit_code": 0, "outcome": "ok"}},
    "missed_total": {"missed_total": "lots"},
    "missed_dates": {"missed_dates": ["yesterday"]},
}


@pytest.mark.parametrize("field", sorted(DAMAGE))
def test_due_refuses_a_damaged_record_instead_of_answering_from_it(tmp_path, field) -> None:
    """The surface round 1's fix missed, and it was the loudest one left.

    On a damaged record this verb said *"no backup has ever been recorded on this host"*,
    ``offsite=no``, ``missed=none``, exit **0** — every one of those a fact read out of a
    file it could not parse, and all of them together byte-for-byte what a genuinely fresh
    host prints.
    """
    answered = run("due", an_env(tmp_path), a_record(tmp_path, **DAMAGE[field]))

    assert answered.returncode != 0, (
        f"a record with a bad {field} answered at exit 0:\n{answered.stdout}"
    )
    assert "NOTHING HAS BEEN ASSUMED FROM IT" in answered.stderr
    assert field in answered.stderr, "the refusal does not name the key it could not read"
    assert "action=" not in answered.stdout and answered.stdout == "", (
        f"the verdict was printed anyway, from a record it refused:\n{answered.stdout}"
    )
    assert "no backup has ever been recorded" not in answered.stdout + answered.stderr, (
        "a damaged record and a host that has never run one are the same sentence again"
    )


def test_a_host_with_no_record_still_gets_an_answer(tmp_path) -> None:
    """The other side of it: absence is not damage, and a fresh host is entitled to run.

    Refusing here would stop the first backup of every new install, which is the state
    ``make backup-schedule`` is designed to leave a host in.
    """
    answered = run("due", an_env(tmp_path), tmp_path / "nowhere")
    assert answered.returncode == 0, answered.stderr
    assert "action=run" in answered.stdout


# --- 3. a clock that ran ahead has stopped the backups -------------------------


AHEAD = "2099-03-01T04:00:00Z"


def test_due_says_a_record_dated_ahead_has_stopped_the_backups(tmp_path) -> None:
    """``action=wait`` for ever, at exit 0, is a backup system that silently stopped.

    A host whose clock jumped forward wrote a record for a day that has not arrived; the
    clock is then put right and every tick from that moment answers "the record is ahead of
    this clock" and takes nothing. Nothing is wrong with the record, so it is read — and
    what is said about it is that no backup is being taken at all.
    """
    state = a_record(
        tmp_path, due_date="2099-03-01",
        last_attempt={**A_GOOD_RUN, "at": AHEAD}, last_success={**A_GOOD_RUN, "at": AHEAD},
    )
    answered = run("due", an_env(tmp_path), state)

    assert answered.returncode != 0, (
        f"the one state that cannot clear by waiting exits 0:\n{answered.stdout}"
    )
    assert "clock=ahead" in answered.stdout, answered.stdout
    assert "action=wait" in answered.stdout, "the verdict itself is still readable"
    assert "DATED AHEAD OF THIS HOST'S CLOCK" in answered.stderr
    assert "NOTHING IS BACKED UP AT ALL" in answered.stderr


def test_status_says_it_too_beside_the_ages_it_makes_worthless(tmp_path) -> None:
    """The panel warns, and this printed *"last success: <a date next year> (ok)"*.

    The age is the whole content of this screen, and a record from the future makes every
    one of them meaningless in the reassuring direction.
    """
    state = a_record(
        tmp_path, due_date="2099-03-01",
        last_attempt={**A_GOOD_RUN, "at": AHEAD}, last_success={**A_GOOD_RUN, "at": AHEAD},
    )
    answered = run("status", an_env(tmp_path), state, a_host(tmp_path, crontab=True))

    assert answered.returncode == 0, answered.stderr
    assert AHEAD in answered.stdout, "the record is readable and is still read"
    assert "DATED AHEAD OF THIS HOST'S CLOCK" in answered.stdout, answered.stdout


def test_an_ordinary_record_says_none_of_that(tmp_path) -> None:
    """The negative, because a warning printed on every host is a warning nobody reads."""
    answered = run("due", an_env(tmp_path), a_record(tmp_path, due_date=today_in("Etc/UTC")))

    assert answered.returncode == 0, answered.stderr
    assert "clock=ok" in answered.stdout
    assert "DATED AHEAD" not in answered.stdout + answered.stderr


# --- 4. a record that was only re-indented is a good record --------------------


def rewritten(state: pathlib.Path, transform) -> None:
    """The record on disk, put through a text transform and written back as bytes."""
    record = state / "last-run.json"
    record.write_bytes(transform(record.read_text()).encode())


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param(lambda text: json.dumps(json.loads(text), indent=4), id="re-indented"),
        pytest.param(lambda text: json.dumps(json.loads(text)), id="all-on-one-line"),
        pytest.param(
            lambda text: json.dumps(json.loads(text), indent=2, separators=(",", ":")),
            id="no-space-after-the-colon",
        ),
        pytest.param(
            lambda text: json.dumps(json.loads(text), indent=1).replace("\n", "\r\n"),
            id="edited-on-windows",
        ),
    ],
)
def test_a_record_someone_pretty_printed_is_still_the_record(tmp_path, layout) -> None:
    """``jq .`` is what an operator types to look at this file, and it rewrote the layout.

    The control plane reads the same bytes with ``json.loads`` and never noticed; this
    reader required each nested entry on one line and called the file damaged. One record,
    two channels, two answers — which is the defect this milestone keeps meeting, arriving
    through the parser this time.
    """
    state = a_record(
        tmp_path, due_date=today_in("Etc/UTC"),
        last_attempt=A_GOOD_RUN, last_success=A_GOOD_RUN,
    )
    canonical = run("status", an_env(tmp_path), state, a_host(tmp_path, crontab=True))
    rewritten(state, layout)
    answered = run("status", an_env(tmp_path), state, a_host(tmp_path, crontab=True))

    assert answered.returncode == 0, answered.stdout + answered.stderr
    assert answered.stdout == canonical.stdout, (
        "the same record in another layout reads as a different host"
    )


@pytest.mark.parametrize(
    "damage,key",
    [
        pytest.param(
            lambda text: text.split('"last_success"', 1)[0], "last_success", id="truncated",
        ),
        pytest.param(
            lambda text: json.dumps({**json.loads(text), "schema": 99}, indent=4),
            "schema", id="re-indented-and-a-schema-from-the-future",
        ),
        pytest.param(
            lambda text: json.dumps(
                {**json.loads(text), "last_success": {"at": "yesterday", "exit_code": 0,
                                                      "outcome": "ok"}},
                indent=4,
            ),
            "last_success", id="re-indented-and-not-a-run",
        ),
        pytest.param(
            lambda text: json.dumps(
                {**json.loads(text), "missed_dates": ["yesterday"]}, indent=4,
            ),
            "missed_dates", id="re-indented-and-a-date-that-is-not-one",
        ),
    ],
)
def test_tolerating_the_layout_tolerated_nothing_else(tmp_path, damage, key) -> None:
    """The line this step was told not to cross, held from the other side.

    A reader made forgiving about whitespace is one edit away from being forgiving about
    values, and that would undo what round 1 was about. Each of these is a damaged record
    IN A NEW LAYOUT: the layout is accepted, the damage is still refused, by name.
    """
    state = a_record(tmp_path, last_attempt=A_GOOD_RUN, last_success=A_GOOD_RUN)
    rewritten(state, damage)
    answered = run("status", an_env(tmp_path), state, a_host(tmp_path, crontab=True))

    assert answered.returncode == 1, answered.stdout
    assert "NOTHING HAS BEEN ASSUMED FROM IT" in answered.stderr
    assert key in answered.stderr, answered.stderr


# --- 5. what the record no longer licenses -------------------------------------


def test_the_exit_three_advice_does_not_outlive_the_failure_it_is_about(tmp_path) -> None:
    """*"It never left the machine, re-send it"* — printed under a run that exited 0.

    ``last_failure`` is kept for ever, on purpose, and the advice was keyed on its exit
    code alone. So a host that failed to upload in March was still being told to re-send an
    artifact from March under this morning's successful, uploaded run.
    """
    old = {"at": "2026-01-01T04:00:00Z", "due_date": "2026-01-01",
           "exit_code": 3, "outcome": "not-sent"}
    fresh = {"at": "2026-02-01T04:00:00Z", "due_date": "2026-02-01",
             "exit_code": 0, "outcome": "offsite"}
    host = a_host(tmp_path, crontab=True)

    healed = run(
        "status", an_env(tmp_path),
        a_record(tmp_path, offsite="yes", last_failure=old, last_success=fresh,
                 last_attempt=fresh),
        host,
    )
    assert healed.returncode == 0, healed.stderr
    assert "did NOT leave this" not in healed.stdout, (
        "a run that exited 0 and did leave the machine is reported as one that did not:\n"
        f"{healed.stdout}"
    )

    still = run(
        "status", an_env(tmp_path),
        a_record(tmp_path, offsite="yes", last_failure=old, last_success=None,
                 last_attempt=old),
        host,
    )
    assert "did NOT leave this" in still.stdout, (
        "the advice is gone from the state it exists for"
    )
    assert "make backup-upload FROM=" in still.stdout


def test_the_missed_days_label_is_not_printed_with_nothing_after_it(tmp_path) -> None:
    """*"days with no backup: 12 — most recent:"* and then the end of the line.

    ``missed_total`` counts every day ever missed; ``missed_dates`` keeps thirty of them.
    A record old enough to have rolled over, or one whose list a hand edit emptied, has the
    count and not the dates — and the panel guards this exact pair.
    """
    answered = run(
        "status", an_env(tmp_path),
        a_record(tmp_path, missed_total=12, missed_dates=[]),
        a_host(tmp_path, crontab=True),
    )
    assert answered.returncode == 0, answered.stderr
    line = [x for x in answered.stdout.splitlines() if "days with no backup" in x]
    assert line, answered.stdout
    assert "12" in line[0]
    assert not line[0].rstrip().endswith("most recent:"), line[0]
    assert "no longer names which" in line[0], line[0]

    named = run(
        "status", an_env(tmp_path),
        a_record(tmp_path, missed_total=2, missed_dates=["2026-02-01", "2026-01-31"]),
        a_host(tmp_path, crontab=True),
    )
    listed = [x for x in named.stdout.splitlines() if "days with no backup" in x]
    assert re.search(r"most recent: 2026-02-01 2026-01-31", listed[0]), listed[0]


# --- 6. one value, one place it is read from -----------------------------------


def test_the_uploader_cannot_be_switched_on_from_the_calling_shell(tmp_path) -> None:
    """The two readers disagreed about WHERE the answer comes from, and both were used.

    Compose interpolates ``${VAR}`` from the calling shell before it falls back to
    ``--env-file``, so ``HASHI_BACKUP_ENABLED=1 make backup`` uploaded — while the recorder,
    which reads the env file and only the env file, wrote ``"offsite": "no"``. The run said
    it had sent the artifact and the screen then said the upload was switched off, about
    the same run.

    Driven rather than read: the two array definitions are sliced out of the script and
    invoked with a ``docker`` on ``PATH`` that answers with what it was given. What compose
    does with the name once it is unset is compose's documented precedence and is not
    re-proven here; what is proven is that the name does not reach it.
    """
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "docker").write_text(
        "#!/usr/bin/env bash\n"
        'printf "HASHI_BACKUP_ENABLED=%s\\n" "${HASHI_BACKUP_ENABLED-<not in the environment>}"\n'
    )
    (binaries / "docker").chmod(0o755)

    definitions = [
        line for line in BACKUP.read_text().splitlines()
        if line.startswith(("COMPOSE=(", "COMPOSE_UPLOAD=("))
    ]
    assert len(definitions) == 2, definitions
    script = "\n".join(['ENV_FILE="/dev/null"', *definitions, '"${COMPOSE_UPLOAD[@]}" run'])

    answered = subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, timeout=60, cwd=REPO,
        stdin=subprocess.DEVNULL,
        env={"PATH": f"{binaries}:{os.environ.get('PATH', '')}",
             "HASHI_BACKUP_ENABLED": "1"},
    )
    assert answered.returncode == 0, answered.stderr
    assert "HASHI_BACKUP_ENABLED=<not in the environment>" in answered.stdout, (
        "an exported HASHI_BACKUP_ENABLED still reaches compose, so the uploader and the "
        f"record can still disagree about one run: {answered.stdout!r}"
    )


def test_the_env_file_is_named_as_the_one_place_that_value_is_read(tmp_path) -> None:
    """The operator's half of the same fix: the template says where it is answered from.

    Whoever exported it on the command line did so because nothing said not to, and the
    one file both readers can see is the one this value belongs in.
    """
    example = (REPO / ".env.example").read_text()
    block = example.split("\nHASHI_BACKUP_ENABLED=0", 1)[0]
    assert "read from THIS FILE" in block, (
        ".env.example no longer says where HASHI_BACKUP_ENABLED is answered from"
    )


# --- 7. one file, one host, one minute, ONE verdict ----------------------------
#
# Found in review of this step, and it is this milestone's own thesis arriving through a
# pipe: `printf "%s\n" "${RECORD}" | grep -q …` under `set -o pipefail` returns 141 when
# grep matches early and exits while printf still has bytes to write. `has_key` read that
# as "the key is not there" and refused a perfectly good record, naming a different valid
# key each time. Measured before the fix on the record below: six refusals in twelve
# consecutive runs — `0 0 1 0 1 0 0 1 1 0 1 1` — naming `at_source`, `zone`, `zone_source`
# and `last_failure`, every one of them present and valid.

# Enough missed days to put the canonicalised text over a pipe buffer while the FILE stays
# under the ceiling — which is the whole trap: this record is legal, and every reader has
# to give the same answer about it every time.
A_LEGAL_RECORD_THIS_BIG = 4900
# Runs per verdict. One green run is not evidence about a race; it is the same trap as a
# test that turns on garbage collection.
ENOUGH_RUNS_TO_SEE_A_RACE = 12


def _dates(count: int) -> list[str]:
    day = datetime.date(2005, 1, 1)
    return sorted(
        (day + datetime.timedelta(days=step)).isoformat() for step in range(count)
    )[::-1]


def _compact(state: pathlib.Path, dates: list[str]) -> None:
    """The record with no spaces in it, which is what a layout-changing tool leaves.

    Compact on purpose: canonicalising it puts back one space after every `:` and `,`, so
    the text the readers work on is LARGER than the file, which is how a file under the
    ceiling produces a string over a pipe buffer.
    """
    record = json.loads((state / "last-run.json").read_text())
    record["missed_dates"] = dates
    record["missed_total"] = len(dates)
    (state / "last-run.json").write_text(json.dumps(record, separators=(",", ":")))


def test_one_unchanged_record_gets_the_same_verdict_every_time(tmp_path) -> None:
    """A legal record, read twelve times, must read the same way twelve times.

    The failure this replaces was not "a wrong answer": it was a CONFIDENT, SPECIFIC
    accusation — *"its \"zone_source\" is not what scripts/backup-run.sh writes there"* —
    about a field whose value is exactly what it should be, on some runs and not others.
    An operator told intermittently that their record is corrupt when it is not is worse
    off than one told nothing.
    """
    state = a_record(tmp_path, last_attempt=A_GOOD_RUN, last_success=A_GOOD_RUN)
    _compact(state, _dates(A_LEGAL_RECORD_THIS_BIG))
    size = (state / "last-run.json").stat().st_size
    assert size < MOST_OF_A_RECORD, (
        f"the fixture outgrew the ceiling and is no longer legal: {size}"
    )

    env, host = an_env(tmp_path), a_host(tmp_path, crontab=True)
    answers = [
        run("status", env, state, host) for _ in range(ENOUGH_RUNS_TO_SEE_A_RACE)
    ]
    codes = [answer.returncode for answer in answers]
    assert codes == [0] * ENOUGH_RUNS_TO_SEE_A_RACE, (
        f"a {size}-byte record that is legal in every respect was refused on "
        f"{codes.count(1)} of {len(codes)} runs: {codes}\n{answers[codes.index(1)].stderr}"
    )
    assert len({answer.stdout for answer in answers}) == 1, (
        "the same file printed two different screens in the same minute"
    )


def test_a_file_too_large_to_be_the_record_is_refused_whole(tmp_path) -> None:
    """The panel refuses anything over 64 KiB outright; so does this, for its size.

    Reading the first 64 KiB and judging THAT is the other option and is worse: it is a
    verdict about a file nobody has seen all of, and a file whose first 64 KiB happen to
    parse would be read out as fact. The two channels now answer a too-large file the same
    way, which is the entire point of this step.
    """
    state = a_record(tmp_path, last_attempt=A_GOOD_RUN, last_success=A_GOOD_RUN)
    _compact(state, _dates(6000))
    size = (state / "last-run.json").stat().st_size
    assert size > MOST_OF_A_RECORD

    env, host = an_env(tmp_path), a_host(tmp_path, crontab=True)
    answers = [run("status", env, state, host) for _ in range(10)]
    assert [answer.returncode for answer in answers] == [1] * 10, (
        [answer.returncode for answer in answers]
    )
    assert all("NOTHING HAS BEEN ASSUMED FROM IT" in a.stderr for a in answers)
    # The file's SIZE, which is a fact about it that needs none of it read — and not
    # `its "size"`, which M28.17 removed: every other fault this refusal names is a real
    # key of the record and there has never been a `size` key for an operator to find.
    assert all(str(size) in a.stderr for a in answers), answers[0].stderr
    assert all("last success:" not in a.stdout for a in answers), (
        "part of a file too big to be the record was read out as fact"
    )


def _whole_pipelines(text: str) -> list[tuple[int, str]]:
    """The script's commands, with backslash continuations folded onto one line.

    Shell reads ``a \\\n  | b`` as ONE command and so must anything asking what that
    command does. Both guards below look for a pattern that spans a pipe, and both were
    blind to the continuation form until this went in front of them: at this step's
    baseline the pipe guard reported ONE of the three ``<<<"${RECORD}" | head -n 1``
    readers, because the other two carried the ``| head`` onto a continuation line that
    holds no ``${RECORD}``.

    The number that comes back is the FIRST physical line, so an offender is still
    reported where a person can find it.
    """
    folded, number, carried, started = [], 0, "", 1
    for line in text.splitlines():
        number += 1
        if not carried:
            started = number
        if line.endswith("\\"):
            carried += line[:-1] + " "
            continue
        folded.append((started, carried + line))
        carried = ""
    if carried:
        folded.append((started, carried))
    return folded


def test_no_reader_of_the_record_feeds_it_through_a_pipe() -> None:
    """The guard, because the fix is one character wide and reads like a style choice.

    `printf … | grep`/`sed` over the record is the shape that produced the race; a
    herestring is written by the shell itself and has no writer to kill. Structural, and
    aimed at the reintroduction rather than at the symptom — a behavioural test for this
    passes on the day the race happens not to fire.

    Widened twice by M28.18. It sweeps every shell surface rather than one script, because
    the readers moved into ``scripts/lib/backup-record.sh`` and a guard naming one file
    would have gone quiet on the move — which is exactly how a rule gets evaded without
    anybody meaning to. And it now names BOTH ends of the race: a writer that can be killed
    (`printf`/`echo`/`cat` into a pipe) and a reader that exits early on the other end of
    one (`| head`, `| grep -q`), which is the half `read_state` had all along in
    ``sed … <<<"${RECORD}" | head -n 1``. The record needs enough lines matching one key for
    that to fire, so it had never been seen — the same "narrow window, therefore green"
    that hid the first half for eleven milestones.

    A PIPELINE IS JUDGED AS A PIPELINE, not as a line. Measured at this step's baseline,
    the line-wise version of this test reported ONE of the three ``<<<"${RECORD}" | head
    -n 1`` occurrences that were there: the other two — in ``raw_field`` and in
    ``read_state`` — carried the ``| head -n 1`` onto a backslash continuation, which holds
    no ``${RECORD}`` and so was never looked at. The continuation is the form the code
    actually used twice, so a guard that cannot see it was guarding the rarer shape.
    """
    offenders = []
    for path in SHELL_SURFACES:
        for number, line in _whole_pipelines(path.read_text()):
            # Comments are skipped for the reason ``code_only`` exists one file over:
            # every script here quotes the wrong version of a line beside the right one,
            # and both of the shapes below are named in the library's own explanation of
            # why they are forbidden. An assertion over raw text measures the prose.
            if "${RECORD}" not in line or line.lstrip().startswith("#"):
                continue
            if line.lstrip().startswith(("printf", "echo", "cat")):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
            elif re.search(r"\|\s*(head|tail|grep\s+-[a-z]*[qm]|read)\b", line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "a reader of the record is feeding it through a pipe again, which returns 141 "
        f"under pipefail whenever either end exits early: {offenders}"
    )


# --- 8. one reader of the record, and nothing that can grow into a second one --------
#
# M28.18, and it is the defect the other six surfaces were symptoms of. ``backup-run.sh``
# held TWO readers of one file: the lenient `field`/`read_state` path behind `tick` and
# `now`, which pulled values out of whatever was at the path and checked none of them, and
# the strict `record_problem` path behind `status` and `due`. Every fix in this milestone
# was correct and none generalised, because each one taught ONE of them something.
#
# What these three tests are aimed at is the SECOND READER COMING BACK, not at today's
# spelling: a `field`-alike appearing in any of these scripts would have to open the record
# or take apart the text of it, and neither is reachable from outside the library any more.
#
# WHERE THE FENCE ENDS, written here rather than in a review note, because a fence whose
# seams are recorded somewhere else is one the next person trusts further than it goes:
#
#   * a second parser written INSIDE the library and reached through the entry point is not
#     caught by any of these. It is the weakest remaining shape and it is deliberately out
#     of reach of a structural check — what these protect is that no CALLER can get a value
#     the validation refused, and a parser behind the entry point still cannot;
#   * only shell is swept. A reader in Python, or in the control zone, is another test's;
#   * the record's path has to appear literally — ``${STATE_FILE}`` or ``last-run.json`` —
#     so a path assembled out of pieces at runtime walks past;
#   * a command riding on a trailing ``#`` comment is not seen, because comment lines are
#     skipped whole (the scripts here quote the forbidden shapes while explaining them);
#   * and these read the source. Nothing here proves the library BEHAVES as one reader; the
#     tests above this section do that by running the verbs.

UNREADABLE = {
    "schema": {"schema": 99},
    "offsite": {"offsite": 3},
    "last_attempt": {"last_attempt": {"at": "yesterday", "exit_code": 0, "outcome": "ok"}},
    "missed_dates": {"missed_dates": ["yesterday"]},
}


@pytest.mark.parametrize("fault", sorted(UNREADABLE))
def test_a_tick_takes_a_backup_rather_than_believing_a_record_it_cannot_read(
    tmp_path, fault
) -> None:
    """The owner's decision of 2026-09-24, on the channel that actually takes backups.

    A damaged ``last_attempt`` used to make the tick conclude the day's backup had been
    taken — out of a file it could not parse, and byte-for-byte the opposite of what the
    panel said about the same file. It reads through the same reader as ``due`` now, gets
    the same refusal, and treats a record it cannot read as no record: it RUNS.

    Observed without Docker, and this is the trick worth keeping: the record's directory is
    made read-only, so a tick that decides to WAIT returns 0 before it ever looks at the
    directory, while a tick that decides to RUN reaches ``ensure_state_dir`` and refuses
    there, loudly, having dumped nothing. The two decisions are told apart by the exit code
    without a database anywhere near it.
    """
    state = a_record(tmp_path, due_date=today_in("Etc/UTC"), **UNREADABLE[fault])
    state.chmod(0o500)
    try:
        answered = run("tick", an_env(tmp_path), state)
    finally:
        state.chmod(0o700)

    assert answered.returncode == 1, (
        f"a tick read a record with a damaged {fault} and concluded the day's backup was "
        "taken, which is what it did before this step and what the panel has never said "
        f"about the same file:\n{answered.stdout}{answered.stderr}"
    )
    assert "cannot write the backup record" in answered.stderr, answered.stderr


def test_due_says_what_the_tick_will_do_with_the_record_it_just_refused(tmp_path) -> None:
    """The sentence the collapse made possible — and it is the tick's own verdict.

    Until there was one reader this verb ended with *"Nothing is said above about what the
    next tick would do, because that answer is read out of this same file"*, which was true:
    the tick read that file leniently and this verb had no way of knowing what it would make
    of the bytes. Both hold the same reading now, so the refusal can end by naming the
    action — and the action comes from running ``decide``, not from a sentence somebody
    keeps in step with it by hand.

    ``decide``'s REASON is deliberately not printed with it: on an empty reading that reason
    is *"no backup has ever been recorded on this host"*, which is what a genuinely fresh
    host is told, and M28.15 took that sentence off this verb for exactly that reason.
    """
    refused = run("due", an_env(tmp_path), a_record(tmp_path, schema=99))
    assert refused.returncode == 1
    assert "action=run" in refused.stderr, (
        f"the refusal does not say what the next tick will do with the file:\n{refused.stderr}"
    )
    assert "no record" in refused.stderr
    assert "no backup has ever been recorded" not in refused.stderr, (
        "the sentence a fresh host is told is back on a refusal about a damaged record"
    )

    # The one fault where the tick does NOT end in a backup, because it never reaches that
    # verdict: `ensure_state_dir` refuses a path that is not a file before anything is
    # dumped, and promising a backup there would be a promise nothing keeps.
    state = tmp_path / "shape"
    (state / "last-run.json").mkdir(parents=True)
    shaped = run("due", an_env(tmp_path), state)
    assert shaped.returncode == 1
    assert "will not take a backup either" in shaped.stderr, shaped.stderr
    assert "action=" not in shaped.stderr, (
        "a backup is promised at a path a tick refuses before it dumps anything"
    )


# The record's own path, however it is spelled. ``last-run.json`` as well as the variable,
# because a second reader that built the path out of ``STATE_DIR`` by hand would otherwise
# walk straight past a guard that only knew the variable.
THE_RECORD_PATH = re.compile(r"\$\{STATE_FILE\}|last-run\.json")
# The commands that take text apart. In COMMAND POSITION only: these words appear in the
# prose this script prints — *"could not be read"* has `read` in it, and the refusals talk
# about files — and a guard that flagged prose would be turned off within a milestone.
TAKES_TEXT_APART = re.compile(
    r"^(?:sed|awk|grep|egrep|fgrep|cut|head|tail|tr|wc|jq|cat|xargs|source|\.)\b"
)


def _commands(line: str) -> list[str]:
    """One shell line as the separate commands it runs.

    Each ``$( )`` body is lifted out and judged on its own, then what is left of the line
    is judged without it. That distinction is the whole reason this is not a substring
    search: ``printf … "$(… | tr …)" "${STATE_FILE}"`` mentions a text tool and the record's
    path on one line and reads nothing — the tool is inside a substitution that never sees
    the path. Lifting them apart tells that from ``x="$(sed -n … "${STATE_FILE}")"``, which
    is the thing being forbidden.
    """
    # BACKTICKS FIRST, and they are not a style question here. `` X="`sed -n 1p
    # "${STATE_FILE}"`" `` is the same tool reading the same file through the older syntax,
    # and a walker that only knows ``$( )`` leaves the fragment starting with a backtick, so
    # the anchored match below never fires and the fence passes. There is no shellcheck in
    # the Makefile or in CI, so nothing else in this project covers SC2006 either. One
    # level of nesting, which is all the form supports without escaping.
    line = re.sub(r"`([^`]*)`", r"$(\1)", line)
    pieces, rest, depth, start = [], "", 0, 0
    for index, char in enumerate(line):
        if line.startswith("$(", index):
            if depth == 0:
                start = index + 2
            depth += 1
        elif char == ")" and depth:
            depth -= 1
            if depth == 0:
                pieces += _commands(line[start:index])
                continue
        elif depth == 0:
            rest += char
    pieces.append(rest)
    # `local x=`, `x=` and the leading whitespace go, so what is left starts with the word
    # that is actually run.
    return [
        re.sub(r"^(?:local\s+)?[A-Za-z_][A-Za-z0-9_]*=", "", part).strip()
        for piece in pieces
        for part in re.split(r"\|\||&&|[|;&]", piece)
    ]


def test_only_the_library_ever_opens_the_record() -> None:
    """No script but ``scripts/lib/backup-record.sh`` takes that file as input.

    Two shapes, because a reader arrives as one or the other: a redirect of the file into
    something, and a text tool with the file among its arguments. At the baseline of this
    step ``backup-run.sh`` had both — ``wc -c < "${STATE_FILE}"`` and ``record_as_lines <
    "${STATE_FILE}"`` — so this is red before the change and green after it, which is what
    makes it a guard rather than a description.

    What it deliberately does NOT forbid is writing there: ``mv``, ``chmod`` and the
    heredoc that builds the record all name the path, and the writer is this script's own.

    The redirect half matches the path HOWEVER IT IS SPELLED — ``while … done <
    "${STATE_DIR}/last-run.json"`` reads the record as surely as the variable does, and an
    earlier version of this only knew ``${STATE_FILE}``.

    WHAT IT STILL DOES NOT CATCH, so that nobody trusts it further than it goes: a reader
    written inside the library itself and reached through the entry point (both channels
    would still agree, which is the property being protected, but it is a real seam); a
    reader in another language or in another zone; a path assembled at runtime out of
    pieces, since the literal has to appear somewhere in the line to be seen; and a command
    hidden in a trailing ``#`` comment on a code line.
    """
    offenders = []
    for path in SHELL_SURFACES:
        if path == RECORD_LIB:
            continue
        # Folded, exactly as the pipe guard is: ``sed -n '…' \\`` on one line and
        # ``"${STATE_FILE}"`` on the next is a reader whose command word and whose file
        # never appear together, and a line-wise scan sees neither half as an offence.
        for number, line in _whole_pipelines(path.read_text()):
            if not THE_RECORD_PATH.search(line):
                continue
            for command in _commands(line):
                if not THE_RECORD_PATH.search(command):
                    continue
                redirected = [
                    target
                    for target in re.findall(r'<\s*"?([^\s"|;&<>]+)"?', command)
                    if THE_RECORD_PATH.search(target)
                ]
                if redirected or TAKES_TEXT_APART.match(command):
                    offenders.append(f"{path.name}:{number}: {command}")
    assert not offenders, (
        "something other than scripts/lib/backup-record.sh is reading the backup record, "
        "which is the second reader this step exists to remove — two readers of one file "
        f"is how one host gets two verdicts about it: {offenders}"
    )


def test_the_canonical_text_of_the_record_lives_in_one_place() -> None:
    """``${RECORD}`` — the file's bytes, canonicalised — exists in the library and nowhere.

    A second parser does not have to open the file: it only has to get hold of the text.
    Keeping the text inside the library is what makes the entry point the only way in, and
    it is also what keeps the pipe guard above honest, since that guard looks for this name.
    """
    elsewhere = [
        f"{path.name}:{number}"
        for path in SHELL_SURFACES
        if path != RECORD_LIB
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "${RECORD}" in line
    ]
    assert not elsewhere, (
        "the record's canonicalised text has escaped the library that reads it, so a "
        f"second parser of it can be written without opening the file: {elsewhere}"
    )


def test_the_verbs_reach_the_record_only_through_the_one_entry_point() -> None:
    """One function of that library is callable from outside it, and one only.

    This is the fence rather than a description of today's code: a library that grows a
    second public ``field()`` and a verb that calls it is the two-reader shape back, with
    the file in the right place and the property gone. It fails on the SHAPE — any library
    function reached from another script — and not on a list of the names that exist now.

    The same for what the verbs may believe: they may read the values the library assigns
    and may not assign one themselves, because a reading written back into is no longer a
    reading of the file.
    """
    library = RECORD_LIB.read_text()
    functions = set(re.findall(r"^(\w+)\(\) \{", library, re.M))
    assert "backup_record_read" in functions, "the entry point is no longer a function"
    assigned = set(re.findall(r"\b(RECORD|RECORD_[A-Z0-9_]+|READING_[A-Z0-9_]+)=", library))

    for path in SHELL_SURFACES:
        if path == RECORD_LIB:
            continue
        text = path.read_text()
        called = {name for name in functions if re.search(rf"\b{name}\b", text)}
        assert called <= {"backup_record_read"}, (
            f"{path.name} reaches past the record's one entry point and into "
            f"{sorted(called - {'backup_record_read'})}"
        )
        used = set(re.findall(r"\$\{(RECORD|RECORD_[A-Z0-9_]+|READING_[A-Z0-9_]+)\}", text))
        assert used <= assigned, (
            f"{path.name} reads {sorted(used - assigned)} out of the record's reader, which "
            "no longer sets it"
        )
        written = re.findall(
            r"^\s*(RECORD|RECORD_[A-Z0-9_]+|READING_[A-Z0-9_]+)=", text, re.M
        )
        assert not written, (
            f"{path.name} writes back into the reading ({written}), so what the verbs act "
            "on is no longer what the library read"
        )
