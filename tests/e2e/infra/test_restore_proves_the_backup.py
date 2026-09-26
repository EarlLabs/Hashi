"""A backup that has never been restored is not a backup — backlog item 32.

WHAT: fills a disposable stack, dumps it, restores the dump into a CLEAN stack, and
      checks that what the owner would need is actually there — plus the failures that
      matter: a restore with the wrong key, a restore that stops halfway, and a host
      trying to read back the backup it just wrote. Since M28.2 the artifact is `age`
      ciphertext, so the scenario also covers the shape written before that, which
      exists in the world and must still restore. Since M28.3 it also leaves the machine:
      the last four scenarios stand up a disposable S3-compatible endpoint and prove an
      object really landed, that a refused credential leaves the operator holding the
      artifact with an exit code of its own, and that a half-configured offsite block is
      refused before the database is read. Since M28.8 it also comes BACK: S13 runs the one
      command on a THIRD compose project that nothing here installed — no stack, no image,
      no database, an env file naming no object store — and the command itself installs the
      control plane, reads the bucket with a credential handed to it at that moment, takes
      the newest artifact that opens, restores it, and is measured by the user's own
      subscription link resolving byte for byte on the rebuilt host.
WHY:  the charter says a backup nobody has restored is not a backup, and that proving it
      belongs to the e2e set. Until this file, ``tests/infra/test_backup_script.py`` read
      the script's TEXT and said so honestly in its own header: "nothing here proves a
      dump restores". So the one artefact whose loss cannot be repaired by rebuilding a
      node had a backup routine that had never once been exercised.
HOW:  two real compose projects, each with its own volumes, brought up by the panel
      bootstrap (item 31) — which is also the honest way to do it: the restore has to work
      on a host installed the way the owner installs one. Everything is torn down with its
      volumes afterwards.

      The fleet is created through the API, because that is how the rows a restore has to
      carry actually come into existence. Asserting on tables directly would prove a
      transfer of bytes; asserting through the API proves the fleet still works.

Boundary: this proves a dump restores onto a host with Docker, and what survives. It says
nothing about TLS, nothing about whether any node is reachable, and nothing about a real
Russian network.
"""

import contextlib
import gzip
import pathlib
import shutil
import subprocess
import uuid

import httpx
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
BOOTSTRAP = REPO_ROOT / "scripts" / "panel-bootstrap.sh"
BACKUP = REPO_ROOT / "scripts" / "backup.sh"
SCHEDULER = REPO_ROOT / "scripts" / "backup-run.sh"
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.yml"
DEV_OVERLAY = REPO_ROOT / "deploy" / "docker-compose.dev.yml"

RUN = uuid.uuid4().hex[:8]
SOURCE_PROJECT = f"hashi-restore-src-{RUN}"
TARGET_PROJECT = f"hashi-restore-dst-{RUN}"
# The machine that has never run this project — M28.8. Its own compose project, its own
# volumes, its own env file, and nothing installed on it by anything in this module: the
# command under test is what brings it into existence.
RESCUE_PROJECT = f"hashi-restore-new-{RUN}"

# The key the source stack encrypts with. Fixed and obviously fake. The target stack is
# given the SAME key for the successful restore and a DIFFERENT one for the failure.
KEY = "e2e-restore-key-not-real-0000000000000000000000000"
WRONG_KEY = "e2e-restore-WRONG-key-not-real-0000000000000000000"

# The backup keypair for this scenario. Fixed, obviously fake and committed on purpose,
# exactly like the key above. Generating one here would need `age` on the machine running
# pytest, and the whole point of shipping the binary in the control image is that a host
# which can run the stack can make and open a backup without installing anything — so the
# suite must pass on a machine that has never heard of age.
#
# The stack under test is given ONLY the public half. The identity below never enters an
# env file: it is handed to the restore at the moment it runs, which is the contract.
BACKUP_RECIPIENT = "age1efx4vjnw8csr825yvmypzas9k63sf0r2suv82fefvle058azwayskvwgcz"
BACKUP_IDENTITY = "AGE-SECRET-KEY-1SHYNP57023UZU8D3JCXETCWLW2WMDZX34A2E5FENPYWP89090HNQ4M4JSC"
# A second, unrelated pair — for the difference between holding AN identity and holding
# THE identity.
UNRELATED_IDENTITY = "AGE-SECRET-KEY-1E7H77KJSTLXSA5GDKA24AH48970FZUJ92X6V84LVMUPVE90M934SMH5W7P"

# The disposable object store the upload scenarios send to — M28.3. An S3-compatible
# server in a container, on the stack's own network, holding one bucket that exists for
# the length of this module. It is TEST infrastructure: it is in no compose file of this
# project, no Make target starts it, and nothing in the product knows it exists. Proving
# that `PutObject` happened needs something that actually implements the protocol, and an
# independent implementation is also the only honest check that the signature this
# repository computes is the signature the protocol specifies — a home-made receiver would
# agree with whatever mistake the signer made.
#
# From quay rather than the other registry, where this repository is now gated behind a
# login. Pinned to a release, like every other image here.
STORE_IMAGE = "quay.io/minio/minio:RELEASE.2024-09-13T20-26-02Z"
STORE_BUCKET = "hashi-e2e-backups"
STORE_PREFIX = "control/"
# Obviously fake, like every other credential in this file. The store's ROOT credential:
# this one may read, which is how the scenario checks that an object landed. The control
# host under test is never given anything but what the env file below carries.
STORE_ACCESS_KEY = "e2e-upload-not-real"
STORE_SECRET_KEY = "e2e-upload-secret-not-real-00000"
WRONG_STORE_SECRET_KEY = "e2e-upload-WRONG-secret-not-real"

OPERATOR_PASSWORD = "restore-proves-the-backup"
# Loopback ports well clear of the dev (541xx) and e2e (542xx) blocks, per CLAUDE.md's
# published-port rule: this is a third stack on the same host and it must collide with
# neither.
SOURCE_PORT = 54300
TARGET_PORT = 54301
# The rescue host's, clear of the two above and of the `+2` the wrong-key scenario takes.
RESCUE_PORT = 54305
# Where the disposable store is published, so this suite can read an object back. The
# control plane under test never uses this address: it reaches the store by container name
# on the compose network, which is the only route a real one would have.
STORE_PORT = 54308


def _docker_env() -> dict[str, str]:
    import os

    env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
    if os.environ.get("DOCKER_HOST"):
        env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
    return env


def env_file(
    directory: pathlib.Path, *, key: str, port: int, recipient: str | None = BACKUP_RECIPIENT
) -> pathlib.Path:
    """The env file a host under test is installed from.

    ``recipient=None`` is what a REBUILT host really looks like — M28.10. The age
    recipient and the write-only S3 key lived only in the `.env` that was lost, because
    that file is deliberately in no backup, so the machine that comes back out of the
    backup history is the one machine that cannot add to it. Every other scenario here
    needs the recipient, because it takes a backup; the rescue host does not take one.
    """
    from control.app.crypto import hash_password

    # Every `$` doubled. `docker compose --env-file` interpolates the values it reads, so
    # a scrypt hash's `$<salt>$<digest>` is read as variable references and arrives
    # mangled — which is how this scenario first failed, with a correct-looking hash in
    # the file and a 401 on login. scripts/panel-bootstrap.sh now refuses an env file
    # that has one, so this is also what keeps the install below from being refused.
    def escaped(value: str) -> str:
        return value.replace("$", "$$")

    path = directory / "restore.env"
    path.write_text(
        "".join(
            f"{name}={value}\n"
            for name, value in {
                "HASHI_SECRET_KEY": key,
                # The PUBLIC half, and nothing else. This is what makes the stack able to
                # write a backup it cannot read — the property the next test asserts.
                **({"HASHI_BACKUP_AGE_RECIPIENT": recipient} if recipient else {}),
                "HASHI_PUBLIC_HOST": "restore.invalid",
                "HASHI_PRIVATE_HOST": "restore-console.invalid",
                "HASHI_PRIVATE_PORT": "54143",
                "HASHI_OPERATOR_USERNAME": "owner",
                "HASHI_OPERATOR_PASSWORD_HASH": escaped(hash_password(OPERATOR_PASSWORD)),
                "POSTGRES_USER": "hashi",
                "POSTGRES_PASSWORD": "restore-not-real",
                "POSTGRES_DB": "hashi",
                "CADDY_ACME_EMAIL": "nobody@restore.invalid",
                # The dev overlay is added below only so the scenario can reach the API
                # from outside. A real install uses the base file alone.
                "DEV_API_PORT": str(port),
                "DEV_DB_PORT": str(port + 32),
                "DEV_BIND_ADDR": _bind_address(),
            }.items()
        )
    )
    path.chmod(0o600)
    return path


def _bind_address() -> str:
    """Where the disposable stack publishes, and why it is not always loopback.

    Same reasoning as ``deploy/docker-compose.dev.yml``'s own comment: when the engine is
    not the machine running pytest — the fleet's isolated dind — ``127.0.0.1`` is dind's
    loopback and nothing here could reach the stack. Derived from the host the rest of
    this suite was told to use rather than hardcoded either way.
    """
    import os

    return "0.0.0.0" if os.environ.get("E2E_API_HOST", "127.0.0.1") != "127.0.0.1" else "127.0.0.1"


def plain_http_overlay(directory: pathlib.Path) -> pathlib.Path:
    """An overlay that lets this scenario speak plain HTTP to the stack.

    The session cookie is ``Secure`` by default, so over http the operator's login
    succeeds and the cookie is dropped — a 303 followed by a 401, which is exactly how
    this scenario first failed. A real install sits behind Caddy on https and needs none
    of this; ``deploy/docker-compose.e2e.yml`` makes the same accommodation for the same
    reason.

    Applied only AFTER ``scripts/panel-bootstrap.sh`` has installed the stack its own way,
    so what is under test is still the real install.
    """
    path = directory / "plain-http.yml"
    path.write_text(
        "services:\n"
        "  control:\n"
        "    environment:\n"
        '      HASHI_PUBLIC_HTTPS: "false"\n'
    )
    return path


def identity_file(directory: pathlib.Path, secret: str = BACKUP_IDENTITY) -> pathlib.Path:
    """The private half, written where only this run can read it.

    A file, because that is what ``HASHI_RESTORE_AGE_IDENTITY`` names and what an operator
    carries. It lives in pytest's tmp directory and nowhere near an env file — putting it
    in one on the control host is the exact thing the design forbids.
    """
    path = directory / "backup-identity.txt"
    path.write_text(secret + "\n")
    path.chmod(0o600)
    return path


