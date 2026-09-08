"""The acceptance driver's pure half.

WHAT: target parsing, URL rewriting, tree truncation and the budget.
WHY:  everything else in drive.py needs a browser and a stand, so it is proven by
      being used. These four are plain data, they are what the agent's every call
      passes through, and each of them has a failure that looks like something
      else: a mis-parsed target reads as "the button was not there", an
      un-rewritten URL as "the panel is down", a spent budget as an agent that
      lost interest.
HOW:  imported by path — scripts/ is not a package, and making it one would put a
      test-only shim in the deployed image.
"""

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SPEC = importlib.util.spec_from_file_location("drive", ROOT / "scripts/acceptance/drive.py")
drive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(drive)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("button=add user", ("role", "button", "add user")),
        ("link=all users", ("role", "link", "all users")),
        ("textbox=nickname", ("role", "textbox", "nickname")),
        # Case and stray spaces are what a tired agent types at 3 a.m.
        ("Button = add user ", ("role", "button", "add user")),
        # A role with no name addresses the only one on the screen.
        ("dialog=", ("role", "dialog", "")),
        ("text=identified and blocked", ("locator", "text", "identified and blocked")),
        ("css=.panel .table", ("locator", "css", ".panel .table")),
        # No `=` at all: treat it as text rather than refusing.
        ("add user", ("locator", "text", "add user")),
    ],
)
def test_a_target_parses_the_way_the_snapshot_reads(target, expected) -> None:
    assert drive.parse_target(target) == expected


def test_an_unknown_kind_says_what_the_kinds_are() -> None:
    """The failure has to teach, because the agent cannot ask anyone."""
    with pytest.raises(ValueError) as raised:
        drive.parse_target("widget=save")
    message = str(raised.value)
    assert "widget" in message
    assert "button" in message and "css" in message


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("http://127.0.0.1:54200/panel/", "http://control:8000/panel/"),
        ("http://localhost:54200/sub/abc", "http://control:8000/sub/abc"),
        ("https://127.0.0.1/panel/", "http://control:8000/panel/"),
        # A path with no host is left alone, and so is a real remote address: the
        # driver must never quietly redirect a scenario somewhere else.
        ("/panel/nodes", "/panel/nodes"),
        ("http://example.test/panel/", "http://example.test/panel/"),
    ],
)
def test_a_published_address_becomes_the_in_network_one(given, expected) -> None:
    assert drive.rewrite_url(given) == expected


def test_the_token_survives_rewriting() -> None:
    """A subscription URL is a bearer credential; rewriting the host must not eat it."""
    token = "a" * 32
    assert drive.rewrite_url(f"http://127.0.0.1:54200/sub/{token}").endswith(f"/sub/{token}")


def test_a_short_tree_comes_back_whole() -> None:
    tree = "\n".join(f"line {n}" for n in range(10))
    assert drive.truncate_tree(tree, max_lines=220) == tree


def test_a_long_tree_is_cut_and_says_so() -> None:
    tree = "\n".join(f"line {n}" for n in range(500))
    cut = drive.truncate_tree(tree, max_lines=220).splitlines()
    assert len(cut) == 221
    assert cut[219] == "line 219"
    assert "280 more lines" in cut[-1]


def test_the_budget_stops_at_the_action_cap() -> None:
    budget = drive.Budget("M8", max_actions=3, minutes=60)
    for _ in range(3):
        budget.spend()
    assert budget.left == 0
    with pytest.raises(drive.BudgetSpent) as raised:
        budget.spend()
    # The message is the report's own wording, so a stopped run reads the same way
    # whoever writes it up.
    assert "could not" in str(raised.value)


def test_the_budget_stops_when_the_clock_runs_out() -> None:
    import time

    budget = drive.Budget("M9", max_actions=1000, minutes=1, started=time.time() - 120)
    with pytest.raises(drive.BudgetSpent) as raised:
        budget.spend()
    assert "minutes" in str(raised.value)


def test_a_budget_survives_a_round_trip_through_its_state_file() -> None:
    """Every verb is a new process; a counter that did not persist would never count."""
    budget = drive.Budget("M10", max_actions=10, minutes=30)
    budget.spend()
    budget.spend()
    restored = drive.Budget.from_dict(budget.to_dict())
    assert restored.used == 2
    assert restored.left == 8
    assert restored.milestone == "M10"


def test_the_compose_invocation_matches_the_makefile() -> None:
    """Both --env-file flags, the project name and all three overlays.

    Drift here is the failure that wastes a night: `docker compose exec` would
    address a DIFFERENT project, report no such service, and look like a browser
    that would not start.
    """
    makefile = (ROOT / "Makefile").read_text()
    command = " ".join(drive.compose("ps"))
    for flag in ("--env-file .env", "--env-file deploy/e2e.env"):
        assert flag in command and flag in makefile
    for overlay in ("docker-compose.yml", "docker-compose.dev.yml", "docker-compose.e2e.yml"):
        assert f"deploy/{overlay}" in command, f"{overlay} missing from the driver"
        assert f"deploy/{overlay}" in makefile
    assert "--profile browser" in command


def test_the_dev_overlays_ports_are_always_set() -> None:
    """An empty ${DEV_API_PORT} is rejected by compose and reads as a broken stand."""
    env = drive.compose_env()
    assert env["DEV_API_PORT"] and env["DEV_DB_PORT"] and env["DEV_BIND_ADDR"]


def test_the_browser_publishes_nothing() -> None:
    """The charter's port rule, asserted where it would be broken by a one-line edit.

    A published Chrome debugging port is remote code execution with a friendly
    name, and it would sit outside this project's 54100–54299 block.
    """
    import yaml

    overlay = yaml.safe_load((ROOT / "deploy/docker-compose.e2e.yml").read_text())
    browser = overlay["services"]["browser"]
    assert "ports" not in browser, "the acceptance browser must publish nothing"
    assert browser["profiles"] == ["browser"], "it must not start with an ordinary e2e run"


def test_the_browser_is_built_not_bind_mounted() -> None:
    """The lesson caddy.Dockerfile already paid for.

    A bind mount of scripts/acceptance is resolved on the DAEMON's filesystem,
    which is not this checkout whenever the engine is remote — dind, or an
    overnight run driving docker on another host. The driver would be missing or
    stale, and every verb would fail like a broken browser.
    """
    import yaml

    overlay = yaml.safe_load((ROOT / "deploy/docker-compose.e2e.yml").read_text())
    browser = overlay["services"]["browser"]
    assert "volumes" not in browser, "the driver must travel in the image, not a mount"
    assert browser["build"]["dockerfile"] == "deploy/docker/acceptance-browser.Dockerfile"

    dockerfile = (ROOT / "deploy/docker/acceptance-browser.Dockerfile").read_text()
    # The client and the bundled browsers must be the same version, or the failure
    # arrives as "executable doesn't exist", several layers from its cause.
    assert "v1.55.0-noble" in dockerfile and "playwright==1.55.0" in dockerfile
    assert "COPY scripts/acceptance/drive.py" in dockerfile
