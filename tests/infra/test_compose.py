"""Deployment-description tests.

WHAT: checks the compose files obey the exposure rules, not that the stack boots.
WHY:  these are exactly the mistakes that stay invisible until the day the host
      faces the internet: a published database, a service with no healthcheck, a
      floating image tag that changes under you.
HOW:  parses the YAML directly — no Docker required, so this runs in CI and on a
      laptop with the daemon stopped.
"""

import pathlib
import re

import pytest
import yaml

DEPLOY = pathlib.Path(__file__).resolve().parents[2] / "deploy"
BASE = DEPLOY / "docker-compose.yml"
DEV = DEPLOY / "docker-compose.dev.yml"
# The deployed shape, M7: the delivery endpoint for everyone and the console for the
# management tunnel. It was a heredoc an operator typed onto the box until getting a
# bind address wrong became the difference between a private console and a public one.
PUBLIC = DEPLOY / "docker-compose.public.yml"

# Ports the host is likely to already be using. Publishing on one is how two
# projects collide on the same laptop, and the collision shows up as a confusing
# "port is already allocated" mid-build. Inside the compose network defaults are
# fine — this is only about what we publish.
SERVICE_DEFAULTS = {
    80, 443, 3000, 3306, 5000, 5432, 5672, 6379, 8000, 8080,
    8443, 9000, 9090, 9200, 15672, 27017,
}
# A published mapping is "<bind>:<host port>:<container port>", where either of
# the first two may be a compose interpolation with a default:
#   "127.0.0.1:8000:8000" | "${DEV_BIND_ADDR:-127.0.0.1}:${DEV_API_PORT:-58000}:8000"
BIND = r"(?:\$\{\w+:-([\d.]+)\}|([\d.]+))"
PORT = r"(?:\$\{\w+:-(\d+)\}|(\d+))"
HOST_PORT = re.compile(rf"^{BIND}:{PORT}:\d+$")


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


def assert_pinned(label: str, image: str) -> None:
    """An upstream that changes under us changes our fingerprint."""
    assert ":" in image, f"{label}: image {image!r} has no tag at all"
    tag = image.split(":", 1)[1]
    assert tag != "latest", f"{label}: image pinned to 'latest'"
    assert tag.count(".") >= 1, f"{label}: tag {tag!r} is a bare major — pin the patch version"


@pytest.mark.parametrize("name", sorted(load(BASE)["services"]))
def test_images_are_pinned(name: str) -> None:
    """No floating tags on anything we pull."""
    image = load(BASE)["services"][name].get("image")
    if image is None:
        return  # built locally — covered by test_dockerfile_base_images_are_pinned
    assert_pinned(name, image)


ARG_DEFAULT = re.compile(r"^ARG\s+(\w+)\s*=\s*(\S+)\s*$")
INTERPOLATION = re.compile(r"\$\{(\w+)\}|\$(\w+)")


def expand_args(image: str, defaults: dict[str, str]) -> str:
    """Resolve ``${NAME}`` / ``$NAME`` in a FROM line against the ARG defaults.

    A tag may legitimately be composed from a build argument: the acceptance
    browser DERIVES its upstream tag from the version it installs the ``playwright``
    package at, so the package and the browser build it drives cannot drift apart.
    The pin is then the ARG's default — and an ARG with no default is not a pin at
    all, it is a tag whoever runs the build gets to choose.
    """
    return INTERPOLATION.sub(
        lambda found: defaults.get(found.group(1) or found.group(2), found.group(0)), image
    )


@pytest.mark.parametrize(
    "path", sorted((DEPLOY / "docker").glob("*.Dockerfile")), ids=lambda p: p.name
)
def test_dockerfile_base_images_are_pinned(path: pathlib.Path) -> None:
    """Same rule one level down: a service we build still pulls a base image.

    Moving a service from ``image:`` to ``build:`` used to silently exempt it
    from the pinning rule — this is the half that catches it.
    """
    lines = path.read_text().splitlines()
    defaults = {
        found.group(1): found.group(2)
        for found in (ARG_DEFAULT.match(line.strip()) for line in lines)
        if found
    }
    froms = [
        line.split(maxsplit=1)[1].split()[0]
        for line in lines
        if line.upper().startswith("FROM ")
    ]
    assert froms, f"{path.name}: no FROM line"
    for image in froms:
        resolved = expand_args(image, defaults)
        assert "$" not in resolved, (
            f"{path.name}: the base image {image!r} names a build argument with no "
            f"default, so the tag is whatever the caller passes — that is a floating "
            f"tag with extra steps"
        )
        assert_pinned(path.name, resolved)


