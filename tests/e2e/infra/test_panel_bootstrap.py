"""Installing the panel on a host, for real — backlog item 31.

WHAT: runs ``scripts/panel-bootstrap.sh`` against a throwaway compose project and
      asserts the four things the charter asks of it: it is idempotent, it asks nothing,
      it verifies before claiming success, and it never generates ``HASHI_SECRET_KEY``.
WHY:  "everything is deployed by one script" is a charter line, and there are two
      scripts. The node one has existed since M1. This one did not exist at all, so the
      charter's own deployment story was half-written — and the missing half is the one
      the owner runs while replacing a seized host.
HOW:  a real stack, in its own compose project, with its own volumes, from an env file
      this module writes. The base compose file only — no dev overlay — so nothing is
      published, exactly as on a real host. Torn down with its volumes afterwards.

      Nothing is stubbed and nothing is mocked. That is the point: the failures this
      script exists to prevent are all failures of the real thing.

Boundary, stated plainly: this proves the control plane comes up and answers on a host
that has Docker. It proves nothing about TLS from the public internet (Caddy asks a real
CA for a real name, which this scenario neither has nor wants), and nothing about whether
any of it is reachable from inside Russia.
"""

import functools
import pathlib
import shutil
import subprocess
import sys
import uuid

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "panel-bootstrap.sh"

# Its own project name, so nothing here can touch the dev stack, the e2e stack, or
# whatever the owner is running. Unique per module run: a leftover project from an
# interrupted run must not make the next one pass for the wrong reason.
PROJECT = f"hashi-panel-bootstrap-{uuid.uuid4().hex[:8]}"

# A fixed, obviously fake key of a length the application accepts. Never a generated one:
# a value that changes per run would make a failure ambiguous.
FAKE_SECRET_KEY = "e2e-panel-bootstrap-key-not-real-000000000000000000"

# Long enough to build an image and initialise a database on a cold cache, short enough
# that the failure scenario does not hold the suite for three minutes.
HEALTH_TIMEOUT = "150"
FAILING_HEALTH_TIMEOUT = "20"

# The password the operator of this throwaway install chose. It exists in this file, in a
# hash of itself in a temporary directory, and nowhere else.
OPERATOR_PASSWORD = "panel-bootstrap-password"


@functools.cache
def operator_hash_line() -> str:
    """The line ``python -m control.cli hash-password`` prints, taken verbatim — M6.4.

    Verbatim is the whole point. The runbook tells an operator to run that command and
    paste its output into ``.env``, and on the live host the pasted value did not survive:
    ``docker compose --env-file`` expands what it reads, so ``$<digest>`` was read as a
    variable name and the digest arrived empty. This fixture stopped being
    ``hash_password(...).replace("$", "$$")`` — which was this suite doing by hand what no
    operator was doing at all, and therefore testing a path nobody walks.

    FORCED, not sampled. A base64 digest starts with a letter about five times in six and
    only a letter or an underscore is eaten, so a scenario that hashed one fixed password
    would pass or fail at random and the failure would look like flakiness rather than
    like this bug. Re-running the command until the dangerous shape comes up makes it
    certain — and it is the ordinary shape, not an exotic one.

    ``start_new_session`` detaches the child from the terminal, so ``getpass`` cannot open
    ``/dev/tty`` and falls back to stdin. Without it this hangs on a developer's machine
    and passes on a runner.
    """
    for _ in range(50):
        result = subprocess.run(
            [sys.executable, "-m", "control.cli", "hash-password"],
            input=f"{OPERATOR_PASSWORD}\n{OPERATOR_PASSWORD}\n",
            capture_output=True, text=True, timeout=120, cwd=REPO_ROOT,
            start_new_session=True,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        line = next(
            line for line in result.stdout.splitlines()
            if line.startswith("HASHI_OPERATOR_PASSWORD_HASH=")
        )
        if line.rsplit("$$", 1)[-1][:1].isalpha():
            return line
    raise AssertionError(
        "50 hashes in a row ended in a digit — hash-password has stopped printing base64, "
        "or stopped printing an escaped hash, and this scenario is no longer forcing the "
        "case it exists to force"
    )


def env_file(directory: pathlib.Path, **overrides: str | None) -> pathlib.Path:
    """A complete env file, with keys removable by passing ``None``.

    Written per scenario rather than shared, because half of what is under test is what
    the script does when a key is absent — and a shared file would have to be mutated,
    which is how two scenarios start depending on their order.
    """
    values: dict[str, str | None] = {
        "HASHI_SECRET_KEY": FAKE_SECRET_KEY,
        "HASHI_PUBLIC_HOST": "panel-bootstrap.invalid",
        # M7's private site. Required by the caddy service since the Caddyfile split in
        # two; the port is inside the container only, because this install publishes
        # nothing (the script uses the base compose file alone).
        "HASHI_PRIVATE_HOST": "panel-bootstrap-console.invalid",
        "HASHI_PRIVATE_PORT": "54143",
        "HASHI_OPERATOR_USERNAME": "owner",
        # Pasted exactly as the command printed it, escaping and all — see above.
        "HASHI_OPERATOR_PASSWORD_HASH": operator_hash_line().split("=", 1)[1],
        "POSTGRES_USER": "hashi",
        "POSTGRES_PASSWORD": "panel-bootstrap-not-real",
        "POSTGRES_DB": "hashi",
        "CADDY_ACME_EMAIL": "nobody@panel-bootstrap.invalid",
    }
    values.update(overrides)

    path = directory / "panel.env"
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items() if value is not None)
    )
    path.chmod(0o600)
    return path


