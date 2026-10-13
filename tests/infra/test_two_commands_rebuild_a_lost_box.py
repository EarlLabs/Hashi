"""Losing the entry box costs a DNS change and two commands — M36.

WHAT: static and sliced-behaviour checks over ``scripts/restore-panel.sh``,
      ``scripts/restore-node.sh``, ``scripts/lib/remote.sh``, the Make targets that run
      them, the restore's management-tunnel skip in ``scripts/panel-bootstrap.sh`` and
      ``scripts/backup.sh``, and the runbook's cheat sheet.
WHY:  each assertion here is one of the hand steps of the 2026-10-13 rebuild, or one of the
      rules that rebuild had to keep by hand: the identity on the host only for the
      restore, the bucket credential never printed, DNS before a public CA is asked,
      a ufw that logs turned off, no second restore on a re-run, no account named after a
      dead box, no tunnel keys minted for a dead endpoint.
HOW:  read, and where a piece can run without a host, run. The commands themselves were
      walked end to end against a disposable Ubuntu container (docs/tracker/M36); a real
      host, a real DNS change and a real CA are the owner's run and are not claimed here.
"""

import os
import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
RESTORE_PANEL = SCRIPTS / "restore-panel.sh"
RESTORE_NODE = SCRIPTS / "restore-node.sh"
REMOTE_LIB = SCRIPTS / "lib" / "remote.sh"
BOOTSTRAP = SCRIPTS / "panel-bootstrap.sh"
BACKUP = SCRIPTS / "backup.sh"
MAKEFILE = REPO / "Makefile"
RUNBOOK = REPO / "docs" / "deploy" / "runbook.md"

NEW_SCRIPTS = (RESTORE_PANEL, RESTORE_NODE, REMOTE_LIB)


def code_only(text: str) -> str:
    """The script without its comments, so a rule is asserted on code and not on prose."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def panel() -> str:
    return RESTORE_PANEL.read_text()


@pytest.fixture(scope="module")
def node() -> str:
    return RESTORE_NODE.read_text()


# --- the two verbs ------------------------------------------------------------------------

@pytest.mark.parametrize("script", [RESTORE_PANEL, RESTORE_NODE])
def test_both_scripts_exist_are_executable_and_stop_on_any_error(script) -> None:
    assert os.access(script, os.X_OK), f"{script.name} is not executable"
    assert "set -euo pipefail" in script.read_text()


def test_the_owner_has_one_make_verb_for_each() -> None:
    makefile = MAKEFILE.read_text()
    pairs = (("restore-panel", "restore-panel.sh"), ("restore-node", "restore-node.sh"))
    for verb, script in pairs:
        recipe = makefile.split(f"\n{verb}:\n", 1)[1].split("\n\n", 1)[0]
        assert "$(need_bash)" in recipe, f"make {verb} runs bash without asking for it"
        assert f"scripts/{script}" in recipe


@pytest.mark.parametrize("script", NEW_SCRIPTS)
def test_no_address_and_no_port_is_written_into_the_commands(script) -> None:
    """A node's address and ports are record data; a literal here is a host you cannot leave."""
    code = code_only(script.read_text())
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", code.replace("127.0.0.1", "")), (
        f"{script.name} carries an IP address literal"
    )
    assert not re.search(r"--port[ =]\"?\d", code), f"{script.name} opens a literal port"


@pytest.mark.parametrize("script", NEW_SCRIPTS)
def test_nothing_is_named_after_the_box_that_died(script) -> None:
    assert "esinilyadev" not in script.read_text()


# --- restore-panel: the secrets ----------------------------------------------------------

def test_the_secret_files_only_ever_travel_as_stdin(panel: str) -> None:
    """Never ``cat``, ``echo`` or ``source`` on this machine — only redirected into ssh."""
    code = code_only(panel)
    for variable in ("SERVER_ENV", "RESTORE_ENV", "IDENTITY"):
        uses = re.findall(rf"[^\n]*\$\{{{variable}\}}[^\n]*", code)
        for use in uses:
            if re.search(r"^\s*(cat|echo|printf|\.|source)\b", use.strip()):
                pytest.fail(f"{variable} is read out on this machine: {use.strip()!r}")
    assert '< "${IDENTITY}"' in code and '< "${RESTORE_ENV}"' in code


