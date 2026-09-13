"""The node bootstrap's contract, read rather than run — M11.1.

WHAT: static checks over ``scripts/node-bootstrap.sh`` and the Make target that pipes it
      to a host.
WHY:  the only honest proof of this script is a host that has never run hashi, and no
      suite rents one (M11.4 is a person with real hardware). What IS provable from the
      tree is that the script cannot quietly do the dangerous version of each step —
      prompt on a pipe, guess a port, generate a private key on the machine most likely
      to be seized, or leave the host writing down who connected to it.
HOW:  the script is read, not run — with one growing exception at the bottom of this
      file, added by M18's acceptance: the tests that RUN its checking half, cut at the
      section where it first touches the host. Reading cannot catch a refusal that is
      written correctly and can never fire, which is what a `getent` that ends the run by
      itself under ``set -e`` produced. Everything else keeps the division
      ``test_panel_bootstrap_script.py`` and ``test_backup_script.py`` use.

      Stated plainly: nothing here proves a host becomes a node. It proves the script
      cannot do the harmful version of becoming one.

      M11.2 added the second half: that a re-run changes nothing and claims nothing untrue,
      and that the script states the boundaries an operator would otherwise assume away.

      M18.3 added the one thing a re-run now DOES change on a host that has already been
      applied to: who owns what an earlier apply left under the node directory. That is
      the only way an account change can be carried out without the operator typing a
      recursive chown on a live node, and the assertions for it sit beside the ones that
      keep the re-run's claims honest, because the two constrain each other.

      M19 added the two checks that are about the HOST rather than about the run — will
      sshd read the file the key went into, and can this kernel forward — and both of
      them had to be RUN rather than read, for the reason M18's acceptance established:
      a refusal that cannot fire reads exactly like one that can. Both run late in the
      script, which the cut cannot reach, so the test supplies the CALL and the script
      supplies the function (``function_in``). What is exercised is the script's own
      code; what is stubbed is only what sshd and the kernel answer. The scenario in
      ``tests/e2e/infra/test_a_real_host_answers_the_bootstrap_preconditions.py`` puts
      the same functions in front of a real OpenSSH and a real ``/proc/sys``, because a
      stub can only repeat what its author believed the output looks like.
"""

import os
import pathlib
import pwd
import re
import stat
import subprocess

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
    assert re.search(r"^key_is_authorised\(\) \{", script, re.M), (
        "the script appends the key without checking whether it is already there"
    )
    assert re.search(r"^if key_is_authorised; then", script, re.M), (
        "the presence check is not the thing that decides whether to append"
    )
    assert re.search(r"KEY_BODY=.*awk", script), (
        "the key is compared whole, so re-running with a different comment appends a "
        "second copy of the same key"
    )


def test_a_commented_out_key_does_not_count_as_authorised(script: str) -> None:
    """The presence check decides twice: whether to append, and whether to report success.

    A plain substring search over authorized_keys also matches the key in a disabled entry
    or in a note about one. It would then report "already authorised" AND pass the
    verification at the end, for a key sshd ignores — a host that says it is ready and
    cannot be logged into, which is the worst shape an untrue re-run can take.
    """
    guard = re.search(r"^key_is_authorised\(\) \{\n(?:.*\n)*?\}$", script, re.M)
    assert guard, "there is no single guard, so the two callers can disagree"
    assert "/^[[:space:]]*#/ { next }" in guard.group(0), (
        "a commented-out entry counts as an authorisation"
    )
    # And the final verification asks the same question, not a looser one.
    assert re.search(r"^key_is_authorised \|\| fail", script, re.M), (
        "the verification uses a different, weaker check than the install did"
    )
    assert not re.search(r"grep -qF[^\n]*KEY_BODY", script), (
        "a substring search over the whole file survives somewhere"
    )


def test_an_existing_authorized_keys_file_is_not_rewritten(script: str) -> None:
    """touch(1) on an existing file is a write, and a second run must change nothing.

    The chown and chmod beside it are deliberately unconditional: they assert a state
    rather than change one, and sshd silently ignores a file others can write, so
    re-asserting them every run is the point.
    """
    assert re.search(r'^\[ -e "\$\{KEYS_FILE\}" \] \|\| as_root touch', script, re.M), (
        "the script touches authorized_keys unconditionally, so a second run bumps its "
        "mtime — a change, on a run that promised none"
    )