def run_bootstrap(
    path: pathlib.Path, *, project: str, timeout_seconds: str = HEALTH_TIMEOUT
) -> subprocess.CompletedProcess:
    """Run the script exactly as an operator would, with no TTY and no input.

    ``stdin`` is closed rather than inherited, which is the mechanism behind the
    "not one interactive question" property: a ``read`` anywhere in the script would get
    EOF and the run would fail here instead of hanging in production.
    """
    return subprocess.run(
        [str(SCRIPT), "--env-file", str(path)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(path.parent),
            "COMPOSE_PROJECT_NAME": project,
            "PANEL_HEALTH_TIMEOUT": timeout_seconds,
            **({"DOCKER_HOST": _docker_host()} if _docker_host() else {}),
        },
    )


def _docker_host() -> str:
    import os

    return os.environ.get("DOCKER_HOST", "")


def compose(
    project: str, *args: str, stdin: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker", "compose", "-p", project,
            "-f", str(REPO_ROOT / "deploy" / "docker-compose.yml"),
            *args,
        ],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=300,
        cwd=REPO_ROOT,
        # The compose invocations below only inspect and tear down, so they need no env
        # file — but interpolation still runs, so supply the few keys it reads.
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HASHI_SECRET_KEY": FAKE_SECRET_KEY,
            "HASHI_PUBLIC_HOST": "panel-bootstrap.invalid",
            "HASHI_PRIVATE_HOST": "panel-bootstrap-console.invalid",
            "HASHI_PRIVATE_PORT": "54143",
            "HASHI_OPERATOR_USERNAME": "owner",
            "HASHI_OPERATOR_PASSWORD_HASH": "x",
            "POSTGRES_USER": "hashi",
            "POSTGRES_PASSWORD": "panel-bootstrap-not-real",
            "POSTGRES_DB": "hashi",
            "CADDY_ACME_EMAIL": "nobody@panel-bootstrap.invalid",
            **({"DOCKER_HOST": _docker_host()} if _docker_host() else {}),
        },
    )


def container_ids(project: str) -> list[str]:
    result = compose(project, "ps", "-q")
    return sorted(result.stdout.split())


@pytest.fixture(scope="module", autouse=True)
def docker_available() -> None:
    if shutil.which("docker") is None:
        pytest.skip("no docker CLI, so the panel bootstrap cannot be run at all")


