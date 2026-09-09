"""Does the command we declare actually run the program it names? — M5.1, asked of Docker.

WHAT: for every transport, starts a real container from the real image with the real
      rendered argv, and asks the engine three things about what happened: which binary
      it resolved and executed, that the container did not die because that binary was
      missing, and that the program then read the argument we passed it.
WHY:  M2 shipped ``command=("up", "{config}")`` against images that declare no
      entrypoint, so ``up`` was the whole program and both containers died at
      ``Created`` with exit 127. That failure is now checked in three places and none of
      them starts anything:

        * ``tests/edge/test_every_data_plane_command_is_executable.py`` reads recorded
          facts and asks whether argv[0] resolves;
        * ``tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py`` keeps
          those facts true of the images, by exec-ing each binary ALONE;
        * ``tests/e2e/edge/test_compose_hands_the_engine_the_command_we_wrote.py``
          proves the argv survives Compose's interpolation, by CREATING a container and
          never starting it.

      Between them they cover M5.1's letter — see M2's step notes, which say so — and
      they leave one gap, which they also name: *"``awg-quick`` exec-ing is not
      ``awg-quick`` accepting that config"*. Nothing has ever handed a real engine the
      WHOLE rendered argv and watched what came out. This does.
HOW:  the config is deliberately ABSENT, and that is what makes the scenario cheap and
      the assertion sharp. Every data plane here answers a missing config by naming the
      path it was given, so "the program read our argument" is observable without a
      valid config, without a network and in about two seconds. Whether a config the
      daemon ACCEPTS then keeps the container alive is the next scenario
      (``test_a_data_plane_container_reaches_up_and_stays_up.py``).

Boundary: needs a docker engine and the pinned images (it pulls them). It proves the
argv the engine resolves is the binary the image's real entrypoint decides, and that our
arguments reach that binary. It proves nothing about the tunnel, the handshake or one
byte of traffic — those are M5.4 and a field observation.
"""

import json
import subprocess
import uuid

import pytest

from edge.bootstrap import node_stack
from edge.registry import discover

INSTALLED = sorted(discover())


def run(arguments: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """One docker command, captured.

    Defined here rather than imported from ``conftest``: pytest runs with
    ``--import-mode=importlib``, under which importing across test modules is not
    reliable — the same reason ``tests/edge/conftest.py`` exposes its helpers as
    fixtures. Every sibling scenario in this directory carries its own.
    """
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)

# What the OCI runtime reports for a command it could not exec at all. Docker's own
# documented convention, and the exact pair M2's bug produced.
NOT_FOUND = 127
NOT_EXECUTABLE = 126

# A name no image ships, for the check on the check below.
NOT_A_PROGRAM = "hashi-not-a-program"


def image_entrypoint(image: str) -> tuple[list[str], list[str]]:
    """The image's OWN entrypoint and command, read from the engine, not from a file.

    The golden ``image-facts.json`` says the same thing and is kept honest by its own
    scenario. This one asks the engine directly, because the question here is what the
    engine will really do with our command — and the rule that decides it is the one M2
    got wrong: a compose ``command:`` replaces the image's ``Cmd`` and never its
    ``Entrypoint``.
    """
    pulled = run(["docker", "pull", "--quiet", image], timeout=900)
    assert pulled.returncode == 0, (
        f"could not pull the pinned image {image!r}, so nothing can be asked of it:\n"
        f"{pulled.stderr.strip()[:1000]}"
    )
    inspected = run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Entrypoint}}|{{json .Config.Cmd}}",
            image,
        ]
    )
    assert inspected.returncode == 0, inspected.stderr
    entrypoint, _, command = inspected.stdout.strip().partition("|")
    return json.loads(entrypoint) or [], json.loads(command) or []


def start(service: dict) -> str:
    """Create one rendered service's container, try to start it, and return its id.

    Everything the service declares is passed through — image, argv, capabilities,
    devices — because a container that reached ``Up`` without the capability it needs is
    the same failure one level in. Nothing else is: no network, no bind mount, and no
    restart policy, so a command that exits stays exited and can be read.

    ``create`` then ``start``, rather than ``run``, because a FAILING start is a result
    here and not an error: M2's containers were created and never ran, and ``docker run``
    reports that by returning 127 itself and leaving the caller with no id to inspect.
    Split in two, the container always exists and the engine's own answer about it can
    be read the same way whatever happened.
    """
    name = f"hashi-m5-argv-{uuid.uuid4().hex[:12]}"
    arguments = ["docker", "create", "--name", name, "--network", "none"]
    for capability in service["capabilities"]:
        arguments += ["--cap-add", capability]
    for device in service["devices"]:
        arguments += ["--device", device]
    arguments += [service["image"], *service["command"]]

    created = run(arguments, timeout=900)
    assert created.returncode == 0, (
        f"docker refused to create the container at all, so nothing was learned:\n"
        f"{created.stderr.strip()[:1000]}"
    )
    container = created.stdout.strip()
    run(["docker", "start", container], timeout=120)
    return container


