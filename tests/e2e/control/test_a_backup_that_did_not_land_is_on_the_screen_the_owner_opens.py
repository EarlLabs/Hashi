"""A run that did not land is on the first screen, without anybody going to look.

WHAT: writes a record into the very directory the control container has mounted, then
      opens the panel as the operator and requires the standing to be on the Overview —
      the screen ``/panel/`` opens on — with the sentence that says what it does not know.
WHY:  M28.6's criterion, in the plan's own words: *"make a run that does not land visible
      without anyone going to look for it."* The unit tier proves the reading and the
      wording; neither of them proves that a file written on the HOST reaches a panel
      running in a container. That is a mount, a read-only one, a setting and a template,
      and every one of those is invisible to a suite that constructs the application in
      process.

      The second half is the sentence this milestone exists not to inflate. A successful
      run means the object store received exactly those bytes and accepted them; the
      credential on this host may only write, so nothing here can look in the bucket, and
      nothing in this repository asserts what it keeps. That caveat is asserted on the
      RENDERED page, because a constant in a module that never reaches a screen is not a
      thing the operator was told.
HOW:  over real HTTP against the booted stack, as the operator, with a session from the
      real login form. The record is written through a one-off container that mounts the
      same source the control container has — the engine running the stack is not always
      the machine running pytest (see tests/e2e/conftest.py), so writing the path from
      here would silently write nothing on a remote engine. Whatever was in the directory
      before is put back on the way out.

Boundary: real control, postgres, caddy. No node is contacted, no backup is taken, and
nothing here proves an artifact exists anywhere — that is the whole point of the caveat
being asserted rather than the absence of one.
"""

import datetime
import json
import subprocess

import pytest

OPERATOR = {"username": "owner", "password": "e2e-operator-password"}

# Where the record is mounted inside the control container — deploy/docker-compose.yml,
# read-only. Written out rather than imported: nothing in this directory imports the
# application, and this is the contract between a compose file and a setting, so a
# scenario that took it from the code could not notice the two disagreeing.
IN_THE_CONTAINER = "/var/lib/hashi/backup/last-run.json"

# Words the screen may never acquire. Each turns "this host's own runs went like this"
# into "a restorable artifact exists", which is the claim nothing in this product makes.
NEVER_SAID = ("safe", "guaranteed", "verified", "you are covered")


def _docker(*argv: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *argv], input=stdin, capture_output=True, text=True, timeout=120
    )


@pytest.fixture
async def operator(client):
    response = await client.post("/panel/login", data=OPERATOR)
    assert response.status_code == 303, (
        f"the operator could not log in ({response.status_code}) — check "
        "deploy/e2e.env"
    )
    client.cookies.update(response.cookies)
    return client


@pytest.fixture
def on_the_hosts_disk(compose):
    """Puts a record where the host's schedule puts one, in the mount the panel reads.

    Through a one-off container rather than through an open() here, and as the DIRECTORY'S
    own owner rather than as root: the mount source is a path on the engine's filesystem,
    which is not necessarily this one, and a root-owned file left in a checkout is one the
    real schedule — which runs unprivileged — could never rewrite.

    Whatever the directory held before is restored on the way out, because a developer's
    checkout may well hold a real record from a real run.
    """
    running = compose("ps", "-q", "control").stdout.split()
    assert running, "no running control container — is the e2e stack up?"
    container = running[0]

    mounts = json.loads(
        _docker("inspect", container, "--format", "{{json .Mounts}}").stdout
    )
    source = next(
        mount["Source"]
        for mount in mounts
        if mount["Destination"] == IN_THE_CONTAINER.rsplit("/", 1)[0]
    )
    image = _docker("inspect", container, "--format", "{{.Config.Image}}").stdout.strip()
    owner = _docker(
        "exec", container, "stat", "-c", "%u:%g", IN_THE_CONTAINER.rsplit("/", 1)[0]
    ).stdout.strip()

    def as_the_host(script: str, stdin: str | None = None) -> None:
        # ``--entrypoint sh`` is mandatory: the image's own entrypoint boots the
        # application and would answer about a database rather than writing a file.
        done = _docker(
            "run", "--rm", "-i", "--user", owner, "--entrypoint", "sh",
            "-v", f"{source}:/state", image, "-c", script,
            stdin=stdin,
        )
        assert done.returncode == 0, done.stderr

    # Read-only from in here is still a read, which is how the original is preserved.
    before = _docker("exec", container, "cat", IN_THE_CONTAINER)
    original = before.stdout if before.returncode == 0 else None

    def write(record: dict) -> None:
        as_the_host(
            "cat > /state/last-run.json && chmod 644 /state/last-run.json",
            stdin=json.dumps(record, indent=2),
        )

    def remove() -> None:
        as_the_host("rm -f /state/last-run.json")

    try:
        yield write, remove
    finally:
        if original is None:
            remove()
        else:
            as_the_host(
                "cat > /state/last-run.json && chmod 644 /state/last-run.json",
                stdin=original,
            )


