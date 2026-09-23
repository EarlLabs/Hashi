"""A backup that has been failing for six weeks says so where the owner already looks.

WHAT: the record on disk turned into the standing the Overview draws — every way the file
      can be missing, damaged or absurd, every way the backups themselves can stand, and
      the rendered screen carrying the right one of them.
WHY:  M28.6. The dangerous state is not "the backup failed", it is "the backup has been
      failing for six weeks and nothing said so". Two halves are being pinned here and
      they fail differently:

      * the READING must never raise. It is called from the path that draws the panel's
        front page, and a shell script that wrote a file badly, a mount that arrived
        empty or a path pointing at a log file must degrade into a sentence rather than
        into a 500 on the screen the operator opens first.
      * the WORDING must never inflate. This host's record says how its own runs went. It
        says nothing about whether an artifact is still in the bucket — the credential
        here may only write, so it cannot look (M28.3), and nothing in this repository
        asserts what the bucket keeps (M28.4). Every standing, including the good one,
        carries that sentence, and this file asserts it for all six rather than for the
        alarming ones.
HOW:  the reader is driven against real files under ``tmp_path``; the wording is composed
      from readings with no filesystem at all; the screen is rendered through the real
      application, with ``backup_record`` pointing at a record this file wrote.

      The sample record is written out by hand from the writer's own heredoc
      (``scripts/backup-run.sh``, ``write_state``) rather than produced by running it: the
      script dumps a database and needs a docker engine, which this tier deliberately does
      not have. What stops the two drifting is that the writer's key set is closed and
      asserted in the infra zone, and that ``test_the_closed_key_set_is_what_this_reads``
      below pins the same fifteen names from this end. Nothing here reads
      ``scripts/``: the contract is the one written down in
      ``docs/tracker/M28/step-notes.md``, not the other zone's source.
"""

import datetime
import json
import logging
import os
import pathlib
import subprocess
import sys

import pytest

from control.app.services import backups, console

# The child in ``test_a_fifo_at_the_record_path_cannot_hang_the_panel`` imports the
# application, so it is started from the checkout root rather than from here.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# A fixed instant for every judgement, so "43 days ago" is arithmetic and not a race.
NOW = datetime.datetime(2026, 9, 23, 12, 0, 0, tzinfo=datetime.UTC)

# Every key the writer emits, M28.5's closed set, in its own order. Written out because
# this is the contract between two zones and a contract repeated in one place is a
# contract; read out of the other zone's script it would be a copy of whatever that
# script does today.
EVERY_KEY = (
    "schema",
    "written_at",
    "at",
    "at_source",
    "zone",
    "zone_source",
    "offsite",
    "due_date",
    "attempts",
    "retry_not_before",
    "last_attempt",
    "last_success",
    "last_failure",
    "missed_dates",
    "missed_total",
)

# The file as the schedule really lays it out: one key per line, the three nested entries
# on one line each, so a shell with no JSON parser can read it with sed. Copied from the
# writer's heredoc and used byte for byte by one test below.
AS_THE_SCHEDULE_WRITES_IT = """{
  "schema": 1,
  "written_at": "2026-09-23T04:00:11Z",
  "at": "04:00",
  "at_source": "configured",
  "zone": "Europe/Belgrade",
  "zone_source": "configured",
  "offsite": "yes",
  "due_date": "2026-09-23",
  "attempts": 1,
  "retry_not_before": "",
  "last_attempt": { "at": "2026-09-23T04:00:11Z", "due_date": "2026-09-23", \
"exit_code": 0, "outcome": "offsite" },
  "last_success": { "at": "2026-09-23T04:00:11Z", "due_date": "2026-09-23", \
"exit_code": 0, "outcome": "offsite" },
  "last_failure": null,
  "missed_dates": [],
  "missed_total": 0
}
"""

# Words a screen about backups must never acquire. Not a style rule: each of them turns
# "this host's own runs went like this" into "a restorable artifact exists", which is the
# claim nothing in this product can make.
NEVER_SAID = ("safe", "guaranteed", "verified", "backed up and", "you are covered")


def moment(hours_ago: float) -> str:
    """A timestamp in the writer's own format, that long before ``NOW``."""
    when = NOW - datetime.timedelta(hours=hours_ago)
    return when.strftime(backups.TIMESTAMP)