def test_the_identity_is_shredded_by_a_trap_and_right_after_the_restore(panel: str) -> None:
    code = code_only(panel)
    assert "trap cleanup EXIT" in code
    cleanup = code.split("cleanup() {", 1)[1].split("\n}\n", 1)[0]
    assert "shred -u" in cleanup and "REMOTE_TMP" in cleanup
    after_restore = panel.split("make restore-from-bucket", 1)[1].split("# --- 5.", 1)[0]
    assert "shred -u" in after_restore, (
        "the identity waits for the end of the whole run instead of leaving with the restore"
    )


def test_the_staging_directory_is_private_and_prefers_ram(panel: str) -> None:
    assert "/dev/shm" in panel and "chmod 700" in panel and "umask 077" in panel


# --- restore-panel: the order ------------------------------------------------------------

def test_dns_is_checked_before_anything_is_published(panel: str) -> None:
    """A CA is asked the moment 80/443 are published; early, it validates the old address."""
    code = code_only(panel)
    assert code.index('resolve_ipv4 "${PUBLIC_HOST}"') < code.index("make ${publish}")


def test_a_rerun_does_not_restore_over_a_fleet(panel: str) -> None:
    code = code_only(panel)
    gate = code.split('if [ "${nodes_held}" != "0" ] && [ "${FORCE_RESTORE:-0}" != "1" ]; then', 1)
    assert len(gate) == 2, "nothing stops a second restore over a database that holds nodes"
    skipped_branch = gate[1].split("else", 1)[0]
    assert "make restore-from-bucket" not in skipped_branch


def test_ufw_logging_is_turned_off_rather_than_refused(panel: str) -> None:
    assert "ufw logging off" in code_only(panel)


def test_the_backup_schedule_comes_back(panel: str) -> None:
    assert "make backup-schedule" in code_only(panel)


def test_the_console_url_it_prints_is_the_one_caddy_serves_over_ssh(panel: str) -> None:
    """The Caddyfile's private site answers on https://127.0.0.1:<port> too."""
    caddyfile = (REPO / "deploy" / "caddy" / "Caddyfile").read_text()
    assert "https://127.0.0.1:{$HASHI_PRIVATE_PORT}" in caddyfile
    assert "https://127.0.0.1:${PRIVATE_PORT}/panel/" in panel
    assert "-L ${PRIVATE_PORT}:127.0.0.1:${PRIVATE_PORT}" in panel


