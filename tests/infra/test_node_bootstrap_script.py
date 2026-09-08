"""The node bootstrap's contract, read rather than run — M11.1.

WHAT: static checks over ``scripts/node-bootstrap.sh`` and the Make target that pipes it
      to a host.
WHY:  the only honest proof of this script is a host that has never run hashi, and no
      suite rents one (M11.4 is a person with real hardware). What IS provable from the
      tree is that the script cannot quietly do the dangerous version of each step —
      prompt on a pipe, guess a port, generate a private key on the machine most likely
      to be seized, or leave the host writing down who connected to it.
HOW:  the script is read, not run. Same division as ``test_panel_bootstrap_script.py``
      and ``test_backup_script.py``.

      Stated plainly: nothing here proves a host becomes a node. It proves the script
      cannot do the harmful version of becoming one.
"""

import pathlib
import re
import stat

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "node-bootstrap.sh"
MAKEFILE = REPO / "Makefile"


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


def test_the_script_exists_and_is_executable() -> None:
    """A script that has to be invoked via `bash` is one an operator mistypes."""
    assert SCRIPT.is_file(), "the leaf half of the charter's one-command deploy is missing"
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_it_fails_the_whole_run_on_any_error(script: str) -> None:
    """``set -euo pipefail``.

    ``-e`` is what stops a failed docker install from being followed by a firewall that
    comes up in front of nothing; ``-u`` is what stops a typo'd variable becoming an empty
    argument to ``ufw allow``.
    """
    assert re.search(r"^set -euo pipefail$", script, re.M)


def test_it_asks_no_questions(script: str) -> None:
    """Not one prompt, and this script has four places one could hide.

    It is run over a flaky SSH session, usually piped — ``ssh host 'bash -s' < script`` —
    where stdin is the script itself. A prompt there does not wait for an answer, it
    consumes the rest of the script.
    """
    for forbidden in (r"\bread\s+-", r"^\s*read\s", r"\bselect\s+\w+\s+in\b"):
        assert not re.search(forbidden, script, re.M), (
            f"the script contains an interactive construct matching {forbidden!r}"
        )
    # sudo without -n prompts for a password on a host that wants one.
    assert not re.search(r"(?:^|[;&|(])\s*sudo\s+(?!-n\b)", script, re.M), (
        "the script calls sudo without -n, so a host that wants a password hangs"
    )
    # apt asks about config files and service restarts unless told not to.
    for apt in re.findall(r"apt-get install[^\n]*", script):
        assert "-y" in apt, f"apt-get install without -y: {apt!r}"
        assert "DEBIAN_FRONTEND=noninteractive" in script, "apt is left free to ask"
    # `ufw enable` asks for a confirmation, because it may disrupt the session running it.
    for enable in re.findall(r"as_root ufw[^\n|]*\benable\b", script):
        assert "--force" in enable, f"ufw enable without --force will prompt: {enable!r}"


def test_it_never_creates_a_private_key_on_the_node(script: str) -> None:
    """THE refusal, and the same shape as panel-bootstrap's.

    The private key is what the control database holds to reach every node. Generated on
    the node it would sit in clear on the machine most likely to be seized, and one seized
    leaf would then be a key to the fleet. The script installs the PUBLIC half only.

    The distinction the assertion has to make is real: the refusal message names
    ``ssh-keygen`` for the operator to run ELSEWHERE, so what is forbidden is executing a
    generator here, not mentioning one.
    """
    assert not re.search(r"^\s*(sudo -n |as_root )?ssh-keygen\b", script, re.M), (
        "the script runs ssh-keygen — a node must never hold a key it generated"
    )
    for generator in (r"openssl\s+genpkey", r"openssl\s+rand", r"wg\s+genkey", r"uuidgen"):
        assert not re.search(generator, script), f"the script contains a generator ({generator!r})"
    # And it refuses a private key handed to it by mistake, which is one hurried paste away.
    assert "PRIVATE KEY" in script, (
        "the script does not catch a pasted private key, so the fleet's key could land on "
        "a node with everything afterwards appearing to work"
    )


def test_the_public_key_is_required_rather_than_defaulted(script: str) -> None:
    """No key, no run. A node whose key came from a default is a node anyone can drive."""
    assert "--authorized-key" in script
    assert re.search(r'\[ -n "\$\{AUTHORIZED_KEY\}" \]', script), (
        "the script does not refuse an empty key"
    )
    assert re.search(r'^AUTHORIZED_KEY=""$', script, re.M), (
        "the script supplies a default public key"
    )


