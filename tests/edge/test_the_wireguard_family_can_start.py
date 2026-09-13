"""What the WireGuard family's container is actually told to do — M2.1.

WHAT: the argv a WireGuard-family transport's container is started with, and the
      behaviour of the shell command line inside it.
WHY:  M2. ``command=("up", "{config}")`` on an image with no entrypoint made ``up`` the
      program, so both containers stopped at ``Created`` with exit 127. Fixing the
      program is only half of it, and the other half has no image in it at all:
      ``wg-quick up`` CONFIGURES and returns, so a container whose whole command is that
      exits 0 immediately and ``restart: unless-stopped`` restarts it forever. And the
      interface it creates lives in the node's own network namespace
      (``network_mode: host``), so it outlives a container that does not take it down.

      Those are properties of our shell line rather than of any image, which is why they
      can be — and here are — checked without docker: the script is run under the test
      host's ``/bin/sh`` against a stub tool, and asked the three questions a node would
      ask it. The one thing in the script that is NOT ours — the ``sleep`` its idle
      needs — the test supplies itself, at the strictest reading of the standard, so the
      answers do not depend on whose coreutils the developer has (M21.3).
HOW:  ``make test-edge``. Nothing here needs a network, a docker engine or a node.

Boundary: this proves the command's SHAPE and the script's behaviour. Whether the image
can exec the tool is ``test_every_data_plane_command_is_executable.py``; whether a real
tunnel comes up and carries traffic is a field observation on real hardware.
"""

import os
import pathlib
import shutil
import signal
import subprocess
import time

import pytest
import yaml

from edge.bootstrap import node_stack
from edge.bootstrap.ssh import CommandResult
from edge.health.probe import probe
from edge.registry import discover

# The transports whose data plane takes its interface name from the config's filename —
# the wg-quick family, named by the property rather than by protocol, so a third member
# added later is tested by arriving.
WG_FAMILY = sorted(
    name
    for name, meta in discover().items()
    if node_stack.DATA_PLANES[meta.config_format].interface_from_config_filename
)

A_CONFIG = "[Interface]\n"


def service_for(transport_name: str) -> dict:
    """One transport's service, read back out of the rendered compose file.

    Through YAML on purpose rather than from ``services_for``'s dict: the command is a
    shell line full of quotes, and the question this file exists to answer is what the
    NODE's compose parser sees, not what Python held before rendering.
    """
    rendered = node_stack.render_compose(
        transports=node_stack.services_for({transport_name: A_CONFIG})
    )
    return yaml.safe_load(rendered)["services"][transport_name]


def test_there_is_a_wireguard_family_to_check() -> None:
    """An empty family would make every scenario below vacuously green."""
    assert WG_FAMILY, "no transport declares a wg-quick-style data plane"


@pytest.mark.parametrize("transport_name", WG_FAMILY)
def test_the_command_survives_the_compose_file_intact(transport_name: str) -> None:
    """The shell line reaches the node exactly as written.

    It carries single quotes, double quotes and ``$`` — enough to make a hand-quoted
    YAML list either unparseable or, worse, parseable into something else.
    """
    command = service_for(transport_name)["command"]

    assert command == node_stack.services_for({transport_name: A_CONFIG})[0]["command"]


@pytest.mark.parametrize("transport_name", WG_FAMILY)
def test_the_config_it_is_pointed_at_is_the_one_we_write(transport_name: str) -> None:
    """The daemon loads the file ``place_config`` puts on the node, at the same path."""
    command = service_for(transport_name)["command"]

    assert command[-1] == node_stack.config_path_for(transport_name)


@pytest.mark.parametrize("transport_name", WG_FAMILY)
def test_the_interface_it_creates_is_named_after_the_transport(transport_name: str) -> None:
    """The filename IS the interface name, so the transport's name reaches the kernel.

    Worth an assertion rather than a comment because it is the coupling that makes the
    config's path part of the fix: move the config, rename the interface.
    """
    command = service_for(transport_name)["command"]
    interface = pathlib.PurePosixPath(command[-1]).stem

    assert interface == transport_name
    assert node_stack.INTERFACE_NAME.match(interface)


@pytest.mark.parametrize("transport_name", WG_FAMILY)
def test_it_gets_what_creating_a_tunnel_needs(transport_name: str) -> None:
    """NET_ADMIN and /dev/net/tun, and a container that reaches `Up` without them is the
    same failure one level in: running, and unable to create an interface."""
    service = service_for(transport_name)

    assert "NET_ADMIN" in service["cap_add"]
    assert any("/dev/net/tun" in str(device) for device in service["devices"])


# --- the script's own behaviour, run for real against a stub tool ------------------