def test_dev_overlay_binds_loopback_by_default() -> None:
    """Published ports must not reach another machine unless someone says so.

    The bind address may be an interpolation (``${DEV_BIND_ADDR:-127.0.0.1}``),
    because the fleet's dind engine needs an explicit opt-in — but the DEFAULT,
    which is what `make up-dev` and every hand-typed compose command use, has to
    be loopback. A literal ``0.0.0.0`` here, or a default that is anything else,
    is a database on a café network.
    """
    for name, service in load(DEV)["services"].items():
        for mapping in service.get("ports", []):
            match = HOST_PORT.match(str(mapping))
            assert match, f"{name}: cannot read a bind address out of {mapping!r}"
            bind = match.group(1) or match.group(2)
            assert bind == "127.0.0.1", (
                f"{name}: port mapping {mapping!r} defaults to {bind!r}, not loopback"
            )


def test_published_ports_avoid_service_defaults() -> None:
    """A published port must not be one the host probably already runs."""
    offenders = []
    for name, service in load(DEV)["services"].items():
        for mapping in service.get("ports", []):
            match = HOST_PORT.match(str(mapping))
            assert match, f"{name}: cannot read a host port out of {mapping!r}"
            port = int(match.group(3) or match.group(4))
            if port in SERVICE_DEFAULTS:
                offenders.append(f"{name}:{port}")
    assert offenders == [], (
        f"published ports on a service default: {offenders} — pick something the "
        "host is not already using"
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


def split_mapping(mapping: str) -> list[str]:
    """Split ``bind:host:container`` on colons that are not inside a ``${…}``.

    Needed because this file's interpolations carry ``:?`` guards whose MESSAGES
    contain colons and spaces — a plain ``str.split(":")`` reads one mapping as
    eleven fields and every assertion below then passes for the wrong reason.
    """
    fields, depth, current = [], 0, ""
    for character in mapping:
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        if character == ":" and depth == 0:
            fields.append(current)
            current = ""
            continue
        current += character
    fields.append(current)
    return fields


def test_only_the_reverse_proxy_is_published_on_a_deployed_host() -> None:
    """Caddy, and never the database.

    The base file publishes nothing and cannot be made to unpublish (``ports:`` is a
    sequence and Compose appends), so this overlay is the only place a real host opens
    anything — which makes it the only place a database can be opened by accident.
    """
    services = load(PUBLIC)["services"]
    publishing = sorted(name for name, svc in services.items() if svc.get("ports"))
    assert publishing == ["caddy"], (
        f"the deployed overlay publishes {publishing}; only the reverse proxy belongs "
        "on a host that faces the internet"
    )


def test_the_console_is_published_on_an_address_and_never_on_everything() -> None:
    """M7, stated as the property the milestone is actually made of.

    Caddy inside the container listens on every interface it has; the console is
    private exactly and only because this mapping names an address. A mapping with no
    bind address — ``"54143:54143"`` — publishes the panel to the whole internet and
    looks almost identical to the correct line.

    The delivery endpoint is the deliberate exception and is checked by name: it is
    supposed to face the world, and it serves ``/sub/*`` and a redirect and nothing
    else (deploy/caddy/Caddyfile).
    """
    delivery = {"80", "443"}
    for mapping in load(PUBLIC)["services"]["caddy"]["ports"]:
        fields = split_mapping(str(mapping))
        if len(fields) == 2 and fields[0] in delivery:
            continue
        assert len(fields) == 3, (
            f"the mapping {mapping!r} names no bind address, so it publishes on every "
            "interface this host has — including the public one"
        )
        bind = fields[0]
        assert bind == "127.0.0.1" or ":?" in bind, (
            f"the mapping {mapping!r} binds to {bind!r}: a deployed console is either on "
            "loopback (the SSH fallback) or on a required variable naming the management "
            "tunnel's address. A default here would be a default panel address."
        )


def test_the_deployed_overlay_fails_loudly_on_a_missing_value() -> None:
    """Same rule as the base file, and it matters more here.

    Without ``:?`` an unset ``HASHI_PRIVATE_BIND_ADDR`` interpolates to the empty
    string, the mapping becomes ``":54143:54143"``, and docker publishes the console on
    every interface. The stack comes up, the panel works, and it is public.
    """
    bad = []
    for line in PUBLIC.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        without_escapes = line.replace("$$", "")
        if "${" in without_escapes and ":?" not in without_escapes:
            bad.append(line.strip())
    assert bad == [], f"interpolations without a :? guard: {bad}"
