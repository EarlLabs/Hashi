"""The two channels agree about the same file — M28.12.

WHAT: what ``make backup-status`` does with a record it cannot read, where it says a host
      sends its backups, what a bare exit code means, and what ``make backup`` says when
      compose refuses a value that has nothing to do with the backup keypair. Plus the two
      things a second bare-host walk found in the install path: a re-run that unpublishes a
      serving host, and a management tunnel generated out of ``.env.example``'s own values.
WHY:  the panel and the command line read ONE file, and until this step they said
      different things about it. The panel refused a damaged record — *"Nothing has been
      assumed from it"* — and sent the operator to ``make backup-status``, which printed
      that same record as fact: *"last success: never / last attempt: never"*, a confident
      schedule line, exit **0** — which is byte-for-byte what a machine that has never
      taken a backup prints. Two channels disagreeing about a record is worse than either
      of them being wrong alone, because the operator learns to believe whichever one is
      easier to reach.

      The other half is the advice. ``make backup`` blamed the backup keypair for ANY
      value compose could not resolve, and an operator who follows that generates a new
      pair — after which every artifact in the store is addressed to an identity they have
      just replaced, with nothing on this host able to open one.
HOW:  the reading verbs are RUN, against records written the way the writer writes them,
      with no docker anywhere — ``status`` reads a file and an env file and starts nothing.
      ``missing_value_advice`` is run as well: the function is sliced out of the script and
      driven with compose's own sentence, so the three branches are exercised rather than
      read.

      The parity with the panel is asserted against ``control/app/services/console.py``
      itself, not against a copy of its words kept here: a caveat reworded on one side and
      not the other fails in this file, which is the whole point of the check. Reading the
      other zone's source is the same thing
      ``test_node_bootstrap_agrees_with_the_control_plane.py`` does, and for the same
      reason — the agreement is the subject.
"""

import pathlib
import re
import subprocess

import pytest

from tests.infra.test_backup_schedule import env_file, run, seed

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts" / "backup-run.sh"
BACKUP = REPO / "scripts" / "backup.sh"
INSTALLER = REPO / "scripts" / "backup-schedule.sh"
BOOTSTRAP = REPO / "scripts" / "panel-bootstrap.sh"
FETCHER = REPO / "deploy" / "backup" / "fetch.py"
ENV_EXAMPLE = REPO / ".env.example"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"
CONSOLE = REPO / "control" / "app" / "services" / "console.py"

# The three sentences the panel closes with, by their openings. M28.11 pinned them as the
# contract for this step, and each is the first clause of one of ``BACKUP_CAVEATS``.
CAVEAT_OPENINGS = (
    "What this does NOT say: whether any of those artifacts is still in the bucket.",
    "What this does NOT say: that this host is sending its backups anywhere.",
    "What this does NOT say: whether anything was sent anywhere.",
)
# ...and the clause all three of them end on.
ONLY_A_RESTORE = "The only thing that proves a backup is a restore"


def flat(text: str) -> str:
    """One line, with Python's own string-concatenation seams closed.

    A caveat in ``console.py`` is a wrapped constant and this page wraps its own output at
    a different width: where a line breaks is not a fact about what either of them says,
    and asserting on it would make every reflow a failure.
    """
    return " ".join(text.split()).replace('" "', "")


@pytest.fixture(scope="module")
def runner() -> str:
    return RUNNER.read_text()


@pytest.fixture(scope="module")
def backup() -> str:
    return BACKUP.read_text()


@pytest.fixture(scope="module")
def bootstrap() -> str:
    return BOOTSTRAP.read_text()


def status(tmp_path: pathlib.Path, **fields) -> subprocess.CompletedProcess:
    """``make backup-status`` over a record seeded with whatever this test needs.

    Through ``run()``, so every invocation inherits M28.5's assertion that nothing out of
    the env file reached the output — this verb prints more of the record than any other
    and is the one most likely to start printing the wrong file.
    """
    state = tmp_path / "state"
    seed(state, **fields)
    return run("status", env_file(tmp_path, HASHI_BACKUP_TZ="Etc/UTC"), state)


