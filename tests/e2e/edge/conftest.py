"""Plumbing for the scenarios that RUN a data plane on a real engine — M5.

WHAT: how a scenario starts a node's data plane here instead of on a node: a real
      rendered config, the real rendered compose file, a real ``docker compose up -d``,
      and the real ``edge`` code that asks a node what it is running.
WHY:  M5 exists because nothing in this repository ever started what it renders. Every
      check that existed asked a question one step short of the one that matters — the
      tag resolves, the argv is intact, the command's binary is present — and M1, M2 and
      M3 each survived all of them and failed on a rented host. So these scenarios pay
      the price of a real engine, and the plumbing that makes them affordable lives here
      rather than in four copies.
HOW:  the configs are the GOLDEN files ``tests/edge/golden/<transport>-server.<ext>``.
      That is deliberate and it is the cheapest honest option: a golden file is the real
      renderer's real output, already reviewed as a diff, and reading one needs none of
      the transport-specific fixtures that live in ``tests/edge/conftest.py`` and cannot
      be imported across directories under ``--import-mode=importlib``. A transport
      added later brings a golden file by the edge rulebook's own rule, so it is covered
      by arriving; one that somehow has none fails here, loudly, rather than being
      skipped.

Boundary — what this plumbing changes about a node, and therefore what none of the
scenarios using it can prove:

  * **The containers get their own network namespace, not the host's.** A node runs its
    data plane under ``network_mode: host`` so a daemon listens on the node's real
    interface. Running that here would create interfaces and insert iptables rules on
    whatever machine the suite is on, which is not a thing a test may do. So nothing
    here proves a daemon is REACHABLE from outside the container, that its port is free
    on a node, or that two transports do not collide in one namespace.
  * **The bind-mount source is this test's directory, not ``/opt/hashi/conf``.** The
    path INSIDE the container is the node's own, unchanged, so the daemon still loads
    the file at the path the compose file names.

Both are expressed as a compose OVERRIDE file rather than by editing what
``render_compose`` produced: the file under test stays byte-identical to the one an
apply would place on a node, and the two deviations are one readable diff.
"""

import datetime
import os
import pathlib
import re
import subprocess
import uuid
from collections.abc import Mapping

import pytest
import yaml

from edge.bootstrap import node_stack
from edge.bootstrap.ssh import CommandResult
from edge.registry import discover

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = REPO_ROOT / "tests" / "edge" / "golden"

# The golden file's extension follows the config FORMAT — the same table
# ``tests/edge/test_golden_configs.py`` writes them with. Read from ``EXTENSION`` in
# ``node_stack`` rather than copied, so the two cannot disagree about where a new
# format's golden file lives.
EXTENSION = node_stack.EXTENSION

# An absolute path, as it appears in a rendered config. Used to find the files a config
# names that the CONTROL PLANE places by another route than the config directory — a
# TLS certificate and its key, today. Anchored on a non-word, non-slash character so
# that a prefix length (``10.44.0.0/24``) and a path fragment inside a comment
# (``edge/egress.py``) are not mistaken for one.
ABSOLUTE_PATH = re.compile(r"(?<![\w/])(/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)")


def run(
    arguments: list[str],
    timeout: int = 600,
    env: dict | None = None,
    cwd: pathlib.Path | None = None,
):
    """One external command, captured. Never shell — every argument is passed through."""
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=None if env is None else {**os.environ, **env},
        cwd=cwd,
    )


def golden_config(transport_name: str) -> str:
    """One transport's rendered SERVER config, as the golden files hold it.

    A real config from the real renderer, frozen and reviewed. The scenarios that run it
    need a config a daemon will actually accept, and this is the only source of one that
    does not need the transport's own parameter fixtures.
    """
    meta = discover()[transport_name]
    path = GOLDEN / f"{transport_name}-server.{EXTENSION[meta.config_format]}"
    assert path.exists(), (
        f"there is no golden server config for {transport_name!r} at {path}, so this "
        "scenario has nothing real to start. Record one:\n"
        "    UPDATE_GOLDEN=1 pytest tests/edge/test_golden_configs.py"
    )
    return path.read_text()


def files_the_config_names(config: str) -> list[str]:
    """Absolute paths a rendered config expects to find, other than its own directory.

    A transport may reference material the node holds outside the config directory — a
    certificate and its key (``edge/checker.py`` says so: the upstream checker does not
    parse a config, it OPENS what the config names). A daemon handed such a config with
    the file absent refuses to start, which here would read as "the data plane cannot
    run" when what is missing is the node's other half.

    Derived from the config TEXT rather than from a list of parameter names, so a
    transport added later with a file-backed parameter is handled by arriving. Comment
    lines are dropped first: every template in this project explains itself at length,
    and those explanations cite paths in this repository.
    """
    body = "\n".join(
        line for line in config.splitlines() if not line.lstrip().startswith("#")
    )
    return sorted(
        {
            found
            for found in ABSOLUTE_PATH.findall(body)
            if not found.startswith(node_stack.CONFIG_DIR)
        }
    )


