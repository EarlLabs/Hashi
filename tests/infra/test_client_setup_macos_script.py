"""The macOS client setup script — run, not read.

WHAT: runs ``scripts/client-setup-macos.sh`` in its two modes that change nothing on the
      machine (``--print-runner`` and ``--bundle``), then runs the runner it would install
      in its one mode that needs neither macOS nor sing-box (``--config-from``), and checks
      the sing-box config that comes out.
WHY:  installing needs a Mac with Happ on it, which CI is not; but everything the runner
      decides — which routes go into the auto group, which hosts bypass the tunnel, which
      suffixes go direct — is decided in ``build_config``, and that runs anywhere bash,
      base64 and sed do. A test that only read the source would miss the one thing that
      matters: whether the JSON sing-box receives says what the header promises.

      Every address below is a reserved test name (``.invalid``, TEST-NET-3), because the
      repository holds no fleet address — CLAUDE.md's hard rule.
HOW:  each scenario runs the script with no TTY and closed stdin, in a temporary HOME.
"""

import base64
import json
import os
import pathlib
import re
import stat
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "client-setup-macos.sh"

SUBSCRIPTION = "https://sub.example.invalid/sub/TOKEN-for-tests-only"

# Three routes as the delivery endpoint writes them: two on one entry host (two ports), one
# on a leaf registered by IP. The fragment is the node's display name.
ROUTES = [
    "vless://11111111-1111-1111-1111-111111111111@entry.example.invalid:8443"
    "?encryption=none&flow=xtls-rprx-vision&security=reality&type=tcp"
    "&sni=decoy-a.invalid&fp=chrome&pbk=PUBKEYAAAA&sid=ab12#Somewhere%20%C2%B7%20entry-one",
    "vless://11111111-1111-1111-1111-111111111111@203.0.113.7:443"
    "?encryption=none&flow=xtls-rprx-vision&security=reality&type=tcp"
    "&sni=decoy-b.invalid&fp=firefox&pbk=PUBKEYBBBB&sid=cd34#Elsewhere%20%C2%B7%20leaf-two",
    "vless://11111111-1111-1111-1111-111111111111@entry.example.invalid:49443"
    "?encryption=none&flow=xtls-rprx-vision&security=reality&type=tcp"
    "&sni=decoy-c.invalid&fp=chrome&pbk=PUBKEYCCCC&sid=ef56#Somewhere%20%C2%B7%20entry-one",
]


def run(
    *args: str, script: pathlib.Path = SCRIPT, home: pathlib.Path
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)},
    )


def runner_text(tmp_path: pathlib.Path, *extra: str) -> str:
    result = run("--subscription", SUBSCRIPTION, *extra, "--print-runner", home=tmp_path)
    assert result.returncode == 0, result.stderr
    return result.stdout


