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
      this module composes no prose — every sentence built from a ``Reading`` carries
      ``console.BACKUP_NOT_THE_BUCKET``, and a green tick on a screen is precisely how
      that distinction would otherwise be lost.
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


@dataclasses.dataclass(frozen=True, slots=True)
class Run:
    """One run of the backup, as the record remembers it.

    ``outcome`` is the writer's own word for what happened — ``offsite``,
    ``on-this-host-only``, ``not-sent``, ``no-artifact``, ``refused`` — derived there from
    the exit code and whether the upload is switched on, never by parsing any output. It
    is kept as the word rather than as a judgement: what it MEANS is a sentence, and
    sentences are composed in ``services/console.py`` like every other thing this panel
    says.

    The record carries a ``due_date`` on each entry as well. It is not read here: what it
    answers — which day's backup this run was for — is the scheduler's own business, and
    a field with no reader is a field that quietly goes wrong.
    """

    at: datetime.datetime
    exit_code: int
    outcome: str


@dataclasses.dataclass(frozen=True, slots=True)
class Record:
    """The record's contents, as far as anything here has a use for them.

    A deliberate subset of M28.5's fifteen keys. ``schema`` is checked and not kept,
    ``written_at`` and ``due_date`` say what ``last_attempt`` already says, and
    ``attempts``, ``retry_not_before`` and ``offsite`` are the scheduler's own working
    state — the last of those is already in every run's ``outcome``. A field nothing
    reads is a field nobody notices has gone wrong, so they are not carried.
    """

    # The appointed time and the zone it is in, both exactly as the host resolved them.
    # ``zone`` is an IANA NAME and is displayed as one: it is never turned into a country,
    # a flag or an offset, here or anywhere downstream.
    at: str
    at_source: str
    zone: str
    zone_source: str
    # Days the schedule noticed had no backup at all, and the cumulative count of them.
    # Both survive the run that ends a gap, so they are history rather than an alarm.
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
    # How long ago the last successful run was, ``None`` if there has never been one.
    since_success: datetime.timedelta | None
    # ...and the last failed one, on the same terms.
    since_failure: datetime.timedelta | None
    # Whether a run has failed since the last success — M28.5's own test for it, which is
    # ``last_failure.at > last_success.at`` and is true of a failure with no success at
    # all beside it.
    failed_since: bool


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
        missed_dates=tuple(dates),
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
        since_success=since_success,
        since_failure=since_failure,
        failed_since=failed_since,
    )


def _age(moment: datetime.datetime, now: datetime.datetime) -> datetime.timedelta:
    """How long ago something happened, never less than nothing.

    A record timestamped in the future is a host whose clock disagrees with this one, not
    a backup that has not happened yet. Clamped rather than reported, because the only
    thing an operator could do with "-3 hours ago" is misread it, and a clock that
    disagrees must not be able to turn a fresh backup into a stale one or the reverse.
    """
    return max(now - moment, datetime.timedelta(0))


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
        since_success=None,
        since_failure=None,
        failed_since=False,
    )
