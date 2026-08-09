"""Shared plumbing for the acceptance scenarios.

WHAT: how a scenario reaches the booted e2e stack, and how it reads a
      container's logs.
WHY:  every scenario needs the same two things, and both have a trap in them.
      The address is one: the stack publishes to the ENGINE's loopback, and the
      engine is not always the machine running pytest (the fleet drives an
      isolated dind engine), so the host is configuration, never a constant.
      The compose project is the other: `docker compose logs` without
      ``-p hashi-e2e`` reads the DEV stack and cheerfully reports nothing.
HOW:  ``make test-e2e`` boots nothing — the stack must already be up
      (``make e2e-up``). Scenarios talk to it over real HTTP and over the
      docker CLI; nothing here imports the application. Helpers are exposed as
      FIXTURES rather than imported from this module, because pytest runs with
      ``--import-mode=importlib`` and a plain ``from conftest import ...`` is
      not reliable under it.

Boundary (from .e2e/profile.yml — the honesty section):
  real:     control, postgres, caddy
  stubbed:  none
  external: none
  NOT covered: no real node, no tunnel, no Russian network. Charter criterion 1
  ("survives a whitelist shutdown") is not provable here and must never be
  reported as covered by this suite.
"""

import os
import pathlib
import subprocess
from collections.abc import Callable

import httpx
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Defaults match the Makefile's own (E2E_API_PORT ?= 54200, E2E_API_HOST ?=
# 127.0.0.1) so that running pytest directly and running `make test-e2e` reach
# the same stack rather than disagreeing silently.
API_HOST = os.environ.get("E2E_API_HOST", "127.0.0.1")
API_PORT = os.environ.get("E2E_API_PORT", "54200")
PROJECT = os.environ.get("E2E_PROJECT", "hashi-e2e")

CONTROL = "control"
CADDY = "caddy"
DB = "db"

# The same three files `make e2e-up` uses. Dropping the e2e overlay here would
# make `compose exec` address a different stack than the one that is running.
COMPOSE = [
    "docker", "compose",
    # BOTH env files, in the Makefile's order — see deploy/e2e.env. With only `.env`
    # here, every scenario that shells out to compose fails on interpolation while the
    # stack it is talking to is up and healthy, which reads as "the stack is broken".
    "--env-file", ".env", "--env-file", "deploy/e2e.env",
    "-p", PROJECT,
    "-f", "deploy/docker-compose.yml",
    "-f", "deploy/docker-compose.dev.yml",
    "-f", "deploy/docker-compose.e2e.yml",
]


def _compose(*args: str) -> subprocess.CompletedProcess:
    """Run a docker compose command against the e2e project, never the dev one."""
    return subprocess.run(
        [*COMPOSE, *args], capture_output=True, text=True, timeout=180, cwd=REPO_ROOT
    )


def _container_id(service: str) -> str:
    """The running container for a compose service, or fail the scenario."""
    running = _compose("ps", "-q", service).stdout.split()
    assert running, f"no running container for service {service!r} — is the e2e stack up?"
    return running[0]


def _logs_of(service: str) -> str:
    """Everything the service has written to stdout+stderr since it booted.

    Deliberately the container log rather than a log file: the container log is
    what actually lands on the operator's disk and in `docker logs`, so it is
    where a leaked subscription token would really end up.
    """
    result = subprocess.run(
        ["docker", "logs", _container_id(service)],
        capture_output=True, text=True, timeout=60,
    )
    return result.stdout + result.stderr


def _exec_in(service: str, *argv: str) -> subprocess.CompletedProcess:
    """Run a command inside a service's container."""
    return subprocess.run(
        ["docker", "exec", _container_id(service), *argv],
        capture_output=True, text=True, timeout=60,
    )


@pytest.fixture(scope="session")
def base_url() -> str:
    """The control plane as a client outside the stack sees it."""
    return f"http://{API_HOST}:{API_PORT}"


@pytest.fixture
async def client(base_url: str):
    """An HTTP client that does not follow redirects — a 3xx is a result here.

    The timeout is raised well above httpx's 5s default on purpose. Several operator
    actions attempt SSH to the stub nodes in this stack — revocation re-pushes every
    node the friend was on, and apply pushes the one it was called for — and those
    attempts have to run out their own connect timeout before the request can answer.
    At the default, such a scenario fails as a ``ReadTimeout``, which reads as "the
    stack is broken" rather than as "the operator waited": the same failure the
    Makefile's own comments warn about elsewhere. Slow is the correct answer here, and
    it gets slower as a run adds nodes.
    """
    async with httpx.AsyncClient(
        base_url=base_url, follow_redirects=False, timeout=60.0
    ) as c:
        yield c


@pytest.fixture(scope="session")
def compose() -> Callable[..., subprocess.CompletedProcess]:
    return _compose


@pytest.fixture(scope="session")
def logs_of() -> Callable[[str], str]:
    return _logs_of


@pytest.fixture(scope="session")
def exec_in() -> Callable[..., subprocess.CompletedProcess]:
    return _exec_in