def a_record(**overrides) -> dict:
    """The record the schedule writes, in its own shape. M28.5's closed key set."""
    written = {
        "schema": 1,
        "written_at": "2026-08-01T04:00:07Z",
        "at": "04:00",
        "at_source": "configured",
        "zone": "Europe/Belgrade",
        "zone_source": "configured",
        "offsite": "yes",
        "due_date": "2026-08-01",
        "attempts": 1,
        "retry_not_before": "",
        "last_attempt": None,
        "last_success": None,
        "last_failure": None,
        "missed_dates": [],
        "missed_total": 0,
    }
    written.update(overrides)
    return written


def a_run(days_ago: int, *, exit_code: int = 0, outcome: str = "offsite") -> dict:
    when = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago)
    return {
        "at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "due_date": when.strftime("%Y-%m-%d"),
        "exit_code": exit_code,
        "outcome": outcome,
    }


async def test_six_weeks_of_failure_is_on_the_overview_the_panel_opens_on(
    operator, on_the_hosts_disk
) -> None:
    """The whole criterion, end to end: written on the host, read in the container.

    Nothing is navigated to. ``/panel/`` IS the Overview, so this is what the operator
    sees on the first request of a session — which is the difference between a fact that
    is available and a fact that is told.
    """
    write, _ = on_the_hosts_disk
    write(
        a_record(
            last_success=a_run(43),
            last_failure=a_run(1, exit_code=3, outcome="not-sent"),
            last_attempt=a_run(1, exit_code=3, outcome="not-sent"),
        )
    )

    page = (await operator.get("/panel/")).text

    assert "Backups on this host are failing." in page
    assert "The last one that succeeded was 43 days ago" in page
    assert ">failing<" in page, "the standing's own word is not on the screen"
    # What it did not manage, in the words the script itself prints for exit 3.
    assert "it did NOT leave this machine" in page


async def test_the_screen_says_what_it_does_not_know_even_when_all_is_well(
    operator, on_the_hosts_disk
) -> None:
    """The good state is where the caveat matters most, so it is asserted there.

    "Last backup 3 hours ago: written here, and the object store accepted it" is the
    strongest claim this host is entitled to make, and an operator who reads it as "a
    restorable artifact exists offsite" has read something nothing in this product can
    check: the credential here may only write, so it cannot look.
    """
    write, _ = on_the_hosts_disk
    write(a_record(last_success=a_run(0), last_attempt=a_run(0)))

    page = (await operator.get("/panel/")).text

    assert "the object store accepted it" in page
    assert "whether any of those artifacts is still in the bucket" in page
    assert "may only write, so it cannot look" in page
    for word in NEVER_SAID:
        assert word not in page.lower(), f"the screen says {word!r} about a backup"