def throwaway_certificate() -> bytes:
    """A self-signed certificate and its key, in ONE PEM file. Thrown away with the test.

    One file rather than two because what is known about a path found in a config is
    only that something opens it — not whether it wants the certificate or the key. A
    PEM bundle carrying both satisfies either reader, which keeps
    ``files_the_config_names`` free of any knowledge about which parameter is which.

    Worthless by construction: generated per run, never written into the repository,
    never presented to anything but a parser that has to open something to start.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # A reserved example name (RFC 2606), like every fixture in this zone.
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "front.example.com")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(2100, 1, 1, tzinfo=datetime.UTC))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


class LocalNode:
    """A stand-in for ``NodeConnection`` that runs the node's commands on this machine.

    Exists so a scenario can call the REAL ``edge`` functions — ``loaded_digests`` above
    all — against a real engine, instead of a fake that models what Docker would answer.
    Modelling it is exactly what M1's unit test does and exactly what it says it cannot
    prove.

    ONE substitution, and it is the only thing this class invents: the directory the
    command runs in. A node's stack lives at ``node_stack.NODE_ROOT``; here it lives in
    the test's own directory, because creating ``/opt/hashi`` on a developer's machine
    is not a test's business. The docker pipeline, its format string and the parsing of
    its output are untouched and are the product's own.
    """

    learned_host_key = None

    def __init__(self, directory: pathlib.Path, project: str) -> None:
        self.directory = directory
        self.project = project

    async def run(self, command: str, *, check: bool = True) -> CommandResult:
        relocated = command.replace(f"cd {node_stack.NODE_ROOT}", f"cd {self.directory}")
        result = subprocess.run(
            ["/bin/sh", "-c", relocated],
            capture_output=True,
            text=True,
            timeout=180,
            # The project name a compose command without ``-p`` would otherwise take from
            # the rendered file's own ``name:``. Set so that a scenario can never address
            # — or tear down — a stack somebody else on this machine is running.
            env={**os.environ, "COMPOSE_PROJECT_NAME": self.project},
        )
        if check:
            assert result.returncode == 0, f"{command}\n{result.stderr}"
        return CommandResult(
            exit_status=result.returncode, stdout=result.stdout, stderr=result.stderr
        )

    async def read_file(self, path: str) -> str | None:
        """One config file, as ``health.probe`` reads it off a node.

        The same single substitution as ``run``: the node's config directory is this
        test's. Nothing else about the answer is invented — the file really is the one
        the container has mounted, so drift and staleness are read from the same bytes
        the daemon was given.
        """
        local = self.directory / "conf" / pathlib.PurePosixPath(path).name
        return local.read_text() if local.exists() else None


class DataPlaneStack:
    """One node's data plane, rendered by ``edge`` and run by a real docker compose.

    The verbs are the node's own: place the configs, place the compose file, ``up -d``.
    What is added is the reading — a scenario needs the container's id, its labels and
    its start time, and none of those are things the product asks a node for.
    """

    def __init__(self, directory: pathlib.Path) -> None:
        self.directory = directory
        self.config_dir = directory / "conf"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Unique per stack: two scenarios running at once must not share containers, and
        # neither may adopt a real node's ``hashi-node`` project on the same machine.
        self.project = f"hashi-m5-{uuid.uuid4().hex[:12]}"
        self.compose = ["docker", "compose", "-p", self.project]
        self.services: list[dict] = []

    def place(self, configs: Mapping[str, str]) -> None:
        """Write the configs and the compose file, exactly as an apply would.

        Order matters and it is M1's order: the config is on disk BEFORE the compose file
        that names its digest, and long before anything starts. The field measurement
        that opened M1 had them the other way round by eight minutes.
        """
        self.services = node_stack.services_for(configs)
        for service in self.services:
            path = self.config_dir / pathlib.PurePosixPath(service["config_path"]).name
            path.write_text(configs[service["name"]])
            for named in files_the_config_names(configs[service["name"]]):
                # Placed beside the configs and mounted at the path the config names —
                # see ``files_the_config_names`` for what these are and why one file
                # serves both readers.
                (self.config_dir / pathlib.PurePosixPath(named).name).write_bytes(
                    throwaway_certificate()
                )
        (self.directory / "docker-compose.yml").write_text(
            node_stack.render_compose(transports=self.services)
        )
        (self.directory / "docker-compose.override.yml").write_text(self._override(configs))

    def _override(self, configs: Mapping[str, str]) -> str:
        """The two host-isolation deviations, as a compose override file.

        See this module's docstring for both and for what they cost. Written as YAML
        through the parser rather than as text, so a service name with a character YAML
        cares about cannot produce a file that means something else.
        """
        services: dict[str, dict] = {}
        for service in self.services:
            volumes = [f"{self.config_dir}:{node_stack.CONFIG_DIR}:ro"]
            for named in files_the_config_names(configs[service["name"]]):
                source = self.config_dir / pathlib.PurePosixPath(named).name
                volumes.append(f"{source}:{named}:ro")
            services[service["name"]] = {"network_mode": "none", "volumes": volumes}
        return yaml.safe_dump({"services": services}, sort_keys=True)

    def up(self) -> subprocess.CompletedProcess:
        """The node's own verb, run by a real engine (``node_stack.restart``)."""
        result = run(
            [*self.compose, "up", "-d", "--remove-orphans"], timeout=900, cwd=self.directory
        )
        assert result.returncode == 0, (
            "a real docker compose refused the compose file this project renders:\n"
            f"{(result.stderr or result.stdout).strip()[:2000]}"
        )
        return result

    def container_id(self, transport_name: str) -> str:
        """The container currently serving one transport, or a failure naming it."""
        result = run([*self.compose, "ps", "-q", transport_name], timeout=120, cwd=self.directory)
        container = result.stdout.split()
        assert container, (
            f"no container for {transport_name!r} — it never started, or it is gone.\n"
            f"{self.logs(transport_name)[-2000:]}"
        )
        return container[0]

    def inspect(self, container: str, template: str) -> str:
        result = run(["docker", "inspect", "--format", template, container], timeout=120)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def logs(self, transport_name: str) -> str:
        """Everything the container wrote, for a failure message that says why."""
        result = run(
            [*self.compose, "logs", "--no-color", transport_name], timeout=120, cwd=self.directory
        )
        return result.stdout + result.stderr

    def node(self) -> LocalNode:
        """This stack, as the control plane's own code would address a node."""
        return LocalNode(self.directory, self.project)

    def down(self) -> None:
        run(
            [*self.compose, "down", "--remove-orphans", "-t", "10"],
            timeout=300,
            cwd=self.directory,
        )