@pytest.fixture
def stub_tool(tmp_path: pathlib.Path) -> pathlib.Path:
    """A stand-in for ``wg-quick`` that records what it was asked to do.

    It reports failure for ``down`` — which is what the real tool does when there is no
    interface to take down, and therefore the case the recovery line has to tolerate.
    """
    tool = tmp_path / "stub-quick"
    tool.write_text(
        "#!/bin/sh\n"
        f'echo "$1 $2" >> {tmp_path / "calls"}\n'
        '[ "$1" = down ] && exit 1\n'
        "exit 0\n"
    )
    tool.chmod(0o755)
    return tool


@pytest.fixture
def posix_sleep(tmp_path: pathlib.Path) -> pathlib.Path:
    """A directory whose ``sleep`` accepts only what the standard promises every host.

    The supervisor idles in ``sleep``, and which operands a ``sleep`` takes is a property
    of the HOST rather than of our script: GNU coreutils accepts ``infinity``, fractions
    and suffixes, and says so itself — "portable POSIX scripts must give ``sleep`` a
    single non-negative integer argument without a suffix". BSD's takes the integer and
    nothing else. Running these scenarios under whichever one the developer happens to
    have is how ``sleep infinity`` sat in the shipped script until it turned the owner's
    ``make verify`` red on macOS while staying green in CI (M21.3).

    So the test opens the thing it depends on. This shim is the strictest reading — one
    operand, decimal digits only — which makes the scenarios below hold for the same
    reason on every host, and makes a non-portable idle red everywhere rather than red
    only on the machine that cannot afford to discover it.

    Refusals are recorded so a failure can name the operand instead of leaving the reader
    with a process that is merely gone.
    """
    real_sleep = shutil.which("sleep")
    assert real_sleep, "no sleep on PATH, so the supervisor's idle cannot be exercised"

    binaries = tmp_path / "posix-bin"
    binaries.mkdir()
    shim = binaries / "sleep"
    shim.write_text(
        "#!/bin/sh\n"
        # One argument, and every character of it a digit: anything else falls through
        # to the refusal below. `1:` on its own catches an empty operand.
        'case "$#:$1" in\n'
        "  1:*[!0-9]*|1:) ;;\n"
        f'  1:*) exec {real_sleep} "$1" ;;\n'
        "esac\n"
        f'echo "sleep: invalid time interval $*" >> {tmp_path / "refused"}\n'
        'echo "sleep: invalid time interval $*" >&2\n'
        "exit 1\n"
    )
    shim.chmod(0o755)
    return binaries


def refused_sleep(tmp_path: pathlib.Path) -> str:
    """What ``posix_sleep`` turned down, if anything — for appending to a failure.

    The symptom of a non-portable idle is only that the process is no longer there, which
    reads like any other crash. This puts the cause in front of the reader who is looking
    at a red gate on a host the author never used.
    """
    refused = tmp_path / "refused"
    if not refused.exists():
        return ""
    return (
        " — and the idle asked for a sleep operand POSIX does not promise, which a BSD "
        f"sleep refuses: {refused.read_text().strip()}"
    )


def run_supervisor(
    stub_tool: pathlib.Path, config: str, posix_sleep: pathlib.Path
) -> subprocess.Popen:
    """Start the real command line under the host's shell, with the stub as its tool.

    ``PATH`` leads with ``posix_sleep``, so the idle at the end of the script is held to
    the standard rather than to whatever this host's own ``sleep`` is willing to allow.
    """
    return subprocess.Popen(
        ["/bin/sh", "-c", node_stack._WG_QUICK_SUPERVISOR, str(stub_tool), config],
        start_new_session=True,
        env={**os.environ, "PATH": f"{posix_sleep}{os.pathsep}{os.environ['PATH']}"},
    )


def test_the_container_stays_up_after_the_tunnel_is_configured(
    stub_tool, posix_sleep, tmp_path
) -> None:
    """``wg-quick up`` returns; the container must not.

    A command that exits when the tool returns turns ``restart: unless-stopped`` into a
    restart loop — a data plane that is never ``Up`` for two seconds together, which
    reads on the node as "it starts and something kills it".
    """
    process = run_supervisor(stub_tool, str(tmp_path / "amneziawg.conf"), posix_sleep)
    try:
        time.sleep(1)

        assert process.poll() is None, (
            f"the command exited (status {process.returncode}) once the tool returned, "
            f"so the container would restart forever{refused_sleep(tmp_path)}"
        )
        assert "up" in (tmp_path / "calls").read_text()
    finally:
        process.kill()
        process.wait(timeout=10)


