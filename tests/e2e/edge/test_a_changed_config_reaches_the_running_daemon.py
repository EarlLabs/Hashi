"""Does an apply reach the process? — M5.3, asked of a real Docker, which is the point.

WHAT: places a config, brings the data plane up, changes the config, applies again, and
      asks the engine whether the process serving it changed too — plus what
      ``edge.health.probe`` says about a node in between, while the file on disk is
      already new and the daemon is still old.
WHY:  M1. On a real node, measured, a config was written **8m25s after** the container
      meant to serve it started; the apply returned 200, the node reported ``active``,
      and the probe said ``healthy: true, drifted: []``. A revoked friend would have
      stayed connected. The cause is that ``docker compose up -d`` is DECLARATIVE and
      the CONTENTS of a bind-mounted file are not part of a service definition, so the
      fix was to put the config's digest into the definition as a label.

      M1's own unit test says, in its header, that it cannot prove the half that
      matters: *"nothing here proves Docker recreates a container when a label changes.
      That is Compose's documented behaviour and it is a field observation on a real
      node."* A fake that models one rule of Compose reproduces the bug it is testing
      for, one level up. **This is the scenario that stops relying on the model.**
HOW:  one sequence, run once, with every state recorded as it happens: apply, observe;
      change the file underneath the running daemon, probe; apply again, observe; apply
      a third time with nothing changed, observe. The assertions then read the record,
      so they cannot reorder each other and the expensive part happens once.

      The changed config is the same config plus one byte. The mechanism under test is a
      digest of BYTES, and one byte is the smallest difference an edit can make — a
      friend added or revoked changes far more, and would prove strictly less. Choosing
      it this way also keeps the scenario free of any knowledge of a config's syntax, so
      a transport added later is applied here by arriving.

Boundary: needs a docker engine, ``/dev/net/tun`` and the pinned images, and it changes
what the offline suite could not: that a REAL engine recreates a real container on a
label change. It still proves nothing about SSH, about the control plane's apply
endpoint, or about a friend's client — the first is ``tests/control``, the last is a
field observation with a real client on a real node.
"""

import asyncio
import datetime
import pathlib

import pytest
import yaml

from edge.bootstrap import node_stack
from edge.health.probe import probe
from edge.registry import discover

INSTALLED = sorted(discover())

# One byte, appended. See the module docstring: the definition's digest is over the
# config's bytes, and both config formats in this project tolerate a trailing newline —
# so this is a real change to the file that needs no knowledge of what is in it.
A_BYTE = "\n"


def when(timestamp: str) -> datetime.datetime:
    """Docker's RFC 3339 timestamps, which carry more precision than Python parses.

    Truncated to microseconds rather than rounded: the comparison this feeds is "the
    process started after the file was written", and a nanosecond either way cannot
    change an answer that was eight minutes wrong on the node this milestone came from.
    """
    head, _, rest = timestamp.partition(".")
    fraction = (rest.rstrip("Z")[:6] or "0").ljust(6, "0")
    return datetime.datetime.fromisoformat(f"{head}.{fraction}+00:00")


def observe(stack, transport_name: str) -> dict:
    """Everything about the container currently serving one transport, AT THIS MOMENT.

    The digest of the file on disk is read here rather than by the assertion, because
    this scenario deliberately changes that file underneath a running daemon later on —
    an assertion reading it afterwards would be comparing the container to a config that
    replaced the one it was created from.
    """
    container = stack.container_id(transport_name)
    label, _, started = stack.inspect(
        container,
        f'{{{{index .Config.Labels "{node_stack.CONFIG_DIGEST_LABEL}"}}}}|{{{{.State.StartedAt}}}}',
    ).partition("|")
    on_disk = (
        stack.config_dir
        / pathlib.PurePosixPath(node_stack.config_path_for(transport_name)).name
    ).read_text()
    return {
        "container": container,
        "label": label,
        "started": when(started),
        "on_disk": node_stack.digest_of(on_disk),
    }


