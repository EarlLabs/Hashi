"""The one command that brings the control plane back — M28.8.

WHAT: static checks over ``deploy/backup/fetch.py``, the ``restore-from-bucket`` verb of
      ``scripts/backup.sh``, the overlay that carries the read credential, and the runbook
      section beside them. Plus real unit tests of the fetcher's configuration, its
      listing and its signature, driven in-process against a fake store.
WHY:  this is the command that is used on the worst day this project has, by somebody
      frightened and in a hurry, and almost none of it can be exercised by the person who
      needs it before they need it. The properties here are the ones whose absence is
      discovered at exactly that moment: a credential silently read from the wrong place,
      a "newest" artifact chosen by a name an attacker can write, a refusal that says "it
      did not work" instead of which of the three inputs is wrong.
HOW:  the shell is read rather than run — running it needs a bare host, a bucket and a
      stack, and that is
      ``tests/e2e/infra/test_restore_proves_the_backup.py``'s S13. The Python IS run,
      because it is Python and there is no excuse not to.

      Stated plainly, so a green run is not read as more than it is: nothing here proves
      that an artifact comes back out of a real store. It proves the command cannot
      quietly do the dangerous version of each step.
"""

import importlib.util
import io
import pathlib
import re
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "backup.sh"
MAKEFILE = REPO / "Makefile"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"
ENV_EXAMPLE = REPO / ".env.example"
FETCHER = REPO / "deploy" / "backup" / "fetch.py"
UPLOADER = REPO / "deploy" / "backup" / "upload.py"
RESTORE_OVERLAY = REPO / "deploy" / "docker-compose.restore.yml"
BASE_COMPOSE = REPO / "deploy" / "docker-compose.yml"

# The runbook heading the command's own output and `.env.example` both point at. Renaming
# it fails the tests below rather than leaving two pointers into nothing.
RESTORE_SECTION = "Coming back from the bucket, on a machine that has never run this"
NOT_DONE_SECTION = "What `make restore-from-bucket` does not do"


def load(name: str, path: pathlib.Path) -> types.ModuleType:
    """One of the two programs, imported the way the e2e scenario imports the uploader."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


@pytest.fixture(scope="module")
def fetcher() -> str:
    return FETCHER.read_text()


@pytest.fixture(scope="module")
def fetch():
    return load("hashi_backup_fetcher", FETCHER)


@pytest.fixture(scope="module")
def upload():
    return load("hashi_backup_uploader_for_fetch_tests", UPLOADER)


def body_of(script: str, function: str) -> str:
    """The lines of one shell function, so an assertion can be about ORDER inside it."""
    match = re.search(rf"^{function}\(\) \{{\n((?:.*\n)*?)^\}}$", script, re.MULTILINE)
    assert match, f"{function} is no longer a function in this script"
    return match.group(1)


def code_of(script: str, function: str) -> str:
    """The same body with comments and printed text removed.

    Everything this command does is also EXPLAINED by it, at length, in comments and in
    heredocs the operator reads — so an order assertion over the raw text would be
    measuring the prose. Same helper and same reason as ``test_backup_script.py``'s.
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


# --- the two programs must not drift apart ------------------------------------


def test_the_two_programs_sign_a_request_identically(fetch, upload) -> None:
    """The one real cost of writing the signature out twice, pinned so it is paid once.

    ``fetch.py`` cannot import ``upload.py``: each is handed to a one-off container as a
    single ``-c`` argument read from the checkout, which is what keeps a restore from
    waiting on a rebuild. So the maths exists twice, and the failure mode of that is one of
    them being quietly corrected and the other not — a bug that shows up as a store
    refusing the credential on the day of a rebuild, which reads as the wrong key.
    """
    from datetime import UTC, datetime

    config = {
        "scheme": "https",
        "netloc": "store.example.invalid",
        "region": "example-region-1",
        "bucket": "a-bucket",
        "prefix": "control/",
        "access_key": "not-a-real-key-id",
        "secret_key": "not-a-real-secret",
    }
    fixed = datetime(2026, 9, 23, 4, 0, 0, tzinfo=UTC)
    assert fetch.signed(
        config, "PUT", "control/hashi-x.sql.gz.age", "deadbeef", now=fixed
    ) == upload.signed(config, "PUT", "control/hashi-x.sql.gz.age", "deadbeef", now=fixed)


