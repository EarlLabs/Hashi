"""Does the daemon actually accept what we render?

WHAT: runs Xray's own config checker over every transport's rendered server config.
WHY:  this is the validation half of the charter's fourth success criterion, and
      the edge rulebook is blunt about why our own opinion does not count: "a
      config we believe is valid is not a config the daemon accepts". Every other
      test in this directory asserts what we *think* the config means. This one
      asks the program that will run it.
HOW:  needs the upstream binary, fetched by ``scripts/fetch-upstream-checkers.sh``
      (backlog item 1a). When it is absent these tests SKIP LOUDLY — the reason
      string says the criterion is unproven and names the remedy. A skip that
      reads as green is how a broken config reaches a node, so the skip is never
      silent, and ``tests/e2e/edge/`` additionally refuses to accept a suite where
      it has never once run for real.

      Validation goes through ``edge.checker``, which is the same code path the
      apply pipeline in `control` uses before pushing to a node — so a green run
      here is evidence about the real gate, not about a test-only reimplementation.
"""

import json

import pytest

from edge.checker import awg_quick_binary, validate, xray_binary
from edge.registry import ConfigFormat, discover, profile

INSTALLED = sorted(discover())
PARAMS_FIXTURE = {
    "vless-reality": "reality_params",
    "vless-ws-tls": "ws_params",
    "amneziawg": "awg_params",
}
CREDENTIALS_FIXTURE = {
    "vless-reality": "credentials",
    "vless-ws-tls": "credentials",
    "amneziawg": "awg_credentials",
}


def checkable_params(name: str, request, tmp_path) -> dict[str, object]:
    """The transport's parameters, made loadable by the upstream checker.

    ``checkable_params_for`` comes from conftest as a fixture rather than an
    import: pytest runs with ``--import-mode=importlib``, under which
    ``from .conftest import ...`` is not reliable.
    """
    materialise = request.getfixturevalue("checkable_params_for")
    return materialise(request.getfixturevalue(PARAMS_FIXTURE[name]), tmp_path)

# One checker per config format, resolved the same way the production code resolves it.
CHECKERS = {
    ConfigFormat.XRAY_JSON: ("xray", xray_binary),
    ConfigFormat.WG_QUICK: ("awg-quick", awg_quick_binary),
}


def require_checker_for(name: str) -> None:
    """Skip LOUDLY when this transport's checker is not installed.

    Per-format rather than one blanket skip: with only Xray present, the two VLESS
    transports are genuinely validated and AmneziaWG genuinely is not, and a single
    marker would either fail the run or hide which of the two happened.

    The rulebook is explicit that a validation test which silently passes is how a
    broken config reaches a node, so the reason names the unproven criterion and the
    remedy rather than saying "missing binary".
    """
    tool, locate = CHECKERS[discover()[name].config_format]
    if locate() is None:
        pytest.skip(
            f"{tool} not present — the VALIDATION half of charter criterion 4 is NOT "
            f"proven for {name} by this run. Install it: "
            "scripts/fetch-upstream-checkers.sh"
        )


@pytest.mark.parametrize("name", INSTALLED)
def test_upstream_accepts_the_rendered_server_config(
    name: str, node, request, tmp_path
) -> None:
    """The daemon that will run each config accepts it, with clients on it."""
    require_checker_for(name)
    transport = profile(name)
    validated = transport.validate(checkable_params(name, request, tmp_path))
    clients = request.getfixturevalue(CREDENTIALS_FIXTURE[name])
    rendered = transport.profile.render_server(node, validated, clients)

    result = validate(rendered, config_format=transport.meta.config_format)
    assert result.ok, f"{name}: xray rejected the rendered config\n{result.output}"


@pytest.mark.parametrize("name", INSTALLED)
def test_upstream_accepts_a_config_with_no_clients(name: str, node, request, tmp_path) -> None:
    """A node whose last friend was just revoked must still be a valid node.

    Otherwise the final revocation produces a config the daemon refuses, the node
    fails to restart, and the symptom is an outage for everyone still on it.
    """
    require_checker_for(name)
    transport = profile(name)
    validated = transport.validate(checkable_params(name, request, tmp_path))
    result = validate(
        transport.profile.render_server(node, validated, ()),
        config_format=transport.meta.config_format,
    )
    assert result.ok, f"{name}: xray rejected an empty-client config\n{result.output}"


def test_the_checker_actually_rejects_something() -> None:
    """Proof that the checker is checking — the red half of this file.

    Without this, a broken `xray` binary that exits 0 on everything would make
    every test above pass and mean nothing. The rulebook's red-first rule applied
    to the tool rather than to the product.
    """
    if xray_binary() is None:
        pytest.skip("xray not present, so the checker itself cannot be checked")
    broken = json.dumps({"inbounds": [{"protocol": "no-such-protocol", "port": 1}]})
    result = validate(broken, config_format=ConfigFormat.XRAY_JSON)
    assert result.available
    assert not result.ok, (
        "xray accepted a config with an unknown protocol — the checker is not "
        "checking, so every other result in this file is meaningless"
    )


def test_absent_checker_is_never_reported_as_success() -> None:
    """``CheckResult`` must not let "could not ask" collapse into "yes".

    Runs with or without the binary, because it is about the type rather than the
    tool: the apply path in `control` decides whether to push a config based on
    this value, and a falsy-when-unavailable result is what stops an unvalidated
    config reaching a node.
    """
    from edge.checker import CheckResult

    unavailable = CheckResult(available=False, ok=False)
    assert not unavailable
    assert not CheckResult(available=True, ok=False)
    assert CheckResult(available=True, ok=True)
