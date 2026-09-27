"""The schedule's contract — M28.5.

WHAT: the decisions ``scripts/backup-run.sh`` makes about WHEN a backup is owed, and the
      shape of the crontab entry ``scripts/backup-schedule.sh`` installs.
WHY:  a schedule that silently skips a day is discovered during a restore, and by then the
      day is gone. Everything that could skip silently is decided by a shell script rather
      than by cron, so it can be exercised — which is what this file does: the scheduling
      verbs are run, with a real clock, a real env file and a seeded record, and no Docker
      anywhere.
HOW:  ``due`` answers "what would a tick do right now" and changes nothing, so every
      scheduling decision is reachable without dumping a database. The clock is the host's
      own and is never frozen, so a fixture seeding the date the schedule is on asks
      ``day_owed_in`` for it and never the calendar — the two answers differ at every hour
      before the configured one, which is where M27.9 found a suite red.
      ``tick``, ``now`` and a real backup are the e2e tier's —
      ``tests/e2e/infra/test_restore_proves_the_backup.py``
      is where the schedule is watched actually firing against a booted stack.

      What is NOT proven anywhere, stated rather than implied: that a host's ``cron``
      daemon invokes a ``*/15`` line. Proving that means waiting on a quarter-hour boundary
      inside a privileged container, and it would be proving cron rather than hashi. What
      is proven here is that the entry is a well-formed five-field line with no hour in it,
      installed without disturbing the operator's other entries.
"""

import datetime
import json
import os
import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts" / "backup-run.sh"
INSTALLER = REPO / "scripts" / "backup-schedule.sh"
BACKUP = REPO / "scripts" / "backup.sh"
MAKEFILE = REPO / "Makefile"
BASE_COMPOSE = REPO / "deploy" / "docker-compose.yml"
ENV_EXAMPLE = REPO / ".env.example"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"

# The heading the schedule is written under. Quoted by scripts/backup-schedule.sh when a
# host has no crontab, so renaming it silently breaks that pointer.
SCHEDULE_SECTION = "When the backup runs, and how you know it did"

# The record's keys, in full. A file written once a day for years is exactly the thing that
# grows into a log, so this list is the fence: adding a key is a deliberate act that fails
# here first, and nothing about a PERSON may ever appear in it (CLAUDE.md — never log who
# connected to what).
RECORD_KEYS = {
    "schema", "written_at", "at", "at_source", "zone", "zone_source", "offsite",
    "due_date", "attempts", "retry_not_before", "last_attempt", "last_success",
    "last_failure", "missed_dates", "missed_total",
}


@pytest.fixture(scope="module")
def runner() -> str:
    return RUNNER.read_text()


@pytest.fixture(scope="module")
def installer() -> str:
    return INSTALLER.read_text()


# Planted in every env file this suite writes, and asserted absent from the output of
# every run — see `run()`. This script is the only one in the project that opens the env
# file at all, so the check belongs on the path every test already takes rather than in one
# test somebody can forget to look at.
PLANTED = ("this-is-not-real-and-must-never-be-read-0000", "also-not-real-either")


def env_file(directory: pathlib.Path, **values: str) -> pathlib.Path:
    """An env file with the schedule's settings in it, and secrets that must not be read.

    The secrets are there on purpose, and `run()` asserts on them after every invocation:
    what this script may take out of the env file is three named settings, and everything
    else in the file must stay in it.
    """
    path = directory / "schedule.env"
    path.write_text(
        f"HASHI_SECRET_KEY={PLANTED[0]}\n"
        f"POSTGRES_PASSWORD={PLANTED[1]}\n"
        + "".join(f"{name}={value}\n" for name, value in values.items())
    )
    return path


def run(verb: str, path: pathlib.Path, state: pathlib.Path) -> subprocess.CompletedProcess:
    """One invocation, with the environment cron gives it — and nothing leaked.

    The secrets planted by `env_file()` are checked here rather than in a test of their
    own, so the property is asserted by every scheduling test in this file instead of by
    one that has to be remembered. A cron job's output goes to a mail spool.
    """
    result = subprocess.run(
        [str(RUNNER), verb],
        capture_output=True, text=True, timeout=60, cwd=REPO,
        stdin=subprocess.DEVNULL,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "ENV_FILE": str(path),
            "HASHI_BACKUP_STATE_DIR": str(state),
        },
    )
    said = result.stdout + result.stderr
    for secret in PLANTED:
        assert secret not in said, (
            f"`{verb}` printed a value it is not allowed to read out of the env file"
        )
    record = state / "last-run.json"
    if record.is_file():
        written = record.read_text()
        for secret in PLANTED:
            assert secret not in written, "a secret from the env file reached the record"
    return result


def verdict(result: subprocess.CompletedProcess) -> dict[str, str]:
    """The first line of ``due``, which is ``key=value`` pairs and nothing else."""
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    first = result.stdout.splitlines()[0]
    return dict(pair.split("=", 1) for pair in first.split(" "))


