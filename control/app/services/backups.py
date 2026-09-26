"""What this host wrote down about its own backups — read, never written.

WHAT: reads the one record ``scripts/backup-run.sh`` leaves after every run and reduces
      it to the few facts a screen needs: when a backup last succeeded, whether one has
      failed since, and whether anything has been trying at all.
WHY:  the dangerous state is not "the backup failed", it is "the backup has been failing
      for six weeks and nothing said so". That record is the only account of it that
      exists on this machine, and until M28.6 nothing read it unless the operator went to
      the host and typed ``make backup-status`` — which is exactly what an operator who
      has stopped thinking about backups does not do.

      AND THE SENTENCE THIS MODULE MUST NOT INFLATE. What comes out of here is what THIS
      HOST recorded about its own runs. It is not a fact about the object store: the
      credential the upload uses may only write, so it cannot look, there is no read path
      in this product at all (M28.3), and nothing in this repository asserts the bucket's
      retention or ever can (M28.4). A successful run means the store received exactly
      those bytes and accepted them, and says nothing about a minute later. That is why
      this module composes no prose — every sentence built from a ``Reading`` carries the
      caveat for where that host sends, and a green tick on a screen is precisely how that
      distinction would otherwise be lost.

      AND THE OTHER HALF OF IT, which M28.11 found inverted: whether a run reached a store
      AT ALL is something this host does know, and until then the panel threw it away.
      ``HASHI_BACKUP_ENABLED=0`` is the shipped default, so the screen that talked about a
      bucket was, by default, talking about a bucket that does not exist. The two claims
      are different and both are said now: where the run went, which this host recorded,
      and whether the artifact is still there, which nothing here will ever know.

      AND THE SAME MISTAKE FROM THE OTHER SIDE, which is M28.20. Every other correction in
      this milestone was a channel asserting more than the record licensed; this one was
      this module declining to read a field the record states plainly. ``due_date`` was
      dropped as repeating what ``last_attempt`` already said — it does not — so a record
      naming a day this host had not reached went past here without a word, and the panel
      answered with the quietest sentence it has. What is read now is one bit, and the
      sentence composed from it stays inside what one file can support: which day the
      record says it is owed for, against the clock this reader already holds. What the
      SCHEDULE will do about that is not asked here and may not be guessed at — see
      ``Reading.due_ahead``, and ``DUE_AHEAD_GRACE`` for the half of the shape this
      deliberately still cannot see.
HOW:  the file is a bind mount, read-only, so there is no writer here and there is not
      going to be one. It is parsed STRICTLY and every way it can disappoint degrades to
      one of two answers, ``ABSENT`` or ``UNREADABLE``: a mount that arrived empty, a
      shell script that wrote the file badly, a hand edit, or a path pointing at
      something enormous must not be able to make this panel claim anything about
      backups, and must not be able to raise inside the request that draws a screen.
      Nothing in here raises — the return value carries the bad news.

      The record's shape is M28.5's and is settled (docs/tracker/M28/step-notes.md): one
      key per line so a shell with no JSON parser can read it, which is still ordinary
      JSON to this reader. It is written atomically — a temporary file and a rename — so
      a half-written record should not be observable at all; it is handled anyway,
      because a file on a disk is where a hand edit goes.
"""

import asyncio
import dataclasses
import datetime
import enum
import json
import logging
import os
import pathlib
import re
import stat

logger = logging.getLogger(__name__)

# The record schema this code understands. The writer stamps ``"schema": 1`` and the key
# set behind that number is closed and asserted by a test in the infra zone. A record
# claiming a number this code has never seen is read as UNREADABLE rather than guessed
# at: the panel saying "I cannot read this" is recoverable, and the panel reporting a
# success it inferred from a layout it does not know is not.
RECORD_SCHEMA = 1

# The most of the file that is ever read. The real record is well under a kilobyte; this
# is a ceiling on what a wrong path — a mount pointing somewhere else, a log file — can
# pull into memory on every render of a screen. Over it, the file is not the record.
MOST_OF_A_RECORD = 64 * 1024

# The longest any single string out of the record may be. Every one of them reaches a
# screen, and a zone name of ten thousand characters is not a zone name. Autoescaping
# makes it safe; this makes it readable.
LONGEST_VALUE = 200

