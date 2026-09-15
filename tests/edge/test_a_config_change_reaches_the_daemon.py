"""A changed config must change the container, and be provable on the running one — M1.

WHAT: that a transport's rendered config is part of its compose SERVICE DEFINITION,
      that ``loaded_digests`` reads back what a running container was created with,
      and that a probe calls a stale daemon stale instead of healthy.
WHY:  measured on real hardware on 2026-09-09 (docs/tracker/M1/field-measurement.md):
      a config written 8m25s AFTER the container meant to serve it started, an apply
      that returned 200, a node reported ``active`` and a health probe reporting
      ``reachable: true, healthy: true, drifted: []``. Every one of those answers was
      true; none of them established that the daemon had read the file. The friend who
      had just been added could not connect, and — the dangerous direction — a revoked
      friend would not have been cut off.
HOW:  against a fake node rather than a host. Two of the tests here are red by
      ASSERTION against the pre-M1 tree rather than by AttributeError, which is the
      only form of red worth much: see ``_FakeNode.run`` for the one deliberate
      accommodation that buys it.

      Stated plainly, because it is the boundary of this file: nothing here proves
      Docker recreates a container when a label changes. That is Compose's documented
      behaviour and it is a field observation on a real node — see M1's step notes for
      what to look at. What is proven here is our half: that the definition we render
      differs when the config differs, and that we ask the running container what it
      was started from.
"""

import pytest
import yaml

from edge.bootstrap import node_stack
from edge.bootstrap.ssh import CommandResult
from edge.health.probe import probe
from edge.registry import discover

# Two real transport names, so ``services_for`` resolves a real config format and a
# real pinned image. The config TEXT is arbitrary on purpose: a digest is a digest of
# whatever bytes were rendered, and depending on a renderer here would make this file
# fail for reasons that have nothing to do with M1.
FIRST = "vless-reality"
SECOND = "vless-ws-tls"

A_CONFIG = '{"inbounds": []}'
# The same config with one client added — which is exactly what adding a friend does,
# and what the field measurement's node never picked up.
A_CHANGED_CONFIG = '{"inbounds": [{"clients": ["a-friend"]}]}'


class _FakeNode:
    """A node with containers and files, answering the questions an apply asks it.

    ``containers`` is service name → the config digest that container was CREATED
    with, which is the only thing ``docker inspect`` can tell us and the whole basis
    of the check. ``files`` is what ``read_file`` finds on disk, so a probe can be
    given the state the field measurement found: a perfect file, a stale process.
    """

    learned_host_key = None

    def __init__(
        self,
        containers: dict[str, str],
        files: dict[str, str] | None = None,
        stopped: tuple[str, ...] = (),
    ) -> None:
        self.containers = containers
        self.files = files or {}
        self.stopped = stopped
        self.commands: list[str] = []

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        self.commands.append(command)

        if "docker inspect" in command:
            # Four fields since M22 — service, digest, running, RESTARTING. Nothing in
            # this file crash-loops, so the last is always false; the state itself is
            # modelled where it is the subject, in
            # ``test_a_transport_that_is_not_serving_is_not_reported_as_serving.py``.
            lines = [
                f"{service}|{digest}|{'false' if service in self.stopped else 'true'}|false"
                for service, digest in self.containers.items()
            ]
            return CommandResult(exit_status=0, stdout="\n".join(lines) + "\n", stderr="")

        if "docker compose ps --services" in command:
            # The PRE-M1 question — "which services are up" — kept answerable on
            # purpose, and this is the only reason it is here. It is what makes the two
            # tests below red by assertion when this file is run against the baseline
            # commit instead of erroring on a name that does not exist yet. A fake that
            # went silent on the old question would have made a stale node look
            # missing, which is a pass for the wrong reason.
            return CommandResult(
                exit_status=0,
                stdout="\n".join(
                    service for service in self.containers if service not in self.stopped
                ),
                stderr="",
            )

        return CommandResult(exit_status=0, stdout="", stderr="")

    async def read_file(self, path: str) -> str | None:
        return self.files.get(path)


def compose_for(configs: dict[str, str]) -> str:
    return node_stack.render_compose(transports=node_stack.services_for(configs))


def test_a_changed_config_is_a_changed_service_definition() -> None:
    """M1.1, and the assertion the whole milestone rests on.

    `docker compose up -d` compares the desired service definition against the running
    container and does nothing when they match. Before M1 these two rendered
    byte-identically — the config lives in a bind-mounted file whose CONTENTS are not
    part of the definition — so the apply that added a friend recreated nothing and the
    daemon went on serving the config it started with.
    """
    before = compose_for({FIRST: A_CONFIG})
    after = compose_for({FIRST: A_CHANGED_CONFIG})

    assert before != after, (
        "the compose file is byte-identical for two different configs, so `docker "
        "compose up -d` sees an unchanged service definition and leaves the stale "
        "container running — this is the M1 defect"
    )


def test_the_same_config_renders_the_same_definition() -> None:
    """The other half: unchanged configs must NOT churn the node.

    If the digest were derived from anything but the bytes — a timestamp, an ordering
    — every apply would recreate every container, and an apply that is not idempotent
    is an apply nobody dares run during a rotation.
    """
    assert compose_for({FIRST: A_CONFIG}) == compose_for({FIRST: A_CONFIG})


def test_each_service_carries_the_digest_of_its_own_config() -> None:
    """Per service, not per node: one transport's change must not restart the others.

    A node-wide digest would make enabling a new protocol restart the one every
    existing friend is already using — the blast radius the compose template exists to
    avoid (charter criterion 3).
    """
    rendered = yaml.safe_load(compose_for({FIRST: A_CONFIG, SECOND: A_CHANGED_CONFIG}))

    labels = {
        name: service["labels"][node_stack.CONFIG_DIGEST_LABEL]
        for name, service in rendered["services"].items()
    }
    assert labels[FIRST] == node_stack.digest_of(A_CONFIG)
    assert labels[SECOND] == node_stack.digest_of(A_CHANGED_CONFIG)
    assert labels[FIRST] != labels[SECOND]