def test_logging_is_turned_off_before_the_firewall_can_come_up(script: str) -> None:
    """The milestone's own requirement, and the one record the charter forbids outright.

    ``ufw enable`` turns logging ON by default and begins writing source addresses
    immediately. Doing ``logging off`` afterwards still creates the record — so the order
    is the property, not the presence (docs/decisions.md, decision 5).
    """
    # The redirection is optional and the command is not: ufw's own sentence about the
    # change is discarded (M19's acceptance — a run whose lines all start ``==> `` should
    # not have another program's wording in the middle of it), and what the script did is
    # said afterwards in its own words. Anchored so a ``logging off`` piped into something
    # that could swallow its failure still does not satisfy this.
    logging_off = re.search(r"^\s*as_root ufw logging off(?: >/dev/null)?$", script, re.M)
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

    M13 narrowed this by exactly one directory and not one byte more. The script now
    creates ``NODE_ROOT``, EMPTY, because ``/opt`` is root-owned and the library that
    drives a node never escalates (see the agreement suite beside this file). An empty
    directory is not state — nothing in it needs regenerating, because nothing is in it —
    so what this assertion now checks is that emptiness: the one creation is allowed, and
    anything that would put CONTENT under ``/opt`` is still a finding.
    """
    for forbidden in (
        r"git clone",
        r"pip install",
        r"python3? -m venv",
        r"apt-get install[^\n]*python",
    ):
        assert not re.search(forbidden, script), f"the script installs {forbidden!r} on the node"
    # Commands only, never comments: the section explaining WHY the directory is created
    # quotes the `mkdir: cannot create directory '/opt/hashi'` that M13 was found through,
    # and a rule that cannot tell prose from a command cannot be written honestly.
    commands = re.findall(r"^[^#\n][^\n]*", script, re.M)
    writes_under_opt = [
        line
        for line in commands
        if re.search(r"(mkdir|tee|cp|scp|curl)[^\n]*(/opt/|\$\{NODE_ROOT\})", line)
        or re.search(r'(tee|cp|scp|curl)[^\n]*"\$\{NODE_ROOT\}', line)
    ]
    assert writes_under_opt == [], (
        f"the script writes content into /opt on the node — node state belongs to the "
        f"control plane: {writes_under_opt}"
    )
    # And the one directory it does create is the root itself, never a path inside it:
    # anything under NODE_ROOT is the control plane's to place and to reconcile.
    for creation in re.findall(r"^\s*as_root install -d[^\n]*", script, re.M):
        assert re.search(r'"\$\{(?:NODE_ROOT|SSH_DIR)\}"$', creation), (
            f"the script creates a directory that is neither the account's .ssh nor the "
            f"node root itself: {creation!r}"
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
    assert re.search(r'^\[ -e "\$\{KEYS_FILE\}" \]', script, re.M), (
        "authorized_keys is touched unconditionally"
    )
    assert re.search(r"^ufw_default\(\) \{", script, re.M), (
        "the default policies are written without reading what they already are"
    )
    assert re.search(r"^UFW_LOGLEVEL=", script, re.M), (
        "the logging level is set without reading what it already is"
    )


def test_no_ufw_command_that_rewrites_its_config_runs_unconditionally(script: str) -> None:
    """The four ufw calls that are not additive, each behind a guard.

    ``ufw logging`` and ``ufw default`` rewrite ufw's own config files and reload the
    firewall EVERY time they are called, whether or not the value changes — so calling them
    unconditionally made a second run a change, and on a host whose operator had chosen
    their own policy it overwrote that choice while the run still announced that the
    existing rules were kept. ``ufw allow`` is the exception and stays unguarded: it is
    additive and ufw deduplicates it itself.

    Guarded is checked as indented, which is what an ``if`` around a line does. A line at
    column zero here is a line that runs on every host, every time.
    """
    for command in (
        "ufw logging off",
        "ufw --force default deny incoming",
        "ufw --force default allow outgoing",
        "ufw --force enable",
    ):
        found = re.findall(rf"^([ \t]*)as_root {re.escape(command)}", script, re.M)
        assert found, f"the script never runs `{command}`"
        for indent in found:
            assert indent, f"`{command}` runs unconditionally, so a second run is a change"


def test_the_logging_check_fails_towards_turning_logging_off(script: str) -> None:
    """The one guard whose failure direction is a charter question, not a tidiness one.

    Reading the current level is an optimisation — it exists so a second run does not
    reload the firewall and print ufw's own line into the middle of ours. It must never
    become a reason logging stays ON: an unreadable or missing config leaves the answer
    empty, empty is not ``off``, and the command then runs. So the guard tests for
    already-off and does the work in its ELSE branch, never the other way round.
    """
    guard = re.search(
        r'^if \[ "\$\{UFW_LOGLEVEL\}" = "off" \]; then\n(?:.*\n)*?^fi$', script, re.M
    )
    assert guard, "the logging guard is not shaped as a test for already-off"
    body = guard.group(0)
    already, _, otherwise = body.partition("\nelse\n")
    assert otherwise, "the guard has no else branch, so a failed read leaves logging alone"
    assert "ufw logging off" in otherwise, (
        "logging is turned off only when the config could be read — a host whose config is "
        "missing would then keep recording who connected to it"
    )
    assert "ufw logging off" not in already, "the guard turns logging off when it is already off"


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


def test_a_re_run_does_not_claim_it_opened_a_port_that_was_already_open(script: str) -> None:
    """"Opened" is a claim about an effect, and on a second run there is no effect.

    ufw refuses to add a rule it already holds and says so; that answer is the whole
    difference between "opened" and "was already open". The captured form also matters:
    piping ufw into ``grep -q`` under ``pipefail`` lets the early pipe close report ufw's
    SIGPIPE instead of the match, which is the trap M11.1 already hit once.
    """
    assert "Skipping adding existing rule" in script, (
        "the script cannot tell an added rule from one that was already there"
    )
    assert "was already open" in script, "a second run still claims it opened the port"
    assert re.search(r'opened="\$\(as_root env LC_ALL=C ufw allow', script), (
        "ufw's answer is not captured under a fixed locale, so a translated build silently "
        "falls through to the wrong message"
    )
    assert not re.search(r"ufw allow[^\n]*\|\s*grep", script), (
        "ufw is piped into grep, where pipefail turns an early pipe close into a failure"
    )
    # A genuine refusal must still stop the run, not be swallowed by the capture.
    assert re.search(r'if ! opened="\$\(as_root env LC_ALL=C ufw allow[^\n]*\n\s*fail ', script), (
        "a ufw refusal is captured and discarded, so the run continues past a rule that "
        "was never added"
    )


def test_it_stays_honest_about_hashi_state_on_a_host_already_applied_to(script: str) -> None:
    """The closing line is read as "there is nothing of hashi's here", and on a re-run of a
    live node that is false — the control plane put its directory there on the first apply.

    What is true on every run is the narrower claim: THIS SCRIPT wrote nothing into the
    directory and removed nothing from it. The extra line is what keeps the sentence above
    it from being read as the wider one.

    M13 made the claim narrower still, because the script now creates the directory: the
    closing line says it is EMPTY, which stops being true on the second run of a live node.
    So the correction has to fire on whether the directory PRE-EXISTED this run, which is a
    fact only this run knows — the directory is there either way by the time it is read.
    """
    assert "no hashi code and no hashi state was installed here" in script, (
        "the run no longer states that it left no hashi state behind"
    )
    remembered = re.search(
        r'^if \[ -d "\$\{NODE_ROOT\}" \]; then NODE_ROOT_EXISTED=1', script, re.M
    )
    created = re.search(r'^as_root install -d[^\n]*"\$\{NODE_ROOT\}"$', script, re.M)
    corrected = re.search(r'^if \[ "\$\{NODE_ROOT_EXISTED\}" -eq 1 \]; then$', script, re.M)
    assert remembered and created and corrected, (
        "the run does not correct its own closing line for a host that already had the "
        "directory"
    )
    assert remembered.start() < created.start(), (
        "whether the directory pre-existed is read AFTER this run created it, so the answer "
        "is always yes — the correction then fires on every run, including the first, and "
        "the closing line is wrong in the other direction"
    )
    assert re.search(r"neither read, changed nor removed it", script), (
        "the line does not say that this run left the existing contents alone"
    )
    # M18.3 made the claim narrower again, in the other direction. The run now takes
    # ownership of the CONTENTS as well, so a line ending "only re-asserted that the
    # account owns the directory" would understate what it did — and understating a
    # change of ownership is how an operator concludes their files were left as they
    # were. The contents are still neither read nor written; what moved is who they
    # belong to, and the line has to say so.
    assert re.search(r"it now belongs to \$\{TARGET_USER\} along with the directory", script), (
        "the run hands the existing contents to the prepared account without saying so — "
        "which is the half-measure M18.3 forbids, in reverse"
    )


def test_the_closing_summary_does_not_contradict_itself_on_a_re_run(script: str) -> None:
    """It said the directory was empty and, on the next line, what was left in it — M18.

    Both lines were true of the run they were written for and only one of them was ever
    conditional, so a re-run of a host the control plane has already applied to printed
    a summary that denied itself: ``/opt/hashi is an empty directory owned by <user>``
    immediately above ``whatever an earlier apply left in it``. An operator reading a
    closing summary is deciding whether to trust the run; a summary that argues with
    itself about the one directory it is a summary of does not survive that.

    Asserted as the SHAPE rather than as a pair of strings, because the defect is which
    branch each sentence is in and a substring check cannot see a branch: the empty claim
    belongs to the run that created the directory, and the claim about what is already in
    there belongs to the other one. Both must still say the run installed no hashi state,
    which is the sentence this whole passage exists for.
    """
    closing = re.search(
        r'^if \[ "\$\{NODE_ROOT_EXISTED\}" -eq 1 \]; then\n'
        r"(?P<re_run>(?:  \S.*\n)+)"
        r"^else\n"
        r"(?P<first_run>(?:  \S.*\n)+)"
        r"^fi$",
        script[script.index("say \"ready: docker"):],
        re.M,
    )
    assert closing, (
        "the closing summary no longer chooses what to say about the node directory, so "
        "one of its two claims about it is being made on the run it is false on"
    )
    re_run, first_run = closing.group("re_run"), closing.group("first_run")

    assert "is an empty directory" in first_run, first_run
    assert "is an empty directory" not in re_run, (
        "a re-run of a host that already has the directory is still told it is empty, "
        "one line above being told what an earlier apply left in it"
    )
    assert "whatever an earlier apply left in it" in re_run, re_run
    assert "whatever an earlier apply left in it" not in first_run, (
        "a host that never had the directory is told about contents that cannot exist"
    )
    for branch in (re_run, first_run):
        assert "no hashi code and no hashi state was installed here" in branch, (
            f"this run no longer states that it left no hashi state behind: {branch}"
        )


def test_it_hands_an_existing_node_directorys_contents_to_the_prepared_account(
    script: str,
) -> None:
    """M18.3 — the step's whole subject, and the reason "re-run the script" was not enough.

    A node applied as one account and later prepared for another kept root-owned files
    inside a directory the new account owned. The next apply died three layers away, in
    ``node_stack.prepare``, on a ``chmod`` of a directory the account cannot chmod — and
    the bootstrap that caused it had just printed ``ready``.

    The step allowed either carrying the files or saying plainly that it does not. This
    is the carrying half, and the assertion is deliberately about the RECURSION: a
    non-recursive chown, or the ``install -d`` alone, is precisely the half-measure that
    looks like it carries them. Both the mode and the owner must still be asserted on the
    directory itself, which is what ``install -d`` is for, so neither line replaces the
    other.
    """
    handover = re.search(
        r'^as_root chown -R\S* "\$\{TARGET_USER\}:\$\{TARGET_GROUP\}" '
        r'"\$\{NODE_ROOT\}(/\.)?"$',
        script,
        re.M,
    )
    assert handover, (
        "the node directory's contents are never handed to the account this run prepares "
        "for, so a host applied to as another account is left with files it cannot replace"
    )
    created = re.search(r'^as_root install -d[^\n]*"\$\{NODE_ROOT\}"$', script, re.M)
    assert created and created.start() < handover.start(), (
        "the contents are chowned before the directory is known to exist"
    )
    # It must not follow a symlink out of the directory it is recursing through, and the
    # flag that decides that is `-P` — not `-h`, which this asserted until M18.1's review.
    # `-h` decides whether a symlink leaf or its referent is changed; `-H`/`-L`/`-P` decide
    # whether the walk DESCENDS through a link to a directory, and only `-P` refuses.
    # Measured on coreutils 9.4: `chgrp -RhL` over a tree holding a link to an outside
    # directory changed the files inside that directory, `-RhLP` changed nothing outside
    # the tree. GNU already defaults `-R` to `-P`, so this is invisible in a passing run
    # here — which is exactly why the wrong flag stayed pinned as though it were the
    # guard, and why this is asserted on the flag that closes the hole rather than on the
    # one the comment happened to name.
    flags = handover.group(0).split()[2]
    assert "P" in flags, (
        "the recursive chown does not state that it refuses to descend through a symlink, "
        "so on a chown that traverses by default a link planted under the node directory "
        f"redirects it at an arbitrary path on the host — `-h` does not close this ({flags}"
        "), it only decides whether a link or its referent is changed"
    )
    assert "h" in flags, (
        f"the recursive chown ({flags}) no longer says it changes a symlink itself rather "
        "than what it points at"
    )
    # And it names the DIRECTORY rather than a link to it. `-P` refuses to traverse the
    # argument as well, so on a host where the node directory is a symlink to a data
    # volume the chown changed the link, left every file inside owned by the old account
    # and exited 0 — while the run announced the handover. `install -d` above has always
    # followed the link; `/.` is what makes the two mean the same thing.
    assert handover.group(0).endswith('"${NODE_ROOT}/."'), (
        "the handover chowns ${NODE_ROOT} itself, so a symlinked node directory flips the "
        "link's owner, leaves its contents with the old account, and says it is done"
    )


def test_it_says_what_it_does_not_do(script: str) -> None:
    """M11.2's other half, and the headline item is the one outside the host entirely.

    A closed security group looks EXACTLY like a broken transport — host firewall open,
    container up, every check in this script green, client still timing out — so an
    operator who is not told about it debugs the transport. It sits in the provider's
    console, beyond the reach of anything running on the host, so the only thing the script
    can do about it is name it.
    """
    section = re.search(
        r"^# WHAT THIS SCRIPT DOES NOT DO(?:.*\n)*?^set -euo pipefail$", script, re.M
    )
    assert section, (
        "the script enumerates what it holds itself to and never states its boundaries, so "
        "every gap reads as covered"
    )
    boundaries = section.group(0)
    assert "security group" in boundaries, "the provider's own firewall is not named"
    assert re.search(r"LOOKS EXACTLY LIKE A BROKEN TRANSPORT", boundaries), (
        "the section names the security group without saying what it looks like when it is "
        "shut, which is the only part that saves an operator an evening"
    )
    assert "false negative" in boundaries and "unprivileged" in boundaries, (
        "the section does not warn that the check itself can lie — a probe that cannot bind "
        "a privileged port reports a shut port that is in fact open"
    )
    assert "IT DOES NOT REGISTER THE NODE" in boundaries, (
        "a prepared host reads as a node the fleet knows about"
    )
    for elsewhere in ("rsyslog", "journald", "kern.log"):
        assert elsewhere in boundaries, (
            f"the log sweep is not qualified: {elsewhere} holds the same lines on a host "
            "that has already logged, and no cleanup here reaches it"
        )
    assert "IT NEVER CLOSES ANYTHING" in boundaries, (
        "the rule set is the union of every run, and nothing says so"
    )
    assert "IT IS NOT HOST HARDENING" in boundaries, (
        "'the host is ready' is left to cover password authentication and the rest of it"
    )


def test_the_run_itself_names_the_provider_firewall(script: str) -> None:
    """A boundary only in the header is a boundary nobody piping this to a host will read.

    It is said last, after success, because that is the moment the operator goes off to
    test a transport — and the moment a shut security group starts costing them the
    evening.
    """
    says = re.findall(r"^say \"(?:[^\"]*)\"", script, re.M | re.S)
    assert says, "the script says nothing"
    assert "security group" in says[-1], (
        "the last thing the run says is not the one thing that is outside its reach"
    )
    assert "outside this script" in says[-1]


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


# --- the run itself, as far as the first line that changes the host -----------
#
# Everything above READS the script. The three below RUN part of it, because the defect
# M18's acceptance found is one no reading catches: the refusal for `--user <an account
# that does not exist>` was written, was correct, and could never fire. `getent` reports
# "no such account" by exiting 2 and printing nothing, so under `set -euo pipefail` the
# lookup on the line above ended the run by itself — exit 2, zero bytes on stdout, zero
# bytes on stderr — and the operator who used the most natural first-run order, naming the
# account they intend to use before creating it, was answered with total silence.
#
# CUT AT SECTION 2, and the cut is what makes running this safe. Everything before it is
# checks — the arguments, the way to root, the key, the account — and none of it touches
# the host; the first line that installs, adds or opens anything is the container runtime.
# So these run the script's own lines, and a mutation that deletes the refusal cannot
# install docker on whoever is running the suite.
WHERE_THE_HOST_IS_FIRST_TOUCHED = "# --- 2. the container runtime"

# Shape only — this is what the script's own check looks for, and no key material is
# involved: the body is not a key and is never used as one.
A_PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAthisisnotakey hashi-control"


def run_the_checks(
    script: str,
    tmp_path: pathlib.Path,
    *arguments: str,
    then: str = "",
    stubs: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """The script's checking half, run with no TTY and nothing to answer a prompt with.

    ``sudo`` is stubbed with one that runs what it is given, because the only use of it
    before the cut is ``sudo -n true`` — the test for a password-less one. Nothing
    privileged is invoked before the cut, so the stub grants the run nothing.

    ``then`` is shell text appended after the cut, and it is how M19's two checks are
    reached: both of them have to run LATE — one because the container runtime is what
    sets the kernel setting it reads, the other because it verifies what the run
    installed — and everything between the cut and them changes the host. So the test
    supplies the CALL and the script supplies the function, lifted out of the file by
    ``function_in``: what runs is the script's own code, not a copy of it.

    ``stubs`` are further programs to put on the run's PATH, by name — ``sshd`` and
    ``sysctl``, whose answers are the whole input to those two checks. Stubbing them from
    outside is what keeps the script free of a switch that exists for a test.
    """
    prefix = tmp_path / "node-bootstrap-checks.sh"
    prefix.write_text(script[: script.index(WHERE_THE_HOST_IS_FIRST_TOUCHED)] + then)
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "sudo").write_text('#!/bin/sh\n[ "$1" = "-n" ] && shift\nexec "$@"\n')
    (stub_dir / "sudo").chmod(0o755)
    for name, text in (stubs or {}).items():
        (stub_dir / name).write_text(text)
        (stub_dir / name).chmod(0o755)
    return subprocess.run(
        ["bash", str(prefix), *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        env={
            "PATH": f"{stub_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(tmp_path),
        },
    )


def function_in(script: str, name: str) -> str:
    """One of the script's own shell functions, lifted out of the file by name.

    The same extraction ``test_a_commented_out_key_does_not_count_as_authorised`` does to
    read ``key_is_authorised``'s body — used here to RUN the function rather than to read
    it. A function that stops being defined at column zero, or stops closing at column
    zero, fails here rather than being silently skipped.
    """
    found = re.search(rf"^{re.escape(name)}\(\) \{{\n(?:.*\n)*?^\}}$", script, re.M)
    assert found, f"the script no longer defines {name}() at the top level"
    return found.group(0) + "\n"


def test_an_account_that_does_not_exist_is_refused_by_name(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The operator gets a sentence, not an exit code — M18's acceptance.

    What was measured on the host: ``--user hashi`` before ``useradd hashi`` exited 2 with
    nothing on either stream, and the same invocation after it printed the full summary.
    Silence is the worst of the possible answers here, because the run that follows it
    once the account exists looks identical, so the operator has no way to learn what the
    first one was about.

    The account is named because it is the one thing the operator can act on: which of
    the three things they meant — create it, name another, or leave the flag off — depends
    on which account this is, and a refusal that says "no such account" says none of it.
    """
    missing = "hashi-no-such-account"

    refused = run_the_checks(script, tmp_path, "--authorized-key", A_PUBLIC_KEY, "--user", missing)

    assert refused.returncode != 0, refused.stdout
    assert refused.stderr.strip(), (
        "the run ended non-zero with nothing on either stream, which is the finding: "
        f"stdout {refused.stdout!r}"
    )
    # Flattened, because the message is wrapped at this file's width and a phrase that
    # crosses a wrap would be an assertion about where the wrap is.
    said = " ".join(refused.stderr.split())
    assert missing in said, said
    # Every way forward this script supports, because it will not create the account
    # itself: make it, name a different one, or let the default stand.
    assert "useradd -m" in said, said
    assert "--user" in said, said
    # And it says it changed nothing, which is what makes "run it again" safe to offer.
    assert "nothing on this host was changed" in said, said