# How long the request that draws a screen will wait for the filesystem before giving up
# on it. Two seconds: a kilobyte off a local bind mount is microseconds, so anything near
# this ceiling is not a slow read, it is a mount that has stopped answering.
#
# WHAT IT FREES AND WHAT IT DOES NOT, because the next reader will assume it is the whole
# fix and it is not. It frees the REQUEST: the coroutine stops waiting and the screen says
# it could not read the record, which is true. It does NOT free the THREAD — nothing in
# Python can reclaim a thread blocked in a syscall, so a filesystem that never answers
# costs one slot of the default executor for the life of the process, and an interpreter
# shutdown that drains that executor will itself wait on it. That is a real residual and
# it is written down rather than papered over.
#
# Why the shared default executor anyway, having said that: a private pool moves the leak
# without closing it and adds a problem of its own — its threads are non-daemon and are
# joined at interpreter exit, so an isolated pool turns a leaked thread into a hang on
# shutdown. What actually shrinks the exposure is one file over: the open is non-blocking
# and refuses anything that is not a regular file, so the only way left into this state is
# a mount that has died, which is a fault on the host rather than a shape anything can
# plant at the path.
READ_CEILING_SECONDS = 2.0

# How old the last SUCCESS may be before this stops being recent. The schedule takes one
# backup a day, so two days is a whole appointed time missed plus a day of slack — long
# enough that a box off for an evening is not an alarm, short enough that nothing can go
# quiet for a week without saying so.
#
# It is the age of the last SUCCESS and deliberately not "has the last run failed": a
# schedule that was uninstalled, or a host whose cron stopped, produces no failure at all
# — nothing runs, nothing fails, and the record simply stops moving. That is the
# six-weeks-of-silence case, and keying on failures alone would miss exactly it.
SUCCESS_STALE_AFTER = datetime.timedelta(days=2)

# The writer's timestamp format, UTC, as ``date -u +%Y-%m-%dT%H:%M:%SZ`` produces it.
TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"

# A missed day, as the writer records it. Checked rather than trusted because these are
# printed on a screen.
A_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# How far ahead of this process's clock a record's timestamp may be before it is reported
# as coming from the future rather than quietly treated as "just now".
#
# There is normally no skew at all to absorb: the schedule writes the file and this reads
# it through a bind mount, so both sit on one kernel's clock, and the writer truncates to
# whole seconds, which can only move a stamp backwards. The grace is for the two cases
# where the two clocks really are two — a record delivered over a network mount from the
# machine that takes the backups, and an NTP step landing between the write and the read —
# so that neither puts a standing sentence about a broken clock on the front page for the
# few seconds it lasts. Anything beyond a minute is not skew, it is a host that has the
# wrong time, and that is worth a sentence because it makes every age on this screen wrong.
CLOCK_AHEAD_GRACE = datetime.timedelta(minutes=1)

# The same question for the record's DUE DATE, which is a calendar day rather than a moment
# and so cannot be graced by a minute. M28.20: until then this module read the two run
# timestamps and never the due date, so a record naming a day this host has not reached —
# ``"due_date": "2099-01-01"`` — drew the quietest screen this feature has, permanently.
#
# WHY A WHOLE DAY OF GRACE, AND WHY IT IS NOT SLACK. The due date is resolved by the writer
# in the SCHEDULE'S zone (``Record.zone``), and this reader has one clock, in UTC. The
# inhabited zones run from UTC−12 to UTC+14, so a due date resolved honestly in any of them
# is at most one day either side of this reader's own date, and a comparison without this
# grace would put a complaint about a clock on the front page of a host that was backing
# itself up perfectly.
#
# HOW OFTEN, MEASURED, BECAUSE THE QUANTIFIER KEPT COMING OUT WRONG. It is not every host
# east of UTC and it is not a standing banner. ``scripts/backup-run.sh::due_date`` names
# the local day, less one before the configured hour has come round, so the hours of the
# day at which a zero-grace comparison would fire are ``floor(offset − at)``, never below
# zero, with both in hours: exact for the half-hour and quarter-hour zones too, where
# rounding either term separately is not — UTC+5:30 at 04:00 fires for 1 hour and not 1.5,
# UTC+12:45 for 8, UTC+3:30 for none. Swept over every whole offset from UTC−12 to UTC+14,
# and over those fractional zones, against the real ``date`` and the real zone database.
# With the schedule at 04:00:
# UTC+0 through UTC+4 would never be flagged at all, UTC+9 for 5 hours of every 24, UTC+12
# for 8, UTC+14 for 10, and nowhere west of UTC ever. The hour is configuration, so it
# moves every one of those numbers — the same sweep at 00:30 gives UTC+14 thirteen hours
# and reaches as far west as UTC+2, and at 12:00 only UTC+13 and UTC+14 are left with
# anything, one hour and two. What survives every one of those numbers is the argument for
# the grace, because on the hosts it does reach it fires every day — and a banner that
# appears daily on a healthy host is the ``RECENT_GAP`` mistake in a new place: it becomes
# furniture and stops being read.
#
# So this is not a tolerance for skew, it is the width of the calendar. Over it, the
# record names a day that has not begun anywhere on Earth, and NO timezone explains it —
# which is the whole of what this reader is entitled to conclude from one file.
#
# WHAT THAT LEAVES UNSEEN, because it is the state the plan reproduced organically and it
# is not caught here. Moving ``HASHI_BACKUP_TZ`` west across the date line leaves a record
# due NO MORE THAN A DAY ahead of this reader — zero or one, depending on the hour and on
# ``HASHI_BACKUP_AT`` — which is the same shape a host legitimately scheduled far to the
# east writes whenever the two disagree at all: at 04:00 a due date resolved at UTC+14
# equals this reader's UTC date for 14 hours of the 24 and is one day ahead for the other
# 10. Either way it is under the grace, so this file never sees it. The two are
# indistinguishable from this file: telling them apart needs the zone the host is set to
# NOW, and that lives in ``.env`` — which this panel may not open — while the record's own
# ``zone`` is the one the LAST RUN used and so is the very thing that changed.
# ``scripts/backup-run.sh due`` reads the configured zone and does catch it; this reads one
# file and says nothing about it rather
# than guessing. Resolving ``Record.zone`` here instead was considered and refused on three
# counts: it is filesystem I/O off a string from a disk file, on the path that draws a
# screen; it is a second copy of the schedule's own ``TZ=<zone> date +%F``, which is the one
# thing this panel may not grow; and it needs a zone database. The base image happens to
# carry one — measured, ``zoneinfo.ZoneInfo("Pacific/Kiritimati")`` resolves inside the
# control container — and NOTHING IN THIS REPOSITORY ASSERTS THAT IT DOES, so the failure
# mode is the silent one: a rebase drops the feature with every test still green.
DUE_AHEAD_GRACE = datetime.timedelta(days=1)