def damaged(tmp_path: pathlib.Path, text: str) -> subprocess.CompletedProcess:
    """A record that is not the one the writer writes, put there by hand."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "last-run.json").write_text(text)
    return run("status", env_file(tmp_path, HASHI_BACKUP_TZ="Etc/UTC"), state)


def record_text(**fields) -> str:
    """The writer's own layout — one key per line — with fields overridden verbatim."""
    values = {
        "schema": "1",
        "written_at": '"2026-09-23T04:00:12Z"',
        "at": '"04:00"',
        "at_source": '"configured"',
        "zone": '"Etc/UTC"',
        "zone_source": '"configured"',
        "offsite": '"no"',
        "due_date": '"2026-09-23"',
        "attempts": "1",
        "retry_not_before": '""',
        "last_attempt": "null",
        "last_success": "null",
        "last_failure": "null",
        "missed_dates": "[]",
        "missed_total": "0",
    }
    values.update(fields)
    return "{\n" + ",\n".join(f'  "{k}": {v}' for k, v in values.items()) + "\n}\n"


A_RUN = (
    '{{ "at": "{at}", "due_date": "2026-09-23", "exit_code": {code}, "outcome": "{outcome}" }}'
)


# --- 1. a record this cannot read is not a host that has never run ------------


@pytest.mark.parametrize(
    "field,value",
    [
        # A schema nobody here has seen. The panel calls this unreadable rather than
        # guessing at the fields behind the number, and so does this.
        ("schema", "99"),
        # A key this reader reads, gone. `offsite` is the one M28.11 added, and a record
        # missing it is a record this cannot answer "where does this host send" from.
        ("offsite", None),
        ("zone", None),
        # A nested entry that is not a run. "No backup has ever succeeded" is a statement
        # the record is entitled to make; "this line is not a run" is not.
        ("last_success", '{ "at": "yesterday", "exit_code": 0, "outcome": "offsite" }'),
        ("last_attempt", '"probably fine"'),
        # A count that is not one, and a missed day that is not a day.
        ("missed_total", '"lots"'),
        ("missed_dates", '["yesterday"]'),
    ],
)
def test_a_damaged_record_is_refused_rather_than_read_as_a_fresh_host(
    tmp_path, field, value
) -> None:
    """THE finding: every one of these used to print as *"last success: never"*, exit 0.

    Which is what a machine that has never taken a backup prints, so the two states were
    indistinguishable on the one channel the panel sends the operator to.
    """
    fields = {field: value} if value is not None else {}
    text = record_text(**fields)
    if value is None:
        text = "\n".join(
            line for line in text.splitlines() if f'"{field}"' not in line
        ).replace(",\n}", "\n}")
    result = damaged(tmp_path, text)

    assert result.returncode == 1, (
        f"a record with a bad {field} exited 0, so a schedule that has never run and a "
        f"record nothing can read are the same answer:\n{result.stdout}"
    )
    said = result.stdout + result.stderr
    assert "NOTHING HAS BEEN ASSUMED FROM IT" in said
    assert field in said, "the refusal does not say which field it could not read"
    assert "last success:" not in said and "last attempt:" not in said, (
        "the damaged record was printed anyway, under a sentence saying it was not read"
    )
    assert "scheduled:" not in said, (
        "a confident schedule line is printed beside a record nothing could read"
    )


def test_the_refusal_names_the_field_and_never_what_was_in_it(tmp_path) -> None:
    """A thousand characters of somebody's idea of an outcome, and a tag with it.

    The panel refuses anything over its own ``LONGEST_VALUE`` for the same reason, and
    what neither of them does is quote the value back: a record is a file a hand edit
    reaches, and a reader that echoes it is a reader that can be made to say anything on
    the terminal it is read at.
    """
    planted = "<script>alert(1)</script>" + "A" * 1000
    result = damaged(
        tmp_path,
        record_text(last_attempt=A_RUN.format(at="2026-09-23T04:00:12Z", code=0, outcome=planted)),
    )
    said = result.stdout + result.stderr
    assert result.returncode == 1
    assert "last_attempt" in said
    assert "<script>" not in said and "AAAA" not in said, (
        "the value out of the record was printed back at the terminal"
    )


def test_an_absent_record_and_an_unreadable_one_are_different_sentences(tmp_path) -> None:
    """Both exit 1, and they are not the same fault.

    "Nothing has ever run here" is the normal state of a host whose schedule was never
    installed. "There is a file here and it is not the record" is somebody's disk or
    somebody's editor, and the remedies are different.
    """
    absent = run("status", env_file(tmp_path), tmp_path / "nowhere")
    assert absent.returncode == 1
    assert "No backup has ever been recorded on this host" in absent.stderr

    broken = damaged(tmp_path, record_text(schema="7"))
    assert broken.returncode == 1
    assert "No backup has ever been recorded on this host" not in broken.stderr
    assert "not the file the schedule writes" in broken.stderr


