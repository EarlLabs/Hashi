"""The acceptance instrument, checked the way the subject already was — M12.

WHAT: that the browser service is built with the package the driver imports, that
      the package version and the image tag cannot drift apart, that ``stand.sh``
      takes one real action before it reports ready, and that its ``down`` takes
      away every profile its ``up`` can start.
WHY:  found in the field on 2026-09-08, on the first real run of
      ``scripts/acceptance/drive.py``. The compose file pulled the bare upstream
      Playwright image, which ships Chromium under /ms-playwright and ships pip but
      NOT the ``playwright`` Python package — so every verb died on
      ``ModuleNotFoundError`` while the stand around it was perfectly healthy, and
      ``tests/infra/test_drive.py`` was green throughout: it tests the driver's
      argument handling on the host and never asks whether the container can import
      what the driver imports. This file asks.
HOW:  static, like the rest of this tier — reading the compose overlay, the
      Dockerfile, the Makefile and the stand script. Building the image here would
      put a two-gigabyte base image on every ``make test-infra``, including the
      three CI zone jobs that deliberately need no docker engine, and the browser
      is behind a profile precisely so the ordinary gate never waits for it.
      The RUNTIME half is not skipped, it is moved to where the browser actually
      exists: ``acceptance-browser.Dockerfile`` performs the driver's own import at build
      time, and ``stand.sh up`` drives one real verb before it says ready.
"""

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
OVERLAY = REPO / "deploy" / "docker-compose.e2e.yml"
DOCKERFILE = REPO / "deploy" / "docker" / "acceptance-browser.Dockerfile"
MAKEFILE = REPO / "Makefile"
STAND = REPO / "scripts" / "acceptance" / "stand.sh"
DRIVER = REPO / "scripts" / "acceptance" / "drive.py"

# The version this repository pins, wherever it is written. A dotted release, not
# a name, so the two places that need it can be compared.
VERSION = re.compile(r"\d+(?:\.\d+)+")
ARG_DEFAULT = re.compile(r"^ARG\s+(\w+)\s*=\s*(\S+)\s*$", re.M)


@pytest.fixture(scope="module")
def browser() -> dict:
    return yaml.safe_load(OVERLAY.read_text())["services"]["browser"]


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text()


def resolve(text: str) -> str:
    """Substitute every ``${ARG}`` with the default the Dockerfile declares.

    The version is written once and reaches both the image tag and the pip pin
    through the same build argument; the tests below compare what the build
    actually ends up with, not the two spellings of it.
    """
    defaults = dict(ARG_DEFAULT.findall(text))
    return re.sub(
        r"\$\{(\w+)\}|\$(\w+)",
        lambda found: defaults.get(found.group(1) or found.group(2), found.group(0)),
        text,
    )


def test_the_browser_is_built_and_not_pulled(browser: dict) -> None:
    """The bug itself, as an assertion.

    Pulling the upstream image is exactly what looked right and was not: it carries
    the browsers and pip, so the container starts, the stand goes healthy, and the
    first verb dies importing a package nobody installed.
    """
    assert "image" not in browser, (
        "the browser service pulls an image again. The upstream Playwright image "
        "does not contain the `playwright` Python package the driver imports — "
        "build it from deploy/docker/acceptance-browser.Dockerfile instead"
    )
    assert browser["build"]["dockerfile"] == "deploy/docker/acceptance-browser.Dockerfile"
    assert browser["build"]["context"] == "..", "built from the repo root, like the other two"


def test_the_image_carries_the_module_the_driver_imports(dockerfile: str) -> None:
    """Tied to the driver's own import line rather than to the word 'playwright'.

    If ``drive.py`` ever imports something else at ``serve()``, this goes red
    instead of continuing to check the module that used to matter.
    """
    imports = ("from playwright", "import playwright")
    imported = {
        line.split()[1].split(".")[0]
        for line in DRIVER.read_text().splitlines()
        if line.strip().startswith(imports)
    }
    assert imported, (
        "drive.py no longer imports playwright — this file is checking the wrong module"
    )
    installed = resolve(dockerfile)
    for module in imported:
        assert re.search(rf"pip install[^\n]*{module}==", installed), (
            f"the browser image never installs {module!r}, which the driver imports "
            f"at its first verb"
        )


def test_the_package_version_and_the_image_tag_cannot_drift(dockerfile: str) -> None:
    """One version, one place. Two spellings of 1.55.0 is a night on the wrong layer.

    Playwright refuses to launch a browser build that is not its own release, and
    the failure surfaces as a driver that cannot open a page — the same symptom the
    missing package had, on a stand that is once again perfectly healthy.
    """
    resolved = resolve(dockerfile)
    from_line = next(line for line in resolved.splitlines() if line.upper().startswith("FROM "))
    tag = VERSION.search(from_line.rsplit(":", 1)[1])
    assert tag, f"no version in the base image tag: {from_line!r}"

    pinned = re.search(r"playwright==([^\"\s]+)", resolved)
    assert pinned, "the image installs no pinned playwright"
    assert pinned.group(1) == tag.group(0), (
        f"the image tag carries Playwright {tag.group(0)} and the package is pinned to "
        f"{pinned.group(1)} — a browser build and a client that disagree"
    )

    written = DOCKERFILE.read_text().count(tag.group(0))
    assert written == 1, (
        f"{tag.group(0)} appears {written} times in the Dockerfile. Write it once "
        f"and derive the rest from it (ARG PLAYWRIGHT_VERSION), or the two copies will "
        f"drift the first time somebody upgrades in a hurry"
    )