def run(hours_ago: float, *, exit_code: int = 0, outcome: str = "offsite") -> dict:
    return _run_at(NOW, hours_ago, exit_code=exit_code, outcome=outcome)


def live(hours_ago: float, *, exit_code: int = 0, outcome: str = "offsite") -> dict:
    """The same, against the REAL clock — for the tests that render the screen.

    Nothing passes a ``now`` through an HTTP request, so a rendered screen reads the wall
    clock. A record pinned to ``NOW`` would therefore age as the day went on, and a
    scenario asserting "43 days ago" would read 42 in the morning and 43 after lunch. The
    gap is only ever measured downwards to the next whole unit, so a record built this way
    can only stay on the number it was built for while the test runs.
    """
    return _run_at(
        datetime.datetime.now(datetime.UTC), hours_ago, exit_code=exit_code, outcome=outcome
    )


def _run_at(
    base: datetime.datetime, hours_ago: float, *, exit_code: int, outcome: str
) -> dict:
    when = base - datetime.timedelta(hours=hours_ago)
    return {
        "at": when.strftime(backups.TIMESTAMP),
        "due_date": when.strftime("%Y-%m-%d"),
        "exit_code": exit_code,
        "outcome": outcome,
    }


def record(**overrides) -> dict:
    """A whole record, healthy unless a test says otherwise."""
    written = {
        "schema": 1,
        "written_at": moment(6),
        "at": "04:00",
        "at_source": "configured",
        "zone": "Europe/Belgrade",
        "zone_source": "configured",
        "offsite": "yes",
        "due_date": "2026-09-23",
        "attempts": 1,
        "retry_not_before": "",
        "last_attempt": run(6),
        "last_success": run(6),
        "last_failure": None,
        "missed_dates": [],
        "missed_total": 0,
    }
    written.update(overrides)
    return written


@pytest.fixture
def written(backup_record: pathlib.Path):
    """Puts a record where this suite's control plane reads one from.

    Takes the same path the ``settings`` fixture was built with, so a test may write the
    file and then ask the real application to draw the screen — the read happens per
    request, so the order of the two does not matter.
    """

    def write(content: str | dict) -> pathlib.Path:
        backup_record.parent.mkdir(parents=True, exist_ok=True)
        backup_record.write_text(
            content if isinstance(content, str) else json.dumps(content, indent=2)
        )
        return backup_record

    return write


async def standing_of(path: pathlib.Path) -> console.BackupStanding:
    """What the screen would say about the record at ``path``, right now at ``NOW``."""
    return console.backup_standing(await backups.read(path, now=NOW))


# --- the reading, and every way a file can disappoint -------------------------------

async def test_no_record_at_all_is_nothing_recorded_and_not_an_error(
    backup_record: pathlib.Path,
) -> None:
    """The normal case on a control plane that does not run beside the backups.

    The mount is read-only and arrives empty when the host has never taken one — and it
    arrives empty for the whole life of a control plane running somewhere else. Neither is
    a fault, and the sentence says so rather than reporting a broken panel; what it does
    not do is stay silent, because "no backup has ever been recorded" IS the six weeks of
    silence, on day one.
    """
    reading = await backups.read(backup_record, now=NOW)
    assert reading.standing is backups.Standing.ABSENT
    assert reading.record is None
    assert reading.since_success is None

    said = console.backup_standing(reading)
    assert said.loud
    assert said.headline == "No backup has ever been recorded on this host."
    assert str(backup_record) in said.detail
    assert "nothing recorded" in said.detail
    assert "make backup-schedule" in said.detail


async def test_the_record_the_schedule_really_writes_is_read(written) -> None:
    """Byte for byte, in the layout the writer's heredoc produces."""
    path = written(AS_THE_SCHEDULE_WRITES_IT)
    reading = await backups.read(path, now=NOW)

    assert reading.standing is backups.Standing.FRESH
    assert reading.record.zone == "Europe/Belgrade"
    assert reading.record.last_success.outcome == "offsite"
    assert reading.record.last_failure is None