def test_the_fetcher_can_only_read(fetcher: str) -> None:
    """One method, and no verb that could change anything in the bucket.

    The mirror of ``test_the_uploader_can_only_write``. This program runs on a machine
    being rebuilt, with a credential that is allowed to list and get — and a delete path
    here would mean the one command an operator runs while panicking is also the one that
    could empty the history they are restoring from.
    """
    methods = re.findall(r'putrequest\(\s*\n?\s*(?:method|"([A-Z]+)")', fetcher)
    issued = {found for found in methods if found}
    assert issued <= {"GET"}, f"the fetcher issues {sorted(issued)}"
    assert 'opened(config, "GET"' in fetcher, "no GET is issued at all, so nothing is read"
    for forbidden in ('"PUT"', '"DELETE"', '"POST"'):
        assert forbidden not in fetcher, f"the fetcher names the {forbidden} method"
    modes = re.search(r'mode not in \(([^)]*)\)', fetcher)
    assert modes, "the fetcher no longer declares which verbs it accepts"
    assert sorted(re.findall(r'"([a-z]+)"', modes.group(1))) == ["get", "list", "preflight"]


def test_neither_program_names_a_provider(fetcher: str, script: str) -> None:
    """CLAUDE.md's rule, in the file most likely to break it a second time.

    A restore is exactly where a bucket endpoint gets baked in — it is written under
    pressure and tested against one store. The protocol's own wire constants are not a
    provider: they are what every S3-compatible store implements. Everything else is a
    provider you cannot rotate away from on the day you need to leave it.
    """
    allowed = ("AWS4-HMAC-SHA256", "AWS4", "aws4_request", "x-amz-", "x-amz")
    # Loopback is not an address in the sense this rule is about. The rule exists so that
    # a country, a provider or a host cannot be baked into code you then cannot rotate
    # away from; `127.0.0.1` names no host and rotates nowhere — it is a constant of the
    # protocol, written as such in this project's compose files, its Makefile and its
    # runbook. M28.10 put it on this screen for one sentence: the `ssh -L` line an
    # operator needs when a restored host has no management tunnel yet, which is the one
    # route into the panel at that moment and is exactly the kind of step that must not
    # live in a document. Everything else that looks like an address still fails here.
    loopback = "127.0.0.1"
    providers = re.compile(
        r"aws|amz|amazon|google|azure|cloudflare|backblaze|wasabi|yandex|selectel|minio",
        re.IGNORECASE,
    )
    for path, text in (
        (FETCHER, fetcher),
        (SCRIPT, script),
        (RESTORE_OVERLAY, RESTORE_OVERLAY.read_text()),
    ):
        stripped = text
        for literal in allowed:
            stripped = stripped.replace(literal, "")
        assert providers.findall(stripped) == [], f"{path.name} names a provider"
        assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text.replace(loopback, "")), (
            f"{path.name} hardcodes an address"
        )


def test_the_fetcher_writes_nothing_to_stdout_but_what_was_asked_for(fetcher: str) -> None:
    """One stray byte on stdout is a corrupted artifact.

    ``get`` streams the object to stdout, so every message in this program goes to stderr
    through ``say``. The listing is the one deliberate exception, and it is one call.
    """
    bare = [
        line for line in fetcher.splitlines()
        if re.search(r"(?<![a-z_])print\(", line) and "file=sys.stderr" not in line
    ]
    assert len(bare) == 1 and "modified" in bare[0], (
        f"something other than the listing prints to stdout: {bare}"
    )


def test_the_fetcher_never_prints_the_credential(fetcher: str) -> None:
    """It derives a signing key in one place and appears in no output and no exception."""
    assert len(re.findall(r'config\["secret_key"\]', fetcher)) == 1
    for line in fetcher.splitlines():
        if re.search(r"say\(|Refusal\(", line):
            assert "secret_key" not in line, f"a message interpolates the credential: {line}"