# --- 2. where this host sends, and the three sentences that go with it --------


def test_the_panel_still_owns_the_three_caveats_this_matches() -> None:
    """The contract, checked against the other channel's source and not against a copy.

    M28.11 keyed the panel's caveat on where the HOST sends — the record's own ``offsite``
    — and pinned the three openings as the wording this step must match. Asserting them
    against a list written down here would pass on the day somebody rewords the panel,
    which is the exact failure this is for.
    """
    console = flat(CONSOLE.read_text())
    for opening in CAVEAT_OPENINGS:
        assert opening in console, (
            "the panel no longer says this, so the command line is now the only place it "
            "is said and the two channels have drifted"
        )
    assert console.count(ONLY_A_RESTORE) >= len(CAVEAT_OPENINGS)


@pytest.mark.parametrize(
    "offsite,opening",
    [("yes", CAVEAT_OPENINGS[0]), ("no", CAVEAT_OPENINGS[1]), ("ok", CAVEAT_OPENINGS[2])],
)
def test_the_caveat_is_chosen_by_where_the_record_says_this_host_sends(
    tmp_path, offsite, opening
) -> None:
    """One field, two readers, one answer — including the word neither of them knows.

    ``HASHI_BACKUP_ENABLED=0`` is the shipped default, so before this the command line
    closed a host that sends nothing anywhere with a caveat about a bucket it does not
    have. An unrecognised word collapses into neither answer, exactly as the panel's
    ``Destination.UNKNOWN`` does: guessing "offsite" is the original bug and guessing
    "this host" denies a working upload.
    """
    result = status(tmp_path, offsite=offsite)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    said = flat(result.stdout)
    assert opening in said, result.stdout
    assert ONLY_A_RESTORE in said
    for wrong in [line for line in CAVEAT_OPENINGS if line != opening]:
        assert wrong not in said


def test_an_outcome_this_version_has_no_meaning_for_stays_readable(tmp_path) -> None:
    """The line the panel draws too: a sixth word must not turn a screen into an alarm.

    ``offsite`` and ``outcome`` are deliberately different here — an unknown value in the
    first is "this cannot say where it went", an unknown value in the second is named
    verbatim — and both readers do it the same way.
    """
    result = status(
        tmp_path,
        offsite="yes",
        last_success={"at": "2026-09-23T04:00:12Z", "due_date": "2026-09-23",
                      "exit_code": 0, "outcome": "ok"},
    )
    assert result.returncode == 0, result.stderr
    assert "(ok)" in result.stdout
    assert "NOTHING HAS BEEN ASSUMED" not in result.stdout + result.stderr


def test_the_schedule_line_says_it_came_from_the_env_file(tmp_path) -> None:
    """It always did, and it read as a fact about the backups.

    The appointed time on this page is resolved from the env file as it is NOW; everything
    under it is what the record says happened. Printed side by side with no source, a
    confident *"scheduled: 04:00 Etc/UTC (configured)"* beside *"last success: never"*
    reads as a working schedule that has simply not fired yet.
    """
    result = status(tmp_path, offsite="no")
    scheduled = [line for line in result.stdout.splitlines() if "scheduled:" in line]
    assert scheduled, result.stdout
    where = result.stdout.splitlines()[result.stdout.splitlines().index(scheduled[0]) + 1]
    assert "not from this record" in where, result.stdout


# --- 3. a bare exit code, and days in the order the label claims --------------


def test_exit_three_is_said_as_what_it_means_and_names_its_remedy(tmp_path) -> None:
    """3 is a state with a remedy, and it was shown as a digit and nowhere else.

    The artifact of that run is on the machine: re-dumping writes a second copy of the same
    database and never fixes why the store refused the first.
    """
    result = status(
        tmp_path,
        offsite="yes",
        last_attempt={"at": "2026-09-23T04:00:12Z", "due_date": "2026-09-23",
                      "exit_code": 3, "outcome": "not-sent"},
        last_failure={"at": "2026-09-23T04:00:12Z", "due_date": "2026-09-23",
                      "exit_code": 3, "outcome": "not-sent"},
    )
    assert result.returncode == 0, result.stderr
    assert "did NOT leave this" in result.stdout
    assert "make backup-upload FROM=" in result.stdout


