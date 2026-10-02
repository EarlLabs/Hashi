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

from control.app.settings import Settings

DEPLOY = pathlib.Path(__file__).resolve().parents[2] / "deploy"
BASE = DEPLOY / "docker-compose.yml"
DEV = DEPLOY / "docker-compose.dev.yml"
# The deployed shape, M7: the delivery endpoint for everyone and the console for the
# management tunnel. It was a heredoc an operator typed onto the box until getting a
# bind address wrong became the difference between a private console and a public one.
PUBLIC = DEPLOY / "docker-compose.public.yml"
# The second half of that shape, M28.10: the console on the management tunnel's own
# address. Split out because it is the only mapping that needs an address THIS HOST
# HOLDS, and a machine restored from a bucket holds none — `make up-panel-over-ssh` is
# the same publication without it. Every exposure rule below applies to both files: a
# mapping with no bind address is exactly as dangerous in one as in the other.
TUNNEL = DEPLOY / "docker-compose.tunnel.yml"
PANEL_OVERLAYS = [PUBLIC, TUNNEL]

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


# The variables this stack is allowed to leave UNSET, spelled out rather than inferred
# from the form they are written in — M27.6. Every other interpolation must carry `:?`,
# because `${VAR}` silently becomes '' without `--env-file` and the stack then comes up
# configured for nothing. These two are different in kind: blank means "no node serves
# its own users' subscription refreshes", which is a supported shape and the shipped one,
# so `:?` would refuse to start the fleet that has not got that feature.
#
# Which interpolations may be blank, DERIVED from the settings model rather than listed
# here — M31.2. A blank is safe for exactly one kind of variable: a ``Settings`` field with
# a default, because ``Settings`` reads a set-but-empty variable as unset
# (``env_ignore_empty``) and so takes the default written in control/app/settings.py.
#
# Derived and not an allowlist since M31, and the direction still holds: a REQUIRED field
# made optional in this file (``${HASHI_SECRET_KEY:-}``) is not in this set, so it is still
# red rather than reading as intentional — and so is any non-``HASHI_`` variable, which no
# default of ours can catch.
SETTINGS_WITH_A_DEFAULT = {
    f"HASHI_{name.upper()}"
    for name, field in Settings.model_fields.items()
    if not field.is_required()
}


def test_required_env_vars_fail_loudly() -> None:
    """`${VAR}` silently becomes '' without --env-file; `${VAR:?msg}` does not.

    And `${VAR:-}` — blank on purpose — only for a setting whose blank is its default.
    """
    assert Settings.model_config.get("env_ignore_empty") is True, (
        "Settings no longer reads a blank variable as unset, so every `${VAR:-}` below "
        "hands the control plane an empty string it will refuse to boot on"
    )
    bad = []
    for line in BASE.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        # `$$` is compose's escape: it reaches the container as a literal `$` and
        # is expanded there, so it is not a compose interpolation at all.
        without_escapes = line.replace("$$", "")
        if "${" not in without_escapes:
            continue
        named = re.findall(r"\$\{([A-Z0-9_]+)", without_escapes)
        if ":?" not in without_escapes and not set(named) <= SETTINGS_WITH_A_DEFAULT:
            bad.append(line.strip())
    assert bad == [], f"interpolations without a :? guard: {bad}"


# The settings a DEPLOYED control plane deliberately cannot be handed, each with the
# reason. Everything else ``Settings`` declares must be in ``control.environment`` —
# M31.2. Kept as a dict with its reasons beside it so that adding a name here is a
# sentence somebody has to write, rather than a quiet way to make the test below pass.
NOT_FOR_A_DEPLOYMENT = {
    # Off only in the e2e overlay, which talks to the control plane over plain HTTP. The
    # base file leaving it out is what keeps a deployment from inheriting it from a laptop
    # (deploy/docker-compose.e2e.yml says so where it sets it).
    "HASHI_PUBLIC_HTTPS",
    # Its default IS the read-only mount point this file declares; a value set in .env
    # would name a path inside the container that nothing mounts. The suite points it at
    # a record it wrote itself, which is the only reason it is a setting at all.
    "HASHI_BACKUP_RECORD",
}


def test_a_setting_the_operator_is_told_to_fill_reaches_the_container() -> None:
    """The defect this is the guard for shipped twice and could not be seen either time.

    `control.environment` enumerates what the control plane may read, there is no
    `env_file`, and `.env` is excluded from the build context — so a variable missing from
    that list does not exist inside the container however carefully the operator sets it.
    There is no error: the setting takes its default, and the feature it configures is
    simply absent. M27.6 shipped the delivery certificate pair that way.

    WHY THIS RULE MISSED THE SECOND ONE (M31.2). It asked only about settings documented
    in ``.env.example``, and ``HASHI_FINDING_REMEASURE_INTERVAL`` was documented in
    ``docs/decisions.md``, in the settings model and nowhere an ``^VAR=`` line could be
    found — so it was outside the rule's question entirely, and so were five more that the
    Settings screen tells the operator to change (``HASHI_SESSION_MAX_AGE``,
    ``HASHI_NODE_SSH_TIMEOUT``, …). The field walk set it in ``.env`` and ``env`` inside
    the container showed nothing.

    So the question is now asked of the SETTINGS MODEL ALONE: every field is passed
    through, or is named in ``NOT_FOR_A_DEPLOYMENT`` with the reason it must not be.
    Where the operator happened to read about a variable no longer decides whether it
    works.
    """
    readable = {f"HASHI_{name.upper()}" for name in Settings.model_fields}
    passed_through = set(
        yaml.safe_load(BASE.read_text())["services"]["control"]["environment"]
    )
    unreachable = sorted(readable - passed_through - NOT_FOR_A_DEPLOYMENT)
    assert unreachable == [], (
        "control/app/settings.py reads these, and deploy/docker-compose.yml does not pass "
        f"them into the container, so setting them in .env does nothing: {unreachable}"
    )
    assert NOT_FOR_A_DEPLOYMENT <= readable, (
        "NOT_FOR_A_DEPLOYMENT names a setting that no longer exists: "
        f"{sorted(NOT_FOR_A_DEPLOYMENT - readable)}"
    )
    assert not NOT_FOR_A_DEPLOYMENT & passed_through, (
        "a setting kept off deployments on purpose is passed through after all: "
        f"{sorted(NOT_FOR_A_DEPLOYMENT & passed_through)}"
    )


