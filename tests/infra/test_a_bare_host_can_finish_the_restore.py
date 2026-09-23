"""What the bare-host walk found, and what now answers it — M28.10.

WHAT: static checks over the pieces that a restore on a genuinely bare machine walks
      through: ``scripts/hash-password.sh``, the confirmation and closing screen of
      ``scripts/backup.sh``, ``scripts/panel-bootstrap.sh``'s refusals, the two
      publication overlays and the Make targets that load them.
WHY:  a control plane was destroyed on one host and restored on another on 2026-09-23.
      The restore worked. What failed was the milestone's own measure — *the walk fails
      if the operator had to read anything other than the command to get there* — and
      six things made that untrue. Each of them is a place where the command was silent,
      or said something that was false on the one machine it exists for: a value that
      could not be produced there, a question asked into a session that could not answer,
      an instruction that would take the panel away, a publication needing an address the
      host does not have, a fleet that is no longer backed up and nothing saying so, and
      a diagnostic that ran a program a bare host does not carry.
HOW:  read, not run. Findings 1–4 are ultimately proven by a second walk on real hosts
      and not by any suite — that is stated in the plan and is not softened here. What a
      tree can hold is held here: that the command still SAYS the thing, still says it at
      the moment it is needed, and still cannot quietly do the version that was wrong.

      The behavioural halves that can be run live in
      ``tests/e2e/infra/test_restore_proves_the_backup.py`` (a rebuild driven with no
      terminal and no ``FORCE``) and
      ``tests/e2e/infra/test_the_hash_can_be_made_on_the_host.py`` (the hash produced
      inside the image, and verified against the password it was made from).
"""

import pathlib
import re
import stat

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
BACKUP = SCRIPTS / "backup.sh"
BOOTSTRAP = SCRIPTS / "panel-bootstrap.sh"
HASH_PASSWORD = SCRIPTS / "hash-password.sh"
MAKEFILE = REPO / "Makefile"
ENV_EXAMPLE = REPO / ".env.example"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"
PUBLIC_OVERLAY = REPO / "deploy" / "docker-compose.public.yml"
TUNNEL_OVERLAY = REPO / "deploy" / "docker-compose.tunnel.yml"

# Every shell surface in this project, for the sweeps at the bottom. The same list the
# other audits keep: add a script here rather than building a second one.
SHELL_SURFACES = sorted(SCRIPTS.glob("*.sh")) + sorted((SCRIPTS / "lib").glob("*.sh"))


def code_only(script: str) -> str:
    """The script with its comments and the text it PRINTS removed.

    Every one of these scripts explains itself at length and quotes the wrong version of
    a line beside the right one — ``# NOT `make down && make up`, which is what this line
    used to say`` is a comment whose whole job is to name the thing that must not happen.
    An assertion over raw text measures the prose.
    """
    kept, terminator = [], None
    for line in script.splitlines():
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        if line.lstrip().startswith("#"):
            continue
        opened = re.search(r"<<-?\s*'?([A-Za-z_][A-Za-z_0-9]*)'?", line)
        if opened:
            terminator = opened.group(1)
        kept.append(line)
    return "\n".join(kept)


@pytest.fixture(scope="module")
def backup() -> str:
    return BACKUP.read_text()


@pytest.fixture(scope="module")
def bootstrap() -> str:
    return BOOTSTRAP.read_text()


@pytest.fixture(scope="module")
def makefile() -> str:
    return MAKEFILE.read_text()


# --- 1. the one value that could not be made on the machine that needs it ------

def test_the_hash_is_produced_on_the_host_inside_the_control_image() -> None:
    """Finding 1, and the shape of the answer matters as much as its existence.

    The hash is a scrypt digest from ``control/app/crypto.py``, so producing it needs this
    project's code and Python 3.14. A host rented an hour ago has neither: the walk got
    ``python3 -m control.cli hash-password`` -> traceback and ``make setup`` ->
    ``python3.14: No such file or directory``. The image has all three and the restore
    builds it anyway, which is the same answer this project already gives for ``pg_dump``
    and for ``age`` — the tool lives where the stack lives.
    """
    assert HASH_PASSWORD.is_file()
    assert HASH_PASSWORD.stat().st_mode & stat.S_IXUSR, (
        "a script an operator has to invoke through `bash` is one they mistype"
    )
    script = HASH_PASSWORD.read_text()
    assert "deploy/docker/control.Dockerfile" in script, "it builds something else"
    assert "-m control.cli hash-password" in script, (
        "the hash is computed somewhere other than the command that owns it — a second "
        "implementation of a password hash is one that will disagree with the first"
    )
    assert "--entrypoint" in script, (
        "without --entrypoint the image boots the control plane and answers about a "
        "database instead of prompting for a password"
    )


