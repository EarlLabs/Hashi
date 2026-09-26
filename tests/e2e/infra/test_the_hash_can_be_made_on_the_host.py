"""The one value in `.env` that could not be produced on the machine that needs it.

WHAT: runs ``scripts/hash-password.sh`` for real — it builds the control image and runs
      ``python -m control.cli hash-password`` inside it — and follows the line it prints
      all the way to the value the control container would be started with.
WHY:  M28.10, finding 1. The restore runbook asks for four values and says *"Nothing else
      is needed"*. On the bare host the walk used, one of them could not be made:
      ``python3 -m control.cli hash-password`` is a traceback on the system's Python 3.10,
      and ``make setup`` is ``python3.14: No such file or directory``. So a rebuild after
      a seizure required a **second working computer**, in the middle of the emergency.

      The static half of this is in ``tests/infra/test_a_bare_host_can_finish_the_restore.py``
      and can only say the script names the right things. What cannot be read off the text
      is the part that matters: that the hash this produces is one the control plane
      accepts, after surviving being written into an env file and interpolated by compose
      — which is where this project has already lost a hash once (M6.5: a lone ``$``
      before a salt, a silently emptied field, and an owner locked out of their own panel).
HOW:  needs a docker engine; it builds an image and runs a container, and it needs no
      stack. Roughly a minute the first time on a cold cache, seconds afterwards, because
      the layers are the ones the stand has already built.
"""

import json
import os
import pathlib
import shutil
import subprocess

import pytest

from control.app.crypto import is_well_formed_hash, verify_password

REPO = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "hash-password.sh"
BASE = REPO / "deploy" / "docker-compose.yml"

# Twelve characters is the command's own floor, and a password shorter than that is
# refused rather than hashed — see control/cli.py.
PASSWORD = "a-password-the-owner-chose"

# Everything else the base compose file requires, so `config` gets as far as rendering the
# one value under test. None of it is a real secret and none of it is used for anything.
OTHER_KEYS = {
    "HASHI_SECRET_KEY": "not-a-real-key-for-an-interpolation-test",
    "HASHI_PUBLIC_HOST": "hash.invalid",
    "HASHI_PRIVATE_HOST": "console.invalid",
    "HASHI_PRIVATE_PORT": "54143",
    "HASHI_OPERATOR_USERNAME": "owner",
    "POSTGRES_USER": "hashi",
    "POSTGRES_PASSWORD": "not-a-real-password",
    "POSTGRES_DB": "hashi",
    "CADDY_ACME_EMAIL": "owner@hash.invalid",
}


@pytest.fixture(scope="module")
def printed() -> subprocess.CompletedProcess:
    """The command, run the way a bare host runs it: no terminal, password on stdin.

    A real operator gets a hidden prompt because they have a tty. Here there is not one,
    and the command still works — Python says out loud that it cannot control the echo,
    which is honest and is what makes this testable at all without a pty.
    """
    if shutil.which("docker") is None:
        pytest.skip("this is a skip, not a pass: no docker CLI, so nothing can build the image")
    engine = subprocess.run(["docker", "info"], capture_output=True, timeout=120)
    if engine.returncode != 0:
        pytest.skip("this is a skip, not a pass: no docker engine answering")

    return subprocess.run(
        [str(SCRIPT)],
        input=f"{PASSWORD}\n{PASSWORD}\n",
        capture_output=True, text=True, timeout=1800, cwd=REPO,
    )


def the_line(printed: subprocess.CompletedProcess) -> str:
    lines = [
        line for line in printed.stdout.splitlines()
        if line.startswith("HASHI_OPERATOR_PASSWORD_HASH=")
    ]
    assert len(lines) == 1, (
        f"stdout does not carry exactly one line to paste: {printed.stdout[-2000:]}"
    )
    return lines[0]


def test_the_hash_is_produced_on_a_host_with_nothing_but_a_container_runtime(
    printed,
) -> None:
    """The machine running this needs no venv, no Python 3.14 and no dependencies.

    It is proven here only in the weak sense that the build and the run are the whole of
    what happened — the host under test does have a venv, because pytest is running in it.
    What is really asserted is that the command's own path to the hash goes through the
    image and not through this machine's interpreter.
    """
    assert printed.returncode == 0, f"{printed.stdout[-2000:]}\n{printed.stderr[-4000:]}"
    assert "control image" in printed.stderr, (
        "the run did not build the image, so it produced the hash some other way"
    )
    assert is_well_formed_hash(the_line(printed).split("=", 1)[1].replace("$$", "$")), (
        "the line is not a hash the control plane would accept at boot"
    )


