"""The operator's hash, carried from the command that prints it to the container — M6.4.

WHAT: generates a hash the way an operator does, pastes the printed line into an env file
      verbatim, and asks ``docker compose`` what value the control service would actually
      receive.
WHY:  this seam broke on a live host and cost the owner their panel. ``docker compose
      --env-file`` interpolates the values it reads, and a scrypt hash is
      ``scrypt$n$r$p$salt$digest`` — five dollars, four of them in front of something that
      reads as a variable name. The observed result was an 86-character hash arriving as
      42, with compose exiting 0, the health check passing, and the login answering 401
      forever. Nothing in the repository was in a position to notice.
HOW:  real ``docker compose config``, which resolves interpolation and needs no daemon —
      so this runs wherever the CLI exists, including CI, which is where it has to run:
      the acceptance tier does not run on every push.

      It lives in ``tests/infra`` because the seam is compose's, and it imports from
      ``control`` because the value is produced there. That import is the seam, not a
      layering slip: the whole defect was that the two zones disagreed about the format
      of one string and neither test suite could see both ends of it.

NOT a coin flip, and that is a deliberate property of this file. A base64 digest starts
with a letter about five times in six, and only a field starting with a letter or an
underscore is eaten — so a scenario that hashed one fixed password would pass or fail at
random. ``a_hash_compose_would_eat`` forces the dangerous case every run.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from control.app.crypto import hash_password, verify_password
from control.cli import escaped_for_env_file

REPO = pathlib.Path(__file__).resolve().parents[2]
BASE = REPO / "deploy" / "docker-compose.yml"

# Never the owner's password and never a plausible one: this string only ever exists in
# this file and in a hash of itself in a temporary directory.
PASSWORD = "an-operator-password-that-is-only-a-fixture"

# Everything the base compose file demands before it will render at all. Only the hash is
# under test; the rest are fake values that exist so `config` gets that far.
OTHER_KEYS = {
    "HASHI_SECRET_KEY": "infra-test-not-a-real-key-000000000000000000000000",
    "HASHI_PUBLIC_HOST": "operator-hash.invalid",
    # M7's private site block; the caddy service requires both since the split.
    "HASHI_PRIVATE_HOST": "operator-hash-console.invalid",
    "HASHI_PRIVATE_PORT": "54143",
    "HASHI_OPERATOR_USERNAME": "owner",
    "POSTGRES_USER": "hashi",
    "POSTGRES_PASSWORD": "operator-hash-not-real",
    "POSTGRES_DB": "hashi",
    "CADDY_ACME_EMAIL": "nobody@operator-hash.invalid",
}


@pytest.fixture(scope="module", autouse=True)
def compose_available() -> None:
    if shutil.which("docker") is None:
        pytest.skip("no docker CLI, so compose interpolation cannot be asked about")


def a_hash_compose_would_eat() -> str:
    """A real hash whose LAST field begins with a letter.

    That is the dangerous shape and the reason this file exists: ``$digest`` is then a
    valid variable name, compose replaces it with nothing, and the value that reaches the
    container has no digest in it at all. The salt is left to chance — one forced field is
    enough to make the case certain, and forcing both would be a hash no operator's
    generator is more likely to produce than any other.
    """
    for _ in range(50):
        candidate = hash_password(PASSWORD)
        if candidate.rsplit("$", 1)[-1][:1].isalpha():
            return candidate
    raise AssertionError(
        "50 hashes in a row had a digest starting with a digit, which is about a one in "
        "ten-million event — hash_password has probably stopped producing base64"
    )


def env_file(directory: pathlib.Path, hash_value: str) -> pathlib.Path:
    path = directory / "operator-hash.env"
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in OTHER_KEYS.items())
        + f"HASHI_OPERATOR_PASSWORD_HASH={hash_value}\n"
    )
    path.chmod(0o600)
    return path


def as_the_container_would_get_it(path: pathlib.Path) -> tuple[str, str]:
    """The hash the control service would actually be started with, and compose's warnings.

    ``config`` re-escapes every ``$`` on the way out, because its output is itself a
    compose file that has to survive being read again. So the value is un-doubled here —
    that is a documented property of the OUTPUT format, not a second chance for the value
    to be repaired: interpolation has already happened by then, and a field compose
    swallowed is gone before this line runs.
    """
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(path), "-f", str(BASE),
         "config", "--format", "json"],
        capture_output=True, text=True, timeout=120, cwd=REPO,
        # No daemon is contacted by `config`, and pointing at a socket that does not
        # exist keeps it that way — a test that quietly needed the owner's engine would
        # skip on the machine where it matters most.
        env={**os.environ, "DOCKER_HOST": "unix:///nonexistent-on-purpose.sock"},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    rendered = json.loads(result.stdout)["services"]["control"]["environment"]
    return rendered["HASHI_OPERATOR_PASSWORD_HASH"].replace("$$", "$"), result.stderr


def test_the_line_the_command_prints_reaches_the_container_intact(tmp_path) -> None:
    """The whole point: paste it verbatim, and the operator can log in.

    Asserted with ``verify_password`` rather than by comparing strings, because equality
    with the value we started from is a weaker claim than the one that matters — that what
    arrives still checks the password the owner chose.
    """
    original = a_hash_compose_would_eat()
    path = env_file(tmp_path, escaped_for_env_file(original))

    arrived, warnings = as_the_container_would_get_it(path)

    assert arrived == original, (
        "the hash was changed on its way through docker compose, so the operator's "
        "password no longer matches what the control plane holds"
    )
    assert verify_password(PASSWORD, arrived), (
        "the value the container would receive does not verify the operator's password"
    )
    assert "is not set" not in warnings, (
        f"compose read part of the hash as a variable name: {warnings[-500:]}"
    )


def test_the_same_hash_undoubled_is_destroyed(tmp_path) -> None:
    """Proof that the doubling above is load-bearing rather than decorative.

    Without this the first test would still pass on a day when compose stopped
    interpolating, and nobody would learn that the escaping had become unnecessary — or,
    far worse, that it had become wrong. This is the failure exactly as it was seen on the
    live host, reproduced on demand.
    """
    original = a_hash_compose_would_eat()
    path = env_file(tmp_path, original)

    arrived, warnings = as_the_container_would_get_it(path)

    assert arrived != original, (
        "an undoubled hash now survives compose — if that is really true, the escaping in "
        "control/cli.py and the refusal in scripts/panel-bootstrap.sh are both obsolete "
        "and should be removed deliberately rather than left as folklore"
    )
    assert not verify_password(PASSWORD, arrived)
    assert "is not set" in warnings, (
        "compose did not even warn, which is the whole reason this is worth a test"
    )


def test_the_command_itself_prints_the_escaped_form(tmp_path) -> None:
    """Run the real command, the way the runbook tells an operator to.

    ``start_new_session`` detaches it from the terminal, so ``getpass`` cannot open
    ``/dev/tty`` and falls back to stdin — without it this test hangs on a developer's
    machine and passes in CI, which is the worst of both.
    """
    result = subprocess.run(
        [sys.executable, "-m", "control.cli", "hash-password"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
        capture_output=True, text=True, timeout=120, cwd=REPO, start_new_session=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]

    line = next(
        line for line in result.stdout.splitlines()
        if line.startswith("HASHI_OPERATOR_PASSWORD_HASH=")
    )
    printed = line.split("=", 1)[1]
    assert "$" in printed and printed.replace("$$", "").count("$") == 0, (
        "the command prints a hash with a lone $ in it, which scripts/panel-bootstrap.sh "
        "refuses and docker compose would eat"
    )
    # And it is still a hash of the password once compose has expanded it.
    assert verify_password(PASSWORD, printed.replace("$$", "$"))
