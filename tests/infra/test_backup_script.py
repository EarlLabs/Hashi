"""The backup script's contract — backlog item 22.

WHAT: static checks over ``scripts/backup.sh`` and the Make targets that call it.
WHY:  the control database is the one thing whose loss cannot be repaired by
      rebuilding a node (core invariants §3), and a backup routine is only ever tested
      by an emergency. The properties here are the ones whose absence would be
      discovered at exactly the wrong moment: a restore that half-succeeds, a dump left
      world-readable, a dump silently useless because nobody was told the key is
      needed to restore it, or — since M28.2 — a dump that wrote the fleet's addresses
      to the disk in the clear on its way to being encrypted.
HOW:  the script is read, not run — running it needs a booted stack, and that belongs to
      the e2e tier. What is provable by the tree is proven here, which is the rule this
      project's acceptance follows.

      Stated plainly: nothing here proves a dump restores. It proves the script cannot
      quietly do the dangerous version of each step.
"""

import pathlib
import re
import stat

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "backup.sh"
MAKEFILE = REPO / "Makefile"
# The one variable compose reads out of the env file on the script's behalf — see the
# file's own header for why it is not in docker-compose.yml.
BACKUP_OVERLAY = REPO / "deploy" / "docker-compose.backup.yml"


def body_of(script: str, function: str) -> str:
    """The lines of one shell function, so an assertion can be about ORDER inside it.

    "The dump is encrypted before it is written" is a claim about the order of stages in
    one pipeline, and a test that only asks whether two strings are both somewhere in the
    file cannot tell that claim from its opposite.
    """
    match = re.search(rf"^{function}\(\) \{{\n((?:.*\n)*?)^\}}$", script, re.MULTILINE)
    assert match, f"{function} is no longer a function in this script"
    return match.group(1)


def code_of(script: str, function: str) -> str:
    """The same body with comments and printed text removed.

    Needed because everything this script does is also EXPLAINED in this script: the
    comment above the pipeline names ``pg_dump``, and the operator-facing heredocs name
    age and the env file. An order assertion over the raw text measures the prose.
    """
    kept, terminator = [], None
    for line in body_of(script, function).splitlines():
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        if line.lstrip().startswith("#"):
            continue
        opened = re.search(r"<<'?([A-Z]+)'?", line)
        if opened:
            terminator = opened.group(1)
        kept.append(line)
    return "\n".join(kept)


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


def test_the_script_exists_and_is_executable() -> None:
    """A backup script that has to be invoked via `bash` is one an operator mistypes."""
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_it_fails_the_whole_run_on_any_error(script: str) -> None:
    """``set -euo pipefail``.

    Without ``pipefail`` the dump is the case that bites: ``pg_dump | gzip`` reports
    gzip's exit status, so a failed dump writes a small, valid, EMPTY archive and the
    script says it succeeded.
    """
    assert re.search(r"^set -euo pipefail$", script, re.MULTILINE)


def test_the_dump_is_not_world_readable(script: str) -> None:
    """It holds every node's credentials and every user's token, encrypted.

    Encrypted at rest is not a reason to leave the file readable by every account on
    the host — it is one layer, and the charter's threat model includes a host that is
    not exclusively ours.
    """
    assert "chmod 600" in script


def test_every_run_says_the_dump_needs_the_secret_key(script: str) -> None:
    """The one thing an operator can get catastrophically wrong.

    A dump without ``HASHI_SECRET_KEY`` restores nothing, and the moment that is
    discovered is the moment it cannot be fixed. So the warning is unconditional
    output, not documentation.
    """
    assert "HASHI_SECRET_KEY" in script
    assert "cannot be restored" in script


def test_a_restore_is_all_or_nothing(script: str) -> None:
    """``ON_ERROR_STOP`` and ``--single-transaction``.

    Without both, a failed restore leaves a half-populated database that looks
    restored: some users back, some not, and no error anywhere.
    """
    assert "ON_ERROR_STOP=on" in script
    assert "--single-transaction" in script


def test_a_restore_asks_before_replacing_live_data(script: str) -> None:
    """Destructive and undoable, so it is confirmed — and skippable only deliberately."""
    assert "FORCE:-0" in script
    assert "read -r" in script


def test_the_script_never_reads_the_env_file_itself(script: str) -> None:
    """Hard rule: never read or print ``.env``.

    Connection details come from ``printenv`` inside the container via compose, so the
    real file is never opened, sourced or echoed by this script.
    """
    assert "printenv" in script
    # Over CODE only: the script's own header explains at length why it must not touch
    # .env, and that explanation names the file.
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in (r"cat\s+\.env", r"source\s+\.env", r"^\s*\.\s+\.env", r"grep.*\.env"):
        assert not re.search(forbidden, code, re.MULTILINE), forbidden