# --- the refusals, which cost nothing to run ----------------------------------

def test_it_refuses_to_run_without_a_secret_key_and_never_generates_one(tmp_path) -> None:
    """The one rule here that protects a person rather than an uptime figure.

    ``HASHI_SECRET_KEY`` decrypts every user's credentials and every node's private
    key. If the panel is on the Russian entry node — which the topology allows — a key
    generated on that host would sit on the machine most likely to be seized, beside the
    data it opens, with nobody having decided that. So absence must stop the run.

    Asserted three ways, because a "helpful" future edit could break any one of them: the
    run fails, the message says it does not generate one and why, and the env file is
    unchanged afterwards.
    """
    path = env_file(tmp_path, HASHI_SECRET_KEY=None)
    before = path.read_text()
    project = f"{PROJECT}-nokey"

    result = run_bootstrap(path, project=project)

    assert result.returncode != 0, result.stdout
    combined = result.stdout + result.stderr
    assert "HASHI_SECRET_KEY" in combined
    assert "does NOT generate it" in combined
    # The reason, not just the refusal: an operator who is told "no" without "why" adds
    # the key wherever is easiest, which is this host.
    assert "seized" in combined

    assert path.read_text() == before, "the script wrote a key into the env file"
    assert container_ids(project) == [], "a refused run still started containers"


def test_a_missing_key_is_named_rather_than_defaulted(tmp_path) -> None:
    """Every other required key. A default here would be a fleet-wide constant."""
    path = env_file(tmp_path, POSTGRES_PASSWORD=None)
    project = f"{PROJECT}-nopass"

    result = run_bootstrap(path, project=project)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "POSTGRES_PASSWORD" in combined
    assert container_ids(project) == []


def test_it_never_prints_the_env_file(tmp_path) -> None:
    """A secret in a terminal scrollback is a secret in an SSH log.

    The env file this scenario writes contains a password nobody uses, so the assertion
    is about the script's habit rather than about this value.
    """
    path = env_file(tmp_path, HASHI_PUBLIC_HOST=None)
    result = run_bootstrap(path, project=f"{PROJECT}-quiet")

    combined = result.stdout + result.stderr
    assert "panel-bootstrap-not-real" not in combined, (
        "the script echoed a value out of the env file"
    )
    assert FAKE_SECRET_KEY not in combined


# --- the real thing -----------------------------------------------------------

@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """One real installation, torn down with its volumes afterwards.

    Module-scoped because building the image and initialising Postgres is the expensive
    part, and the two scenarios that need it are asking different questions about the
    same install — which is also exactly how idempotence is worth asserting: the second
    run happens against a stack that is genuinely already there.
    """
    directory = tmp_path_factory.mktemp("panel")
    path = env_file(directory)
    project = f"{PROJECT}-real"

    first = run_bootstrap(path, project=project)
    try:
        yield path, project, first
    finally:
        compose(project, "down", "-v")


def test_a_bare_host_becomes_a_working_panel(installed) -> None:
    """The whole point, and note WHAT is asserted: the script's own verdict.

    The script ends by asking the running control plane two real questions over HTTP —
    ``/healthz`` and a bogus token on the delivery route. So a zero exit code here means
    the panel answered, not that a container was created. ``echo ok`` is how an operator
    ends up believing a broken panel is up, and this is the assertion that would catch it.
    """
    _, project, first = installed

    assert first.returncode == 0, (
        f"the panel bootstrap failed:\n{first.stdout[-4000:]}\n{first.stderr[-4000:]}"
    )
    assert "the control plane answers on /healthz" in first.stdout
    assert "routes /sub/{token}" in first.stdout

    running = container_ids(project)
    assert len(running) >= 2, f"expected at least db and control, got {running}"

    # And nothing is published. The base compose file has no ports, and a panel host that
    # published its database because someone copied a laptop command is the failure the
    # split between the two compose files exists to prevent.
    published = compose(project, "ps", "--format", "{{.Publishers}}").stdout
    assert "0.0.0.0" not in published, f"the panel install published a port: {published}"