def test_an_account_that_exists_is_prepared_rather_than_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The other half, without which the refusal above could be unconditional.

    ``root`` rather than the account running the suite: this asserts that the check
    passes for an account that is really there, and root is the one every host has — it
    is also the ``ssh_user`` default the panel offers, so it is the account most first
    runs name.
    """
    accepted = run_the_checks(script, tmp_path, "--authorized-key", A_PUBLIC_KEY, "--user", "root")

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_no_lookup_in_it_can_end_the_run_without_saying_why(script: str) -> None:
    """The class the silent refusal belonged to, rather than the one instance.

    Under ``set -euo pipefail`` any command that answers by exiting ends the whole run,
    and a command that answers by exiting AND printing nothing ends it with nothing for
    the operator to read. ``getent`` is the one lookup in this file that answers that way
    — every other command here (``curl``, ``install``, ``apt-get``, ``ufw``, ``chown``,
    ``id``) writes its own diagnostic to stderr before it fails — so every use of it has
    to be caught and answered rather than left to kill the run.
    """
    for line in script.splitlines():
        if "getent" in line and not line.lstrip().startswith("#"):
            assert "|| true" in line, (
                "a getent that fails ends the run with nothing on either stream, so the "
                f"refusal written under it never fires: {line.strip()}"
            )


# --- M19's acceptance: what the run refuses, and what it has already done ------
#
# The walk handed ``--authorized-key`` a TWO-LINE value. The script installed both lines
# into the account's ``authorized_keys`` — the second belonging to somebody else entirely
# — printed that it had authorised the control plane's key, and only then refused, at the
# very end, on a check that compares the first key's body and never mentioned the other
# one. The operator was stopped and never told that a key they did not choose was now
# authorised for that account; nothing removed it; and the non-zero exit invited a retry
# that would leave it behind. It is reached by accident as easily as by malice — a .pub
# file with a stray second line is an ordinary mistake.
#
# Every test below runs the script's checking half rather than reading it, for the reason
# the section above gives, and the cut is what makes each of them evidence: a refusal that
# fires before ``# --- 2. the container runtime`` is a refusal that fired before the host
# was touched, because that is the first line in the file that changes anything.


def test_a_value_carrying_a_second_key_is_refused_before_anything_is_written(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The acceptance finding, and the position of the check is half of the fix.

    ``authorized_keys`` holds one key per line, so a value with a newline in it is several
    keys and appending it authorises all of them. Refusing here — before section 3 writes
    anything — is what makes "nothing on this host was changed" true; a check on the far
    side of the write could only repair, and a repair has a window in which the stranger's
    key is live and a failure mode of its own.
    """
    smuggled = "AAAAsmuggled"

    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        f"{A_PUBLIC_KEY}\nssh-ed25519 {smuggled} intruder@elsewhere",
        "--user",
        "root",
    )

    assert refused.returncode != 0, refused.stdout
    assert refused.stderr.strip(), f"refused in silence: stdout {refused.stdout!r}"
    # And nothing was announced before it. The refusal the walk got arrived after `==>
    # authorised the control plane's key for root`, which is the sentence that made the
    # operator believe they knew what had happened; a check in this position has no
    # progress line in front of it to contradict.
    assert refused.stdout.strip() == "", refused.stdout
    said = " ".join(refused.stderr.split())
    assert "more than one key" in said, said
    # It says the host is untouched, which is the claim only a check in this position can
    # make — and the one an operator needs before they retry.
    assert "nothing on this host was changed" in said, said
    # And neither key is put on a terminal, here or anywhere else.
    assert smuggled not in refused.stdout + refused.stderr
    assert A_PUBLIC_KEY.split()[1] not in refused.stdout + refused.stderr