@pytest.fixture(scope="session")
def engine() -> str:
    """A real docker engine, or a failure that says the scenario needs one.

    Not a skip. Every scenario in this file's directory exists because the offline suite
    cannot answer the question, so an engine that is absent means the answer was not
    obtained — and a green run that quietly answered nothing is the exact failure M5 was
    opened to end.
    """
    result = run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=120)
    assert result.returncode == 0, (
        "these scenarios run a real data plane and there is no docker engine here:\n"
        f"{result.stderr.strip()[:500]}"
    )
    return result.stdout.strip()


@pytest.fixture(scope="session")
def golden_server_config():
    """Look up one transport's real rendered server config — see ``golden_config``.

    A fixture rather than an import because pytest runs with ``--import-mode=importlib``,
    under which importing across test modules is not reliable. Same reasoning, and same
    shape, as ``transport_fixture`` in ``tests/edge/conftest.py``.
    """
    return golden_config


@pytest.fixture(scope="session")
def material_a_config_names():
    """Place whatever a rendered config OPENS, and say where each file must be mounted.

    The other half of ``files_the_config_names``: that one says which paths a config
    expects to find, this one puts a throwaway file at each and hands back the ``-v``
    arguments that mount them where the config looks. A scenario starting a daemon by
    hand needs both, and ``DataPlaneStack`` — which does the same two things for a
    scenario starting one through compose — is no use to it.

    A fixture rather than an import for the reason ``golden_server_config`` gives: pytest
    runs with ``--import-mode=importlib``, under which importing across test modules is
    not reliable.
    """

    def place(config: str, directory: pathlib.Path) -> list[str]:
        mounts = []
        for named in files_the_config_names(config):
            source = directory / pathlib.PurePosixPath(named).name
            source.write_bytes(throwaway_certificate())
            mounts.append(f"{source}:{named}:ro")
        return mounts

    return place


@pytest.fixture(scope="module")
def data_plane_stack(engine, tmp_path_factory):
    """A factory for node data-plane stacks, torn down whatever the test does.

    A factory rather than one stack because M5.3 needs to place a second configuration
    over the first, and a fixture that had already started one would decide for it.

    Module-scoped so a scenario can bring one stack up and then ask several questions of
    it: an ``up -d`` of every installed transport is the expensive part of these runs,
    and asking it once per assertion would multiply the whole suite's cost by four.
    """
    stacks: list[DataPlaneStack] = []

    def make() -> DataPlaneStack:
        directory = tmp_path_factory.mktemp("node")
        stack = DataPlaneStack(directory)
        stacks.append(stack)
        return stack

    yield make

    for stack in stacks:
        stack.down()