def test_compose_is_always_invoked_with_an_env_file(script: str) -> None:
    """Without ``--env-file`` every ``${VAR}`` silently becomes an empty string."""
    for line in script.splitlines():
        if "docker compose" in line and "--env-file" not in line:
            pytest.fail(f"compose without --env-file: {line.strip()}")


def test_make_restore_refuses_to_guess_which_dump(script: str) -> None:
    """"The newest one" is not a decision a Makefile should make during an incident."""
    makefile = MAKEFILE.read_text()
    assert "restore:" in makefile
    assert 'test -n "$(FROM)"' in makefile
    assert "backup:" in makefile


def test_the_dump_is_encrypted_before_it_reaches_the_disk(script: str) -> None:
    """The order of the stages, not merely their presence — M28.2.

    A pipeline that dumps to a file and encrypts it afterwards satisfies "the artifact is
    encrypted" and leaves a map of the fleet on the disk of the machine most likely to be
    seized, for as long as the encryption takes. So this asserts the shape: pg_dump, gzip,
    age, and only THEN a redirection. The only thing that is ever written is ciphertext.
    """
    dump = code_of(script, "command_dump")
    dumped = dump.index("pg_dump")
    compressed = dump.index("gzip -9", dumped)
    encrypted = dump.index("age --recipient", compressed)
    # The first redirection AFTER the dump begins is the one that ends this pipeline.
    written = dump.index('> "${partial}"', dumped)
    assert written > encrypted, (
        "the artifact is redirected to a file before age has seen it — that is plaintext "
        "on the disk of the host this whole design assumes will be taken"
    )
    assert "pg_dump" not in dump[written:], "a second dump path bypasses the encryption"


def test_the_dump_refuses_rather_than_falling_back_to_plaintext(script: str) -> None:
    """No recipient configured is a refusal, and it happens before the database is read.

    A fallback would be how the plain shape survives: the one run where the variable was
    blank is the one artifact that ends up somewhere public. Resolving the recipient FIRST
    also means the refusal costs nothing — no dump has run and no file exists yet.
    """
    dump = code_of(script, "command_dump")
    assert "config --quiet" in dump, "nothing checks the recipient resolves before dumping"
    assert dump.index("config --quiet") < dump.index("pg_dump"), (
        "the recipient is checked after the dump has already run"
    )
    assert re.search(r"exit 1", dump), "a missing recipient does not fail the run"


def test_the_script_no_longer_says_the_artifact_is_unencrypted(script: str) -> None:
    """The sentence M28.1 made true, and M28.2 has to make false in the same breath.

    Deliberate wording was left in this script saying the file is NOT encrypted. It was
    correct then and is a lie now; this is the test that stops it coming back with the
    behaviour, in either direction.
    """
    assert "NOT encrypted" not in script
    assert not re.search(r"not encrypted", script, re.IGNORECASE)
    assert "age --recipient" in script, "nothing in this script encrypts anything"


def test_a_restore_takes_the_identity_at_the_moment_it_runs(script: str) -> None:
    """``HASHI_RESTORE_AGE_IDENTITY``, streamed in, never written down.

    The whole value of a keypair is that the host holds one half. A restore that copied
    the identity onto the box — into a file, a container, or the env file — would undo
    that at the one moment the operator is least able to notice.
    """
    assert "HASHI_RESTORE_AGE_IDENTITY" in script
    assert "--identity -" in script, (
        "the identity is not streamed to age on stdin, so it is a path inside something"
    )
    restore = code_of(script, "command_restore")
    assert not re.search(r'cat\s+"\$\{identity\}"', restore), "the identity is copied somewhere"
    assert not re.search(r'>\s*\S*identity', restore), "something writes an identity file"


def test_an_artifact_from_before_the_encryption_still_restores(script: str) -> None:
    """Plain ``.sql.gz`` files exist in the world and must still come back.

    And the shape is read out of the FILE rather than its name: the operator who needs
    this most is restoring something somebody else named, at an hour when a confusing
    error costs more than the backup did.
    """
    assert "age-encryption.org/v1" in script, "nothing recognises the encrypted shape"
    assert "1f8b" in script, "nothing recognises the gzip shape, so an old dump is refused"
    restore = code_of(script, "command_restore")
    assert "artifact_kind" in restore
    assert 'kind="$(artifact_kind "${input}")"' in restore
    # The refusal an operator meets when the file is neither shape has to say so rather
    # than failing somewhere inside gunzip.
    assert "neither shape this script can restore" in script