def test_one_key_on_one_line_is_still_installed(script: str, tmp_path: pathlib.Path) -> None:
    """The accept-case the refusal above is worthless without.

    A public key carries an optional comment, so it has spaces in it and its own shape —
    a check that refused anything with whitespace would refuse every key ever generated.
    """
    accepted = run_the_checks(
        script, tmp_path, "--authorized-key", A_PUBLIC_KEY, "--user", "root"
    )

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_a_key_file_holding_two_keys_is_refused_rather_than_narrowed_to_the_first(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The same rule through the other flag, which used to read the file with ``head -1``.

    That silently installed the first of however many keys the file held, so a file whose
    SECOND line is the fleet's key installed somebody else's and reported that it had
    authorised the control plane's. One invocation, one key, whichever flag carries it.
    """
    two_keys = tmp_path / "two.pub"
    two_keys.write_text(f"{A_PUBLIC_KEY}\nssh-ed25519 AAAAsomebodyelse other@host\n")

    refused = run_the_checks(
        script, tmp_path, "--authorized-key-file", str(two_keys), "--user", "root"
    )

    assert refused.returncode != 0, refused.stdout
    said = " ".join(refused.stderr.split())
    assert "more than one key" in said, said
    assert "nothing on this host was changed" in said, said


def test_a_key_file_holding_one_key_is_read_whole(script: str, tmp_path: pathlib.Path) -> None:
    """The accept-case, and the reason the whole file can be read rather than its head.

    Every ``.pub`` ends in a newline and command substitution strips it, so a well-formed
    file is one line by the time the check sees it. A trailing blank line is stripped the
    same way and is not an operator error.
    """
    one_key = tmp_path / "one.pub"
    one_key.write_text(f"{A_PUBLIC_KEY}\n\n")

    accepted = run_the_checks(
        script, tmp_path, "--authorized-key-file", str(one_key), "--user", "root"
    )

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_an_option_with_nothing_after_it_is_refused_in_this_script_s_words(
    script: str, tmp_path: pathlib.Path
) -> None:
    """``--authorized-key`` as the last token died with ``$2: unbound variable``.

    That is ``set -u`` speaking, not this script: it names a line number in a file the
    operator is piping in and never names the flag they typed. ``shift 2`` past the end is
    the same hazard one token later and worse — it returns non-zero and ``set -e`` ends the
    run in silence, which is the defect M18's acceptance found in ``getent``.
    """
    for option in ("--authorized-key", "--authorized-key-file", "--user", "--port", "--ssh-port"):
        refused = run_the_checks(script, tmp_path, option)

        assert refused.returncode != 0, f"{option} with no value was accepted: {refused.stdout}"
        assert refused.stderr.strip(), f"{option} refused in silence: {refused.stdout!r}"
        said = " ".join(refused.stderr.split())
        assert said.startswith("node-bootstrap:"), (
            f"{option} was answered by the shell rather than by this script: {said}"
        )
        assert option in said, said
        assert "unbound variable" not in said, said


def test_an_argument_that_is_not_a_port_is_refused_before_the_host_is_touched(
    script: str, tmp_path: pathlib.Path
) -> None:
    """M19's acceptance: the port checks used to run four host-changing steps too late.

    ``--port 0/udp`` was refused only after the key had been installed, /opt/hashi created
    and the firewall reconfigured. ``--ssh-port 0`` was not checked at all — it reached a
    firewall rule, where ufw answered with its own bare ``ERROR: Bad port`` and ``set -e``
    ended the run. Both are knowable from the command line alone, so both are answered
    there: this runs the checking half, which stops before the first line that touches the
    host, and every case below must already be refused by then.
    """
    for arguments in (
        ("--ssh-port", "0"),
        ("--port", "0/udp"),
        ("--ssh-port", "99999999999999999999"),
        ("--port", "99999999999999999999/udp"),
        ("--ssh-port", "not-a-number"),
        ("--port", "1/sctp"),
    ):
        refused = run_the_checks(
            script, tmp_path, "--authorized-key", A_PUBLIC_KEY, "--user", "root", *arguments
        )

        assert refused.returncode != 0, f"{arguments} was accepted: {refused.stdout}"
        said = " ".join(refused.stderr.split())
        assert said.startswith("node-bootstrap:"), (
            f"{arguments} was answered by a program the operator did not invoke: {said}"
        )
        # The value the operator typed, whole — not the piece of it the check looked at.
        assert arguments[1] in said, said
        # Not ufw's sentence, and not bash's arithmetic complaint.
        assert "Bad port" not in said, said
        assert "integer expression" not in said, said


def test_the_ports_an_operator_really_passes_are_not_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The accept-case, without which every check above could be unconditional.

    Both forms the usage documents — a bare number and a number with a protocol — and both
    flags, because they are validated by different functions.
    """
    accepted = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        "--port",
        "9999/udp",
        "--port",
        "9998",
        "--ssh-port",
        "2222",
    )

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_every_refusal_after_the_key_is_installed_says_the_key_is_installed(
    script: str,
) -> None:
    """A refusal that hides a change it made is the class M19's acceptance was closing.

    Past the line that appends the key, the host carries an authorisation it did not carry
    before. The sshd questions in section 6 named it already; the firewall, the daemon and
    the kernel refusals did not, so an operator stopped by one of those had no way to know
    whether anything had been authorised, and no reason to go and look. Read rather than
    run, because the point is that EVERY one of them says it — a test that ran them would
    only cover the ones somebody thought of.
    """
    installed = re.search(r'^  say "authorised the control plane\'s key for', script, re.M)
    assert installed, "the script no longer announces that it installed the key"
    for message in re.finditer(r'fail \\?\n?\s*"((?:[^"\\]|\\.)*)"', script[installed.end() :]):
        said = " ".join(message.group(1).split())
        assert "${KEYS_FILE}" in said, (
            "a refusal after the key is installed does not say that it is installed or "
            f"which file it is in: {said[:120]}"
        )


# --- M19.2: a verification that can fail --------------------------------------
#
# The script wrote ``authorized_keys`` and then verified its own work by reading back the
# file it had just written — which is true whether or not sshd consults that file at all.
# One of this project's own field hosts takes its keys from cloud metadata through an
# ``AuthorizedKeysCommand`` and works only because its sshd ALSO sets
# ``AuthorizedKeysFile``; on a host with the command and no usable file, the run said
# ``ready`` for a key that cannot authenticate. Same defect class as M4.6: a check whose
# answer is fixed by construction.


def the_sshd_key_check(script: str) -> str:
    """The script's own sshd lookup and all three key checks, with the calls the run makes.

    All three, in the run's own order, because they constrain each other: the guard is what
    keeps an unaskable daemon from passing both of the questions under it, and the two
    questions are halves of one answer — which file would sshd read a key from, and would
    reading it end in a login. Assembling only one of them here would let a test pass a
    host the script refuses.

    BOTH lookups, for the same reason: the global one is what the guard reads and what the
    account-scoped one falls back to, and the three checks read the account-scoped one. A
    harness that assembled only the first would be testing a script that no longer exists.
    """
    return (
        function_in(script, "sshd_effective_config")
        + 'SSHD_CONFIG="$(sshd_effective_config)"\n'
        + function_in(script, "sshd_config_for_this_account")
        + 'SSHD_ACCOUNT_CONFIG="$(sshd_config_for_this_account)"\n'
        + function_in(script, "refuse_if_sshd_cannot_be_asked")
        + function_in(script, "refuse_if_this_account_cannot_use_a_key")
        + function_in(script, "refuse_if_sshd_ignores_the_key_file")
        + "refuse_if_sshd_cannot_be_asked\n"
        + "refuse_if_this_account_cannot_use_a_key\n"
        + "refuse_if_sshd_ignores_the_key_file\n"
        + 'say "the run would have gone on to report ready"\n'
    )


def an_sshd_that_says(*lines: str) -> dict[str, str]:
    """A stub sshd whose ``-T`` prints exactly these directives.

    The shape is real OpenSSH's: one directive per line, name lowercased, the value in
    force. ``tests/e2e/infra/test_a_real_host_answers_the_bootstrap_preconditions.py``
    puts the same checks in front of a REAL sshd, because a stub can only ever repeat what
    its author believed the output looks like.
    """
    printed = "\n".join(lines)
    return {"sshd": f"#!/bin/sh\ncat <<'CONFIG'\n{printed}\nCONFIG\n"}


