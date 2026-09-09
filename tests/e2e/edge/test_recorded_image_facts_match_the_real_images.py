"""Are the image facts this repository asserts against still true of the images?

WHAT: pulls every upstream data-plane image pinned in ``edge/bootstrap/node_stack.py``
      and re-derives, from the real image, the two things a container command depends
      on — the image's own entrypoint and command, and whether each binary a
      ``DataPlane`` names can actually be executed in it. Then compares that against
      ``tests/edge/golden/image-facts.json``, which the unit suite asserts against.
WHY:  M2 was one wrong assumption about an image: ``command=("up", "{config}")`` on two
      images that declare NO entrypoint, so the whole argv became a binary called
      ``up``. Both containers died at ``Created`` with exit 127 and
      ``exec: "up": executable file not found in $PATH``, and nothing in the tree said
      so, because nothing in the tree had ever asked an image a question.

      The unit test that now asks it (``tests/edge/test_every_data_plane_command_is_
      executable.py``) has to run without a network — a check people skip is a check
      that does not exist — so it reads recorded facts. Recorded facts rot. This is the
      scenario that stops them rotting: it is the only thing standing between "a JSON
      file in our repository says awg-quick is there" and "awg-quick is there".
HOW:  ``make test-e2e``, or directly:

          pytest tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py

      To RE-RECORD after changing a pin or adding a data plane, run it with

          HASHI_RECORD_IMAGE_FACTS=1 pytest \
              tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py

      which rewrites the golden file from the real images and then asserts against what
      it wrote. The rewrite is a deliberate act reviewed as a diff, like every other
      golden file in this repository — never something a test run does by itself.

      Resolvability is answered by asking DOCKER to exec the binary as the container's
      entrypoint, and reading the exit code its own runtime reports: 127 is "executable
      file not found", 126 is "found and not executable". That is deliberately the same
      mechanism that produced the bug, rather than a shell lookup of ours — the xray
      image ships no shell at all, so a shell-based probe could not even ask.

Boundary: this reaches the public internet (it pulls images) and needs a docker engine.
It proves the recorded facts are true of the image. It does NOT prove the data plane
WORKS: that the arguments are right, that the tunnel comes up, that traffic flows. That
is the owner's field check on a real node, and no scenario here can stand in for it.
"""

import json
import os
import pathlib
import subprocess
import uuid

import pytest

from edge.bootstrap.node_stack import DATA_PLANES

FACTS_FILE = (
    pathlib.Path(__file__).resolve().parents[2] / "edge" / "golden" / "image-facts.json"
)

RECORD = os.environ.get("HASHI_RECORD_IMAGE_FACTS") == "1"

# Sorted so a failure names the same image on every run.
IMAGES = sorted({data_plane.image for data_plane in DATA_PLANES.values()})

# How long a binary that STARTS is given before we accept that it started. Anything that
# is still running has plainly been found and executed, which is the whole question.
STARTED_AFTER = 20

# What the OCI runtime reports for a command it could not exec. Docker's own documented
# convention, and the exact pair of codes M2's bug produced.
NOT_FOUND = 127
NOT_EXECUTABLE = 126


def _run(arguments: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)


def image_config(image: str) -> tuple[list[str], list[str]]:
    """The image's OWN entrypoint and command, straight from its metadata.

    Both matter and they are not interchangeable: compose's ``command:`` replaces the
    image's ``Cmd`` and never its ``Entrypoint``, so which of the two a name comes from
    decides whether our declared command is the whole argv or only its tail.
    """
    result = _run(
        ["docker", "inspect", "--format", "{{json .Config.Entrypoint}}|{{json .Config.Cmd}}", image]
    )
    assert result.returncode == 0, f"could not inspect {image!r}:\n{result.stderr.strip()}"
    entrypoint, _, command = result.stdout.strip().partition("|")
    return json.loads(entrypoint) or [], json.loads(command) or []