# --- what the fetcher does with what it is given ------------------------------


def test_the_four_non_secret_fields_fall_back_and_the_credential_never_does(
    fetch, monkeypatch
) -> None:
    """Which store, which bucket: not secrets, already in the env file, and retyped wrong.

    The credential is the opposite case. Falling back to the write-only key in ``.env``
    would turn the clearest refusal this command has — "that key may only write" — into a
    403 from the store, which reads as the operator's own key being wrong.
    """
    for name in list(fetch.REQUIRED) + list(fetch.FALLBACK.values()) + [fetch.PREFIX]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HASHI_BACKUP_S3_ENDPOINT", "https://store.example.invalid")
    monkeypatch.setenv("HASHI_BACKUP_S3_REGION", "example-region-1")
    monkeypatch.setenv("HASHI_BACKUP_S3_BUCKET", "a-bucket")
    monkeypatch.setenv("HASHI_BACKUP_S3_PREFIX", "control")
    monkeypatch.setenv("HASHI_BACKUP_S3_ACCESS_KEY_ID", "the-write-only-key")
    monkeypatch.setenv("HASHI_BACKUP_S3_SECRET_ACCESS_KEY", "the-write-only-secret")

    with pytest.raises(fetch.Refusal) as refused:
        fetch.configuration()
    said = str(refused.value)
    assert fetch.ACCESS_KEY in said and fetch.SECRET_KEY in said
    assert "only write" in said, (
        "the refusal does not say that the key already on this host is the wrong one, "
        "which is the mistake an operator is most likely to have just made"
    )
    assert "the-write-only-secret" not in said

    monkeypatch.setenv(fetch.ACCESS_KEY, "the-carried-key")
    monkeypatch.setenv(fetch.SECRET_KEY, "the-carried-secret")
    config = fetch.configuration()
    assert config["bucket"] == "a-bucket"
    assert config["region"] == "example-region-1"
    # A prefix with no separator glues itself to the file name and the objects land beside
    # the folder the operator believes they are in.
    assert config["prefix"] == "control/"
    assert config["access_key"] == "the-carried-key"

    # And the restore-side names win over them, so a second bucket can be read without
    # touching the block this host writes to.
    monkeypatch.setenv(fetch.BUCKET, "another-bucket")
    assert fetch.configuration()["bucket"] == "another-bucket"


def test_every_missing_name_is_reported_at_once(fetch, monkeypatch) -> None:
    """A host being rebuilt is usually missing more than one, and one run at a time is
    three round trips nobody has that evening."""
    for name in list(fetch.REQUIRED) + list(fetch.FALLBACK.values()):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(fetch.Refusal) as refused:
        fetch.configuration()
    for name in fetch.REQUIRED:
        assert name in str(refused.value)


def test_plain_http_to_a_public_address_is_refused(fetch, monkeypatch) -> None:
    """The artifact is ciphertext; the key id and the bucket's name are not.

    Same rule as the upload's, and the same escape hatch for the same reason: a disposable
    endpoint on a private network has nobody on the path, which is where the acceptance
    scenario's store lives.
    """
    for name in list(fetch.REQUIRED) + list(fetch.FALLBACK.values()):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(fetch.REGION, "example-region-1")
    monkeypatch.setenv(fetch.BUCKET, "a-bucket")
    monkeypatch.setenv(fetch.ACCESS_KEY, "k")
    monkeypatch.setenv(fetch.SECRET_KEY, "s")
    monkeypatch.setenv(fetch.ENDPOINT, "http://store.example.invalid")
    monkeypatch.setattr(fetch, "addresses_of", lambda host: [])
    with pytest.raises(fetch.Refusal, match="does not resolve"):
        fetch.configuration()

    import ipaddress

    # A genuinely public address, and not one out of a documentation range: Python's own
    # registry marks 198.51.100.0/24 and 203.0.113.0/24 as private, so a test written with
    # one of those would pass whatever this code did.
    monkeypatch.setattr(
        fetch, "addresses_of", lambda host: [ipaddress.ip_address("93.184.216.34")]
    )
    with pytest.raises(fetch.Refusal, match="Use https"):
        fetch.configuration()

    monkeypatch.setattr(fetch, "addresses_of", lambda host: [ipaddress.ip_address("10.1.2.3")])
    assert fetch.configuration()["scheme"] == "http"