def seed(state: pathlib.Path, **fields) -> pathlib.Path:
    """A record as ``scripts/backup-run.sh`` writes one, so the script reads its own shape.

    Written as JSON with one key per line, which is the format the script both writes and
    reads back with ``sed`` — a host that can run the stack is not assumed to have a JSON
    parser, and the control plane is the one machine that may be rebuilt from nothing.
    """
    record = {
        "schema": 1,
        "written_at": "2026-01-01T00:00:00Z",
        "at": "04:00",
        "at_source": "configured",
        "zone": "Etc/UTC",
        "zone_source": "configured",
        "offsite": "no",
        "due_date": "2026-01-01",
        "attempts": 1,
        "retry_not_before": "",
        "last_attempt": {"at": "2026-01-01T04:00:00Z", "due_date": "2026-01-01",
                         "exit_code": 0, "outcome": "on-this-host-only"},
        "last_success": {"at": "2026-01-01T04:00:00Z", "due_date": "2026-01-01",
                         "exit_code": 0, "outcome": "on-this-host-only"},
        "last_failure": None,
        "missed_dates": [],
        "missed_total": 0,
    }
    record.update(fields)
    state.mkdir(parents=True, exist_ok=True)
    lines = [f'  "{name}": {json.dumps(value)}' for name, value in record.items()]
    (state / "last-run.json").write_text("{\n" + ",\n".join(lines) + "\n}\n")
    return state / "last-run.json"


# The hour as ``scripts/backup-run.sh::resolve_schedule`` reads one: the characters it
# keeps, the shape it accepts, and the zero-padding it applies. Copied here rather than
# elided because ``4:00`` is supported operator input — pinned by
# ``test_a_time_that_is_not_a_time_falls_back_and_says_so`` below — and an oracle that
# compared a wall clock against the raw string answered a day early for every hour of a
# two-digit clock. Held to the script by
# ``test_the_day_this_suite_seeds_is_the_day_the_script_owes``; change this only with a run
# of that.
AT_SHAPE = re.compile(r"^([0-9]|[01][0-9]|2[0-3]):[0-5][0-9]$")
AT_KEEPS = re.compile(r"[^A-Za-z0-9_+:/.-]")
AT_WHEN_THERE_IS_NONE = "04:00"


def the_hour_the_script_resolves(at: str) -> str:
    """``at`` as the script will hold it, which is not always as the env file spells it."""
    kept = AT_KEEPS.sub("", at)[:64]
    if not AT_SHAPE.match(kept):
        return AT_WHEN_THERE_IS_NONE
    hour, _, minute = kept.partition(":")
    return f"{int(hour, 10):02d}:{minute}"