async def test_the_closed_key_set_is_what_this_reads(written) -> None:
    """The fifteen keys M28.5 settled, and a sixteenth that must change nothing.

    Both halves matter and they pull opposite ways. Reading a record whose keys are
    exactly the closed set is the contract; ignoring a key this code has never seen is
    what stops a later version of the writer turning this screen into "the record is
    unreadable" for a field the panel does not even want.
    """
    whole = record()
    assert tuple(whole) == EVERY_KEY, "the sample has drifted from M28.5's closed set"
    assert (await standing_of(written(whole))).loud is False

    with_a_sixteenth = record()
    with_a_sixteenth["artifact_bytes"] = 4096
    assert (await standing_of(written(with_a_sixteenth))).loud is False


async def test_a_half_written_record_says_it_could_not_be_read(written) -> None:
    """Truncated mid-object. The writer renames a complete file into place, so this
    should not be observable at all — a hand edit is where it comes from, and the panel
    still may not fall over on it."""
    path = written(json.dumps(record(), indent=2)[:120])
    reading = await backups.read(path, now=NOW)

    assert reading.standing is backups.Standing.UNREADABLE
    assert reading.record is None

    said = console.backup_standing(reading)
    assert said.loud
    assert "could not read it" in said.headline
    # The refusal to guess, said in both directions: an operator who reads only the
    # headline must not take "unreadable" for either answer.
    assert "not telling you backups are working" in said.detail
    assert "not telling you they are failing" in said.detail


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("not json at all\n", id="not-json"),
        pytest.param("[1, 2, 3]\n", id="not-an-object"),
        pytest.param("", id="empty"),
    ],
)
async def test_a_file_that_is_not_the_record_is_never_read_as_one(
    written, content: str
) -> None:
    assert (await backups.read(written(content), now=NOW)).standing is (
        backups.Standing.UNREADABLE
    )


async def test_a_record_from_a_newer_writer_is_not_guessed_at(written) -> None:
    """A schema number this code has never seen is refused, not interpreted.

    The layout behind that number is the whole of what this reader assumes. Reading a
    future one on the assumption it is still shaped like this is how a panel reports a
    success it inferred from a file it does not understand.
    """
    path = written(record(schema=backups.RECORD_SCHEMA + 1))
    assert (await backups.read(path, now=NOW)).standing is backups.Standing.UNREADABLE


async def test_a_run_whose_entry_is_not_a_run_is_not_read_as_never(written) -> None:
    """A damaged ``last_success`` is UNREADABLE, never "no backup has ever succeeded".

    The two would raise the same alarm for completely different reasons, and the second is
    a statement the record is entitled to make while the first is not.
    """
    path = written(record(last_success={"at": "yesterday-ish", "outcome": "offsite"}))
    assert (await backups.read(path, now=NOW)).standing is backups.Standing.UNREADABLE


async def test_a_path_pointing_at_something_enormous_is_not_slurped(written) -> None:
    """Whatever is at the path is read on every draw of the front page, so there is a
    ceiling on it. Over the ceiling the file is not the record, and that is the answer."""
    path = written("x" * (backups.MOST_OF_A_RECORD + 10))
    assert (await backups.read(path, now=NOW)).standing is backups.Standing.UNREADABLE


async def test_a_directory_where_the_record_should_be_degrades(
    backup_record: pathlib.Path,
) -> None:
    """What dockerd leaves when a bind mount's source is missing. Presence with nothing
    legible in it, which is not the same answer as absence."""
    backup_record.mkdir(parents=True)
    assert (await backups.read(backup_record, now=NOW)).standing is (
        backups.Standing.UNREADABLE
    )


async def test_something_that_is_not_a_file_is_refused_before_it_is_read(caplog) -> None:
    """A character device answers instantly and for ever, so it is refused on its type.

    ``/dev/zero`` rather than something planted: it is a real non-regular file every Linux
    has, it opens without blocking, and it would otherwise hand back as many bytes as this
    process cared to ask for. The refusal is on ``S_ISREG``, before a byte is read, which
    is the same guard that keeps a FIFO out — see the scenario below.

    The LOG LINE is asserted and not only the standing, because the standing alone would
    not notice the guard going: sixty-four kilobytes of zeros are not JSON either, so a
    reader that slurped the device would answer UNREADABLE for the wrong reason and this
    would stay green while the FIFO hole reopened.
    """
    with caplog.at_level(logging.WARNING, logger="control.app.services.backups"):
        reading = await backups.read(pathlib.Path("/dev/zero"), now=NOW)

    assert reading.standing is backups.Standing.UNREADABLE
    assert "is not a regular file" in caplog.text, caplog.text