async def test_an_empty_mount_reads_as_nothing_recorded_and_names_the_file(
    operator, on_the_hosts_disk
) -> None:
    """The normal case for a control plane that does not run beside the backups.

    It also proves, from outside, that the container is reading the MOUNT POINT rather
    than some path of its own: the sentence names the file it looked for, and that name
    is the one deploy/docker-compose.yml mounts.
    """
    _, remove = on_the_hosts_disk
    remove()

    page = (await operator.get("/panel/")).text

    assert "No backup has ever been recorded on this host." in page
    assert IN_THE_CONTAINER in page
    # With no record there is nothing that says where this host sends, so the closing
    # sentence claims neither. The bucket's caveat here would imply a bucket (M28.11).
    assert "whether anything was sent anywhere" in page
    assert "whether any of those artifacts is still in the bucket" not in page


async def test_the_shipped_default_does_not_read_like_a_host_that_uploads(
    operator, on_the_hosts_disk
) -> None:
    """M28.11, acceptance 2026-09-23: `HASHI_BACKUP_ENABLED=0` is what ships.

    Two records identical but for ``offsite`` drew byte-identical screens, and the one
    that sends nothing closed with a caveat about a bucket it does not have. Driven here
    rather than only in the unit tier because what acceptance compared was two rendered
    pages off a real stack, and the field the panel had dropped travels from the writer's
    file through a mount and a parser before it reaches a sentence.
    """
    write, _ = on_the_hosts_disk

    write(a_record(offsite="no", last_success=a_run(0, outcome="on-this-host-only"),
                   last_attempt=a_run(0, outcome="on-this-host-only")))
    stays_here = (await operator.get("/panel/")).text

    write(a_record(offsite="yes", last_success=a_run(0), last_attempt=a_run(0)))
    uploads = (await operator.get("/panel/")).text

    assert stays_here != uploads
    assert "that this host is sending its backups anywhere" in stays_here
    assert "on this host and nowhere else" in stays_here
    assert "whether any of those artifacts is still in the bucket" not in stays_here
    # ...and the claim M28.6 spent two rounds on is intact on the host that does upload.
    assert "whether any of those artifacts is still in the bucket" in uploads
    for word in NEVER_SAID:
        assert word not in stays_here.lower(), f"the screen says {word!r} about a backup"


async def test_a_record_from_the_future_is_not_the_quiet_state(
    operator, on_the_hosts_disk
) -> None:
    """A clock that disagrees gave "less than an hour ago" permanently — M28.11.

    The age is still clamped, so a disagreeing clock cannot turn a stale backup into a
    stale-looking one or the reverse; what it may no longer do is print a number this
    panel cannot stand behind, on the quietest line the feature has.
    """
    write, _ = on_the_hosts_disk
    write(a_record(last_success=a_run(-2), last_attempt=a_run(-2)))

    page = (await operator.get("/panel/")).text

    assert "less than an hour ago" not in page
    assert "at a time that had not come yet when this was read" in page
    assert ">clock ahead<" in page


async def test_the_panel_cannot_write_the_record_it_reads(
    operator, on_the_hosts_disk, compose
) -> None:
    """The mount is read-only so the control plane can neither invent nor erase a run.

    Asserted as a property of the running container rather than of the compose file: what
    matters is that the process serving the panel cannot write there, and a scenario that
    read the YAML would be reading an intention.
    """
    write, _ = on_the_hosts_disk
    write(a_record(last_success=a_run(0), last_attempt=a_run(0)))

    container = compose("ps", "-q", "control").stdout.split()[0]
    before = _docker("exec", container, "cat", IN_THE_CONTAINER).stdout

    assert (await operator.get("/panel/")).status_code == 200

    # As the user the application runs as: it is refused, and that is the whole claim.
    refused = _docker("exec", container, "sh", "-c", f"echo x >> {IN_THE_CONTAINER}")
    assert refused.returncode != 0, "the control container can write the backup record"

    # And as root, which is what tells the mount from the ownership. Root walks through a
    # file mode and is stopped by a read-only filesystem, so this is the assertion that
    # the DIRECTION is the mount's rather than a permission somebody could chown away.
    as_root = _docker(
        "exec", "--user", "0:0", container, "sh", "-c", f"echo x >> {IN_THE_CONTAINER}"
    )
    assert as_root.returncode != 0
    assert "read-only" in as_root.stderr.lower(), as_root.stderr

    assert _docker("exec", container, "cat", IN_THE_CONTAINER).stdout == before