def test_the_build_and_the_prompts_stay_off_stdout(printed) -> None:
    """Named for what it checks, which is not "stdout is only the line".

    It is not: ``control/cli.py`` prints the line under a sentence naming where it goes
    and over a paragraph about the doubled ``$$``, and that block is out of this step's
    fence and worth having. What this asserts is the property the redirection actually
    buys — that **nothing this script emitted** is mixed into it. An operator at 3am
    copies what they see, and a build log interleaved with the value is how half a hash
    ends up in an env file.

    The first name this test had claimed the stronger property and checked this one, which
    is the defect this repository has recorded more often than any other.
    """
    stdout = printed.stdout
    kept = [line for line in stdout.splitlines() if line.strip()]

    # Everything on stdout comes from the CLI's block: the line, and prose about it.
    assert kept[0].startswith("Put this in .env"), stdout[:500]
    assert sum(line.startswith("HASHI_OPERATOR_PASSWORD_HASH=") for line in kept) == 1
    assert kept[-1].endswith("would arrive empty."), stdout[-500:]

    # And nothing the SCRIPT emitted is anywhere in it. Each of these is a real line from
    # one of the three noisy sources: this script's own progress, docker's build, and
    # getpass's prompt — checked as text rather than by a marker, so a change in any of
    # the three that starts leaking is caught here rather than on somebody's terminal.
    for noise in (
        "building the control image",   # this script's own progress lines
        "DONE",                         # buildkit's step output
        "CACHED",
        "sha256:",
        "naming to docker.io",
        "operator password:",           # getpass, which writes its prompt to stderr
        "again:",
        "Warning: Password input may be echoed.",
    ):
        assert noise not in stdout, f"{noise!r} reached stdout, where the value to paste is"

    # The other half of the same claim, so none of the above can pass by nothing having
    # been printed at all: all three sources really did emit, on the other stream.
    assert "building the control image" in printed.stderr
    assert "operator password:" in printed.stderr
    assert "DONE" in printed.stderr or "CACHED" in printed.stderr, (
        "docker printed no build output anywhere, so the sweep above proves nothing"
    )


def test_the_line_survives_the_env_file_and_reaches_the_container_intact(
    printed, tmp_path
) -> None:
    """The end of the walk: paste it verbatim into `.env`, and the panel takes the password.

    This is the step that has gone wrong before. A scrypt hash is
    ``scrypt$N$r$p$salt$digest``, and ``docker compose --env-file`` interpolates what it
    reads — so a lone ``$`` starts a variable reference and the field after it arrives
    empty, which happens or does not depending on the salt's first byte. The command
    prints the value already doubled, and this asserts the doubling is right by checking
    what ARRIVES rather than by comparing strings.
    """
    path = tmp_path / "restored-host.env"
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in OTHER_KEYS.items())
        + the_line(printed)
        + "\n"
    )
    path.chmod(0o600)

    rendered = subprocess.run(
        ["docker", "compose", "--env-file", str(path), "-f", str(BASE),
         "config", "--format", "json"],
        capture_output=True, text=True, timeout=120, cwd=REPO,
        # `config` contacts no daemon, and pointing DOCKER_HOST at a socket that does not
        # exist keeps it honest — the same trick tests/infra uses for this question.
        env={**os.environ, "DOCKER_HOST": "unix:///nonexistent-on-purpose.sock"},
    )
    assert rendered.returncode == 0, rendered.stderr[-2000:]

    arrived = json.loads(rendered.stdout)["services"]["control"]["environment"][
        "HASHI_OPERATOR_PASSWORD_HASH"
    ].replace("$$", "$")
    assert verify_password(PASSWORD, arrived), (
        "the hash produced on the host does not verify the password it was made from once "
        "it has been through an env file — which is an operator locked out of the panel "
        "they have just restored, with a correct-looking hash sitting in .env"
    )