def control_image(project: str, path: pathlib.Path) -> str:
    """The image name compose built for the control service of a running stack.

    Asked of compose rather than assembled from the project name, so the convention for
    naming built images is not something this file has to be right about.
    """
    import json

    listed = compose(project, path, "images", "--format", "json", "control")
    assert listed.returncode == 0, listed.stderr[-2000:]
    entries = json.loads(listed.stdout)
    assert entries, "compose knows of no image for the control service"
    entry = entries[0]
    return f"{entry['Repository']}:{entry['Tag']}"


def age_in_the_image(image: str, ciphertext: bytes, *, identity: str | None):
    """Try to open an artifact with the same `age` the script uses, and nothing else.

    The binary comes from the control image on purpose: the machine running this suite is
    not assumed to have age, because the point of shipping it in an image this repository
    builds is that any host able to run the stack can make and open a backup. Asserting
    with a different age would be asserting about a different tool than the one deployed.

    ``identity=None`` is the interesting case — it is everything the control host has.
    """
    # --entrypoint, because the image's own entrypoint boots the control plane: without it
    # this asks age a question and gets "database did not become reachable" back.
    command = ["docker", "run", "--rm", "-i", "--entrypoint", "sh"]
    program = "exec age --decrypt"
    if identity is not None:
        command += ["-e", f"AGE_IDENTITY={identity}"]
        # Written inside a container that is deleted on exit. The script itself never does
        # this on a real host — it streams the identity to age on stdin — but here the
        # ciphertext is what arrives on stdin, so the two have to swap places.
        program = 'printf "%s\\n" "$AGE_IDENTITY" > /tmp/identity; exec age --decrypt --identity /tmp/identity'
    command += [image, "-c", program]
    return subprocess.run(
        command, input=ciphertext, capture_output=True, timeout=120, env=_docker_env()
    )


def encrypt_in_the_image(image: str, plaintext: bytes, recipient: str = BACKUP_RECIPIENT) -> bytes:
    """The other direction, for building an artifact this scenario needs but the script
    would not write — a DAMAGED one. Encrypting needs only the public half, which is the
    property under test, so nothing secret is involved in making it.
    """
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "--entrypoint", "sh",
         "-e", f"AGE_RECIPIENT={recipient}", image,
         "-c", 'exec age --recipient "$AGE_RECIPIENT"'],
        input=plaintext, capture_output=True, timeout=120, env=_docker_env(),
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


def compose(project: str, path: pathlib.Path, *args: str, dev: bool = True):
    files = ["-f", str(COMPOSE_FILE)]
    if dev:
        files += ["-f", str(DEV_OVERLAY), "-f", str(plain_http_overlay(path.parent))]
    return subprocess.run(
        ["docker", "compose", "--env-file", str(path), "-p", project, *files, *args],
        capture_output=True, text=True, timeout=600, cwd=REPO_ROOT, env=_docker_env(),
    )


def install(path: pathlib.Path, project: str) -> None:
    """Bring a stack up through the panel bootstrap, then publish a port for the test.

    The bootstrap runs first and unmodified, because a restore has to work on a host
    installed the way the owner installs one. The dev overlay is applied afterwards, only
    so this scenario can speak to the API; a real install never does it.
    """
    bootstrap = subprocess.run(
        [str(BOOTSTRAP), "--env-file", str(path)],
        capture_output=True, text=True, timeout=900, cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        env={**_docker_env(), "COMPOSE_PROJECT_NAME": project, "PANEL_HEALTH_TIMEOUT": "150"},
    )
    assert bootstrap.returncode == 0, (
        f"could not install the stack under test:\n{bootstrap.stdout[-3000:]}\n"
        f"{bootstrap.stderr[-3000:]}"
    )
    published = compose(project, path, "up", "-d")
    assert published.returncode == 0, published.stderr[-3000:]


# --- the disposable object store, and the upload under test (M28.3) -----------