# How far back a day with no backup still counts as part of what is happening now.
#
# ``missed_total`` is cumulative and never falls, which is right — it is the record's whole
# history — and is exactly why it cannot be the measure of whether a gap is current. A host
# that was off for a fortnight in June carries fourteen for ever, and a screen that changes
# its weight on that number changes it for ever too, which is how a warning becomes
# furniture. What a reader can ask instead is how many of the days the record still NAMES
# fall inside a window ending now, and that number falls back to nothing as the days age
# out.
#
# Eight weeks, because a shorter window would have missed the seven acceptance was
# looking at. It is longer than the thirty dates the writer keeps (M28.5), so this can
# UNDERCOUNT — and the undercount is harmless in the one direction that matters: the dates
# kept are the newest, so the count only ever comes out low, and it can only come out low
# on a host that has missed more than thirty days, which is far past any number a screen
# downstream calls a lot. It cannot hide a gap; it can only fail to exaggerate one.
RECENT_GAP = datetime.timedelta(weeks=8)


class Standing(enum.StrEnum):
    """Where the backups on this host stand, in the only six answers there are.

    Ordered by how much the operator has to do about it, and the split between the last
    three is the whole judgement in this module:

    * ``ABSENT`` — no record at all. On a control plane that does not run beside the
      backups this is the normal case and means "nothing recorded", NOT "broken".
    * ``UNREADABLE`` — a file is there and it is not the record. Nothing is assumed.
    * ``NEVER`` — a record, and no backup has ever succeeded on this host.
    * ``SILENT`` — one succeeded once, it is stale, and nothing has failed since. Nothing
      has been trying: the schedule is gone, or the host it was installed on is.
    * ``FAILING`` — a run has failed and none has succeeded since. Says nothing on its
      own about how bad it is — one blip and six weeks are both this — so the age of the
      last success travels beside it and is what the screen leads with.
    * ``FRESH`` — one succeeded recently and nothing has failed since it.
    """

    ABSENT = "absent"
    UNREADABLE = "unreadable"
    NEVER = "never"
    SILENT = "silent"
    FAILING = "failing"
    FRESH = "fresh"


class Destination(enum.StrEnum):
    """Where this host sends its backups — which is not the same question as how a run went.

    THE DISTINCTION THE PANEL GOT WRONG UNTIL M28.11, and it is the milestone's own
    premise inverted. ``HASHI_BACKUP_ENABLED=0`` is the shipped default: the artifact is
    written and stays on the machine, which is a supported mode and not a fault. The
    record says so in its own ``offsite`` field, the reader dropped that field on the
    grounds that every run's ``outcome`` already carried it, and so two hosts — one
    uploading, one sending nothing anywhere — drew byte-identical screens, both closing
    with a caveat about a bucket one of them does not have. A caveat about a bucket, on a
    host with no bucket, is worse than saying nothing.

    The two are different in TIME as well as in kind, which is why both are kept. A run's
    ``outcome`` says what happened to THAT artifact, whenever it was taken. This says what
    the host is set to do NOW, and the operator may have changed it since — so the two
    disagreeing is not a damaged record, it is a switch that was thrown between two runs.

    * ``OFFSITE`` — the record says the upload is on.
    * ``THIS_HOST`` — the record says it is off. Nothing has been sent anywhere.
    * ``UNKNOWN`` — there is no record, or it holds a word this panel has no meaning for.
      Never collapsed into either of the other two: guessing "offsite" would reinstate the
      bug, and guessing "this host" would deny an upload that may well be happening.
    """

    OFFSITE = "offsite"
    THIS_HOST = "this-host"
    UNKNOWN = "unknown"