def day_owed_in(zone: str, at: str) -> str:
    """The date whose backup a schedule of ``at`` in ``zone`` owes at this instant.

    The rule is ``scripts/backup-run.sh::due_date``'s and this is a second implementation
    of it rather than a reading of the script. WHICH OF THE TWO A TEST WANTS, because the
    file next door states the opposite rule and both are right about their own subject:
    **implement the date here when the assertion is ABOUT the date** — that the tick wrote
    the day it owes, that a record dated now is not called ahead — because asking the
    script would make the assertion agree with whatever the script does; **ask the script
    for it** when the date is only scaffolding under some other assertion, which is the
    canonical second case and is
    ``test_the_backup_surfaces_record_nobody.py::test_a_tick_with_nothing_owed_says_nothing_at_all``.

    WHY THE CALENDAR'S DATE IS NOT THIS DATE, which is the whole of M27.9 and the reason the
    helper that returned it (``today_in``) is gone rather than left beside this one for the
    next fixture to reach for. Before ``at`` the day owed is still the previous one, so a
    record seeded with the calendar's date is a record dated AHEAD of the schedule for those
    hours and the script says so — three tests in
    ``test_what_the_command_line_may_say_about_a_backup.py`` were green for twenty hours a
    day and red for four, against a product that was right at all twenty-four, and four
    here were the same defect in the one minute before ``00:01``. Ask this with the pair the
    env file under test names, never with a pair typed beside it.

    The zone is handed to ``date`` as it was written, deliberately: the script resolves an
    unusable one to UTC, and ``TZ=<not a zone> date`` prints UTC too (measured on this host,
    and the script's own comment records it), so the two agree without a second copy of
    that fallback. The hour has no such luck and goes through
    ``the_hour_the_script_resolves``.

    One ``date`` call for both halves, because two would let the day and the hour come from
    opposite sides of a midnight — which is one more than the script itself manages, and the
    only place this implementation is deliberately not a mirror.
    """
    result = subprocess.run(
        ["date", "+%F %H:%M"], capture_output=True, text=True, timeout=30,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TZ": zone},
    )
    day, _, hour = result.stdout.strip().partition(" ")
    if hour < the_hour_the_script_resolves(at):
        day = (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()
    return day


# --- the oracle this suite seeds with, held against the script ------------------


# The grid is chosen by OFFSET and not by hour, so whatever the wall clock is when this
# runs, it holds zones on both sides of every hour below — a pin written against one zone
# would itself be green only at some hours, which is M27.9's defect a third time. The last
# zone is not a zone: the script resolves an unusable one to UTC, `date` does too, and this
# is where that agreement is checked rather than assumed.
@pytest.mark.parametrize(
    "at",
    # The last four are the spellings the script does not hold as they were written: `4:00`
    # and `9:30` are accepted and PADDED, `25:00` is refused and falls back to the hour it
    # uses when there is none, and `1 2:00` is stripped down to a time it then accepts. An
    # oracle comparing a clock against the raw string answers a day out for all four, and
    # was measured doing exactly that before this test existed.
    ["00:01", "04:00", "12:00", "23:59", "4:00", "9:30", "25:00", "1 2:00"],
)
@pytest.mark.parametrize(
    "zone", ["Etc/GMT+11", "Etc/GMT+5", "Etc/UTC", "Etc/GMT-5", "Etc/GMT-13", "Nowhere/Useful"],
)
def test_the_day_this_suite_seeds_is_the_day_the_script_owes(tmp_path, zone, at) -> None:
    """``day_owed_in`` is a second implementation of ``due_date`` and nothing held it there.

    Every fixture in this zone that seeds a current due date is dated by that helper, so a
    helper that drifts from the script does not fail — it seeds records the script reads as
    dated ahead or behind, and the tests around it then assert whatever the drift produces.
    That is M28.12's two-readers defect arriving in the harness instead of the product, and
    it was already here when the helper was born: the raw-string comparison it shipped with
    answered ``2026-09-26`` where the script answered ``2026-09-27`` for ``at=4:00`` in
    ``Etc/GMT-8`` — measured, at 02:24 UTC on the day this test was written.

    The oracle is read on both sides of the invocation because the two clocks are read a
    moment apart: a comparison taken across the configured minute would be red for one
    second a day, which is the shape this whole step is about.
    """
    state = tmp_path / "state"
    state.mkdir()
    path = env_file(tmp_path, HASHI_BACKUP_AT=at, HASHI_BACKUP_TZ=zone)

    before = day_owed_in(zone, at)
    answered = verdict(run("due", path, state))["due"]
    after = day_owed_in(zone, at)

    assert answered in {before, after}, (
        f"the date this suite seeds and the date the script owes have parted at "
        f"{zone} {at!r}: the script says {answered}, the oracle says {before} — every "
        "fixture dated by that helper is now seeding a record the script reads as dated "
        "ahead or behind"
    )


# --- what 04:00 means ---------------------------------------------------------


def test_the_hour_is_read_in_the_configured_zone_and_not_the_hosts(tmp_path) -> None:
    """The decision the plan names: a host's clock is UTC and its owner is not.

    Two zones a whole day apart in the same instant, and a time between them — the same
    host, the same minute, and a different answer about which day's backup is owed. If the
    host's own clock decided this, both would answer the same.
    """
    state = tmp_path / "state"
    (tmp_path / "e").mkdir()
    (tmp_path / "l").mkdir()
    early = env_file(tmp_path / "e", HASHI_BACKUP_AT="12:00", HASHI_BACKUP_TZ="Pacific/Kiritimati")
    late = env_file(tmp_path / "l", HASHI_BACKUP_AT="12:00", HASHI_BACKUP_TZ="Pacific/Midway")

    seed(state, due_date="2020-01-01")
    one = verdict(run("due", early, state))
    other = verdict(run("due", late, state))

    assert one["zone"] == "Pacific/Kiritimati" and one["zone_source"] == "configured"
    assert other["zone"] == "Pacific/Midway" and other["zone_source"] == "configured"
    assert one["due"] != other["due"], (
        "two zones a day apart answered with the same due date, so the zone is not what "
        "decides when 04:00 is — which is the whole reason HASHI_BACKUP_TZ exists"
    )


@pytest.mark.parametrize(
    "zone,source",
    [
        ("Etc/UTC", "configured"),
        ("", "unset"),
        ("Nowhere/Useful", "unknown"),
        ("+03:00", "unknown"),
        # A PATH rather than a name. `../../../../etc/passwd` under the zone database is a
        # real file, so the `-f` test alone called it a configured zone and the promise in
        # docs/decisions.md — checked against the database rather than trusted — was not
        # true for this shape. Nothing was disclosed either way; `date` ignores a file that
        # is not a zone file. It is refused by name now.
        ("../../../../etc/passwd", "unknown"),
        ("/etc/passwd", "unknown"),
        ("..", "unknown"),
        ("Europe/../Europe/Moscow", "unknown"),
    ],
)
def test_a_zone_that_is_missing_or_not_a_zone_is_named_rather_than_guessed(
    tmp_path, zone: str, source: str
) -> None:
    """`TZ=Nowhere/Useful date` does not fail — it answers in UTC and exits 0.

    Checked on this machine rather than assumed, which is why the script looks the name up
    in the host's zone database instead of trusting it. Without that, a misspelled zone is
    indistinguishable from a working one and the backup quietly runs hours away from where
    the operator put it.

    An offset (`+03:00`) lands in the same bucket deliberately: it is not a zone name, and
    accepting it would be accepting a number that stops being true the next time the rule
    changes.
    """
    state = tmp_path / "state"
    seed(state, due_date="2020-01-01")
    answer = verdict(run("due", env_file(tmp_path, HASHI_BACKUP_TZ=zone), state))
    assert answer["zone_source"] == source
    if source != "configured":
        assert answer["zone"] == "UTC", (
            "an unusable zone fell back to something other than the host's own clock — no "
            "country may be guessed at here"
        )
    assert answer["action"] == "run", "a bad zone stopped the backup; it must only be recorded"


@pytest.mark.parametrize(
    "value,at,source",
    [("04:00", "04:00", "configured"), ("4:00", "04:00", "configured"),
     ("23:59", "23:59", "configured"), ("", "04:00", "unset"),
     # 08 and 09 are the two hours a leading zero makes fatal: both printf and $(( ))
     # read them as OCTAL, and the tick died before writing any record at all — a silent
     # skip with nothing for the panel to show. Found by review, not by the suite, which
     # is why they are named here rather than left to whichever hour a test picks.
     ("08:00", "08:00", "configured"), ("09:15", "09:15", "configured"),
     ("08:30", "08:30", "configured"), ("09:00", "09:00", "configured"),
     ("quarter past", "04:00", "malformed"), ("25:00", "04:00", "malformed")],
)
def test_a_time_that_is_not_a_time_falls_back_and_says_so(
    tmp_path, value: str, at: str, source: str
) -> None:
    """A typo in a setting must not cost a day of backups — it costs a line in the panel."""
    state = tmp_path / "state"
    seed(state, due_date="2020-01-01")
    answer = verdict(run("due", env_file(tmp_path, HASHI_BACKUP_AT=value), state))
    assert (answer["at"], answer["at_source"]) == (at, source)
    assert answer["action"] == "run"


# --- the box that was down ----------------------------------------------------


def test_a_day_the_box_was_down_is_owed_rather_than_skipped(tmp_path) -> None:
    """The failure this whole step exists to prevent.

    The record says the last accounted day was five days ago. Whatever the hour is now,
    the answer is "run" — not "wait until 04:00 tomorrow", which is what a crontab line
    carrying an hour would have done, silently, for the fifth day running.
    """
    state = tmp_path / "state"
    at, zone = "04:00", "Etc/UTC"
    path = env_file(tmp_path, HASHI_BACKUP_AT=at, HASHI_BACKUP_TZ=zone)
    owed = day_owed_in(zone, at)
    old = subprocess.run(
        ["date", "-d", f"{owed} - 5 days", "+%F"], capture_output=True, text=True, timeout=30,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    ).stdout.strip()

    answer = verdict(run("due", path, seed(state, due_date=old).parent))
    assert answer["action"] == "run"


def test_the_days_that_had_no_backup_are_named_by_date(tmp_path) -> None:
    """"The fact that a day was missed must survive" — as dates, so M28.6 can say which.

    And exactly the days BETWEEN: a dump is a copy of the database as it is now, so the
    catch-up is one run, not one per missed day, and the days that genuinely have no
    artifact are the ones in the gap.
    """
    state = tmp_path / "state"
    at, zone = "00:01", "Etc/UTC"
    path = env_file(tmp_path, HASHI_BACKUP_AT=at, HASHI_BACKUP_TZ=zone)
    owed = day_owed_in(zone, at)
    dates = [
        subprocess.run(
            ["date", "-d", f"{owed} - {back} days", "+%F"],
            capture_output=True, text=True, timeout=30,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        ).stdout.strip()
        for back in (3, 2, 1)
    ]

    answer = verdict(run("due", path, seed(state, due_date=dates[0]).parent))
    assert answer["action"] == "run"
    assert answer["missed"] == ",".join(dates[1:]), (
        "the days between the last accounted backup and this one are not listed, so a "
        "restore would find a gap the panel never mentioned"
    )


def test_a_day_that_already_has_a_backup_is_not_taken_twice(tmp_path) -> None:
    """The other half: a tick every fifteen minutes must be quiet 95 times out of 96."""
    state = tmp_path / "state"
    at, zone = "00:01", "Etc/UTC"
    path = env_file(tmp_path, HASHI_BACKUP_AT=at, HASHI_BACKUP_TZ=zone)
    seed(state, due_date=day_owed_in(zone, at))
    answer = verdict(run("due", path, state))
    assert answer["action"] == "wait"
    assert answer["missed"] == "none"

    quiet = run("tick", path, state)
    assert quiet.returncode == 0
    assert quiet.stdout == "" and quiet.stderr == "", (
        "a tick with nothing to do printed something, so cron mails the operator 96 times "
        "a day and the one mail that matters is lost in them"
    )


def test_an_artifact_that_did_not_leave_the_machine_is_not_dumped_again(tmp_path) -> None:
    """Exit 3 is a state with its own remedy, not a failure to retry.

    Re-dumping would write a second copy of the same database and never fix the reason the
    store refused it; `make backup-upload FROM=<path>` sends the one already on disk.
    """
    state = tmp_path / "state"
    at, zone = "00:01", "Etc/UTC"
    path = env_file(tmp_path, HASHI_BACKUP_AT=at, HASHI_BACKUP_TZ=zone)
    owed = day_owed_in(zone, at)
    seed(
        state,
        due_date=owed,
        attempts=1,
        retry_not_before="",
        last_attempt={"at": "2026-01-01T04:00:00Z", "due_date": owed,
                      "exit_code": 3, "outcome": "not-sent"},
        last_failure={"at": "2026-01-01T04:00:00Z", "due_date": owed,
                      "exit_code": 3, "outcome": "not-sent"},
    )
    answer = run("due", path, state)
    assert verdict(answer)["action"] == "wait"
    assert "has not been sent" in answer.stdout


def test_a_run_that_produced_nothing_is_retried_but_not_without_limit(tmp_path) -> None:
    """Exit 1 is usually a stack that had not finished booting, and a retry costs nothing.

    Capped, because a permanently broken configuration should fail once an hour and not
    once every tick, and it must not keep trying for ever into tomorrow's window either.
    """
    state = tmp_path / "state"
    at, zone = "00:01", "Etc/UTC"
    path = env_file(tmp_path, HASHI_BACKUP_AT=at, HASHI_BACKUP_TZ=zone)
    owed = day_owed_in(zone, at)
    failed = {"at": "2026-01-01T04:00:00Z", "due_date": owed,
              "exit_code": 1, "outcome": "no-artifact"}

    waiting = run("due", path, seed(
        state, due_date=owed, attempts=1, retry_not_before="2999-01-01T00:00:00Z",
        last_attempt=failed, last_failure=failed,
    ).parent)
    assert verdict(waiting)["action"] == "wait"
    assert "not before" in waiting.stdout

    ready = run("due", path, seed(
        state, due_date=owed, attempts=1, retry_not_before="2000-01-01T00:00:00Z",
        last_attempt=failed, last_failure=failed,
    ).parent)
    assert verdict(ready)["action"] == "run"

    spent = run("due", path, seed(
        state, due_date=owed, attempts=99, retry_not_before="2000-01-01T00:00:00Z",
        last_attempt=failed, last_failure=failed,
    ).parent)
    assert verdict(spent)["action"] == "wait"


def test_a_host_with_no_record_at_all_takes_one_at_once(tmp_path) -> None:
    """A control plane with no backup should not wait until tomorrow's 04:00 for its first.

    It is also what makes an operator find out within a quarter of an hour of installing
    the schedule that it works, rather than the morning after.
    """
    answer = verdict(run("due", env_file(tmp_path), tmp_path / "empty"))
    assert answer["action"] == "run"


def test_two_ticks_do_not_dump_at_the_same_time(tmp_path) -> None:
    """A dump takes minutes and ticks are fifteen apart — until one is slow.

    The lock is a directory because ``mkdir`` is the atomic operation every host has. A
    tick that finds one held does nothing and exits 0: it is not an error, and the next
    tick is fifteen minutes away.
    """
    state = tmp_path / "state"
    state.mkdir()
    (state / ".tick.lock").mkdir()
    blocked = run("tick", env_file(tmp_path), state)
    assert blocked.returncode == 0
    assert not (state / "last-run.json").exists(), "a locked tick still wrote a record"


# --- what is written down -----------------------------------------------------


def test_the_record_carries_backups_and_never_people(runner: str) -> None:
    """The one record that can hurt a real person is the one nobody writes on purpose.

    A file the schedule appends to every day for years is exactly the thing that becomes a
    log, so the key set is fixed here. Dates, exit codes and the schedule's own settings —
    no user, no node, no address, no token, no path into anybody's traffic.
    """
    block = re.search(r"cat > \"\$\{tmp\}\" <<JSON\n((?:.*\n)*?)JSON", runner)
    assert block, "the record is no longer written as one block, so its keys cannot be read"
    written = set(re.findall(r'^\s*"(\w+)":', block.group(1), re.M))
    assert written == RECORD_KEYS, (
        f"the record's keys changed: added {sorted(written - RECORD_KEYS)}, removed "
        f"{sorted(RECORD_KEYS - written)}. Adding one is a decision about what this host "
        "writes down every day for ever."
    )
    forbidden = re.compile(r"user|friend|node|token|subscri|address|ip_|traffic", re.I)
    assert [key for key in written if forbidden.search(key)] == []


def test_the_record_answers_the_question_the_panel_has_to_ask(tmp_path) -> None:
    """M28.6's question: when did a backup last succeed, and has one failed since.

    Answerable from this file alone, which matters because it cannot be answered any other
    way on this host — the credential here may only write, so the bucket cannot be asked.
    """
    state = tmp_path / "state"
    record = json.loads(seed(
        state,
        last_success={"at": "2026-01-01T04:00:00Z", "due_date": "2026-01-01",
                      "exit_code": 0, "outcome": "offsite"},
        last_failure={"at": "2026-01-02T04:00:00Z", "due_date": "2026-01-02",
                      "exit_code": 3, "outcome": "not-sent"},
    ).read_text())
    assert record["last_success"]["at"] < record["last_failure"]["at"]
    assert record["last_failure"]["exit_code"] == 3


def test_the_control_container_can_read_the_record_and_cannot_write_it() -> None:
    """The panel reads it; nothing in the stack may invent a success or erase a failure."""
    mounts = re.search(
        r"^  control:\n((?:.*\n)*?)^  \w", BASE_COMPOSE.read_text(), re.M
    )
    assert mounts, "the control service is no longer where this file expects it"
    line = [
        text.strip() for text in mounts.group(1).splitlines()
        if "backups/state" in text and not text.lstrip().startswith("#")
    ]
    assert line == ["- ../backups/state:/var/lib/hashi/backup:ro"], (
        "the control container does not get a read-only view of the backup record, so the "
        f"panel has no way to answer when a backup last succeeded: {line}"
    )


def test_the_state_directory_exists_before_a_daemon_can_create_it_as_root() -> None:
    """A bind mount whose source is missing is created by dockerd, owned by root.

    The schedule runs as the operator and would then never write the record — on a host
    where everything else works. Both routes that bring a stack up create it first.
    """
    assert "mkdir -p backups/state" in MAKEFILE.read_text(), (
        "`make env` does not create the record's directory, so the first `make up` on a "
        "fresh clone hands it to root"
    )
    bootstrap = (REPO / "scripts" / "panel-bootstrap.sh").read_text()
    assert "backups/state" in bootstrap, (
        "the panel bootstrap brings a stack up without creating the record's directory"
    )


def test_status_says_nothing_has_run_rather_than_nothing_at_all(tmp_path) -> None:
    """"No record" and "no backup" look the same to an operator, and both need saying."""
    result = subprocess.run(
        [str(RUNNER), "status"],
        capture_output=True, text=True, timeout=60, cwd=REPO, stdin=subprocess.DEVNULL,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "ENV_FILE": str(env_file(tmp_path)),
            "HASHI_BACKUP_STATE_DIR": str(tmp_path / "nothing"),
        },
    )
    assert result.returncode == 1
    assert "No backup has ever been recorded on this host" in result.stderr
    assert "make backup-schedule" in result.stderr