def test_the_missed_days_are_printed_newest_first_whatever_the_file_says(tmp_path) -> None:
    """The label says "most recent", and a reader may not take a file's order on trust.

    The panel sorts what it reads (M28.11) and so does this, because the record is a file
    on a disk where a hand edit goes. The WRITER sorts as well now — see below — so on a
    record this project wrote there is nothing left to disagree about.
    """
    result = status(
        tmp_path,
        missed_dates=["2026-08-01", "2026-09-20", "2026-09-19"],
        missed_total=3,
    )
    assert result.returncode == 0, result.stderr
    listed = [line for line in result.stdout.splitlines() if "days with no backup" in line]
    assert listed, result.stdout
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", listed[0])
    assert dates == sorted(dates, reverse=True), listed[0]
    assert dates[0] == "2026-09-20"


def test_the_writer_stores_them_newest_first_too(runner: str) -> None:
    """Fixed at the source, so both readers stop guessing — the plan's own instruction.

    Static, and stated as such: what is asserted is that the list is sorted descending
    before the cap and that the cap keeps the head rather than the tail. The behavioural
    half needs a real gap and a real dump, which is
    ``tests/e2e/infra/test_restore_proves_the_backup.py``'s catch-up scenario.
    """
    body = runner.split("record_missed() {", 1)[1].split("\n}", 1)[0]
    assert "sort -r" in body, "the writer appends missed days in the order it walked them"
    assert "head -n" in body and "tail -n" not in body, (
        "the list is capped from the wrong end, so the cap drops the recent days it is "
        "there to keep"
    )


# --- 4. the advice that would have orphaned every artifact --------------------


def advice(refusal: str) -> subprocess.CompletedProcess:
    """``missing_value_advice`` on its own, driven with compose's own sentence.

    Sliced out of the script and run, rather than read: the branch is the whole finding,
    and a test that greps for the words would pass on a version that prints all of them.
    """
    script = BACKUP.read_text()
    body = "missing_value_advice() {" + script.split("missing_value_advice() {", 1)[1].split(
        "\n}\n", 1
    )[0] + "\n}\n"
    program = (
        "set -euo pipefail\n"
        "ENV_FILE=/tmp/an-env-file\n"
        f"{body}\n"
        'missing_value_advice "$1"'
    )
    return subprocess.run(
        ["bash", "-c", program, "bash", refusal],
        capture_output=True, text=True, timeout=30,
    )


COMPOSE_SAYS = (
    "error while interpolating services.{service}.environment.{name}: required variable "
    "{name} is missing a value: set this in .env"
)


def test_only_the_recipient_being_missing_is_about_the_backup_keypair() -> None:
    """The one case the old page was written for, and it still gets that page."""
    said = flat(advice(
        COMPOSE_SAYS.format(service="control", name="HASHI_BACKUP_AGE_RECIPIENT")
    ).stderr)
    assert "PUBLIC half of your backup keypair" in said
    assert "age-keygen" in said


@pytest.mark.parametrize(
    "name", ["POSTGRES_PASSWORD", "HASHI_SECRET_KEY", "HASHI_OPERATOR_PASSWORD_HASH"]
)
def test_any_other_missing_value_is_not_blamed_on_the_keypair(name) -> None:
    """THE finding, and the damage is not the wasted minute.

    The overlay carries the base compose file, where every interpolation has a ``:?``
    guard, so any of nine names lands here. An operator told their recipient is missing
    generates a new keypair — and every artifact already in the store is addressed to the
    public half they have just replaced, which nothing on this host can open or
    re-address. The remedy for a wrong sentence is a lost backup history.
    """
    said = flat(advice(COMPOSE_SAYS.format(service="db", name=name)).stderr)
    assert name in said, "the advice does not name the variable compose named"
    assert "age-keygen" not in said, (
        f"{name} being empty produced the page that tells an operator to generate a new "
        "backup keypair"
    )
    assert "NOT ABOUT YOUR BACKUP KEYPAIR" in said
    assert "orphans every artifact" in said or "orphans" in said


def test_a_refusal_naming_no_variable_still_refuses_the_keypair_advice() -> None:
    """Compose says other things, and none of them is a statement about a keypair."""
    said = flat(advice("yaml: line 3: did not find expected key").stderr)
    assert "age-keygen" not in said
    assert "Nothing was dumped" in said