# The writer's own two words for its ``offsite`` field, and the only two it emits. Anything
# else is UNKNOWN rather than _Malformed, for ``outcome``'s reason one field over: a later
# writer gaining a third word must not be able to turn this screen into "the record is
# unreadable", and "this panel cannot tell where these go" is an answer it can say out loud.
_DESTINATIONS = {
    "yes": Destination.OFFSITE,
    "no": Destination.THIS_HOST,
}


@dataclasses.dataclass(frozen=True, slots=True)
class Run:
    """One run of the backup, as the record remembers it.

    ``outcome`` is the writer's own word for what happened — ``offsite``,
    ``on-this-host-only``, ``not-sent``, ``no-artifact``, ``refused`` — derived there from
    the exit code and whether the upload is switched on, never by parsing any output. It
    is kept as the word rather than as a judgement: what it MEANS is a sentence, and
    sentences are composed in ``services/console.py`` like every other thing this panel
    says.

    The record carries a ``due_date`` on each entry as well. THAT one is still not read:
    what a per-run due date answers — which day's backup this particular run was for — is
    the scheduler's own business, and a field with no reader is a field that quietly goes
    wrong. The record's TOP-LEVEL ``due_date`` is a different field answering a different
    question, and since M28.20 it is read — see ``Record.due_date``.
    """

    at: datetime.datetime
    exit_code: int
    outcome: str


@dataclasses.dataclass(frozen=True, slots=True)
class Record:
    """The record's contents, as far as anything here has a use for them.

    A deliberate subset of M28.5's fifteen keys. ``schema`` is checked and not kept,
    ``written_at`` says what ``last_attempt`` already says, and ``attempts`` and
    ``retry_not_before`` are the scheduler's own working state. A field nothing reads is a
    field nobody notices has gone wrong, so they are not carried.

    ``due_date`` WAS ON THAT LIST, on the same grounds — it was said to repeat what
    ``last_attempt`` already carried — and that was the M28.20 defect. It does not repeat
    it: ``last_attempt`` says when something last ran, and this says which day the record
    considers the backup owed for, so a record can hold a run from an hour ago beside a day
    no clock has reached. Nothing here noticed that, and the panel drew the quietest screen
    it has over it.

    ``offsite`` USED TO BE ON THAT LIST and that was the M28.11 defect — see
    ``Destination``. The reason given for dropping it was that every run's ``outcome``
    already carried it, which is true only while the outcome is one of the five words this
    panel knows; a sixth word is named verbatim, and a screen composed from nothing but
    that word says nothing at all about whether the artifact left the machine.
    """

    # The appointed time and the zone it is in, both exactly as the host resolved them.
    # ``zone`` is an IANA NAME and is displayed as one: it is never turned into a country,
    # a flag or an offset, here or anywhere downstream.
    at: str
    at_source: str
    zone: str
    zone_source: str
    # The host's own word for whether the upload is switched on, kept verbatim. What it
    # MEANS is ``Reading.destination``; the raw word stays here so nothing is lost on the
    # way to a screen that may have to print a word this code does not recognise.
    offsite: str
    # The day the record says the backup is owed for, ``YYYY-MM-DD`` as the writer resolved
    # it IN THE SCHEDULE'S ZONE — which is why ``DUE_AHEAD_GRACE`` is a day wide.
    #
    # READ LENIENTLY, AND THAT IS LOAD-BEARING. Empty string for absent, ``null``, a
    # non-string or anything that is not a date, and never ``_Malformed``. The shell's
    # reader validates neither this field nor ``attempts`` nor ``retry_not_before``
    # (M28.18, and deliberately, because refusing what the panel reads happily is the
    # two-channel disagreement arriving from the strict side) — so refusing a file HERE for
    # this field would open the same seam from the other end: a record ``make
    # backup-status`` prints in full and the panel calls unreadable. A due date this reader
    # cannot make sense of costs it one sentence it would otherwise have said, which is the
    # direction every other degradation in this module goes.
    due_date: str
    # Days the schedule noticed had no backup at all, and the cumulative count of them.
    # Both survive the run that ends a gap, so they are history rather than an alarm.
    #
    # NEWEST FIRST, AND SORTED HERE RATHER THAN TRUSTED. The panel says "most recent" over
    # the first few of these, and until M28.11 it said it over whatever order the writer
    # happened to use — which put a label meaning "now" on three days in August while a
    # gap was running. Nothing downstream can check an order, and this file is on a disk
    # where a hand edit goes, so the order is established here and the invariant belongs
    # to the type rather than to an agreement between two zones. These are
    # ``YYYY-MM-DD`` and validated as such before they get here, so sorting them as text
    # is sorting them as dates.
    missed_dates: tuple[str, ...]
    missed_total: int
    last_attempt: Run | None
    last_success: Run | None
    last_failure: Run | None