# What sshd prints when nothing has been configured, read off a real OpenSSH 9.6p1: the
# account's own file, no command, keys on, no method requirement, and root admitted with a
# key. The path is relative, which is how sshd writes it and is the case the check has to
# expand rather than compare literally. ``permitrootlogin without-password`` is here for
# the same reason: it is what ``sshd -T`` prints for the value written as
# ``prohibit-password``, it is the compiled default, and it PERMITS a key — so a check that
# refused on it would refuse most of the hosts this project will ever meet.
A_DEFAULT_SSHD = an_sshd_that_says(
    "authorizedkeyscommand none",
    "authorizedkeyscommanduser none",
    "authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2",
    "pubkeyauthentication yes",
    "authenticationmethods any",
    "permitrootlogin without-password",
)

# The field condition this whole section exists for, and the one no host in the fleet has
# today: keys come from a command, and the file this script writes is read by nobody.
A_METADATA_ONLY_SSHD = an_sshd_that_says(
    "authorizedkeyscommand /usr/local/bin/keys-from-metadata %u",
    "authorizedkeyscommanduser nobody",
    "authorizedkeysfile none",
)


def test_a_host_whose_sshd_reads_the_file_is_not_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The other half, without which every refusal below could be unconditional.

    ``root`` for the reason the account test above gives: it is the account every host
    has and the one most first runs name. The path sshd reports is RELATIVE, so this also
    asserts the expansion — a check that compared the two strings literally would refuse
    every ordinary host on earth.
    """
    accepted = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs=A_DEFAULT_SSHD,
    )

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "the run would have gone on to report ready" in accepted.stdout


def test_a_host_that_takes_keys_only_from_a_command_never_reaches_ready(
    script: str, tmp_path: pathlib.Path
) -> None:
    """M19's second "done when", and the acceptance line, as an assertion.

    The run must stop, must say which of the two sources sshd really uses, and must say
    it in words — a non-zero exit with an empty stderr is the same defect as a wrong
    answer (M18's acceptance), and this check runs late, where the operator has already
    watched everything else succeed.
    """
    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs=A_METADATA_ONLY_SSHD,
    )

    assert refused.returncode != 0, refused.stdout
    assert "the run would have gone on to report ready" not in refused.stdout
    assert refused.stderr.strip(), (
        f"the run ended non-zero with nothing on stderr: stdout {refused.stdout!r}"
    )
    said = " ".join(refused.stderr.split())
    # By name, both of them: which command sshd asks, and the file it is not reading.
    assert "/usr/local/bin/keys-from-metadata" in said, said
    assert "/root/.ssh/authorized_keys" in said, said
    # And what the operator can do about it, since this script cannot.
    assert "AuthorizedKeysFile" in said, said
    # The key itself is never on a terminal, here or anywhere else.
    assert A_PUBLIC_KEY.split()[1] not in refused.stdout + refused.stderr


def test_a_host_whose_sshd_reads_some_other_file_is_refused_too(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The same failure without a command anywhere in it.

    ``AuthorizedKeysCommand`` is how the case was FOUND, not what makes it a case: any
    configuration that moves the account's keys elsewhere leaves this script writing to a
    file sshd will not open. Asserted separately so the check cannot degenerate into
    "does this host have a keys command".
    """
    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs=an_sshd_that_says(
            "authorizedkeyscommand none",
            "authorizedkeysfile /etc/ssh/authorized_keys_for/%u",
        ),
    )

    assert refused.returncode != 0, refused.stdout
    said = " ".join(refused.stderr.split())
    assert "/etc/ssh/authorized_keys_for" in said, said
    assert "/root/.ssh/authorized_keys" in said, said


def test_an_sshd_that_cannot_be_asked_is_not_taken_as_a_yes(
    script: str, tmp_path: pathlib.Path
) -> None:
    """"Could not check" must not read as "checked" — that is the whole defect class.

    A host where ``sshd -T`` answers nothing is a host where this run does not know
    whether the key works, and the file it just wrote cannot tell it. Refusing is the
    honest answer and it is a narrowing: before M19 such a host was told ``ready``.
    """
    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs={"sshd": "#!/bin/sh\nexit 1\n"},
    )

    assert refused.returncode != 0, refused.stdout
    said = " ".join(refused.stderr.split())
    assert "sshd -T" in said, said
    assert "/root/.ssh/authorized_keys" in said, said


# --- M19.2, second half: a file sshd reads is not yet a login -----------------
#
# The first half of this check answered WHICH FILE sshd reads a key from and the run
# treated that as "this key authenticates". It is not the same sentence, and the
# difference is three directives ``sshd -T`` was already printing: a host with
# ``PubkeyAuthentication no`` was told, truthfully, that the file its key went into is one
# sshd consults — and then reported ``ready`` for a key that logs nobody in.
#
# Every case below is run rather than read, for the reason the rest of this section gives,
# and every one of them is paired with the configuration it must NOT refuse. A check that
# turns away a working host costs the operator the evening this script exists to save.


def an_account_that_is_not_root() -> str:
    """A real account with a non-zero uid, or a skip that names what is missing.

    ``PermitRootLogin`` is a rule about uid 0, and the script reads that uid out of the
    passwd entry — so the case where the directive must NOT apply needs an account that
    really exists on the machine running the suite. ``getent`` is not stubbed here and must
    not be: which uid an account has is the input under test.
    """
    try:
        entry = pwd.getpwnam("nobody")
    except KeyError:  # pragma: no cover - every Unix in this project's path has one
        pytest.skip(
            "no 'nobody' account on this machine, so the case that PermitRootLogin must "
            "not be applied to a non-root account did not run"
        )
    assert entry.pw_uid != 0, "the 'nobody' account on this machine is uid 0"
    return "nobody"


def run_the_key_check_against(
    script: str, tmp_path: pathlib.Path, *directives: str, account: str = "root"
) -> subprocess.CompletedProcess:
    """The three sshd checks, against a daemon that prints ``directives`` and nothing else.

    The default account is ``root`` for the reason the tests above give: it is the account
    every host has and the ``ssh_user`` the panel's node form offers first.
    """
    return run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        account,
        then=the_sshd_key_check(script),
        stubs=an_sshd_that_says(*directives),
    )


# The file half answered perfectly: the account's own file, no command, nothing moved. The
# ONLY thing wrong with each of these hosts is that the key could not authenticate anyway.
A_FILE_SSHD_REALLY_READS = (
    "authorizedkeyscommand none",
    "authorizedkeysfile .ssh/authorized_keys",
)


def test_a_host_that_authenticates_nobody_with_a_key_never_reaches_ready(
    script: str, tmp_path: pathlib.Path
) -> None:
    """M19's second "done when", for the plainest way a key fails to authenticate.

    ``PubkeyAuthentication no`` and everything else stock: sshd really does read
    ``/root/.ssh/authorized_keys``, so the file half of this check says yes and is right to
    — and no key in it logs anyone in. This is the shape the first round of M19 shipped a
    ``ready`` for.
    """
    refused = run_the_key_check_against(
        script, tmp_path, *A_FILE_SSHD_REALLY_READS, "pubkeyauthentication no"
    )

    assert refused.returncode != 0, refused.stdout
    assert "the run would have gone on to report ready" not in refused.stdout
    assert refused.stderr.strip(), (
        f"the run ended non-zero with nothing on stderr: stdout {refused.stdout!r}"
    )
    said = " ".join(refused.stderr.split())
    # By name, because "the key will not work" sends an operator to the wrong file.
    assert "PubkeyAuthentication" in said, said
    assert "/root/.ssh/authorized_keys" in said, said
    assert A_PUBLIC_KEY.split()[1] not in refused.stdout + refused.stderr


def test_a_host_that_wants_a_second_factor_beside_the_key_never_reaches_ready(
    script: str, tmp_path: pathlib.Path
) -> None:
    """``AuthenticationMethods``, in both of the shapes that keep the control plane out.

    ``password`` refuses a key outright. ``publickey,password`` is the subtler one and the
    reason this is not a membership test: a comma means BOTH must succeed, so the key is
    necessary and not sufficient, and the control plane — which has a key, no password to
    offer and no terminal to be prompted on — gets no further with it than without it. That
    failure would otherwise land at the first apply, a screen away from anything naming it.
    """
    for methods in ("password", "publickey,password"):
        refused = run_the_key_check_against(
            script,
            tmp_path,
            *A_FILE_SSHD_REALLY_READS,
            f"authenticationmethods {methods}",
        )

        assert refused.returncode != 0, f"'{methods}' was accepted: {refused.stdout}"
        assert "the run would have gone on to report ready" not in refused.stdout
        assert refused.stderr.strip(), f"refused in silence: stdout {refused.stdout!r}"
        said = " ".join(refused.stderr.split())
        assert methods in said, said
        assert "AuthenticationMethods" in said, said