def test_stopping_the_container_takes_the_tunnel_down(stub_tool, posix_sleep, tmp_path) -> None:
    """SIGTERM — what ``docker stop`` sends — tears the interface down and exits 0.

    The interface is in the NODE's network namespace, so one that is not taken down
    survives the container: a rotation then leaves a configured tunnel on a node that is
    no longer serving it, and the replacement container cannot create its own.
    """
    process = run_supervisor(stub_tool, str(tmp_path / "amneziawg.conf"), posix_sleep)
    time.sleep(1)

    process.send_signal(signal.SIGTERM)
    status = process.wait(timeout=10)

    assert status == 0, (
        "the container would be reported as having crashed on a normal stop"
        f"{refused_sleep(tmp_path)}"
    )
    calls = (tmp_path / "calls").read_text().split("\n")
    assert calls[-2].startswith("down"), f"the tunnel was not taken down on stop: {calls}"


def test_a_tunnel_left_behind_by_an_unclean_stop_is_recovered(
    stub_tool, posix_sleep, tmp_path
) -> None:
    """The tunnel is taken down BEFORE it is brought up, and a failing down is tolerated.

    M1 is what makes this necessary: a changed config now recreates the container, and a
    stop that skipped the trap — SIGKILL, an OOM kill, a node reboot mid-write — leaves
    the old interface in the host's namespace. Without this line the replacement dies
    with ``wg-quick: `amneziawg' already exists`` and crash-loops, which is measurably
    what happens: verified against the real image before this test was written.
    """
    process = run_supervisor(stub_tool, str(tmp_path / "amneziawg.conf"), posix_sleep)
    try:
        time.sleep(1)
        calls = [line for line in (tmp_path / "calls").read_text().split("\n") if line]

        # The stub exits 1 on `down`, as the real tool does when there is nothing to take
        # down — and the sequence still reaches `up`.
        assert calls[0].startswith("down")
        assert calls[1].startswith("up")
    finally:
        process.kill()
        process.wait(timeout=10)


def test_the_shell_line_names_no_protocol(stub_tool) -> None:
    """One script for the whole family: the tool arrives as an argument, never inline.

    Core invariants §1 — no transport's name in shared code. The script is shared by
    every member of the family and would be shared by a third; if a protocol's tool were
    written into it, adding one would mean editing it.
    """
    script = node_stack._WG_QUICK_SUPERVISOR

    for tool in ("wg-quick", "awg-quick", "wireguard", "amnezia"):
        assert tool not in script


def test_the_script_needs_no_shell_this_project_does_not_have() -> None:
    """It is POSIX: both images' ``/bin/sh`` is busybox, and this host's is not.

    A guard against the obvious future edit — reaching for a bashism because the tool
    itself is a bash script. The tool having bash does not mean PID 1 does.

    It is a check on SYNTAX and can see nothing else: ``sleep infinity`` parses perfectly
    under every shell there is, and was wrong anyway. That half is ``posix_sleep``'s.
    """
    check = subprocess.run(
        ["/bin/sh", "-n", "-c", node_stack._WG_QUICK_SUPERVISOR],
        capture_output=True,
        text=True,
        env={**os.environ, "POSIXLY_CORRECT": "1"},
    )

    assert check.returncode == 0, check.stderr


# --- and what the node then reports about it --------------------------------------


class _FakeNode:
    """A node running exactly what we pushed: right container, right file, right path."""

    learned_host_key = None

    def __init__(self, containers: dict[str, str], files: dict[str, str]) -> None:
        self.containers = containers
        self.files = files

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        if "docker inspect" in command:
            lines = [f"{service}|{digest}|true" for service, digest in self.containers.items()]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")
        return CommandResult(exit_status=0, stdout="", stderr="")

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)


@pytest.mark.parametrize("transport_name", WG_FAMILY)
async def test_a_healthy_node_is_not_reported_as_drifted(transport_name: str) -> None:
    """Drift is read from the path the transport DECLARED, not from a default.

    Carried over from M1 (docs/tracker/M1/carry-over.md) and fixed here because M2 is
    what makes it bite: ``probe`` resolved the config with ``config_path``, whose
    default format is Xray JSON, so it looked for every transport's config at a
    ``.json`` path. Harmless while the only live transport was an Xray one — and the
    moment this family works, every one of its transports reports as permanently
    drifted on a node where nothing is wrong. An operator who is told the node was
    edited goes looking for an intruder.
    """
    node = _FakeNode(
        containers={transport_name: node_stack.digest_of(A_CONFIG)},
        files={node_stack.config_path_for(transport_name): A_CONFIG},
    )

    health = await probe(node, expected={transport_name: A_CONFIG})

    assert health.drifted == [], (
        "a node running exactly what we pushed is reported as drifted, so the config "
        "was looked for somewhere it is never written"
    )
    assert health.healthy