def test_the_query_string_is_encoded_the_way_a_signature_expects(fetch) -> None:
    """Sorted, and every character encoded — ``/`` included.

    A prefix is the one parameter that always contains a separator, so a store that
    recomputes the signature over the unencoded form disagrees on every listing and on no
    other request. That is a bug that only appears once there is a prefix, which is once
    there is a real bucket.
    """
    assert fetch.canonical_query({"prefix": "control/", "list-type": "2"}) == (
        "list-type=2&prefix=control%2F"
    )


class _Answer:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)


class _Connection:
    closed = False

    def close(self) -> None:
        self.closed = True


def _listing_page(entries, *, token: str = "") -> bytes:
    """One ``ListObjectsV2`` answer, in the shape a store really sends it.

    Under a document namespace, deliberately: the parser matches on the LOCAL name of each
    element, and a test that sends bare tags would not notice if that stopped being true.
    """
    contents = "".join(
        f"<Contents><Key>{key}</Key><LastModified>{when}</LastModified>"
        f"<Size>{size}</Size></Contents>"
        for key, when, size in entries
    )
    truncated = "true" if token else "false"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://example.invalid/doc/2006-03-01/">'
        f"<IsTruncated>{truncated}</IsTruncated>"
        + (f"<NextContinuationToken>{token}</NextContinuationToken>" if token else "")
        + contents
        + "</ListBucketResult>"
    ).encode()


def test_the_newest_is_decided_by_the_store_and_not_by_the_name(fetch, monkeypatch) -> None:
    """THE choice this command makes for the operator, and why it is not the obvious one.

    The object's name is chosen by whichever key wrote it, and on a live control plane that
    is a key whoever seized the box holds — so a name can be written to sort first. The
    store's ``LastModified`` is the one value in the exchange that the lost host had no say
    in. Here the two disagree on purpose: the name that looks newest is the oldest object.
    """
    pages = [
        _listing_page(
            [
                ("control/hashi-20990101T000000Z.sql.gz.age", "2026-09-01T04:00:00.000Z", "10"),
                ("control/hashi-20260921T040000Z.sql.gz.age", "2026-09-21T04:00:00.000Z", "10"),
            ],
            token="more",
        ),
        _listing_page(
            [
                ("control/hashi-20260922T040000Z.sql.gz.age", "2026-09-22T04:00:00.000Z", "10"),
                # A folder marker and an empty object: both exist in real buckets and
                # neither would ever open.
                ("control/", "2026-09-22T04:00:00.000Z", "0"),
                ("control/half-written.age", "2026-09-23T04:00:00.000Z", "0"),
            ]
        ),
    ]
    asked = []

    def fake(config, method, object_key, parameters):
        asked.append(parameters)
        return _Connection(), _Answer(200, pages[len(asked) - 1])

    monkeypatch.setattr(fetch, "opened", fake)
    found = fetch.listing({"prefix": "control/", "bucket": "b", "endpoint": "e"})

    assert [name for _, _, name in found] == [
        "hashi-20260922T040000Z.sql.gz.age",
        "hashi-20260921T040000Z.sql.gz.age",
        "hashi-20990101T000000Z.sql.gz.age",
    ], "the listing is not ordered by the store's own timestamp, newest first"
    # The second page was asked for, which is the whole of the paging: a store answers a
    # thousand keys at a time in LEXICOGRAPHIC order, so one page of a long history is the
    # OLDEST names wearing the word "newest".
    assert len(asked) == 2 and asked[1]["continuation-token"] == "more"
    assert asked[0]["prefix"] == "control/"