@dataclasses.dataclass(frozen=True, slots=True)
class Reading:
    """What this control plane can say about the backups, and how sure it is.

    ``since_success`` and ``since_failure`` are ages rather than timestamps on purpose:
    the clock is read exactly once, here, so everything composed from this is a pure
    function of the reading. A screen that computed "43 days ago" for itself would be a
    second place the answer comes from.
    """

    # Where it was read from, so the sentence can name the file rather than describe it.
    path: str
    standing: Standing
    # ``None`` for ABSENT and UNREADABLE, and those are the only two.
    record: Record | None
    # Where this host sends its backups, as the record says it does today. ``UNKNOWN``
    # whenever there is no record to ask, which is exactly the two standings above.
    destination: Destination
    # How long ago the last successful run was, ``None`` if there has never been one.
    since_success: datetime.timedelta | None
    # ...and the last failed one, on the same terms.
    since_failure: datetime.timedelta | None
    # Whether a run has failed since the last success — M28.5's own test for it, which is
    # ``last_failure.at > last_success.at`` and is true of a failure with no success at
    # all beside it.
    failed_since: bool
    # How many of the days the record names as having no backup at all fall inside
    # ``RECENT_GAP`` of the moment this was read — that is, how much of the gap is now
    # rather than history. Counted here because this is where the clock is read, and
    # counted at all because ``missed_total`` cannot answer it: see ``RECENT_GAP``.
    #
    # It is a COUNT and not a verdict. What is a lot of days is a question about how loud a
    # screen should be, which belongs beside the sentences in ``services/console.py`` with
    # every other decision of that kind, and not in the module that reads a file.
    missed_recently: int
    # Whether that run is stamped AHEAD of the clock this was read against, per run,
    # because a screen prints the two ages in separate sentences and only one of them may
    # be the impossible one.
    #
    # The ages above stay CLAMPED — arithmetic on a negative age is how a clock that
    # disagrees turns a stale backup into a fresh one or the reverse, and M28.6 was right
    # about that. These are what stops the clamp from also being a lie: without them the
    # panel reported "last backup less than an hour ago" for a record dated next week, for
    # ever, which is the most reassuring sentence on the screen said about the one state
    # nobody can get out of by waiting.
    success_ahead: bool
    failure_ahead: bool
    # ...and whether the record's DUE DATE is a day this reader's own clock has not reached
    # and no timezone can account for. The third part of the same finding and kept apart
    # from the two above for the reason they are kept apart from each other: the three cost
    # different things, so the screen says three different sentences and only the ones that
    # are true of this record.
    #
    # It is NOT a seventh standing and it does not move ``standing`` at all. The six are
    # about the backups — one succeeded, one failed, none has happened — and this is about
    # a date the record and this reader cannot reconcile, which rides on whichever standing
    # was already there exactly as the run-timestamp halves do.
    #
    # AND IT LICENSES NOTHING ABOUT THE SCHEDULE. A due date ahead used to stop the
    # schedule dead; since M28.19 it does not — the next tick takes a backup and the run
    # rewrites the date, whether or not the dump succeeds. So nothing composed from this
    # may say the host has stopped backing up, and nothing composed from it may work out
    # when the next backup is due either: that is the schedule's reasoning, it lives in
    # ``scripts/backup-run.sh`` where it can be called rather than restated, and a second
    # copy of it on a screen is this milestone's own defect in a new costume.
    due_ahead: bool


class _Malformed(Exception):
    """This is not the record ``scripts/backup-run.sh`` writes.

    Private, and it never leaves this module: ``read`` catches it and answers
    ``UNREADABLE``. A domain exception (``errors.py``) would be wrong — nothing refused
    the operator anything, and a screen must still draw with a damaged file on disk.
    """