def test_the_authorized_key_lands_with_restrictive_permissions(script: str) -> None:
    """sshd ignores an authorized_keys file others can write, and says so only in its log."""
    assert re.search(r"install -d -m 700", script), "the .ssh directory is not created 0700"
    assert re.search(r"chmod 600", script), "authorized_keys is not restricted to its owner"


def test_installing_the_key_twice_does_not_append_it_twice(script: str) -> None:
    """Property 1, at the one place a second run would visibly accumulate state."""
    assert re.search(r"grep -qF .*KEY_BODY", script), (
        "the script appends the key without checking whether it is already there"
    )
    assert re.search(r"KEY_BODY=.*awk", script), (
        "the key is compared whole, so re-running with a different comment appends a "
        "second copy of the same key"
    )


def test_logging_is_turned_off_before_the_firewall_can_come_up(script: str) -> None:
    """The milestone's own requirement, and the one record the charter forbids outright.

    ``ufw enable`` turns logging ON by default and begins writing source addresses
    immediately. Doing ``logging off`` afterwards still creates the record — so the order
    is the property, not the presence (docs/decisions.md, decision 5).
    """
    logging_off = re.search(r"^as_root ufw logging off$", script, re.M)
    assert logging_off, "the script does not turn ufw logging off"
    enable = re.search(r"^\s*as_root ufw --force enable", script, re.M)
    assert enable, "the script never enables the firewall"
    assert logging_off.start() < enable.start(), (
        "the firewall is enabled before logging is turned off, so the host writes "
        "connection records in between — which is the whole thing this must not do"
    )
    # And it never turns it back on, at any level, for any reason.
    assert not re.search(r"ufw logging (?:on|low|medium|high|full)", script), (
        "the script sets a ufw logging level other than off"
    )


def test_it_opens_the_management_port_before_enabling_the_firewall(script: str) -> None:
    """A firewall that comes up before its own admission rule is a locked door.

    This runs on a host the operator is in the middle of building, over the very session
    the rule protects.
    """
    allow_ssh = re.search(r'ufw allow "\$\{port\}/tcp"', script)
    enable = re.search(r"as_root ufw --force enable", script)
    assert allow_ssh and enable
    assert allow_ssh.start() < enable.start(), "the firewall comes up before SSH is allowed"


def test_it_refuses_rather_than_guessing_which_port_ssh_uses(script: str) -> None:
    """The alternative to detection is a literal, and a literal is a lock-out.

    Detected from two independent places — the port this session arrived on and the port
    the daemon itself reports — and when neither answers, the script stops instead of
    enabling a firewall it cannot prove leaves a way back in.
    """
    assert "SSH_CONNECTION" in script, "the live session's own port is not consulted"
    assert re.search(r"sshd -T", script), "the daemon is never asked which port it listens on"
    assert re.search(r'\[ -n "\$\{SSH_PORTS\}" \] \|\| fail', script), (
        "the script proceeds to the firewall without knowing the management port"
    )
    assert "--ssh-port" in script, "there is no way to tell it the port by hand"


def test_no_port_country_provider_or_address_is_hardcoded(script: str) -> None:
    """Every port it opens arrives as an argument; none is a literal in this file.

    A node whose transport listens on an arbitrary port is the normal case — the port is a
    property of the node record, not of this script — and a hardcoded one is a port the
    fleet cannot move away from. Same rule as a country, a provider or an address.
    """
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", script), "an IP address is hardcoded"
    for port in (21, 22, 23, 25, 53, 80, 443, 1194, 3306, 5432, 6379, 8000, 8080, 8443, 51820):
        assert not re.search(rf"\b{port}\b", script), (
            f"the literal port {port} appears in the script — even in a comment it is a "
            "value somebody will copy into a rule"
        )
    for allow in re.findall(r"ufw allow [^\n]*", script):
        assert "${" in allow, f"a firewall rule is opened for a literal: {allow!r}"
    # Exactly one address in the file: upstream docker's installer, and it is overridable.
    urls = re.findall(r"[a-z]+://[^\s\"']+", script)
    assert urls == ["https://get.docker.com}"], f"unexpected addresses in the script: {urls}"
    assert "DOCKER_INSTALL_URL:-" in script, (
        "the runtime installer's address is not overridable, so a host behind a mirror "
        "cannot be bootstrapped"
    )