def outcome(container: str, seconds: int = 60) -> dict:
    """What the container did: the binary the engine resolved, its status, its output."""
    status = run(["docker", "inspect", "--format", "{{.State.Status}}", container])
    if status.stdout.strip() == "running":
        # Only then: ``docker wait`` on a container that never started blocks until one
        # does, which is a hang rather than an answer.
        run(["docker", "wait", container], timeout=seconds)

    inspected = run(
        ["docker", "inspect", "--format", "{{json .Path}}|{{.State.ExitCode}}", container]
    )
    assert inspected.returncode == 0, inspected.stderr
    path, _, exit_code = inspected.stdout.strip().partition("|")
    logs = run(["docker", "logs", container], timeout=60)
    return {
        "path": json.loads(path),
        "status": int(exit_code),
        "output": logs.stdout + logs.stderr,
    }


@pytest.fixture
def started():
    """Containers this test started, removed however it ends."""
    containers: list[str] = []

    def keep(container: str) -> str:
        containers.append(container)
        return container

    yield keep

    for container in containers:
        run(["docker", "rm", "-f", container], timeout=120)


@pytest.fixture(params=INSTALLED)
def transport_ran(request, engine, started) -> tuple[dict, dict]:
    """One transport's rendered service, and what a real engine did with it.

    Parametrised over ``discover()`` rather than over today's answers: a transport added
    later brings its own data plane, and is asked this question by arriving.
    """
    service = node_stack.services_for({request.param: "a rendered config"})[0]
    container = started(start(service))
    return service, outcome(container)


def test_the_engine_execs_the_binary_the_images_entrypoint_decides(transport_ran, engine) -> None:
    """The head of the argv, as resolved by Docker — the rule M2 was broken by.

    An image with an entrypoint prepends it and our command is only arguments; an image
    without one is handed our command as the whole argv. Two of the three pinned images
    declare none, which is why ``("up", "{config}")`` was a program.
    """
    service, ran = transport_ran
    entrypoint, own_command = image_entrypoint(service["image"])

    if entrypoint:
        wanted = entrypoint[0]
    else:
        wanted = (service["command"] or own_command)[0]

    assert ran["path"] == wanted, (
        f"the engine resolved {ran['path']!r} for {service['name']!r}, and the image's "
        f"own entrypoint {entrypoint!r} plus our command {service['command']!r} says it "
        f"should have been {wanted!r}"
    )


def test_the_container_does_not_die_because_its_program_is_missing(transport_ran) -> None:
    """M2's exit code, asserted against a running engine instead of a recorded fact."""
    service, ran = transport_ran

    assert ran["status"] not in (NOT_FOUND, NOT_EXECUTABLE), (
        f"the container for {service['name']!r} exited {ran['status']}: the engine could "
        f"not execute what our command names. It never runs, and every offline test "
        f"still passes.\n{ran['output'][:1000]}"
    )


def test_the_program_reads_the_argument_we_gave_it(transport_ran) -> None:
    """The gap the offline check names: exec-ing is not accepting the config.

    The config is absent, so every data plane here fails — and what it says while failing
    is the evidence, because a program that echoes back the path we passed has plainly
    been handed our arguments and parsed them. A shell that exec'd and then did something
    else with its own arguments could not produce this.
    """
    service, ran = transport_ran

    assert service["config_path"] in ran["output"], (
        f"nothing the container for {service['name']!r} wrote mentions "
        f"{service['config_path']!r}, so there is no evidence the program we named ever "
        f"received the config path we passed it.\n{ran['output'][:1000]}"
    )


def test_a_command_naming_a_program_that_is_not_there_is_caught(engine, started) -> None:
    """The check on the check: exit 127 must still be reachable and still be reported.

    Without this, an engine that answered 0 to everything — or an inspect field we read
    wrongly — would make every assertion above vacuously green. ``up`` was the real
    argv[0] until M2, on an image that declares no entrypoint; the same shape is used
    here with a name no image could ever ship.

    The image is chosen for the property that MADE M2 possible — declaring no entrypoint
    — rather than named, so this stays true if a pin changes.
    """
    images = sorted({plane.image for plane in node_stack.DATA_PLANES.values()})
    without_entrypoint = [image for image in images if not image_entrypoint(image)[0]]
    assert without_entrypoint, (
        "every pinned image now declares an entrypoint, so a declared command can no "
        "longer become argv[0] — which is worth knowing, because it means the scenarios "
        "above are asserting about a failure that can no longer happen this way"
    )

    container = started(
        start(
            {
                "image": without_entrypoint[0],
                "command": [NOT_A_PROGRAM],
                "capabilities": [],
                "devices": [],
            }
        )
    )
    ran = outcome(container)

    assert ran["status"] == NOT_FOUND, (
        f"a command naming a program that certainly does not exist exited "
        f"{ran['status']} instead of {NOT_FOUND}, so 'the container started' is not "
        f"something this scenario can actually distinguish"
    )