def test_a_key_on_its_own_among_other_alternatives_is_not_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The false refusal the test above is one comma away from.

    A SPACE separates alternatives and a comma joins requirements, so
    ``publickey password`` is "a key, or a password" — a host the control plane logs into
    with the key alone. ``any`` is the default and the value almost every host prints. A
    check that read the directive as a word list would refuse both, and would then refuse
    every stock host on earth for the default value.
    """
    for methods in ("any", "publickey password", "publickey keyboard-interactive"):
        accepted = run_the_key_check_against(
            script,
            tmp_path,
            *A_FILE_SSHD_REALLY_READS,
            f"authenticationmethods {methods}",
        )

        assert accepted.returncode == 0, (
            f"'{methods}' lets a key alone in and was refused:"
            f"\n{accepted.stdout}{accepted.stderr}"
        )
        assert "the run would have gone on to report ready" in accepted.stdout


def test_an_account_root_may_not_log_into_never_reaches_ready(
    script: str, tmp_path: pathlib.Path
) -> None:
    """``PermitRootLogin``, in the two values that keep the installed key out.

    The panel's node form defaults ``ssh_user`` to root, so this is the likely combination
    rather than the exotic one — the operator takes the default, the host ships with root
    logins off, and every other signal in the run is green.
    ``forced-commands-only`` is the one that reads like a yes: it admits root with a key,
    but only a key carrying its own forced ``command=``, and this script installs a bare
    one while the control plane runs ordinary commands over that session.
    """
    for value in ("no", "forced-commands-only"):
        refused = run_the_key_check_against(
            script, tmp_path, *A_FILE_SSHD_REALLY_READS, f"permitrootlogin {value}"
        )

        assert refused.returncode != 0, f"'{value}' was accepted: {refused.stdout}"
        assert "the run would have gone on to report ready" not in refused.stdout
        assert refused.stderr.strip(), f"refused in silence: stdout {refused.stdout!r}"
        said = " ".join(refused.stderr.split())
        assert "PermitRootLogin" in said, said
        assert value in said, said
        # And the way out, which is not only "change sshd": the account is an argument.
        assert "--user" in said, said


def test_the_root_value_that_permits_a_key_is_not_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The false refusal that would have turned away most of the hosts in existence.

    ``prohibit-password`` PERMITS public-key authentication and forbids only the password —
    it is what a hardened host sets, and ``sshd -T`` prints it under its older spelling,
    ``without-password``, which is also OpenSSH's compiled default. A check that refused on
    the string it saw would refuse a stock Debian, and a check that accepted only the
    modern spelling would refuse every daemon that prints the old one.
    """
    for value in ("yes", "prohibit-password", "without-password"):
        accepted = run_the_key_check_against(
            script, tmp_path, *A_FILE_SSHD_REALLY_READS, f"permitrootlogin {value}"
        )

        assert accepted.returncode == 0, (
            f"'{value}' admits a key and the run refused it:"
            f"\n{accepted.stdout}{accepted.stderr}"
        )
        assert "the run would have gone on to report ready" in accepted.stdout


def test_root_only_rules_are_not_applied_to_an_account_that_is_not_root(
    script: str, tmp_path: pathlib.Path
) -> None:
    """``PermitRootLogin no`` is the normal, correct configuration of a host with a
    non-root deploy account — and this script's whole non-root shape (M13) is that account.

    So reading the directive without asking who the run is preparing for would refuse the
    most sensible host in the fleet. The account is tested by uid rather than by name,
    which is also what sshd does: it is a rule about uid 0, not about the word ``root``.
    """
    account = an_account_that_is_not_root()

    accepted = run_the_key_check_against(
        script,
        tmp_path,
        "authorizedkeyscommand none",
        "authorizedkeysfile .ssh/authorized_keys",
        "permitrootlogin no",
        account=account,
    )

    assert accepted.returncode == 0, (
        f"a run preparing '{account}' was refused for a rule that only governs uid 0:"
        f"\n{accepted.stdout}{accepted.stderr}"
    )
    assert "the run would have gone on to report ready" in accepted.stdout


# --- M19's acceptance: the question is about THIS account ---------------------
#
# The walk built a host carrying ``PubkeyAuthentication no`` with a ``Match User root``
# block three lines below that switches keys back on, and then LOGGED IN with the key to
# prove it works. The script refused it, honestly — ``sshd -T`` with no connection to
# describe prints the configuration before any ``Match`` — and there was no way past the
# refusal, so that host could never produce the line the panel registers from. It was
# unregisterable. A check that turns away a working host is the same defect as one that
# passes a broken one, which is the convention this milestone established.
#
# The answer is ``sshd -T -C user=<the account>``, and the reason it is available at all is
# that the account is the ONE part of a connection this script legitimately knows: the
# operator passed it. An address would be a hard-rule violation in this file.


def an_sshd_that_answers(*, globally: tuple[str, ...], for_root: tuple[str, ...]) -> dict[str, str]:
    """A stub sshd whose ``-T`` answer depends on whether it was asked about an account.

    Two configurations behind one binary, which is what a ``Match User`` block IS from the
    outside: the daemon has one answer with no connection to describe and another for a
    named account. The scenario under ``tests/e2e/infra/`` puts the same question to a REAL
    sshd running a real ``Match`` block, because a stub can only repeat what its author
    believed; this one isolates WHICH of the two answers the script reads.
    """

    def printed(directives: tuple[str, ...]) -> str:
        return "  printf '%s\\n' " + " ".join(f"'{line}'" for line in directives) + "\n"

    return {
        "sshd": (
            "#!/bin/sh\n"
            "scoped=no\n"
            'for argument in "$@"; do\n'
            '  if [ "$argument" = "user=root" ]; then scoped=yes; fi\n'
            "done\n"
            'if [ "$scoped" = yes ]; then\n'
            + printed(for_root)
            + "else\n"
            + printed(globally)
            + "fi\n"
        )
    }


def test_a_host_that_switches_keys_on_for_this_account_alone_is_not_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The acceptance finding: a host the walk logged into, and the script turned away.

    The value at the top of the file governs everybody except the account in question, so
    reading it is reading the wrong answer — and the wrong answer here costs the operator
    a host they cannot register at all, not merely an evening.
    """
    accepted = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs=an_sshd_that_answers(
            globally=(*A_FILE_SSHD_REALLY_READS, "pubkeyauthentication no"),
            for_root=(*A_FILE_SSHD_REALLY_READS, "pubkeyauthentication yes"),
        ),
    )

    assert accepted.returncode == 0, (
        "a host whose Match block admits this account with a key was refused, which makes "
        f"it unregisterable:\n{accepted.stdout}{accepted.stderr}"
    )
    assert "the run would have gone on to report ready" in accepted.stdout


def test_a_host_that_switches_keys_off_for_this_account_alone_is_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The same blind spot in the direction that used to pass a broken host.

    Keys on at the top of the file and off inside a ``Match`` covering this account: the
    pre-``Match`` answer says yes, no key logs this account in, and the run would have
    reported ``ready``. Both halves come from the same fix, and a test for only the first
    would be satisfied by a script that stopped asking sshd anything.
    """
    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs=an_sshd_that_answers(
            globally=(*A_FILE_SSHD_REALLY_READS, "pubkeyauthentication yes"),
            for_root=(*A_FILE_SSHD_REALLY_READS, "pubkeyauthentication no"),
        ),
    )

    assert refused.returncode != 0, refused.stdout
    assert "the run would have gone on to report ready" not in refused.stdout
    said = " ".join(refused.stderr.split())
    assert "PubkeyAuthentication" in said, said
    # And it does not send the operator looking for a Match block that is already read.
    assert "this run cannot see it" not in said, said


def test_which_file_sshd_reads_is_asked_about_this_account_too(
    script: str, tmp_path: pathlib.Path
) -> None:
    """``AuthorizedKeysFile`` is allowed inside a ``Match`` block, so it needs the same scope.

    Both directions of the same wiring: a host that moves every OTHER account's keys
    elsewhere and leaves this one's where it is works and must not be turned away, and a
    host that moves THIS account's keys elsewhere does not work and must not be passed. The
    pre-``Match`` answer gets both of them backwards, and the refusal has to name the file
    sshd really reads for this account rather than the one at the top of the config.
    """
    somewhere_else = "/etc/ssh/keys_for/%u"

    accepted = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs=an_sshd_that_answers(
            globally=("authorizedkeyscommand none", f"authorizedkeysfile {somewhere_else}"),
            for_root=A_FILE_SSHD_REALLY_READS,
        ),
    )

    assert accepted.returncode == 0, (
        "a host that reads this account's own key file was refused for where it keeps "
        f"everybody else's:\n{accepted.stdout}{accepted.stderr}"
    )

    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs=an_sshd_that_answers(
            globally=A_FILE_SSHD_REALLY_READS,
            for_root=("authorizedkeyscommand none", f"authorizedkeysfile {somewhere_else}"),
        ),
    )

    assert refused.returncode != 0, (
        f"a host that reads this account's keys from somewhere else was accepted:\n"
        f"{refused.stdout}"
    )
    said = " ".join(refused.stderr.split())
    assert "/etc/ssh/keys_for" in said, said
    assert "/root/.ssh/authorized_keys" in said, said


def test_the_daemon_is_asked_about_an_account_and_never_about_an_address(
    script: str,
) -> None:
    """The hard rule, at the one place in this file where breaking it would be tempting.

    ``-C`` also takes an address, a hostname, a local address and a local port, and any of
    them would answer more of the question. A country, a provider, an address or a port in
    this script is a node the fleet cannot rotate away from, so the specification carries
    the account and nothing else — and what that costs is written into section G of the
    header rather than papered over.
    """
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    given = re.findall(r'-C\s+"?([^"\s]+)"?', code)
    assert given == ['user=${TARGET_USER}'], (
        f"the connection specification handed to sshd is not the account alone: {given}"
    )
    for criterion in ("addr=", "host=", "laddr=", "lport=", "rdomain="):
        assert criterion not in code, (
            f"'{criterion}' is handed to sshd, which puts a piece of node topology in this "
            "file — the one thing it may never hold"
        )