def test_the_shape_is_settled_before_the_destructive_confirmation(script: str) -> None:
    """Nobody is asked to authorise a restore that was already going to refuse.

    Typing the database name is the operator saying "yes, replace live data". Being told
    afterwards that the identity is missing means that consent was collected for nothing,
    at an hour when the second attempt is where mistakes happen.
    """
    restore = code_of(script, "command_restore")
    assert restore.index("artifact_kind") < restore.index("Type the database name")


def test_the_recipient_is_read_out_of_the_env_file_by_compose_and_not_by_this_script(
    script: str,
) -> None:
    """Hard rule again: the script does not open the env file, for the recipient either.

    Compose is the one thing allowed to read it, so the value is interpolated into a
    one-off container and never passes through the script — which is why the overlay
    exists at all, and why its guard lives there instead of in the base stack.
    """
    assert BACKUP_OVERLAY.is_file(), "the backup overlay is gone"
    assert BACKUP_OVERLAY.name in script, "the script no longer loads the backup overlay"
    overlay = BACKUP_OVERLAY.read_text()
    assert "HASHI_BACKUP_AGE_RECIPIENT:?" in overlay, (
        "the overlay does not guard the recipient, so an unset value becomes an empty "
        "string and age is asked to encrypt to nobody"
    )
    # The value is only ever named, never captured: no assignment of it anywhere.
    assert not re.search(r"^\s*\w*=.*HASHI_BACKUP_AGE_RECIPIENT", script, re.MULTILINE)
    assert "ports:" not in overlay and "services:\n  control:\n" in overlay, (
        "the backup overlay has grown beyond the one variable it exists for"
    )


def test_no_make_target_loads_the_backup_overlay() -> None:
    """A deployed stack never carries the recipient, because nothing needs it to.

    ``make up`` loading this file would put the variable in a long-lived container and
    make a blank recipient — which is what a host ships with — a reason the whole stack
    refuses to start.
    """
    assert "docker-compose.backup.yml" not in MAKEFILE.read_text()


# --- the upload, M28.3 --------------------------------------------------------

UPLOADER = REPO / "deploy" / "backup" / "upload.py"
UPLOAD_OVERLAY = REPO / "deploy" / "docker-compose.upload.yml"
BASE_COMPOSE = REPO / "deploy" / "docker-compose.yml"


@pytest.fixture(scope="module")
def uploader() -> str:
    return UPLOADER.read_text()


def test_the_upload_is_settled_before_the_database_is_read(script: str) -> None:
    """Same rule as the recipient: refuse while nothing has happened yet.

    A host whose offsite block is half filled in is the normal state of a host being set
    up. Discovering that after the dump leaves a fresh artifact on the disk and an operator
    deciding whether it is safe where it is; discovering it first costs nothing.
    """
    dump = code_of(script, "command_dump")
    assert "resolve_upload" in dump, "nothing works out whether this dump is going anywhere"
    assert dump.index("resolve_upload") < dump.index("pg_dump"), (
        "the upload is resolved after the database has already been read"
    )


def test_the_artifact_is_written_and_only_then_sent(script: str) -> None:
    """Send from the file, not from the pipeline.

    Uploading a stage of the pipe would mean the thing on this host and the thing in the
    bucket are two different streams, either of which could be the truncated one — and the
    local copy is what the operator is left holding when the store says no.
    """
    dump = code_of(script, "command_dump")
    assert dump.index('> "${partial}"') < dump.index("upload_artifact")


def test_a_failed_upload_keeps_the_artifact_and_has_an_exit_code_of_its_own(
    script: str,
) -> None:
    """Exit 3: the dump exists and it did not leave the machine.

    Neither 0 nor 1 would be true. 0 says an offsite backup happened; 1 says there is no
    backup and sends the operator to take another one, when what they are holding is a
    complete encrypted artifact that only needs sending. The panel (M28.6) keys on this
    distinction, so it is part of the script's contract and not an implementation detail.
    """
    upload = code_of(script, "upload_artifact")
    assert "exit 3" in upload, "a failed upload does not have its own exit code"
    assert not re.search(r"\brm\b", upload), (
        "the failure path deletes something — the artifact is the one thing the operator "
        "still has"
    )
    # And the operator is told how to send what they are holding, without dumping again.
    assert "make backup-upload FROM=" in script
    assert re.search(r"^#\s+3\s+the artifact WAS written", script, re.MULTILINE), (
        "the exit codes are not written down in the script's own header"
    )


