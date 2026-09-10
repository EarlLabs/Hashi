"""Does the argv survive Docker Compose's interpolation pass? — asked of real Compose.

WHAT: renders a node's compose file, hands it to a real ``docker compose``, and asserts
      the argv the ENGINE ends up holding is byte-identical to what
      ``node_stack.services_for`` produced.
WHY:  the WireGuard family's command is a shell command line, and it is full of ``$``:
      ``"$0"``, ``"$1"``, ``wait $!``. Compose interpolates ``$`` in every value of a
      compose file before the engine ever sees it. Those three happen to be forms
      Compose leaves alone — but "happen to be" is the whole problem, and this
      repository has already paid for that class of assumption once: M6.4, where
      ``--env-file`` interpolation ate the ``$``-separated fields of an scrypt hash and
      an 86-character value reached the container as 42. Silently. The stack was
      healthy, the password was correct, and it was rejected on a real host.

      A wrong answer here has the same shape: the container starts, ``$0`` is empty, the
      shell runs ``"" down ""``, and the failure reads as a broken config rather than as
      a mangled command. So the check does not belong in a comment saying it was
      verified by hand — the next person to edit that line will not repeat the check,
      and Compose's rules are not ours to freeze.
HOW:  ``docker compose create`` and then ``docker inspect``, rather than
      ``docker compose config``. Two reasons, and the first is decisive: ``config``
      RE-ESCAPES ``$`` as ``$$`` on output, so comparing its text would need an
      un-escaping step of ours — a transformation in the very place the test exists to
      prove nothing transforms anything. ``.Config.Cmd`` on a created container is the
      argv the engine holds, with nothing between it and ``execve``.

      ``create`` and not ``up``: it materialises the container, and therefore the argv,
      without running a process, touching the host's network namespace or creating the
      bind-mount source (checked — ``/opt/hashi`` is not created by this).

Boundary: needs a docker engine, ``/dev/net/tun``, and the pinned images (it pulls them).
It proves the command REACHES the engine unaltered. It proves nothing about whether the
command then works — that is
``tests/edge/test_every_data_plane_command_is_executable.py`` for the binaries, and a
field observation on a real node for the tunnel.
"""

import copy
import json
import pathlib
import subprocess
import uuid

import pytest

from edge.bootstrap import node_stack
from edge.registry import discover

# Every transport, not only the family with the shell line: the Xray data plane's plain
# argv is the control that shows a difference would be the command's and not Compose's.
CONFIGS = {name: "a rendered config" for name in sorted(discover())}

# What the label-reading idiom in ``node_stack.loaded_digests`` uses, for the same
# reason: a container maps back to its service by Compose's own label, never by parsing
# a container name.
INSPECT_FORMAT = (
    f'{{{{index .Config.Labels "{node_stack.COMPOSE_SERVICE_LABEL}"}}}}'
    "|{{json .Config.Cmd}}"
)

# A variable name nothing sets, spliced into the command for the red half below. Compose
# substitutes an unset variable with the empty string — which is exactly how M6.4 lost
# half a password without an error anywhere.
CANARY = "$HASHI_INTERPOLATION_CANARY"

# The flag that makes the next argument a script rather than a filename — the element
# with the ``$`` in it. Same constant, same reasoning, as the offline check in
# ``tests/edge/test_every_data_plane_command_is_executable.py``.
INTERPRETED = "-c"


def _run(arguments: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)


def argv_from_a_real_engine(compose: str, tmp_path: pathlib.Path) -> dict[str, list[str]]:
    """Create the stack's containers from this compose file and read back their argv.

    Returns service name → the argv the engine holds. The project name is unique per
    call so this can never address, or tear down, a stack somebody else is running.
    """
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(compose)
    project = f"hashi-argv-{uuid.uuid4().hex[:12]}"
    base = ["docker", "compose", "-f", str(compose_file), "-p", project]

    try:
        created = _run([*base, "create"])
        assert created.returncode == 0, (
            "the rendered compose file was refused by a real docker compose:\n"
            f"{(created.stderr or created.stdout).strip()[:2000]}"
        )

        listed = _run([*base, "ps", "-aq"])
        assert listed.returncode == 0, listed.stderr
        containers = listed.stdout.split()
        assert containers, "docker compose created nothing, so there is no argv to read"

        inspected = _run(["docker", "inspect", "--format", INSPECT_FORMAT, *containers])
        assert inspected.returncode == 0, inspected.stderr
    finally:
        _run([*base, "down", "--remove-orphans"])

    argv = {}
    for line in inspected.stdout.splitlines():
        service, _, command = line.strip().partition("|")
        argv[service] = json.loads(command)
    return argv


@pytest.fixture(scope="module")
def engine_argv(tmp_path_factory) -> dict[str, list[str]]:
    """The argv a real engine holds for a real rendered node compose file."""
    compose = node_stack.render_compose(transports=node_stack.services_for(CONFIGS))
    return argv_from_a_real_engine(compose, tmp_path_factory.mktemp("rendered"))


@pytest.mark.parametrize("transport_name", sorted(CONFIGS))
def test_the_engine_holds_exactly_the_argv_we_rendered(
    transport_name: str, engine_argv: dict[str, list[str]]
) -> None:
    """Byte-identical, element for element.

    Not "starts with the right binary" and not "contains the config path": the failure
    this guards against changes the MIDDLE of a string and leaves both ends intact.
    """
    wanted = next(
        service["command"]
        for service in node_stack.services_for(CONFIGS)
        if service["name"] == transport_name
    )

    assert engine_argv[transport_name] == wanted, (
        f"the argv the engine holds for {transport_name!r} is not the one we rendered. "
        "Docker Compose interpolates every value in a compose file, so a `$` in the "
        "command can be substituted away before the engine sees it — the container then "
        "starts and runs something else."
    )


def test_a_dollar_sign_compose_would_eat_really_is_eaten(tmp_path) -> None:
    """The red half, and it is a check on the CHECK rather than on the product.

    The scenario above is only worth something if this round-trip can change a command
    at all. So: splice a variable nothing sets into the same element of the same command
    — the shell line — and confirm the engine does NOT get it back. If this ever fails,
    Compose has stopped interpolating and the assertion above has quietly become an
    identity — which is worth knowing, and is why this fails loudly rather than being
    written as a comment.
    """
    family = [
        service
        for service in node_stack.services_for(CONFIGS)
        if INTERPRETED in service["command"]
    ]
    assert family, "no data plane runs a shell command line, so there is no `$` to lose"

    poisoned = copy.deepcopy(family[0])
    script = poisoned["command"].index(INTERPRETED) + 1
    # Appended rather than spliced into a clause the script happens to contain. The
    # question is whether a ``$`` ANYWHERE in this element survives, so naming a word of
    # the script buys nothing and costs everything: this line used to poison ``sleep
    # infinity``, and M21.3's reword of that idle would have turned ``replace`` into a
    # no-op, leaving the assertion below looking for a canary nothing had ever spliced in.
    # A green red-half is worse than no red half. ``:`` is the shell's own no-op.
    poisoned["command"][script] += f"; : {CANARY}"

    compose = node_stack.render_compose(transports=[poisoned])
    engine = argv_from_a_real_engine(compose, tmp_path)[poisoned["name"]]

    assert CANARY not in engine[script], (
        "an unset variable spliced into the command survived the round trip, so "
        "Docker Compose is no longer interpolating and the scenario above no longer "
        "proves that our `$0`/`$1` survive it either — it proves nothing at all"
    )