# --- what it is allowed to read -----------------------------------------------


def test_the_schedule_reads_three_names_out_of_the_env_file_and_no_others(runner: str) -> None:
    """The env file holds real secrets and this is the only script in the project that opens it.

    `scripts/backup.sh` deliberately opens nothing — compose reads the file on its behalf.
    This one cannot use that route: it has to decide that a backup is owed at the moment
    the stack may be down, which is exactly when no container can be asked. So it greps
    named keys, never sources, never prints, and the names it may ask for are a list the
    script enforces on itself.
    """
    allowed = re.search(r'SCHEDULE_KEYS="([^"]*)"', runner)
    assert allowed, "the whitelist is gone, so any name could be lifted out of the env file"
    names = set(allowed.group(1).split())
    assert names == {"HASHI_BACKUP_AT", "HASHI_BACKUP_TZ", "HASHI_BACKUP_ENABLED"}

    asked = set(re.findall(r"env_value (\w+)", runner))
    assert asked <= names, f"the script reads {sorted(asked - names)} out of the env file"
    assert "exit 2" in re.search(
        r"env_value\(\) \{\n((?:.*\n)*?)^\}$", runner, re.M
    ).group(1), "the whitelist is advisory rather than enforced"


def test_the_schedule_never_prints_the_env_file(runner: str) -> None:
    """A routine that runs unattended every fifteen minutes, with its output going to mail."""
    for line in runner.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert not re.search(r"(cat|source|\.)\s+\"?\$\{ENV_FILE", line), (
            f"the env file is read whole here, not by name: {line.strip()}"
        )