def uploader() -> object:
    """The program `scripts/backup.sh` runs inside the container, imported here.

    Used for ONE thing this file cannot otherwise do: sign a `GetObject` so the scenario
    can read back what the control plane wrote. Reusing the code under test to check the
    code under test would normally be circular — it is not here, because the thing being
    proven is that a real S3 implementation ACCEPTS what this signs, and the store is the
    one making that judgement. A wrong signature is a 403 at the PUT, before any of this
    runs; the GET is only how the bytes come back.
    """
    import importlib.util

    source = REPO_ROOT / "deploy" / "backup" / "upload.py"
    spec = importlib.util.spec_from_file_location("hashi_backup_uploader", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stack_network(project: str, path: pathlib.Path) -> str:
    """The network the stack's containers are on, asked rather than assumed.

    The store has to be reachable by the one-off container `scripts/backup.sh` starts, and
    that container joins whatever network compose made for the project. Deriving the name
    from the project name would be this file being right about a compose convention;
    asking is the same choice ``control_image`` makes one function up.
    """
    listed = compose(project, path, "ps", "-q", "control")
    assert listed.returncode == 0, listed.stderr[-2000:]
    container = listed.stdout.strip().splitlines()[0]
    inspected = subprocess.run(
        ["docker", "inspect", "-f",
         "{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}", container],
        capture_output=True, text=True, timeout=60, env=_docker_env(),
    )
    assert inspected.returncode == 0, inspected.stderr[-2000:]
    return inspected.stdout.strip()


def object_store(project: str, path: pathlib.Path) -> dict | None:
    """Start the disposable endpoint, or say why there is none and let the caller skip.

    ``None`` when the image cannot be obtained — an offline machine that has never pulled
    it. The scenarios that need it skip loudly rather than failing: a suite that goes red
    because a third-party registry is unreachable teaches everyone to ignore it.

    THE PULL IS NOT THE QUESTION; HAVING THE IMAGE IS — M28.19. A pull ran here
    unconditionally and its exit code decided, so ten scenarios (four upload, six
    bucket-restore) skipped on a machine that had the image in its own store, because
    quay.io answers 401 to an anonymous request for it. That is the whole restore path
    unproven on the gate of the milestone whose subject is the restore path, reported as a
    skip nobody reads. Asking the daemon what it already has is the fix, and it changes
    NOTHING about what the scenarios do: the store that starts is a real MinIO, the
    artifact is really signed, really uploaded and really read back. What stops being a
    disqualification is a registry outage.

    The pull still runs first, and it is still the thing that picks up a re-tagged or a
    newer image where the registry can be reached; the local answer is a fallback rather
    than a replacement, so a host with an out-of-date copy is not pinned to it.
    """
    pulled = subprocess.run(
        ["docker", "pull", STORE_IMAGE],
        capture_output=True, text=True, timeout=600, env=_docker_env(),
    )
    if pulled.returncode != 0:
        held = subprocess.run(
            ["docker", "image", "inspect", STORE_IMAGE],
            capture_output=True, text=True, timeout=120, env=_docker_env(),
        )
        if held.returncode != 0:
            return None

    name = f"hashi-store-{RUN}"
    started = subprocess.run(
        ["docker", "run", "-d", "--name", name,
         "--network", stack_network(project, path),
         "-p", f"{_bind_address()}:{STORE_PORT}:9000",
         "-e", f"MINIO_ROOT_USER={STORE_ACCESS_KEY}",
         "-e", f"MINIO_ROOT_PASSWORD={STORE_SECRET_KEY}",
         "--entrypoint", "sh", STORE_IMAGE,
         # The bucket is a directory that exists before the server starts, which is all
         # this store needs to consider it created. Creating it over the API would take a
         # credential allowed to create buckets, and the whole point of the scenario is
         # that the host under test holds one that may only write an object.
         "-c", f"mkdir -p /data/{STORE_BUCKET} && exec minio server /data"],
        capture_output=True, text=True, timeout=300, env=_docker_env(),
    )
    assert started.returncode == 0, started.stderr[-2000:]

    import os
    import time

    published = os.environ.get("E2E_API_HOST", "127.0.0.1")
    store = {
        "container": name,
        # What the control plane under test is told: a name on the compose network, which
        # is the only way it could reach a store from inside.
        "endpoint": f"http://{name}:9000",
        # What THIS process uses to look: the published port.
        "reachable": f"http://{published}:{STORE_PORT}",
        "bucket": STORE_BUCKET,
        "prefix": STORE_PREFIX,
    }

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        with contextlib.suppress(httpx.HTTPError):
            # Any answer at all means it is serving; an anonymous request is refused, and
            # a refusal is an answer.
            httpx.get(store["reachable"], timeout=5.0)
            return store
        time.sleep(1.0)
    remove_store(store)
    raise AssertionError("the disposable object store never answered")


def remove_store(store: dict | None) -> None:
    if store:
        subprocess.run(
            ["docker", "rm", "-f", store["container"]],
            capture_output=True, timeout=120, env=_docker_env(),
        )


def configure_upload(
    path: pathlib.Path, store: dict, *, secret: str = STORE_SECRET_KEY, bucket: str | None = None
) -> None:
    """Point a stack's env file at the store, the way an operator's `.env` would.

    Rewritten rather than appended to, so a second call replaces the first — the failure
    scenarios differ from the working one by one value, which is exactly how an operator
    gets it wrong.
    """
    kept = [
        line
        for line in path.read_text().splitlines()
        if not line.startswith(("HASHI_BACKUP_S3_", "HASHI_BACKUP_ENABLED"))
    ]
    kept += [
        "HASHI_BACKUP_ENABLED=1",
        f"HASHI_BACKUP_S3_ENDPOINT={store['endpoint']}",
        "HASHI_BACKUP_S3_REGION=e2e-region-1",
        f"HASHI_BACKUP_S3_BUCKET={bucket if bucket is not None else store['bucket']}",
        f"HASHI_BACKUP_S3_PREFIX={store['prefix']}",
        f"HASHI_BACKUP_S3_ACCESS_KEY_ID={STORE_ACCESS_KEY}",
        f"HASHI_BACKUP_S3_SECRET_ACCESS_KEY={secret}",
    ]
    path.write_text("\n".join(kept) + "\n")
    path.chmod(0o600)


def object_in_the_store(store: dict, name: str) -> tuple[int, bytes]:
    """Read one object back with a credential the control host does not have."""
    module = uploader()
    config = {
        "scheme": "http",
        "netloc": store["reachable"].removeprefix("http://"),
        "region": "e2e-region-1",
        "bucket": store["bucket"],
        "access_key": STORE_ACCESS_KEY,
        "secret_key": STORE_SECRET_KEY,
    }
    request_path, headers = module.signed(
        config, "GET", store["prefix"] + name, module.EMPTY_BODY
    )
    with httpx.Client(timeout=120.0) as client:
        answer = client.get(store["reachable"] + request_path, headers=headers)
    return answer.status_code, answer.content


def run_backup(arguments: list[str], path: pathlib.Path, project: str):
    """The script, run the way an operator runs it, with nothing extra in its environment."""
    return subprocess.run(
        [str(BACKUP), *arguments],
        capture_output=True, text=True, timeout=600, cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        env={**_docker_env(), "ENV_FILE": str(path), "COMPOSE_PROJECT_NAME": project},
    )


def query(project: str, path: pathlib.Path, sql: str) -> str:
    """One value straight out of Postgres, bypassing the application entirely.

    Needed exactly where the API refuses: with the wrong key the control plane will not
    answer, and the question "did the rows arrive" still has to be asked.
    """
    result = compose(
        project, path, "exec", "-T", "db",
        "psql", "-U", "hashi", "-d", "hashi", "-tAc", sql,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip()


def rows_in(project: str, path: pathlib.Path, table: str) -> int:
    return int(query(project, path, f"select count(*) from {table}"))


def api(port: int) -> httpx.Client:
    host = __import__("os").environ.get("E2E_API_HOST", "127.0.0.1")
    return httpx.Client(base_url=f"http://{host}:{port}", follow_redirects=False, timeout=60.0)


@contextlib.contextmanager
def as_operator(port: int):
    """A logged-in operator client, closed on the way out.

    A context manager rather than a function returning a client: httpx refuses to be
    re-entered, and logging in has to happen before the caller's ``with`` block.
    """
    client = api(port)
    try:
        response = client.post(
            "/panel/login", data={"username": "owner", "password": OPERATOR_PASSWORD}
        )
        assert response.status_code == 303, response.text
        yield client
    finally:
        client.close()


def a_fleet(client: httpx.Client) -> dict:
    """One node with a transport, and one user holding a subscription.

    Deliberately the smallest fleet that exercises all three encrypted kinds: node-scoped
    transport secrets, a user's client-scoped material, and the subscription token's
    keyed digest.
    """
    node = client.post(
        "/api/nodes",
        json={"name": "leaf-restored", "address": "192.0.2.60", "location_label": "Restoreland"},
    )
    assert node.status_code == 201, node.text
    node_id = node.json()["id"]

    enabled = client.post(
        f"/api/nodes/{node_id}/transports",
        json={
            "transport_name": "vless-reality",
            "params": {"port": 8490, "decoy_host": "www.example.com", "decoy_port": 443,
                       "server_names": ["www.example.com"]},
        },
    )
    assert enabled.status_code == 201, enabled.text
    assert client.post(f"/api/nodes/{node_id}/state", json={"state": "active"}).status_code == 200

    user = client.post("/api/users", json={"nickname": "restored-user"})
    assert user.status_code == 201, user.text
    user_id = user.json()["id"]
    url = client.get(f"/api/users/{user_id}/subscription").json()["url"]

    return {
        "node_id": node_id,
        "user_id": user_id,
        "token": url.rsplit("/", 1)[-1],
        "transport_id": enabled.json()["id"],
        "params": enabled.json()["params"],
    }


def run_scheduler(
    verb: str, path: pathlib.Path, project: str, state: pathlib.Path
) -> subprocess.CompletedProcess:
    """The thing cron calls, run the way cron calls it."""
    return subprocess.run(
        [str(SCHEDULER), verb],
        capture_output=True, text=True, timeout=600, cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        env={
            **_docker_env(),
            "ENV_FILE": str(path),
            "COMPOSE_PROJECT_NAME": project,
            # The record goes in this run's own directory rather than the checkout's, so a
            # suite never overwrites the record of a real host it is running on.
            "HASHI_BACKUP_STATE_DIR": str(state),
        },
    )


def schedule_scenarios(directory: pathlib.Path, path: pathlib.Path) -> dict:
    """Watch the schedule actually fire — M28.5.

    A schedule nobody watched run is this milestone's whole subject, so this does not read
    the crontab and conclude things: it sets the appointed time about a minute into the
    future, calls `tick` the way cron would, and looks at what is on the disk before and
    after that minute passes. The ticks are driven here rather than by a cron daemon
    because the entry that is installed is `*/15` — proving a daemon fires it would mean
    waiting on a quarter-hour boundary, which proves cron rather than hashi. Everything
    that decides whether a backup happens is in the script, and that is what runs here.

    Three things come out of it: a first tick on a host with no record (which must back up
    at once), a tick before the appointed minute (which must not), and the same tick after
    it (which must). Then the case the plan names — a record whose last accounted day is
    four days ago, which is what a box that was switched off leaves behind.
    """
    import datetime
    import time

    state = directory / "schedule-state"
    artifacts = REPO_ROOT / "backups"
    artifacts.mkdir(exist_ok=True)
    before = set(artifacts.glob("*.age"))
    results: dict = {"artifacts_created": set()}

    try:
        # Far enough ahead that the two ticks below are safely before it, near enough that
        # the suite waits under two minutes. Truncated to the minute, which is the
        # granularity HASHI_BACKUP_AT is written at.
        target = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=75)
        appointed = target.strftime("%H:%M")
        kept = [
            line for line in path.read_text().splitlines()
            if not line.startswith(("HASHI_BACKUP_AT", "HASHI_BACKUP_TZ"))
        ]
        # `Etc/UTC` here only because a test needs a zone whose answer it can compute; the
        # product defaults to no zone at all and records that it did.
        path.write_text(
            "\n".join(kept + [f"HASHI_BACKUP_AT={appointed}", "HASHI_BACKUP_TZ=Etc/UTC"]) + "\n"
        )
        path.chmod(0o600)
        results["appointed"] = appointed

        # 1. A host with no record of any backup. The first tick takes one immediately —
        #    a control plane with no backup at all must not wait for tomorrow's 04:00.
        results["first"] = run_scheduler("tick", path, SOURCE_PROJECT, state)
        results["after_first"] = _new_artifacts(artifacts, before)
        results["record_after_first"] = _record(state)
        # Read now, because the artifacts this scenario writes are deleted on the way out:
        # they land in the checkout's own `backups/`, which belongs to whoever is running
        # the suite and not to it.
        results["first_artifact_head"] = (
            results["after_first"][0].read_bytes()[:21] if results["after_first"] else b""
        )

        # 2. The same tick again, still before the appointed minute. Nothing may happen:
        #    this is the 95 ticks out of 96 that must be silent.
        results["early"] = run_scheduler("tick", path, SOURCE_PROJECT, state)
        results["after_early"] = _new_artifacts(artifacts, before)

        # 3. Now wait for the minute to arrive, ticking the way cron does.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            time.sleep(5.0)
            results["fired"] = run_scheduler("tick", path, SOURCE_PROJECT, state)
            if len(_new_artifacts(artifacts, before)) > len(results["after_early"]):
                break
        results["after_appointed"] = _new_artifacts(artifacts, before)
        results["record_after_appointed"] = _record(state)

        # 4. The box that was down. Its record says the last day accounted for was four
        #    days ago, which is exactly what a machine that was off leaves behind.
        record = state / "last-run.json"
        gap_start = (
            datetime.date.fromisoformat(results["record_after_appointed"]["due_date"])
            - datetime.timedelta(days=4)
        ).isoformat()
        record.write_text(
            record.read_text().replace(
                f'"due_date": "{results["record_after_appointed"]["due_date"]}",',
                f'"due_date": "{gap_start}",',
                1,
            )
        )
        results["catch_up"] = run_scheduler("tick", path, SOURCE_PROJECT, state)
        results["record_after_catch_up"] = _record(state)
        results["after_catch_up"] = _new_artifacts(artifacts, before)
        results["gap_start"] = gap_start

        # 5. What `make backup-status` prints, read back off a record that four real runs
        #    over a real fleet produced — for the audit sweep in S11. It touches nothing
        #    and needs no docker, so it costs this fixture nothing.
        results["status"] = run_scheduler("status", path, SOURCE_PROJECT, state)
    finally:
        results["artifacts_created"] = _new_artifacts(artifacts, before)
        for written in results["artifacts_created"]:
            written.unlink(missing_ok=True)
    return results


def _new_artifacts(directory: pathlib.Path, before: set) -> list[pathlib.Path]:
    return sorted(set(directory.glob("*.age")) - before)


def _record(state: pathlib.Path) -> dict:
    import json

    path = state / "last-run.json"
    return json.loads(path.read_text()) if path.is_file() else {}


# --- the one command, on a machine that has never run this (M28.8) -------------

def run_the_one_command(
    path: pathlib.Path,
    project: str,
    *,
    identity: pathlib.Path,
    store: dict,
    secret: str = STORE_SECRET_KEY,
) -> subprocess.CompletedProcess:
    """`make restore-from-bucket`, with exactly what an operator is carrying and no more.

    Everything the bucket needs is in THIS PROCESS'S environment and in none of the files
    on the host under test: its env file names no object store at all, which is what a
    machine that has never run this project looks like. That is the contract — the read
    credential and the age identity are handed over at the moment of the restore and are
    never written onto a control-plane host.
    """
    return subprocess.run(
        [str(BACKUP), "restore-from-bucket"],
        capture_output=True, text=True, timeout=1800, cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        env={
            **_docker_env(),
            "ENV_FILE": str(path),
            "COMPOSE_PROJECT_NAME": project,
            "PANEL_HEALTH_TIMEOUT": "150",
            "HASHI_RESTORE_AGE_IDENTITY": str(identity),
            "HASHI_RESTORE_S3_ENDPOINT": store["endpoint"],
            "HASHI_RESTORE_S3_REGION": "e2e-region-1",
            "HASHI_RESTORE_S3_BUCKET": store["bucket"],
            "HASHI_RESTORE_S3_PREFIX": store["prefix"],
            "HASHI_RESTORE_S3_ACCESS_KEY_ID": STORE_ACCESS_KEY,
            "HASHI_RESTORE_S3_SECRET_ACCESS_KEY": secret,
            # NO `FORCE`, and its absence is the assertion — M28.10. This is a real
            # non-interactive session: `stdin=DEVNULL`, no tty, nothing to answer a
            # question on. It used to print the destructive confirmation, read EOF and
            # exit 2 with no sentence, after installing a control plane and fetching an
            # artifact, and the suite hid that behind `FORCE=1`. A machine this command
            # has just built from nothing holds no rows, so there is nothing to confirm
            # and nothing is asked; a run that starts asking again fails here.
        },
    )


def rescue_scenarios(
    directory: pathlib.Path, store: dict, fleet: dict, object_name: str
) -> dict:
    """Bring a control plane back on a host that has never run this — M28.8.

    Two invocations, and the first one is not a warm-up. The disposable store lives on the
    SOURCE stack's network, and the rescue stack's network does not exist until something
    creates it — so the first run is the command meeting a store it cannot reach, which is
    both a failure mode worth asserting and the only way to install this stack without
    this file doing the installing the command is supposed to do. Afterwards the store is
    connected to the network that first run created, and the second run is the real thing:
    list, fetch, open, restore.

    Nothing is asserted here; the scenarios below do that. The HTTP answers are collected
    while the stack is up, because it is torn down before this fixture returns.
    """
    results: dict = {}
    rescue = directory / "rescue"
    rescue.mkdir(exist_ok=True)
    # No recipient, because a rebuilt host has none: it was in the `.env` that was lost.
    # That is the state the closing screen has to notice and say out loud — M28.10.
    path = env_file(rescue, key=KEY, port=RESCUE_PORT, recipient=None)
    identity = identity_file(rescue)
    results["env_file"] = path.read_text()
    network = ""

    try:
        results["unreachable"] = run_the_one_command(
            path, RESCUE_PROJECT, identity=identity, store=store
        )
        # The store joins the network the run above created. A real operator's bucket is on
        # the internet and needs none of this; a disposable one on a compose network does.
        network = stack_network(RESCUE_PROJECT, path)
        connected = subprocess.run(
            ["docker", "network", "connect", network, store["container"]],
            capture_output=True, text=True, timeout=120, env=_docker_env(),
        )
        assert connected.returncode == 0, connected.stderr[-2000:]

        results["restored"] = run_the_one_command(
            path, RESCUE_PROJECT, identity=identity, store=store
        )

        # Published only now, and only so this process can speak to the panel: the command
        # installs the base stack, which publishes nothing, exactly as a real one does.
        published = compose(RESCUE_PROJECT, path, "up", "-d")
        assert published.returncode == 0, published.stderr[-3000:]

        with as_operator(RESCUE_PORT) as client:
            results["nodes"] = client.get("/api/nodes").json()
            results["users"] = client.get("/api/users").json()
        with api(RESCUE_PORT) as anonymous:
            answer = anonymous.get(f"/sub/{fleet['token']}")
            results["subscription_status"] = answer.status_code
            results["subscription"] = answer.text
        # What the command left on the rescue host: the artifact it fetched, kept, still
        # encrypted and not readable by anybody else on the box.
        landed = REPO_ROOT / "backups" / object_name
        results["fetched_exists"] = landed.is_file()
        results["fetched_mode"] = oct(landed.stat().st_mode & 0o777) if landed.is_file() else ""
        results["fetched_bytes"] = landed.read_bytes() if landed.is_file() else b""
    finally:
        # BEFORE the teardown, and this is the same trap the store itself carries: a
        # container attached to a compose project's network stops compose removing it, so
        # `down -v` leaves the network behind and the next run inherits it.
        if network:
            subprocess.run(
                ["docker", "network", "disconnect", "-f", network, store["container"]],
                capture_output=True, timeout=120, env=_docker_env(),
            )
        compose(RESCUE_PROJECT, path, "down", "-v")
        # Read above, removed here: this lands in the checkout the suite is running in.
        (REPO_ROOT / "backups" / object_name).unlink(missing_ok=True)
    return results


def offsite_scenarios(directory: pathlib.Path, path: pathlib.Path, fleet: dict) -> dict:
    """Drive every upload case once, while there is a stack and a store to drive it with.

    Kept in one place rather than four independent scenarios because all of it needs the
    same two expensive, short-lived things: a stack with a fleet in it, and a store on that
    stack's own network. Nothing is asserted here — the tests below do that — so a failure
    reads as the scenario it belongs to rather than as "the fixture broke".
    """
    store = object_store(SOURCE_PROJECT, path)
    if store is None:
        return {"store": None}

    results: dict = {"store": store}
    try:
        configure_upload(path, store)
        uploaded = directory / "uploaded.sql.gz.age"
        results["artifact"] = uploaded
        results["dump"] = run_backup(["dump", str(uploaded)], path, SOURCE_PROJECT)
        if uploaded.is_file():
            results["local"] = uploaded.read_bytes()
            results["object"] = object_in_the_store(store, uploaded.name)

        # The same artifact, the same store, a credential it will refuse — a key that was
        # rotated, mistyped, or never allowed to write. The operator has to be left holding
        # something rather than nothing.
        configure_upload(path, store, secret=WRONG_STORE_SECRET_KEY)
        results["denied"] = run_backup(["upload", str(uploaded)], path, SOURCE_PROJECT)
        results["after_denial"] = uploaded.read_bytes() if uploaded.is_file() else None

        # Switched on, half filled in — the state a host is in halfway through being set
        # up. It must be refused BEFORE the database is read, which is why the path it was
        # told to write to is checked afterwards and must not exist.
        half = directory / "half-configured.env"
        half.write_text(path.read_text())
        configure_upload(half, store, bucket="")
        never = directory / "never-written.sql.gz.age"
        results["refused"] = run_backup(["dump", str(never)], half, SOURCE_PROJECT)
        results["never"] = never

        # And the whole point of an offsite copy: getting it back onto a machine that has
        # never run this. Here, because it needs the store still standing and the object
        # already in it — M28.8.
        results["rescue"] = rescue_scenarios(directory, store, fleet, uploaded.name)
    finally:
        # Before the stack comes down: a container attached to the project's network stops
        # compose from removing it.
        remove_store(store)
    return results


@pytest.fixture(scope="module", autouse=True)
def docker_available() -> None:
    if shutil.which("docker") is None:
        pytest.skip("no docker CLI, so a restore cannot be exercised at all")


@pytest.fixture(scope="module")
def dumped(tmp_path_factory):
    """A filled source stack and a dump of it. The source is gone by the time we restore.

    Torn down before the restore deliberately: a restore that quietly depended on the
    original stack still running would pass here and fail on the day it is needed.

    Two artefacts come out of it. The one the script writes today — `age` ciphertext — and
    one built the way the script built them before M28.2, plain SQL gzipped, taken with
    pg_dump directly rather than through the script, because the script no longer has a
    code path that writes one. Files of that shape exist in the world and the restore has
    to keep taking them.
    """
    directory = tmp_path_factory.mktemp("restore-source")
    path = env_file(directory, key=KEY, port=SOURCE_PORT)

    install(path, SOURCE_PROJECT)
    try:
        with as_operator(SOURCE_PORT) as client:
            fleet = a_fleet(client)
            # Read what the user receives BEFORE the dump, so the assertion after the
            # restore is about the same bytes rather than about a shape.
            subscription = client.get(f"/sub/{fleet['token']}")
            assert subscription.status_code == 200
            fleet["subscription"] = subscription.text

        # Asked while the stack is up; used by the tests that run age after it is gone.
        fleet["image"] = control_image(SOURCE_PROJECT, path)

        legacy = directory / "pre-m28-2.sql.gz"
        old_shape = compose(
            SOURCE_PROJECT, path, "exec", "-T", "db",
            "pg_dump", "--username=hashi", "--dbname=hashi", "--clean", "--if-exists",
            "--format=plain",
        )
        assert old_shape.returncode == 0, old_shape.stderr[-2000:]
        legacy.write_bytes(gzip.compress(old_shape.stdout.encode()))
        fleet["legacy"] = legacy

        dump = directory / "hashi.sql.gz.age"
        result = run_backup(["dump", str(dump)], path, SOURCE_PROJECT)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert dump.is_file() and dump.stat().st_size > 0
        # This env file names no object store, which is what a host ships as. Kept so the
        # scenario below can assert the run SAYS the artifact went nowhere.
        fleet["local_only"] = result.stderr
        # And the whole run, both streams, for the audit sweep in S11: what an operator
        # (or cron) is shown by a dump taken over a real fleet.
        fleet["dump_run"] = result

        # A restore this session could never authorise, over a database that HAS a fleet in
        # it — M28.10. No `FORCE`, no terminal, and something real to lose: the one case
        # that must stop. Driven here rather than on a stack of its own because it changes
        # nothing by construction, and the assertion below is that the fleet is still here
        # afterwards. Before the schedule and the upload, so the `missed`/store state those
        # set up is untouched by it.
        fleet["refused_without_a_terminal"] = subprocess.run(
            [str(BACKUP), "restore", str(dump)],
            capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            env={
                **_docker_env(),
                "ENV_FILE": str(path),
                "COMPOSE_PROJECT_NAME": SOURCE_PROJECT,
                "HASHI_RESTORE_AGE_IDENTITY": str(identity_file(directory)),
            },
        )
        fleet["users_after_the_refusal"] = rows_in(SOURCE_PROJECT, path, "users")

        # The schedule, driven BEFORE the upload scenarios because those leave the env file
        # pointing at a store that has been torn down — M28.5.
        fleet["schedule"] = schedule_scenarios(directory, path)

        # Everything about the upload, driven here because it needs this stack up — M28.3.
        # It ends by bringing a control plane back on a fresh host out of the object it
        # just sent, which is what the whole offsite half exists for — M28.8.
        fleet["offsite"] = offsite_scenarios(directory, path, fleet)

        # A restore onto a database with NO TABLES IN IT — M28.7. Last, and on this stack,
        # because it replaces a database that is about to be thrown away anyway: no second
        # stack is installed for it and it costs this fixture one restore.
        #
        # WHY it is worth the lines. Every restore scenario below runs against a target
        # whose migrations have already made the tables, so `--clean --if-exists` drops
        # something real. A bare database is where those same statements find nothing, and
        # it is the disaster-recovery shape this whole milestone exists for — a host rented
        # an hour ago. Nothing here had ever read what that prints, which is exactly how
        # M28.7's audit came to claim more than it had measured. S12 is the assertion.
        emptied = compose(
            SOURCE_PROJECT, path, "exec", "-T", "db",
            "psql", "-U", "hashi", "-d", "hashi",
            "-c", "drop schema public cascade; create schema public;",
        )
        assert emptied.returncode == 0, emptied.stderr[-2000:]
        # Counted rather than assumed: if the drop quietly did not happen, the restore
        # below would go over a populated database and the scenario would be the same one
        # as S1 wearing a different name — which is precisely the mistake it exists to fix.
        fleet["tables_before_bare_restore"] = query(
            SOURCE_PROJECT, path,
            "select count(*) from information_schema.tables where table_schema = 'public'",
        )
        fleet["onto_bare"] = restore_into(
            dump, path, SOURCE_PROJECT, identity=identity_file(directory)
        )
    finally:
        compose(SOURCE_PROJECT, path, "down", "-v")

    return dump, fleet


def restore_into(
    dump: pathlib.Path,
    path: pathlib.Path,
    project: str,
    *,
    identity: pathlib.Path | None = None,
):
    """Run the restore the way an operator does, with what they are carrying.

    ``identity=None`` is not an oversight: it is how a pre-M28.2 artifact is restored, and
    the absence of the variable is part of what those scenarios assert.
    """
    return subprocess.run(
        [str(BACKUP), "restore", str(dump)],
        capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        env={
            **_docker_env(),
            "ENV_FILE": str(path),
            "COMPOSE_PROJECT_NAME": project,
            # Supplied HERE, at the moment of the restore, and nowhere else. It is not in
            # the env file above and never reaches the control host — see .env.example.
            **({"HASHI_RESTORE_AGE_IDENTITY": str(identity)} if identity else {}),
            # The confirmation prompt exists because a restore is destructive and has no
            # undo. Skipping it has to be deliberate, which is why it is an env var and
            # not a flag.
            "FORCE": "1",
        },
    )


# --- S1: the restore carries the fleet ----------------------------------------

def test_a_clean_stack_restored_from_a_dump_carries_the_whole_fleet(dumped, tmp_path) -> None:
    """S1. Users, nodes, enabled transports — and the secrets still decrypt.

    The last one is the point of the whole file. A dump that restores every row and then
    cannot decrypt any of them is not a restored fleet: it is a database that looks right
    and serves nobody. So the assertion is not "the user row exists" but "the user's
    own subscription link still resolves to the same configuration".
    """
    dump, fleet = dumped
    path = env_file(tmp_path, key=KEY, port=TARGET_PORT)
    install(path, TARGET_PROJECT)

    try:
        result = restore_into(dump, path, TARGET_PROJECT, identity=identity_file(tmp_path))
        assert result.returncode == 0, f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"

        with as_operator(TARGET_PORT) as client:
            nodes = client.get("/api/nodes").json()
            assert [node["id"] for node in nodes] == [fleet["node_id"]], nodes
            assert nodes[0]["state"] == "active", "a restored node came back out of service"

            users = client.get("/api/users").json()
            assert [user["id"] for user in users] == [fleet["user_id"]], users

            # The node-scoped material: present, and the non-secret half unchanged.
            assert nodes[0]["location_label"] == "Restoreland"

        # THE assertion. Anonymous, exactly as the user's client fetches it, with the
        # link they already hold — and byte for byte what it was before the dump. This is
        # only possible if every encrypted value decrypted with the restored key AND the
        # token's keyed digest still matches.
        with api(TARGET_PORT) as anonymous:
            after = anonymous.get(f"/sub/{fleet['token']}")
            assert after.status_code == 200, (
                "the user's link does not resolve after a restore — their access did "
                "not survive"
            )
            assert after.text == fleet["subscription"], (
                "the restored fleet serves a different configuration than the one that "
                "was dumped"
            )

        # M28.7. A restore pipes plain SQL into `psql`, which echoes a command tag per
        # statement — so what an operator watches during a restore is the one place a row
        # of the database could reach a terminal. This is the restore OVER a populated
        # database; the bare-database one, which is louder, is S12.
        watched = result.stdout + result.stderr
        for needle in (*NOBODY_MAY_BE_NAMED, fleet["token"], KEY, BACKUP_IDENTITY):
            assert needle not in watched, (
                f"the restore printed {needle!r} — a restore is watched by an operator and "
                "its output is a copy of nothing"
            )
    finally:
        compose(TARGET_PROJECT, path, "down", "-v")


# --- S2: the wrong key does not hand anything over ----------------------------

def test_the_same_dump_with_a_different_key_yields_no_secrets_and_says_so(
    dumped, tmp_path
) -> None:
    """S2. Restoring is not the same as being able to read.

    Encryption at rest is only worth anything if a dump in the wrong hands is inert. So
    the rows arrive — that is what a dump does — and everything they protect stays shut,
    loudly. Both halves are asserted, because either alone would be a false comfort:
    silence would leave the operator to discover it on the day they need a node, and a
    plaintext secret would mean the encryption was decorative.

    What running it actually showed, and what this now asserts: the refusal is not
    confined to one screen. Every operator read that touches an encrypted column — the
    node list included, because a node carries an SSH key — answers ``secrets_unreadable``
    with the key named. That is the right behaviour and stronger than "one endpoint
    complains": there is no corner of the panel where a wrong-key restore looks normal.
    """
    dump, fleet = dumped
    project = f"{TARGET_PROJECT}-wrongkey"
    path = env_file(tmp_path, key=WRONG_KEY, port=TARGET_PORT + 2)
    install(path, project)

    try:
        result = restore_into(dump, path, project, identity=identity_file(tmp_path))
        # The restore itself SUCCEEDS: psql does not know or care about our key. Asserted
        # rather than assumed, because "it failed" would be the wrong kind of comfort —
        # the rows really are there, and that is the situation encryption has to survive.
        assert result.returncode == 0, f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"

        # The rows arrived — read straight from Postgres, because the API cannot tell us:
        # it refuses, which is the other half of this scenario.
        assert rows_in(project, path, "nodes") == 1
        assert rows_in(project, path, "users") == 1

        # And what is stored is ciphertext. A Fernet token begins `gAAAA`; a plaintext JSON
        # object would begin `{`. This is the assertion that would fail if encryption at
        # rest ever quietly stopped happening — at which point the dump in anyone's hands
        # would be readable.
        stored = query(project, path, "select secrets from node_transports limit 1")
        assert stored.startswith("gAAAA"), (
            f"a node-transport's secrets column is not ciphertext: {stored[:40]!r}"
        )

        with as_operator(TARGET_PORT + 2) as client:
            # Every read that touches an encrypted column refuses, and names the setting.
            for endpoint in (
                "/api/nodes",
                f"/api/users/{fleet['user_id']}/subscription",
            ):
                response = client.get(endpoint)
                assert response.status_code == 409, (
                    f"{endpoint} answered {response.status_code} after a restore with the "
                    f"wrong key: {response.text[:300]}"
                )
                body = response.json()["error"]
                assert body["code"] == "secrets_unreadable"
                assert "HASHI_SECRET_KEY" in body["message"], (
                    "the failure does not tell the operator that the key does not match — "
                    "they would read it as data loss"
                )
                # It says the data is fine, which is the difference between fixing one
                # line in an env file and going to look for another dump.
                assert "intact" in body["message"]
                # And it says nothing about the data itself.
                for leak in ("gAAAA", "BEGIN", "192.0.2.60", fleet["token"]):
                    assert leak not in response.text, f"the refusal leaked {leak!r}"

        # The user's own link is dead rather than serving something wrong. A 404, because
        # the token's lookup digest is derived from the key too — so the subscription
        # cannot even be found, which is the correct answer rather than an error.
        with api(TARGET_PORT + 2) as anonymous:
            assert anonymous.get(f"/sub/{fleet['token']}").status_code == 404
    finally:
        compose(project, path, "down", "-v")


# --- S3: an interrupted restore leaves nothing half-done ----------------------

def test_a_restore_that_fails_halfway_leaves_the_database_untouched(dumped, tmp_path) -> None:
    """S3. All or nothing — which today is asserted only against the script's text.

    A half-applied restore is the worst outcome available: some users back, some gone,
    some nodes carrying credentials that no longer exist, and an operator with no way to
    tell which. ``--single-transaction`` and ``ON_ERROR_STOP`` are what prevent it, and
    this is the assertion that proves they are doing it rather than merely being written
    down.

    The damaged dump is built from the real one, so everything before the injected error
    is valid SQL that WOULD have applied. That is what makes the assertion meaningful:
    without the transaction, the fleet would be half there.

    It is damaged in the SHAPE the script writes, not in the older plain one: opening the
    artifact is now part of the restore, and a transaction test that skipped that stage
    would stop covering the path an operator actually takes.
    """
    dump, fleet = dumped
    project = f"{TARGET_PROJECT}-halfway"
    path = env_file(tmp_path, key=KEY, port=TARGET_PORT + 4)

    # Built BEFORE the stack is installed: everything here can fail, and a failure between
    # the install and the try/finally below leaks a running stack onto the machine.
    damaged = tmp_path / "damaged.sql.gz.age"
    # Opened with the identity this scenario carries, damaged, and sealed again with the
    # PUBLIC half — which is all encrypting ever needs, and is the asymmetry under test.
    opened = age_in_the_image(fleet["image"], dump.read_bytes(), identity=BACKUP_IDENTITY)
    assert opened.returncode == 0, opened.stderr[-2000:]
    text = gzip.decompress(opened.stdout).decode()
    # Cut after the users table's data and append a statement Postgres must reject.
    marker = text.rfind("COPY public.users")
    assert marker != -1, "the dump does not contain the users table, so this is vacuous"
    cut = text.find("\n\n", marker)
    damaged.write_bytes(
        encrypt_in_the_image(
            fleet["image"],
            gzip.compress(
                (text[:cut] + "\n\nSELECT this_function_does_not_exist();\n").encode()
            ),
        )
    )

    install(path, project)
    try:
        result = restore_into(damaged, path, project, identity=identity_file(tmp_path))
        assert result.returncode != 0, (
            "a restore that hit a broken statement reported success"
        )

        with as_operator(TARGET_PORT + 4) as client:
            # Nothing arrived. The stack was installed and empty, and it is still empty —
            # not "one node and no users", which is what a non-transactional restore
            # would have left.
            assert client.get("/api/nodes").json() == []
            assert client.get("/api/users").json() == []

        with api(TARGET_PORT + 4) as anonymous:
            assert anonymous.get(f"/sub/{fleet['token']}").status_code == 404
    finally:
        compose(project, path, "down", "-v")


# --- S4: the host cannot read back what it just wrote -------------------------

def test_the_host_that_wrote_the_backup_cannot_read_it_back(dumped) -> None:
    """S4. The point of a keypair, asserted rather than asserted-about — M28.2.

    The control host holds the PUBLIC half and nothing else, so it can write a backup and
    cannot open one. That is what makes the artifact safe to copy off the machine: seizing
    the box yields every backup it ever wrote and opens none of them. A design where the
    host could decrypt would look identical from the outside and be worth nothing.

    Three attempts with everything that host has, then one with what the operator carries.
    No stack is installed: this is about bytes and keys, and the age it uses is the one
    from the image the stack was built from.
    """
    dump, fleet = dumped
    raw = dump.read_bytes()
    image = fleet["image"]

    assert raw.startswith(b"age-encryption.org/v1\n"), (
        "the artifact is not age ciphertext at all"
    )
    # Nothing readable survives into the file. The node address and the token are the two
    # things the plan names as what a reader of the bucket must not get; the SQL markers
    # are what a plain dump would have opened with.
    for leak in (b"COPY public.", b"CREATE TABLE", b"192.0.2.60", b"gAAAA",
                 fleet["token"].encode()):
        assert leak not in raw, f"the artifact carries {leak!r} in the clear"

    # 1. Everything the control host has: the artifact, and no identity anywhere on it.
    none_at_all = age_in_the_image(image, raw, identity=None)
    assert none_at_all.returncode != 0, "the artifact opened with no identity at all"
    assert b"no identity matched" in none_at_all.stderr, none_at_all.stderr[-500:]

    # 2. An identity, but not this one. Holding A key is not holding THE key.
    unrelated = age_in_the_image(image, raw, identity=UNRELATED_IDENTITY)
    assert unrelated.returncode != 0, "an unrelated identity opened the artifact"
    assert b"no identity matched" in unrelated.stderr, unrelated.stderr[-500:]

    # 3. The public half the host DOES hold, offered as though it were a key. This is the
    #    mistake an operator might actually make, and it must fail rather than half-work.
    as_a_key = age_in_the_image(image, raw, identity=BACKUP_RECIPIENT)
    assert as_a_key.returncode != 0, "the public recipient decrypted the artifact"

    # 4. And the identity the owner carries opens it, so the failures above are about the
    #    key rather than about a broken file.
    carried = age_in_the_image(image, raw, identity=BACKUP_IDENTITY)
    assert carried.returncode == 0, carried.stderr[-2000:]
    assert b"COPY public.users" in gzip.decompress(carried.stdout)


# --- S5: an artifact from before the encryption still restores ----------------

def test_an_artifact_written_before_the_encryption_still_restores(dumped, tmp_path) -> None:
    """S5. Plain `.sql.gz` files exist in the world, and they are somebody's last backup.

    Breaking them would mean the step that made backups safe also made every backup taken
    before it unusable — discovered, as always, on the day one is needed. So the script
    reads the file to decide what it is holding, takes the old shape as-is, and needs no
    identity for it: this restore is run with ``HASHI_RESTORE_AGE_IDENTITY`` unset, which
    is the situation of an operator who has an old dump and no keypair yet.

    It also says which shape it found before it touches anything, so the operator is never
    guessing which kind of file they just restored.
    """
    dump, fleet = dumped
    project = f"{TARGET_PROJECT}-legacy"
    path = env_file(tmp_path, key=KEY, port=TARGET_PORT + 6)
    install(path, project)

    try:
        result = restore_into(fleet["legacy"], path, project)
        assert result.returncode == 0, f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        assert "PLAIN SQL, gzipped" in result.stderr, (
            "the operator is not told which shape was restored:\n" + result.stderr[-1000:]
        )

        with as_operator(TARGET_PORT + 6) as client:
            assert [node["id"] for node in client.get("/api/nodes").json()] == [
                fleet["node_id"]
            ]
            assert [user["id"] for user in client.get("/api/users").json()] == [
                fleet["user_id"]
            ]

        # The same assertion S1 makes, because "it restored" means the user's link works.
        with api(TARGET_PORT + 6) as anonymous:
            after = anonymous.get(f"/sub/{fleet['token']}")
            assert after.status_code == 200, after.text
            assert after.text == fleet["subscription"]
    finally:
        compose(project, path, "down", "-v")


# --- S6: the artifact actually leaves the machine ------------------------------

def offsite(dumped) -> dict:
    """The upload results, or a loud skip when there was no store to send to."""
    results = dumped[1]["offsite"]
    if results["store"] is None:
        pytest.skip(
            f"{STORE_IMAGE} could not be pulled and is not in this machine's own image "
            "store either, so no S3-compatible endpoint exists to send an object to. The "
            "upload is UNPROVEN on this machine — this is a skip, not a pass."
        )
    return results


def test_the_artifact_is_sent_to_the_object_store_and_lands_byte_for_byte(dumped) -> None:
    """S6. The step's whole claim: the backup is somewhere other than the box it came from.

    Read back afterwards with the store's own credential — which the control plane under
    test does not have and must never have — and compared byte for byte with the file on
    the host. Anything weaker ("the script printed success") would pass for a script that
    uploaded nothing at all, which is exactly the failure this milestone exists to prevent.
    """
    results = offsite(dumped)
    sent = results["dump"]
    assert sent.returncode == 0, f"{sent.stdout[-3000:]}\n{sent.stderr[-3000:]}"
    assert "the object store accepted it" in sent.stderr, sent.stderr[-2000:]

    status, stored = results["object"]
    assert status == 200, f"the object is not in the bucket: HTTP {status}"
    assert stored == results["local"], (
        "the object in the bucket is not the artifact that was written here"
    )
    assert stored.startswith(b"age-encryption.org/v1\n"), (
        "what left this machine is not the encrypted shape"
    )

    # The upload is a copy, not a move: the artifact is still here, and a restore run an
    # hour later from this host does not depend on the store answering.
    assert results["artifact"].is_file()

    # Nothing in what a person or a log sees carries the credential that sent it.
    for leak in (STORE_SECRET_KEY, "Signature=", "Credential="):
        assert leak not in sent.stdout + sent.stderr, f"the upload printed {leak!r}"


def test_the_upload_says_what_it_proves_and_what_it_does_not(dumped) -> None:
    """S6b. The sentence an operator will quote at 3am, and the one M28.6 must not inflate.

    A write-only credential cannot read its own object back, so "uploaded" is a statement
    about a response and not about a bucket. The run says so on every success, because the
    alternative is a project that believes it has an offsite backup on the strength of a
    tick mark.
    """
    sent = offsite(dumped)["dump"]
    assert "What it does not prove" in sent.stderr or "does not prove" in sent.stderr, (
        sent.stderr[-2000:]
    )
    assert "write-only" in sent.stderr


# --- S7: the store refuses, and the operator is left holding something ---------

def test_a_store_that_refuses_the_credential_leaves_the_artifact_and_its_own_exit_code(
    dumped,
) -> None:
    """S7. The dump succeeded and the object did not land. That is neither 0 nor 1.

    Exit 3 exists so a schedule, and the panel M28.6 builds on it, can tell "there is no
    backup" from "there is a backup and it never left the machine" — two different things
    to do about it. The artifact must survive the failure untouched: what the operator is
    holding is a complete, encrypted backup, and the retry is a send rather than a dump.
    """
    results = offsite(dumped)
    denied = results["denied"]
    assert denied.returncode == 3, (
        f"a refused upload exited {denied.returncode}, so it is indistinguishable from "
        f"having no backup at all:\n{denied.stderr[-2000:]}"
    )
    assert "did NOT leave this machine" in denied.stderr, denied.stderr[-2000:]
    assert "make backup-upload FROM=" in denied.stderr, (
        "the operator is not told how to send the file they are holding"
    )
    # What the store said, so the fix is a key and not a guess.
    assert "the object store did not take it" in denied.stderr
    assert "403" in denied.stderr, denied.stderr[-2000:]

    assert results["after_denial"] == results["local"], (
        "the artifact changed, or was removed, when its upload failed"
    )
    for leak in (WRONG_STORE_SECRET_KEY, STORE_SECRET_KEY):
        assert leak not in denied.stdout + denied.stderr, "the refusal printed the credential"


# --- S8: half-configured is refused before the database is read ----------------

def test_an_offsite_block_that_is_switched_on_and_incomplete_refuses_before_the_dump(
    dumped,
) -> None:
    """S8. The state a host is in halfway through being set up.

    Refusing after the dump would leave a fresh artifact on disk and an operator who has to
    work out whether it is safe where it is. Refusing first costs nothing and touches
    nothing — which is what the missing file below proves — and it names every variable
    that is missing at once rather than one per run.
    """
    results = offsite(dumped)
    refused = results["refused"]
    assert refused.returncode == 1, refused.stderr[-2000:]
    assert not results["never"].exists(), (
        "an artifact was written by a run that was supposed to refuse before dumping"
    )
    assert "HASHI_BACKUP_S3_BUCKET" in refused.stderr, refused.stderr[-2000:]
    assert "write-only" in refused.stderr


# --- S9: no store configured is a real mode, and it says so --------------------

def test_a_dump_with_no_store_configured_says_the_artifact_went_nowhere(dumped) -> None:
    """S9. `HASHI_BACKUP_ENABLED` unset is supported, and must never look like coverage.

    This is the state every host ships in, so the run that takes a local-only backup is the
    run most likely to be believed to have done more. It succeeds — a local artifact is a
    real thing to have — and it says in as many words that this artifact is on this host
    and nowhere else.
    """
    said = dumped[1]["local_only"]
    assert "on this host and nowhere else" in said, said[-2000:]
    assert "HASHI_BACKUP_ENABLED" in said


# --- S10: something runs it, and it is watched running -------------------------

def schedule(dumped) -> dict:
    return dumped[1]["schedule"]


def test_a_host_with_no_backup_at_all_gets_one_at_the_first_tick(dumped) -> None:
    """S10. The first tick after the schedule is installed, on a host with no record.

    Waiting for tomorrow's 04:00 would mean a control plane spends its first day with no
    backup — and that the operator learns whether the schedule works the morning after
    installing it, rather than within the quarter of an hour they are still watching.
    """
    observed = schedule(dumped)
    first = observed["first"]
    assert first.returncode == 0, f"{first.stdout[-2000:]}\n{first.stderr[-2000:]}"
    assert len(observed["after_first"]) == 1, (
        "the first tick on a host with no record did not take a backup: "
        f"{observed['after_first']}"
    )
    assert observed["first_artifact_head"] == b"age-encryption.org/v1", (
        "the schedule wrote something that is not the encrypted artifact the script writes"
    )
    record = observed["record_after_first"]
    assert record["last_success"]["exit_code"] == 0
    assert record["zone"] == "Etc/UTC" and record["zone_source"] == "configured"


def test_the_tick_waits_for_the_appointed_minute_and_then_fires(dumped) -> None:
    """S10b. The schedule was watched running — which is this milestone's whole subject.

    Both halves matter and neither is provable from the other: a tick that always backed up
    would pass "it fired" while making the hour meaningless, and a tick that never did
    would pass "it waited" while the host quietly went un-backed-up for ever. So the same
    tick is called before the appointed minute and after it, one minute apart, against a
    real stack, and what is asserted is what appeared on the disk.
    """
    observed = schedule(dumped)
    early = observed["early"]
    assert early.returncode == 0, f"{early.stdout[-2000:]}\n{early.stderr[-2000:]}"
    assert early.stdout == "" and early.stderr == "", (
        "a tick with nothing owed printed something; cron would mail that 96 times a day"
    )
    assert observed["after_early"] == observed["after_first"], (
        f"a tick before {observed['appointed']} took a second backup — the appointed time "
        "decides nothing"
    )

    assert len(observed["after_appointed"]) == len(observed["after_first"]) + 1, (
        f"the appointed minute ({observed['appointed']}) passed and no backup was taken: "
        f"{observed['after_appointed']}"
    )
    assert observed["fired"].returncode == 0
    assert observed["record_after_appointed"]["due_date"] > (
        observed["record_after_first"]["due_date"]
    ), "the run after the appointed time was not recorded against the new day"


def test_a_box_that_was_down_takes_the_backup_late_and_names_the_days_it_lost(
    dumped,
) -> None:
    """S10c. The failure the plan calls the one discovered during a restore.

    The record says the last day accounted for was four days ago — which is what a machine
    that was switched off leaves behind. The tick that finds it must back up AT ONCE rather
    than wait for the hour, and the three days in the gap must be written down by date,
    because after this run succeeds nothing else on this host would remember them.

    One run, not four: a dump is a copy of the database as it is now, so four runs today
    would be four copies of today wearing four different dates.
    """
    observed = schedule(dumped)
    catch_up = observed["catch_up"]
    assert catch_up.returncode == 0, f"{catch_up.stdout[-2000:]}\n{catch_up.stderr[-2000:]}"
    assert len(observed["after_catch_up"]) == len(observed["after_appointed"]) + 1, (
        "a box that had been down for four days took no backup when it came back"
    )

    record = observed["record_after_catch_up"]
    assert record["missed_total"] == 3, (
        f"the days with no backup were not recorded: {record['missed_dates']}"
    )
    assert len(record["missed_dates"]) == 3
    assert observed["gap_start"] not in record["missed_dates"], (
        "the last day that DID have a backup is listed as missed"
    )
    assert record["due_date"] not in record["missed_dates"], (
        "the day this very run backed up is listed as missed"
    )
    # NEWEST FIRST, as written by a real tick over a real gap — M28.12. Both readers label
    # the first few of these "most recent" and both sort what they read, because a record
    # is a file on a disk where a hand edit goes; this is the other half, that the file
    # this project writes needs no sorting to be right. The writer used to append them in
    # the order it walked the gap, which is oldest first.
    assert record["missed_dates"] == sorted(record["missed_dates"], reverse=True), (
        f"the writer stored the missed days oldest first: {record['missed_dates']}"
    )
    # And the record still answers M28.6's question after a successful catch-up: the days
    # that were lost survive the run that ends the gap.
    assert record["last_success"]["due_date"] == record["due_date"]
    assert record["last_success"]["outcome"] == "on-this-host-only"


def test_the_record_the_panel_will_read_says_nothing_about_anybody(dumped) -> None:
    """S10d. The one record that can hurt a real person is the one written automatically.

    This file is appended to by an unattended job for as long as the host lives, which is
    how a schedule becomes a log. What the fleet that produced it looked like — one node,
    one user, one subscription, all of it in the database this very run dumped — must be
    nowhere in it.
    """
    observed = schedule(dumped)
    written = (observed["record_after_catch_up"] or {})
    assert written, "no record was written at all"
    flat = repr(written)
    fleet = dumped[1]
    for secret in (fleet["token"], "restored-user", "leaf-restored", "192.0.2.60",
                   "Restoreland", "vless-reality"):
        assert secret not in flat, f"the backup record names {secret!r}"
    assert set(written) == {
        "schema", "written_at", "at", "at_source", "zone", "zone_source", "offsite",
        "due_date", "attempts", "retry_not_before", "last_attempt", "last_success",
        "last_failure", "missed_dates", "missed_total",
    }, sorted(written)


# --- S11: none of this wrote down who connected to what (M28.7) ----------------

# Everything that would be a finding if it turned up in what a run printed. The first five
# are the fleet this module really dumped — a nickname, a node's name and its real address,
# a location label and a live subscription token — and the rest are the secrets out of the
# env file that produced it. Checked against OUTPUT only: the artifact itself is supposed
# to contain the fleet, and it is `age` ciphertext by the time it reaches a disk.
NOBODY_MAY_BE_NAMED = (
    "restored-user",
    "leaf-restored",
    "192.0.2.60",
    "Restoreland",
)
NOTHING_MAY_BE_QUOTED = (KEY, "restore-not-real", STORE_SECRET_KEY, BACKUP_IDENTITY)

# Stands in for whatever an operator's malformed env-file line really holds — most likely
# HASHI_SECRET_KEY or POSTGRES_PASSWORD, since those are the long opaque values a hand edit
# goes wrong on.
PLANTED_IN_THE_ENV_FILE = "PLANTED-VALUE-THAT-MUST-NOT-BE-MAILED"


def _every_stream(fleet: dict) -> dict[str, str]:
    """Both streams of every run this module made, keyed by which run it was.

    Collected from the fixtures rather than by running anything again: these are the same
    processes the scenarios above already judged, so the sweep costs nothing and covers a
    dump, four scheduled ticks, a status, a successful upload, a refused upload and a
    refusal before the database was read.
    """
    runs = {"dump": fleet["dump_run"]}
    runs |= {
        f"schedule:{name}": fleet["schedule"][name]
        for name in ("first", "early", "fired", "catch_up", "status")
        if fleet["schedule"].get(name) is not None
    }
    runs |= {
        f"offsite:{name}": fleet["offsite"][name]
        for name in ("dump", "denied", "refused")
        if fleet["offsite"].get(name) is not None
    }
    # The two longest-running things this module does, and the two that print the most:
    # a whole rebuild that failed at the store and a whole rebuild that worked — M28.8.
    rescue = fleet["offsite"].get("rescue") or {}
    runs |= {
        f"rescue:{name}": rescue[name]
        for name in ("unreachable", "restored")
        if rescue.get(name) is not None
    }
    return {name: (run.stdout or "") + (run.stderr or "") for name, run in runs.items()}


def test_nothing_any_of_these_runs_printed_names_anybody_in_the_fleet_it_dumped(
    dumped,
) -> None:
    """S11a. A dump is a copy of the whole database; what it SAYS must be about nothing.

    The charter's one absolute prohibition is that nothing records who connected to what,
    at any level and including while debugging, and a backup job is a new thing that prints
    on every run — an artifact path, a size, an object name, a store's refusal. Every one of
    those is a place a fact about a person could surface, and the only way to know is to
    take a backup of a real fleet and read what came out.

    So this asserts against the fleet that was actually dumped a few minutes ago, on this
    run, rather than against a fixture: the user whose subscription S1 then fetched, the
    node whose address is in that dump, and the env file's own secrets. The failure paths
    are in here too — a refused upload and a half-configured refusal both print more than a
    success does, and more is where this goes wrong.
    """
    _, fleet = dumped
    token = fleet["token"]

    for name, said in _every_stream(fleet).items():
        for needle in NOBODY_MAY_BE_NAMED:
            assert needle not in said, f"`{name}` printed {needle!r}, which names a user or a node"
        assert token not in said, (
            f"`{name}` printed a subscription token — a bearer credential in a URL path"
        )
        for secret in NOTHING_MAY_BE_QUOTED:
            assert secret not in said, f"`{name}` printed a secret out of the env file"


def test_a_scheduled_run_never_mails_a_line_of_the_env_file(tmp_path) -> None:
    """S11b. The finding this step made, reproduced: one stray quote used to mail a secret.

    ``docker compose`` is the only thing allowed to open the env file, and when it cannot
    PARSE that file it quotes the offending line's whole value straight back —
    ``unterminated quoted value "…"``. ``scripts/backup.sh`` printed compose's complaint so
    that an operator could see which variable was wrong, and ``scripts/backup-run.sh``
    prints a failed run's whole output, which is what cron mails. A single unclosed quote
    on the ``HASHI_SECRET_KEY`` line therefore put the secret key in a mail spool, on every
    retry, every day, for as long as the file stayed wrong.

    Three of compose's parse errors carry the line's text and one carries only a variable
    name, so all four shapes are driven here. Nothing is dumped and no stack is needed —
    the refusal happens before anything reaches a database, which is itself part of the
    contract.
    """
    malformed = {
        "an unclosed quote": 'HASHI_BACKUP_AGE_RECIPIENT="age1' + PLANTED_IN_THE_ENV_FILE,
        "a stray dollar": f"HASHI_BACKUP_AGE_RECIPIENT=age1${{{PLANTED_IN_THE_ENV_FILE}",
        "a quote inside a value": f'HASHI_PRIVATE_HOST="a"{PLANTED_IN_THE_ENV_FILE}"',
        "a key with a space in it": f"A KEY={PLANTED_IN_THE_ENV_FILE}",
    }

    for why, line in malformed.items():
        path = tmp_path / "broken.env"
        path.write_text(
            f"POSTGRES_USER=hashi\nPOSTGRES_DB=hashi\n"
            f"HASHI_SECRET_KEY={PLANTED_IN_THE_ENV_FILE}\n{line}\n"
        )
        refused = run_backup(["dump"], path, SOURCE_PROJECT)

        assert refused.returncode == 1, f"{why}: {refused.stdout}\n{refused.stderr}"
        said = refused.stdout + refused.stderr
        assert PLANTED_IN_THE_ENV_FILE not in said, (
            f"{why}: a line of the env file reached the output of a run, which is what "
            "cron mails when a scheduled run fails"
        )
        assert "compose cannot read" in said, (
            f"{why}: the operator is not told that their env file is the problem"
        )
        assert str(path) in said, f"{why}: the operator is not told which file to look at"


# --- S12: the restore this backup actually exists for, and what it prints ------

def test_a_restore_onto_a_bare_database_prints_schema_and_never_a_row(dumped) -> None:
    """S12. The disaster-recovery restore — and the audit's own blind spot.

    Every other restore in this file goes into a stack whose migrations have already made
    the tables, so ``--clean --if-exists``'s ``DROP TABLE IF EXISTS`` drops something real
    and says nothing. Onto a database with NOTHING in it, the same statements are the
    loudest thing the product does — and nothing had ever read that output. This is the
    shape the whole milestone exists for: a host rented an hour ago.

    WHAT IT ACTUALLY PRINTS, measured rather than reasoned about: command tags, and not one
    table name. ``NOTICE: table "…" does not exist, skipping`` is what Postgres would
    answer, and it never arrives — because ``pg_dump`` puts ``SET client_min_messages =
    warning`` in the artifact's own preamble, so the restore is quiet about missing objects
    for reasons that belong to the DUMP and not to anything this repository chose. That is
    worth pinning precisely because it is not ours: a later change of format or flags could
    take it away without anyone here deciding to.

    Both halves are asserted, and they fail differently. A table name on the terminal would
    NOT be a charter matter — schema names are public, they are in this repository's own
    migrations, and a restore is interactive, never scheduled, so its output reaches an
    operator and never a log or cron's mail. It would make a sentence in M28.7's notes
    wrong, which is why the mechanism is asserted beside it. **A row is the charter matter**,
    and ``psql`` reports ``COPY <n>`` per table and never what is in one — so no nickname, no
    node name, no real address, no subscription token and neither of the two secrets a
    restore costs, checked against the fleet this module really dumped.
    """
    _, fleet = dumped
    restored = fleet["onto_bare"]
    watched = restored.stdout + restored.stderr

    assert restored.returncode == 0, f"{restored.stdout[-3000:]}\n{restored.stderr[-3000:]}"
    assert fleet["tables_before_bare_restore"] == "0", (
        "the database was not actually bare, so this scenario is S1 under another name"
    )

    # THE claim. A row of the database must not reach the terminal an operator is watching.
    for needle in (*NOBODY_MAY_BE_NAMED, fleet["token"], KEY, BACKUP_IDENTITY):
        assert needle not in watched, (
            f"a restore onto a bare database printed {needle!r} — psql reports `COPY <n>` "
            "per table and must never report what is in one"
        )

    # ...and the quieter half, with the reason beside it so a failure says which changed.
    assert "NOTICE" not in watched, (
        "a restore onto a bare database now names tables on the operator's terminal. That "
        "is not a charter violation — schema names are public and a restore is never "
        "scheduled — but M28.7 recorded that it does not happen, and the note is now wrong."
    )
    preamble = gzip.decompress(fleet["legacy"].read_bytes()).decode()[:4000]
    assert "SET client_min_messages = warning;" in preamble, (
        "the artifact no longer raises client_min_messages, which is the ONLY reason a "
        "restore onto a bare database says nothing about the objects it did not find"
    )


# --- S13: one command, on a machine that has never run this (M28.8) ------------

@pytest.fixture(scope="module")
def rescue(dumped) -> dict:
    """What the one command did on a fresh host, or a loud skip if there was no store."""
    _, fleet = dumped
    if fleet["offsite"].get("store") is None:
        pytest.skip(
            f"{STORE_IMAGE} is neither pullable nor on this machine, so nothing was in "
            "a bucket to come back out of — this is a skip, not a pass"
        )
    return fleet["offsite"]["rescue"]


def test_one_command_brings_the_control_plane_back_on_a_machine_that_never_ran_it(
    dumped, rescue
) -> None:
    """S13a. The step the whole milestone is for, end to end and with nothing else run.

    A host with no stack, no image, no database and an env file that names no object store
    at all. One command, three inputs — HASHI_SECRET_KEY in that env file, the age identity
    and a read credential, the last two handed over at the moment it runs — and what comes
    out is a control plane serving the same users and driving the same nodes as the one
    that was lost.

    The assertion is not "rows arrived". It is the user's own subscription link, fetched
    anonymously with the token they already hold, byte for byte what it was before the
    dump. That is only possible if the object was found in the bucket, opened with the
    identity, restored, and every encrypted column decrypted with the key in this new
    machine's env file.
    """
    _, fleet = dumped
    restored = rescue["restored"]
    assert restored.returncode == 0, f"{restored.stdout[-4000:]}\n{restored.stderr[-4000:]}"

    assert [node["id"] for node in rescue["nodes"]] == [fleet["node_id"]], rescue["nodes"]
    assert rescue["nodes"][0]["state"] == "active"
    assert [user["id"] for user in rescue["users"]] == [fleet["user_id"]], rescue["users"]

    assert rescue["subscription_status"] == 200, (
        "the user's link does not resolve on the rebuilt control plane — their access did "
        "not survive the one command that exists to carry it"
    )
    assert rescue["subscription"] == fleet["subscription"], (
        "the rebuilt control plane serves a different configuration than the one that was "
        "backed up"
    )


def test_the_restore_host_holds_neither_of_the_two_credentials_it_was_given(
    rescue,
) -> None:
    """S13b. What makes a restore cost two secrets that never meet.

    The age identity and the bucket's read credential are handed to the command in its
    environment and must be nowhere on the host when it is over — not in the env file it
    installed from, and not in anything it wrote. `HASHI_SECRET_KEY` is the deliberate
    exception and is asserted to be there, because the control plane cannot start without
    it: that key is the restored machine's own, exactly as it was the lost machine's.
    """
    env = rescue["env_file"]
    assert "HASHI_SECRET_KEY=" in env, (
        "the env file has no secret key, so this test is not watching the thing it says"
    )
    for carried in ("HASHI_RESTORE_", BACKUP_IDENTITY, STORE_SECRET_KEY, STORE_ACCESS_KEY):
        assert carried not in env, (
            f"{carried!r} ended up in the env file on the rebuilt control plane, which is "
            "the one place the design says it must never be"
        )
    # And the artifact it fetched is kept, still encrypted, readable by nobody else.
    assert rescue["fetched_exists"], "the fetched artifact was not kept on the host"
    assert rescue["fetched_mode"] == "0o600", rescue["fetched_mode"]
    assert rescue["fetched_bytes"].startswith(b"age-encryption.org/v1"), (
        "what was written to the rescue host's disk is not ciphertext"
    )


def test_a_store_it_cannot_reach_stops_before_anything_is_fetched_or_changed(
    rescue,
) -> None:
    """S13c. The first run, and it is not a warm-up.

    The store was on another network then, so this is the command meeting an endpoint that
    does not resolve from inside the stack it has just installed. Two things have to be
    true of that: the control plane must be UP anyway — which is what makes the command
    safe to run again, and is how the second run had a network for the store to join — and
    it must say that nothing was fetched and nothing was changed, because an operator who
    cannot tell a failed fetch from a half-finished restore will go looking for another
    artifact.
    """
    first = rescue["unreachable"]
    assert first.returncode != 0, "a store that cannot be reached was reported as a success"
    said = first.stdout + first.stderr
    assert "does not resolve" in said, (
        f"the refusal does not say the endpoint could not be reached: {said[-2000:]}"
    )
    assert "Nothing was fetched and nothing was changed" in said
    assert "the control plane answers on /healthz" in said, (
        "the run did not get as far as installing the control plane, so the failure is "
        "somewhere other than the one this scenario is about"
    )


def test_a_restore_that_cannot_be_confirmed_stops_and_says_so(dumped) -> None:
    """S14. The question is not printed into a session that cannot answer it — M28.10.

    Measured on the bare-host walk: over a non-interactive session the old code printed the
    confirmation, read EOF and exited 2 with **no sentence at all** — after installing a
    control plane and fetching an artifact. `ssh host 'make …'`, a wrapper, anything that
    closes stdin: the operator got a bare exit code at the end of a rebuild.

    This is the case that must still stop, because there is a real fleet in that database.
    The other case — a machine the command has just built from nothing — is asserted by
    S13, which now runs with no terminal and no `FORCE` and is expected to succeed.
    """
    _, fleet = dumped
    refused = fleet["refused_without_a_terminal"]
    said = refused.stdout + refused.stderr

    assert refused.returncode != 0, f"a restore nobody authorised went ahead: {said[-3000:]}"
    assert "no terminal here" in said, (
        f"it stopped without saying why a terminal matters: {said[-3000:]}"
    )
    assert "FORCE=1" in said, "the refusal does not say how to mean it deliberately"
    assert "row(s) of data" in said, (
        "the refusal does not say what it found, so the operator cannot tell a database "
        "with their fleet in it from one with nothing"
    )
    assert fleet["users_after_the_refusal"] == 1, (
        "the database was changed by a restore that refused"
    )


def test_a_machine_built_from_nothing_is_not_asked_what_it_is_overwriting(rescue) -> None:
    """S15. The other half of the same finding, and it is the reason S13 can run at all.

    A control plane installed minutes ago holds a migrated schema and no rows, so the old
    prompt — *"Every current node, user and credential is overwritten"* — described nothing
    in exactly the case the command exists for. It now counts, says what it found, and asks
    nothing.
    """
    said = rescue["restored"].stdout + rescue["restored"].stderr
    assert "no rows at all" in said, (
        f"the rebuild did not report an empty destination: {said[-3000:]}"
    )
    assert "nothing to confirm" in said
    assert "Type the database name to confirm" not in said, (
        "a machine with nothing in it was still asked to authorise the replacement of "
        "nothing — and over a session with no terminal, which is how this used to end in "
        "exit 2 and silence"
    )


def test_the_last_screen_only_names_commands_this_host_can_actually_run(rescue) -> None:
    """S16. Findings 3, 4 and 5 of the walk, all of them read off one screen.

    Between "restored" and "logged in" the screen used to contradict itself: it said
    `make down && make up`, which converges a deployed stack back to publishing NOTHING,
    and two paragraphs later `make up-panel` — which on this host fails anyway, because
    `HASHI_PRIVATE_BIND_ADDR` names a management-tunnel address a rebuilt machine does not
    have. And it said nothing at all about the thing that is now true of this host: the
    backup recipient and the write-only key were in the `.env` that was lost, so the
    machine built out of the backup history cannot add to it.
    """
    said = rescue["restored"].stdout + rescue["restored"].stderr
    closing = said[said.index("did NOT do"):]

    assert "make down && make up" not in said, (
        "the rebuild still ends by telling a deployed host to unpublish itself"
    )
    assert "make restart-control" in said

    assert "make up-panel-over-ssh" in closing, (
        "the only publication offered is the one that needs a tunnel this machine has not "
        "got — which is what sent the walk to `ip addr add`"
    )

    assert "HASHI_BACKUP_AGE_RECIPIENT" in closing, (
        "nothing on the last screen says this host is not backing anything up"
    )
    assert "make backup-schedule" in closing
    # MEASURED, not chosen: this rescue env file carries no recipient, exactly as a
    # rebuilt host's does not, so the screen has to be the NOT-backing-up one. The other
    # branch — a recipient present, nothing scheduled — is asserted as text only.
    assert "this host is NOT backing anything up" in closing, closing[-2000:]


def test_the_run_says_what_it_chose_what_it_saw_and_what_it_did_not_do(
    dumped, rescue
) -> None:
    """S13d. The output IS the product here: it is read once, under pressure, at 3am.

    Three things have to be on that screen. What is in the bucket, so an operator can see
    for themselves that the schedule did not stop six weeks ago. Which object was taken.
    And the three things the command cannot do — DNS, the certificate, telling anybody —
    because a restored control plane on a new address that the old name still points away
    from serves nobody, and those are the sentences that turn a green run into a plan.
    """
    _, fleet = dumped
    said = rescue["restored"].stdout + rescue["restored"].stderr
    uploaded = fleet["offsite"]["artifact"]

    assert "what is in the bucket, newest first" in said
    assert uploaded.name in said, "the run never names the object it took"
    assert "restored." in said

    closing = said[said.index("did NOT do"):]
    assert "DNS" in closing
    assert "certificate" in closing
    assert "Telling anybody" in closing
    assert "The data is intact; the key is wrong." in closing, (
        "the last screen does not say what a wrong HASHI_SECRET_KEY looks like — the one "
        "failure here that leaves everything looking fine"
    )
    # The delivery name is read off the running control plane rather than out of the env
    # file, so the sentence about DNS names the host this operator actually has to move.
    assert "restore.invalid" in closing, (
        "the DNS line does not name the delivery host, so it reads as generic advice"
    )