def test_a_credential_that_cannot_list_says_which_credential_it_is(fetch, monkeypatch) -> None:
    """The likeliest mistake on the whole list: reaching for the key that is in `.env`."""
    monkeypatch.setattr(
        fetch,
        "opened",
        lambda *a, **k: (
            _Connection(),
            _Answer(403, b"<Error><Code>AccessDenied</Code><Message>no</Message></Error>"),
        ),
    )
    with pytest.raises(fetch.Refusal) as refused:
        fetch.listing({"prefix": "", "bucket": "b", "endpoint": "e"})
    said = str(refused.value)
    assert "LIST and GET" in said
    assert "may only write" in said, (
        "the refusal does not name the write-only key, so an operator who used it is left "
        "to work that out at the worst possible moment"
    )


def test_a_bucket_that_is_not_there_is_not_reported_as_a_bad_credential(
    fetch, monkeypatch
) -> None:
    """Two different problems, said apart — the credential answered, so it is the name."""
    monkeypatch.setattr(
        fetch,
        "opened",
        lambda *a, **k: (
            _Connection(),
            _Answer(404, b"<Error><Code>NoSuchBucket</Code><Message>gone</Message></Error>"),
        ),
    )
    with pytest.raises(fetch.Refusal, match="no such bucket"):
        fetch.listing({"prefix": "", "bucket": "b", "endpoint": "e"})


def test_an_empty_prefix_says_the_credential_worked(fetch, monkeypatch) -> None:
    """"Nothing came back" has two causes and only one of them is worth an hour."""
    monkeypatch.setattr(
        fetch, "opened", lambda *a, **k: (_Connection(), _Answer(200, _listing_page([])))
    )
    monkeypatch.setattr(fetch, "configuration", lambda: {
        "prefix": "control/", "bucket": "b", "endpoint": "e", "netloc": "n",
    })
    captured: list[str] = []
    monkeypatch.setattr(fetch, "say", captured.append)
    assert fetch.main(["list"]) == fetch.REFUSED
    assert any("The credential works" in line for line in captured)


# --- the command itself -------------------------------------------------------


def test_the_new_verb_sits_behind_the_one_gate_and_has_none_of_its_own(script: str) -> None:
    """M28.7's property is structural, and a new verb is exactly how it gets lost.

    The env-file gate runs in the DISPATCH, before any verb function is entered, so every
    compose call any of them can reach is behind it — however many there come to be. A verb
    added below the gate rather than through it would print compose's complaint about an
    env file it cannot parse, which quotes that line's whole value back.
    """
    dispatch = script.rsplit("case \"${1:-}\" in", 1)[-1]
    assert "restore-from-bucket)" in dispatch, "the verb is not in the dispatch at all"
    for verb in ("dump", "upload", "restore", "restore-from-bucket"):
        branch = re.search(rf"^\s*{re.escape(verb)}\)(?:\s|\n)+[^\n]*\n?[^\n]*", dispatch, re.M)
        assert branch and "env_file_must_be_readable" in branch.group(0), (
            f"the {verb} branch does not pass through the env-file gate"
        )
    # ONE implementation of the gate, in a library both this script and
    # `scripts/panel-bootstrap.sh` source — never a copy in either, which is how two
    # scrubbers come to disagree and the next printer ends up behind only one of them.
    assert not re.search(r"^env_file_must_be_readable\(\) \{", script, re.M), (
        "the gate is defined in this script as well as in the library it sources"
    )
    assert '. "${REPO_ROOT}/scripts/lib/env-file-gate.sh"' in script