def test_a_missing_input_is_a_sentence_before_any_host_is_dialled(tmp_path) -> None:
    ran = subprocess.run(
        [str(RESTORE_PANEL), "--host", "nobody@host.invalid",
         "--server-env", str(tmp_path / "absent.env"),
         "--restore-env", str(tmp_path / "absent2.env"),
         "--identity", str(tmp_path / "absent.txt")],
        capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert ran.returncode == 1
    assert "absent.env is missing or empty" in ran.stderr
    assert "reaching" not in ran.stdout


# --- the restore never mints a management tunnel ------------------------------------------

def test_the_restore_asks_the_bootstrap_to_skip_the_tunnel() -> None:
    call = [line for line in BACKUP.read_text().splitlines()
            if "panel-bootstrap.sh" in line and "if !" in line]
    assert call and "PANEL_SKIP_MGMT_TUNNEL=1" in call[0], call


def test_a_skipped_tunnel_never_reaches_the_generator(tmp_path) -> None:
    """Section 1c, run: a REAL block (not the template's) plus the skip — no generator call."""
    bootstrap = BOOTSTRAP.read_text()
    body = bootstrap.split("MGMT_MODE=none\n", 1)[1].split("\nfi\n", 1)[0]
    decision = "MGMT_MODE=none\n" + body + "\nfi\n"
    (tmp_path / "scripts").mkdir()
    generator = tmp_path / "scripts" / "management-tunnel.sh"
    generator.write_text("#!/bin/sh\ntouch \"$(dirname \"$0\")/called\"\n")
    generator.chmod(0o755)
    env_file = tmp_path / "host.env"
    env_file.write_text("HASHI_MGMT_ADDRESS=10.77.0.1/24\n")
    harness = (
        "set -euo pipefail\n"
        f"REPO_ROOT={tmp_path}\nENV_FILE={env_file}\n"
        "has_value() { grep -Eq \"^[[:space:]]*$1=[[:space:]]*[^[:space:]]\" \"${ENV_FILE}\"; }\n"
        "mgmt_is_the_template() { return 1; }\n"
        "fail() { echo \"FAIL $1\"; exit 1; }\n"
        + decision + 'echo "MODE=${MGMT_MODE}"\n'
    )
    for skip, mode, called in (("1", "skipped", False), ("0", "generate", True)):
        marker = tmp_path / "scripts" / "called"
        marker.unlink(missing_ok=True)
        ran = subprocess.run(["bash", "-c", harness], capture_output=True, text=True,
                             env={"PATH": "/usr/bin:/bin", "PANEL_SKIP_MGMT_TUNNEL": skip})
        assert f"MODE={mode}" in ran.stdout, (ran.stdout, ran.stderr)
        assert marker.exists() is called


# --- restore-node -------------------------------------------------------------------------

def test_the_node_account_is_a_parameter_with_a_plain_default(node: str) -> None:
    assert 'ACCOUNT="hashi"' in node
    assert "useradd -m" in code_only(node)


def test_the_node_is_moved_and_applied_through_the_control_planes_own_verbs(node: str) -> None:
    code = code_only(node)
    makefile = MAKEFILE.read_text()
    for verb in ("node-plan", "node-relocate", "node-apply"):
        assert f"make -s {verb}" in code, f"restore-node does not use make {verb}"
        assert f"\n{verb}:" in makefile
    assert "psql" not in code and "update nodes" not in code.lower(), (
        "the record is moved by hand rather than through the audited relocation"
    )


def test_the_ports_come_from_the_record_and_from_the_running_caddy(node: str) -> None:
    code = code_only(node)
    assert "PLAN[ports]" in code
    assert "com.docker.compose.service=caddy" in code


def test_the_record_is_moved_only_after_the_host_is_ready(node: str) -> None:
    code = code_only(node)
    assert code.index("node-bootstrap.sh") < code.index("make -s node-relocate")


def test_an_account_name_useradd_would_misread_is_refused_first(tmp_path) -> None:
    ran = subprocess.run(
        [str(RESTORE_NODE), "--node", "entry-1", "--host", "nobody@host.invalid",
         "--account", "-o root"],
        capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert ran.returncode == 1
    assert "is not an account name" in ran.stderr


def test_the_caddy_port_reading_skips_loopback_and_unpublished_ports(node: str) -> None:
    """The awk that reads ``docker ps``'s Ports column, run on a real-shaped line."""
    program = node.split("| awk -F'->' '", 1)[1].split("'", 1)[0]
    ports = ("0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, "
             "[::]:443->443/tcp, 127.0.0.1:54143->54143/tcp, 2019/tcp")
    ran = subprocess.run(["awk", "-F->", program], input=ports.replace(", ", "\n"),
                         capture_output=True, text=True, check=True)
    assert sorted(set(ran.stdout.split())) == ["443/tcp", "80/tcp"]


# --- the runbook ---------------------------------------------------------------------------

def test_the_cheat_sheet_is_dns_and_two_commands() -> None:
    sheet = RUNBOOK.read_text().split("## Короткая памятка")[1].split("\n## ")[0]
    section = sheet.split("### Восстановить после потери сервера")[1].split("\n### ")[0]
    dns = section.index("DNS")
    panel_at = section.index("make restore-panel HOST=")
    assert dns < panel_at < section.index("make restore-node NODE=")
    assert "https://127.0.0.1:PORT/panel/" in sheet
    assert "https://PRIVATE_HOST:PORT/panel/` и" not in sheet