def test_every_directive_about_the_account_is_read_from_the_account_scoped_answer(
    script: str,
) -> None:
    """All five of them, and not the two a behavioural test happens to reach.

    Each question in section 6 is answered by grepping one directive out of one variable,
    and there are now two variables that look alike: the pre-``Match`` answer, which the
    port detection in section 5 wants, and the one sshd gave about this account, which
    every key question wants. Reading the wrong one compiles, runs, passes its own tests on
    a host with no ``Match`` block at all, and silently restores the defect M19's
    acceptance found — on the one host shape where it matters.

    Read rather than run for that reason: a behavioural case per directive would be five
    stubs proving the same wiring, and the one that was forgotten is the one that breaks.
    """
    for directive in (
        "pubkeyauthentication",
        "authenticationmethods",
        "permitrootlogin",
        "authorizedkeysfile",
        "authorizedkeyscommand",
    ):
        at = script.index(f"/^{directive} ")
        read_from = re.findall(r"\$\{(SSHD_\w*CONFIG)\}", script[:at])
        assert read_from and read_from[-1] == "SSHD_ACCOUNT_CONFIG", (
            f"{directive} is read from {read_from[-1:] or 'nothing'} rather than from the "
            "answer sshd gave about this account, so a Match block covering it is invisible"
        )
    # And the one question that is NOT about an account keeps the answer it needs: a Port
    # cannot appear inside a Match block, and section 5 asks before the account-scoped
    # lookup could have been made to fail on an odd account name.
    at = script.index("/^port ")
    read_from = re.findall(r"\$\{(SSHD_\w*CONFIG)\}", script[:at])
    assert read_from and read_from[-1] == "SSHD_CONFIG", (
        f"the management port is read from {read_from[-1:] or 'nothing'} rather than from "
        "the daemon's own global answer"
    )


def test_a_daemon_that_will_not_take_the_account_spec_still_gets_an_answer(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The fallback, and it has to be the old answer rather than silence.

    A daemon that refuses the specification — an unparsable one exits 1, and an account
    name containing a comma makes one — leaves the account-scoped lookup empty, and empty
    would send the guard into refusing a host with nothing wrong with it. Falling back to
    the pre-``Match`` answer restores exactly the blind spot this script had before and
    nothing worse.
    """
    accepted = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_sshd_key_check(script),
        stubs={
            "sshd": (
                "#!/bin/sh\n"
                'for argument in "$@"; do\n'
                '  if [ "$argument" = "-C" ]; then\n'
                '    echo "Invalid test mode specification" >&2\n'
                "    exit 1\n"
                "  fi\n"
                "done\n"
                "printf '%s\\n' 'authorizedkeyscommand none' "
                "'authorizedkeysfile .ssh/authorized_keys' 'pubkeyauthentication yes'\n"
            )
        },
    )

    assert accepted.returncode == 0, (
        "a daemon that will not take the account specification was treated as a daemon "
        f"that could not be asked at all:\n{accepted.stdout}{accepted.stderr}"
    )
    assert "the run would have gone on to report ready" in accepted.stdout


def test_every_token_sshd_expands_in_the_keys_file_is_expanded(script: str) -> None:
    """``%h``, ``%u`` and ``%U`` — the three sshd_config(5) lists for AuthorizedKeysFile.

    Read rather than run, and this is the one place in this section where that is the
    honest option: an unexpanded token leaves the comparison unequal, which REFUSES, so
    the cost of missing one is a working host turned away — and the only host on which
    expanding ``%U`` changes the answer is one whose home directory path contains its own
    numeric uid, which no account on a machine running this suite does. ``%%`` is the
    fourth token and is deliberately not here: it can only make the comparison unequal,
    which is the direction this check fails in.
    """
    body = function_in(script, "refuse_if_sshd_ignores_the_key_file")
    for token, value in (("%h", "TARGET_HOME"), ("%u", "TARGET_USER"), ("%U", "TARGET_UID")):
        assert re.search(rf"s\|{token}\|\$\{{{value}\}}\|g", body), (
            f"{token} is never expanded, so a host whose AuthorizedKeysFile uses it is "
            "refused for a configuration that works"
        )


def test_the_final_key_check_asks_sshd_before_it_reads_the_file(script: str) -> None:
    """Both questions, in the order that makes the second one mean anything.

    "Is the key in the file" is only an answer once "will sshd open that file" is yes,
    and it is still needed — sshd consulting the file says nothing about what is in it.
    So neither check replaces the other, and the file check must not be reached first.
    """
    asks_sshd = re.search(r"^refuse_if_sshd_ignores_the_key_file$", script, re.M)
    reads_file = re.search(r"^key_is_authorised \|\| fail", script, re.M)
    assert asks_sshd, (
        "nothing in the run asks sshd which files it reads keys from, so the final "
        "verification is once again the file reading back what the run wrote into it"
    )
    # And all three of them are CALLED, in the order that makes each one worth asking: the
    # guard first, or an unaskable daemon passes the two under it; then whether a key can
    # authenticate this account at all, because "sshd reads that file" printed above a
    # refusal is a line an operator would otherwise act on.
    called = [
        re.search(rf"^{name}$", script, re.M)
        for name in (
            "refuse_if_sshd_cannot_be_asked",
            "refuse_if_this_account_cannot_use_a_key",
            "refuse_if_sshd_ignores_the_key_file",
        )
    ]
    assert all(called), (
        "one of the three sshd checks is defined and never called, which is the shape of "
        f"a refusal that cannot fire: {[bool(found) for found in called]}"
    )
    assert [found.start() for found in called] == sorted(found.start() for found in called), (
        "the three sshd checks are called out of order — the guard has to run first and "
        "the file question last, or one of them reports on a host the next one refuses"
    )
    assert reads_file, "the run no longer checks that the key is in the file at all"
    assert asks_sshd.start() < reads_file.start(), (
        "the file is read back before sshd is asked whether it will ever open it"
    )
    # And the answer comes from sshd itself rather than from our reading of its config.
    assert re.search(r'^SSHD_CONFIG="\$\(sshd_effective_config\)"$', script, re.M), (
        "the effective sshd configuration is never captured, so the check is guessing"
    )
    assert not re.search(r"(?:grep|awk|cat|sed)[^\n]*/etc/ssh/sshd_config", script), (
        "the script parses sshd's config file instead of asking sshd — an Include, a "
        "Match block or a distribution default would then be invisible to it"
    )


def test_the_header_states_the_limit_of_what_sshd_was_asked(script: str) -> None:
    """``sshd -T`` with no connection to describe prints the pre-``Match`` configuration.

    So a host that moves this one account's keys inside ``Match User`` is still told its
    key is fine. That residual hole is exactly the kind of thing the header's second half
    exists for: an operator who reads "the key check asks sshd" would otherwise assume it
    asked about their account.

    And the residual hole must be NAMED rather than covered by a sentence that sounds
    total. The header used to close with "everything outside a `Match` block is checked",
    which was false in a way it did not say: four directives outside any ``Match`` can keep
    this key out of this host and none of them is asked. The list of what is not asked is
    therefore part of the claim, and this asserts one member of it — an overclaim standing
    next to a hole is worse than either.
    """
    section = re.search(
        r"^# WHAT THIS SCRIPT DOES NOT DO(?:.*\n)*?^set -euo pipefail$", script, re.M
    )
    assert section, "the script no longer states its boundaries"
    assert "Match" in section.group(0), (
        "the header does not say that the key check reads the GLOBAL sshd configuration, "
        "so a per-account override reads as covered"
    )
    assert "AllowUsers" in section.group(0), (
        "the header does not name the account lists it never asks about, so a reader is "
        "left to infer that a green run means this key logs in — which it does not"
    )
    assert "Everything outside a `Match` block is checked" not in section.group(0), (
        "the header claims it checks everything outside a Match block. It checks four "
        "directives; AllowUsers, PAM, a locked account and the key's own algorithm all "
        "sit outside one and are not asked"
    )


# --- M19.1: the kernel settings a node's traffic depends on -------------------
#
# Neither is set by anything in this project and neither can be: ``/proc/sys`` is mounted
# read-only inside the data-plane container, so the rules M14 and M3 render cannot reach
# them. Both were fine on the two field hosts, which is why they are preconditions rather
# than a regression — and why nothing had ever noticed.


def the_kernel_check(script: str) -> str:
    """The script's own kernel preconditions, with the call the run makes."""
    return (
        function_in(script, "sysctl_value")
        + function_in(script, "kernel_preconditions")
        + "kernel_preconditions\n"
        + 'say "the run would have gone on to report ready"\n'
    )


# The settings as both field hosts really carry them: forwarding on (the docker daemon
# sets it at every start) and loose reverse-path filtering.
A_WORKING_KERNEL = {
    "net.ipv4.ip_forward": "1",
    "net.ipv4.conf.all.rp_filter": "2",
    "net.ipv4.conf.default.rp_filter": "2",
}


def kernel_stub(**changed: str) -> dict[str, str]:
    """A stub ``sysctl`` answering ``-n <name>`` for a working host, with changes.

    Keyword names are the sysctl names with their dots written as underscores, because a
    dot is not legal in a Python keyword — ``net_ipv4_ip_forward`` is
    ``net.ipv4.ip_forward``, and the three settings this script reads have no underscore
    of their own except ``ip_forward``, which is why the mapping is spelled out below
    rather than guessed at by replacing characters.

    Anything the stub is not given fails the way a real ``sysctl`` fails for a setting
    that is not there, which is a case the check has to answer rather than assume.
    """
    named = {
        "net_ipv4_ip_forward": "net.ipv4.ip_forward",
        "net_ipv4_conf_all_rp_filter": "net.ipv4.conf.all.rp_filter",
        "net_ipv4_conf_default_rp_filter": "net.ipv4.conf.default.rp_filter",
    }
    values = {**A_WORKING_KERNEL}
    for keyword, value in changed.items():
        values[named[keyword]] = value
    branches = "\n".join(f'  {name}) echo "{value}" ;;' for name, value in values.items())
    return {
        "sysctl": (
            '#!/bin/sh\n[ "$1" = "-n" ] && shift\ncase "$1" in\n'
            f"{branches}\n  *) exit 1 ;;\nesac\n"
        )
    }


def test_a_host_with_both_settings_right_is_not_stopped(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The green case, and it has to say nothing.

    A precondition that is met is not news, and a line on every run is a line an operator
    stops reading — which is the whole reason the one below can still be seen.
    """
    accepted = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_kernel_check(script),
        stubs=kernel_stub(),
    )

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "rp_filter" not in accepted.stdout, accepted.stdout


def test_a_host_that_cannot_forward_is_refused_by_name(
    script: str, tmp_path: pathlib.Path
) -> None:
    """M19's first "done when", for the setting that breaks ANY node.

    ``net.ipv4.ip_forward`` is 1 on every hashi node today only because the docker daemon
    sets it at every start. Nothing states it, nothing checks it, and a 0 there is M14's
    exact shape: interface up, container up, handshake complete, bytes counted, nothing
    arriving anywhere and nothing logged.
    """
    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_kernel_check(script),
        stubs=kernel_stub(net_ipv4_ip_forward="0"),
    )

    assert refused.returncode != 0, refused.stdout
    assert refused.stderr.strip(), (
        f"the run ended non-zero with nothing on stderr: stdout {refused.stdout!r}"
    )
    said = " ".join(refused.stderr.split())
    assert "net.ipv4.ip_forward" in said, said
    # The consequence, because "set this sysctl" without it is a chore rather than a
    # reason, and this is the failure an operator would otherwise debug in the transport.
    assert "1" in said and "/etc/sysctl.d" in said, said
    assert "the run would have gone on to report ready" not in refused.stdout


def test_a_setting_that_cannot_be_read_is_not_taken_as_a_pass(
    script: str, tmp_path: pathlib.Path
) -> None:
    """Unreadable is not 1. The same rule as the sshd check, for the same reason."""
    refused = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_kernel_check(script),
        stubs={"sysctl": "#!/bin/sh\nexit 1\n"},
    )

    assert refused.returncode != 0, refused.stdout
    said = " ".join(refused.stderr.split())
    assert "net.ipv4.ip_forward" in said, said


def test_reverse_path_filtering_that_cannot_be_read_is_said_so_and_still_passes(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The other unreadable case, and the one branch of this theme nothing was holding.

    Its sibling — an ``ip_forward`` that cannot be read — refuses, and is pinned above.
    This one cannot refuse, for the same reason strict filtering does not: the setting is
    only wrong for an ENTRY node and nothing tells this script which role the host will be
    registered in. So the branch has to do the awkward thing — SAY that it could not look,
    and let the run finish — and a branch that both prints and returns zero is exactly the
    one a deletion leaves looking fine. Under ``set -euo pipefail`` a ``case`` with no
    matching branch is a no-op with status 0, so the whole of this case is one silent line.

    The stub answers ``ip_forward`` and fails both ``rp_filter`` reads, which is a host
    whose procps is present and whose kernel does not carry the setting — a container, in
    practice, and the shape an operator most easily mistakes for "checked".
    """
    unreadable = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_kernel_check(script),
        stubs={
            "sysctl": (
                '#!/bin/sh\n[ "$1" = "-n" ] && shift\ncase "$1" in\n'
                "  net.ipv4.ip_forward) echo 1 ;;\n  *) exit 1 ;;\nesac\n"
            )
        },
    )

    assert unreadable.returncode == 0, (
        "a host whose reverse-path filtering could not be read was refused. It is a "
        f"working leaf, and the setting is only wrong for an entry:\n{unreadable.stderr}"
    )
    assert "the run would have gone on to report ready" in unreadable.stdout
    said = " ".join(unreadable.stdout.split())
    # Both names, because an operator has to go and read them by hand — and the role the
    # unknown value would matter for, which is the whole reason this is not silence.
    assert "net.ipv4.conf.all.rp_filter" in said, said
    assert "net.ipv4.conf.default.rp_filter" in said, said
    assert "ENTRY" in said, said


def test_strict_reverse_path_filtering_is_named_rather_than_refused(
    script: str, tmp_path: pathlib.Path
) -> None:
    """The owner's decision, and the reason the two settings are not treated alike.

    Strict ``rp_filter`` breaks an ENTRY node — the replies arriving on the hop interface
    are dropped in the kernel before anything sees them — and is entirely correct on a
    leaf. Nothing tells this script which role a host will be registered in, so refusing
    would turn away every leaf for a setting that is right for it. It is named, with what
    it would do, beside the line that tells the operator to go and register the host.
    """
    warned = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_kernel_check(script),
        stubs=kernel_stub(
            net_ipv4_conf_all_rp_filter="1", net_ipv4_conf_default_rp_filter="1"
        ),
    )

    assert warned.returncode == 0, (
        "a host with strict reverse-path filtering was refused. It is a working leaf, and "
        f"this script is not told which role it will have:\n{warned.stderr}"
    )
    assert "the run would have gone on to report ready" in warned.stdout
    said = " ".join(warned.stdout.split())
    assert "net.ipv4.conf.all.rp_filter" in said, said
    # The role it breaks, and the shape of the breakage — without which an operator has
    # no way to tell whether the line applies to the host in front of them.
    assert "ENTRY" in said, said
    assert "hop" in said, said


