"""Golden-file tests: the exact bytes each transport renders.

WHAT: a fixed node plus fixed parameters plus fixed credentials, compared byte for
      byte against a checked-in file.
WHY:  every other test here asserts a property ("the port is right", "the access
      log is off"). This one asserts the whole artefact, which is the only way to
      notice the change nobody thought to write a property for — a reordered key,
      a dropped setting, a template that started emitting a default. A diff in a
      golden file is a deliberate act, reviewed as such (edge rulebook, Testing).
HOW:  ``UPDATE_GOLDEN=1 pytest tests/edge/test_golden_configs.py`` rewrites them.
      That escape hatch is for when the change IS intended; it prints what it
      wrote so an unintended rewrite is visible in the diff rather than silent.
"""

import os
import pathlib

import pytest

from edge.registry import discover, profile

GOLDEN = pathlib.Path(__file__).parent / "golden"
INSTALLED = sorted(discover())

PARAMS_FIXTURE = {"vless-reality": "reality_params", "vless-ws-tls": "ws_params"}


@pytest.mark.parametrize("name", INSTALLED)
def test_server_config_matches_its_golden_file(name: str, node, credentials, request) -> None:
    """The node's whole config file, byte for byte."""
    transport = profile(name)
    validated = transport.validate(request.getfixturevalue(PARAMS_FIXTURE[name]))
    rendered = transport.profile.render_server(node, validated, credentials)

    path = GOLDEN / f"{name}-server.json"
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(rendered)
        pytest.skip(f"golden file rewritten: {path.name} ({len(rendered)} bytes)")

    assert path.is_file(), (
        f"no golden file for {name} — run: UPDATE_GOLDEN=1 pytest {__file__}"
    )
    assert rendered == path.read_text(), (
        f"{name}: rendered server config differs from {path.name}. If the change is "
        "intended, rewrite with UPDATE_GOLDEN=1 and review the diff as a decision."
    )


@pytest.mark.parametrize("name", INSTALLED)
def test_client_entry_matches_its_golden_file(name: str, node, credentials, request) -> None:
    """One friend's subscription entry, byte for byte.

    Pinned separately from the server config because this string goes to a
    friend's device: a change here is a change to the only artefact they hold, and
    the charter says that must never require them to re-import anything.
    """
    transport = profile(name)
    validated = transport.validate(request.getfixturevalue(PARAMS_FIXTURE[name]))
    entry = transport.profile.render_client(node, validated, credentials[0])
    rendered = f"{entry.entry}\n"

    path = GOLDEN / f"{name}-client.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(rendered)
        pytest.skip(f"golden file rewritten: {path.name}")

    assert path.is_file(), (
        f"no golden file for {name} — run: UPDATE_GOLDEN=1 pytest {__file__}"
    )
    assert rendered == path.read_text()