# --- the entry cron actually gets ---------------------------------------------


def test_the_cron_entry_carries_no_hour(installer: str) -> None:
    """The decision the milestone turns on.

    `0 4 * * *` is a promise cron cannot keep: a box that is off, asleep or being rebuilt
    at 04:00 misses the minute and nothing anywhere records that it did. The entry fires
    every fifteen minutes and asks the script whether the day's backup is owed, so "today
    has no backup" stays true until one is taken.
    """
    entries = [
        line for line in installer.splitlines()
        if re.match(r"^[\d*][\d*/,\-]* .* \S*scripts/backup-run\.sh", line)
    ]
    assert len(entries) == 1, f"expected exactly one cron entry, found {entries}"
    fields = entries[0].split()
    assert fields[:5] == ["*/15", "*", "*", "*", "*"], (
        f"the cron entry names an hour: {entries[0]!r}. An hour is a promise cron cannot "
        "keep across a reboot."
    )
    assert fields[-1] == "tick"


def test_the_entry_does_not_throw_away_what_a_failed_run_says(installer: str) -> None:
    """`>/dev/null 2>&1` on a cron line is how a broken backup runs for a year unnoticed.

    A tick with nothing to do prints nothing, so a working schedule is already silent; the
    output that exists is the output that matters.
    """
    assert "/dev/null" not in installer.split("our_block()")[1].split("}")[0]


