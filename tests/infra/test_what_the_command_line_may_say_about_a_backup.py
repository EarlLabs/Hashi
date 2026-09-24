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

import json
import os
import pathlib
import re
import subprocess

import pytest

from tests.infra.test_backup_schedule import PLANTED, env_file, seed, today_in

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts" / "backup-run.sh"
INSTALLER = REPO / "scripts" / "backup-schedule.sh"
BACKUP = REPO / "scripts" / "backup.sh"

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