def test_the_read_credential_is_taken_from_the_environment_and_never_from_the_env_file(
    script: str,
) -> None:
    """What makes "two secrets that never meet on the control host" true after M28.8.

    Measured rather than assumed: compose's short pass-through form does NOT mean "the
    shell only" — with ``--env-file`` a value in the env file reaches the container exactly
    as a shell value would. So no shape of the overlay can enforce this, and the
    enforcement has to be a refusal here. The value itself is only ever tested for
    emptiness; it is never assigned, never printed and never an argument.
    """
    for name in ("HASHI_RESTORE_S3_ACCESS_KEY_ID", "HASHI_RESTORE_S3_SECRET_ACCESS_KEY"):
        expansions = [line for line in script.splitlines() if "${" + name in line]
        assert expansions, f"{name} is never checked, so a credential only in .env works"
        for line in expansions:
            assert re.search(rf'\[ -n "\$\{{{name}:-\}}" \]', line), (
                f"{name} is expanded somewhere other than a presence test: {line.strip()}"
            )
    # And the script still opens no env file — the rule this verb was most tempted to
    # break, since "is the credential in there?" is one grep away.
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in (r"cat\s+\$\{ENV_FILE", r"grep[^\n]*ENV_FILE", r"source\s+\$\{ENV_FILE"):
        assert not re.search(forbidden, code), forbidden


def test_the_read_credential_never_reaches_the_long_lived_control_plane() -> None:
    """The mirror of the write key's rule, and the sharper half of it.

    A credential that can read the bucket is a credential that hands over every backup the
    fleet ever wrote. It lives for the length of one ``compose run`` container, from an
    overlay no Make target loads and the base stack has never heard of.
    """
    whole = RESTORE_OVERLAY.read_text()
    # The declarations alone: this file's header names the two variables it deliberately
    # does NOT pass, and a check over the comments would be reading the explanation.
    overlay = whole[whole.index("services:"):]
    assert "HASHI_RESTORE_S3_SECRET_ACCESS_KEY" in overlay
    assert "ports:" not in whole and "services:\n  control:\n" in whole, (
        "the restore overlay has grown beyond the variables it exists for"
    )
    for write_only in ("HASHI_BACKUP_S3_ACCESS_KEY_ID", "HASHI_BACKUP_S3_SECRET_ACCESS_KEY"):
        assert write_only not in overlay, (
            f"{write_only} is in the restore overlay, so the key that writes and the "
            "credential that reads arrive in one container together"
        )
    assert "HASHI_RESTORE" not in BASE_COMPOSE.read_text(), (
        "the base stack carries the read credential, so every control container has it"
    )
    assert "docker-compose.restore.yml" not in MAKEFILE.read_text(), (
        "a Make target loads the restore overlay, which puts the read credential in the stack"
    )


def test_the_fetcher_reaches_the_container_as_an_argument_and_not_as_an_image(
    script: str,
) -> None:
    """A restore must never wait on a rebuild, and a stale image must not be able to break it."""
    assert re.search(
        r'COMPOSE_RESTORE\[@\]\}" run --rm --no-deps -T --entrypoint python3 control',
        script,
    ), "the fetcher is not run in a one-off container with its own entrypoint"
    assert '-c "$(cat "${FETCHER}")"' in script, (
        "the fetcher is not handed to the container as an argument read from the checkout"
    )
    for dockerfile in (REPO / "deploy" / "docker").glob("*.Dockerfile"):
        assert "fetch.py" not in dockerfile.read_text(), (
            f"{dockerfile.name} bakes the fetcher into an image, so a restore now needs a build"
        )


def test_the_artifact_is_proven_to_open_before_anything_destructive(script: str) -> None:
    """Nobody types a database name to authorise a restore that was always going to fail.

    The same ordering M28.2 settled for the artifact's shape, one step further: the file is
    decrypted and checked to be a whole gzip stream BEFORE ``command_restore`` — which is
    what asks for the confirmation and what replaces the database.
    """
    code = code_of(script, "command_restore_from_bucket")
    opens, restores = code.find("artifact_opens"), code.find("command_restore ")
    assert opens > 0 and restores > 0, "the verb no longer verifies or no longer restores"
    assert opens < restores, (
        "the restore happens before the artifact is known to open, so the destructive "
        "confirmation is asked for a file that may be unopenable"
    )
    # And the plaintext of that check goes into `gunzip -t` and nowhere else: not a file,
    # not a terminal, not a variable.
    verify = code_of(script, "artifact_opens")
    assert "gunzip -t" in verify and "--identity -" in verify, (
        "the check no longer streams the identity in and pipes the plaintext straight out"
    )
    assert not re.search(r">\s*\"?\$\{?(file|target|out)", verify), (
        "the verification writes the plaintext somewhere"
    )