@pytest.fixture(scope="module")
def applied(data_plane_stack, golden_server_config) -> dict:
    """One apply, one edit, a second apply and a third — recorded as it happened.

    ``asyncio.run`` for the two ``edge`` functions that take a node connection: they are
    the product's own async code and this fixture is not a test, so it runs each in its
    own loop rather than forcing every assertion below to be async for a value that was
    read minutes earlier.
    """
    first_configs = {name: golden_server_config(name) for name in INSTALLED}
    second_configs = {name: config + A_BYTE for name, config in first_configs.items()}

    stack = data_plane_stack()
    stack.place(first_configs)
    stack.up()
    first = {name: observe(stack, name) for name in INSTALLED}
    written = {
        name: datetime.datetime.fromtimestamp(
            (stack.config_dir / pathlib.PurePosixPath(path).name).stat().st_mtime,
            tz=datetime.UTC,
        )
        for name, path in (
            (service["name"], service["config_path"]) for service in stack.services
        )
    }

    # The state the field measurement actually found: the file on disk is already the one
    # we would push, and the process serving it is not. Written WITHOUT re-rendering the
    # compose file, because that is what an apply did before M1 — place the config, run
    # `up -d`, and change nothing the engine compares.
    for name, config in second_configs.items():
        placed = pathlib.PurePosixPath(node_stack.config_path_for(name)).name
        (stack.config_dir / placed).write_text(config)
    stale = asyncio.run(probe(stack.node(), expected=second_configs))

    stack.place(second_configs)
    stack.up()
    second = {name: observe(stack, name) for name in INSTALLED}
    loaded = asyncio.run(node_stack.loaded_digests(stack.node()))
    healthy = asyncio.run(probe(stack.node(), expected=second_configs))

    stack.up()
    third = {name: observe(stack, name) for name in INSTALLED}

    return {
        "stack": stack,
        "configs": (first_configs, second_configs),
        "written": written,
        "first": first,
        "second": second,
        "third": third,
        "loaded": loaded,
        "stale": stale,
        "healthy": healthy,
    }


@pytest.mark.parametrize("transport_name", INSTALLED)
def test_the_container_carries_the_digest_of_the_config_it_was_given(
    transport_name: str, applied
) -> None:
    """The label is the config's own digest — the two halves of M1 cannot disagree.

    Asserted against the FILE rather than against ``services_for``'s own return value:
    the field proof compared the label to a ``sha256sum`` of the file on the node, and
    comparing the renderer's digest to the renderer's label would compare a value to
    itself.
    """
    first_configs, _ = applied["configs"]
    observed = applied["first"][transport_name]

    assert observed["label"] == observed["on_disk"], (
        f"the container serving {transport_name!r} carries a digest that is not the one "
        "of the file it has mounted, so the label certifies a config that was never "
        "placed"
    )
    assert observed["on_disk"] == node_stack.digest_of(first_configs[transport_name])


@pytest.mark.parametrize("transport_name", INSTALLED)
def test_the_process_started_after_the_config_it_serves_was_written(
    transport_name: str, applied
) -> None:
    """The field measurement, inverted into an assertion.

    Before M1: config written 01:48:11, container started 01:39:46 — the process serving
    a file was eight minutes older than the file. After: 0.5s the right way round.
    """
    started = applied["first"][transport_name]["started"]
    written = applied["written"][transport_name]

    assert started >= written, (
        f"the container serving {transport_name!r} started {written - started} BEFORE "
        "the config it is supposed to be serving was written — which is the exact shape "
        "of the failure measured on a live node, and every other signal is green"
    )


@pytest.mark.parametrize("transport_name", INSTALLED)
def test_a_changed_config_replaces_the_running_container(transport_name: str, applied) -> None:
    """The whole of M1, on a real engine: apply again, and the PROCESS changes.

    Not "the file changed" and not "compose said Started" — a different container, from
    a different definition, carrying the new digest. This is the assertion the unit test
    says it cannot make.
    """
    _, second_configs = applied["configs"]
    before = applied["first"][transport_name]
    after = applied["second"][transport_name]

    assert after["container"] != before["container"], (
        f"the container serving {transport_name!r} survived a config change, so the "
        "daemon is still running what it loaded at start. On a node this is a revoked "
        "friend who is still connected — and the apply returns 200."
    )
    assert after["label"] == node_stack.digest_of(second_configs[transport_name])
    assert after["started"] > before["started"]