# A whole interpreter, started by the scenario below, because the fault it is about cannot
# be exercised in this process safely. Kept as source rather than as a helper module so
# what the child does is readable beside the reason it is a child.
FIFO_PROBE = """
import asyncio, os, pathlib, sys

from control.app.services import backups

path = pathlib.Path(sys.argv[1])
os.mkfifo(path)
print(asyncio.run(backups.read(path)).standing.value)
"""


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_a_fifo_at_the_record_path_cannot_hang_the_panel(tmp_path) -> None:
    """The one shape that could stop the front page answering at all, in a child process.

    ``open()`` on a FIFO with no writer does not fail and is not slow: it blocks in the
    kernel and never returns. A Python thread stuck there cannot be killed, cancelled or
    reclaimed, so before the non-blocking open this was a request that never answered and
    an executor slot gone until the process restarted — and an interpreter shutdown that
    drains that executor waits on it too.

    IN A SUBPROCESS ON PURPOSE, and this is the whole reason the test is shaped this way:
    a regression here does not fail, it HANGS, and a test that hangs wedges ``make verify``
    for everybody instead of reporting. The child can be killed and a timeout is then an
    ordinary failing assertion with a sentence on it. Nothing in this process ever opens
    the FIFO.
    """
    fifo = tmp_path / "last-run.json"
    try:
        answered = subprocess.run(
            [sys.executable, "-c", FIFO_PROBE, str(fifo)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            "reading a FIFO at the record path never returned — the open is blocking "
            "again, so the panel's front page hangs and one executor thread is gone for "
            "the life of the process"
        )

    assert answered.returncode == 0, answered.stderr
    assert answered.stdout.strip() == backups.Standing.UNREADABLE.value, answered.stdout


# --- what counts as alarming --------------------------------------------------------

async def test_a_recent_backup_with_nothing_wrong_is_not_a_banner(written) -> None:
    """The good state is a muted note, and it still says what it does not know."""
    said = await standing_of(written(record()))

    assert said.loud is False
    assert said.label is None
    assert said.headline == (
        "Last backup 6 hours ago: written here, and the object store accepted it."
    )
    assert "04:00 Europe/Belgrade" in said.detail


async def test_one_failed_run_does_not_cry_wolf(written) -> None:
    """A blip: last night's run failed, the morning before that one succeeded.

    It is the same standing as six weeks of failures on purpose — what tells them apart is
    the age of the last success in the sentence, not a second colour. So the assertion is
    on the sentence: the operator must be able to read "yesterday" off it.
    """
    said = await standing_of(
        written(
            record(
                last_success=run(19),
                last_failure=run(1, exit_code=3, outcome="not-sent"),
                last_attempt=run(1, exit_code=3, outcome="not-sent"),
            )
        )
    )

    assert said.loud
    assert said.label == "failing"
    assert "The last one that succeeded was 19 hours ago" in said.headline
    assert "it did NOT leave this machine" in said.detail
    assert "exit 3" in said.detail


async def test_six_weeks_of_failures_is_unmissable(written) -> None:
    """The same standing, and the number is what makes it a different sentence."""
    said = await standing_of(
        written(
            record(
                last_success=run(24 * 43),
                last_failure=run(8, exit_code=1, outcome="no-artifact"),
                last_attempt=run(8, exit_code=1, outcome="no-artifact"),
                missed_total=42,
                missed_dates=["2026-09-20", "2026-09-21", "2026-09-22"],
            )
        )
    )

    assert said.loud
    assert said.label == "failing"
    assert "The last one that succeeded was 43 days ago" in said.headline
    assert "every run since has failed" in said.headline
    assert "Days with no backup at all since this record began: 42" in said.detail


async def test_a_schedule_that_stopped_running_is_caught_with_no_failure_at_all(
    written,
) -> None:
    """The insidious one, and the reason freshness is keyed on the SUCCESS.

    A crontab that was removed, or a host that was retired, produces no failure: nothing
    runs, so nothing fails, and the last entry in the record is a perfectly good backup
    from six weeks ago. Keyed on "has one failed since?" alone, this record reads as fine
    forever.
    """
    said = await standing_of(written(record(last_success=run(24 * 43), last_attempt=run(24 * 43))))

    assert said.loud
    assert said.label == "silent"
    assert "for 43 days, and nothing has failed either" in said.headline
    assert "nothing has been trying" in said.headline
    assert "make backup-schedule is idempotent" in said.detail


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        pytest.param(47, backups.Standing.FRESH, id="inside-two-days"),
        pytest.param(49, backups.Standing.SILENT, id="past-two-days"),
    ],
)
async def test_the_line_between_recent_and_stale_is_two_days(
    written, hours: int, expected: backups.Standing
) -> None:
    """One whole appointed time missed, plus a day of slack. A box off for an evening is
    not an alarm; a box that has been quiet since the day before yesterday is."""
    path = written(record(last_success=run(hours), last_attempt=run(hours)))
    assert (await backups.read(path, now=NOW)).standing is expected