def test_the_install_comes_before_the_bucket_is_read(script: str) -> None:
    """A mechanical ordering with a reason worth keeping written down.

    The program that speaks to the store runs inside this project's control image, which is
    what keeps a rented host from needing anything installed. There is no image until
    something builds one — so the bootstrap is first, and that is also what makes the whole
    command safe to run again after any failure below it.
    """
    code = code_of(script, "command_restore_from_bucket")
    assert code.index("panel-bootstrap.sh") < code.index("fetch_run"), (
        "the bucket is read before the control plane exists, which needs an image nothing "
        "has built yet"
    )


def test_every_refusal_names_which_of_the_three_inputs_is_wrong(script: str) -> None:
    """"It did not work" is the difference between five minutes and an hour at 3am."""
    verb = body_of(script, "command_restore_from_bucket")
    assert "HASHI_RESTORE_AGE_IDENTITY is not set" in verb
    assert "HASHI_RESTORE_S3_ACCESS_KEY_ID" in verb
    assert "the artifact is intact; the identity is wrong." in verb, (
        "the wrong-keypair case does not get its own sentence, so it reads as a damaged "
        "backup — which sends the operator looking for another artifact"
    )
    assert "no `docker`" in verb, "a machine with no container runtime is not answered"
    # And nothing anywhere claims a state it did not leave the host in.
    for promise in ("Nothing has been fetched and nothing has been changed",
                    "Nothing was fetched and nothing was changed"):
        assert promise in verb


def test_a_damaged_artifact_is_walked_past_and_a_wrong_identity_is_not(script: str) -> None:
    """Two failures that look identical and call for opposite things.

    Every object in the bucket was written to the same public half, so an identity that
    opens none of them will open none of the older ones either: walking the history there
    is a slower way to print the same sentence. A damaged newest artifact is the opposite —
    the one before it is very likely fine, and that is the whole reason to look.
    """
    verify = body_of(script, "artifact_opens")
    assert "no identity matched" in verify, (
        "the two failures are not told apart, so a wrong identity reads as a bucket full "
        "of damaged backups"
    )
    verb = code_of(script, "command_restore_from_bucket")
    assert re.search(r"identity\)\n(?:.*\n)*?\s*exit 1", verb), (
        "a wrong identity does not stop the walk"
    )
    assert "RESTORE_CANDIDATES" in verb, "the walk has no bound"


def test_naming_one_object_never_promises_to_try_the_one_before_it(script: str) -> None:
    """Two lines that contradict each other are worse than either of them alone.

    With ``OBJECT=`` there is exactly one candidate, so "Trying the one before it."
    followed immediately by "none of them opened" reads as a command that has lost track of
    what it is doing — and an operator who stops believing the output stops believing the
    part of it that says which of their three inputs is wrong. Both the walk line and the
    advice at the end are conditional on whether the operator chose.
    """
    verb = body_of(script, "command_restore_from_bucket")
    walk = [line for line in verb.splitlines() if "Trying the one before it." in line]
    assert len(walk) == 1, walk
    assert 'if [ -z "${wanted}" ]; then' in walk[0], (
        "the walk line is printed even when the operator named the one object there is"
    )
    assert "That is the one object you named." in verb, (
        "the give-up message tells an operator who named an object to name one"
    )
    assert 'if [ -n "${wanted}" ]; then' in code_of(script, "command_restore_from_bucket")