def test_the_interfaces_that_do_not_exist_yet_are_accounted_for(
    script: str, tmp_path: pathlib.Path
) -> None:
    """``conf.all`` alone is not the answer, and the hop interface is not there yet.

    The kernel applies the MAX of ``conf.all`` and the interface's own value, and an
    interface created later starts from ``conf.default``. So a host with ``all`` off and
    ``default`` strict still drops the hop's replies, and a host with either set to loose
    does not — 2 beats 1, which reads backwards until you know that 2 is the loose mode.
    """
    strict_by_default = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_kernel_check(script),
        stubs=kernel_stub(
            net_ipv4_conf_all_rp_filter="0", net_ipv4_conf_default_rp_filter="1"
        ),
    )
    assert "rp_filter" in strict_by_default.stdout, (
        "a host whose conf.all is off and whose conf.default is strict was passed in "
        "silence — the hop interface does not exist yet and will inherit the strict one"
    )

    loose_somewhere = run_the_checks(
        script,
        tmp_path,
        "--authorized-key",
        A_PUBLIC_KEY,
        "--user",
        "root",
        then=the_kernel_check(script),
        stubs=kernel_stub(
            net_ipv4_conf_all_rp_filter="1", net_ipv4_conf_default_rp_filter="2"
        ),
    )
    assert "rp_filter" not in loose_somewhere.stdout, (
        "a host where the loose mode wins was warned about strict filtering: the kernel "
        f"takes the MAX of the two and 2 is loose\n{loose_somewhere.stdout}"
    )


def test_the_kernel_is_read_after_the_daemon_that_sets_one_of_them(script: str) -> None:
    """Ordering, and it is a correctness property rather than a preference.

    ``net.ipv4.ip_forward`` is 0 on a host that has never run docker, and the daemon sets
    it to 1 at every start. A check placed before section 2 would therefore refuse every
    fresh host — the exact case this script exists for — for a fault it does not have.
    """
    call = re.search(r"^kernel_preconditions$", script, re.M)
    assert call, "nothing in the run checks the kernel settings a node's traffic needs"
    assert script.index(WHERE_THE_HOST_IS_FIRST_TOUCHED) < call.start(), (
        "the kernel is read before the container runtime is installed, so a host that has "
        "never had docker is refused for a setting docker itself would have set"
    )
    daemon = re.search(r"^as_root docker version --format", script, re.M)
    assert daemon and daemon.start() < call.start(), (
        "the kernel is read before the daemon is known to answer, so ip_forward is read "
        "at a moment when nothing has set it"
    )
    ready = re.search(r'^say "ready: docker', script, re.M)
    assert ready and call.start() < ready.start(), (
        "the kernel is read after the run has already reported success"
    )


def test_it_reads_kernel_settings_and_writes_none(script: str) -> None:
    """Section E of the header, still true: it does not tune the kernel.

    The distinction M19 turns on is that "does not tune" and "does not check" are
    different promises. So a write is forbidden and a read is not — and the refusal above
    NAMES the write for the operator to run, which is why this is anchored on a command
    at the start of a line rather than on the string appearing anywhere. Same shape, and
    the same reason, as the ``ssh-keygen`` assertion further up this file.
    """
    for setter in (r"sysctl -w", r"sysctl -p", r"sysctl [^\n-]", r"tee[^\n]*/proc/sys"):
        assert not re.search(rf"^\s*(?:as_root )?{setter}", script, re.M), (
            f"the script writes a kernel setting ({setter!r}) — it reads them and refuses, "
            "and tuning a host's kernel belongs to whoever owns the host"
        )
    assert re.search(r"^\s*sysctl -n ", script, re.M), "nothing reads a kernel setting"
    assert re.search(r"not tune the kernel", script, re.I), (
        "the header no longer states the boundary the reads above stay inside"
    )
