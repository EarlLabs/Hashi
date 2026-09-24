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

import ast
import dataclasses
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


async def test_the_advice_on_a_host_with_no_record_is_true_on_a_restored_one(
    backup_record: pathlib.Path,
) -> None:
    """Found on a real rebuilt host: the panel named a command that refuses there.

    A machine restored out of the backup history has no `.env` — the age recipient and
    the write-only key lived only in the file that is deliberately in no backup — so
    `make backup` there refuses outright, and this is the state such a machine is in:
    nothing at the record path.

    The panel cannot tell that machine from one where the schedule was simply never
    installed, and it does not try. What it may do is lead with the command that runs in
    either case, and say that what it cannot see is whether a backup can run there at all.
    """
    said = console.backup_standing(await backups.read(backup_record, now=NOW))

    assert "start with make backup-status" in said.detail
    assert ".env is in no backup by design" in said.detail
    assert "make backup refuses there" in said.detail
    # It is still told what to do, so the softening did not turn into a shrug.
    assert "make backup-schedule installs the schedule" in said.detail
    # And it does not borrow the restore screen's verdict, which was measured on a host.
    assert "NOT backing anything up" not in said.detail


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

    M28.14 narrowed that and did not reverse it: a gap that is HAPPENING now does get a
    word (below). The dates here are months old — which is why this record is still the
    quiet one, and why the count beside them is still not the thing that decides.
    """
    said = await standing_of(
        written(record(missed_total=14, missed_dates=["2026-06-01", "2026-06-02"]))
    )

    assert said.loud is False
    assert "Days with no backup at all since this record began: 14" in said.detail
    # Newest first — see the ordering scenario below for why the panel does not take the
    # writer's word for which end of the list "most recent" is at.
    assert "most recent 2026-06-02, 2026-06-01" in said.detail


async def test_a_clock_that_disagrees_does_not_invent_a_stale_backup(written) -> None:
    """A record timestamped in the future is a host whose clock differs from this one."""
    path = written(record(last_success=run(-5), last_attempt=run(-5)))
    reading = await backups.read(path, now=NOW)

    assert reading.standing is backups.Standing.FRESH
    assert reading.since_success == datetime.timedelta(0)

    # ...and the clamp is the arithmetic, never the sentence. M28.11: on its own it made a
    # record dated next week read as the quietest line this feature has, permanently.
    assert reading.success_ahead is True


# --- where the artifact went, which is not whether it is still there (M28.11) --------

async def test_a_host_that_sends_nothing_does_not_read_like_one_that_uploads(
    client, written
) -> None:
    """Acceptance 2026-09-23, the first finding, and the milestone's own premise inverted.

    Two records identical but for ``offsite``, both with a recent success, drew screens a
    ``cmp`` could not tell apart — and both closed by saying what they could not tell you
    about a bucket, which on a host that sends nothing anywhere is worse than silence.
    ``HASHI_BACKUP_ENABLED=0`` is the SHIPPED DEFAULT, so that was the out-of-the-box
    screen.

    Driven through the rendered page rather than through the composed object, because
    byte-identical pages is what was actually observed, and an assertion on the two
    standings would not have noticed a template that dropped the difference again.
    """
    screens = {}
    for offsite in ("yes", "no"):
        # The outcome the walker's records carried: a word this panel has no meaning for,
        # so the run clause cannot be what distinguishes the two. That is the point — the
        # record's own ``offsite`` field is the only thing left that can, and the panel
        # used to drop it.
        written(
            record(
                offsite=offsite,
                last_success=live(17, outcome="ok"),
                last_attempt=live(17, outcome="ok"),
            )
        )
        screens[offsite] = (await client.get("/panel/")).text

    assert screens["yes"] != screens["no"], "cmp reports no difference, as acceptance did"
    assert console.BACKUP_NOT_THE_BUCKET in screens["yes"]
    assert console.BACKUP_NOT_THE_BUCKET not in screens["no"]
    assert console.BACKUP_NEVER_LEFT_THIS_HOST in screens["no"]
    assert console.BACKUP_NEVER_LEFT_THIS_HOST not in screens["yes"]


async def test_the_shipped_default_says_the_backup_never_left_the_machine(
    written,
) -> None:
    """The words, on the record `.env.example`'s own default produces.

    Its comment states the rule: a backup that never left the machine is not an offsite
    backup and must not be reported as one. It is still not an alarm — the artifact is
    taken, the schedule keeps running, and that is a supported mode — so the weight does
    not change and only the sentence does.
    """
    said = await standing_of(
        written(
            record(
                offsite="no",
                last_success=run(6, outcome="on-this-host-only"),
                last_attempt=run(6, outcome="on-this-host-only"),
            )
        )
    )

    assert said.loud is False, "not sending is a supported mode, not a fault"
    assert said.caveat == console.BACKUP_NEVER_LEFT_THIS_HOST
    assert "What this does NOT say: that this host is sending its backups anywhere" in (
        said.caveat
    )
    assert "written to the disk of that one machine and stays there" in said.caveat
    assert "neither of them survives losing the machine" in said.caveat
    # The claim M28.6 spent two rounds on is not weakened by the claim M28.11 added: this
    # screen still refuses to say an artifact can be restored.
    assert "only thing that proves a backup is a restore" in said.caveat
    for word in NEVER_SAID:
        assert word not in f"{said.headline} {said.detail} {said.caveat}".lower()


async def test_a_run_that_reached_a_store_still_says_nothing_about_the_bucket(
    written,
) -> None:
    """The other half, and the one that must NOT be softened into the new one.

    Whether a run reached a store at all is something this host knows and now says.
    Whether what reached it is still there is something nothing here will ever know, and
    the caveat that refuses it is unchanged, word for word, from M28.6 — it opens with the
    words `make backup-status` closes with, and the two channels may not be two different
    strengths of claim.
    """
    said = await standing_of(written(record(offsite="yes")))

    assert said.headline == (
        "Last backup 6 hours ago: written here, and the object store accepted it."
    )
    assert said.caveat == console.BACKUP_NOT_THE_BUCKET
    assert "still in the bucket" in said.caveat
    assert "may only write, so it cannot look" in said.caveat


async def test_where_it_went_is_not_guessed_when_the_record_does_not_say(
    written,
) -> None:
    """A word this panel has no meaning for is neither of the two answers.

    Guessing "offsite" is the bug this field exists to close; guessing "this host" tells an
    operator whose uploads are working that nothing is leaving. The third answer is the
    only true one, and it is a sentence rather than a silence.
    """
    reading = await backups.read(written(record(offsite="maybe")), now=NOW)

    assert reading.destination is backups.Destination.UNKNOWN
    said = console.backup_standing(reading)
    assert said.caveat == console.BACKUP_WHERE_IT_WENT_IS_UNKNOWN
    assert "not claiming an artifact reached one and not claiming none did" in said.caveat


async def test_a_record_with_no_offsite_field_is_not_read_as_a_record(written) -> None:
    """``offsite`` is a key this reader now READS, so the strict half applies to it.

    The distinction M28.6 drew and this keeps: silent about keys it does not read, strict
    about keys it does. A record missing one of those is not this writer's record, and
    "I cannot read this" is recoverable in a way "I assumed where your backups go" is not.
    """
    without = record()
    del without["offsite"]
    assert (await backups.read(written(without), now=NOW)).standing is (
        backups.Standing.UNREADABLE
    )


async def test_every_standing_and_every_destination_closes_with_a_caveat(
    written,
) -> None:
    """Six standings against three destinations, and none of the eighteen inflates.

    Iterates the real enums, so a seventh standing or a fourth destination cannot be
    satisfied by a hand-picked pair — the same reason the sweep above iterates ``Standing``
    rather than a list of strings.
    """
    bodies = {
        backups.Standing.NEVER: record(last_success=None, last_attempt=None),
        backups.Standing.SILENT: record(
            last_success=run(24 * 43), last_attempt=run(24 * 43)
        ),
        backups.Standing.FAILING: record(
            last_failure=run(1, exit_code=3, outcome="not-sent")
        ),
        backups.Standing.FRESH: record(),
    }
    words = {
        "yes": backups.Destination.OFFSITE,
        "no": backups.Destination.THIS_HOST,
        "sometimes": backups.Destination.UNKNOWN,
    }

    seen = set()
    for standing, body in bodies.items():
        for word, destination in words.items():
            reading = await backups.read(written(body | {"offsite": word}), now=NOW)
            assert reading.standing is standing
            assert reading.destination is destination, word

            said = console.backup_standing(reading)
            assert said.caveat == console.BACKUP_CAVEATS[destination]
            # The refusal M28.6 built, said the same way whatever the destination is:
            # naming where a run went may not come at the cost of the claim about what
            # is still there.
            assert "What this does NOT say" in said.caveat
            assert "only thing that proves a backup is a restore" in said.caveat
            whole = f"{said.label or ''} {said.headline} {said.detail} {said.caveat}"
            for never in NEVER_SAID:
                assert never not in whole.lower(), f"{standing}/{word} says {never!r}"
            seen.add((standing, destination))

    # The two standings with no record behind them can only be UNKNOWN, and are swept by
    # ``test_every_standing_says_what_it_does_not_know`` above.
    assert seen == {
        (standing, destination)
        for standing in bodies
        for destination in backups.Destination
    }


# --- "most recent" must point at now (M28.11) ---------------------------------------

async def test_the_most_recent_missed_days_are_the_most_recent_ones(written) -> None:
    """Acceptance 2026-09-23, the second finding.

    Eight missed days, three of them six weeks back and three of them this week, and the
    panel printed the August ones under a label whose entire job is to point at now — in
    the long-outage state, which is the exact case that sentence exists to distinguish.

    THE ORDER ON DISK IS NOT TRUSTED, and that is the fix rather than an agreement with
    the writer. Neither surface sorted, so one of the two labels was wrong whatever order
    the writer used; and the record is a file on a disk, which is where a hand edit goes.
    The reader establishes the order, so the label is true however the list arrives.
    """
    said = await standing_of(
        written(
            record(
                missed_total=8,
                missed_dates=[
                    "2026-08-12",
                    "2026-08-13",
                    "2026-08-14",
                    "2026-09-20",
                    "2026-09-21",
                    "2026-09-22",
                ],
                last_success=run(24 * 43),
                last_attempt=run(24 * 43),
            )
        )
    )

    assert "most recent 2026-09-22, 2026-09-21, 2026-09-20" in said.detail
    assert "2026-08" not in said.detail


@pytest.mark.parametrize(
    "order",
    [
        pytest.param(["2026-09-22", "2026-09-21", "2026-08-14"], id="newest-first"),
        pytest.param(["2026-08-14", "2026-09-21", "2026-09-22"], id="oldest-first"),
        pytest.param(["2026-09-21", "2026-08-14", "2026-09-22"], id="no-order-at-all"),
    ],
)
async def test_the_missed_days_arrive_in_one_order_whatever_the_writer_used(
    written, order: list[str]
) -> None:
    """The invariant belongs to the type, so nothing downstream has to check it.

    These are ``YYYY-MM-DD`` and validated as such before they are sorted, so sorting them
    as text is sorting them as dates.
    """
    reading = await backups.read(written(record(missed_dates=order)), now=NOW)
    assert reading.record.missed_dates == ("2026-09-22", "2026-09-21", "2026-08-14")


# --- a record from the future is not the reassuring state (M28.11) ------------------

async def test_a_record_dated_in_the_future_does_not_read_as_a_fresh_backup(
    client, written
) -> None:
    """Acceptance 2026-09-23, the third finding.

    Clock skew gave "Last backup less than an hour ago" — the quietest sentence on the
    screen — and gave it for ever, because no amount of waiting makes a future timestamp
    pass. The clamp stays: it is the arithmetic, and without it a disagreeing clock could
    turn a stale backup into a fresh one or the reverse. What changes is that the screen
    stops printing an age it cannot stand behind.
    """
    written(record(last_success=live(-30), last_attempt=live(-30)))

    body = (await client.get("/panel/")).text

    assert "less than an hour ago" not in body
    assert "at a time that had not come yet when this was read" in body
    assert ">clock ahead<" in body, "the quiet state is where this hid"
    assert "no age on this screen can be believed" in body


async def test_the_clock_is_said_without_becoming_a_seventh_standing(written) -> None:
    """It is a fault in a clock, not a standing of the backups, so it rides on whichever
    standing was already there — and it does not invent a second colour."""
    said = await standing_of(
        written(
            record(
                last_success=run(19),
                last_failure=run(-30, exit_code=3, outcome="not-sent"),
                last_attempt=run(-30, exit_code=3, outcome="not-sent"),
            )
        )
    )

    assert said.label == "failing", "the standing is unchanged"
    assert "The last one that succeeded was 19 hours ago" in said.headline
    assert "The last run was at a time that had not come yet" in said.detail
    assert "disagree about the time" in said.detail


async def test_a_clock_a_moment_out_is_not_worth_a_sentence(written) -> None:
    """The record is written and read on one machine, so there is normally no skew at all
    — but a network mount or an NTP step is two clocks, and neither should put a standing
    complaint on the front page for the few seconds it lasts."""
    inside = await backups.read(
        written(record(last_success=run(-0.001), last_attempt=run(-0.001))), now=NOW
    )
    assert inside.success_ahead is False
    assert console.backup_standing(inside).loud is False

    outside = await backups.read(
        written(record(last_success=run(-1), last_attempt=run(-1))), now=NOW
    )
    assert outside.success_ahead is True


# --- the schedule this panel cannot see (M28.14) ------------------------------------

def _every_standing_with_a_record() -> dict[backups.Standing, dict]:
    """One record per standing that has one, so a claim can be swept over all four.

    ABSENT and UNREADABLE are left out because neither has a record to read a time out of,
    which is the whole subject here.
    """
    return {
        backups.Standing.NEVER: record(last_success=None, last_attempt=None),
        backups.Standing.SILENT: record(
            last_success=run(24 * 43), last_attempt=run(24 * 43)
        ),
        backups.Standing.FAILING: record(
            last_failure=run(1, exit_code=1, outcome="no-artifact"),
            last_attempt=run(1, exit_code=1, outcome="no-artifact"),
        ),
        backups.Standing.FRESH: record(),
    }


async def test_no_standing_says_a_backup_is_taken_daily(written) -> None:
    """Acceptance round 2, the blocker: the panel promised a schedule it cannot see.

    "The host takes one a day at 04:00 Etc/UTC." was drawn on a stand where
    ``scripts/backup-schedule.sh show`` answered *no hashi backup schedule is installed
    for this account* and the crontab held no entry — and installing it is opt-in, so that
    is the state of every fresh install.

    The record carries ``at`` and ``zone`` because they are what a scheduled run WOULD
    use. They are resolved and written by a run, and a run is what ``make backup`` is, so
    their presence is not evidence that anything is installed to call it. Swept over every
    standing that has a record rather than asserted on one, because the sentence is one
    helper and four branches reach it.
    """
    for standing, body in _every_standing_with_a_record().items():
        reading = await backups.read(written(body), now=NOW)
        assert reading.standing is standing

        said = console.backup_standing(reading)
        assert "takes one a day" not in said.detail, standing
        assert "A run would be due at 04:00 Europe/Belgrade." in said.detail, standing
        assert "if one is installed" in said.detail, standing
        assert (
            "cannot tell you whether anything on that host is taking these backups at all"
            in said.detail
        ), standing


async def test_the_time_and_the_zone_are_still_printed_as_the_host_resolved_them(
    written,
) -> None:
    """Saying less is not saying nothing. The two values stay, and so do their notes."""
    said = await standing_of(
        written(record(at="23:30", zone="UTC", zone_source="unset"))
    )

    assert "A run would be due at 23:30 UTC." in said.detail
    assert "No zone is configured for the schedule" in said.detail


def test_nothing_this_panel_says_about_the_schedule_needs_a_second_source() -> None:
    """The fix is in what the panel may CLAIM from the record, never in a new source.

    A panel that shelled out, read the crontab or reached the host would answer the
    question properly and would also be the one thing this rendering path may not become.
    So the sentence is built here from a ``Reading`` assembled by hand — no file, no
    clock, no settings object — and if composing it ever needed a second source this would
    be the test that could not run.
    """
    said = console.backup_standing(
        backups.Reading(
            path="/var/lib/hashi/backup/last-run.json",
            standing=backups.Standing.FRESH,
            record=backups.Record(
                at="04:00",
                at_source="configured",
                zone="Europe/Belgrade",
                zone_source="configured",
                offsite="yes",
                missed_dates=(),
                missed_total=0,
                last_attempt=None,
                last_success=backups.Run(
                    at=NOW, exit_code=0, outcome="offsite"
                ),
                last_failure=None,
            ),
            destination=backups.Destination.OFFSITE,
            since_success=datetime.timedelta(hours=6),
            since_failure=None,
            failed_since=False,
            missed_recently=0,
            success_ahead=False,
            failure_ahead=False,
        )
    )

    assert "A run would be due at 04:00 Europe/Belgrade." in said.detail


# --- a gap that is still happening is not a quiet fact (M28.14) ---------------------

def days_before(
    count: int, *, ending: float = 1.0, base: datetime.datetime = NOW
) -> list[str]:
    """``count`` consecutive dates, the most recent of them ``ending`` days before ``base``.

    ``base`` is ``NOW`` for the tests that judge at ``NOW`` and the real clock for the ones
    that render a screen — a rendered page reads the wall clock, so dates pinned to a fixed
    constant would age out of the window this measures and the test would fail on a
    calendar rather than on a change (M28.6, ``live()``).
    """
    first = base - datetime.timedelta(days=ending)
    return [
        (first - datetime.timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(count)
    ]


async def test_a_gap_that_is_still_happening_is_not_the_quiet_state(written) -> None:
    """Acceptance round 2: twelve missed days across seven weeks carried no word at all.

    One failed run at 04:00 drew a banner labelled `failing`; twelve days with no backup
    at all drew the muted note, because the last run happened to succeed. Both sentences
    were true and the screen ranked them the wrong way round.

    It is a LABEL and a frame, not a standing and not a colour: ``Standing`` is still
    exactly six and this record is still FRESH.
    """
    reading = await backups.read(
        written(record(missed_total=12, missed_dates=days_before(12))), now=NOW
    )

    assert reading.standing is backups.Standing.FRESH
    assert reading.missed_recently == 12

    said = console.backup_standing(reading)
    assert said.loud is True
    assert said.label == "missed days"
    assert "Days with no backup at all since this record began: 12" in said.detail


async def test_a_gap_that_has_aged_out_goes_quiet_again(written) -> None:
    """And the word clears itself, which is why it is a window and not the total.

    ``missed_total`` never falls, so a screen keyed on it would carry the word for ever on
    a host that has not missed a day since June — and a word that is always there is one
    nobody reads. The days are still stated; only the weight goes away.
    """
    reading = await backups.read(
        written(
            record(
                missed_total=12,
                missed_dates=days_before(12, ending=backups.RECENT_GAP.days + 1),
            )
        ),
        now=NOW,
    )

    assert reading.missed_recently == 0

    said = console.backup_standing(reading)
    assert said.loud is False
    assert said.label is None
    assert "Days with no backup at all since this record began: 12" in said.detail


@pytest.mark.parametrize(
    ("recent", "labelled"),
    [
        pytest.param(console.A_GAP_WORTH_A_LABEL - 1, False, id="under"),
        pytest.param(console.A_GAP_WORTH_A_LABEL, True, id="at"),
    ],
)
async def test_where_a_gap_stops_being_quiet(written, recent: int, labelled: bool) -> None:
    """A box off over a long weekend is not a host that is not being backed up."""
    said = await standing_of(
        written(record(missed_total=recent, missed_dates=days_before(recent)))
    )

    assert said.loud is labelled
    assert said.label == ("missed days" if labelled else None)


async def test_a_clock_from_the_future_is_still_the_thing_that_gets_said(written) -> None:
    """Both can be true at once, and the clock is the larger of the two.

    A record dated ahead means no age on the screen can be believed, which is worse than
    any single number on it. The gap is spelled out in the sentence underneath either way.
    """
    said = await standing_of(
        written(
            record(
                last_success=run(-5),
                last_attempt=run(-5),
                missed_total=12,
                missed_dates=days_before(12),
            )
        )
    )

    assert said.loud is True
    assert said.label == "clock ahead"
    assert "Days with no backup at all since this record began: 12" in said.detail


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
        # One of the three, chosen by where that host sends — never absent, and never the
        # bucket's one on a reading that could not tell whether there is a bucket.
        assert said.caveat == console.BACKUP_CAVEATS[reading.destination]
        assert "What this does NOT say" in said.caveat
        assert "only thing that proves a backup is a restore" in said.caveat
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


async def test_the_rendered_overview_does_not_state_a_daily_backup_as_fact(
    client, written
) -> None:
    """Asserted on the SCREEN, because the screen is what acceptance read.

    The healthy record is the case that was found, and it is the one where the false
    sentence was most reassuring: a recent success above it, and under it a present-tense
    claim that this host takes one every day — on a stand whose crontab was empty.
    """
    written(record(last_success=live(6), last_attempt=live(6)))

    for path in ("/panel/", "/panel/overview/body"):
        body = (await client.get(path)).text
        assert "takes one a day" not in body, path
        assert "A run would be due at 04:00 Europe/Belgrade." in body, path
        assert "if one is installed" in body, path


async def test_a_gap_that_is_still_happening_carries_a_word_on_the_screen(
    client, written
) -> None:
    """The badge, rendered — the frame and the word, not a second colour.

    ``banner-failure`` is reserved for a request the operator just made and that failed
    (docs/decisions.md, 2026-09-10), and a gap is a standing condition, so this uses the
    neutral frame every other standing uses and carries its severity in the word.
    """
    written(
        record(
            last_success=live(6),
            last_attempt=live(6),
            missed_total=12,
            missed_dates=days_before(12, base=datetime.datetime.now(datetime.UTC)),
        )
    )

    body = (await client.get("/panel/")).text

    assert ">missed days<" in body
    assert "Days with no backup at all since this record began: 12" in body
    assert "banner-failure" not in body


async def test_the_overview_says_so_when_nothing_has_been_recorded(client) -> None:
    """No file at all — the empty mount, which is what a fresh install really has."""
    body = (await client.get("/panel/")).text

    assert "No backup has ever been recorded on this host." in body
    # With no record there is nothing to say where this host sends, so the caveat is the
    # one that claims neither — not the bucket's, which would imply there is a bucket.
    assert console.BACKUP_WHERE_IT_WENT_IS_UNKNOWN in body
    assert console.BACKUP_NOT_THE_BUCKET not in body


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


# --- and none of it records who connected to what (M28.7) ---------------------------

# Planted in every damaged record below, and looked for in every log line and every
# sentence that comes back. It stands in for A BYTE OF THE FILE reaching a log by any
# route at all — not for a nickname the record could really hold, because it could not:
# the writer's key set is closed and the three values it takes out of the env file are
# charset-limited to 64 characters (M28.5). What this guards is the OTHER direction, where
# a future `logger.warning(..., data)`, or an exception rendered with `str()` instead of
# with its type, starts putting the contents of a file on a read-only mount into the
# container's log — which `make logs` keeps and which is a persistent record of a file
# this panel has no business quoting.
NOT_FOR_A_LOG = "PLANTED-NICKNAME-AND-192.0.2.7"

DISAPPOINTING = {
    "not json at all": NOT_FOR_A_LOG.encode(),
    "json, but not an object": json.dumps(NOT_FOR_A_LOG).encode(),
    "a string that never ends": b'{"schema": 1, "at": "' + NOT_FOR_A_LOG.encode(),
    "a control character in a value": b'{"schema": 1, "at": "' + NOT_FOR_A_LOG.encode() + b'\n"}',
    "a schema this reader has never seen": json.dumps(
        {"schema": 99, "at": NOT_FOR_A_LOG}
    ).encode(),
    "a key of the wrong kind": json.dumps(
        {"schema": 1, "at": [NOT_FOR_A_LOG], "missed_dates": []}
    ).encode(),
    "a missed day that is not a day": json.dumps(
        record(missed_dates=[NOT_FOR_A_LOG])
    ).encode(),
    "a timestamp that is not one": json.dumps(
        record(last_success={"at": NOT_FOR_A_LOG, "due_date": "2026-09-23",
                             "exit_code": 0, "outcome": "offsite"})
    ).encode(),
    "bytes that are not utf-8": b'{"schema": 1, "at": "\xff\xfe' + NOT_FOR_A_LOG.encode() + b'"}',
    "a file far too big to be the record": b'{"x": "' + NOT_FOR_A_LOG.encode() * 10_000 + b'"}',
}


@pytest.mark.parametrize("why", sorted(DISAPPOINTING))
async def test_no_way_of_disappointing_this_reader_puts_the_file_into_a_log(
    backup_record: pathlib.Path, caplog, why: str
) -> None:
    """M28.7. Every branch that gives up on the record, and none of them quotes it.

    Ten ways in, one rule out: the log line carries the PATH and the failure's KIND, and
    never a byte of what was at that path. Parametrised rather than written as one sweep so
    that a branch which starts talking fails on its own name — and driven through the real
    ``read`` rather than through the private helpers, because the two places this could go
    wrong are the ``except`` clauses and they are only reachable from outside.

    The composed sentence is checked as well as the log. ``UNREADABLE`` names the file it
    could not read, which is right — an operator has to be told which file to go and look
    at — and that is the whole of what it may repeat about it.
    """
    backup_record.parent.mkdir(parents=True, exist_ok=True)
    backup_record.write_bytes(DISAPPOINTING[why])

    with caplog.at_level(logging.DEBUG, logger="control.app.services.backups"):
        reading = await backups.read(backup_record, now=NOW)
    said = console.backup_standing(reading)

    assert reading.standing is backups.Standing.UNREADABLE, why
    assert caplog.text.strip(), f"{why}: gave up on the record without saying so anywhere"
    assert NOT_FOR_A_LOG not in caplog.text, f"{why}: the record's contents reached a log"
    assert str(backup_record) in caplog.text, f"{why}: the log line does not say which file"
    assert NOT_FOR_A_LOG not in said.headline + said.detail + said.label, (
        f"{why}: the record's contents reached the screen"
    )


async def test_the_reading_that_reaches_a_screen_carries_no_request_and_no_person(
    written,
) -> None:
    """What a ``Reading`` is allowed to be made of, checked as a whole rather than field by field.

    A subscription token is a bearer credential in a URL path (CLAUDE.md), so the thing to
    be sure of about a value that crosses from a file into a rendered page is not only that
    it is harmless today: it is that the set of values is small, named and fixed. Every
    string in a reading is either the record's own path or one of M28.5's closed fields,
    and this walks the dataclass to say so — a sixteenth field added here would have to be
    justified against this list rather than arriving with a template change.
    """
    reading = await backups.read(written(record()), now=NOW)

    assert dataclasses.fields(backups.Reading) and [
        field.name for field in dataclasses.fields(backups.Reading)
    ] == [
        "path",
        "standing",
        "record",
        "destination",
        "since_success",
        "since_failure",
        "failed_since",
        "missed_recently",
        "success_ahead",
        "failure_ahead",
    ]
    assert [field.name for field in dataclasses.fields(backups.Record)] == [
        "at", "at_source", "zone", "zone_source", "offsite", "missed_dates",
        "missed_total", "last_attempt", "last_success", "last_failure",
    ]
    assert [field.name for field in dataclasses.fields(backups.Run)] == [
        "at", "exit_code", "outcome",
    ]
    # Nothing in the reading is a URL, and nothing in it came out of a request.
    assert "/sub/" not in repr(reading) and "http" not in repr(reading)


def test_this_module_prints_nothing_and_logs_through_one_logger() -> None:
    """The zone's rule, checked on the one module in it that reads a file off a mount.

    ``print`` would go to the container's stdout, which is the same journal as everything
    else and is kept — and a module that reads a file is where a debugging ``print`` gets
    left behind. The logger is asserted to be the module's own so that the level set in
    ``main.configure_logging`` applies to it: a logger acquired by another name would not
    be covered by the two lines that silence uvicorn's access log.
    """
    source = pathlib.Path(backups.__file__).read_text()

    assert "print(" not in source
    assert source.count("logging.getLogger(") == 1
    assert "logger = logging.getLogger(__name__)" in source
    # ...and no log call anywhere in the module takes the bytes or the parsed object as an
    # argument. Read off the syntax tree rather than out of a regex: the point is which
    # NAMES are handed to the logger, and a text search answers that question about the
    # prose around it as well.
    tree = ast.parse(source)
    carriers = {"data", "raw", "value", "handle", "record"}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue
        named = {
            inner.id for argument in node.args for inner in ast.walk(argument)
            if isinstance(inner, ast.Name)
        }
        assert not named & carriers, (
            f"a log call on line {node.lineno} is handed {sorted(named & carriers)} — the "
            "contents of the record, which is a file this module reads and never quotes"
        )