def test_it_leaves_no_hashi_code_and_no_hashi_state_on_the_host(script: str) -> None:
    """A node holds nothing that cannot be regenerated from the control database.

    That property is what makes destroying and replacing a node safe, and this script must
    not invent the first exception. It installs a runtime, a public key and firewall rules
    — the compose file and every transport config are pushed later, by the control plane.
    """
    for forbidden in (
        r"git clone",
        r"pip install",
        r"python3? -m venv",
        r"apt-get install[^\n]*python",
    ):
        assert not re.search(forbidden, script), f"the script installs {forbidden!r} on the node"
    assert not re.search(r"(mkdir|install -d|tee|cp|scp|curl)[^\n]*/opt/", script), (
        "the script writes into /opt on the node — node state belongs to the control plane"
    )
    assert not re.search(r"docker-compose\.ya?ml", script), (
        "the script places a compose file, which the control plane would then have to "
        "reconcile with"
    )
    # It is piped to the host, so it must not depend on this repository being there.
    assert "BASH_SOURCE" not in script and "REPO_ROOT" not in script, (
        "the script resolves its own repository path, so it cannot be piped to a host"
    )
    assert not re.search(r"^\s*(\.|source)\s", script, re.M), "the script sources another file"


def test_nothing_in_it_is_destructive(script: str) -> None:
    """Idempotence, checked as the absence of the operations that would break it.

    The exception is deliberate and narrow: the ufw log is removed, because it holds the
    one record the charter forbids and leaving it would be keeping the evidence while only
    stopping the note-taking.
    """
    for forbidden in (r"rm -rf", r"ufw reset", r"docker rm", r"docker system prune", r"userdel"):
        assert not re.search(forbidden, script), f"the script contains {forbidden!r}"
    removals = re.findall(r"rm -f [^\n']*", script)
    assert removals, "the ufw log is not removed at all"
    for removal in removals:
        assert re.search(r"/var/log/ufw\.log|INSTALLER", removal), (
            f"the script deletes something it was not asked to: {removal!r}"
        )


def test_a_second_run_finds_every_step_already_done(script: str) -> None:
    """Property 1, stated as the guards that make it true.

    Both field hosts already have docker and one already has an active firewall with
    rules: "already done, by somebody else" is the normal case here, not the exception.
    """
    assert re.search(r"command -v docker", script), "docker is installed unconditionally"
    assert re.search(r"id -nG .*grep -qx docker", script), (
        "group membership is added without checking, so every run is a change"
    )
    assert re.search(r"ufw status[^\n]*inactive", script), (
        "the firewall is enabled without checking whether it is already up"
    )


def test_it_verifies_the_host_before_it_reports_success(script: str) -> None:
    """The third property, and the same one panel-bootstrap holds itself to.

    The questions are the control plane's own: can a container be started, is the key
    actually installed, is the firewall up, and is it quiet. `echo ok` is how an operator
    ends up believing a broken node is ready.
    """
    assert re.search(r"docker version --format", script), "the daemon is never asked to answer"
    assert re.search(r"docker compose version", script), (
        "the compose plugin is never checked, so the first apply is where it fails"
    )
    assert re.search(r"Status: active", script), "the firewall's state is never confirmed"
    assert re.search(r"Logging: off", script), (
        "the script never confirms the host is not recording connections"
    )


def test_it_prints_no_rules_and_no_logs(script: str) -> None:
    """A firewall rule can name an address; a log can name a person.

    The script has no reason to put either on a terminal, and terminals are recorded.
    """
    assert not re.search(r"ufw status(?![^\n]*(\||>))", script), (
        "the script prints the firewall's rule table"
    )
    assert not re.search(r"(?:journalctl|cat|tail|less|head|grep)[^\n]*\s/var/log/", script), (
        "the script reads a system log"
    )


def test_the_owner_has_a_make_target_for_it() -> None:
    """The infra rulebook: an operation without a Make target is a bug in this zone."""
    makefile = MAKEFILE.read_text()
    assert re.search(r"^node-bootstrap:", makefile, re.M), "there is no `make node-bootstrap`"
    assert re.search(r"^\.PHONY:[^\n]*node-bootstrap", makefile, re.M), (
        "the target is not declared .PHONY"
    )
    target = re.search(r"^node-bootstrap:\n(?:\t[^\n]*\n)+", makefile, re.M).group(0)
    assert "scripts/node-bootstrap.sh" in target
    assert "$(NODE)" in target, "the target hardcodes which host it prepares"
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", target), "an address is hardcoded"
    # Piped, not copied: nothing of this repository is left on a node.
    assert "<" in target and "scp" not in target, (
        "the Make target copies the script onto the node instead of piping it"
    )