def test_making_the_hash_needs_no_env_file(makefile: str) -> None:
    """The ordering is the whole reason this works, so it is asserted rather than hoped.

    The operator needs the hash in order to write ``.env``; the image is built from a
    checkout and needs no ``.env`` to build. A `docker compose` call here would reverse
    that — compose reads the env file, and every interpolation in the base stack carries a
    ``:?`` guard, so it would refuse on the file this command exists to help fill in.
    """
    code = code_only(HASH_PASSWORD.read_text())
    assert "docker compose" not in code, (
        "compose reads the env file; this runs before there is one to read"
    )
    assert "--env-file" not in code
    assert not re.search(r"\.env\b", code), "something here opens or names the env file"
    assert "hash-password:" in makefile, "there is no Make target for it"


def test_the_refusals_name_the_command_that_works_here(bootstrap: str) -> None:
    """Said at the moment it is needed, not in a document the operator has to find.

    The walk met the bootstrap's refusal, followed it to ``.env.example``, followed that
    to ``python -m control.cli hash-password``, and arrived at a machine that cannot run
    it. Three hops, ending nowhere. Both ends now name the command that works on the host
    the operator is standing on.
    """
    assert "make hash-password" in bootstrap
    assert "make hash-password" in ENV_EXAMPLE.read_text()
    # And the old route is kept beside it: on a machine that has the project set up it is
    # the same command without a build, and deleting it would make this worse there.
    assert "python -m control.cli hash-password" in ENV_EXAMPLE.read_text()


def test_the_runbook_names_it_before_the_command_it_is_needed_for() -> None:
    """Order on the page is the whole of it: after the restore line it is a footnote.

    The block used to say *"fill in HASHI_SECRET_KEY, the hostnames, the operator password
    hash and the database password. Nothing else is needed"* — and one of those four could
    not be made on the machine.
    """
    runbook = RUNBOOK.read_text()
    section = runbook.split("### Coming back from the bucket")[1]
    hashing = section.index("make hash-password")
    restoring = section.index("make restore-from-bucket")
    assert hashing < restoring, (
        "the way to produce the hash comes after the command that needs it to already be "
        "in the env file"
    )


def test_an_unfilled_hash_is_refused_at_once_rather_than_three_minutes_later(
    bootstrap: str,
) -> None:
    """The placeholder is non-empty, so a presence check passes and the failure moves.

    Left as it ships, the control plane refuses to boot on a hash that is not one — which
    arrives at the end of this script as a health-check timeout whose message is about a
    container that did not answer, with nothing in it about a password.

    The placeholder is READ OUT of ``.env.example`` rather than written into the script,
    so the two cannot drift; a copy here would be a copy that goes stale silently.
    """
    placeholder = next(
        line.split("=", 1)[1]
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line.startswith("HASHI_OPERATOR_PASSWORD_HASH=")
    )
    assert placeholder.strip(), (
        "the template ships an EMPTY hash, so this refusal is now dead code — either "
        "restore the placeholder or delete the check that looks for it"
    )
    assert placeholder not in bootstrap, "the placeholder is hardcoded here and will drift"
    assert ".env.example" in bootstrap
    assert "HASHI_OPERATOR_PASSWORD_HASH" in bootstrap


# --- 2. a question nobody could answer, about data that was not there ----------

def test_a_restore_measures_what_it_is_about_to_replace(backup: str) -> None:
    """Finding 2's first half: the prompt described nothing, in exactly this case.

    *"Every current node, user and credential is overwritten"* was printed on every
    restore, including onto a control plane installed minutes earlier that held a migrated
    schema and no rows. A prompt that overstates what it protects is one an operator
    learns to type through.

    The count names no table of ours — it is discovered from the catalogue, so it stays
    true across a schema change — and the one name it does mention is alembic's own
    bookkeeping row, which is nobody's data and which the dump replaces anyway.
    """
    assert "rows_at_stake()" in backup
    measured = re.search(r"rows_at_stake\(\) \{\n((?:.*\n)*?)^\}$", backup, re.MULTILINE)
    assert measured, "the measurement is no longer a function"
    body = measured.group(1)
    assert "information_schema.tables" in body
    assert "query_to_xml" in body
    named = set(re.findall(r"'([a-z_]+)'", body)) - {"public", "BASE TABLE", "/row/c/text()"}
    assert named <= {"alembic_version"}, (
        f"the count names {sorted(named)}; a table name in this script is a copy of the "
        "schema that stops being true the next time the schema moves"
    )