def test_the_advice_takes_a_bare_identifier_out_of_what_compose_said() -> None:
    """M28.7's rule: compose names VARIABLES and never values, and this keeps it that way.

    The capture is ``[A-Za-z_][A-Za-z0-9_]*``, so nothing that is not an identifier can
    come back out of it however the refusal was worded.
    """
    body = BACKUP.read_text().split("missing_value_advice() {", 1)[1].split("\n}\n", 1)[0]
    assert "required variable" in body
    assert re.search(r"\[A-Za-z_\]\[A-Za-z0-9_\]\*", body), (
        "the variable name is captured with something looser than an identifier"
    )


# --- 5. the install path: a second run, and a tunnel nobody asked for ---------


def test_the_bootstrap_says_a_second_run_unpublishes_before_it_does_it(
    bootstrap: str,
) -> None:
    """Finding 5: true for the data, false for the panel, and only the runbook said so.

    It asks the running stack rather than assuming: a fresh host is publishing nothing and
    must not be warned about something that cannot happen to it.
    """
    assert "ps --format json" in bootstrap, "nothing asks what this host publishes today"
    assert "PublishedPort" in bootstrap
    detect = bootstrap.index('PUBLISHED_BEFORE="no"')
    # The command itself, not the paragraph explaining it: `up -d --build` is discussed in
    # a comment long before it is run.
    converge = bootstrap.index("BUILDX_NO_DEFAULT_ATTESTATIONS=1 \"${COMPOSE[@]}\" up -d")
    assert detect < converge, (
        "the publication is measured after the converge that takes it away"
    )
    assert bootstrap.count("PUBLISHED_BEFORE") >= 3, (
        "it is measured and warned about once, so the operator is told before the slow "
        "part and not when it has finished"
    )
    warning = bootstrap[detect:converge]
    assert "make up-panel-over-ssh" in warning and "make up-panel" in warning


def test_no_management_tunnel_is_generated_from_the_templates_own_values(
    bootstrap: str,
) -> None:
    """Finding 6: a rebuild printed two device private keys nobody asked for.

    ``.env.example`` ships a complete ``HASHI_MGMT_*`` block, so the presence check passed
    on a machine that had copied the template, and the generator did what it is for — at
    an operator who wanted a control plane back, with an endpoint that is not this host.

    The value is read out of ``.env.example`` exactly as the password hash's placeholder
    is, so a template that changes cannot leave a stale copy behind in the script.
    """
    placeholder = next(
        line.split("=", 1)[1]
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line.startswith("HASHI_MGMT_ADDRESS=")
    )
    assert placeholder.strip(), (
        "the template ships an empty HASHI_MGMT_ADDRESS, so this check is dead code — "
        "either restore the example value or delete the comparison"
    )
    assert placeholder not in bootstrap, "the template's value is hardcoded here"
    assert "mgmt_is_the_template" in bootstrap
    checked = bootstrap.split("mgmt_is_the_template() {", 1)[1].split("\n}", 1)[0]
    assert "TEMPLATE" in checked
    # Three lines and not one: an address range and a pair of peer addresses are values
    # somebody could genuinely choose, so the endpoint travels with them and the message
    # names whichever matched.
    for key in ("HASHI_MGMT_ADDRESS", "HASHI_MGMT_ENDPOINT", "HASHI_MGMT_PEERS"):
        assert key in checked
    # Skipped and not refused: a host with no tunnel is a real mode and is the mode every
    # restored machine is in, so this must not be able to stop a rebuild.
    skip = bootstrap.split("mgmt_is_the_template; then", 1)[1].split("elif", 1)[0]
    assert "exit" not in skip, "an unfilled tunnel block stops the install"
    assert "NO" in skip and "management tunnel" in skip


# --- 6. one stream, and a port nobody should have to go and find -------------


def test_a_restore_keeps_psql_off_the_operators_other_stream(backup: str) -> None:
    """~90 command tags and a build log on stdout, between two sentences on stderr.

    Everything this script says to a person is on stderr; the restore's own plumbing was
    the one thing on the other stream, which is what put six kilobytes between
    *"restoring…"* and the screen saying what the restore did not do.
    """
    restores = [line for line in backup.splitlines() if re.search(r"^\s*psql ", line.strip())]
    assert restores, "no psql invocation found, so this test is measuring nothing"
    for line in backup.split("command_restore() {", 1)[1].split("\n}\n", 1)[0].splitlines():
        if "--set=ON_ERROR_STOP=on" in line:
            assert ">&2" in line, f"psql still writes its command tags to stdout: {line}"
    assert backup.count("--quiet \\\n") + backup.count("--quiet ") >= 2