def test_installing_the_schedule_leaves_the_operators_other_entries_alone(
    installer: str,
) -> None:
    """A crontab is the operator's file and may hold entries that matter more than ours.

    Idempotent by construction rather than by intent: the block between two markers is
    dropped and rewritten, everything else is copied through, so installing twice leaves
    one entry and removing takes out exactly that block.
    """
    assert re.search(r"without_our_block; our_block; \} \| crontab -", installer), (
        "install does not rebuild the crontab from everything-that-is-not-ours plus ours"
    )
    assert installer.count("crontab -l") >= 1
    remove = re.search(r"command_remove\(\) \{\n((?:.*\n)*?)^\}$", installer, re.M)
    assert remove and "without_our_block | crontab -" in remove.group(1)


def test_the_installer_says_where_to_go_on_a_host_with_no_cron(installer: str) -> None:
    """The one thing in this design that depends on something the host provides."""
    assert SCHEDULE_SECTION in installer, (
        "a host without `crontab` is told nothing about the systemd timer that replaces it"
    )
    assert f"### {SCHEDULE_SECTION}" in RUNBOOK.read_text(), "the section it points at is gone"


# --- the verbs the owner types ------------------------------------------------


def test_every_scheduling_verb_is_a_make_target() -> None:
    """The Makefile is this zone's contract with the owner (04-infra-rulebook)."""
    makefile = MAKEFILE.read_text()
    for target in ("backup-schedule:", "backup-unschedule:", "backup-status:"):
        assert target in makefile, f"{target} is not a Make target"