def test_an_empty_database_is_told_rather_than_asked(backup: str) -> None:
    """The case the command exists for asks nothing, because there is nothing to ask.

    A question whose true answer is always yes is a step, and a step on the way out of a
    seizure is a step that gets skipped or done wrong.
    """
    confirmation = code_only(backup)
    assert "Nothing here is being overwritten, so there is nothing to confirm." in backup
    empty_branch = confirmation.index('"${at_stake}" = "0"')
    asked = confirmation.index("read -r answer")
    assert empty_branch < asked, (
        "the prompt is reached before the count is branched on, so an empty database is "
        "still asked to authorise the replacement of nothing"
    )


def test_a_question_that_cannot_be_answered_is_not_printed(backup: str) -> None:
    """Finding 2's second half, measured on the walk: prompt, EOF, exit 2, no sentence.

    And it happened *after* installing a control plane and fetching an artifact. Nothing
    in the runbook's command block said a terminal was needed.
    """
    assert "no_terminal_refusal()" in backup
    code = code_only(backup)
    guard = code.index("[ -t 0 ] || no_terminal_refusal")
    asked = code.index("read -r answer")
    assert guard < asked, "the question is printed first and the silence is read afterwards"
    assert "FORCE=1" in backup, "the refusal does not say how to mean it deliberately"


def test_the_refusal_comes_before_the_bucket_is_read(backup: str) -> None:
    """Nothing is fetched to find out that nothing can be restored.

    Whether there is anything to lose cannot be known before the control plane is
    installed — until then there is no database on this machine at all — so section 3 is
    the earliest this can be asked. It is asked there.
    """
    rebuild = re.search(
        r"command_restore_from_bucket\(\) \{\n((?:.*\n)*?)^\}$", backup, re.MULTILINE
    )
    assert rebuild, "the rebuild is no longer a function"
    body = code_only(rebuild.group(1))
    checked = body.index("no_terminal_refusal")
    fetched = body.index("fetch_run preflight")
    assert checked < fetched, (
        "the run installs, fetches and only then discovers it cannot ask the question"
    )


# --- 3. the instruction that would have taken the panel away -------------------

def test_the_restore_does_not_end_by_unpublishing_the_host(backup: str, makefile: str) -> None:
    """Finding 3: the screen contradicted itself between "restored" and "logged in".

    It said *"Restart the control plane so it reconnects: make down && make up"*, which on
    a deployed host converges the stack back to the base file's shape and takes every
    published port away — the Makefile's own comment on ``up-panel`` warns against exactly
    that — and two paragraphs later the same screen said ``make up-panel``.
    """
    assert "make down && make up" not in code_only(backup), (
        "the restore still tells a deployed host to run the one sequence that unpublishes it"
    )
    assert "make restart-control" in backup
    assert "restart-control:" in makefile
    recipe = makefile.split("restart-control:")[1].splitlines()[1]
    assert "restart" in recipe
    assert "down" not in recipe and "up -d" not in recipe, (
        "restart-control brings the stack down or up, so it decides what this host "
        "publishes — which is the whole thing it exists not to do"
    )


# --- 4. a publication that needs an address a fresh restore does not have ------

def test_a_host_with_no_tunnel_can_still_publish_the_panel(makefile: str) -> None:
    """Finding 4: ``make up-panel`` wants an address a rebuilt machine does not hold.

    ``HASHI_PRIVATE_BIND_ADDR`` is the management tunnel's address on this host, and a
    restored machine has no tunnel — its keys were on the box that was lost. Loopback is
    refused because the fallback mapping already claims that port. The walk answered it
    with ``ip addr add``, by hand, at the point where the operator cannot log in yet.

    So the mapping that needs a tunnel is a file of its own, and everything a deployed host
    publishes regardless is in the other. Neither publishes the console on an address the
    internet can reach — that property is checked in ``test_compose.py`` over both files.
    """
    assert TUNNEL_OVERLAY.is_file()
    assert "HASHI_PRIVATE_BIND_ADDR" in TUNNEL_OVERLAY.read_text()
    assert "HASHI_PRIVATE_BIND_ADDR" not in PUBLIC_OVERLAY.read_text(), (
        "the mapping that needs a tunnel address is still in the file a host with no "
        "tunnel has to load"
    )
    assert "127.0.0.1:" in PUBLIC_OVERLAY.read_text(), (
        "the loopback fallback moved out of the always-published file, so the `ssh -L` "
        "way in now depends on having the tunnel it exists to work without"
    )

    assert "up-panel-over-ssh:" in makefile
    over_ssh = makefile.split("up-panel-over-ssh:")[1].splitlines()[1]
    assert "COMPOSE_PANEL_SSH" in over_ssh
    up_panel = makefile.split("\nup-panel:")[1].splitlines()[1]
    assert "COMPOSE_PANEL)" in up_panel or "COMPOSE_PANEL " in up_panel
    # `up-panel` is both files and means exactly what it meant; the new target is the
    # first alone. Changing what an existing verb means is what this project's rulebook
    # forbids, so the composition is asserted rather than left to a reader.
    definitions = {
        line.split(":=")[0].strip(): line
        for line in makefile.splitlines()
        if ":=" in line and line.startswith("COMPOSE_PANEL")
    }
    assert "docker-compose.public.yml" in definitions["COMPOSE_PANEL_SSH"]
    assert "docker-compose.tunnel.yml" not in definitions["COMPOSE_PANEL_SSH"]
    assert "docker-compose.tunnel.yml" in definitions["COMPOSE_PANEL"]