def test_the_label_discloses_nothing_from_the_config() -> None:
    """A digest, never the bytes. `docker inspect` is readable by anyone on the node.

    A rendered server config carries the node's private key and every live friend's
    subject, which is why the file itself is 0600. Putting any of it in a label would
    hand it to every process on the host that can talk to the docker socket.
    """
    secret = "s3cret-node-private-key"
    rendered = compose_for({FIRST: f'{{"privateKey": "{secret}"}}'})

    assert secret not in rendered


async def test_a_running_container_reports_the_digest_it_was_created_with() -> None:
    """M1.2 — the read-back, which is what makes the label a proof rather than a hope."""
    node = _FakeNode(containers={FIRST: "abc123", SECOND: "def456"})

    assert await node_stack.loaded_digests(node) == {FIRST: "abc123", SECOND: "def456"}


async def test_a_container_that_is_not_running_is_not_reported_as_loaded() -> None:
    """"Up" is still necessary, it is just no longer sufficient.

    A daemon that starts on a bad config and exits immediately would otherwise be
    reported as loading the digest it was created with — which it did, for a second.
    """
    node = _FakeNode(containers={FIRST: "abc123"}, stopped=(FIRST,))

    assert await node_stack.loaded_digests(node) == {}


async def test_a_container_from_before_this_label_existed_reports_an_empty_digest() -> None:
    """The upgrade case, and it must not read as "up to date".

    Every node already running when M1 lands has containers with no such label. Docker
    prints ``<no value>`` for one, and the honest answer is an empty digest: the
    container is up, and it is provably not on the config we would push. Omitting it
    instead would report the transport as "not running", which is a different and
    wrong repair.
    """
    node = _FakeNode(containers={FIRST: "<no value>"})

    assert await node_stack.loaded_digests(node) == {FIRST: ""}
    assert node_stack.digest_of(A_CONFIG) != ""


async def test_a_node_that_answers_with_nothing_is_not_read_as_healthy() -> None:
    """No containers, or an unparseable line, means no digests — never a silent match."""
    node = _FakeNode(containers={})

    assert await node_stack.loaded_digests(node) == {}


async def test_the_verification_command_names_no_transport() -> None:
    """Core invariants §1, on the one file most tempted to break it.

    Asking a daemon what it loaded would have been the obvious implementation, and it
    is protocol-specific: a different command and a different answer per transport.
    Reading a container's own labels works for every family alike, and this is the
    assertion that keeps the cheaper answer out.
    """
    node = _FakeNode(containers={FIRST: "abc123"})
    await node_stack.loaded_digests(node)

    for name in discover():
        for command in node.commands:
            assert name not in command, (
                f"the verification command names the transport {name!r}: {command!r}"
            )


async def test_a_stale_daemon_is_not_reported_healthy() -> None:
    """The field measurement of 2026-09-09, as a test.

    The file on disk is exactly what we would push; the process was started from the
    previous one. Before M1 this node answered ``healthy: true, drifted: []`` — every
    field true, and the friend who had just been added could not connect.
    """
    node = _FakeNode(
        containers={FIRST: node_stack.digest_of(A_CONFIG)},
        files={node_stack.config_path(FIRST): A_CHANGED_CONFIG},
    )

    health = await probe(node, expected={FIRST: A_CHANGED_CONFIG})

    assert health.healthy is False, (
        "a node whose daemon never read the config we pushed reported healthy — this "
        "is the second half of the M1 defect, and it is what an operator reads before "
        "believing a revocation took effect"
    )
    assert health.stale == [FIRST]
    assert health.drifted == [], (
        "staleness was reported as drift, which tells the operator somebody edited the "
        "node when nobody did"
    )
    assert "still running an older configuration" in health.detail


async def test_a_node_running_what_we_pushed_is_healthy() -> None:
    """The green case, so the check above cannot pass by refusing everything."""
    node = _FakeNode(
        containers={FIRST: node_stack.digest_of(A_CONFIG)},
        files={node_stack.config_path(FIRST): A_CONFIG},
    )

    health = await probe(node, expected={FIRST: A_CONFIG})

    assert health.healthy is True
    assert health.stale == []
    assert health.drifted == []
    assert health.running == [FIRST]


async def test_an_edited_file_is_drift_and_not_staleness() -> None:
    """The two faults stay apart, because their repairs differ.

    Somebody edited the config on the node and the daemon is running what we pushed.
    That is drift; applying again replaces the file. Calling it staleness would send
    the operator looking for an apply that did not take.
    """
    node = _FakeNode(
        containers={FIRST: node_stack.digest_of(A_CONFIG)},
        files={node_stack.config_path(FIRST): "edited by hand on the node"},
    )

    health = await probe(node, expected={FIRST: A_CONFIG})

    assert health.drifted == [FIRST]
    assert health.stale == []
    assert "configuration drifted" in health.detail


@pytest.mark.parametrize("transport_name", sorted(discover()))
def test_every_transport_gets_a_digest_label(transport_name: str) -> None:
    """Every family, not just the one the bug was found on.

    ``services_for`` is shared code and the WireGuard families run a different daemon
    with a different command. If the label were attached anywhere protocol-aware, this
    is where it would show.
    """
    rendered = yaml.safe_load(compose_for({transport_name: A_CONFIG}))
    service = rendered["services"][transport_name]

    assert service["labels"][node_stack.CONFIG_DIGEST_LABEL] == node_stack.digest_of(A_CONFIG)