def test_a_backup_taken_by_hand_counts_as_the_days_backup() -> None:
    """Otherwise the panel reports a host as un-backed-up an hour after it was backed up.

    And the schedule would take a second one at 04:00 for a day that already has one.
    """
    makefile = MAKEFILE.read_text()
    target = re.search(r"^backup:\n((?:\t.*\n)+)", makefile, re.M)
    assert target, "the backup target is gone"
    assert "backup-run.sh now" in target.group(1), (
        "`make backup` goes straight to the dump, so a backup taken by hand leaves no "
        "trace in the record the panel reads"
    )


def test_the_exit_codes_are_the_ones_the_panel_keys_on(runner: str) -> None:
    """M28.3's contract, unchanged: 0 written, 1 no artifact, 2 usage, 3 did not leave.

    The wrapper adds a record and no new codes — 3 in particular has to survive, because it
    is the difference between "there is no backup" and "there is one and it is only here".
    """
    outcomes = re.search(r"outcome_for\(\) \{\n((?:.*\n)*?)^\}$", runner, re.M)
    assert outcomes, "the exit codes are no longer turned into a recorded outcome"
    body = outcomes.group(1)
    assert re.search(r"^\s*3\)\s.*not-sent", body, re.M)
    assert re.search(r"^\s*1\)\s.*no-artifact", body, re.M)
    assert re.search(r"^\s*0\)\s.*offsite.*on-this-host-only", body, re.M)
    assert 'return "${status}"' in runner, "the backup's exit code is not passed through"


def test_the_backup_script_itself_is_unchanged_in_what_it_promises() -> None:
    """The scheduler wraps the dump; it does not reach inside it.

    A schedule that reimplemented any part of the pipeline would be a second description of
    the artifact, and M28.1 settled that the artifact and its description move together.
    """
    code = re.sub(r"(?m)^\s*#.*$", "", RUNNER.read_text())
    for stage in ("pg_dump", "docker compose", "--recipient", "gzip"):
        assert stage not in code, (
            f"the scheduler runs {stage!r} itself, so there are now two accounts of what a "
            "backup is and they will disagree"
        )
    assert '"${BACKUP}" dump' in code
    assert BACKUP.is_file()


# --- what the operator is told ------------------------------------------------