def test_the_loopback_refusal_names_the_command_instead_of_a_document(
    bootstrap: str, backup: str
) -> None:
    """The refusal pointed at the runbook, which is one more thing to read.

    Its advice was also incomplete: "leave the variable unset and reach the panel over
    SSH" is correct and there was no command that did it.
    """
    assert "make up-panel-over-ssh" in bootstrap
    assert "make up-panel-over-ssh" in backup, (
        "the closing screen of a rebuild still offers only the publication that needs a "
        "tunnel this machine does not have"
    )


# --- 5. a restored fleet is an unbacked-up fleet -------------------------------

def test_a_restored_host_is_told_that_nothing_is_backing_it_up(backup: str) -> None:
    """Finding 5, and the silence is the finding.

    The write-only S3 key and the age recipient lived only in the ``.env`` that was lost —
    deliberately, because that file is in no backup — so the machine rebuilt OUT of the
    backup history is the one machine that cannot add to it. ``make backup`` there refuses
    outright and the panel truthfully reports that nothing has been recorded, which reads
    as a new host rather than as a gap.

    Measured rather than asserted: the same compose check a dump makes, whose complaint is
    discarded rather than printed — repeating what compose says about an env file is how
    M28.7's leak worked.
    """
    screen = backup.split("# --- 6. and what it did not do")[1]
    assert "HASHI_BACKUP_AGE_RECIPIENT" in screen
    assert "make backup-schedule" in screen
    # Both branches, because only one of them can be exercised by any single run. The
    # e2e rescue host carries no recipient — which is what a rebuilt host really looks
    # like — so it reads the first; the second is what a host whose recipient survived
    # is told, and it is text only.
    assert "this host is NOT backing anything up" in screen
    assert "nothing is SCHEDULED" in screen
    measurement = [
        line for line in screen.splitlines() if "COMPOSE_BACKUP" in line and "config" in line
    ]
    assert measurement, "the standing is asserted rather than measured"
    assert all(">/dev/null 2>&1" in line for line in measurement), (
        "compose's complaint about the env file reaches the screen — M28.7"
    )


# --- 6. a diagnostic that ran a program a bare host does not have --------------

@pytest.mark.parametrize("path", SHELL_SURFACES, ids=lambda p: p.name)
def test_no_operator_facing_heredoc_runs_a_command(path: pathlib.Path) -> None:
    """Finding 6, generalised to the class rather than to the one line that had it.

    ``scripts/backup.sh``'s wrong-identity message read *"the one `age-keygen` printed
    when the pair was made"* inside a heredoc that interpolates — so the backticks RAN.
    On the bare host the walk used that printed ``age-keygen: command not found`` and lost
    the words it meant to show; on a host that has the tool it would have generated a
    keypair and spliced it into the sentence.

    This is the second time in this one script: ``command_upload``'s heredoc is quoted
    with a comment saying it ran a ``make`` target the first time it was written. So the
    rule is a test now. Backticks only, deliberately: ``$( )`` is how this project writes
    substitution it MEANS, and one heredoc — the record writer — is built from it.
    """
    lines = path.read_text().splitlines()
    index, offences = 0, []
    while index < len(lines):
        # `(?<!<)<<(?!<)` because `<<<` is a herestring and because this project prints
        # one: scripts/backup-schedule.sh carries `# <<< hashi backup schedule <<<` as the
        # closing marker of the block it writes into a crontab, and a parser that reads
        # that as a heredoc swallows the rest of the file and sweeps nothing.
        opened = re.search(
            r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\1", lines[index]
        )
        if not opened:
            index += 1
            continue
        tag, quoted = opened.group(2), bool(opened.group(1))
        end = index + 1
        while end < len(lines) and lines[end].strip() != tag:
            end += 1
        if not quoted:
            offences += [
                f"{path.name}:{n + 1}: {lines[n].strip()}"
                for n in range(index + 1, end)
                if re.search(r"(?<!\\)`", lines[n])
            ]
        index = end + 1
    assert offences == [], (
        "a backtick in a heredoc that interpolates is a command this script runs at the "
        "operator: " + "; ".join(offences)
    )