def test_the_driver_can_be_run_the_way_it_is_documented() -> None:
    """`scripts/acceptance/drive.py begin …` — as a command, with no interpreter.

    That is how aikit.yml's `hands` block spells it and how the stand invokes it,
    and the file was committed 0644 while its two siblings were 0755: every one of
    those calls got `Permission denied`. The same shape as the rest of this
    milestone — a documented instrument that had never been run.
    """
    assert DRIVER.read_text().startswith("#!"), "no shebang, so it cannot be run as a command"
    assert DRIVER.stat().st_mode & 0o111, (
        "scripts/acceptance/drive.py is not executable, so the documented hands "
        "command fails before it reaches the stand"
    )


def profiles_in_the_overlay() -> set[str]:
    services = yaml.safe_load(OVERLAY.read_text())["services"]
    return {profile for service in services.values() for profile in service.get("profiles", [])}


def test_down_takes_away_every_profile_up_can_start() -> None:
    """`docker compose down` only touches services in the profiles it is given.

    Observed: after a clean ``stand.sh down``, ``hashi-e2e-browser-1`` was still
    running, holding its gigabyte of shared memory — one leaked per acceptance run,
    and invisible to ``up``'s own safety check, because a browser answers nothing on
    /healthz. Asserted against the overlay rather than against the word "browser",
    so a second profile inherits the rule.
    """
    makefile = MAKEFILE.read_text()
    declared = re.search(r"^E2E_ALL_PROFILES\s*:?=\s*(.*)$", makefile, re.M)
    assert declared, "the Makefile no longer says which profiles a teardown has to cover"
    assert set(declared.group(1).split()) == profiles_in_the_overlay(), (
        "E2E_ALL_PROFILES and the profiles in docker-compose.e2e.yml disagree, so "
        "`make e2e-down` leaves a container behind"
    )
    # `override` is required, not merely tolerated. Without it GNU Make lets a
    # command-line `E2E_PROFILES=...` win over a target-specific variable, which is a
    # latent way to defeat the very leak this line closes — a browser left running per
    # acceptance run, holding 1 GB of shm. Teardown takes everything, always.
    assert re.search(
        r"^e2e-down:\s*override\s+E2E_PROFILES\s*:?=\s*\$\(E2E_ALL_PROFILES\)", makefile, re.M
    ), (
        "`e2e-down` no longer widens E2E_PROFILES with `override`, so it tears down only "
        "what a profile-less `up` would have started — or lets a command-line "
        "E2E_PROFILES= silently narrow it"
    )


def test_the_teardown_override_is_not_frozen_by_a_simple_assignment() -> None:
    """`COMPOSE_E2E :=` would expand the profile list once, at the empty default.

    The target-specific override above would then be accepted by make, change
    nothing, and leave the browser running — a failure with no error message at
    all, which is the shape of every bug in this milestone.
    """
    assert re.search(r"^COMPOSE_E2E\s+=", MAKEFILE.read_text(), re.M), (
        "COMPOSE_E2E is simply expanded again, so `e2e-down`'s profile override is "
        "silently ignored"
    )


def test_the_stand_proves_its_hands_before_it_reports_ready() -> None:
    """A health check proves the subject. This proves the instrument.

    ``stand.sh up`` reported ready on a stand whose driver could not take a single
    action, which is how a broken instrument reached the milestone it was there to
    judge.
    """
    stand = STAND.read_text()
    assert "prove_the_hands" in stand, "the stand no longer takes an action before saying ready"
    check = stand.split("prove_the_hands() {", 1)[1].split("\n}", 1)[0]
    assert "drive.py begin" in check and "drive.py open" in check, (
        "the check no longer goes through the real driver — an `import playwright` "
        "inside the container would leave the socket, the mount and the compose "
        "invocation unproved, and those all looked healthy while the driver was dead"
    )
    called = re.search(r"^\s*prove_the_hands \|\| die ", stand, re.M)
    assert called, (
        "the hands check no longer stops the stand from reporting ready — a check "
        "whose failure is ignored is worse than no check"
    )


def test_the_stand_check_never_opens_a_subscription_url() -> None:
    """A subscription path is a bearer credential, and this one is printed and shot.

    The instrument check writes a screenshot and its address goes to whoever ran the
    stand. It opens the panel's front door, which carries no token.
    """
    body = STAND.read_text().split("prove_the_hands() {", 1)[1].split("\n}", 1)[0]
    # Comments stripped: the function's own comment says not to open a /sub/ address,
    # and a test that reads that as an offence would be arguing with the reason.
    commands = [line for line in body.splitlines() if not line.strip().startswith("#")]
    assert "/sub/" not in "\n".join(commands), (
        "the hands check opens a delivery URL, so a token ends up in the stand's own "
        "output and in a screenshot filename"
    )


def test_a_stand_that_is_down_is_checked_for_leftovers() -> None:
    """`down` says 'gone.' — it now has to be true before it says it."""
    down = STAND.read_text().split("down() {", 1)[1].split("\n}", 1)[0]
    assert "docker ps -a" in down and "com.docker.compose.project" in down, (
        "nothing asks whether the teardown left a container behind, which is how a "
        "browser per acceptance run accumulated on a host short of memory"
    )
    assert "die " in down, "the leftover check reports nothing it can act on"
