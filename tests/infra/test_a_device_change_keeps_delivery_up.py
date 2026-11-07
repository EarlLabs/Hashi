"""Changing the management tunnel never takes user delivery off the air — M33.4.

WHAT: two findings from the real-host walk of M33, each pinned by RUNNING the scripts:
      D1 — adding or removing a device has a command of its own, ``make mgmt-tunnel``,
      that runs the tunnel generator and no container command, and the runbook's device
      sections use it; D2 — ``panel-bootstrap.sh`` runs the generator's refusals BEFORE
      it touches the stack, so a refused run has published and unpublished nothing.
WHY:  on the real host, the runbook's "re-run the bootstrap" converged a serving stack to
      the base compose file, so Caddy lost 80/443 and every user's ``/sub/`` answered
      "connection refused" until ``make up-panel`` (D1). And a changed HASHI_MGMT_PORT
      was refused with "nothing was changed" AFTER the stack step had already taken the
      ports away (D2). Both are about order and about which command touches what, which
      reading the source asserts badly and running it asserts exactly.
HOW:  ``docker`` is a stub on PATH that writes each invocation to a log and answers as a
      healthy, publishing stack would — so "did this run touch the stack?" is a question
      about that log. No engine is needed. Skips loudly, like the generator's own tests,
      when the host has neither ``wg`` nor ``openssl``: a key cannot be made without one.
"""

import os
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PANEL = REPO / "scripts" / "panel-bootstrap.sh"
TUNNEL = REPO / "scripts" / "management-tunnel.sh"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"

pytestmark = pytest.mark.skipif(
    shutil.which("wg") is None and shutil.which("openssl") is None,
    reason="neither wg nor openssl is on this host, so no tunnel key can be generated — "
           "a skip rather than a pass because nothing was proved",
)

# A docker that records what it was asked and answers like a running stack that publishes
# 443: `compose config` is fine, `ps --format json` shows a published port (so the
# bootstrap's own "this run takes ports away" path is the live one), and `exec` — the
# health probe — succeeds.
STUB_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$*" in
  *" ps --format json"*) printf '[{"Service":"caddy","PublishedPort":443}]\\n' ;;
esac
exit 0
"""


def env_file(directory: pathlib.Path, port: str) -> pathlib.Path:
    """Every key the bootstrap requires, filled, and a tunnel block nobody's template has."""
    values = {
        "HASHI_SECRET_KEY": "test-only-not-a-real-key-" + "x" * 40,
        "HASHI_PUBLIC_HOST": "delivery.invalid",
        "HASHI_PRIVATE_HOST": "10.88.0.1",
        "HASHI_PRIVATE_PORT": "54143",
        "HASHI_OPERATOR_USERNAME": "owner",
        "HASHI_OPERATOR_PASSWORD_HASH": "scrypt$$1$$2$$3$$salt$$digest",
        "POSTGRES_USER": "hashi",
        "POSTGRES_PASSWORD": "test-only",
        "POSTGRES_DB": "hashi",
        "HASHI_MGMT_ADDRESS": "10.88.0.1/24",
        "HASHI_MGMT_PORT": port,
        "HASHI_MGMT_ENDPOINT": "panel.invalid",
        "HASHI_MGMT_MTU": "1420",
        "HASHI_MGMT_PEERS": "laptop=10.88.0.2/32,phone=10.88.0.3/32",
    }
    path = directory / "panel.env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    return path