def test_the_remeasure_interval_is_documented_with_its_off_switch() -> None:
    """M31.2's other half: the operator can find it, and finds out what 0 does."""
    lines = (DEPLOY.parent / ".env.example").read_text().splitlines()
    at = next(
        (i for i, line in enumerate(lines) if line.startswith("HASHI_FINDING_REMEASURE_INTERVAL=")),
        None,
    )
    assert at is not None, ".env.example does not name HASHI_FINDING_REMEASURE_INTERVAL"
    # The comment paragraph directly above the line, and nothing further up.
    above = []
    for line in reversed(lines[:at]):
        if not line.startswith("#"):
            break
        above.append(line)
    assert "HASHI_FINDING_REMEASURE_INTERVAL=0" in "\n".join(above), (
        ".env.example names the interval without saying that 0 switches it off"
    )


def test_the_delivery_certificate_is_readable_where_its_path_points() -> None:
    """Passing the PATHS through is half of it — M27.6.

    The control plane reads those two files and pushes their contents to a node, so a
    path naming somewhere the container cannot open fails exactly as leaving them blank
    does. `.env.example` tells the operator to put the pair in `deploy/delivery/` and to
    name them under `/etc/hashi/delivery`; this is what holds those two sentences to the
    mount that makes them true.
    """
    mounts = yaml.safe_load(BASE.read_text())["services"]["control"]["volumes"]
    assert "../deploy/delivery:/etc/hashi/delivery:ro" in mounts, mounts
    guidance = (DEPLOY.parent / ".env.example").read_text()
    assert "/etc/hashi/delivery/" in guidance
    assert "deploy/delivery/" in guidance


def test_the_operator_is_told_the_pair_must_be_readable_by_the_container() -> None:
    """The other half of "readable", and the one following the instructions loses — M27.7.

    The control plane runs as a system account in its own image (uid 999, measured on a
    built image on 2026-09-27) and the files belong to whoever placed them. At the 0600 a
    private key normally carries the read fails, the pair is refused, and no host serves
    refreshes — so an operator who does exactly as told, with a correctly permissioned
    key, gets the same outcome as one who configured nothing.

    AND IT IS CHECKED BESIDE THE RENEWAL INSTRUCTION, not only beside the placement one.
    Renewal is "replace the two files", which is where `cp -p` and a certbot deploy hook
    put the issuer's own mode back — a step an operator takes every few months, long
    after reading the paragraph above it.
    """
    guidance = (DEPLOY.parent / ".env.example").read_text()
    assert "uid 999" in guidance, (
        "`.env.example` no longer says which account inside the container has to be able "
        "to read the delivery pair"
    )
    renewal = next(
        (
            paragraph
            for paragraph in guidance.split("#\n")
            if "Renewal is replacing the two files" in paragraph
        ),
        "",
    )
    assert renewal, "the renewal instruction for the delivery pair is gone"
    assert "mode" in renewal, (
        "the renewal instruction no longer says to check the mode — this is the step "
        "that reintroduces a 0600 key the container cannot open"
    )


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


@pytest.mark.parametrize("overlay", PANEL_OVERLAYS, ids=lambda p: p.name)
def test_only_the_reverse_proxy_is_published_on_a_deployed_host(overlay: pathlib.Path) -> None:
    """Caddy, and never the database.

    The base file publishes nothing and cannot be made to unpublish (``ports:`` is a
    sequence and Compose appends), so this overlay is the only place a real host opens
    anything — which makes it the only place a database can be opened by accident.
    """
    services = load(overlay)["services"]
    publishing = sorted(name for name, svc in services.items() if svc.get("ports"))
    assert publishing == ["caddy"], (
        f"{overlay.name} publishes {publishing}; only the reverse proxy belongs "
        "on a host that faces the internet"
    )


@pytest.mark.parametrize("overlay", PANEL_OVERLAYS, ids=lambda p: p.name)
def test_the_console_is_published_on_an_address_and_never_on_everything(
    overlay: pathlib.Path,
) -> None:
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
    for mapping in load(overlay)["services"]["caddy"]["ports"]:
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


@pytest.mark.parametrize("overlay", PANEL_OVERLAYS, ids=lambda p: p.name)
def test_the_deployed_overlay_fails_loudly_on_a_missing_value(overlay: pathlib.Path) -> None:
    """Same rule as the base file, and it matters more here.

    Without ``:?`` an unset ``HASHI_PRIVATE_BIND_ADDR`` interpolates to the empty
    string, the mapping becomes ``":54143:54143"``, and docker publishes the console on
    every interface. The stack comes up, the panel works, and it is public.
    """
    bad = []
    for line in overlay.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        without_escapes = line.replace("$$", "")
        if "${" in without_escapes and ":?" not in without_escapes:
            bad.append(line.strip())
    assert bad == [], f"interpolations without a :? guard: {bad}"