def test_the_env_file_says_what_an_unset_or_wrong_zone_does() -> None:
    """The two variables existed before anything read them; now they mean something."""
    said = ENV_EXAMPLE.read_text()
    assert "HASHI_BACKUP_AT" in said and "HASHI_BACKUP_TZ" in said
    for phrase in ("unset", "unknown", "malformed", "make backup-schedule"):
        assert phrase in said, f"`.env.example` does not say what happens when it is {phrase}"
    assert "backups/state/last-run.json" in said, (
        "the env file does not say where the record of the runs is kept"
    )


def test_the_runbook_section_says_a_missed_day_is_recorded_rather_than_lost() -> None:
    """The plan's own sentence: a schedule that silently skips is found during a restore."""
    section = re.search(
        rf"^### {re.escape(SCHEDULE_SECTION)}\n((?:.*\n)*?)(?=^#{{2,3}} )",
        RUNBOOK.read_text(), re.M,
    )
    assert section, "the runbook no longer says when the backup runs"
    said = section.group(1)
    assert "0 4 * * *" in said, (
        "the section does not show the entry it refuses to install, so the reason for the "
        "fifteen-minute tick reads as an implementation detail"
    )
    assert re.search(r"written down by date", said)
    assert "make backup-status" in said
    assert re.search(r"systemd", said, re.I), "a host with no cron is left with nothing"
    assert "Persistent=true" in said


def test_the_schedule_section_points_at_the_two_tables_rather_than_restating_them() -> None:
    """`## Backups` has two decision tables and this is not a third.

    What goes into an artifact is M28.1's table; what the bucket does to it is M28.4's.
    When it runs is neither, so the section says so and points, instead of growing a third
    copy of a decision that is settled elsewhere.
    """
    runbook = RUNBOOK.read_text()
    section = re.search(
        rf"^### {re.escape(SCHEDULE_SECTION)}\n((?:.*\n)*?)(?=^#{{2,3}} )", runbook, re.M
    ).group(1)
    assert "|" not in section, "the schedule section grew a table of its own"
    assert "The retention this host's own key cannot reach" in section, (
        "the section claims a green schedule is a kept backup without pointing at the one "
        "place that says this host cannot check the bucket"
    )


def test_a_tick_that_cannot_write_the_record_is_loud_and_not_silent(tmp_path) -> None:
    """The hazard the read-only mount introduces, turned into an error message.

    The record's directory is bind mounted into the control container, so the docker daemon
    creates it — as root — if a stack comes up before anything else makes it. Every tick
    after that would be unable to record, on a host where the backup itself works fine. A
    schedule that shrugs at that is the silent-skip failure wearing a different hat, so it
    refuses out loud and before it touches the database.
    """
    fenced = tmp_path / "fenced"
    fenced.mkdir()
    fenced.chmod(0o500)
    try:
        result = run("tick", env_file(tmp_path), fenced / "state")
    finally:
        fenced.chmod(0o700)
    assert result.returncode == 1
    assert "cannot write the backup record" in result.stderr
    assert "chown" in result.stderr, "the operator is not told how to fix it"


def test_a_tick_refuses_a_directory_where_the_record_goes_rather_than_writing_into_it(
    tmp_path,
) -> None:
    """``mv`` onto a directory does not fail — it moves the file INSIDE it.

    So a tick dumped the database, moved ``last-run.json.partial`` into the directory
    sitting at the record's path, exited 0 and recorded nothing. Every fifteen minutes, for
    ever, on a host whose backups were working: the schedule reporting success and leaving
    no account of itself is the silent skip this script exists to refuse, wearing the same
    hat as the read-only directory above. It refuses before anything is dumped, and it
    refuses rather than repairing — nothing here deletes what an operator put on a disk.
    """
    state = tmp_path / "state"
    (state / "last-run.json").mkdir(parents=True)

    result = run("tick", env_file(tmp_path), state)

    assert result.returncode == 1, (
        f"a tick wrote its record into a directory and called it a success:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "cannot write the backup record" in result.stderr
    assert "a directory" in result.stderr, "the shape that is in the way is not named"
    assert not list((state / "last-run.json").iterdir()), (
        "the partial record was deposited inside the directory anyway"
    )


def test_the_record_directory_is_made_before_anything_locks_or_dumps(runner: str) -> None:
    """Regression: the lock is a directory inside the record's directory.

    ``mkdir`` of the lock fails when its parent does not exist, and a tick that cannot take
    the lock does nothing and exits 0 — so on a host where the record had never been
    written, the schedule was silently a no-op for ever. Found by running it, not by
    reading it.
    """
    for verb in ("command_tick", "command_now"):
        body = re.search(rf"{verb}\(\) \{{\n((?:.*\n)*?)^\}}$", runner, re.M).group(1)
        assert "ensure_state_dir" in body, f"{verb} does not make sure it can record"
        assert body.index("ensure_state_dir") < body.index("take_lock"), (
            f"{verb} takes the lock before the directory holding it is known to exist"
        )