def built_config(tmp_path: pathlib.Path, *extra: str) -> dict:
    """The config the installed runner would hand sing-box for ``ROUTES``."""
    runner = tmp_path / "hashi-vpn.sh"
    runner.write_text(runner_text(tmp_path, *extra))
    sub = tmp_path / "subscription.b64"
    # Unpadded, as the endpoint may serve it: the runner pads it itself.
    sub.write_text(base64.b64encode("\n".join(ROUTES).encode()).decode().rstrip("="))
    result = subprocess.run(
        ["bash", str(runner), "--config-from", str(sub)],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def rules_with(config: dict, section: str, key: str) -> list[dict]:
    return [rule for rule in config[section]["rules"] if key in rule]


def test_the_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_it_fails_the_whole_run_on_any_error() -> None:
    assert re.search(r"^set -euo pipefail$", SCRIPT.read_text(), re.M)


def test_the_repository_copy_holds_no_subscription_and_no_country() -> None:
    """A bundle fills these two lines; the committed file must leave both empty."""
    text = SCRIPT.read_text()
    assert re.search(r'^BUNDLED_SUBSCRIPTION=""$', text, re.M)
    assert re.search(r'^BUNDLED_DIRECT_SUFFIXES=""$', text, re.M)


def test_an_unknown_argument_exits_two(tmp_path) -> None:
    assert run("--frobnicate", home=tmp_path).returncode == 2


def test_the_subscription_is_never_defaulted(tmp_path) -> None:
    result = run("--print-runner", home=tmp_path)
    assert result.returncode == 1
    assert "--subscription" in result.stderr


@pytest.mark.parametrize("bad", ["http://sub.example.invalid/sub/x", "sub.example.invalid/sub/x",
                                 'https://sub.example.invalid/sub/x"y'])
def test_a_malformed_subscription_is_refused(tmp_path, bad: str) -> None:
    assert run("--subscription", bad, "--print-runner", home=tmp_path).returncode == 1


@pytest.mark.parametrize("bad", ["RU", ".example", "exa mple", "ex/ample"])
def test_a_malformed_direct_suffix_is_refused(tmp_path, bad: str) -> None:
    result = run(
        "--subscription", SUBSCRIPTION, "--direct-suffix", bad, "--print-runner", home=tmp_path
    )
    assert result.returncode == 1


def test_the_runner_carries_the_subscription_and_no_placeholder(tmp_path) -> None:
    text = runner_text(tmp_path)
    assert f'SUB_URL="{SUBSCRIPTION}"' in text
    assert "__SUBSCRIPTION__" not in text and "__DIRECT_SUFFIXES__" not in text


def test_every_route_in_the_subscription_goes_into_the_auto_group(tmp_path) -> None:
    config = built_config(tmp_path)
    auto = next(o for o in config["outbounds"] if o["tag"] == "auto")
    assert auto["type"] == "urltest"
    assert auto["outbounds"] == ["entry-one:8443", "leaf-two:443", "entry-one:49443"]
    assert config["route"]["final"] == "auto"


def test_each_route_keeps_its_own_server_and_disguise(tmp_path) -> None:
    config = built_config(tmp_path)
    leaf = next(o for o in config["outbounds"] if o["tag"] == "leaf-two:443")
    assert (leaf["server"], leaf["server_port"]) == ("203.0.113.7", 443)
    assert leaf["flow"] == "xtls-rprx-vision"
    assert leaf["tls"]["server_name"] == "decoy-b.invalid"
    assert leaf["tls"]["utls"]["fingerprint"] == "firefox"
    assert leaf["tls"]["reality"] == {
        "enabled": True, "public_key": "PUBKEYBBBB", "short_id": "cd34"
    }


def test_hashis_own_hosts_bypass_the_tunnel(tmp_path) -> None:
    """The subscription host and every route host — each once, IPs as /32s."""
    config = built_config(tmp_path)
    (by_name,) = [r for r in rules_with(config, "route", "domain") if r["outbound"] == "direct"]
    assert by_name["domain"] == ["sub.example.invalid", "entry.example.invalid"]
    (by_ip,) = rules_with(config, "route", "ip_cidr")
    assert by_ip == {"ip_cidr": ["203.0.113.7/32"], "outbound": "direct"}
    (dns_by_name,) = rules_with(config, "dns", "domain")
    assert dns_by_name["server"] == "local"


def test_nothing_goes_direct_by_suffix_unless_asked(tmp_path) -> None:
    config = built_config(tmp_path)
    assert rules_with(config, "route", "domain_suffix") == []
    assert rules_with(config, "dns", "domain_suffix") == []


def test_direct_suffixes_reach_both_dns_and_routing(tmp_path) -> None:
    config = built_config(tmp_path, "--direct-suffix", "example", "--direct-suffix", "xn--example")
    (route,) = rules_with(config, "route", "domain_suffix")
    (dns,) = rules_with(config, "dns", "domain_suffix")
    assert route == {"domain_suffix": ["example", "xn--example"], "outbound": "direct"}
    assert dns == {"domain_suffix": ["example", "xn--example"], "server": "local"}


def test_a_bundle_is_private_and_runs_with_no_arguments(tmp_path) -> None:
    bundle = tmp_path / "setup-for-someone.sh"
    result = run(
        "--subscription", SUBSCRIPTION, "--direct-suffix", "example", "--bundle", str(bundle),
        home=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o600
    assert f'BUNDLED_SUBSCRIPTION="{SUBSCRIPTION}"' in bundle.read_text()
    printed = run("--print-runner", script=bundle, home=tmp_path)
    assert printed.returncode == 0, printed.stderr
    assert f'SUB_URL="{SUBSCRIPTION}"' in printed.stdout
    assert 'DIRECT_SUFFIXES="example"' in printed.stdout


def test_a_bundle_is_never_written_inside_the_repository(tmp_path) -> None:
    target = REPO / "scripts" / "bundle-that-must-not-exist.sh"
    result = run("--subscription", SUBSCRIPTION, "--bundle", str(target), home=tmp_path)
    assert result.returncode == 1
    assert not target.exists()