async def test_a_host_that_has_never_succeeded_says_exactly_that(written) -> None:
    """Two shapes of it, and they are different sentences: nothing has ever run, and
    everything that has run has failed."""
    nothing_yet = await standing_of(
        written(record(last_success=None, last_failure=None, last_attempt=None))
    )
    assert nothing_yet.loud
    assert nothing_yet.label == "no backup"
    assert nothing_yet.headline == "No backup has run on this host yet."

    all_failed = await standing_of(
        written(
            record(
                last_success=None,
                last_failure=run(3, exit_code=2, outcome="refused"),
                last_attempt=run(3, exit_code=2, outcome="refused"),
            )
        )
    )
    assert all_failed.loud
    assert all_failed.label == "no backup"
    assert all_failed.headline == "No backup has ever succeeded on this host."
    assert "refused before anything was dumped" in all_failed.detail


async def test_missed_days_are_history_and_never_an_alarm(written) -> None:
    """``missed_total`` is cumulative and survives the run that ends the gap.

    A fortnight of missed days in June is still fourteen in December, so escalating on it
    would mean a panel that never stops warning about something nobody can now act on. It
    is stated beside a healthy backup and changes nothing about how loud the screen is.
    """
    said = await standing_of(
        written(record(missed_total=14, missed_dates=["2026-06-01", "2026-06-02"]))
    )

    assert said.loud is False
    assert "Days with no backup at all since this record began: 14" in said.detail
    assert "most recent 2026-06-01, 2026-06-02" in said.detail


async def test_a_clock_that_disagrees_does_not_invent_a_stale_backup(written) -> None:
    """A record timestamped in the future is a host whose clock differs from this one."""
    path = written(record(last_success=run(-5), last_attempt=run(-5)))
    reading = await backups.read(path, now=NOW)

    assert reading.standing is backups.Standing.FRESH
    assert reading.since_success == datetime.timedelta(0)


# --- the sentence that must not be inflated -----------------------------------------

async def test_every_standing_says_what_it_does_not_know(written) -> None:
    """All six, including the good one, and especially the good one.

    A successful upload proves the store received exactly those bytes and accepted them,
    and proves nothing about a minute later — the credential on this host may only write,
    so it cannot look, and no test in this project asserts what the bucket keeps. A screen
    that says "last backup 6 hours ago" and stops there is read as "a restorable artifact
    exists offsite", which is the one thing nothing here can promise.
    """
    every = (
        (backups.Standing.ABSENT, None),
        (backups.Standing.UNREADABLE, "not the record"),
        (backups.Standing.NEVER, record(last_success=None, last_attempt=None)),
        (
            backups.Standing.SILENT,
            record(last_success=run(24 * 43), last_attempt=run(24 * 43)),
        ),
        (
            backups.Standing.FAILING,
            record(last_failure=run(1, exit_code=3, outcome="not-sent")),
        ),
        (backups.Standing.FRESH, record()),
    )

    seen = set()
    for expected, content in every:
        # ``None`` is the one standing with no file behind it, so it is the one case that
        # reads a path nothing ever wrote.
        path = (
            pathlib.Path("/nonexistent/hashi/last-run.json")
            if content is None
            else written(content)
        )
        reading = await backups.read(path, now=NOW)
        assert reading.standing is expected, f"{expected} was read as {reading.standing}"
        seen.add(reading.standing)

        said = console.backup_standing(reading)
        assert said.caveat == console.BACKUP_NOT_THE_BUCKET
        assert "still in the bucket" in said.caveat
        whole = f"{said.label or ''} {said.headline} {said.detail}".lower()
        for word in NEVER_SAID:
            assert word not in whole, f"{expected} says {word!r}"

    assert seen == set(backups.Standing), "a standing was never exercised"