def executes(image: str, name: str) -> bool:
    """Can docker exec ``name`` in this image?

    Runs it as the entrypoint with no arguments and no network, and asks only whether
    the runtime could START it. A binary that runs and exits non-zero (a usage message)
    has been found; a binary that keeps running has been found too, and is killed.
    """
    container = f"hashi-facts-{uuid.uuid4().hex[:12]}"
    try:
        arguments = ["docker", "run", "--name", container, "--network", "none"]
        result = _run(arguments + ["--entrypoint", name, image], timeout=STARTED_AFTER)
    except subprocess.TimeoutExpired:
        # Still running after twenty seconds, so it was found and executed.
        return True
    finally:
        _run(["docker", "rm", "-f", container], timeout=60)

    if result.returncode in (NOT_FOUND, NOT_EXECUTABLE):
        return False
    # 125 is docker itself failing rather than the container — a wrong flag, no engine.
    # Reported rather than recorded as an answer, because recording it would write "this
    # binary is missing" into the golden file on the strength of our own mistake.
    assert result.returncode != 125, (
        f"docker could not run {image!r} at all, so nothing was learned about {name!r}:\n"
        f"{result.stderr.strip()[:1000]}"
    )
    return True


def names_needed(image: str, entrypoint: list[str], command: list[str]) -> list[str]:
    """Every binary name this image is expected to be able to exec, for our data planes.

    Two sources, and the distinction is the one M2 got wrong. The head of the argv is
    the image's entrypoint when it declares one, and otherwise the first word of
    whatever ``Cmd`` runs — the data plane's declared command, or the image's own when
    it declares none. And then everything a ``DataPlane`` says its command line invokes
    from inside, which no reading of argv[0] would ever reach.
    """
    planes = [plane for plane in DATA_PLANES.values() if plane.image == image]
    names = set()
    if entrypoint:
        names.add(entrypoint[0])
    else:
        if command:
            names.add(command[0])
        for plane in planes:
            if plane.command:
                names.add(plane.command[0])
    for plane in planes:
        names.update(plane.executables)
    return sorted(names)


def derive() -> dict:
    """Read every pinned image and build the facts from scratch."""
    images = {}
    for image in IMAGES:
        pulled = _run(["docker", "pull", "--quiet", image], timeout=600)
        assert pulled.returncode == 0, (
            f"could not pull the pinned image {image!r}, so it cannot be checked:\n"
            f"{pulled.stderr.strip()[:1000]}"
        )
        entrypoint, command = image_config(image)
        images[image] = {
            "entrypoint": entrypoint,
            "cmd": command,
            "resolves": {
                name: executes(image, name) for name in names_needed(image, entrypoint, command)
            },
        }
    return {
        "_": (
            "Recorded from the real images by "
            "tests/e2e/edge/test_recorded_image_facts_match_the_real_images.py. "
            "Do not hand-edit: re-record with HASHI_RECORD_IMAGE_FACTS=1."
        ),
        "images": images,
    }


@pytest.fixture(scope="module")
def derived() -> dict:
    """The facts as the real images report them today. One pull per run, not per test."""
    return derive()


def test_the_recorded_facts_are_what_the_images_report(derived: dict) -> None:
    """The golden file and the registry agree — or the golden file is rewritten.

    A single equality rather than a field-by-field walk, because the failure this guards
    against is not "one value drifted": it is "the recorded answer no longer describes
    this image", and the whole record is the answer.
    """
    if RECORD:
        FACTS_FILE.write_text(json.dumps(derived, indent=2, sort_keys=True) + "\n")

    recorded = json.loads(FACTS_FILE.read_text())

    assert recorded["images"] == derived["images"], (
        "the recorded image facts no longer match the real images, so the unit check "
        "that reads them is asserting against something that is not true. Re-record "
        "with HASHI_RECORD_IMAGE_FACTS=1 and review the diff — a binary that has "
        "DISAPPEARED from an image is a data plane that will not start."
    )


def test_a_binary_that_is_not_there_is_reported_as_missing() -> None:
    """Proof that the probe can say no. The red half, applied to the tool.

    Without it, a probe that answered "yes, it executes" to everything — a docker CLI
    that swallowed its own error, an exit code we read wrongly — would make every fact
    above a recorded ``true`` and mean nothing. ``up`` is not an arbitrary example: it
    is the exact argv[0] that shipped in this repository until M2.
    """
    assert executes(IMAGES[0], "up") is False, (
        "a binary that is certainly absent was reported as executable, so this probe "
        "is not answering the question and every recorded fact is worthless"
    )