@pytest.mark.parametrize("transport_name", INSTALLED)
def test_the_node_reports_the_digest_it_is_actually_running(transport_name: str, applied) -> None:
    """``loaded_digests``, the real function, against a real engine rather than a fake.

    The unit suite asks this of a ``_FakeNode`` that answers ``docker inspect`` from a
    dict. Here the pipeline is the product's — ``compose ps -q | xargs docker inspect``,
    its format string, its parsing — and the answer comes from containers that exist.
    """
    _, second_configs = applied["configs"]

    assert applied["loaded"].get(transport_name) == node_stack.digest_of(
        second_configs[transport_name]
    ), (
        f"the node reports {applied['loaded'].get(transport_name)!r} for "
        f"{transport_name!r}, which is not the digest of the config we last applied"
    )


@pytest.mark.parametrize("transport_name", INSTALLED)
def test_applying_the_same_config_again_replaces_nothing(transport_name: str, applied) -> None:
    """Idempotence, which is why ``up -d`` is the single verb for every case.

    A label that changed on every render would recreate every container on every apply —
    restarting every friend's tunnel to no purpose, and hiding a real change in the
    noise.
    """
    assert applied["third"][transport_name]["container"] == (
        applied["second"][transport_name]["container"]
    ), (
        f"an apply that changed nothing recreated {transport_name!r}'s container, so "
        "every apply restarts every transport on the node"
    )


def test_a_file_changed_underneath_a_running_daemon_is_reported_stale(applied) -> None:
    """M1's second half, in the state the field measurement found — and it is subtle.

    ``drifted`` is EMPTY here and that is correct: the file on the node genuinely is the
    one we would push. That is exactly why the old answer was so convincing. What is
    wrong is the process, and it takes a separate field to say so.
    """
    stale = applied["stale"]

    assert sorted(stale.stale) == INSTALLED, (
        "a node whose daemons are all running an older configuration reported "
        f"stale={stale.stale!r} — the state that reported `healthy: true` on real "
        "hardware for eight minutes"
    )
    assert stale.drifted == [], (
        "the file on disk is the one we would push, so reporting it as drifted would "
        "send an operator looking for someone who edited the node"
    )
    assert not stale.healthy
    assert applied["healthy"].healthy, (
        "after the second apply the node is running exactly what we pushed and still "
        "does not report healthy"
    )


def test_without_the_digest_label_the_change_is_invisible(
    data_plane_stack, golden_server_config
) -> None:
    """The check on the check: the pre-M1 tree, run for real, must fail to notice.

    This is what makes every assertion above worth something. If a real ``up -d``
    recreated a container whenever a bind-mounted file changed — or whenever anything at
    all changed — the label would be decoration and the scenario would pass without
    testing it. So the same sequence is run with the digest label REMOVED from the
    rendered compose file, which is precisely what this repository shipped before M1,
    and the container must survive the change.

    The label is stripped from the rendered YAML rather than from the template, so the
    product's own file is untouched and the difference under test is exactly one key.
    """
    name = INSTALLED[0]
    configs = {name: golden_server_config(name)}
    stack = data_plane_stack()

    def place_without_the_label(config: str) -> None:
        stack.place({name: config})
        compose_file = stack.directory / "docker-compose.yml"
        compose = yaml.safe_load(compose_file.read_text())
        labels = compose["services"][name].get("labels", {})
        assert node_stack.CONFIG_DIGEST_LABEL in labels, (
            "the rendered compose file no longer carries the config digest label at all, "
            "which is the tree as it was before M1 — an apply cannot reach a running "
            "daemon, and there is nothing here left to strip"
        )
        labels.pop(node_stack.CONFIG_DIGEST_LABEL)
        compose_file.write_text(yaml.safe_dump(compose, sort_keys=True))

    place_without_the_label(configs[name])
    stack.up()
    before = stack.container_id(name)

    place_without_the_label(configs[name] + A_BYTE)
    stack.up()

    assert stack.container_id(name) == before, (
        "a real docker compose recreated a container after a bind-mounted file changed "
        "and nothing in the service definition did. That would mean the digest label is "
        "not what makes an apply reach the daemon — and the scenarios above are not "
        "testing what they claim to test"
    )