def _read_bytes(path: pathlib.Path) -> tuple[bool, bytes | None]:
    """Whether a file is there, and its first ``MOST_OF_A_RECORD + 1`` bytes.

    Two answers rather than an exception, because the caller has to tell "no record" from
    "a record this process cannot read" and they are different sentences. Everything the
    filesystem can raise is one or the other: a missing file, a missing mount point and an
    empty bind mount are all absence; a directory, a permission, a dead mount and an I/O
    error are all presence with nothing legible in it.

    ``O_NONBLOCK``, AND A CHECK THAT THIS IS A REGULAR FILE BEFORE A BYTE IS READ. Both
    are about one shape: a FIFO at the record path. ``open()`` on a FIFO with no writer
    does not fail and is not slow — it blocks in the kernel and **never returns**, and a
    Python thread stuck in that syscall cannot be killed, cancelled or reclaimed by
    anything short of restarting the process. ``O_RDONLY | O_NONBLOCK`` is the documented
    way to ask for a FIFO without agreeing to wait: the open returns at once. The
    ``S_ISREG`` test then refuses it — a FIFO, a socket, a device or a directory at this
    path is not the record, so there is nothing to read out of it and it never gets read.

    Chosen over timing the trap out, which was the other candidate: a ceiling frees the
    REQUEST and leaves the thread gone for the life of the process, so a path an attacker
    (or a careless `mkfifo`) controls would leak one executor slot per page draw. This
    never enters the blocking state at all. The ceiling in ``read`` stays as well, because
    it covers the case ``O_NONBLOCK`` cannot: a dead NFS or fuse mount blocks in the
    filesystem layer, where the flag has no effect.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return False, None
    except OSError as exc:
        # The path and the failure's KIND, never the file's contents — this is a log line
        # and the rule for every log line in this zone is that nothing of a payload goes
        # into one. The record holds nothing about a person either way (M28.5 asserts it),
        # which is not a reason to start printing files into logs.
        logger.warning(
            "the backup record at %s could not be opened (%s)", path, type(exc).__name__
        )
        return True, None

    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            logger.warning(
                "the backup record at %s is not a regular file, so it is not the record",
                path,
            )
            return True, None
        # ``closefd=False`` — the descriptor is this function's and is closed once, below.
        with open(descriptor, "rb", closefd=False) as handle:
            return True, handle.read(MOST_OF_A_RECORD + 1)
    except OSError as exc:
        logger.warning(
            "the backup record at %s could not be read (%s)", path, type(exc).__name__
        )
        return True, None
    finally:
        os.close(descriptor)


def _text(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or len(value) > LONGEST_VALUE:
        raise _Malformed(key)
    return value


def _whole(raw: dict, key: str) -> int:
    value = raw.get(key)
    # ``bool`` is an ``int`` in Python and ``True`` is not a count. Excluded explicitly
    # rather than relied upon to never appear.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _Malformed(key)
    return value


def _a_date(raw: dict, key: str) -> str:
    """A ``YYYY-MM-DD`` field as the writer wrote it, or ``""`` for anything else.

    The one field read this way, and ``Record.due_date`` says why it is not ``_Malformed``:
    the shell does not validate it either, and a panel stricter than the command line about
    whether a record is readable at all is the two-channel disagreement this milestone is
    made of.

    The shape and not the calendar, exactly as ``missed_dates`` is checked: ``2026-13-45``
    is kept, because what this reader does with the value is compare it as text against
    another ``YYYY-MM-DD`` and print it back, and an absurd date in the record is the
    record's own claim rather than something to be corrected on the way to a screen.
    """
    value = raw.get(key)
    return value if isinstance(value, str) and A_DATE.match(value) else ""


def _moment(value: object) -> datetime.datetime:
    if not isinstance(value, str):
        raise _Malformed("timestamp")
    try:
        return datetime.datetime.strptime(value, TIMESTAMP).replace(
            tzinfo=datetime.UTC
        )
    except ValueError as exc:
        raise _Malformed("timestamp") from exc


def _run(raw: dict, key: str) -> Run | None:
    """One of the three nested entries, or ``None`` where that thing has never happened.

    ``null`` and an absent entry are the same answer, and both differ from an entry whose
    fields are wrong: "no backup has ever succeeded here" is a statement the record is
    entitled to make, and "this line is not a run" is not. The second raises, so the whole
    reading becomes UNREADABLE rather than being reported as a host that has never had a
    successful backup — which would be the same alarm for a completely different reason.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _Malformed(key)
    exit_code = value.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise _Malformed(key)
    return Run(
        at=_moment(value.get("at")),
        exit_code=exit_code,
        outcome=_text(value, "outcome"),
    )