def test_the_last_thing_on_the_screen_is_what_it_did_not_do(script: str) -> None:
    """Where the operator is actually looking, rather than a paragraph they reach after.

    A restored control plane on a new address that the old name still does not point at
    serves nobody, and none of these three is a thing a script may do on somebody's behalf.
    """
    verb = body_of(script, "command_restore_from_bucket")
    closing = verb[verb.index("did NOT do"):]
    assert "DNS" in closing
    assert "certificate" in closing
    assert re.search(r"Telling anybody|no message goes to any user", closing, re.I)
    # The one failure it cannot see, named rather than left to be discovered.
    # Since M31.8 the sentence is one variable both restore paths print, so the closing
    # screen carries it by name and the definition carries the words.
    if "${WRONG_KEY_SENTENCE}" in closing:
        definition = script[script.index('WRONG_KEY_SENTENCE="'):]
        closing = definition[: definition.index('artifact."\n')].replace('\\"', '"')
    assert "The data is intact; the key is wrong." in closing, (
        "the closing screen does not tell the operator what a wrong HASHI_SECRET_KEY looks "
        "like, and it is the only failure here that leaves everything looking fine"
    )
    assert verb.rstrip().endswith("MSG"), (
        "something is printed after the list of what this did not do, so it is no longer "
        "the last thing on the screen"
    )


def test_the_make_verb_exists_and_does_not_guess_a_file(script: str) -> None:
    """`make restore` still refuses to choose; this one chooses, and they are different cases."""
    makefile = MAKEFILE.read_text()
    assert "restore-from-bucket:" in makefile
    assert "scripts/backup.sh restore-from-bucket" in makefile
    assert "OBJECT" in makefile, "there is no way to name an artifact other than the newest"
    # The old verb is untouched: given a file the operator is already holding.
    assert 'test -n "$(FROM)"' in makefile


def test_the_runbook_and_the_env_file_point_at_what_exists(script: str) -> None:
    """Both pointers are by exact title, so renaming the section fails here rather than
    leaving an operator at a heading that is no longer in the page."""
    runbook = RUNBOOK.read_text()
    assert f"### {RESTORE_SECTION}" in runbook
    assert f"### {NOT_DONE_SECTION}" in runbook
    # The comment wraps, and a wrapped title is still a pointer — the same flattening
    # `test_deploy_runbook.py` uses for the retention section's pointer.
    env = " ".join(re.sub(r"\n#", " ", ENV_EXAMPLE.read_text()).split())
    assert RESTORE_SECTION in env, (
        "`.env.example` does not point at the section that explains the restore, so the "
        "comment beside the carried credentials is the only account of it"
    )
    assert "make restore-from-bucket" in env


def test_the_runbook_says_the_three_it_does_not_do_under_its_own_heading() -> None:
    """Said out loud, in the outline, not buried in a paragraph after the happy path."""
    runbook = RUNBOOK.read_text()
    section = re.search(
        rf"^### {re.escape(NOT_DONE_SECTION)}\n((?:.*\n)*?)(?=^#{{2,3}} )", runbook, re.M
    )
    assert section, "the runbook no longer says what the restore leaves undone"
    said = " ".join(section.group(1).split())
    assert "does not move DNS" in said
    assert "certificate" in said and "caddy_data" in said
    assert re.search(r"tells no user anything|no message goes to any user", said, re.I)
    assert "HASHI_SECRET_KEY" in said, (
        "the section does not mention the one failure that leaves everything looking fine"
    )


def test_the_runbook_names_what_each_failure_says(script: str) -> None:
    """The failure modes are the product here, so the page carries them as a table.

    Checked against the script's own words rather than against a paraphrase: a runbook that
    quotes a sentence the command does not print is worse than one that quotes nothing,
    because an operator searching for what they saw finds nothing.
    """
    runbook = RUNBOOK.read_text()
    section = re.search(
        rf"^### {re.escape(RESTORE_SECTION)}\n((?:.*\n)*?)(?=^#{{2,3}} )", runbook, re.M
    )
    assert section, "the runbook has no section for the command at all"
    said = section.group(1)
    for quoted in (
        "The artifact is intact; the identity is wrong.",
        "The data is intact; the key is wrong.",
    ):
        assert quoted in said, f"the runbook does not quote {quoted!r}"
        assert quoted.lower() in script.lower() or quoted in RUNBOOK.read_text()
    assert "LIST and GET" in said, (
        "the page does not carry the sentence for the mistake an operator is likeliest to "
        "make — using the key that is already in .env"
    )
    assert "LastModified" in said, (
        "the page does not say how the artifact is chosen, so `newest` reads as the name"
    )