@pytest.fixture
def host(tmp_path: pathlib.Path):
    """A host with a tunnel already generated on port 51821, and a stub docker."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(STUB_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    ufw_conf = tmp_path / "ufw.conf"
    ufw_conf.write_text("LOGLEVEL=off\n")
    mgmt_dir = tmp_path / "management"
    log = tmp_path / "docker.log"
    environment = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path),
        "HASHI_MGMT_DIR": str(mgmt_dir),
        "UFW_CONF": str(ufw_conf),
        "DOCKER_LOG": str(log),
        "PANEL_HEALTH_TIMEOUT": "6",
    }
    first = subprocess.run(
        [str(TUNNEL), "--env-file", str(env_file(tmp_path, "51821"))],
        capture_output=True, text=True, timeout=120, cwd=REPO,
        stdin=subprocess.DEVNULL, env=environment,
    )
    assert first.returncode == 0, first.stderr
    return tmp_path, environment, mgmt_dir / "awg-mgmt.conf", log


def bootstrap(directory: pathlib.Path, environment: dict, port: str):
    return subprocess.run(
        [str(PANEL), "--env-file", str(env_file(directory, port))],
        capture_output=True, text=True, timeout=180, cwd=REPO,
        stdin=subprocess.DEVNULL, env=environment,
    )


def stack_commands(log: pathlib.Path) -> list[str]:
    """Every docker invocation that changes what runs or what is published."""
    if not log.exists():
        return []
    return [
        line for line in log.read_text().splitlines()
        if re.search(r"\s(up|down|restart|stop|rm|start|create)(\s|$)", line)
    ]


def test_a_refused_tunnel_stops_the_bootstrap_before_the_stack_is_touched(host) -> None:
    """D2: "nothing was changed" is true when it is printed.

    Red before M33.4: the stub's log held `compose ... up -d --build` by the time the
    generator refused, because the generator ran only after the stack step.
    """
    directory, environment, conf, log = host
    before = conf.read_bytes()
    result = bootstrap(directory, environment, "51822")
    assert result.returncode != 0, "a changed HASHI_MGMT_PORT was not refused"
    assert "HASHI_MGMT_PORT" in result.stderr
    assert "before this run touched the stack" in result.stderr
    assert stack_commands(log) == [], (
        f"the bootstrap changed the stack before the tunnel refused: {stack_commands(log)}"
    )
    assert conf.read_bytes() == before, "a refused run changed the host's tunnel file"


def test_an_unchanged_tunnel_lets_the_bootstrap_run_to_the_end(host) -> None:
    """The positive control: the check above is not a check that refuses everything.

    With the env file still describing the tunnel on the host, the bootstrap reaches the
    stack step, verifies, and keeps the tunnel byte for byte — printing no key.
    """
    directory, environment, conf, log = host
    before = conf.read_bytes()
    result = bootstrap(directory, environment, "51821")
    assert result.returncode == 0, result.stderr
    assert any(line.endswith(" up -d") for line in stack_commands(log))
    assert conf.read_bytes() == before
    assert "PrivateKey" not in result.stdout


def test_the_device_command_touches_no_container(host) -> None:
    """D1: `make mgmt-tunnel` adds a device, and docker is never invoked.

    Run through make itself, so the target's recipe is what is under test and not a
    description of it.
    """
    directory, environment, conf, log = host
    env_path = env_file(directory, "51821")
    env_path.write_text(
        env_path.read_text().replace(
            "phone=10.88.0.3/32", "phone=10.88.0.3/32,tablet=10.88.0.4/32"
        )
    )
    result = subprocess.run(
        ["make", "--no-print-directory", "mgmt-tunnel", f"ENV_FILE={env_path}"],
        capture_output=True, text=True, timeout=120, cwd=REPO,
        stdin=subprocess.DEVNULL, env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert "device tablet added" in result.stdout
    assert "# peer: tablet" in conf.read_text()
    assert not log.exists() or log.read_text() == "", (
        f"`make mgmt-tunnel` invoked docker: {log.read_text()}"
    )


def test_the_runbook_changes_a_device_without_the_bootstrap() -> None:
    """D1, the document half: the sections an operator follows name `make mgmt-tunnel`.

    The fenced command blocks only — the prose explains why `make panel-bootstrap` is NOT
    the command, and matching that explanation would fail the test for giving the reason.
    """
    text = RUNBOOK.read_text()
    for heading, following in (
        ("#### Adding or removing a device", "#### Starting the tunnel over"),
        ("#### Starting the tunnel over", "### The way back in when the tunnel is unavailable"),
    ):
        section = text[text.index(heading):text.index(following)]
        commands = "\n".join(re.findall(r"```bash\n(.*?)```", section, re.S))
        assert "make mgmt-tunnel" in commands, f"{heading} does not run `make mgmt-tunnel`"
        assert "panel-bootstrap" not in commands, (
            f"{heading} still runs the bootstrap, which takes a serving host's ports away"
        )