def test_only_the_encrypted_shape_is_ever_sent_offsite(script: str) -> None:
    """A pre-M28.2 artifact is a readable map of the fleet, and a bucket is somebody else's.

    Those files exist in the world — the restore path still takes them on purpose — so the
    one thing that must be impossible is sending one to an object store. Sniffed from the
    file, like a restore, because the name proves nothing.
    """
    upload = code_of(script, "command_upload")
    assert 'artifact_kind "${input}"' in upload
    assert upload.index("artifact_kind") < upload.index("upload_artifact")
    assert "only an encrypted artifact is" in script


def test_the_credential_never_passes_through_the_script(script: str) -> None:
    """The secret reaches one container, from compose, and nothing else ever holds it.

    Not a variable in this script, not a command-line argument (a process list is readable
    by every account on the host), and not the environment of the long-running control
    plane, whose job is to face the internet.
    """
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "HASHI_BACKUP_S3_SECRET_ACCESS_KEY" not in code, (
        "the credential is named in this script, so it passes through it"
    )
    assert UPLOAD_OVERLAY.is_file(), "the upload overlay is gone"
    overlay = UPLOAD_OVERLAY.read_text()
    assert "HASHI_BACKUP_S3_SECRET_ACCESS_KEY" in overlay
    assert "ports:" not in overlay and "services:\n  control:\n" in overlay, (
        "the upload overlay has grown beyond the variables it exists for"
    )
    # The one-off container, and nothing else: no `up`, no `exec` into the running plane.
    assert re.search(r"COMPOSE_UPLOAD\[@\]\}\" run --rm --no-deps -T --entrypoint python3", script)
    assert "HASHI_BACKUP_S3" not in BASE_COMPOSE.read_text(), (
        "the base stack carries the bucket credential, so every control container has it"
    )
    assert "docker-compose.upload.yml" not in MAKEFILE.read_text(), (
        "a Make target loads the upload overlay, which puts the credential in the stack"
    )


def test_the_uploader_can_only_write(uploader: str) -> None:
    """One request, one method. There is no code path that reads, lists or deletes.

    The credential on the host is PutObject-and-nothing-else because whoever seizes the box
    holds it; a program that could delete would be a second place for that property to be
    lost, and the first time anybody noticed would be after a seizure.
    """
    methods = re.findall(r'putrequest\(\s*"([A-Z]+)"', uploader)
    assert methods == ["PUT"], f"the uploader issues {methods}"


def test_the_uploader_names_no_provider(uploader: str, script: str) -> None:
    """A reader of this code cannot tell which company holds the bucket — CLAUDE.md.

    The protocol's own wire constants are not a provider: a signature algorithm name and a
    header prefix are what every S3-compatible store implements, the same way every artifact
    this project writes begins ``age-encryption.org/v1``. Anything else is a provider you
    cannot rotate away from, written into code that was supposed to make it a field.
    """
    allowed = ("AWS4-HMAC-SHA256", "AWS4", "aws4_request", "x-amz-", "X-amz-", "x-amz")
    # A short list of the names a "just make it upload" implementation reaches for. It is a
    # negative list on purpose: naming one here forbids it, which is the opposite of the
    # thing the rule is about.
    providers = re.compile(
        r"aws|amz|amazon|google|azure|cloudflare|backblaze|wasabi|yandex|selectel|minio",
        re.IGNORECASE,
    )
    files = (
        (UPLOADER, uploader),
        (SCRIPT, script),
        (UPLOAD_OVERLAY, UPLOAD_OVERLAY.read_text()),
    )
    for path, text in files:
        stripped = text
        for literal in allowed:
            stripped = stripped.replace(literal, "")
        found = providers.findall(stripped)
        assert found == [], f"{path.name} names {sorted(set(found))}"


def test_the_uploader_never_prints_the_secret(uploader: str) -> None:
    """It is used to derive a signing key, in one place, and is printed nowhere.

    An upload is a new thing that prints, and the output of a backup run is the sort of
    thing that ends up in a mail spool, a terminal recording or — from M28.6 — a panel.
    """
    assert len(re.findall(r'config\["secret_key"\]', uploader)) == 1
    for line in uploader.splitlines():
        if re.search(r"say\(|Refusal\(", line):
            assert "secret_key" not in line, f"a message interpolates the secret: {line.strip()}"


def test_the_uploader_is_linted_by_this_zone() -> None:
    """A new directory of Python that no verify command reads is a new blind spot."""
    assert "deploy/backup" in MAKEFILE.read_text(), (
        "make test-infra does not lint deploy/backup, so nothing checks the uploader"
    )
