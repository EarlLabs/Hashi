"""Deployment-description tests.

WHAT: checks the compose files obey the exposure rules, not that the stack boots.
WHY:  these are exactly the mistakes that stay invisible until the day the host
      faces the internet: a published database, a service with no healthcheck, a
      floating image tag that changes under you.
HOW:  parses the YAML directly — no Docker required, so this runs in CI and on a
      laptop with the daemon stopped.
"""

import pathlib

import pytest
import yaml

DEPLOY = pathlib.Path(__file__).resolve().parents[2] / "deploy"
BASE = DEPLOY / "docker-compose.yml"
DEV = DEPLOY / "docker-compose.dev.yml"


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_base_publishes_no_ports() -> None:
    """The base stack is production shape: nothing reaches it from outside."""
    services = load(BASE)["services"]
    published = {name: svc["ports"] for name, svc in services.items() if "ports" in svc}
    assert published == {}, (
        f"base compose publishes ports for {sorted(published)} — publication belongs "
        "in docker-compose.dev.yml only"
    )


@pytest.mark.parametrize("name", sorted(load(BASE)["services"]))
def test_every_service_has_healthcheck_and_restart(name: str) -> None:
    """A service with neither sits dead while `docker compose ps` reports it up."""
    service = load(BASE)["services"][name]
    assert "healthcheck" in service, f"{name}: no healthcheck"
    assert "restart" in service, f"{name}: no restart policy"


@pytest.mark.parametrize("name", sorted(load(BASE)["services"]))
def test_images_are_pinned(name: str) -> None:
    """No floating tags: an upstream that changes under us changes our fingerprint."""
    service = load(BASE)["services"][name]
    image = service.get("image")
    if image is None:
        return  # built locally from a Dockerfile, nothing to pin here
    assert ":" in image, f"{name}: image {image!r} has no tag at all"
    tag = image.split(":", 1)[1]
    assert tag != "latest", f"{name}: image pinned to 'latest'"
    assert tag.count(".") >= 1, f"{name}: tag {tag!r} is a bare major — pin the patch version"


def test_dev_overlay_binds_loopback_only() -> None:
    """Published ports must never be reachable from another machine."""
    for name, service in load(DEV)["services"].items():
        for mapping in service.get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), (
                f"{name}: port mapping {mapping!r} is not pinned to loopback"
            )


def test_required_env_vars_fail_loudly() -> None:
    """`${VAR}` silently becomes '' without --env-file; `${VAR:?msg}` does not."""
    bad = []
    for line in BASE.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        # `$$` is compose's escape: it reaches the container as a literal `$` and
        # is expanded there, so it is not a compose interpolation at all.
        without_escapes = line.replace("$$", "")
        if "${" in without_escapes and ":?" not in without_escapes:
            bad.append(line.strip())
    assert bad == [], f"interpolations without a :? guard: {bad}"
