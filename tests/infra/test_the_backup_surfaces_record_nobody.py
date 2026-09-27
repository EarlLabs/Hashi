"""Nothing M28 added records who connected to what — M28.7.

WHAT: the audit of every surface this milestone put on a host that writes, prints or
      stores something: ``scripts/backup.sh``, ``scripts/backup-run.sh``,
      ``scripts/backup-schedule.sh`` and the cron entry it installs,
      ``deploy/backup/upload.py``, and every ``scripts/lib/*.sh`` those scripts source —
      discovered by reading them, never listed. What each of them emits, on success and on
      the failure paths, and where that output ends up.
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

RECORD_LIB = REPO / "scripts" / "lib" / "backup-record.sh"


# A `.` or a `source` IN COMMAND POSITION, and the word it is handed. Command position is
# the start of a line or anything that ended the command before it, because `. a.sh; . b.sh`
# is two readers and a pattern anchored at `^\s*` finds one of them (M28.21).
_SOURCE_STATEMENT = re.compile(
    r"(?:^|[;&|(]|\b(?:then|do|else)\b)\s*(?:\.|source)\s+([^\s;&|)]+)", re.M
)
# That word, once its quoting is off, as a name under `scripts/`. The quotes come off
# rather than being written into the pattern because `"${REPO_ROOT}"/scripts/lib/a.sh` and
# `${REPO_ROOT}/scripts/"lib/a.sh"` are one path written by two people, and a pattern that
# knows one of them is a description of today's call sites — the same mistake as naming the
# files.
_UNDER_SCRIPTS = re.compile(r"^\$\{?REPO_ROOT\}?/scripts/([\w./-]+\.sh)$")


def _sourced_names(script: str) -> list[str]:
    """Every library under ``scripts/`` this text sources, by name, in the order written.

    Whole-line comments go first: the statement pattern no longer anchors at the start of a
    line, and these scripts quote the shapes they forbid, so a comment naming one would
    otherwise be discovered as a real statement. That leaves the two places prose can still
    sit beside code on one line — a quoted string and a trailing ``#`` comment — and a
    statement written after a separator in either of those IS discovered. The docstring of
    ``_sourced_libraries`` names that as the direction this deliberately errs in.
    """
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    names = []
    for word in _SOURCE_STATEMENT.findall(code):
        under = _UNDER_SCRIPTS.match(word.replace('"', "").replace("'", ""))
        if under:
            names.append(under.group(1))
    return names


def _sourced_libraries(
    *scripts: pathlib.Path, root: pathlib.Path | None = None
) -> tuple[pathlib.Path, ...]:
    """Every shell file under ``scripts/`` any of these scripts sources, by reading them.

    THE NAMED SCRIPTS ARE THIS AUDIT'S SCOPE AND THE LIBRARIES ARE NOT A SECOND LIST. The
    scope is the backup path — a glob over every shell surface in the project would sweep
    ``node-bootstrap.sh`` and ``notify.sh``, which configure a node's own logging and are
    entitled to the words this file forbids, so it would be a different audit with a
    different answer.

    What has gone wrong twice is the other half: code from a surface MOVES INTO A LIBRARY
    and the list does not follow. M28.8 put the env-file gate in one and it landed outside
    a copy of this tuple; M28.18 put the whole of the record reading in another — 469 lines
    of it — and swept a ``backup-run.sh`` that no longer holds any of it. Nothing leaked
    either time; what was wrong is that the audit said it had looked and had not.

    So the libraries are DISCOVERED rather than named: being sourced by a swept script is
    what puts a file in the sweep, which is the same fact that put the code there. A
    library that arrives by the next move arrives inside this list on the same commit.

    AND THE DISCOVERY IS TRANSITIVE, because the next move is library→library. Until M28.19
    this read the three named scripts and did not look inside what it found, which was the
    exact hop the paragraph above describes: record handling had just moved into
    ``scripts/lib/backup-record.sh``, so a second library sourced from THERE would have been
    invisible. Proven rather than argued — a planted ``scripts/lib/record-notes.sh`` with a
    ``tee -a /var/log/…`` in it, sourced from ``backup-record.sh``, left all fourteen tests
    green. The worklist below is the fix: every library found is itself read, until a pass
    finds nothing new.

    AND THE SPELLING IS NOT THE POINT EITHER, which round 1's review found by planting it
    twice more: ``. "$REPO_ROOT/scripts/lib/record-notes.sh"`` without braces, and the same
    library at ``scripts/helpers/`` with them, both walked the whole sweep out of the door
    while every test here stayed green. So the pattern takes braces or none and any path
    under ``scripts/``, and the file has to resolve inside that directory — a discovery
    that recognises one way of writing a name is a description of today's six call sites,
    which is the same mistake as naming the files.

    AND M28.21 CLOSED THREE MORE SPELLINGS, measured rather than imagined, each of which
    walked the whole sweep out of the door on its own: ``. "${REPO_ROOT}"/scripts/lib/a.sh``
    closes the quote after the variable; ``. ${REPO_ROOT}/scripts/"lib/a.sh"`` opens one in
    the middle of the path; and two source statements on one line — ``. a.sh; . b.sh`` —
    where a pattern anchored at the start of a line finds the first and never looks for the
    second. None of the three is written in this tree today, which is precisely the
    argument that was made about the braceless form one round earlier and it turned out to
    matter. So the quoting comes off the word before it is judged, and every command
    position on the line is looked at rather than the first.

    What it still does not see, and the list is short on purpose: a path built at runtime,
    a relative ``. ./lib/x.sh``, and a source line inside a conditional it cannot evaluate.
    All three would be caught by running the script instead of reading it, which is another
    test's job — nothing in this project writes any of them, and the moment one does, this
    sweep is the wrong tool rather than a leaky one.

    What it errs TOWARDS rather than away from, now that it no longer anchors at the start
    of a line, and named as the state it holds for rather than as a worry: a source
    statement written after a ``;``, ``&``, ``|`` or ``(`` **inside a quoted string, or in
    a trailing ``#`` comment on a code line**, is read as a real one — measured, ``echo "a;
    . ${REPO_ROOT}/scripts/lib/nope.sh"`` is discovered — and the ``is_file`` check below
    then fails by name. Whole-line comments are dropped before any of this, so the prose
    these scripts carry about the shapes they forbid is safe; prose on the same line as
    code is not. A loud false positive is the right direction for an audit whose other
    failure mode is going quiet.

    ``root`` is the tree the sourced names are resolved against, and it is a parameter for
    one reason: the transitivity above is a property of THIS function, and the only way to
    hold it is to hand it a chain and see whether it walks the whole thing. Planting that
    chain in the repository would be an audit checking work it had planted. Everything but
    those tests passes the repository.
    """
    root = root or REPO
    found: list[pathlib.Path] = []
    # The scripts still to read. A library goes on it the moment it is discovered, so a
    # chain of any length is walked and a cycle — a pair of libraries sourcing each other —
    # terminates, because nothing is ever queued twice.
    pending: list[pathlib.Path] = list(scripts)
    seen: set[pathlib.Path] = set()
    while pending:
        script = pending.pop(0)
        if script in seen:
            continue
        seen.add(script)
        # `source` as well as `.`, `${REPO_ROOT}` as well as `$REPO_ROOT`, quoted however
        # the author felt like quoting it, anywhere under `scripts/` rather than
        # `scripts/lib/` alone, and at every command position on the line rather than the
        # first: a discovery that only knows one spelling goes QUIET on the others, and a
        # sweep that silently shrinks is the exact failure this function replaces.
        for name in _sourced_names(script.read_text()):
            library = (root / "scripts" / name).resolve()
            # Resolved and then checked to be inside `scripts/`, because the capture now
            # allows `/` and `.`: `../../somewhere/else.sh` would otherwise take the sweep
            # outside the tree it is auditing, and a sweep that can be pointed anywhere is
            # not a sweep of anything.
            assert library.is_relative_to((root / "scripts").resolve()), (
                f"{script.name} sources something outside scripts/: {name}"
            )
            assert library.is_file(), f"{script.name} sources a library that is not there: {name}"
            if library not in found:
                found.append(library)
            pending.append(library)
    return tuple(found)


SURFACES = (BACKUP, RUNNER, INSTALLER, UPLOADER) + _sourced_libraries(
    BACKUP, RUNNER, INSTALLER
)


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


# --- the sweep finds what the sweep is for --------------------------------------------


def test_a_library_sourced_by_a_library_is_swept_too(tmp_path) -> None:
    """The hop the discovery did not make, held by a chain planted outside the repository.

    Red at this step's baseline and green after it: the old discovery read the scripts it
    was given and stopped, so the second hop below — the shape that arrives the moment a
    library is refactored the way ``backup-run.sh`` was — was never opened, and a ``tee -a
    /var/log/…`` in it was swept by nothing while every test in this file stayed green.

    Planted in ``tmp_path`` rather than in ``scripts/lib/``, because an audit that plants
    its own evidence in the tree it audits proves only that it can read its own work — and
    because a file with that line in it has no business in this repository even for the
    length of a test.
    """
    scripts = tmp_path / "scripts"
    (scripts / "lib").mkdir(parents=True)
    (scripts / "helpers").mkdir()
    (scripts / "caller.sh").write_text('. "${REPO_ROOT}/scripts/lib/first.sh"\n')
    (scripts / "lib" / "first.sh").write_text('. "${REPO_ROOT}/scripts/lib/second.sh"\n')
    # Sourced with `source` rather than `.`, so the spelling the project does not use is
    # walked on the hop the project does not make.
    (scripts / "lib" / "second.sh").write_text('source "${REPO_ROOT}/scripts/lib/third.sh"\n')
    # The two the reviewer planted in round 1, both of which walked the whole sweep out of
    # the door: the braceless `$REPO_ROOT`, and a library that is simply not under `lib/`.
    # Neither is a shape this project writes today, which is exactly why nothing was red.
    (scripts / "lib" / "third.sh").write_text(
        '. "$REPO_ROOT/scripts/lib/fourth.sh"\n'
        '. "${REPO_ROOT}/scripts/helpers/fifth.sh"\n'
    )
    (scripts / "lib" / "fourth.sh").write_text("# no braces got it here\n")
    (scripts / "helpers" / "fifth.sh").write_text("# and this one is not in lib/\n")

    found = _sourced_libraries(scripts / "caller.sh", root=tmp_path)

    assert [path.name for path in found] == [
        "first.sh", "second.sh", "third.sh", "fourth.sh", "fifth.sh",
    ], (
        "a library sourced by a library, or named in a spelling this project does not "
        "happen to use, is outside the sweep — so anything that moves one hop further "
        f"from a named script is audited by nothing: {[p.name for p in found]}"
    )


def test_the_discovery_reads_the_three_spellings_that_used_to_walk_it_out(tmp_path) -> None:
    """M28.21's three, each of which took the WHOLE sweep with it and none of which is red.

    Two are quoting — a project puts its quotes where it likes, and a pattern that knows
    one placement is a description of today's six call sites rather than a rule. The third
    is two statements on one line, which the old pattern could not see because it anchored
    at the start of a line and stopped at the first.

    Not one of the three is written in this tree today, and that is the argument for the
    test rather than against it: the braceless ``$REPO_ROOT`` was not written here either
    when round 1 of M28.19 planted it, and it walked every library out of the sweep.

    Planted in ``tmp_path``, like the chain above: an audit that plants its evidence in the
    tree it audits proves only that it can read its own work.
    """
    scripts = tmp_path / "scripts"
    (scripts / "lib").mkdir(parents=True)
    (scripts / "caller.sh").write_text(
        # The quote closed after the variable rather than around the whole word.
        '. "${REPO_ROOT}"/scripts/lib/first.sh\n'
    )
    (scripts / "lib" / "first.sh").write_text(
        # A quote opened in the middle of the path.
        '. ${REPO_ROOT}/scripts/"lib/second.sh"\n'
    )
    # Two statements on one line: the anchored pattern found the first and never looked for
    # the second, so `third.sh` was swept and `fourth.sh` was audited by nothing.
    (scripts / "lib" / "second.sh").write_text(
        '. "${REPO_ROOT}/scripts/lib/third.sh"; . "${REPO_ROOT}/scripts/lib/fourth.sh"\n'
    )
    (scripts / "lib" / "third.sh").write_text("# reached by the first of the two\n")
    (scripts / "lib" / "fourth.sh").write_text("# reached only by looking past it\n")

    found = _sourced_libraries(scripts / "caller.sh", root=tmp_path)

    assert [path.name for path in found] == [
        "first.sh", "second.sh", "third.sh", "fourth.sh",
    ], (
        "a library named in a spelling this project does not happen to use, or sourced by "
        "the second statement on a line, is outside the sweep — and a sweep that shrinks "
        f"silently is the failure this discovery replaces: {[p.name for p in found]}"
    )


def test_a_source_statement_quoted_in_a_comment_is_not_a_library(tmp_path) -> None:
    """The cost of not anchoring at the start of a line, and where it is paid.

    These scripts quote the shapes they forbid, in comments, and the discovery would
    otherwise walk off after a file that does not exist. Whole-line comments are dropped
    for that reason. What is NOT dropped — a statement after a separator inside a quoted
    string or a trailing comment — is named in ``_sourced_libraries``'s own seam list and
    fails loudly there rather than quietly here, which is the safe direction.
    """
    scripts = tmp_path / "scripts"
    (scripts / "lib").mkdir(parents=True)
    (scripts / "caller.sh").write_text(
        '# never write `. "${REPO_ROOT}/scripts/lib/nowhere.sh"` twice on one line\n'
        '   #  . "${REPO_ROOT}/scripts/lib/alsonowhere.sh"\n'
        '. "${REPO_ROOT}/scripts/lib/real.sh"\n'
    )
    (scripts / "lib" / "real.sh").write_text("# the only one there is\n")

    found = _sourced_libraries(scripts / "caller.sh", root=tmp_path)
    assert [path.name for path in found] == ["real.sh"], [p.name for p in found]


def test_the_discovery_terminates_on_a_cycle(tmp_path) -> None:
    """Two libraries sourcing each other is a hang, and a hanging audit is a red gate.

    Not a shape this project has — the sourcing here is a tree — but the worklist is what
    makes it reachable, and a test suite that never returns is worse than one that fails.
    """
    scripts = tmp_path / "scripts"
    (scripts / "lib").mkdir(parents=True)
    (scripts / "caller.sh").write_text('. "${REPO_ROOT}/scripts/lib/one.sh"\n')
    (scripts / "lib" / "one.sh").write_text('. "${REPO_ROOT}/scripts/lib/two.sh"\n')
    (scripts / "lib" / "two.sh").write_text('. "${REPO_ROOT}/scripts/lib/one.sh"\n')

    found = _sourced_libraries(scripts / "caller.sh", root=tmp_path)
    assert sorted(path.name for path in found) == ["one.sh", "two.sh"]


# --- nothing here keeps a log of its own ---------------------------------------------


def test_no_backup_surface_appends_to_anything() -> None:
    """A log is a file something appends to, and none of these appends to anything.

    Stated as the shape rather than as a list of forbidden filenames, because the next
    person to add one will not call it ``backup.log``. Every file these surfaces write —
    the artifact, the record, the lock, the two ``.partial`` files — is created whole and
    replaced whole, so an append is by construction something new.

    Over SURFACES, and over nothing assembled a second time here. This test used to carry
    its own tuple of three, and when M28.8's shared gate was added to SURFACES it landed
    outside that copy — so the one file both scripts now depend on for exactly this class
    of finding was swept for a log destination and not for an append. Nothing leaked,
    because the library has no ``>>`` in it; what was wrong is that the audit said it had
    looked and had not. One list.
    """
    swept = []
    for script in SURFACES:
        if script.suffix != ".sh":
            # `>>` is a shell redirection and in Python it is a right shift, so this shape
            # says nothing about the uploader. What it writes is asserted directly by
            # `test_the_uploader_writes_no_file_but_the_one_it_unlinks` below — excluded by
            # a reason that is here to be read, rather than by being left off a list.
            continue
        swept.append(script.name)
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
    # A sweep that swept nothing is this repository's signature defect, and it is how the
    # gap above went unnoticed: name what was actually looked at.
    assert swept == [script.name for script in SURFACES if script.suffix == ".sh"]
    # The two libraries the backup path actually depends on, named as a floor under the
    # discovery above: if `_sourced_libraries` ever stops finding them the list goes quiet
    # rather than short, and quiet is the failure this whole assertion exists for.
    assert GATE.name in swept, "the surface both scripts share is not in the sweep"
    assert RECORD_LIB.name in swept, (
        "the library that holds every read of the backup record is not in the sweep, so "
        "this audit is looking at a scripts/backup-run.sh the record no longer passes "
        "through"
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
    # here: nothing below asserts anything about this date, it is only the state in which
    # the tick has nothing to do, so a second implementation of the date would be a second
    # thing that can go wrong under an assertion about SILENCE. Where the date IS the
    # assertion, `test_backup_schedule.day_owed_in` works it out instead and says why —
    # this test is the case its docstring names on the other side of that line.
    #
    # Named `owed` and not `today`: for the four hours before `HASHI_BACKUP_AT` the day
    # owed is yesterday's, and a name saying otherwise is the mis-reading M27.9 came from.
    state.mkdir()
    owed = verdict(run("due", path, state))["due"]
    seed(state, due_date=owed,
         last_attempt={"at": f"{owed}T04:00:00Z", "due_date": owed,
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