def _parse(data: bytes) -> Record:
    """The bytes on disk as a ``Record``, or ``_Malformed``.

    Strict about the shape of what it reads and silent about keys it does not know: a
    later version of the writer adding a sixteenth key must not make this panel go
    unreadable, while a key this code DOES read arriving as the wrong kind of thing must,
    because that is the case where a wrong answer would otherwise be composed from it.

    ONE KEY IT READS IS DELIBERATELY EXEMPT, and it is not a gap to be closed: ``due_date``
    goes through ``_a_date``, which answers ``""`` for absent, ``null``, a non-string or a
    string that is not ``YYYY-MM-DD``, and never ``_Malformed``. ``_a_date`` says why —
    ``scripts/lib/backup-record.sh`` does not validate that field either, so a panel that
    refused the file would be the two-channel disagreement M28.18 closed, arriving from
    the strict side. Anyone tightening the rule above onto it reopens that.
    """
    raw = json.loads(data.decode("utf-8"))
    if not isinstance(raw, dict):
        raise _Malformed("record")
    if raw.get("schema") != RECORD_SCHEMA:
        raise _Malformed("schema")

    dates = raw.get("missed_dates")
    if not isinstance(dates, list) or not all(
        isinstance(entry, str) and A_DATE.match(entry) for entry in dates
    ):
        raise _Malformed("missed_dates")

    return Record(
        at=_text(raw, "at"),
        at_source=_text(raw, "at_source"),
        zone=_text(raw, "zone"),
        zone_source=_text(raw, "zone_source"),
        offsite=_text(raw, "offsite"),
        due_date=_a_date(raw, "due_date"),
        # Newest first, whatever order the writer used — see ``Record.missed_dates``.
        missed_dates=tuple(sorted(dates, reverse=True)),
        missed_total=_whole(raw, "missed_total"),
        last_attempt=_run(raw, "last_attempt"),
        last_success=_run(raw, "last_success"),
        last_failure=_run(raw, "last_failure"),
    )


def _judge(record: Record, now: datetime.datetime, path: pathlib.Path) -> Reading:
    """Which of the four "there is a record" standings this one is.

    The order matters and is the answer to "what counts as alarming". Never having
    succeeded comes first, because no amount of recent activity redeems it. Then the age
    of the last success, because that is the measure a host which stopped running the
    schedule at all still moves. A failure since the last success comes last, and on its
    own it is a blip — one run failing at 04:00 with a success the morning before is
    ``FAILING`` exactly as six weeks of failures are, and what separates them on screen is
    the age travelling beside it, never a louder colour.
    """
    success = record.last_success
    failure = record.last_failure
    failed_since = failure is not None and (success is None or failure.at > success.at)

    since_success = None if success is None else _age(success.at, now)
    since_failure = None if failure is None else _age(failure.at, now)

    if since_success is None:
        standing = Standing.NEVER
    elif since_success >= SUCCESS_STALE_AFTER:
        standing = Standing.FAILING if failed_since else Standing.SILENT
    elif failed_since:
        standing = Standing.FAILING
    else:
        standing = Standing.FRESH

    return Reading(
        path=str(path),
        standing=standing,
        record=record,
        destination=_DESTINATIONS.get(record.offsite, Destination.UNKNOWN),
        since_success=since_success,
        since_failure=since_failure,
        failed_since=failed_since,
        missed_recently=_missed_recently(record, now),
        success_ahead=_ahead(success, now),
        failure_ahead=_ahead(failure, now),
        due_ahead=_due_ahead(record, now),
    )


def _missed_recently(record: Record, now: datetime.datetime) -> int:
    """How many of the recorded missed days are inside ``RECENT_GAP`` of now.

    The dates are ``YYYY-MM-DD`` and validated as such before they reach here, so the
    horizon is compared as text and the comparison is a comparison of dates.

    The day boundary is the reader clock's, in UTC, while the writer resolved those dates
    in the schedule zone. Deliberately not corrected for: the two can disagree by at most
    one day at one end of a window eight weeks long, and the answer this feeds is whether
    a screen says a word, not an arithmetic an operator reads.
    """
    horizon = (now - RECENT_GAP).date().isoformat()
    return sum(1 for day in record.missed_dates if day >= horizon)


def _age(moment: datetime.datetime, now: datetime.datetime) -> datetime.timedelta:
    """How long ago something happened, never less than nothing.

    A record timestamped in the future is a host whose clock disagrees with this one, not
    a backup that has not happened yet. Clamped rather than reported, because the only
    thing an operator could do with "-3 hours ago" is misread it, and a clock that
    disagrees must not be able to turn a fresh backup into a stale one or the reverse.

    The clamp is the arithmetic and is right. It is NOT the sentence: on its own it turns
    a record dated next week into "less than an hour ago", which reads as the quietest
    state on the screen and stays there for as long as the clocks disagree. ``_ahead``
    beside it is what lets the sentence say the other thing.
    """
    return max(now - moment, datetime.timedelta(0))