def test_the_bootstrap_inside_a_restore_writes_to_the_same_stream_as_the_rest(
    backup: str,
) -> None:
    """Its progress goes to stdout when it is run on its own, which is right there."""
    call = [
        line for line in backup.splitlines() if "panel-bootstrap.sh" in line and "if !" in line
    ]
    assert call and "1>&2" in call[0], call


def test_the_closing_screen_prints_the_console_port_it_read(backup: str) -> None:
    """Finding 8: it printed ``<panel port>`` and sent the operator to find it in .env.

    Which is a file this script deliberately never opens — while the value was already in
    a container it was about to ask something else of.
    """
    assert "private_port()" in backup
    body = backup.split("private_port() {", 1)[1].split("\n}", 1)[0]
    assert "printenv HASHI_PRIVATE_PORT" in body
    screen = backup.split("Three things it did NOT do", 1)[1]
    assert "<panel port>" not in screen, (
        "the closing screen still asks the operator to go and look the port up"
    )
    assert "ssh -L ${console}:127.0.0.1:${console}" in screen


def test_the_crontab_block_calls_the_record_a_channel() -> None:
    """It said *account*, in the one paragraph explaining what happens when mail does not
    exist — where the word is *channel*, as it is everywhere else this is written down."""
    block = INSTALLER.read_text().split("\nour_block() {", 1)[1].split("\n}", 1)[0]
    assert "is the channel that does not depend on mail existing" in block
    assert "is the account that does not depend" not in INSTALLER.read_text()


# --- 7. the bucket a rebuilt host reads by default ---------------------------


def test_the_preflight_says_where_each_value_came_from_and_not_that_it_resolves() -> None:
    """*"the configuration resolves"* one line above ``Name or service not known``.

    The four non-secret fields fall back to the env file's ``HASHI_BACKUP_S3_`` block,
    which on a machine rebuilt from the template is the template's example store. Saying
    which name each value came from is what turns that into something read BEFORE the
    failure.
    """
    fetcher = FETCHER.read_text()
    assert "the configuration resolves" not in fetcher
    assert "def sources()" in fetcher
    body = fetcher.split("def sources()", 1)[1].split("\ndef ", 1)[0]
    for name in ("ENDPOINT", "REGION", "BUCKET", "PREFIX"):
        assert name in body
    assert "FALLBACK" in body
    assert ".env.example" in body, (
        "nothing says that a value out of the env file on a rebuilt host is the "
        "template's, which is the whole reason this is printed"
    )


def test_the_env_file_names_the_restore_side_block_where_the_backup_one_is() -> None:
    """The walker had to read a trailing comment at the bottom of the file to learn the
    four ``HASHI_RESTORE_S3_`` names exist. They are named in the block they fall back to
    now, and in the runbook's own command."""
    template = ENV_EXAMPLE.read_text()
    backup_block = template.split("HASHI_BACKUP_S3_ENDPOINT=", 1)[0][-1400:]
    assert "HASHI_RESTORE_S3_ENDPOINT" in backup_block, (
        "the block a restore falls back to does not mention that a restore reads it"
    )


def test_the_runbook_restore_block_no_longer_says_nothing_else_is_needed() -> None:
    """It cost a whole failed run: the control plane was installed and then died at a host
    out of the template, because the sentence was true of starting the stack and false of
    reading the bucket."""
    section = RUNBOOK.read_text().split("### Coming back from the bucket")[1]
    command = section.split("```")[1]
    assert "Nothing else is needed" not in section
    for name in (
        "HASHI_RESTORE_S3_ENDPOINT",
        "HASHI_RESTORE_S3_REGION",
        "HASHI_RESTORE_S3_BUCKET",
        "HASHI_RESTORE_S3_PREFIX",
    ):
        assert name in command, f"{name} is not in the command an operator pastes"


def test_the_runbook_says_which_second_run_is_not_safe() -> None:
    """"It is safe to run again after any failure" is printed by the command itself, so
    the one thing it is not safe for belongs beside it rather than under another
    heading."""
    section = RUNBOOK.read_text().split("### Coming back from the bucket")[1]
    section = section.split("### What `make restore-from-bucket` does not do")[0]
    assert "publication" in section and "up-panel" in section
    assert "HASHI_MGMT_" in section, (
        "the section does not mention that a tunnel is not generated from the template"
    )