# --- the screen ---------------------------------------------------------------------

async def test_the_overview_leads_with_where_the_backups_stand(client, written) -> None:
    """The rendered screen, both as a navigation and as the refresh fragment.

    Both, because the Overview's body is a self-swapping fragment: a mutation anywhere
    re-fetches it, and a backup standing that appeared only on the full page would vanish
    the first time the operator added a user.
    """
    written(
        record(
            last_success=live(24 * 43),
            last_failure=live(2, exit_code=3, outcome="not-sent"),
            last_attempt=live(2, exit_code=3, outcome="not-sent"),
        )
    )

    for path in ("/panel/", "/panel/overview/body"):
        body = (await client.get(path)).text
        assert "Backups on this host are failing." in body, path
        assert "43 days ago" in body, path
        assert ">failing<" in body, f"the standing's own word is missing from {path}"
        assert console.BACKUP_NOT_THE_BUCKET in body, path


async def test_the_overview_says_so_when_nothing_has_been_recorded(client) -> None:
    """No file at all — the empty mount, which is what a fresh install really has."""
    body = (await client.get("/panel/")).text

    assert "No backup has ever been recorded on this host." in body
    assert console.BACKUP_NOT_THE_BUCKET in body


async def test_a_damaged_record_does_not_take_the_front_page_down(
    client, written
) -> None:
    """The whole reason the reading never raises: this is the screen the panel opens on."""
    written("{ this is not the record }")

    response = await client.get("/panel/")

    assert response.status_code == 200
    assert "could not read it" in response.text


async def test_the_panel_only_ever_reads_the_record(client, written) -> None:
    """The mount is read-only and this is the assertion that keeps it meaningful.

    The point of the direction is that the control plane can neither invent a success nor
    erase a failure, so nothing in the panel may write, truncate or re-stamp this file.
    """
    path = written(record(last_success=live(6), last_attempt=live(6)))
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    assert (await client.get("/panel/")).status_code == 200
    assert (await client.get("/panel/overview/body")).status_code == 200

    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


async def test_the_zone_is_shown_as_a_name_and_never_as_a_place(client, written) -> None:
    """An IANA zone name is displayed, not interpreted.

    Turning it into a country on a screen is the panel deciding where its operator is,
    which is a fact about a person on the one machine the charter calls most worth
    seizing — and the charter's whole argument is that such a fact is absent rather than
    withheld.
    """
    written(record(zone="Europe/Moscow", last_success=live(6), last_attempt=live(6)))

    body = (await client.get("/panel/")).text

    assert "Europe/Moscow" in body
    assert "Russia" not in body


async def test_a_zone_that_did_not_resolve_says_which_way_it_failed(written) -> None:
    """All three failures resolve to UTC, and the operator fixes a different thing in
    each, so the screen names which one happened rather than printing UTC and stopping."""
    for source, expected in (
        ("unset", "No zone is configured for the schedule"),
        ("unknown", "not one that host's zone database has"),
        ("no-zone-database", "no zone database at all"),
    ):
        said = await standing_of(written(record(zone="UTC", zone_source=source)))
        assert expected in said.detail, source

    malformed = await standing_of(written(record(at="04:00", at_source="malformed")))
    assert "could not be read, so the schedule fell back to 04:00" in malformed.detail


async def test_an_outcome_this_panel_has_no_word_for_is_named_rather_than_hidden(
    written,
) -> None:
    """The writer's outcome set is closed today and may grow. A sixth word must read as
    itself rather than turning the whole record unreadable or silently reading as one of
    the five."""
    said = await standing_of(written(record(last_success=run(6, outcome="sent-twice"))))

    assert said.loud is False
    assert "sent-twice" in said.headline