def _ahead(run: Run | None, now: datetime.datetime) -> bool:
    """Whether that run claims to have happened after the moment it is being read at.

    ``CLOCK_AHEAD_GRACE`` says why this is not simply ``run.at > now``. ``None`` — a thing
    that has never happened — is not ahead of anything.
    """
    return run is not None and run.at - now > CLOCK_AHEAD_GRACE


def _due_ahead(record: Record, now: datetime.datetime) -> bool:
    """Whether the record is owed for a day that had not begun anywhere when it was read.

    ``DUE_AHEAD_GRACE`` says why the horizon is a whole day past this reader's own date and
    what that deliberately cannot see. A record with no due date this reader recognises has
    nothing to be ahead of, which is the same answer ``_ahead`` gives for a run that never
    happened.

    Compared as text. Both sides are ``YYYY-MM-DD`` — the record's is checked against
    ``A_DATE`` before it gets here and this one is built by ``isoformat`` — so comparing
    them as text is comparing them as dates, exactly as ``_missed_recently`` does.
    """
    if not record.due_date:
        return False
    return record.due_date > (now + DUE_AHEAD_GRACE).date().isoformat()


async def read(
    path: pathlib.Path, *, now: datetime.datetime | None = None
) -> Reading:
    """The whole of what this control plane knows about backups on this host.

    Never raises. Every failure — no file, no permission, a damaged file, a file that is
    not this file, a schema from the future — comes back as ``ABSENT`` or ``UNREADABLE``,
    because this is called from the path that draws a screen and a shell script that
    wrote a file badly must not be able to take the panel down with it.

    The read itself goes through a thread, under a ceiling. It is a tiny local file and
    the cost is nothing, but it is the one blocking call on a request path in this zone,
    and a mount whose source has gone away can block for as long as the kernel likes — so
    it blocks a thread rather than the event loop every other request is sharing, and it
    stops waiting after ``READ_CEILING_SECONDS`` rather than holding the front page open
    for ever. A ceiling reached is read as UNREADABLE, which is the honest answer: there is
    supposed to be a record there and this process could not get at it.

    ``READ_CEILING_SECONDS`` says what that does and does not repair — it frees the
    request, not the thread — and ``_read_bytes`` says why the shape that could be planted
    deliberately never reaches it.
    """
    now = now or datetime.datetime.now(datetime.UTC)
    try:
        present, data = await asyncio.wait_for(
            asyncio.to_thread(_read_bytes, path), timeout=READ_CEILING_SECONDS
        )
    except TimeoutError:
        logger.warning(
            "the backup record at %s did not answer within %.1fs, so the screen says it "
            "could not be read",
            path,
            READ_CEILING_SECONDS,
        )
        return _nothing(path, Standing.UNREADABLE)

    if not present:
        return _nothing(path, Standing.ABSENT)
    if data is None:
        return _nothing(path, Standing.UNREADABLE)
    if len(data) > MOST_OF_A_RECORD:
        logger.warning(
            "the backup record at %s is larger than %d bytes, so it is not the record",
            path,
            MOST_OF_A_RECORD,
        )
        return _nothing(path, Standing.UNREADABLE)

    try:
        record = _parse(data)
    except (_Malformed, ValueError, UnicodeDecodeError) as exc:
        # The KEY that disappointed, not the value in it, and not the file. An operator
        # reading this in the container's output needs to know which line to look at.
        logger.warning(
            "the backup record at %s is not the record scripts/backup-run.sh writes "
            "(%s: %s)",
            path,
            type(exc).__name__,
            exc.args[0] if exc.args and isinstance(exc.args[0], str) else "",
        )
        return _nothing(path, Standing.UNREADABLE)

    return _judge(record, now, path)


def _nothing(path: pathlib.Path, standing: Standing) -> Reading:
    """A reading with no record behind it — the two answers that know nothing.

    Both ages are ``None`` rather than zero, and that is the point of the helper: a zero
    in ``since_success`` would be a backup that succeeded this instant, which is a claim
    neither of these standings is entitled to make. ``failed_since`` has no third value to
    be, so it is ``False`` and nothing reads it here — the two sentences these standings
    produce are about the file, not about any run.
    """
    return Reading(
        path=str(path),
        standing=standing,
        record=None,
        # There is no record to ask where this host sends anything, and neither of the
        # other two answers may be guessed: "offsite" would reinstate the bug this field
        # exists to close, and "this host" would deny an upload that may be working.
        destination=Destination.UNKNOWN,
        since_success=None,
        since_failure=None,
        failed_since=False,
        # No record, so no day in it is named as missed — which is not the same as a host
        # that has missed none, and nothing composed from this standing says it is.
        missed_recently=0,
        success_ahead=False,
        failure_ahead=False,
        # No record, so no due date to be unable to reconcile with anything. ABSENT and
        # UNREADABLE are already the two loudest things this panel says about a file.
        due_ahead=False,
    )
