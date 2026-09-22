"""A backup that has never been restored is not a backup — backlog item 32.

WHAT: fills a disposable stack, dumps it, restores the dump into a CLEAN stack, and
      checks that what the owner would need is actually there — plus the two failures
      that matter: a restore with the wrong key, and a restore that stops halfway.
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
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.yml"
DEV_OVERLAY = REPO_ROOT / "deploy" / "docker-compose.dev.yml"

RUN = uuid.uuid4().hex[:8]
SOURCE_PROJECT = f"hashi-restore-src-{RUN}"
TARGET_PROJECT = f"hashi-restore-dst-{RUN}"

# The key the source stack encrypts with. Fixed and obviously fake. The target stack is
# given the SAME key for the successful restore and a DIFFERENT one for the failure.
KEY = "e2e-restore-key-not-real-0000000000000000000000000"
WRONG_KEY = "e2e-restore-WRONG-key-not-real-0000000000000000000"

OPERATOR_PASSWORD = "restore-proves-the-backup"
# Loopback ports well clear of the dev (541xx) and e2e (542xx) blocks, per CLAUDE.md's
# published-port rule: this is a third stack on the same host and it must collide with
# neither.
SOURCE_PORT = 54300
TARGET_PORT = 54301


def _docker_env() -> dict[str, str]:
    import os

    env = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
    if os.environ.get("DOCKER_HOST"):
        env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
    return env


def env_file(directory: pathlib.Path, *, key: str, port: int) -> pathlib.Path:
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

    user = client.post("/api/friends", json={"nickname": "restored-user"})
    assert user.status_code == 201, user.text
    user_id = user.json()["id"]
    url = client.get(f"/api/friends/{user_id}/subscription").json()["url"]

    return {
        "node_id": node_id,
        "user_id": user_id,
        "token": url.rsplit("/", 1)[-1],
        "transport_id": enabled.json()["id"],
        "params": enabled.json()["params"],
    }


@pytest.fixture(scope="module", autouse=True)
def docker_available() -> None:
    if shutil.which("docker") is None:
        pytest.skip("no docker CLI, so a restore cannot be exercised at all")


@pytest.fixture(scope="module")
def dumped(tmp_path_factory):
    """A filled source stack and a dump of it. The source is gone by the time we restore.

    Torn down before the restore deliberately: a restore that quietly depended on the
    original stack still running would pass here and fail on the day it is needed.
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

        dump = directory / "hashi.sql.gz"
        result = subprocess.run(
            [str(BACKUP), "dump", str(dump)],
            capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
            env={**_docker_env(), "ENV_FILE": str(path), "COMPOSE_PROJECT_NAME": SOURCE_PROJECT},
        )
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert dump.is_file() and dump.stat().st_size > 0
    finally:
        compose(SOURCE_PROJECT, path, "down", "-v")

    return dump, fleet


def restore_into(dump: pathlib.Path, path: pathlib.Path, project: str):
    return subprocess.run(
        [str(BACKUP), "restore", str(dump)],
        capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        env={
            **_docker_env(),
            "ENV_FILE": str(path),
            "COMPOSE_PROJECT_NAME": project,
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
        result = restore_into(dump, path, TARGET_PROJECT)
        assert result.returncode == 0, f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"

        with as_operator(TARGET_PORT) as client:
            nodes = client.get("/api/nodes").json()
            assert [node["id"] for node in nodes] == [fleet["node_id"]], nodes
            assert nodes[0]["state"] == "active", "a restored node came back out of service"

            users = client.get("/api/friends").json()
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
        result = restore_into(dump, path, project)
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
                f"/api/friends/{fleet['user_id']}/subscription",
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
    """
    dump, fleet = dumped
    project = f"{TARGET_PROJECT}-halfway"
    path = env_file(tmp_path, key=KEY, port=TARGET_PORT + 4)
    install(path, project)

    damaged = tmp_path / "damaged.sql.gz"
    text = gzip.decompress(dump.read_bytes()).decode()
    # Cut after the users table's data and append a statement Postgres must reject.
    marker = text.rfind("COPY public.users")
    assert marker != -1, "the dump does not contain the users table, so this is vacuous"
    cut = text.find("\n\n", marker)
    damaged.write_bytes(
        gzip.compress(
            (text[:cut] + "\n\nSELECT this_function_does_not_exist();\n").encode()
        )
    )

    try:
        result = restore_into(damaged, path, project)
        assert result.returncode != 0, (
            "a restore that hit a broken statement reported success"
        )

        with as_operator(TARGET_PORT + 4) as client:
            # Nothing arrived. The stack was installed and empty, and it is still empty —
            # not "one node and no users", which is what a non-transactional restore
            # would have left.
            assert client.get("/api/nodes").json() == []
            assert client.get("/api/friends").json() == []

        with api(TARGET_PORT + 4) as anonymous:
            assert anonymous.get(f"/sub/{fleet['token']}").status_code == 404
    finally:
        compose(project, path, "down", "-v")