LOGIN_PROBE = """
import sys
import urllib.error
import urllib.parse
import urllib.request

# The password arrives on stdin, never on the command line: an argument is
# world-readable in /proc, which is the same reason `control.cli hash-password`
# prompts instead of taking one.
password = sys.stdin.read().strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *arguments, **keywords):
        return None


opener = urllib.request.build_opener(NoRedirect)
body = urllib.parse.urlencode({"username": "owner", "password": password}).encode()
try:
    with opener.open("http://127.0.0.1:8000/panel/login", data=body, timeout=10) as answer:
        print(answer.status)
except urllib.error.HTTPError as error:
    print(error.code)
"""


def test_the_operator_can_log_in_with_the_hash_they_pasted(installed) -> None:
    """M6.4's first "done when", and the one the owner would have found out the hard way.

    The env file this install was built from carries the line ``control.cli hash-password``
    printed, character for character, with a digest forced onto the shape compose eats
    (see ``operator_hash_line``). So this asks the only question that settles it: with that
    file, does the password still open the panel?

    Asked from INSIDE the compose network, because a real install publishes no ports —
    the same reason the script's own probe runs there. 303 is the redirect that follows a
    successful login; a rejected one is 401 with the login form again, which is exactly
    what a damaged hash produced on the live host, forever, with nothing to grep for.

    The other half — that the escaping is what saves it, rather than compose having
    stopped interpolating — is proved in ``tests/infra/test_operator_hash_survives_compose``
    without booting anything, because doing it here would cost a second install.
    """
    _, project, _ = installed

    answer = compose(
        project, "exec", "-T", "control", "python", "-c", LOGIN_PROBE,
        stdin=OPERATOR_PASSWORD,
    )

    assert answer.returncode == 0, answer.stderr[-2000:]
    status = answer.stdout.strip().splitlines()[-1]
    assert status == "303", (
        f"the operator could not log in to the panel they just installed (HTTP {status}). "
        "A 401 here means the hash in the env file is not the hash the control plane "
        "loaded — which is what docker compose does to an unescaped one."
    )


def test_running_it_again_changes_nothing(installed) -> None:
    """Idempotence, asserted on container identity rather than on the exit code.

    "It ran twice without erroring" is not the property. The property is that the second
    run did not recreate anything — because recreating the database container is a
    restart of the one service whose loss cannot be repaired by rebuilding a node, and an
    operator re-running a script after fixing an unrelated typo must not risk that.
    """
    path, project, _ = installed
    before = container_ids(project)
    assert before, "nothing was running, so this assertion would be vacuous"

    again = run_bootstrap(path, project=project)

    assert again.returncode == 0, f"{again.stdout[-2000:]}\n{again.stderr[-2000:]}"
    assert container_ids(project) == before, (
        "the second run replaced containers — including, potentially, the database"
    )


def test_a_control_plane_that_never_answers_is_reported_as_a_failure(tmp_path) -> None:
    """Property 3, from the other side: success must be earned.

    The key here is too short for the application to accept, so the control container
    refuses to boot — a real failure, of a real kind, rather than a stubbed one. The
    script must report it, and must NOT tear the stack down: the operator needs the logs,
    and a script that cleans up after a failure it could not explain destroys the
    evidence.
    """
    path = env_file(tmp_path, HASHI_SECRET_KEY="too-short")
    project = f"{PROJECT}-unhealthy"

    try:
        result = run_bootstrap(path, project=project, timeout_seconds=FAILING_HEALTH_TIMEOUT)

        assert result.returncode != 0, (
            f"a control plane that never answered was reported as success:\n{result.stdout}"
        )
        combined = result.stdout + result.stderr
        assert "did not answer" in combined
        # It points at the logs rather than printing them: a log line can carry a request
        # path, and a request path can carry a subscription token.
        assert "logs control" in combined

        assert container_ids(project), (
            "the failed run tore the stack down, so there is nothing left to diagnose"
        )
    finally:
        compose(project, "down", "-v")
