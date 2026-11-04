"""The stack, as an operator's `docker compose ps` sees it.

WHAT: every service in the booted e2e stack reports healthy.
WHY:  tests/infra/test_compose.py reads the compose files and proves what they
      SAY. This proves what they DO, and the gap between the two is where the
      expensive failures live — a bind mount that resolves on the daemon rather
      than in this checkout, a healthcheck command missing from the image, a
      dependency ordering that only breaks on a cold volume.
HOW:  asks compose for the state of the project named by E2E_PROJECT. Boots
      nothing: an unbooted stack is a failed scenario, not something to fix by
      starting one mid-test.

Boundary: real control + postgres + caddy, plus the fake Telegram the e2e overlay runs
beside them (M37.4) — stubbed, and part of every stand — and the add-user bot as its own
container (M39), switched on for the stand behind the `telegram-bot` profile. Nothing external.
"""

import json


def services(compose) -> dict[str, dict]:
    result = compose("ps", "--format", "json")
    assert result.returncode == 0, f"compose ps failed:\n{result.stderr}"
    # compose emits either one JSON object per line or a single JSON array,
    # depending on version. Accept both rather than pinning a compose release.
    text = result.stdout.strip()
    assert text, "the e2e stack is not up — run: make e2e-up"
    parsed = json.loads(text) if text.startswith("[") else [
        json.loads(line) for line in text.splitlines() if line.strip()
    ]
    return {entry["Service"]: entry for entry in parsed}


def test_every_service_is_running(compose) -> None:
    """Caddy is the one that used to be missing here: its config arrived as a
    bind mount, which exists only on the machine holding this checkout."""
    state = services(compose)
    assert set(state) == {"control", "db", "caddy", "telegram", "telegram-bot"}, (
        f"unexpected set of running services: {sorted(state)}"
    )
    stopped = {name: entry["State"] for name, entry in state.items()
               if entry["State"] != "running"}
    assert stopped == {}, f"services not running: {stopped}"


def test_every_service_reports_healthy(compose) -> None:
    """A container that is up but unhealthy is the failure mode `ps` hides."""
    unhealthy = {
        name: entry.get("Health")
        for name, entry in services(compose).items()
        if entry.get("Health") not in ("healthy", "")
    }
    assert unhealthy == {}, f"unhealthy services: {unhealthy}"


def test_the_database_is_actually_reachable_from_the_control_plane(compose) -> None:
    """`depends_on: service_healthy` is a promise about ordering, not about
    connectivity — the two diverge the moment a network or a name changes."""
    result = compose("exec", "-T", "control", "python", "-c",
                     "import socket; socket.create_connection(('db', 5432), timeout=5)")
    assert result.returncode == 0, (
        f"the control plane cannot open a socket to db:5432:\n{result.stderr}"
    )
